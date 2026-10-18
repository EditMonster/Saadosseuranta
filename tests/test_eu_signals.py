"""Unit tests for the forward-looking EU signals: the parsers in scripts/fetch_eu_signals.py against saved
samples (tests/samples/eu_signals/) and the shapes produced by scripts/build_eu_signals.py. No network."""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_eu_signals as b  # noqa: E402
import fetch_eu_signals as f  # noqa: E402
from common import TODAY, load_yaml  # noqa: E402

SAMPLES = ROOT / "tests" / "samples" / "eu_signals"
CFG = load_yaml(ROOT / "config" / "eu_signaalit.yaml")
TOPICS = load_yaml(ROOT / "config" / "topics.yaml")["topics"]
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EVENT_KINDS = {"lausunto", "he", "valiokunta", "eduskunta", "taysistunto", "vahvistettu", "voimaan", "soveltaminen", "maaraaika", "julkaistu",
               "ehdotus", "kuuleminen", "ennuste", "muu", "neuvosto", "parlamentti", "sopu"}


def load(name: str):
    p = SAMPLES / name
    if name.endswith(".json"):
        return json.loads(p.read_text(encoding="utf-8"))
    return p.read_text(encoding="utf-8")


def bindings(name: str) -> list[dict]:
    return [{k: v["value"] for k, v in row.items()} for row in load(name)["results"]["bindings"]]


def future(days: int) -> str:
    return (TODAY + dt.timedelta(days=days)).isoformat()


def check_item(it: dict, laji: str):
    for key in ("id", "scope", "laji", "kind", "title", "ref", "topics", "status", "done", "summary", "source", "links", "events"):
        assert key in it, f"{laji}: {key} puuttuu: {it.get('id')}"
    assert it["scope"] == "eu" and it["laji"] == laji
    assert isinstance(it["topics"], list) and it["topics"]
    assert isinstance(it["done"], bool)
    for ev in it["events"]:
        assert ISO.match(ev["date"]), ev
        assert ev["kind"] in EVENT_KINDS, ev
        assert ev.get("label")
        if ev["kind"] == "ennuste":
            assert ev.get("confirmed") is False, ev
        if ev.get("end"):
            assert ISO.match(ev["end"]) and ev["end"] >= ev["date"]


# ------------------------------------------------------------------ helpers
def test_helpers():
    assert f.dmy_to_iso("8/07/2026") == "2026-07-08"
    assert f.dmy_to_iso("18.02.2026") == "2026-02-18"
    assert f.fr_date("5 octobre 2026") == "2026-10-05"
    assert f.fr_date("1er mars 2027") == "2027-03-01"
    assert f.cellar_pid("procedure:2025_97") == ("2025-0097", "2025/0097")
    assert f.cellar_pid("procedure:2021_211A") == ("2021-0211A", "2021/0211A")
    assert f.cellar_pid("dossier:COM_2025_0180") is None
    assert f.norm_title("Proposal for a Regulation on the Circular Economy Act") == "circular economy act"
    assert f.consil_url("consil:CM_4574_2026_INIT") == "https://data.consilium.europa.eu/doc/document/CM-4574-2026-INIT/en/pdf"
    assert f.consil_url("ST 13654 2026 REV 3", "fi") == "https://data.consilium.europa.eu/doc/document/ST-13654-2026-REV-3/fi/pdf"
    assert f.iso_or_none("2026-10-05T00:00:00.000+0000") == "2026-10-05"
    assert f.iso_or_none("5187-04-22") is None
    assert b.quarter_date("2026-Q2") == "2026-05-01"
    assert b.quarter_date("2026-Q4", 0) == "2026-10-01"
    assert b.quarter_end("2026-Q1") == "2026-03-31"
    assert b.quarter_end("2026-Q4") == "2026-12-31"
    assert b.quarter_text("2027-Q1") == "Q1/2027"
    assert b.act_ref("32014R0833") == "833/2014"
    assert b.act_ref("32014D0145") == "2014/145"
    assert b.act_ref("32026R2333") == "2026/2333"
    assert b.similar("circular economy act", "circular economy act") == 1.0
    assert b.similar("digital fairness act", "consumer package") < 0.4


# ------------------------------------------------------------------ (a) Commission forward look
def test_parse_sec_list():
    out = f.parse_sec_list(str(SAMPLES / "sec_list_SEC_2026_2580.pdf"))
    assert out["reference"] == "SEC(2026)2580"
    assert out["issued"] == "2026-10-05"
    assert out["period"].startswith("20 October 2026")
    dates = [m["date"] for m in out["meetings"]]
    assert dates == sorted(dates) and all(ISO.match(d) for d in dates)
    assert dates[0] == "2026-10-20" and out["meetings"][0]["place"] == "Strasbourg"
    first = out["meetings"][0]["items"]
    assert first[0]["title"] == "2027 Commission work programme" and first[0]["responsible"] == "PRESIDENT"
    pkg = next(i for m in out["meetings"] for i in m["items"] if i["title"] == "Border and migration package")
    assert pkg["responsible"] == "VIRKKUNEN" and len(pkg["subItems"]) == 3
    assert pkg["subItems"][0].startswith("Strengthening Frontex")
    assert pkg["norm"] == "border migration package"
    assert sum(len(m["items"]) for m in out["meetings"]) >= 12


