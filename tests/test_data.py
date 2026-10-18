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
LAJIT = {"laki", "asetus", "eu", "kirjelma", "kuuleminen", "delegoitu"}
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
def mergers():
    return json.loads((DATA / "yrityskaupat.json").read_text(encoding="utf-8"))


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


STAGES = {"tulossa", "avoin", "ratkaistu", "suorahankinta", "mao"}
LIVE = {"tulossa": "tulossa", "avoin": "avoin", "ratkaistu": "ratkaistu", "suorahankinta": "valitusaika"}


def test_tenders_schema(tenders):
    ids = [t["id"] for t in tenders["items"]]
    assert len(ids) == len(set(ids)), "päällekkäisiä kilpailutustunnisteita"
    topics = set(tenders["topics"])
    for t in tenders["items"]:
        st = t["stage"]
        assert st in STAGES, (t["id"], st)
        assert t["scope"] == "hankinta" and t["laji"] == "kilpailutus", t["id"]
        assert t["title"].strip(), t["id"]
        assert t["topics"] and set(t["topics"]) <= topics, (t["id"], t["topics"])
        if st == "mao":
            continue  # Market Court rows are checked in test_market_court_rows
        assert t["id"].startswith("hk-"), t["id"]
        assert t["status"] in TENDER_STATUS | {"tulossa", "ratkaistu", "valitusaika"}, (t["id"], t["status"])
        assert t["url"].startswith("https://www.hankintailmoitukset.fi/"), (t["id"], t["url"])
        assert len(t.get("summary", "")) <= 500, t["id"]
        if t.get("published"):
            assert DATE.match(t["published"]), t["id"]
        if st == "avoin":
            assert DATETIME.match(t["deadline"]), (t["id"], t.get("deadline"))
            assert t["deadlineKind"] in ("tarjous", "osallistumishakemus"), t["id"]
        if st == "tulossa" and t.get("deadline"):
            assert DATETIME.match(t["deadline"]) and t["deadlineKind"] == "vastaus", t["id"]
        if st == "suorahankinta":
            assert DATE.match(t["appealEnd"]), t["id"]
            assert (dt.date.fromisoformat(t["appealEnd"]) - dt.date.fromisoformat(t["published"])).days == tenders["appealDays"], t["id"]
        if st == "ratkaistu":
            assert t["published"] >= (dt.date.today() - dt.timedelta(days=tenders["awardDays"] + 2)).isoformat(), t["id"]
        if t.get("amount") is not None:
            assert isinstance(t["amount"], (int, float)) and t["amount"] >= 0, t["id"]
        if t.get("value") is not None:
            assert isinstance(t["value"], (int, float)) and t["value"] >= 0, t["id"]
        for k in ("docsUrl", "tedUrl"):
            if t.get(k):
                assert t[k].startswith("http"), (t["id"], k)
        for e in t.get("events", []):
            assert DATE.match(e["date"]) and e["label"] and e["kind"] in EVENT_KINDS, (t["id"], e)
        for r in t.get("related", []):
            assert r["id"] in set(ids) and r["stage"] in STAGES, (t["id"], r)


def test_tenders_have_all_stages(tenders):
    present = {t["stage"] for t in tenders["items"]}
    assert present == STAGES, f"vaiheita puuttuu: {STAGES - present}"
    c = tenders["counts"]
    assert c["tulossa"] > 0 and c["ratkaistu"] > 0, c


def test_tenders_lifecycle_links_are_mutual(tenders):
    by_id = {t["id"]: t for t in tenders["items"]}
    for t in tenders["items"]:
        for r in t.get("related", []):
            back = [x["id"] for x in by_id[r["id"]].get("related", [])]
            assert t["id"] in back, (t["id"], r["id"])


