"""Oikeuskäytäntö-lähteen yksikkötestit: jäsentimet tallennetuilla näytteillä (tests/samples/caselaw/),
säädösviittausten tulkinta, tunnisteet ja rakentajan tuottama ratkaisut.json-muoto. Ei verkkoa."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_ratkaisut  # noqa: E402
import fetch_caselaw as fc  # noqa: E402
import fetch_curia as fcu  # noqa: E402

S = ROOT / "tests" / "samples" / "caselaw"
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def sample(name: str) -> str:
    return (S / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def cfg():
    return fc.load_config()


@pytest.fixture(scope="module")
def resolver(cfg):
    return fc.StatuteResolver(cfg)


class FakeResp:
    def __init__(self, text):
        self.text, self.status_code = text, 200

    def raise_for_status(self):
        pass


# ---------- court sites ----------

def test_kko_site_page(cfg, resolver):
    d = fc.parse_site_decision(sample("kko_2026_75.html"), "KKO")
    rec = fc._normalise("KKO", cfg["courts"]["KKO"], cfg, resolver, {"url": "u"}, d)
    assert rec["ref"] == "KKO:2026:75" and rec["date"] == "2026-10-16" and rec["ecli"] == "ECLI:FI:KKO:2026:75"
    assert rec["keywords"] == ["Törkeä kotirauhan rikkominen", "Syyteoikeus"]
    assert rec["diaari"].startswith("R 1/2026/626") and rec["taltio"] == "1052 1034"
    assert rec["abstract"].startswith("A oli yhdessä") and "erittäin tärkeä yleinen etu" in rec["abstract"]
    assert rec["statutes"] == [{"sk": "39/1889", "section": "24 luku 12 §"}]  # RL 24 luku 12 §
    assert "KKO:2026:75" not in rec["citedCases"] and "KKO:2010:1" in rec["citedCases"]
    assert rec["finlexUrl"].endswith("/korkein-oikeus/ennakkopaatokset/2026/75")


def test_kho_site_page(cfg, resolver):
    d = fc.parse_site_decision(sample("kho_2026_83.html"), "KHO")
    rec = fc._normalise("KHO", cfg["courts"]["KHO"], cfg, resolver, {"url": "u"}, d)
    assert rec["ref"] == "KHO:2026:83" and rec["kind"] == "Vuosikirjapäätös" and rec["date"] == "2026-10-13"
    assert rec["keywords"] == ["Henkilökohtaisen tulon verotus", "Osakaslaina", "Ulkomainen osakeyhtiö"]
    assert rec["diaari"] == "1498/2025, 2242/2025" and rec["taltio"] == "2720"
    assert rec["statutes"] == [{"sk": "1535/1992", "section": "53 a §"}]  # "Tuloverolaki 53 a §" + in-text "tuloverolain 53 a §:n"
    assert "Verovuodet" not in rec["abstract"] and "Äänestys perusteluista 3–2" in rec["abstract"]


def test_mao_ipr_page(cfg, resolver):
    d = fc.parse_site_decision(sample("mao_482_2026.html"), "MAO")
    rec = fc._normalise("MAO", cfg["courts"]["MAO"], cfg, resolver, {"url": "u", "category": "ipr"}, d)
    assert rec["ref"] == "MAO:482/2026" and rec["date"] == "2026-10-06"
    assert rec["parties"] == "Elisa Oyj > DNA Oyj" and rec["category"].startswith("Teollis- ja tekijänoikeudelliset")
    assert rec["keywords"][0] == "turvaamistoimi" and rec["diaari"] == "425/2026, 428/2026"
    assert rec["outcome"].startswith("Markkinaoikeus kieltää oikeudenkäymiskaaren 7 luvun 3 §:n")
    assert {"sk": "4/1734", "section": "7 luku 3 §"} in rec["statutes"]


def test_kho_archive_list(monkeypatch):
    monkeypatch.setattr(fc, "http", lambda m, u, **k: FakeResp(sample("kho_arkisto.html")))
    lst = fc.fetch_lift_list("x", r"https://www\.kho\.fi/paatokset/kho\d+/", "KHO")
    assert [x["ref"] for x in lst] == ["KHO:2026:83", "KHO:2026:82", "KHO:2026:81"]
    assert lst[0]["date"] == "2026-10-13" and lst[0]["url"] == "https://www.kho.fi/paatokset/kho202683/"
    assert lst[0]["keywords"] == ["Henkilökohtaisen tulon verotus", "Osakaslaina", "Ulkomainen osakeyhtiö"]


def test_rss_feed(monkeypatch):
    monkeypatch.setattr(fc, "http", lambda m, u, **k: FakeResp(sample("rss_kko.xml")))
    lst = fc.fetch_rss("www.korkeinoikeus.fi", "KKO")
    assert [x["ref"] for x in lst] == ["KKO:2026:75", "KKO:2026:74", "KKO:2026:73"]  # Swedish HD: items dropped
    assert lst[0]["date"] == "2026-10-16" and "/sv/" not in lst[0]["url"]
    assert lst[1]["keywords"] == ["Pakkokeino", "Tutkintavankeus", "Tutkintavangin sijoittaminen"]


# ---------- Finlex ----------

def test_finlex_listing():
    lst = fc.finlex_parse_list(sample("finlex_hovioikeudet_2026_listing.html"))
    assert len(lst) == 4  # the page also lists 5 newest statutes in a sidebar with the same component; only /oikeuskaytanto/ links are kept
    dec = lst
    assert dec[0]["number"] == "Helsingin HO 23.9.2026 542" and dec[0]["href"] == "/fi/oikeuskaytanto/hovioikeudet/2026/helsinki/542"
    assert dec[1]["keywords"] == ["Oikeudenkäynnin julkisuus", "Tietosuoja", "Väliintulo"]
    assert fc.iso(dec[0]["number"]) == "2026-09-23"


def test_finlex_decision(cfg, resolver):
    p = fc.finlex_parse_decision(sample("finlex_kko_2026_74.html"))
    assert p["pageTitle"].startswith("KKO:2026:74 | 7.10.2026")
    assert p["meta"]["Antopäivä"] == "2026-10-07" and p["meta"]["ECLI-tunnus"] == "ECLI:FI:KKO:2026:74"
    assert p["refLines"][0] == "TutkintavankeusL 2 luku 1 § 3 mom"
    base = {"ref": "KKO:2026:74", "url": "u", "keywords": ["Pakkokeino", "Tutkintavankeus - Tutkintavangin sijoittaminen"]}
    rec = fc._normalise("KKO", cfg["courts"]["KKO"], cfg, resolver, base, p, finlex_page=True, href="/fi/oikeuskaytanto/korkein-oikeus/ennakkopaatokset/2026/74")
    assert rec["date"] == "2026-10-07" and rec["diaari"] == "R 1/2025/352" and rec["taltio"] == "1052 1715"
    assert rec["statutes"] == [{"sk": "768/2005", "section": "2 luku 1 § 3 mom"}]
    assert "rawRefs" not in rec  # the Swedish duplicate line is ignored, not reported as unknown
    assert rec["citedCases"][:1] == ["KKO:2020:66"] and rec["keywords"][0] == "Pakkokeino"


# ---------- statute references and ids ----------

def test_statute_resolution(resolver):
    refs, raw = resolver.resolve_lines(["RL 24 luku 12 §", "Tuloverolaki 53 a §", "Laki eläkkeensaajan asumistuesta 5 § ja 9 §",
                                        "HankintaL 93 § 2 mom", "Euroopan ihmisoikeussopimus 6 artikla", "XyzL 3 §"])
    assert {"sk": "39/1889", "section": "24 luku 12 §"} in refs
    assert {"sk": "1535/1992", "section": "53 a §"} in refs
    assert {"sk": "571/2007", "section": "5 §"} in refs and {"sk": "571/2007", "section": "9 §"} in refs
    assert {"sk": "1397/2016", "section": "93 § 2 mom"} in refs
    assert raw == ["Euroopan ihmisoikeussopimus 6 artikla", "XyzL 3 §"]
    text = ("Kysymys tietosuojalain 27 §:ssä tarkoitetusta käsittelystä ja oikeudenkäymiskaaren 7 luvun 3 §:n mukaisesta "
            "turvaamistoimesta sekä julkisista hankinnoista ja käyttöoikeussopimuksista annetun lain 93 §:n ja "
            "sähköisen viestinnän palveluista annetun lain (917/2014) 200 §:n soveltamisesta.")
    t = resolver.resolve_text(text)
    assert {"sk": "1050/2018", "section": "27 §"} in t
    assert {"sk": "4/1734", "section": "7 luku 3 §"} in t
    assert {"sk": "1397/2016", "section": "93 §"} in t
    assert {"sk": "917/2014", "section": "200 §"} in t
    merged, _ = resolver.resolve(["TutkintavankeusL 2 luku 1 § 3 mom"], "tutkintavankeuslain 2 luvun 1 §:n 3 momentissa")
    assert merged == [{"sk": "768/2005", "section": "2 luku 1 § 3 mom"}]


def test_ids():
    assert fc.make_id("KKO", "KKO:2026:45") == "r-kko-2026-45"
    assert fc.make_id("KHO", "KHO:2026:120") == "r-kho-2026-120"
    assert fc.make_id("KHO", "KHO 29.9.2026/2501") == "r-kho-2026-t2501"
    assert fc.make_id("TT", "TT 2026:12") == "r-tt-2026-12"
    assert fc.make_id("VakO", "VakO 1642:2025") == "r-vako-1642-2025"
    assert fc.make_id("MAO", "MAO:482/2026") == "r-mao-482-2026"
    assert fc.make_id("HO", "Helsingin HO 7.9.2026 1064 0647", "/fi/oikeuskaytanto/hovioikeudet/2026/helsinki/10640647") == "r-ho-2026-helsinki-10640647"
    assert fc.make_id("HaO", "Turun HAO 6.10.2026 1971/2026", "/fi/oikeuskaytanto/hallinto-oikeudet/2026/turku/1971") == "r-hao-2026-turku-1971"
    assert build_ratkaisut.case_id("eut", "C-123/25") == "r-eut-c-123-25"
    assert build_ratkaisut.case_id("eut-ag", "C-123/25") == "r-eut-ag-c-123-25"
    assert build_ratkaisut.case_id("erp", "C-123/26") == "r-erp-c-123-26"
    assert fcu.case_no("62025CC0390") == "C-390/25" and fcu.case_no("62025TN0184") == "T-184/25" and fcu.case_no("32016R0679") is None


# ---------- CJEU ----------

def test_cellar_rows():
    rows = json.loads(sample("cellar_recent.json"))["results"]["bindings"]
    cases = fcu.rows_to_cases(rows)
    j = cases["62024CJ0580"]
    assert j["caseNo"] == "C-580/24" and j["type"] == "JUDG" and j["date"] == "2026-10-15" and j["countries"] == ["BGR"]
    assert set(j["subjects"]) == {"COJP", "COPO"} and j["ecli"] == "ECLI:EU:C:2026:865"
    parts = fcu.parse_case_title(j["title"])
    assert parts["parties"] == "Sofiyska gradska prokuratura vastaan LY" and parts["caseLabel"] == "Asia C-580/24"
    assert fcu.nominative_court(parts["referring"]) == "Sofiyski gradski sad"
    assert parts["keywords"].startswith("Ennakkoratkaisupyyntö – Oikeudellinen yhteistyö rikosasioissa")
    ag = cases["62024CC0627"]
    assert ag["type"] == "OPIN_AG" and ag["countries"] == [] and fcu.parse_case_title(ag["title"]) == {"heading": "Julkisasiamies A. Biondi ratkaisuehdotus 15.10.2026."}
    assert fcu.nominative_court("Korkeimman hallinto-oikeuden esittämä ennakkoratkaisupyyntö") == "Korkein hallinto-oikeus"
    assert fcu.nominative_court("Helsingin käräjäoikeuden esittämä ennakkoratkaisupyyntö") == "Helsingin käräjäoikeus"


def test_reference_notice():
    rows = json.loads(sample("cellar_references.json"))["results"]["bindings"]
    titles = [b["title_fi"]["value"].replace("\xa0", " ") for b in rows]
    parsed = [fcu.REF_TITLE.match(t) for t in titles]
    assert all(parsed), titles
    first = parsed[0].groupdict()
    assert first == {"case": "C-463/26", "name": "Järvehi", "court": "Korkein oikeus", "lodged": "11.5.2026", "parties": "A osakeyhtiö v. B:n kaupunki"}
    assert fcu.parse_fi_dmy("28. helmikuuta 2025") == "2025-02-28" and fcu.parse_fi_dmy("11.5.2026") == "2026-05-11"
    n = fcu.parse_reference_notice(fcu.text_of(sample("oj_c_2026_3644_fi.xhtml")))
    assert n["referringCourt"] == "Korkein oikeus"
    assert n["parties"] == "Valittaja: A osakeyhtiö Vastapuoli: B:n kaupunki"
    assert n["questions"].startswith("1) a) Onko direktiivin 2011/7 6 artiklan 1 kohtaa") and "2) Onko direktiivin 6 artiklan" in n["questions"]
    assert len(n["questions"]) <= 1200 and n["acts"] == ["32011L0007"]
    assert fcu.acts_in_text("asetus (EU) 2016/679, neuvoston asetus (EY) N:o 1/2003, direktiivi 95/46/EY") == ["32016R0679", "32003R0001", "31995L0046"]


# ---------- build ----------

def test_build_shape(tmp_path, monkeypatch):
    caselaw = {"fetched": "2026-10-18T00:00:00Z", "health": {"KKO": {"ok": True, "n": 30}},
               "decisions": {
                   "r-kko-2026-75": {"court": "KKO", "kind": "Ennakkopäätös", "ref": "KKO:2026:75", "ecli": "ECLI:FI:KKO:2026:75", "date": "2026-10-16",
                                     "keywords": ["Törkeä kotirauhan rikkominen", "Syyteoikeus"], "abstract": "A oli yrittänyt tunkeutua asuntoon. " * 30,
                                     "statutes": [{"sk": "39/1889", "section": "24 luku 12 §"}], "url": "https://www.korkeinoikeus.fi/x", "finlexUrl": "https://www.finlex.fi/y"},
                   "r-hao-2026-turku-1971": {"court": "HaO", "kind": "Ratkaisu", "ref": "Turun HAO 6.10.2026 1971/2026", "date": "2026-10-06", "courtUnit": "Turun HAO",
                                             "keywords": ["Kansainvälistä suojelua koskeva asia"], "abstract": "Hakija oli alaikäinen.", "statutes": [{"sk": "301/2004", "section": "6 §"}],
                                             "url": "https://www.finlex.fi/fi/oikeuskaytanto/hallinto-oikeudet/2026/turku/1971"},
                   "r-mao-9-2020": {"court": "MAO", "kind": "Ratkaisu", "ref": "MAO:9/2020", "date": "2020-01-10", "keywords": ["patentti"], "url": "u"},
               }}
    curia = {"fetched": "2026-10-18T00:00:00Z",
             "cases": {
                 "62024CJ0232": {"celex": "62024CJ0232", "caseNo": "C-232/24", "type": "JUDG", "date": "2026-10-01", "court": "C", "ecli": "ECLI:EU:C:2026:1",
                                 "countries": ["FIN"], "procedure": ["PREJ"], "subjects": ["TVA"], "subjectsFi": ["Arvonlisävero"], "interprets": ["32006L0112"],
                                 "title": "x", "parties": "A Oy vastaan Veronsaajien oikeudenvalvontayksikkö", "keywords": "Ennakkoratkaisupyyntö – Verotus – Arvonlisävero",
                                 "referringCourt": "Korkein hallinto-oikeus", "fi": True, "why": ["FIN"], "operative": "Direktiivin 2006/112 2 artiklaa on tulkittava siten…",
                                 "links": {"curia": "https://curia.europa.eu/juris/documents.jsf?num=C-232/24&language=fi", "eurlex": "e"}},
                 "62025CC0390": {"celex": "62025CC0390", "caseNo": "C-390/25", "type": "OPIN_AG", "date": "2026-10-08", "court": "C", "countries": [], "procedure": [],
                                 "subjects": [], "interprets": [], "title": "Julkisasiamies A. Biondi ratkaisuehdotus 8.10.2026.###", "fi": True, "why": ["ennakkoratkaisupyyntö"],
                                 "referringCourt": "Korkein hallinto-oikeus", "links": {"curia": "c", "eurlex": "e"}},
             },
             "references": {
                 "C-390/25": {"caseNo": "C-390/25", "celex": "62025CN0390", "oj": "C/2025/4439", "published": "2025-08-18", "lodged": "2025-06-13", "name": "HUS-yhtymä",
                              "referringCourt": "Korkein hallinto-oikeus", "parties": "HUS-yhtymä", "questions": "Onko direktiivin 2014/24/EU 67 artiklaa tulkittava…",
                              "acts": ["32014L0024"], "url": "https://eur-lex.europa.eu/eli/C/2025/4439/oj/fin", "curia": "c", "status": "vireillä", "agCelex": "62025CC0390", "agDate": "2026-10-08"},
             }}
    (tmp_path / "caselaw.json").write_text(json.dumps(caselaw), encoding="utf-8")
    (tmp_path / "curia.json").write_text(json.dumps(curia), encoding="utf-8")
    monkeypatch.setattr(build_ratkaisut, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(build_ratkaisut, "OUT", tmp_path / "ratkaisut.json")
    items = [{"id": "fi-he-1-2026", "scope": "fi", "sk": ["39/1889", "40/2026"]}, {"id": "fi-he-2-2026", "scope": "fi", "sk": ["1/2026"]},
             {"id": "eu-2020-0001", "scope": "eu", "celex": "32006L0112"}, {"id": "eu-2020-0002", "scope": "eu", "celex": "32014L0024"}]
    res = build_ratkaisut.build_ratkaisut(items)
    payload, by_item = res["payload"], res["byItem"]
    assert set(payload) >= {"generated", "counts", "items"}
    written = json.loads((tmp_path / "ratkaisut.json").read_text(encoding="utf-8"))
    assert written["counts"] == payload["counts"]
    ids = {r["id"] for r in payload["items"]}
    assert ids == {"r-kko-2026-75", "r-hao-2026-turku-1971", "r-eut-c-232-24", "r-eut-ag-c-390-25", "r-erp-c-390-25"}  # MAO:9/2020 aged out
    assert payload["counts"]["kko"] == 1 and payload["counts"]["hao"] == 1 and payload["counts"]["eut"] == 1
    assert payload["counts"]["eut_ag"] == 1 and payload["counts"]["erp_vireilla"] == 1 and payload["counts"]["mao"] == 0
    by_id = {r["id"]: r for r in payload["items"]}
    for r in payload["items"]:
        assert r["scope"] == "ratkaisu" and DATE.match(r["date"]) and isinstance(r["fi"], bool) and isinstance(r["topics"], list) and r["topics"]
        assert r["court"] in {"KKO", "KHO", "HO", "HaO", "TT", "VakO", "MAO", "EUT"} and r["courtName"] and r["kind"] and r["title"] and r["status"]
        assert len(r["summary"]) <= 600 and isinstance(r["links"], dict) and r["url"]
        assert re.match(r"^r-(kko|kho|ho|hao|tt|vako|mao|eut-ag|eut|erp)-", r["id"])
    kko = by_id["r-kko-2026-75"]
    assert kko["related"] == ["fi-he-1-2026"] and kko["fi"] is True and kko["kind"] == "Ennakkopäätös" and kko["links"]["finlex"] == "https://www.finlex.fi/y"
    assert kko["title"] == "Törkeä kotirauhan rikkominen – Syyteoikeus" and "Rikos ja prosessi" in kko["topics"]
    assert by_id["r-hao-2026-turku-1971"]["courtName"] == "Turun hallinto-oikeus" and "related" not in by_id["r-hao-2026-turku-1971"]
    eut = by_id["r-eut-c-232-24"]
    assert eut["related"] == ["eu-2020-0001"] and eut["statutes"] == [{"celex": "32006L0112"}] and eut["referringCourt"] == "Korkein hallinto-oikeus"
    assert eut["fi"] is True and eut["kind"] == "Tuomio" and eut["summary"].startswith("Direktiivin 2006/112") and "Verotus" in eut["topics"]
    erp = by_id["r-erp-c-390-25"]
    assert erp["kind"] == "Ennakkoratkaisupyyntö" and erp["status"] == "vireillä" and erp["date"] == "2025-06-13" and erp["related"] == ["eu-2020-0002"]
    assert erp["agId"] == "r-eut-ag-c-390-25" and erp["fi"] is True
    assert by_item["fi-he-1-2026"] == [{"id": "r-kko-2026-75", "court": "KKO", "date": "2026-10-16", "title": "Törkeä kotirauhan rikkominen – Syyteoikeus"}]
    assert set(by_item) == {"fi-he-1-2026", "eu-2020-0001", "eu-2020-0002"}
    dates = [r["date"] for r in payload["items"]]
    assert dates == sorted(dates, reverse=True)


def test_samples_small():
    assert sum(f.stat().st_size for f in S.iterdir()) <= 400_000