def test_parse_cwp_annex_pdf_and_align():
    rows = f.parse_cwp_annex(str(SAMPLES / "cwp_annex_fi_p2-3.pdf"))
    assert len(rows) >= 15
    assert rows[0]["no"] == "1" and rows[0]["title"].startswith("Innovatiivisiin yrityksiin")
    assert rows[0]["quarter"] == "2026-Q1" and rows[0]["kind"] == "legislative"
    assert all(r["quarter"] is None or re.match(r"\d{4}-Q[1-4]$", r["quarter"]) for r in rows)
    kinds = {r["kind"] for r in rows}
    assert "legislative" in kinds
    fi = load("cwp_annex_fi.parsed.json")
    en = load("cwp_annex_en.parsed.json")
    merged = f.align_cwp(fi, en)
    assert len(merged) == len(fi)
    assert merged[0]["title_fi"].startswith("Innovatiivisiin") and merged[0]["title_en"] == "28th Regime for Innovative Companies"
    assert merged[0]["norm"] == "28th regime innovative companies"
    assert all(m["title_en"] for m in merged)  # same row counts per numbered objective -> fully aligned
    only_en = f.align_cwp([], en)
    assert only_en[0]["title_fi"] is None and only_en[0]["title_en"] == en[0]["title"]


# ------------------------------------------------------------------ (b) Council agendas
def test_council_from_rows():
    cfg = {**CFG["neuvosto"], "keep_days": 100000}
    out = f.council_from_rows(bindings("cellar_agendas.json"), bindings("cellar_projected.json"), cfg)
    assert out["agendas"] and out["projected"]
    for a in out["agendas"]:
        assert a["kind"] in ("coreper1", "coreper2", "council", "sca")
        assert a["url"].startswith("https://data.consilium.europa.eu/doc/document/")
        assert all(ISO.match(d) for d in a["meetingDates"])
        for it in a["items"]:
            assert re.match(r"\d{4}-\d{4}[A-Z]?$", it["pid"]) and re.match(r"\d{4}/\d{4}", it["ref"])
    cm = next(a for a in out["agendas"] if a["id"] == "CM 4574 2026 INIT")
    assert cm["body"] == "Coreper I" and cm["kind"] == "coreper1"
    assert "2025-0097" in {i["pid"] for i in cm["items"]}
    item = next(i for i in cm["items"] if i["pid"] == "2025-0097")
    assert item["date"] in cm["meetingDates"] and "DELIB_COREPER_byCONSIL" in item["types"]
    epsco = next(a for a in out["agendas"] if a["id"] == "ST 13720 2026 INIT")
    assert epsco["body"].startswith("Työllisyys-") and epsco["kind"] == "council" and epsco["urlFi"].endswith("/fi/pdf")
    for ev in out["projected"]:
        assert ISO.match(ev["date"]) and ev["type"] and ev["pid"]
    assert any(ev["type"] == "VOTE_byEP" for ev in out["projected"])


def test_body_of():
    cfg = CFG["neuvosto"]
    assert f.body_of("PERMANENT REPRESENTATIVES COMMITTEE (Part 2)", cfg) == ("Coreper II", "coreper2")
    assert f.body_of("COUNCIL OF THE EUROPEAN UNION (Environment)", cfg) == ("Ympäristöneuvosto", "council")
    assert f.body_of("COUNCIL OF THE EUROPEAN UNION (Space)", cfg) == ("Neuvosto (Space)", "council")
    assert f.body_of("Working Party on Company Law", cfg)[1] == "wp"
    # working parties are dropped unless configured in
    rows = f.council_from_rows([{"id": "consil:CM_1_2026_INIT", "date": future(0), "title": "Working Party on Company Law", "dossiers": "procedure:2026_74", "meeting_dates": future(3)}], [], {**cfg, "keep_days": 7})
    assert rows["agendas"] == []
    rows = f.council_from_rows([{"id": "consil:CM_1_2026_INIT", "date": future(0), "title": "Working Party on Company Law", "dossiers": "procedure:2026_74", "meeting_dates": future(3)}], [], {**cfg, "keep_days": 7, "include_working_parties": True})
    assert rows["agendas"][0]["items"][0]["pid"] == "2026-0074"