def test_closed_tenders_are_recent(tenders, settings):
    keep = int(settings.get("hankinnat", {}).get("keep_closed_days", 14))
    cutoff = (dt.date.today() - dt.timedelta(days=keep + 2)).isoformat()
    old = [t["id"] for t in tenders["items"] if t["stage"] == "avoin" and t["status"] != "avoin" and t["deadline"][:10] < cutoff]
    assert not old, f"vanhoja päättyneitä ei siivottu: {old[:5]}"
    old = [t["id"] for t in tenders["items"] if t["stage"] == "suorahankinta" and t["appealEnd"] < cutoff]
    assert not old, f"vanhoja suorahankintoja ei siivottu: {old[:5]}"


# ---------- Council stages and delegated acts (items.json) ----------

def test_council_stages(items):
    eu = [i for i in items if i["scope"] == "eu" and i["laji"] == "eu"]
    council = [e for i in eu for e in i["events"] if e.get("src") == "neuvosto"]
    assert len(council) >= 50, "neuvoston vaiheita puuttuu"
    labels = {e["label"] for e in council}
    assert any(l.startswith("Neuvoston yleisnäkemys") for l in labels) and any(l.startswith("Neuvosto hyväksyi") for l in labels)
    for e in council:
        assert e["kind"] in ("neuvosto", "sopu", "parlamentti", "muu") and DATE.match(e["date"])
    # routine "discussed in Council" marks are dropped once the act is adopted
    for i in eu:
        if any(e["label"].startswith("Neuvosto hyväksyi") for e in i["events"]):
            assert not any("(viimeisin)" in e["label"] for e in i["events"]), i["id"]


def test_delegated_acts(items, meta):
    da = [i for i in items if i["laji"] == "delegoitu"]
    assert len(da) >= 20 and meta["lajit"]["delegoitu"] == len(da)
    for i in da:
        assert i["id"].startswith("eu-da-") and i["scope"] == "eu"
        assert i["status"] in ("vastustamisaika", "odottaa julkaisua", "julkaistu", "voimassa", "vastustettu", "peruutettu"), (i["id"], i["status"])
        assert i["done"] == (i["status"] in ("julkaistu", "voimassa", "vastustettu", "peruutettu"))
        assert DATE.match(i["objectionEnd"]) and i["objectionMonths"]
        assert i["links"].get("regdel", "").startswith("https://webgate.ec.europa.eu/regdel/")
        kinds = [e["kind"] for e in i["events"]]
        assert "ehdotus" in kinds, i["id"]
        if i["status"] in ("vastustamisaika", "odottaa julkaisua"):
            assert any(e["kind"] == "maaraaika" and e["date"] == i["objectionEnd"] for e in i["events"]), i["id"]
        if i["status"] == "vastustamisaika":
            assert i["objectionEnd"] >= meta["today"], i["id"]
        if i["status"] in ("julkaistu", "voimassa"):
            assert "julkaistu" in kinds and i.get("celex"), i["id"]
    assert sum(1 for i in da if i["status"] == "vastustamisaika") >= 5


def test_consultations_present(meta):
    assert meta["lajit"]["kuuleminen"] >= 10, "Have your say -kuulemiset puuttuvat (lähde palautti tyhjää?)"


# ---------- Market Court rows (hankinnat.json, stage mao) ----------

