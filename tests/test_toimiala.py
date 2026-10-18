"""Toimialakerroksen jäsentimet ja rakentaja tallennetuilla näytteillä (tests/samples/toimiala/).

Ei verkkoa: jokainen jäsennin saa probe-ajossa 18.10.2026 tallennetun, olennaiseen osaan karsitun sivun,
ja hakijat ajetaan valeasiakkaalla, joka palauttaa samat näytteet. Päivä on jäädytetty näytteiden
tallennuspäivään, jotta tilat (lausunnolla/päättynyt, annettu/voimassa) eivät riipu ajohetkestä.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_toimiala as bt  # noqa: E402
import fetch_toimiala as ft  # noqa: E402

S = ROOT / "tests" / "samples" / "toimiala"
FROZEN = dt.date(2026, 10, 18)
ISO = r"^\d{4}-\d{2}-\d{2}$"


def rd(name: str) -> str:
    return (S / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    monkeypatch.setattr(ft, "TODAY", FROZEN)
    monkeypatch.setattr(bt, "TODAY", FROZEN)


@pytest.fixture(scope="module")
def cfg_all():
    return yaml.safe_load((ROOT / "config" / "toimiala.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def topics():
    return yaml.safe_load((ROOT / "config" / "topics.yaml").read_text(encoding="utf-8"))["topics"]


# ---------- config ----------

def test_config_shape(cfg_all, topics):
    srcs = cfg_all["sources"]
    assert {"fiva_tiedotteet", "fiva_lausuntopyynnot", "esma_consultations", "eba_consultations", "eiopa_consultations",
            "edpb_consultations", "edpb_guidelines", "vero_ohjeet", "vero_kvl", "traficom_maaraykset", "tsv_finlex"} <= set(srcs)
    for name, s in srcs.items():
        assert s["scope"] in ("fi", "eu"), name
        assert s["laji"] in ("kuuleminen", "ohje", "ratkaisu"), name
        assert s["authority"], name
        for t in s["aihealueet"]:
            assert t in topics, f"{name}: aihealue {t!r} puuttuu topics.yaml:stä"
        if s["enabled"]:
            assert name in ft.RUNNERS, f"{name}: ei hakijaa"
    for blocked in ("energiavirasto", "valvira", "fimea", "tukes", "lausuntopalvelu"):
        assert srcs[blocked]["enabled"] is False


# ---------- Finanssivalvonta ----------

def test_fiva_listing():
    rows = ft.parse_fiva_listing(rd("fiva_valvottavatiedotteet.html"))
    assert len(rows) == 19
    assert rows[0]["date"] == "2026-10-13"  # datetime attribute starts with a newline in the source
    assert rows[0]["title"] == "Kiinnitysluottopankkitoimintaa koskevien säännösten noudattamisessa puutteita"
    assert rows[0]["url"].startswith("https://www.finanssivalvonta.fi/tiedotteet-ja-julkaisut/valvottavatiedotteet/2026/")
    assert rows[12]["date"] == "2026-01-19" and rows[12]["title"].startswith("Finanssivalvonta pyytää lausuntoa")
    assert rows[13]["type"] == "Lehdistötiedote" and rows[13]["date"] == "2026-10-12"


@pytest.mark.parametrize("title,kind", [
    ("Finanssivalvonta pyytää lausuntoa määräys- ja ohjeluonnoksista", "Lausuntopyyntö"),
    ("Määräykset ja ohjeet 3/2016 on korvattu uusilla määräyksillä ja ohjeilla 1/2026", "Määräykset ja ohjeet"),
    ("Muutoksia määräyksiin ja ohjeisiin 10/2012", "Määräykset ja ohjeet"),
    ("Pareto Securities Ab:lle 115 000 euron seuraamusmaksu kaupparaportoinnin laiminlyönnistä", "Hallinnollinen seuraamus"),
    ("Helsingin hallinto-oikeus hyväksyi Alexandria Group Oyj:n valituksen Finanssivalvonnan määräämästä seuraamusmaksusta", "Hallinnollinen seuraamus"),
    ("Seuraamus- ja rikemaksun mitoittamisen periaatteet päivitetty", "Ohje"),
    ("EBAn ohjeet ympäristöskenaarioanalyysista – soveltaminen alkaa 1.1.2027", "EU-valvontaviranomaisen ohjeet"),
    ("Teema-arvio kuluttajien luottokelpoisuuden arvioinnista", None),
    ("Makrovakauspäätös: Asuntolainakatto nousee 95 prosenttiin", None),
])
def test_fiva_kind(title, kind):
    assert ft.fiva_kind(title) == kind


def test_fiva_mok_refs():
    assert ft.mok_refs("Määräykset ja ohjeet 3/2016 on korvattu uusilla määräyksillä ja ohjeilla 1/2026") == ("1/2026", "3/2016")
    assert ft.mok_refs("Muutoksia määräyksiin ja ohjeisiin 10/2012") == ("10/2012", None)
    assert ft.mok_refs("DORA-asetuksesta aiheutuvat muutokset Määräys- ja ohjekokoelmiin") == (None, None)


def test_fiva_tiedote_detail_deadline():
    d = ft.parse_fiva_tiedote(rd("fiva_valvottavatiedote.html"))
    assert d["number"] == "3/2026" and d["date"] == "2026-01-19" and d["type"] == "Valvottavatiedote"
    assert d["deadline"] == "2026-02-13"  # "Lausuntoaika päättyy 13.2.2026* klo 23.59."
    assert d["title"].startswith("Finanssivalvonta pyytää lausuntoa")
    assert "8/2014 rahoitussektorin operatiivisten riskien hallinta" in d["summary"] and len(d["summary"]) <= 500
    assert d["tags"] == ["lausuntopyynnöt", "DORA-asetus", "määräykset ja ohjeet"]
    assert "proposalId=f4bbd1a2-f1c2-4072-b68d-6153cc1053b5" in d["lausuntopalvelu"]


def test_fiva_lausuntopyynnot():
    rows = ft.parse_fiva_lausuntopyynnot(rd("fiva_lausuntopyynnot.html"))
    assert len(rows) == 8
    assert rows[0]["date"] == "2026-06-04" and rows[0]["guid"] == "723a95f7-66a4-4a8a-b8a2-2e66e71d0397"
    assert rows[0]["title"].startswith("Muutoksia työeläkealaa koskeviin")
    assert rows[2]["guid"] == "f4bbd1a2-f1c2-4072-b68d-6153cc1053b5" and rows[2]["date"] == "2026-01-16"
    assert "&amp;" not in rows[6]["url"]  # html entities unescaped in the link


# ---------- ESMA / EBA / EIOPA / EDPB ----------

def test_esma():
    rows = ft.parse_esma(rd("esma_consultations.html"))
    assert len(rows) == 5
    assert rows[0]["start"] == "2026-10-09" and rows[0]["end"] == "2027-01-15"
    assert rows[0]["url"] == "https://www.esma.europa.eu/press-news/consultations/call-evidence-ccp-collateral-tokenisation"
    assert rows[0]["ref"] == "ESMA91-1505572268-4934" and rows[0]["section"] == "CCP"
    assert ft.eu_kind(rows[0]["title"]) == "Call for evidence" and ft.eu_kind(rows[1]["title"]) == "Consultation paper"
    assert rows[1]["ref"] == "ESMA32-753890202-3085"


def test_eba_listing_dates():
    rows = ft.parse_eba_listing(rd("eba_consultations.html"))
    assert len(rows) == 4
    assert rows[0]["start"] == "2026-09-25" and rows[0]["end"] == "2027-01-04"  # "2026 - 2027": deadline takes the second year
    assert rows[0]["ref"] == "EBA/CP/2026/19"
    assert rows[1]["start"] == "2026-08-26" and rows[1]["end"] == "2026-12-31"  # single year
    assert rows[1]["url"].endswith("/consultation-draft-rts-operational-risk-management-framework")


def test_eba_detail():
    d = ft.parse_eba_detail(rd("eba_consultation_item.html"))
    assert d["deadline"] == "2026-12-31" and d["ref"] == "EBA/CP/2026/18" and d["status"] == "open"
    assert d["period"] == "26 AUGUST - 31 DECEMBER 2026"


def test_eiopa_rss_and_listing():
    feed = ft.parse_eiopa_rss(rd("eiopa_consultations_rss.xml"))
    assert len(feed) == 5
    assert feed[0]["date"] == "2026-10-13" and feed[0]["topics"] == ["Stress test"] and feed[0]["type"] == "Consultation"
    assert feed[1]["url"].endswith("/consultation-draft-supervisory-statement-ibip-sales-processes_en")
    li = ft.parse_eiopa_listing(rd("eiopa_consultations.html"))
    assert len(li) == 3
    by_url = {e["url"]: e for e in li}
    e = by_url[feed[1]["url"]]
    assert e["status"] == "open" and e["start"] == "2026-10-08" and e["deadline"] == "2027-01-04"
    assert by_url[feed[0]["url"]]["deadline"] == "2026-10-28"


def test_edpb_consultations():
    rows = ft.parse_edpb_consultations(rd("edpb_consultations.html"))
    assert len(rows) == 6
    assert rows[0]["status"] == "open" and rows[0]["start"] == "2026-07-08" and rows[0]["end"] == "2026-10-30"
    assert rows[0]["title"] == "Guidelines 02/2026 on Anonymisation"
    assert rows[2]["end"] == "2026-11-13"
    assert rows[3]["status"] == "closed" and rows[3]["end"] == "2026-08-05"  # closed cards have no status span
    assert ft.edpb_ref(rows[2]["title"]) == "Guidelines 4/2026"  # leading zero normalised


def test_edpb_documents():
    docs = ft.parse_edpb_documents(rd("edpb_documents_guidelines.html"))
    assert len(docs) == 3
    assert docs[0]["date"] == "2026-09-17" and docs[0]["type"] == "Guideline" and docs[0]["topics"] == ["GDPR enforcement", "Fines"]
    assert docs[1]["title"] == "Guidelines 3/2025 on the interplay between the DSA and the GDPR"
    assert docs[2]["date"] == "2026-07-07"


# ---------- Verohallinto ----------

def test_vero_hits():
    hits = ft.vero_hits(json.loads(rd("vero_api_ohjeet.json")))
    assert len(hits) == 12
    assert hits[0]["contentId"] == 376606 and hits[0]["date"] == "2026-09-30"
    assert hits[0]["url"].startswith("https://www.vero.fi/syventavat-vero-ohjeet/ohje-hakusivu/48546/")
    assert "Eläke" in hits[0]["tags"]
    kvl = ft.vero_hits(json.loads(rd("vero_api_kvl.json")))
    assert kvl[0]["title"] == "KVL:2026/29" and kvl[0]["glossary"][0] == "Arvonlisävero" and kvl[0]["date"] == "2026-10-14"


def test_vero_ohje_detail():
    d = ft.parse_vero_ohje(rd("vero_ohje_item.html"))
    assert d["date"] == "2026-09-25"  # antopäivä, not the site's publication date 30.9.2026
    assert d["diary"] == "VH/5246/00.01.00/2026" and d["replaces"] == "VH/1659/00.01.00/2024"
    assert d["validFrom"] == "2026-09-25" and "validTo" not in d
    assert d["pageId"] == 376606 and d["summary"].startswith("Tässä ohjeessa käsitellään eläketulojen") and len(d["summary"]) <= 500


def test_vero_kvl_detail():
    d = ft.parse_vero_kvl(rd("vero_kvl_item.html"))
    assert d["ref"] == "KVL:2026/29" and d["date"] == "2026-09-23" and d["diary"] == "VH/2079/02.05.04/2026"
    assert d["status"] == "ei lainvoimainen"
    assert d["validity"] == "Ennakkoratkaisu ajalle 23.9.2026–31.12.2027."
    assert d["statutes"].startswith("Arvonlisäverolaki 1 § 1 mom 1 kohta")
    assert "Ennakkoratkaisu ajalle" not in d["summary"] and d["summary"].startswith("Asiassa oli ratkaistavana")
    assert d["keywords"] == ["Arvonlisävero", "Liikuntapalvelu", "Ulkoilmauimala", "Alennettu verokanta", "Palvelukokonaisuus"]


def test_vero_kvl_kho_status():
    d = ft.parse_vero_kvl(rd("vero_kvl_item_kho.html"))
    assert d["ref"] == "KVL:2024/45" and d["date"] == "2024-12-16"
    assert d["status"] == "KHO 21.8.2025 (KHO 2025:59): ei muutosta"
    assert d["kho"] == {"date": "2025-08-21", "taltio": "1732", "ref": "KHO 2025:59", "outcome": "ei muutosta"}
    assert d["validity"] == "Ennakkoratkaisu verovuosille 2024 ja 2025."
    assert d["keywords"][0] == "Rajoitetusti verovelvollisen tulon verotus"  # newline-separated list normalised


# ---------- Traficom / Finlex ----------

def test_traficom(cfg_all):
    rows = ft.parse_traficom(json.loads(rd("traficom_search.json")), cfg_all["sources"]["traficom_maaraykset"])
    assert len(rows) == 10
    by_id = {r["id"]: r for r in rows}
    m = by_id["traficom-893577"]
    assert m["kind"] == "Määräys" and m["date"] == "2026-09-30" and m["validFrom"] == "2026-09-29" and m["status"] == "voimassa"
    assert m["diary"] == "TRAFICOM/893577/03.04.03.00/2025" and m["finlexUrl"].startswith("https://www.finlex.fi/")
    assert by_id["traficom-881368"]["status"] == "annettu" and by_id["traficom-881368"]["validFrom"] == "2027-01-01"  # in force later
    h = by_id["traficom-273851"]
    assert h["kind"] == "Määräyshankepäätös" and h["status"] == "luonnos" and "validFrom" not in h
    assert h["plannedText"] == "keväällä 2027" and h["summary"].startswith("Määräyshankkeen tavoitteena")


def test_tsv_finlex():
    rows = ft.parse_tsv(rd("finlex_tsv.html"))
    assert len(rows) == 20 and len({r["url"] for r in rows}) == 20  # RSC payload repeats items; deduplicated by href
    assert rows[0]["date"] == "2026-10-12" and rows[0]["url"] == "https://www.finlex.fi/fi/viranomaiset/tietosuojavaltuutettu/2026/36"
    assert rows[1]["title"] == "Potilastietojen antamista koskevan määräyksen noudattamatta jättäminen"  # "\n" + indent inside the RSC string
    assert all("\\" not in r["title"] for r in rows)


# ---------- helpers ----------

def test_date_helpers():
    assert ft.iso_uk("15/01/2027") == "2027-01-15"
    assert ft.iso_en("26 AUGUST 2026") == "2026-08-26" and ft.iso_en("08 July 2026") == "2026-07-08"
    assert ft.iso_fi_long("11. tammikuuta 2027") == "2027-01-11" and ft.iso_fi_long("1.1.2027") == "2027-01-01"
    assert ft.en_day_month_year("4", "Jan", "2027") == "2027-01-04"
    assert ft.iso_rfc822("Tue, 13 Oct 2026 10:40:43 +0200") == "2026-10-13"
    assert ft.trim("A" * 30 + ". " + "x" * 600, 60) == "A" * 30 + "."  # whole sentences when the break is past 40 %
    assert len(ft.trim("x" * 600, 60)) == 60 and ft.trim("x" * 600, 60).endswith("…")


def test_prune_keeps_open_and_recent(cfg_all):
    rows = [
        {"id": "a", "laji": "kuuleminen", "date": "2026-01-19", "deadline": "2026-02-13"},   # closed long ago -> out
        {"id": "b", "laji": "kuuleminen", "date": "2026-08-26", "deadline": "2026-12-31"},   # open -> in
        {"id": "c", "laji": "kuuleminen", "date": "2026-10-01"},                            # no deadline, recent -> in
        {"id": "d", "laji": "ohje", "date": "2026-05-01"},                                  # older than 120 d -> out
        {"id": "e", "laji": "ohje", "date": "2026-09-30"},                                  # in
    ]
    kept = {r["id"] for r in ft.prune(rows, {}, cfg_all["defaults"])}
    assert kept == {"b", "c", "e"}


# ---------- runners with a fake client, then the builder ----------

class FakeClient:
    """Serves the saved samples by URL fragment; any other URL raises like a failed detail fetch."""

    def __init__(self, mapping: dict[str, str]):
        self.mapping, self.requests, self.urls = mapping, 0, []

    def set_delay(self, url, seconds):
        pass

    def _find(self, url):
        self.requests += 1
        self.urls.append(url)
        for frag, name in self.mapping.items():
            # a fragment ending in "/" is a listing page and must end the URL, so detail pages under it do not match it
            if (url.rstrip("/").endswith(frag.rstrip("/")) if frag.endswith("/") else frag in url):
                return rd(name)
        raise RuntimeError(f"ei näytettä: {url}")

    def text(self, url, **kw):
        return self._find(url)

    def json(self, url, **kw):
        return json.loads(self._find(url))


@pytest.fixture()
def fetched(cfg_all):
    # long keep windows so that the January 2026 samples are still read in full; the builder test prunes with the real config
    defaults = {**cfg_all["defaults"], "keep_days": 400, "consultation_grace_days": 400}
    src = {k: {**v, "keep_days": 400} for k, v in cfg_all["sources"].items()}
    client = FakeClient({
        "valvottavatiedotteet/2026/finanssivalvonta-pyytaa-lausuntoa": "fiva_valvottavatiedote.html",
        "tiedotteet-ja-julkaisut/valvottavatiedotteet/": "fiva_valvottavatiedotteet.html",
        "tiedotteet-ja-julkaisut/lehdistotiedotteet/": "fiva_valvottavatiedotteet.html",
        "saantely/lausuntopyynnot/": "fiva_lausuntopyynnot.html",
        "esma.europa.eu/press-news/consultations": "esma_consultations.html",
        "consultation-draft-rts-operational-risk-management-framework": "eba_consultation_item.html",
        "eba.europa.eu/publications-and-media/consultations": "eba_consultations.html",
        "node/4764/rss_en": "eiopa_consultations_rss.xml",
        "browse/consultations-and-surveys_en": "eiopa_consultations.html",
        "public-consultations_en": "edpb_consultations.html",
        "edpb.europa.eu/documents_en": "edpb_documents_guidelines.html",
        "kvl0292026": "vero_kvl_item.html",
        "elaketulojen-verotus-kansainvalisissa-tilanteissa7": "vero_ohje_item.html",
        "traficom.fi/search": "traficom_search.json",
        "tietosuojavaltuutettu/2026": "finlex_tsv.html",
    })

    class VeroClient(FakeClient):
        def json(self, url, **kw):
            self.requests += 1
            return json.loads(rd("vero_api_kvl.json" if kw.get("params", {}).get("typeId") == 10 else "vero_api_ohjeet.json"))

    vero = VeroClient(client.mapping)
    rows_all: dict[str, list] = {}
    for name in ft.ORDER:  # unpruned, so the January lausuntopyyntö join can be checked; the builder prunes by itself
        c = vero if name.startswith("vero_") else client
        rows_all[name] = ft.RUNNERS[name](src[name], [], rows_all, c, defaults)
    return rows_all, client


def test_runners(fetched):
    rows_all, client = fetched
    fiva = {r["id"]: r for r in rows_all["fiva_tiedotteet"]}
    assert "fiva-3-2026" in fiva  # id switched from slug to the running number once the page was read
    lp = fiva["fiva-3-2026"]
    assert lp["laji"] == "kuuleminen" and lp["deadline"] == "2026-02-13" and lp["keywords"] == ["lausuntopyynnöt", "DORA-asetus", "määräykset ja ohjeet"]
    pending = [r for r in rows_all["fiva_tiedotteet"] if r.get("detailPending")]
    assert pending and all(r["id"].startswith("fiva-") for r in pending)  # unreachable detail pages are retried next run
    # lausuntopyynnöt row borrows the deadline from the matching tiedote (same proposalId)
    lps = {r["id"]: r for r in rows_all["fiva_lausuntopyynnot"]}
    row = lps["fiva-lp-f4bbd1a2"]
    assert row["deadline"] == "2026-02-13" and row["matchedId"] == "fiva-3-2026" and "deadlineUnknown" not in row
    assert lps["fiva-lp-723a95f7"]["deadlineUnknown"] is True
    # EBA: the one detail page confirms the deadline; the other cards wait for their turn
    eba = {r["id"]: r for r in rows_all["eba_consultations"]}
    assert eba["eba-cp-2026-18"]["deadline"] == "2026-12-31" and eba["eba-cp-2026-18"]["checked"] == FROZEN.isoformat()
    assert eba["eba-cp-2026-19"]["deadline"] == "2027-01-04" and eba["eba-cp-2026-19"]["detailPending"] is True
    assert sum(1 for u in client.urls if "eba.europa.eu" in u) <= 1 + 5
    # EIOPA: deadline from the listing, no detail fetch needed for those rows
    eiopa = {r["id"]: r for r in rows_all["eiopa_consultations"]}
    assert eiopa["eiopa-consultation-draft-supervisory-statement-ibip-sales-processes"]["deadline"] == "2027-01-04"
    # EDPB guideline under consultation is a draft
    gl = {r["ref"]: r for r in rows_all["edpb_guidelines"]}
    assert gl["Guidelines 4/2026"]["status"] == "luonnos" and gl["Guidelines 3/2025"]["status"] == "annettu"
    # Vero: antopäivä and diary from the detail page
    ohje = {r["id"]: r for r in rows_all["vero_ohjeet"]}["vero-376606"]
    assert ohje["date"] == "2026-09-25" and ohje["diary"] == "VH/5246/00.01.00/2026" and ohje["replaces"] == "VH/1659/00.01.00/2024"
    kvl = {r["id"]: r for r in rows_all["vero_kvl"]}["kvl-2026-29"]
    assert kvl["date"] == "2026-09-23" and kvl["status"] == "ei lainvoimainen" and kvl["ref"] == "KVL:2026/29"
    assert {r["id"] for r in rows_all["tsv_finlex"]} >= {"tsv-2026-36", "tsv-2026-35"}
    assert all(r.get("date") and r.get("url") and r.get("title") and r.get("authority") for rows in rows_all.values() for r in rows)


def test_builder_shape(fetched, tmp_path, monkeypatch, topics):
    rows_all, _ = fetched
    (tmp_path / "toimiala.json").write_text(json.dumps({"fetched": "2026-10-18T10:00:00Z", "rows": rows_all, "health": {}}), encoding="utf-8")
    monkeypatch.setattr(bt, "CACHE_DIR", tmp_path)
    out = bt.build_toimiala(topics, {"ratkaisut": {"keep_days": 120}})
    items, rulings = out["items"], out["rulings"]
    assert items and rulings
    import re
    for it in items:
        assert it["scope"] in ("fi", "eu") and it["laji"] in ("kuuleminen", "ohje") and it["authority"] and it["kind"] and it["ref"]
        assert it["id"].startswith(f"{it['scope']}-toim-") and it["done"] is False and it["topics"] and "Muut" not in it["topics"]
        assert it["links"] and it["source"] and len(it["summary"]) <= 500
        for e in it["events"]:
            assert re.match(ISO, e["date"]) and e["label"] and e["kind"] in ("lausunto", "julkaistu", "voimaan", "soveltaminen", "muu")
            if e.get("end"):
                assert re.match(ISO, e["end"]) and e["end"] >= e["date"]
        if it["laji"] == "kuuleminen":
            assert it["status"] in ("lausunnolla", "tulossa", "päättynyt")
        else:
            assert it["status"] in ("annettu", "voimassa", "luonnos")
    by_id = {i["id"]: i for i in items}
    eba = by_id["eu-toim-eba-cp-2026-18"]
    assert eba["status"] == "lausunnolla" and eba["events"] == [{"date": "2026-08-26", "end": "2026-12-31", "label": "Palauteaika", "kind": "lausunto",
                                                                  "confirmed": True, "url": eba["source"]}]
    assert eba["ref"] == "EBA/CP/2026/18" and eba["authority"] == "EBA" and "Yhtiö ja rahoitus" in eba["topics"]
    hanke = by_id["fi-toim-traficom-273851"]
    assert hanke["status"] == "luonnos" and hanke["events"][0]["label"] == "Määräyshankepäätös annettu" and hanke["plannedText"] == "keväällä 2027"
    maarays = by_id["fi-toim-traficom-881368"]
    assert [e["kind"] for e in maarays["events"]] == ["julkaistu", "voimaan"] and maarays["events"][1]["date"] == "2027-01-01"
    ohje = by_id["fi-toim-vero-376606"]
    assert ohje["status"] == "voimassa" and ohje["diary"] == "VH/5246/00.01.00/2026" and ohje["replaces"] == "VH/1659/00.01.00/2024"
    assert "Verotus" in ohje["topics"] and ohje["events"][0]["label"] == "Annettu"
    gl = next(i for i in items if i["laji"] == "ohje" and i.get("ref") == "Guidelines 4/2026")
    assert gl["id"].startswith("eu-toim-edpb-gl-guidelines-042026") and gl["status"] == "luonnos" and gl["authority"] == "EDPB" and "Tietosuoja ja digi" in gl["topics"]
    # a lausuntopyyntö whose deadline passed in February is pruned, the matched tiedote row is not duplicated
    assert not any(i["id"].startswith("fi-toim-fiva-lp-f4bbd1a2") or i["id"] == "fi-toim-fiva-3-2026" for i in items)
    assert all(i["deadlineUnknown"] for i in items if i["id"].startswith("fi-toim-fiva-lp-"))
    # rulings
    for r in rulings:
        assert r["scope"] == "ratkaisu" and r["court"] in ("KVL", "TSV") and r["fi"] is True and r["statutes"] == [] and r["topics"]
        assert re.match(ISO, r["date"]) and r["url"] and r["links"] and r["id"].startswith(f"r-{r['court'].lower()}-")
    kvl = {r["id"]: r for r in rulings}["r-kvl-2026-29"]
    assert kvl["courtName"] == "Keskusverolautakunta" and kvl["kind"] == "Ennakkoratkaisu (KVL)" and kvl["status"] == "ei lainvoimainen"
    assert kvl["title"].startswith("Arvonlisävero – Liikuntapalvelu") and kvl["ref"] == "KVL:2026/29" and "Verotus" in kvl["topics"]
    assert kvl["statuteText"].startswith("Arvonlisäverolaki") and kvl["links"] == {"vero": kvl["url"]}
    tsv = {r["id"]: r for r in rulings}["r-tsv-2026-36"]
    assert tsv["court"] == "TSV" and tsv["courtName"] == "Tietosuojavaltuutettu" and tsv["status"] == "annettu" and tsv["links"] == {"finlex": tsv["url"]}
    assert "Tietosuoja ja digi" in tsv["topics"]
    assert items == sorted(items, key=lambda i: ((i.get("events") or [{}])[0].get("date") or "", i["id"]), reverse=True)