# ------------------------------------------------------------------ (c) EP forecasts
def test_parse_oeil():
    html_out = f.parse_oeil_html(load("oeil_2025-0395_trimmed.html"))
    assert html_out["stage"] == "Awaiting Parliament's position in 1st reading"
    assert html_out["forecasts"] == [{"date": "2026-10-19", "text": "Debate in plenary scheduled"}, {"date": "2026-10-20", "text": "Vote in plenary scheduled"}]
    pdf_out = f.parse_oeil_pdf_text(load("oeil_forecast_2025-0395.txt"))
    assert pdf_out == html_out
    cls = f.classify_forecasts(html_out["forecasts"], CFG["ennusteet"])
    assert cls == {"plenary": "2026-10-20", "committeeVote": None, "otherForecasts": []}
    cls = f.classify_forecasts([{"date": "2026-11-12", "text": "Indicative plenary sitting date, 1st reading"},
                                {"date": "2026-10-28", "text": "Vote scheduled in committee, 1st reading"},
                                {"date": "2026-10-01", "text": "Deadline for amendments"}], CFG["ennusteet"])
    assert cls["plenary"] == "2026-11-12" and cls["committeeVote"] == "2026-10-28" and cls["otherForecasts"][0]["text"] == "Deadline for amendments"
    assert f.parse_oeil_html("<html><body>nothing</body></html>") == {"stage": None, "forecasts": []}
    assert f.parse_oeil_pdf_text("Basic information\n2025/0045(COD) Procedure completed\nSubject\n3.45.01 Company law\n") == {"stage": "Procedure completed", "forecasts": []}


def test_parse_ep_foreseen_and_pending():
    data = {"data": [
        {"id": "x", "activity_date": "2026-10-20", "had_activity_type": "def/ep-activities/PLENARY_VOTE", "notation_agendaPoint": "V-22",
         "inverse_was_scheduled_in": ["eli/dl/proc/2025-0396"], "activity_label": {"fi": "Otsikko suomeksi", "en": "Title"}},
        {"id": "y", "activity_date": "2026-10-20", "had_activity_type": "def/ep-activities/MEETING_PART", "inverse_was_scheduled_in": ["eli/dl/event/MTG-PL-2026-10-20"]},
    ]}
    rows = f.parse_ep_foreseen(data, "MTG-PL-2026-10-20")
    assert rows == [{"pid": "2025-0396", "date": "2026-10-20", "type": "vote", "point": "V-22", "title_fi": "Otsikko suomeksi", "title_en": "Title", "sitting": "MTG-PL-2026-10-20"}]
    eu = {"2025-0001": {"ref": "2025/0001(COD)", "final": False, "cellar": {"acts": {}}, "fetched": "2026-10-01"},
          "2024-0002": {"ref": "2024/0002(COD)", "final": False, "cellar": {"acts": {"32025R0001": {}}}},
          "2023-0003": {"ref": "2023/0003(COD)", "final": True, "cellar": {"acts": {"32024R0001": {}}}}}
    assert [p["pid"] for p in f.pending_procedures(eu)] == ["2025-0001"]


# ------------------------------------------------------------------ (d) infringements
def test_infringements():
    dec = load("infr_decisions_FI.json")["records"]
    cas = load("infr_infringements_FI_active.json")["records"]
    cases = f.infringement_cases(dec, cas, CFG["rikkomukset"])
    assert "INFR(2026)2150" in cases and "INFR(2026)2120" in cases
    c = cases["INFR(2026)2150"]
    assert c["active"] is True and c["nonCommunication"] is True
    assert c["decisions"][0]["date"] == "2026-07-08" and c["decisions"][0]["stage"] == "virallinen ilmoitus"
    assert c["celex"] == "32024L2839" and c["actRef"] == "Directive EU 2024/2839"
    assert c["policyAreas"] == ["Construction and machinery/ Machinery and equipment"]
    assert cases["INFR(2026)2120"]["celex"] == "32019L1152" and cases["INFR(2026)2120"]["actRef"] == "Directive 2019/1152"
    stages = {d["stage"] for cc in cases.values() for d in cc["decisions"]}
    assert {"virallinen ilmoitus", "perusteltu lausunto", "asian lopettaminen", "kanne unionin tuomioistuimeen"} <= stages
    closed = [cc for cc in cases.values() if cc["decisions"][-1]["stage"] == "asian lopettaminen"]
    assert closed and all(cc["active"] is False for cc in closed)
    for cc in cases.values():
        assert cc["lastDecision"] == max(d["date"] for d in cc["decisions"])
        assert [d["date"] for d in cc["decisions"]] == sorted(d["date"] for d in cc["decisions"])
    assert f.act_from_title("Lack of transposition of Directive 1785/2024 on industrial emissions") == ("32024L1785", "Directive 1785/2024")
    assert f.act_from_title("Non-conformity with Directive 2008/98/EC") == ("32008L0098", "Directive 2008/98/EC")
    assert f.act_from_title("Lack of transposition of Directive 32026L0074 by Finland") == ("32026L0074", "32026L0074")
    assert f.act_from_title("Regulation (EU) No 1308/2013 wrongly applied") == ("32013R1308", "Regulation (EU) No 1308/2013")
    assert f.act_from_title("Bad application of EU law") == (None, None)
    assert f.stage_fi("Reasoned opinion Art. 258-260(3) TFEU", CFG["rikkomukset"]) == "perusteltu lausunto"
    assert f.stage_fi("Referral to Court Art. 258 TFEU  - 260(3) TFEU", CFG["rikkomukset"]) == "kanne unionin tuomioistuimeen"
    assert f.stage_fi("Closing of the case", CFG["rikkomukset"]) == "asian lopettaminen"