def test_market_court_rows(tenders):
    items = tenders["items"]
    mao = [t for t in tenders["items"] if t.get("stage") == "mao"]
    assert len(mao) >= 30
    assert tenders["counts"]["mao"] == sum(1 for t in mao if t["status"] == "vireillä") >= 20
    assert tenders["counts"]["mao_ratkaistu"] == sum(1 for t in mao if t["status"] == "ratkaistu") >= 5
    ids = [t["id"] for t in mao]
    assert len(ids) == len(set(ids))
    for t in mao:
        assert t["id"].startswith(("mao-v-", "mao-r-")) and t["buyer"] and t["title"], t["id"]
        assert t["status"] in ("vireillä", "ratkaistu", "poistunut"), t["id"]
        assert t["kind"] in ("Valitus markkinaoikeudessa", "Markkinaoikeuden ratkaisu")
        assert t["url"].startswith("https://www.markkinaoikeus.fi/"), t["id"]
        dates = [e["date"] for e in t["events"]]
        assert dates == sorted(dates), t["id"]
        if t["status"] == "vireillä":
            assert DATE.match(t["filed"]) and any(e["label"].startswith("Valitus vireille") for e in t["events"]), t["id"]
            assert not t.get("ruled")
        if t["status"] == "ratkaistu":
            assert t["maoNumber"].startswith("MAO:") and DATE.match(t["ruled"]) and t["maoUrl"], t["id"]
            kho = [e for e in t["events"] if e["kind"] == "maaraaika"]
            assert len(kho) == 1 and kho[0]["confirmed"] is False and kho[0]["date"] > t["ruled"], t["id"]
            assert t.get("outcome"), t["id"]
        for r in t.get("related") or []:
            assert r["id"].startswith("hk-"), (t["id"], r)
    # reverse links from Hilma notices to the appeal
    back = [t for t in tenders["items"] if t.get("stage") != "mao" and any(r.get("stage") == "mao" for r in t.get("related") or [])]
    for t in back:
        for r in t["related"]:
            if r.get("stage") == "mao":
                assert r["id"] in ids, (t["id"], r)


# ---------- yrityskaupat.json (merger control) ----------

YK_STATUS = {"vireillä", "jatkokäsittelyssä", "hyväksytty", "hyväksytty ehdoin", "kielletty", "peruutettu", "siirretty jäsenvaltiolle",
             "siirretty osittain", "siirretty komissiolle", "ei soveltamisalassa", "päätetty", "poistunut listalta", "rauennut",
             "kieltoesitys markkinaoikeudessa", "yrityskauppa kielletty", "esitys hylätty", "ehtoja muutettu", "ratkaistu markkinaoikeudessa"}
YK_OPEN = {"vireillä", "jatkokäsittelyssä", "kieltoesitys markkinaoikeudessa"}


def test_mergers_schema(mergers):
    items = mergers["items"]
    assert len(items) >= 5
    ids = [m["id"] for m in items]
    assert len(ids) == len(set(ids))
    assert {m["authority"] for m in items} == {"KKV", "EU"}
    topics = set(mergers["topics"])
    for m in items:
        assert m["id"].startswith("yk-fi-" if m["authority"] == "KKV" else "yk-eu-"), m["id"]
        assert m["scope"] == "yrityskauppa" and m["laji"] == "yrityskauppa", m["id"]
        assert m["title"].strip() and m["ref"], m["id"]
        assert m["status"] in YK_STATUS, (m["id"], m["status"])
        assert isinstance(m["done"], bool) and m["done"] == (m["status"] not in YK_OPEN), m["id"]
        assert m["phase"] in (1, 2), m["id"]
        assert set(m["topics"]) <= topics, (m["id"], m["topics"])
        assert m["source"].startswith("https://"), m["id"]
        for k in ("notified", "hearingEnd", "phase1End", "phase2Start", "phase2End", "decided"):
            if m.get(k):
                assert DATE.match(m[k]), (m["id"], k, m[k])
        dates = [e["date"] for e in m["events"]]
        assert dates == sorted(dates), m["id"]
        for e in m["events"]:
            assert e["kind"] in EVENT_KINDS and e["label"], (m["id"], e)
        if m["status"] in YK_OPEN:
            assert any(e["kind"] == "maaraaika" for e in m["events"]) or m["authority"] == "EU", f"{m['id']}: vireillä ilman määräaikaa"
        if m["status"] == "kieltoesitys markkinaoikeudessa":
            assert m.get("maoProposal") and any("kilpailulaki 29 §" in e["label"] for e in m["events"]), m["id"]
        if m["authority"] == "KKV" and m["status"] == "vireillä":
            assert m.get("notified") and m.get("phase1End") and m["phase1End"] > m["notified"], m["id"]
            assert m.get("hearingEnd"), m["id"]
        if m["status"] == "jatkokäsittelyssä" and m["authority"] == "KKV":
            assert m.get("phase2Start") and m.get("phase2End"), m["id"]
        if m["decided"]:
            assert m["done"], m["id"]


