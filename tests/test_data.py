"""Aineiston eheystestit: docs/data/*.json ja .ics ovat sitä, mitä sivu odottaa.

Ajetaan joka pushilla (test.yml) ja jokaisen päivitysajon lopuksi ennen committia (update.yml),
jotta rikkinäinen aineisto ei koskaan päädy julkaistavaksi. Ei verkkoa, ei selainta – alle sekunti.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
LAJIT = {"laki", "asetus", "eu", "kirjelma", "kuuleminen"}
SCOPES = {"fi", "eu"}
EVENT_KINDS = {"lausunto", "he", "eduskunta", "hyvaksytty", "vahvistettu", "voimaan", "maaraaika", "muu", "ehdotus", "sopu",
               "parlamentti", "neuvosto", "julkaistu", "soveltaminen", "kanta"}
TENDER_STATUS = {"avoin", "päättynyt", "poistunut"}


@pytest.fixture(scope="module")
def settings():
    return yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def items():
    return json.loads((DATA / "items.json").read_text(encoding="utf-8"))["items"]


@pytest.fixture(scope="module")
def tenders():
    return json.loads((DATA / "hankinnat.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def meta():
    return json.loads((DATA / "meta.json").read_text(encoding="utf-8"))


# ---------- items.json (säädökset) ----------

def test_items_minimums(items, settings):
    mins = settings["sanity"]
    fi = sum(1 for i in items if i["scope"] == "fi" and not i["done"])
    eu = sum(1 for i in items if i["scope"] == "eu" and not i["done"])
    done = sum(1 for i in items if i["done"])
    assert fi >= mins["fi"], f"kansallisia vireillä vain {fi}"
    assert eu >= mins["eu"], f"EU-menettelyjä vain {eu}"
    assert done >= mins["done"], f"valmiita vain {done}"


def test_items_schema(items):
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids)), "päällekkäisiä tunnisteita"
    for it in items:
        assert re.match(r"^[A-Za-z0-9-]+$", it["id"]), it["id"]
        assert it["scope"] in SCOPES, it["id"]
        assert it.get("laji", "laki") in LAJIT, it["id"]
        assert it["title"].strip(), it["id"]
        assert isinstance(it["topics"], list) and it["topics"], it["id"]
        assert isinstance(it["status"], str) and it["status"], it["id"]
        assert isinstance(it["done"], bool), it["id"]
        assert isinstance(it["events"], list), it["id"]
        dates = []
        for e in it["events"]:
            assert DATE.match(e["date"]), (it["id"], e)
            if e.get("end"):
                assert DATE.match(e["end"]) and e["end"] >= e["date"], (it["id"], e)
            assert e.get("kind", "muu") in EVENT_KINDS, (it["id"], e.get("kind"))
            assert e.get("label", "").strip(), (it["id"], e)
            dates.append(e["date"])
        assert dates == sorted(dates), f"{it['id']}: vaiheet eivät ole aikajärjestyksessä"


def test_items_links_are_https(items):
    for it in items:
        for k, v in (it.get("links") or {}).items():
            if v:
                assert v.startswith("https://"), (it["id"], k, v)
        if it.get("source"):
            assert it["source"].startswith("https://"), it["id"]


def test_done_items_have_entry_date(items):
    missing = [i["id"] for i in items if i["done"] and not any(e["kind"] in ("voimaan", "soveltaminen", "vahvistettu") for e in i["events"])]
    # muutama poikkeus sallitaan (esim. EU-säädös, jolle Cellar ei ole vielä antanut päivää)
    assert len(missing) <= 0.05 * max(1, sum(1 for i in items if i["done"])), missing[:10]


# ---------- hankinnat.json (kilpailutukset) ----------

def test_tenders_minimum(tenders, settings):
    minimum = settings.get("hankinnat", {}).get("min_items", 100)
    open_rows = [t for t in tenders["items"] if t["status"] == "avoin"]
    assert len(open_rows) >= minimum, f"avoimia kilpailutuksia vain {len(open_rows)}"
    assert set(tenders["counts"]) >= {"avoinna", "dps", "sulkeutuu7", "eu"}
    assert tenders["topics"] and tenders["topics"][-1] == "Muut"


def test_tenders_schema(tenders):
    ids = [t["id"] for t in tenders["items"]]
    assert len(ids) == len(set(ids)), "päällekkäisiä kilpailutustunnisteita"
    topics = set(tenders["topics"])
    for t in tenders["items"]:
        assert t["id"].startswith("hk-"), t["id"]
        assert t["scope"] == "hankinta" and t["laji"] == "kilpailutus", t["id"]
        assert t["title"].strip(), t["id"]
        assert DATETIME.match(t["deadline"]), (t["id"], t["deadline"])
        assert t["deadlineKind"] in ("tarjous", "osallistumishakemus"), t["id"]
        assert t["status"] in TENDER_STATUS, t["id"]
        assert t["url"].startswith("https://www.hankintailmoitukset.fi/"), (t["id"], t["url"])
        assert t["topics"] and set(t["topics"]) <= topics, (t["id"], t["topics"])
        assert len(t.get("summary", "")) <= 500, t["id"]
        if t.get("published"):
            assert DATE.match(t["published"]), t["id"]
        if t.get("value") is not None:
            assert isinstance(t["value"], (int, float)) and t["value"] >= 0, t["id"]
        for k in ("docsUrl", "tedUrl"):
            if t.get(k):
                assert t[k].startswith("http"), (t["id"], k)


def test_tenders_sorted_by_deadline(tenders):
    dl = [t["deadline"] for t in tenders["items"]]
    assert dl == sorted(dl)


def test_closed_tenders_are_recent(tenders, settings):
    keep = int(settings.get("hankinnat", {}).get("keep_closed_days", 14))
    cutoff = (dt.date.today() - dt.timedelta(days=keep + 2)).isoformat()
    old = [t["id"] for t in tenders["items"] if t["status"] != "avoin" and t["deadline"][:10] < cutoff]
    assert not old, f"vanhoja päättyneitä ei siivottu: {old[:5]}"


# ---------- meta.json, changes.json, ics ----------

def test_meta(meta, items, tenders):
    gen = dt.datetime.fromisoformat(meta["generated"])
    assert gen.year >= 2026
    c = meta["counts"]
    for k in ("fi", "eu", "done", "lausunnolla", "changes7", "hankinnat", "hankinnat7"):
        assert isinstance(c[k], int) and c[k] >= 0, k
    assert c["fi"] == sum(1 for i in items if i["scope"] == "fi" and not i["done"])
    assert c["eu"] == sum(1 for i in items if i["scope"] == "eu" and not i["done"])
    assert c["done"] == sum(1 for i in items if i["done"])
    assert c["hankinnat"] == tenders["counts"]["avoinna"]
    assert len(meta["sources"]) >= 7
    assert meta["topics"][-1] == "Muut" and len(meta["topics"]) >= 10
    assert meta["hankintaTopics"] == tenders["topics"]
    assert set(meta["lajit"]) == LAJIT
    for name, h in (meta.get("health") or {}).items():
        assert isinstance(h.get("streak", 0), int), name


def test_changes(items):
    rows = json.loads((DATA / "changes.json").read_text(encoding="utf-8"))["changes"]
    for r in rows:
        assert DATE.match(r["date"]) and r["id"] and r["text"], r
        assert r["type"] in {"uusi", "tila", "vaihe", "siirto"}, r
    dates = [r["date"] for r in rows]
    assert dates == sorted(dates, reverse=True)


def test_ics():
    with open(DATA / "saadosseuranta.ics", encoding="utf-8", newline="") as f:  # newline="" säilyttää CRLF:n
        txt = f.read()
    assert txt.startswith("BEGIN:VCALENDAR") and txt.rstrip().endswith("END:VCALENDAR")
    events = txt.split("BEGIN:VEVENT")[1:]
    assert len(events) >= 20
    for ev in events:
        assert "UID:" in ev and "DTSTART;VALUE=DATE:" in ev and "SUMMARY:" in ev and "DTSTAMP:" in ev
    assert "\r\n" in txt