# ------------------------------------------------------------------ (e) comitology
def test_comitology_csv_and_detail():
    docs = f.comreg_csv_rows(load("comreg_draftMeasures_sample.csv"), "2000-01-01")
    assert {"D087670", "D099926", "D106531", "D107429", "D108563", "D105447"} <= set(docs)
    d = docs["D087670"]
    assert d["title"].startswith("COMMISSION IMPLEMENTING REGULATION") and "Annex" not in d["title"][:10]
    assert d["submitted"] == "2026-06-16" and d["status"] == "Adoption" and d["statusDate"] == "2026-07-14"
    assert d["voteDate"] == "2026-07-14" and d["voteResult"] == "Favourable" and d["votingSheet"] == "V116877/01"
    assert d["adoptionDate"] is None and d["version"] == 8
    assert d["meetingCode"] == "CMTD(2026)67" and d["meetingStart"] == "2026-06-29" and d["meetingEnd"] == "2026-06-30"
    assert d["dg"] == "Health and Food Safety" and d["procedure"] == "Art. 5, 6 and 7"
    assert d["basicAct"]["title"].startswith("Regulation") and "Â" not in d["basicAct"]["title"]
    assert [h["status"] for h in d["history"]] == ["Draft Implementing Act submitted to Committee", "Adoption"]
    p = docs["D106531"]
    assert p["status"] == "Sent to committee" and p["statusDate"] == "2026-10-01" and p["voteDate"] is None
    assert docs["D107429"]["status"].startswith("Draft Implementing Act submitted") and docs["D107429"]["voteDate"] is None
    # nothing newer than the cutoff -> dropped
    assert f.comreg_csv_rows(load("comreg_draftMeasures_sample.csv"), "2099-01-01") == {}
    rec = {"ref": "D118546", "basicAct": {"title": None, "celex": None, "code": None}, "title": "", "procedure": None}
    f.comreg_detail(rec, load("comreg_document_D118546.json"))
    assert rec["basicAct"]["celex"] == "32024R1624" and rec["basicAct"]["code"] == "REG/2024/1624/"
    assert rec["dgCode"] == "FISMA" and rec["stage"] == "draft_implementing_examination" and rec["stageDate"] == "2026-09-29"
    assert rec["procedure"] == "Art. 5, 6 and 7" and rec["docStatus"] == "transmitted" and rec["title"].startswith("COMMISSION IMPLEMENTING REGULATION")
    assert f.excluded_title("Commission Implementing Decision on the award of one grant under Horizon Europe", CFG["komitologia"]["exclude_title_patterns"])
    assert not f.excluded_title("COMMISSION IMPLEMENTING REGULATION on the methodology for high-risk third countries", CFG["komitologia"]["exclude_title_patterns"])


def test_ia_title():
    assert b.ia_title("COMMISSION IMPLEMENTING REGULATION (EU) …/... of XXX on the methodology for X (Text with EEA relevance)") == \
        ("Täytäntöönpanoasetus", "Commission Implementing Regulation on the methodology for X")
    assert b.ia_title("Draft COMMISSION IMPLEMENTING DECISION of XXX concerning Y")[0] == "Täytäntöönpanopäätös"
    assert b.ia_title("COMMISSION REGULATION (EU) …/… of XXX amending Annex XVII to Regulation (EC) No 1907/2006") == \
        ("Komission asetus (komitologia)", "Commission Regulation amending Annex XVII to Regulation (EC) No 1907/2006")
    assert b.ia_title("EN 1 EN COMMISSION IMPLEMENTING REGULATION (EU) …/... of XXX amending Implementing Regulation (EU) 2015/1831")[0] == "Täytäntöönpanoasetus"
    assert b.ia_title("Explanatory notes to the Combined Nomenclature")[0] == "Täytäntöönpanosäädös"