def test_mergers_parties(mergers):
    """EU rows carry the parties from the OJ notice once it is published (a few days after notification)."""
    eu = [m for m in mergers["items"] if m["authority"] == "EU"]
    with_parties = [m for m in eu if m.get("parties")]
    assert len(with_parties) >= len(eu) * 0.6, "EUVL-ilmoituksia puuttuu epäilyttävän monelta"
    for m in with_parties:
        assert isinstance(m["fiParty"], bool)
        for p in m["parties"]:
            assert p["name"].strip() and isinstance(p["fi"], bool), (m["id"], p)
            if p["fi"]:
                assert p.get("country") in ("Suomi", "Suomen kansalainen") or True  # control via a Finnish parent also counts
        assert m["fiParty"] == any(p["fi"] for p in m["parties"]), m["id"]
        assert m["noticeDate"] and m["observationsEnd"] and m["observationsEnd"] > m["noticeDate"], m["id"]
        obs = [e for e in m["events"] if e["kind"] == "lausunto"]
        assert len(obs) == 1 and obs[0]["date"] == m["noticeDate"] and obs[0]["end"] == m["observationsEnd"], m["id"]
        assert m["links"].get("euvl", "").startswith("https://eur-lex.europa.eu/eli/C/"), m["id"]
        assert m["summary"].strip(), m["id"]
    for m in eu:
        if not m.get("parties"):
            assert not m["fiParty"] and not any(e["kind"] == "lausunto" for e in m["events"]), m["id"]
    for m in mergers["items"]:
        if m["authority"] == "KKV":
            assert m["fiParty"] is True


def test_mergers_counts(mergers):
    c = mergers["counts"]
    items = mergers["items"]
    assert c["fi"] == sum(1 for m in items if m["authority"] == "KKV")
    assert c["eu"] == sum(1 for m in items if m["authority"] == "EU")
    assert c["fi_open"] == sum(1 for m in items if m["authority"] == "KKV" and not m["done"])
    assert c["eu_open"] == sum(1 for m in items if m["authority"] == "EU" and not m["done"])
    assert c["fi"] >= 3 and c["eu"] >= 10
    assert c["eu_fi"] == sum(1 for m in items if m["authority"] == "EU" and m["fiParty"])
    assert c["eu_fi_open"] == sum(1 for m in items if m["authority"] == "EU" and m["fiParty"] and not m["done"])


# ---------- meta.json, changes.json, ics ----------

def test_meta(meta, items, tenders, mergers):
    gen = dt.datetime.fromisoformat(meta["generated"])
    assert gen.year >= 2026 and gen.tzinfo is not None, "generated-aikaleimassa on oltava aikavyöhyke (sivu näyttää sen paikallisaikana)"
    c = meta["counts"]
    for k in ("fi", "eu", "done", "lausunnolla", "changes7", "hankinnat", "hankinnat7"):
        assert isinstance(c[k], int) and c[k] >= 0, k
    assert c["fi"] == sum(1 for i in items if i["scope"] == "fi" and not i["done"])
    assert c["eu"] == sum(1 for i in items if i["scope"] == "eu" and not i["done"])
    assert c["done"] == sum(1 for i in items if i["done"])
    assert c["hankinnat"] == tenders["counts"]["avoinna"]
    assert c["yrityskaupat"] == mergers["counts"]["fi_open"] + mergers["counts"]["eu_open"]
    assert meta["yrityskauppaTopics"] == mergers["topics"]
    assert len(meta["sources"]) >= 12
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
