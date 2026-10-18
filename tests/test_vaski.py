"""Unit tests for scripts/fetch_vaski.py: the VaskiData parsers against saved samples
(tests/samples/vaski/) and the shape of the cache they produce. No network."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_vaski as fv  # noqa: E402

SAMPLES = ROOT / "tests" / "samples" / "vaski"


def load(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def root_of(name: str):
    return fv.strip_ns(load(name))


# ------------------------------------------------------------------ helpers
def test_header_and_tunnus_helpers():
    assert fv.header(load("agenda_StVE_104_2026.xml")) == ("Esityslista", "fi")
    assert fv.header(load("statement_EDK-2025-AK-56080.xml")) == ("Asiantuntijalausunto", "fi")
    assert fv.header(load("report_VaVM_22_2026.xml")) == ("Valiokunnan mietintö", "fi")
    assert fv.split_tunnus("HaVM 15/2026 vp") == ("HaV", "M", 15, 2026)
    assert fv.split_tunnus("VeJE 58/2026 vp") == ("VeJ", "E", 58, 2026)
    assert fv.split_tunnus("HE 17/2026 vp") is None
    assert fv.committee_of("PeVL 32/2026 vp") == ("PeV", "perustuslakivaliokunta")
    assert fv.committee_of("VeJE 58/2026 vp") == ("VeJ", "valtiovarainvaliokunnan verojaosto")
    assert fv.committee_of("XxVE 1/2026 vp", "Hallintovaliokunta") == ("HaV", "hallintovaliokunta")
    for abbr in ("PeV", "UaV", "VaV", "TrV", "HaV", "LaV", "LiV", "MmV", "PuV", "SiV", "StV", "TaV", "TiV", "TuV", "TyV", "YmV", "SuV"):
        assert abbr in fv.COMMITTEES and abbr in fv.REPORTING
    assert fv.pdf_url("HaVM 15/2026 vp") == "https://www.eduskunta.fi/pdf/HaVM+15/2026"
    assert fv.motion_url("KK 263/2026 vp") == "https://www.eduskunta.fi/valtiopaivaasiat/KK+263/2026"


@pytest.mark.parametrize("who, expected", [
    ("lainsäädäntöneuvos Saara Rahko, valtiovarainministeriö", ("Saara Rahko", "valtiovarainministeriö")),
    ("sosiaali- ja terveysministeriö", (None, "sosiaali- ja terveysministeriö")),
    ("Hyvinvointialueyhtiö Hyvil Oy", (None, "Hyvinvointialueyhtiö Hyvil Oy")),
    ("professori Kaarlo Tuori", ("Kaarlo Tuori", None)),
    ("erityisasiantuntija Pekka Vasara, sisäministeriö, poliisiosasto", ("Pekka Vasara", "sisäministeriö, poliisiosasto")),
    ("OTT, dosentti Mauri Kotamäki", ("Mauri Kotamäki", None)),
    ("Terveyden ja hyvinvoinnin laitos (THL)", (None, "Terveyden ja hyvinvoinnin laitos (THL)")),
    ("johtaja, työmarkkinat, OTK Janne Laitinen, Palvelualojen työnantajat PALTA ry", ("Janne Laitinen", "Palvelualojen työnantajat PALTA ry")),
    ("Kouluterveyskyselyn kehittämispäällikkö Jenni Helenius, Terveyden ja hyvinvoinnin laitos (THL)", ("Jenni Helenius", "Terveyden ja hyvinvoinnin laitos (THL)")),
    ("oikeustieteen tohtori, varatuomari Petri Jääskeläinen", ("Petri Jääskeläinen", None)),
    ("Pohjanmaan käräjäoikeus, laamanni Daniel Allén", ("Daniel Allén", "Pohjanmaan käräjäoikeus")),
    ("Suomen Kuntaliitto", (None, "Suomen Kuntaliitto")),
    ("Stiftelsen för Åbo Akademi", (None, "Stiftelsen för Åbo Akademi")),
    ("Elinkeinoelämän keskusliitto EK ry", (None, "Elinkeinoelämän keskusliitto EK ry")),
])
def test_split_author(who, expected):
    assert fv.split_author(who) == expected


@pytest.mark.parametrize("title, who", [
    ("HE 100/2025 vp HaV 21.11.2025 lainsäädäntöneuvos Saara Rahko, valtiovarainministeriö Asiantuntijalausunto",
     "lainsäädäntöneuvos Saara Rahko, valtiovarainministeriö"),
    ("HE 105/2026 vp PeV 09.09.2026 lainsäädäntöneuvos Nina Santaharju, valtiovarainministeriö Asiantuntijalausunto PowerPoint",
     "lainsäädäntöneuvos Nina Santaharju, valtiovarainministeriö"),
    ("HE 132/2026 vp TyV 15.09.2026 Suomen Ammattiliittojen Keskusjärjestö SAK ry / täydentävä asiantuntijalausunto",
     "Suomen Ammattiliittojen Keskusjärjestö SAK ry"),
    ("HE 127/2026 vp LaV 04.09.2026 Elinkeinoelämän keskusliitto ry", "Elinkeinoelämän keskusliitto ry"),
])
def test_statement_title_regex(title, who):
    m = fv.STATEMENT_TITLE.match(title)
    assert m and m.group("who") == who


def test_stage_name_variants():
    assert fv.stage_name("ATKUUL") == "asiantuntijakuuleminen"
    assert fv.stage_name("VALMKA") == "valmistava keskustelu"
    assert fv.stage_name("YKSKASA") == "yksityiskohtainen käsittely"
    assert fv.stage_name("ILMVKA") == "asia saapunut valiokuntaan"
    assert fv.stage_name("XYZZY") is None and fv.stage_name("") is None


@pytest.mark.parametrize("text, expected", [
    ("Eduskunta hyväksyy muuttamattomana hallituksen esitykseen HE 151/2026 vp sisältyvät 1. ja 2. lakiehdotuksen. "
     "Eduskunta hylkää toimenpidealoitteen TPA 7/2024 vp.", "muuttamattomana"),
    ("Eduskunta hyväksyy muuttamattomana … 3.—5. lakiehdotuksen. Eduskunta hyväksyy muutettuna … 1. lakiehdotuksen.", "muutettuna"),
    ("Eduskunta hylkää hallituksen esitykseen HE 5/2026 vp sisältyvät lakiehdotukset.", "hylättäväksi"),
    ("että tarkastusvaliokunta ottaa edellä olevan huomioon.", "muu"),
])
def test_classify_decision(text, expected):
    assert fv.classify_decision(text) == expected


# ------------------------------------------------------------------ agenda
def test_parse_agenda():
    a = fv.parse_agenda(root_of("agenda_StVE_104_2026.xml"), "2026-10-16T15:39:45")
    assert a["tunnus"] == "StVE 104/2026 vp"
    assert a["committee"] == "StV" and a["committeeName"] == "sosiaali- ja terveysvaliokunta"
    assert a["start"] == "2026-10-20T10:00:00" and a["created"] == "2026-10-16T15:39:45"
    items = {i["asia"]: i for i in a["items"]}
    assert "HE 198/2026 vp" in items and "HE 186/2026 vp" in items
    # Nimenhuuto / Päätösvaltaisuus / Muut asiat are MuuAsiakohta and must not appear
    assert all(fv.ASIA.match(k) for k in items)
    h = items["HE 186/2026 vp"]
    assert h["stage"] == "ATKUUL" and h["stageName"] == "asiantuntijakuuleminen"
    assert h["title"].startswith("Hallituksen esitys eduskunnalle laeiksi sairausvakuutuslain")
    assert {"name": "Eva Ojala", "org": "sosiaali- ja terveysministeriö"} in h["experts"]
    assert {"org": "Kansaneläkelaitos"} in h["experts"]  # organisation invited without a named person
    assert "Elinkeinoelämän keskusliitto ry" in h["written"] and "Tehy ry" in h["written"]
    assert not any("Tehy ry" == e.get("org") for e in h["experts"])  # written statements are not hearings
    w = items["HE 198/2026 vp"]
    assert w["experts"] == [] and w["written"] == ["Hyvinvointialueyhtiö Hyvil Oy", "Terveyden ja hyvinvoinnin laitos (THL)"]


def test_parse_minutes_as_agenda():
    a = fv.parse_agenda(root_of("minutes_HaVP_98_2026.xml"))
    assert a["tunnus"] == "HaVP 98/2026 vp" and a["committee"] == "HaV"
    assert a["start"] == "2026-10-16T11:15:00"
    stages = {i["asia"]: i["stage"] for i in a["items"]}
    assert stages["HE 79/2026 vp"] == "ESITML" and stages["HE 175/2026 vp"] == "ATKUULA"


def test_minutes_do_not_replace_agenda():
    cache = fv.empty_cache()
    agenda = fv.parse_agenda(root_of("minutes_HaVP_98_2026.xml"))
    agenda["tunnus"] = "HaVE 98/2026 vp"
    assert fv.upsert_agenda(cache, dict(agenda), minutes=False) == "HaVE 98/2026 vp"
    minutes = fv.parse_agenda(root_of("minutes_HaVP_98_2026.xml"))
    assert fv.upsert_agenda(cache, minutes, minutes=True) is None  # same committee, same day -> agenda wins
    assert list(cache["agendas"]) == ["HaVE 98/2026 vp"]


# ------------------------------------------------------------------ statements
def test_parse_statement():
    s = fv.parse_statement(root_of("statement_EDK-2025-AK-56080.xml"))
    assert s == {"asia": "HE 100/2025 vp", "edk": "EDK-2025-AK-56080", "date": "2025-11-21", "committee": "HaV",
                 "org": "valtiovarainministeriö", "person": "Saara Rahko",
                 "title": "HE 100/2025 vp HaV 21.11.2025 lainsäädäntöneuvos Saara Rahko, valtiovarainministeriö Asiantuntijalausunto",
                 "url": "https://www.eduskunta.fi/pdf/EDK-2025-AK-56080"}


# ------------------------------------------------------------------ reports
def test_parse_report_amended():
    r = fv.parse_report(root_of("report_HaVM_15_2026_trimmed.xml"))
    assert r["tunnus"] == "HaVM 15/2026 vp" and r["asia"] == "HE 17/2026 vp"
    assert r["committee"] == "HaV" and r["committeeName"] == "hallintovaliokunta" and r["kind"] == "mietintö"
    assert r["date"] == "2026-06-12"  # signing date, not the re-publication date of the XML
    assert r["decision"] == "muutettuna"
    assert r["decisionText"].startswith("Eduskunta hyväksyy muuttamattomana") and len(r["decisionText"]) <= 300
    assert r["changedSections"][:3] == ["1 §", "18 §", "29 §"] and "46 a §" in r["changedSections"]
    assert r["changedLaws"][0] == "Laki eräistä rajat ylittävän sähköisen asioinnin mahdollistavista palveluista"
    assert len(r["changedLaws"]) == 4  # unchanged laws reprinted in the report are not listed
    assert r["dissent"] == 0 and r["dissentParties"] == []
    assert r["experts"] == 29  # 17 heard + 12 written; Kela's "ilmoitus, ei lausuntoa" is not an expert statement
    assert r["url"] == "https://www.eduskunta.fi/pdf/HaVM+15/2026"


def test_parse_report_unchanged_with_dissents():
    r = fv.parse_report(root_of("report_VaVM_22_2026.xml"))
    assert r["tunnus"] == "VaVM 22/2026 vp" and r["asia"] == "HE 151/2026 vp" and r["date"] == "2026-10-16"
    assert r["decision"] == "muuttamattomana"
    # the vastalause of kesk proposes its own amended law text: it must not count as the committee's change
    assert r["changedSections"] == [] and r["changedLaws"] == []
    assert r["dissent"] == 2 and r["dissentParties"] == ["sd", "vihr", "vas", "kesk"]
    assert r["experts"] == 23


def test_parse_lausunto():
    r = fv.parse_report(root_of("lausunto_SiVL_11_2026.xml"))
    assert r["tunnus"] == "SiVL 11/2026 vp" and r["kind"] == "lausunto" and r["asia"] == "K 3/2026 vp"
    assert r["committee"] == "SiV" and r["decision"] == "muu" and r["experts"] == 8
    assert r["url"] == "https://www.eduskunta.fi/pdf/SiVL+11/2026"


# ------------------------------------------------------------------ motions
def test_parse_motion_kk():
    m = fv.parse_motion(root_of("kk_KK_263_2026.xml"))
    assert m["tunnus"] == "KK 263/2026 vp" and m["type"] == "KK" and m["date"] == "2026-06-11"
    assert m["title"] == "Kirjallinen kysymys aborttioikeuden sisällyttämisestä perustuslakiin"
    assert m["firstSigner"] == "Saara Hyrkkö" and m["party"] == "vihr" and m["signers"] == 5
    assert m["text"].startswith("Oikeus raskaudenkeskeytykseen") and len(m["text"]) <= 400
    assert m["keywords"][:2] == ["abortti", "Suomen perustuslaki"] and len(m["keywords"]) <= 8
    assert m["url"] == "https://www.eduskunta.fi/valtiopaivaasiat/KK+263/2026"


def test_parse_motion_la():
    m = fv.parse_motion(root_of("la_LA_20_2026.xml"))
    assert m["tunnus"] == "LA 20/2026 vp" and m["type"] == "LA" and m["date"] == "2026-06-17"
    assert m["firstSigner"] == "Tiina Elo" and m["party"] == "vihr" and m["signers"] == 3
    assert m["text"].startswith("Aloitteen tarkoituksena on muuttaa yhteistoimintalakia")  # pääasiallinen sisältö, not perustelut


def test_parse_motion_from_stages_and_merge():
    s = fv.parse_motion_stages(root_of("kk_KK_263_2026_kasittelytiedot.xml"))
    assert s["tunnus"] == "KK 263/2026 vp" and s["date"] == "2026-06-11" and s["signers"] == 5
    assert s["firstSigner"] == "Saara Hyrkkö" and s["party"] == "vihr" and s["text"] is None
    assert s["keywords"][0] == "abortti"
    cache = fv.empty_cache()
    fv.upsert_motion(cache, s, from_stages=True)
    fv.upsert_motion(cache, fv.parse_motion(root_of("kk_KK_263_2026.xml")), from_stages=False)
    fv.upsert_motion(cache, dict(s), from_stages=True)  # the käsittelytiedot row arriving again must not erase the text
    assert len(cache["motions"]) == 1 and cache["motions"][0]["text"].startswith("Oikeus")


# ------------------------------------------------------------------ cache shape
def test_absorb_builds_cache_shape(monkeypatch):
    cache = fv.empty_cache()
    stats = {"rows": 0, "bad": 0, "agendas": 0, "statements": 0, "reports": 0, "motions": 0, "refreshed": 0, "backfill": 0}
    rows = [
        ("agenda_StVE_104_2026.xml", "StVE 104/2026 vp", "2026-10-16 15:39:45"),
        ("minutes_HaVP_98_2026.xml", "HaVP 98/2026 vp", "2026-10-16 14:27:25"),
        ("statement_EDK-2025-AK-56080.xml", "EDK-2025-AK-56080", "2025-11-29 00:04:40"),
        ("report_HaVM_15_2026_trimmed.xml", "HaVM 15/2026 vp", "2026-10-09 12:15:23"),
        ("report_VaVM_22_2026.xml", "VaVM 22/2026 vp", "2026-10-16 14:03:28"),
        ("lausunto_SiVL_11_2026.xml", "SiVL 11/2026 vp", "2026-09-11 15:33:27"),
        ("kk_KK_263_2026_kasittelytiedot.xml", "KK 263/2026 vp", "2026-07-21 12:06:11"),
        ("kk_KK_263_2026.xml", "KK 263/2026 vp", "2026-06-12 16:30:21"),
        ("la_LA_20_2026.xml", "LA 20/2026 vp", "2026-06-17 16:00:00"),
    ]
    for name, tunnus, created in rows:
        fv.absorb(cache, load(name), tunnus, created[:19].replace(" ", "T"), stats)
    # a Swedish twin and a broken document are ignored without raising
    fv.absorb(cache, load("agenda_StVE_104_2026.xml").replace("StVE 104/2026 vp", "ShUD 104/2026 rd"), "ShUD 104/2026 rd", None, stats)
    fv.absorb(cache, load("kk_KK_263_2026.xml")[:5000], "KK 263/2026 vp", None, stats)
    assert stats["bad"] == 1
    # the same statement twice -> one entry (dedupe by EDK)
    fv.absorb(cache, load("statement_EDK-2025-AK-56080.xml"), "EDK-2025-AK-56080", None, stats)

    assert set(cache) == {"fetched", "lastId", "agendas", "statements", "reports", "motions"}
    assert set(cache["agendas"]) == {"StVE 104/2026 vp", "HaVP 98/2026 vp"}
    ag = cache["agendas"]["StVE 104/2026 vp"]
    assert set(ag) == {"committee", "committeeName", "start", "created", "items"}
    assert set(ag["items"][0]) == {"asia", "stage", "stageName", "title", "experts", "written"}
    assert cache["statements"] == {"HE 100/2025 vp": [{
        "edk": "EDK-2025-AK-56080", "date": "2025-11-21", "committee": "HaV", "org": "valtiovarainministeriö",
        "person": "Saara Rahko", "title": "HE 100/2025 vp HaV 21.11.2025 lainsäädäntöneuvos Saara Rahko, valtiovarainministeriö Asiantuntijalausunto",
        "url": "https://www.eduskunta.fi/pdf/EDK-2025-AK-56080"}]}
    assert set(cache["reports"]) == {"HaVM 15/2026 vp", "VaVM 22/2026 vp", "SiVL 11/2026 vp"}
    assert set(cache["reports"]["HaVM 15/2026 vp"]) == {"asia", "committee", "committeeName", "kind", "date", "decision", "decisionText",
                                                          "changedSections", "changedLaws", "dissent", "dissentParties", "experts", "url"}
    assert [m["tunnus"] for m in cache["motions"]] == ["KK 263/2026 vp", "LA 20/2026 vp"]
    assert set(cache["motions"][0]) == {"tunnus", "type", "date", "title", "firstSigner", "party", "signers", "text", "keywords", "url"}
    assert cache["motions"][0]["text"].startswith("Oikeus")  # document text survived the käsittelytiedot row
    # no XML or full text leaks into the cache
    dumped = json.dumps(cache, ensure_ascii=False)
    assert "<" not in dumped and len(dumped) < 20000

    # pruning: everything here is old relative to a far-future "today" except what the keep windows allow
    monkeypatch.setattr(fv, "TODAY", dt.date(2026, 10, 18))
    fv.prune(cache, {"agenda_keep_days": 7, "statement_keep_days": 400, "report_keep_days": 400, "motion_keep_days": 200})
    assert set(cache["agendas"]) == {"StVE 104/2026 vp", "HaVP 98/2026 vp"}
    assert set(cache["reports"]) == {"HaVM 15/2026 vp", "VaVM 22/2026 vp", "SiVL 11/2026 vp"}
    assert len(cache["motions"]) == 2  # June motions are 123–129 days old: kept with a 200-day window
    fv.prune(cache, {"motion_keep_days": 120})
    assert cache["motions"] == []  # ...and dropped with the default 120-day window
    monkeypatch.setattr(fv, "TODAY", dt.date(2027, 3, 1))
    fv.prune(cache, {"agenda_keep_days": 7, "statement_keep_days": 400, "report_keep_days": 400, "motion_keep_days": 120})
    assert cache["agendas"] == {}
    assert set(cache["reports"]) == {"HaVM 15/2026 vp", "VaVM 22/2026 vp", "SiVL 11/2026 vp"}  # June 2026 is within 400 days
    assert cache["statements"] == {}  # 2025-11-21 is 465 days before 2027-03-01
    monkeypatch.setattr(fv, "TODAY", dt.date(2027, 9, 1))
    fv.prune(cache, {})
    assert set(cache["reports"]) == {"VaVM 22/2026 vp"}  # 2026-10-16 is the only one still within 400 days