# ------------------------------------------------------------------ (f) sanctions
def test_sanctions_rows():
    acts = f.parse_sanctions_rows(bindings("cellar_sanctions.json"), CFG["pakotteet"]["regimes"])
    assert acts and acts == sorted(acts, key=lambda a: (a["oj"], a["celex"]), reverse=True)
    a = next(x for x in acts if x["celex"] == "32026R2333")
    assert a["oj"] == "2026-10-15" and a["eif"] == "2026-10-15" and a["amends"] == ["32014R0269"] and a["regime"] == "Venäjä"
    assert a["title_fi"].startswith("Neuvoston täytäntöönpanoasetus (EU) 2026/2333")
    bel = next(x for x in acts if x["celex"] == "32026D2312")
    assert bel["regime"] == "Valko-Venäjä" and bel["amends"] == ["32012D0642"]
    assert f.regime_of({"amends": [], "title_en": "restrictive measures in view of the situation in Haiti", "title_fi": ""}, CFG["pakotteet"]["regimes"]) == "Haiti"
    assert f.regime_of({"amends": [], "title_en": "restrictive measures somewhere", "title_fi": ""}, CFG["pakotteet"]["regimes"]) == "muu"


# ------------------------------------------------------------------ (g) EUN documents
def test_parse_eun_rows():
    rec = f.parse_eun_rows(load("eun_EUN_8_2026.json"))
    assert rec["tunnus"] == "EUN 8/2026 vp" and rec["n"] == 8 and rec["year"] == 2026
    assert rec["title"] == "Euroopan unionin neuvoston kokous 24.2.2026 (Yleisten asioiden neuvosto)"
    assert rec["council"] == "Yleisten asioiden neuvosto" and rec["date"] == "2026-02-24" and rec["end"] is None
    assert rec["submitted"] == "2026-02-18" and rec["hasMemo"] is True and rec["eutori"] == "EU/5/2026"
    assert rec["pdf"] == "https://www.eduskunta.fi/pdf/EUN+8/2026" and rec["url"] == "https://www.eduskunta.fi/valtiopaivaasiat/EUN+8/2026"
    assert "Venäjän hyökkäys Ukrainaan 2022" in rec["keywords"] and "kilpailukyky" in rec["keywords"]
    assert rec["handling"][0] == {"date": "2026-02-20", "label": "Asiantuntijakuuleminen", "committee": "suuri valiokunta"}
    assert rec["docId"] == "CAB1D5CD-5670-42A9-AB85-CBDAA3ED68DE"
    assert f.parse_eun_rows({"columnNames": [], "rowData": []}) is None


def test_meeting_from_title():
    assert f.meeting_from_title("Euroopan unionin neuvoston kokous 24.2.2026 (Yleisten asioiden neuvosto)") == {"council": "Yleisten asioiden neuvosto", "date": "2026-02-24", "end": None}
    assert f.meeting_from_title("Epävirallinen energiaministerikokous 28.–29.9.2026") == {"council": "Epävirallinen energiaministerikokous", "date": "2026-09-28", "end": "2026-09-29"}
    assert f.meeting_from_title("Eurooppa-neuvoston kokous 15.-16.10.2026") == {"council": "Eurooppa-neuvosto", "date": "2026-10-15", "end": "2026-10-16"}
    assert f.meeting_from_title("EU:n epävirallinen puolustusministerikokous 31.8.-1.9.2026") == {"council": "EU:n epävirallinen puolustusministerikokous", "date": "2026-08-31", "end": "2026-09-01"}


# ------------------------------------------------------------------ builders
def signals_fixture() -> dict:
    """A cache built from the samples, with the time-sensitive dates moved relative to today."""
    sec = f.parse_sec_list(str(SAMPLES / "sec_list_SEC_2026_2580.pdf"))
    shift = (TODAY - dt.date(2026, 10, 18)).days + 2
    for m in sec["meetings"]:
        m["date"] = (dt.date.fromisoformat(m["date"]) + dt.timedelta(days=shift)).isoformat()
    sec.update({"url": "https://ec.europa.eu/transparency/documents-register/detail?ref=SEC(2026)2580", "fetched": TODAY.isoformat()})
    cwp = {"reference": "COM(2025)870", "date": "2025-10-21", "url": "https://ec.europa.eu/transparency/documents-register/detail?ref=COM(2025)870",
           "fetched": TODAY.isoformat(), "initiatives": f.align_cwp(load("cwp_annex_fi.parsed.json"), load("cwp_annex_en.parsed.json"))}
    council = f.council_from_rows(bindings("cellar_agendas.json"), bindings("cellar_projected.json"), {**CFG["neuvosto"], "keep_days": 100000})
    for a in council["agendas"]:
        a["meetingDates"] = [future(5)]
        for it in a["items"]:
            it["date"] = future(5)
    council["projected"] = [{**ev, "date": future(9)} for ev in council["projected"]]
    infr = f.infringement_cases(load("infr_decisions_FI.json")["records"], load("infr_infringements_FI_active.json")["records"], CFG["rikkomukset"])
    docs = f.comreg_csv_rows(load("comreg_draftMeasures_sample.csv"), "2000-01-01")
    f.comreg_detail(docs["D087670"], load("comreg_document_D118546.json"))
    eun = f.parse_eun_rows(load("eun_EUN_8_2026.json"))
    eun2 = {**eun, "n": 99, "tunnus": "EUN 99/2026 vp", "date": future(6), "end": None, "submitted": future(-1), "hasMemo": False, "pdf": None}
    return {
        "forward": {"lists": [sec], "cwp": cwp},
        "council": council,
        "forecasts": {"items": {"2025-0097": {"ref": "2025/0097(COD)", "fetched": TODAY.isoformat(), "stage": "Awaiting committee decision",
                                              "plenary": future(30), "committeeVote": future(12), "forecasts": [{"date": future(30), "text": "Indicative plenary sitting date, 1st reading"}]},
                                "2025-0360": {"ref": "2025/0360(COD)", "fetched": TODAY.isoformat(), "stage": None, "plenary": "2020-01-01", "committeeVote": None, "forecasts": []}},
                      "epAgenda": {"items": {"2025-0395": [{"pid": "2025-0395", "date": future(2), "type": "vote", "point": "V-22", "title_fi": "Otsikko", "title_en": "Title", "sitting": "MTG-PL"}]}}},
        "infringements": {"cases": infr, "fetched": TODAY.isoformat()},
        "comitology": {"documents": docs, "committees": {}},
        "sanctions": {"acts": f.parse_sanctions_rows(bindings("cellar_sanctions.json"), CFG["pakotteet"]["regimes"])},
        "eun": {"docs": {"8/2026": eun, "99/2026": eun2}},
    }


def test_attach_eu_forecasts():
    sig = signals_fixture()
    items = [{"id": "eu-2025-0097", "pid": "2025-0097", "procedure": "2025/0097(COD)", "links": {"oeil": b.OEIL + "2025/0097(COD)"}, "events": [{"date": "2025-03-01", "label": "Komission ehdotus", "kind": "ehdotus", "confirmed": True}]},
             {"id": "eu-2025-0395", "pid": "2025-0395", "procedure": "2025/0395(COD)", "links": {}, "events": []},
             {"id": "eu-2025-0360", "pid": "2025-0360", "procedure": "2025/0360(COD)", "links": {}, "events": []},
             {"id": "eu-2019-0001", "pid": "2019-0001", "procedure": "2019/0001(COD)", "links": {}, "events": []},
             {"id": "eu-da-1", "events": []}]
    b.attach_eu_forecasts(items, sig, CFG)
    a = items[0]
    assert a["forecast"]["plenary"] == future(30) and a["forecast"]["committeeVote"] == future(12) and a["forecast"]["source"] == "oeil"
    labels = {(e["label"], e["kind"], e["confirmed"]) for e in a["events"]}
    assert ("EP:n täysistuntokäsittely (ennuste)", "ennuste", False) in labels
    assert ("Valiokunnan äänestys (ennuste)", "ennuste", False) in labels
    assert a["coreper"] and a["coreper"][0]["body"] == "Coreper I" and a["coreper"][0]["url"].startswith("https://data.consilium.europa.eu/")
    cor = [e for e in a["events"] if e["kind"] == "neuvosto"]
    assert cor and cor[0]["confirmed"] is True and cor[0]["label"].startswith("Coreper I – esityslistalla")
    assert [e["date"] for e in a["events"]] == sorted(e["date"] for e in a["events"])
    # exact EP agenda beats OEIL; a stale (past) OEIL forecast is ignored, Cellar's projected EP vote is the fallback
    assert items[1]["forecast"]["plenary"] == future(2) and items[1]["forecast"]["source"] == "ep-agenda" and items[1]["forecast"]["agendaTitle"] == "Otsikko"
    assert items[2].get("forecast", {}).get("plenary") in (None, future(9))
    if items[2].get("forecast"):
        assert items[2]["forecast"]["source"] == "cellar"
    assert "forecast" not in items[3] and "coreper" not in items[3] and items[3]["events"] == []
    assert items[4] == {"id": "eu-da-1", "events": []}


def test_signal_items():
    sig = signals_fixture()
    cfg = {**CFG, "planned_initiatives": {**CFG["planned_initiatives"], "keep_past_days": 100000}}
    rows = b.signal_items(TOPICS, sig, cfg)
    kinds = {r["kind"] for r in rows}
    assert kinds == {"Komission suunnitelma", "Rikkomusmenettely", "Neuvoston kokous (VNK:n muistio)"}
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))
    for r in rows:
        check_item(r, "signaali")
        assert r["status"] in ("suunniteltu", "vireillä", "annettu", "päättynyt", "tulossa", "pidetty")
        assert r.get("authority")
    com = [r for r in rows if r["kind"] == "Komission suunnitelma"]
    assert all(r["id"].startswith("eu-sig-com-") and re.fullmatch(r"eu-sig-com-[0-9a-f]{12}", r["id"]) for r in com)
    assert all(r["status"] == "suunniteltu" for r in com)
    dated = [r for r in com if r["planned"]]
    assert dated and all(r["events"][0]["kind"] == "ennuste" and r["events"][0]["confirmed"] is False and r["events"][0]["date"] == r["planned"] for r in dated)
    assert all(r["events"] == [] and r["plannedText"] == "ajankohta avoin" for r in com if not r["planned"])
    weekly = [r for r in com if r["ref"].startswith("SEC(")]
    assert weekly and all(ISO.match(r["planned"]) and "komission kokous" in r["plannedText"] for r in weekly)
    pkg = next(r for r in weekly if r["title"] == "Border and migration package")
    assert pkg["responsible"].startswith("Virkkunen") and "Paketti:" in pkg["summary"]
    cwp_only = [r for r in com if r["ref"].startswith("COM(2025)870")]
    assert cwp_only and all(r["plannedText"].startswith("Q") or r["plannedText"] == "ajankohta avoin" for r in cwp_only)
    q = next(r for r in cwp_only if r["quarter"] == "2026-Q2")
    assert q["planned"] == "2026-05-01" and q["events"][0]["date"] == "2026-05-01"
    matched = [r for r in weekly if r["quarter"]]  # weekly rows joined to a work-programme initiative get the Finnish title
    assert matched and all(r["fullTitle"].count(" / ") == 1 for r in matched)
    # same CWP initiative must not appear twice (weekly match + CWP-only)
    cwp_keys = [r["id"] for r in com]
    assert len(cwp_keys) == len(set(cwp_keys))
    infr = [r for r in rows if r["kind"] == "Rikkomusmenettely"]
    assert infr and all(re.fullmatch(r"eu-sig-infr-\d{4}-\d+", r["id"]) for r in infr)
    c = next(r for r in infr if r["ref"] == "INFR(2026)2150")
    assert c["stage"] == "virallinen ilmoitus" and c["status"] == "vireillä" and c["done"] is False and c["celex"] == "32024L2839"
    assert c["events"][0] == {"date": "2026-07-08", "label": "Komissio: virallinen ilmoitus", "kind": "muu", "confirmed": True, "url": "https://ec.europa.eu/commission/presscorner/detail/EN/inf_26_1376"}
    assert c["links"]["saados"].endswith("CELEX:32024L2839")
    closed = [r for r in infr if r["status"] == "päättynyt"]
    assert closed and all(r["done"] and r["stage"] == "asian lopettaminen" for r in closed)
    eun = [r for r in rows if r["kind"] == "Neuvoston kokous (VNK:n muistio)"]
    assert {r["id"] for r in eun} == {"fi-eun-8-2026", "fi-eun-99-2026"}
    e8 = next(r for r in eun if r["id"] == "fi-eun-8-2026")
    assert e8["scope"] == "eu" and e8["authority"] == "Valtioneuvosto" and e8["ref"] == "EUN 8/2026 vp"
    assert e8["status"] == "pidetty" and e8["done"] is True and e8["council"] == "Yleisten asioiden neuvosto"
    mtg = next(ev for ev in e8["events"] if ev["kind"] == "neuvosto")
    assert mtg["date"] == "2026-02-24" and mtg["confirmed"] is True and mtg["label"].startswith("Yleisten asioiden neuvosto")
    assert any(ev["kind"] == "eduskunta" and "suuri valiokunta" in ev["label"] for ev in e8["events"])
    assert e8["links"]["muistio"] == "https://www.eduskunta.fi/pdf/EUN+8/2026"
    e99 = next(r for r in eun if r["id"] == "fi-eun-99-2026")
    assert e99["status"] == "tulossa" and e99["done"] is False and "muistio" not in e99["links"]


def test_implementing_items():
    sig = signals_fixture()
    hys = [{"actType": "REG_IMPL", "title_en": "Renewal of the approval of the active substance pelargonic acid", "url": "https://ec.europa.eu/info/law/better-regulation/have-your-say/initiatives/1_en",
            "periods": [{"stage": "ISC_WORKFLOW", "start": "2026-05-01", "end": "2026-05-29", "open": False}]}]
    rows = b.implementing_items(TOPICS, sig, CFG, hys=hys)
    assert rows
    for r in rows:
        check_item(r, "taytantoonpano")
        assert re.fullmatch(r"eu-ia-d\d+", r["id"])
        assert r["status"] in ("äänestys tulossa", "hyväksytty komiteassa", "annettu", "julkaistu", "lykätty", "ei lausuntoa", "kielteinen lausunto", "muutoksenhakukomiteassa", "peruutettu")
        assert r["links"]["komitologia"].startswith("https://ec.europa.eu/transparency/comitology-register/screen/documents/")
        assert "committee" in r and "voteResult" in r
    d = next(r for r in rows if r["id"] == "eu-ia-d087670")
    assert d["status"] == "hyväksytty komiteassa" and d["voteResult"] == "puoltava" and d["voteDate"] == "2026-07-14"
    assert d["kind"] == "Täytäntöönpanoasetus" and d["title"].startswith("Commission Implementing Regulation")
    labels = {(e["label"], e["kind"], e["confirmed"]) for e in d["events"]}
    assert ("Luonnos toimitettu komitealle", "ehdotus", True) in labels
    assert ("Komitean äänestys: puoltava", "muu", True) in labels
    assert d["celex"] == "32024R1624" and d["links"]["perussaados"].endswith("CELEX:32024R1624")
    assert d["done"] is False
    p = next(r for r in rows if r["id"] == "eu-ia-d106531")
    assert p["status"] == "äänestys tulossa" and not any(e["kind"] == "julkaistu" for e in p["events"])
    pending_vote = [e for e in p["events"] if e["label"].startswith("Komitean äänestys")]
    assert pending_vote and pending_vote[0]["confirmed"] is False
    # Have your say span attached when the titles match
    matched = [r for r in rows if "hys" in r["links"]]
    assert matched and any(e["kind"] == "lausunto" and e["end"] == "2026-05-29" for e in matched[0]["events"])


def test_sanction_items():
    sig = signals_fixture()
    rows = b.sanction_items(TOPICS, sig, CFG)
    assert rows
    for r in rows:
        check_item(r, "pakote")
        assert re.fullmatch(r"eu-pak-3\d{4}[RD]\d{4}", r["id"])
        assert r["status"] in ("voimassa", "julkaistu") and r["topics"][0] == "Turvallisuus ja puolustus"
        assert r["links"]["eurlex"] == f"https://eur-lex.europa.eu/legal-content/FI/TXT/?uri=CELEX:{r['celex']}"
        assert {e["kind"] for e in r["events"]} <= {"julkaistu", "voimaan"} and all(e["confirmed"] for e in r["events"])
    a = next(r for r in rows if r["id"] == "eu-pak-32026R2333")
    assert a["kind"] == "Neuvoston täytäntöönpanoasetus" and a["ref"] == "(EU) 2026/2333" and a["regime"] == "Venäjä 269/2014"
    assert a["title"].startswith("Neuvoston täytäntöönpanoasetus (EU) 2026/2333 – Venäjä 269/2014")
    assert a["fullTitle"].startswith("Neuvoston täytäntöönpanoasetus (EU) 2026/2333, annettu 15 päivänä lokakuuta 2026")
    assert a["events"][0] == {"date": "2026-10-15", "label": "Julkaistu EUVL:ssä", "kind": "julkaistu", "confirmed": True, "url": a["links"]["eurlex"]}
    assert a["links"]["eli"] == "https://eur-lex.europa.eu/eli/reg_impl/2026/2333/oj" and a["links"]["perussaados"].endswith("CELEX:32014R0269")
    assert a["status"] == "voimassa" and a["done"] is True
    d = next(r for r in rows if r["id"] == "eu-pak-32026D2332")
    assert d["kind"] == "Neuvoston päätös (YUTP)" and d["ref"] == "(YUTP) 2026/2332" and d["links"]["eli"].endswith("/eli/dec/2026/2332/oj")


def test_builders_tolerate_empty_cache():
    assert b.signal_items(TOPICS, {}, CFG) == []
    assert b.implementing_items(TOPICS, {}, CFG, hys=[]) == []
    assert b.sanction_items(TOPICS, {}, CFG) == []
    items = [{"id": "eu-1", "pid": "2025-0001", "events": []}]
    b.attach_eu_forecasts(items, {}, CFG)
    assert items == [{"id": "eu-1", "pid": "2025-0001", "events": []}]


@pytest.mark.parametrize("name", ["sec_list_SEC_2026_2580.pdf", "cwp_annex_fi_p2-3.pdf", "eun_EUN_8_2026.json", "cellar_agendas.json", "cellar_projected.json",
                                  "cellar_sanctions.json", "infr_decisions_FI.json", "infr_infringements_FI_active.json", "comreg_draftMeasures_sample.csv",
                                  "comreg_document_D118546.json", "oeil_2025-0395_trimmed.html", "oeil_forecast_2025-0395.txt",
                                  "cwp_annex_fi.parsed.json", "cwp_annex_en.parsed.json"])
def test_samples_small(name):
    assert (SAMPLES / name).stat().st_size <= 150_000
    assert sum(p.stat().st_size for p in SAMPLES.iterdir()) <= 500_000
