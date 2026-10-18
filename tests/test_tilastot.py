"""Tilastokerros (kertyvä data → todennäköisyydet): aggregations of scripts/build_tilastot.py on small synthetic
caches, the history bookkeeping of scripts/fetch_history.py with injected fetchers, and the Finlex / kkv.fi parsers
on trimmed samples in tests/samples/tilastot/. No network, no repo caches."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_tilastot as bt  # noqa: E402
import fetch_history as fh  # noqa: E402

S = ROOT / "tests" / "samples" / "tilastot"
TODAY = "2026-10-18"


def sample(name: str) -> str:
    return (S / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ synthetic caches
def he(num: str, anto: str, report: str | None, committee: str, approval: str | None = None, vahv: str | None = None) -> dict:
    stages = [{"code": "ANTO", "committee": None, "date": anto}]
    if report:
        stages.append({"code": "VKPM", "committee": committee, "date": report})
    if approval:
        stages.append({"code": "2K", "committee": None, "date": approval})
    return {"he": num, "stages": stages, "committees": [committee], "vahvistettu": vahv}


def report(tunnus: str, asia: str, committee: str, decision: str, dissent: int = 0, kind: str = "mietintö") -> dict:
    return {"asia": asia, "committee": committee[:3], "committeeName": committee, "date": "2026-09-01", "decision": decision, "dissent": dissent, "kind": kind}


def project(tunnus: str, ministry: str, *, he_num: str | None = None, annettu: str | None = None, week=None, year=2026, vanha=None, vanha_year=None,
            poistettu=None, lausunnot: int | None = None, consultation: tuple[str, str] | None = None) -> dict:
    return {"tunnus": tunnus, "ministerio": ministry, "heNumerot": [f"HE {he_num}"] if he_num else [], "annettuEduskunnalle": annettu,
            "esittelyviikko": week, "esittelyvuosi": year if week else None, "vanhaEsittelyviikko": vanha, "vanhaEsittelyvuosi": vanha_year,
            "poistettuPaiva": poistettu, "heTila": "POISTETTU_ISTUNTOKAUDEN_AIKANA" if poistettu else None,
            "lausunnot": {"n": lausunnot} if lausunnot is not None else None,
            "etapit": [{"tyyppi": "LAUSUNTOKIERROS", "date": consultation[0], "end": consultation[1]}] if consultation else []}


EDUSKUNTA = {"items": {
    "1/2026": he("1/2026", "2026-01-10", "2026-03-11", "hallintovaliokunta", "2026-03-21", "2026-04-10"),   # 60 / 70 / 90 days
    "2/2026": he("2/2026", "2026-01-10", "2026-02-19", "hallintovaliokunta", "2026-03-01", "2026-03-11"),   # 40 / 50 / 60
    "3/2026": he("3/2026", "2026-01-10", "2026-03-31", "hallintovaliokunta", "2026-04-20", "2026-05-20"),   # 80 / 100 / 130
    "4/2026": he("4/2026", "2026-02-01", "2026-03-03", "talousvaliokunta", None, None),                       # 30 / – / –
    "5/2026": he("5/2026", "2026-02-01", None, "talousvaliokunta"),
}}
VASKI = {"reports": {
    "HaVM 1/2026 vp": report("HaVM 1/2026 vp", "HE 1/2026 vp", "hallintovaliokunta", "muutettuna", 1),
    "HaVM 2/2026 vp": report("HaVM 2/2026 vp", "HE 2/2026 vp", "hallintovaliokunta", "muutettuna"),
    "HaVM 3/2026 vp": report("HaVM 3/2026 vp", "HE 3/2026 vp", "hallintovaliokunta", "muuttamattomana"),
    "HaVM 4/2026 vp": report("HaVM 4/2026 vp", "HE 9/2026 vp", "hallintovaliokunta", "muu"),  # not decided -> not in nReports
    "TaVM 1/2026 vp": report("TaVM 1/2026 vp", "HE 4/2026 vp", "talousvaliokunta", "muutettuna"),
    "HaVL 1/2026 vp": report("HaVL 1/2026 vp", "U 1/2026 vp", "hallintovaliokunta", "muu", kind="lausunto"),
}}
HANKEIKKUNA = {"items": [
    project("VM1:00/2025", "valtiovarainministeriö", he_num="1/2026", annettu="2026-01-10", week=2, lausunnot=10, consultation=("2026-06-01", "2026-07-13")),
    project("VM2:00/2025", "valtiovarainministeriö", he_num="2/2026", annettu="2026-01-10", week=2, vanha=50, vanha_year=2025, lausunnot=30, consultation=("2026-06-01", "2026-07-01")),
    project("VM3:00/2025", "valtiovarainministeriö", he_num="3/2026", annettu="2026-01-10", week=2, vanha=1, vanha_year=2026, lausunnot=20, consultation=("2026-06-01", "2026-08-01")),
    project("VM4:00/2025", "valtiovarainministeriö", week=45, vanha=40),
    project("VM5:00/2025", "valtiovarainministeriö", week=46, poistettu="2026-10-01"),
    project("TEM1:00/2025", "työ- ja elinkeinoministeriö", he_num="4/2026", annettu="2026-02-01", week=5),
    project("TEM2:00/2025", "työ- ja elinkeinoministeriö", he_num="5/2026", annettu="2026-02-01", week=5),
]}


def ruling(num: str, date: str, outcome: str, respondent: str, category: str | None = None, interim: bool = False) -> dict:
    return {"number": num, "date": date, "outcome": outcome, "respondent": respondent, "appellant": "X Oy", "category": category, "interim": interim}


MAO_HISTORY = {"items": {
    "MAO:1/2026": ruling("MAO:1/2026", "2026-03-01", "valitus hylätty", "Oulun kaupunki", "ICT ja ohjelmistot"),
    "MAO:2/2026": ruling("MAO:2/2026", "2026-04-01", "hankintapäätös kumottu", "Oulun kaupunki", "ICT ja ohjelmistot"),
    "MAO:3/2026": ruling("MAO:3/2026", "2026-05-01", "jätetty tutkimatta", "Oulun kaupunki", "Rakentaminen ja infra"),
    "MAO:4/2026": ruling("MAO:4/2026", "2026-06-01", "hyvitysmaksu", "Espoon kaupunki", "ICT ja ohjelmistot"),
    "MAO:5/2026": ruling("MAO:5/2026", "2026-06-02", "välipäätös: keskeytysvaatimus hylätty", "Espoon kaupunki", None, interim=True),
}}
MAO_CACHE = {"decisions": {
    "MAO:6/2026": {"number": "MAO:6/2026", "date": "2026-09-01", "outcome": "valitus hylätty", "respondent": "Vantaan kaupunki", "category": "hankinta"},
    "MAO:7/2026": {"number": "MAO:7/2026", "date": "2026-09-02", "outcome": "esitys hylätty", "respondent": "KKV", "category": "kilpailu"},
}, "pending": {
    "k1": {"key": "k1", "filed": "2026-10-01", "buyer": "Oulun kaupunki", "decisionDate": "2026-09-20"},
    "k2": {"key": "k2", "filed": "2026-10-05", "buyer": "Oulun kaupunki", "decisionDate": "2026-09-25"},
    "k3": {"key": "k3", "filed": "2026-06-01", "buyer": "Oulun kaupunki", "decisionDate": "2026-05-20"},  # older than 90 days
}}
APPEALS_HISTORY = {"items": {
    "a1": {"key": "a1", "filed": "2025-12-01", "buyer": "Oulun kaupunki", "decision": "MAO:1/2026"},   # 90 days to ruling
    "a2": {"key": "a2", "filed": "2026-01-01", "buyer": "Oulun kaupunki", "decision": "MAO:2/2026"},   # 90
    "a3": {"key": "a3", "filed": "2026-01-01", "buyer": "Oulun kaupunki", "decision": "MAO:3/2026"},   # 120
    "a4": {"key": "a4", "filed": "2026-09-30", "buyer": "Espoon kaupunki"},
}}
KKV_HISTORY = {"items": {
    f"KKV/{i}/14.00.10/2026": {"diaari": f"KKV/{i}/14.00.10/2026", "notified": d[:4] + "-03-01", "decided": d, "phase": ph, "outcome": o, "sector": s}
    for i, (d, ph, o, s) in enumerate([("2026-03-15", 1, "hyväksytty", "Kauppa"), ("2026-03-20", 1, "hyväksytty", "Kauppa"), ("2026-03-25", 1, "ehdoin", "Kauppa"),
                                        ("2026-07-01", 2, "ehdoin", "Terveys- ja sosiaalipalvelut"), ("2026-08-01", 2, "kielletty", "Terveys- ja sosiaalipalvelut"),
                                        ("2026-06-01", 2, "esitys MAO", "Terveys- ja sosiaalipalvelut"), ("2023-05-01", 1, "hyväksytty", "Kauppa")], start=1)
}}
KKV_CACHE = {"cases": {
    "KKV/900/14.00.10/2026": {"diaari": "KKV/900/14.00.10/2026", "notified": "2026-10-01", "decided": "2026-10-12", "decision": "Yrityskaupan hyväksyminen sellaisenaan", "pending": False},
    "KKV/901/14.00.10/2026": {"diaari": "KKV/901/14.00.10/2026", "notified": "2026-10-10", "pending": True},
}}
SOPIMUSKAUDET = {"notices": {
    "1": {"id": "EF-1", "noticeId": 1, "buyer": "A", "cpv": "72000000", "contractStart": "2026-01-01", "contractEnd": "2029-01-01", "durationMonths": 36},
    "2": {"id": "EF-2", "noticeId": 2, "buyer": "A", "cpv": "72260000 48000000", "contractStart": "2026-01-01", "contractEnd": "2028-01-01", "durationMonths": 24},
    "3": {"id": "EF-3", "noticeId": 3, "buyer": "B", "cpv": "72500000", "contractStart": "2026-01-01", "contractEnd": "2030-01-01", "durationMonths": None},  # 48 from dates
    "4": {"id": "EF-4", "noticeId": 4, "buyer": "B", "cpv": "45000000", "contractStart": "2026-01-01", "contractEnd": "2026-07-01", "durationMonths": 6},
    "5": {"id": "OLD-5", "contractEnd": None, "skip": "ei sopimuskautta"},
}}
HANKINNAT_CACHE = {"items": [
    {"id": "EF-10", "datePublished": "2026-10-01T10:00:00Z", "deadline": "2026-10-31T21:59:00Z", "cpvCodes": "72000000"},
    {"id": "EF-11", "datePublished": "2026-10-01T10:00:00Z", "deadline": "2026-10-21T21:59:00Z", "cpvCodes": "72200000 48000000"},
    {"id": "EF-12", "datePublished": "2026-10-01T10:00:00Z", "deadline": "2026-11-10T21:59:00Z", "cpvCodes": "72300000"},
    {"id": "EF-13", "datePublished": "2026-10-01T10:00:00Z", "deadline": "2026-10-15T21:59:00Z", "cpvCodes": "45000000"},
]}
REGDEL = {"acts": {
    "1": {"delegatedActStatus": "PUBLISHED", "adoption": "2026-01-10", "publication": "2026-02-01", "events": [], "deadlines": [{"type": "ORIGINAL", "institution": "PARLIAMENT", "months": 2.0}]},
    "2": {"delegatedActStatus": "PUBLISHED", "adoption": "2026-01-10", "publication": "2026-03-25", "events": [], "deadlines": [{"type": "ORIGINAL", "institution": "PARLIAMENT", "months": 2.0}]},
    "3": {"delegatedActStatus": "PUBLISHED", "adoption": "2026-01-10", "publication": "2026-05-25", "events": [{"type": "DA_EXTENSION", "date": "2026-03-01", "months": 2.0}],
          "deadlines": [{"type": "ORIGINAL", "institution": "PARLIAMENT", "months": 2.0}, {"type": "EXTENDEND", "institution": "PARLIAMENT", "months": 2.0}]},
    "4": {"delegatedActStatus": "ADOPTED", "adoption": "2026-09-10", "publication": None, "events": [], "deadlines": [{"type": "ORIGINAL", "institution": "PARLIAMENT", "months": 3.0}]},
}, "skip": {"10": "PUBLISHED", "11": "PUBLISHED", "12": "OBJECTED", "13": "WITHDRAWN", "14": "CANCELLED", "15": "PUBLISHED", "16": "NOTIFIED"}}


@pytest.fixture(scope="module")
def stats():
    history = {"mao": MAO_HISTORY, "kkv": KKV_HISTORY, "awards": {"items": {}}, "appeals": APPEALS_HISTORY}
    return bt.compute([], [], eduskunta=EDUSKUNTA, hankeikkuna=HANKEIKKUNA, vaski=VASKI, mao=MAO_CACHE, kkv=KKV_CACHE, sopimuskaudet=SOPIMUSKAUDET,
                      hankinnat=HANKINNAT_CACHE, regdel=REGDEL, history=history, today=TODAY)


# ------------------------------------------------------------------ helpers
def test_quantiles_shares_and_min_n():
    assert bt.quantiles([10, 20, 30, 40, 50]) == {"median": 30, "p25": 20, "p75": 40, "n": 5}
    assert bt.quantiles([7, 9]) == {"median": None, "p25": None, "p75": None, "n": 2}
    assert bt.median([3, 1, 2]) == {"median": 2, "n": 3} and bt.median([1, 2]) == {"median": None, "n": 2}
    assert bt.share(1, 2) is None and bt.share(1, 4) == 0.25
    assert bt.he_key("HE 248/2026 vp") == "248/2026" and bt.he_key("HE 007/2026") == "7/2026" and bt.he_key(None) is None
    assert bt.cpv_division("72000000 48000000") == "72" and bt.cpv_division("") is None
    assert bt.week_delta("2026-10-15", 42, 2026) == 0 and bt.week_delta("2026-11-05", 42, 2026) == 3 and bt.week_delta("2026-10-15", 60, 2026) is None
    assert bt.weeks_between(2025, 50, 2026, 2) == 4   # 2025 has 52 ISO weeks
    assert bt.buyer_keys("Helsingin kaupunki – Stara") == ["helsingin stara", "helsingin"]   # the entity first, then the city behind it
    assert "helsingin" in bt.buyer_keys("Helsingin kaupungin liikennelaitos")


# ------------------------------------------------------------------ eduskunta
def test_eduskunta_overall_and_committees(stats):
    ov = stats["eduskunta"]["overall"]
    assert ov["n"] == 5 and ov["since"] == "2026-01-10"
    assert ov["heToReport"] == {"median": 50, "p25": 38, "p75": 65, "n": 4}  # 60, 40, 80, 30 -> inclusive quartiles
    assert ov["heToApproval"]["median"] == 70 and ov["heToApproval"]["n"] == 3
    assert ov["heToConfirmation"]["median"] == 90
    assert ov["reportChangedShare"] == 0.75 and ov["nReports"] == 4   # 3 muutettuna of 4 decided; 'muu' and the lausunto do not count
    assert ov["dissentShare"] == 0.2                                   # 1 of 5 mietintö rows with a dissent count
    hv = stats["eduskunta"]["byCommittee"]["hallintovaliokunta"]
    assert hv["n"] == 3 and hv["heToReport"]["median"] == 60 and hv["reportChangedShare"] == round(2 / 3, 3) and hv["nReports"] == 3
    tv = stats["eduskunta"]["byCommittee"]["talousvaliokunta"]
    assert tv["n"] == 1 and tv["heToReport"]["median"] is None and tv["heToReport"]["n"] == 1 and tv["reportChangedShare"] is None


def test_eduskunta_by_ministry_joins_hankeikkuna(stats):
    vm = stats["eduskunta"]["byMinistry"]["valtiovarainministeriö"]
    assert vm["n"] == 3 and vm["heToReport"]["median"] == 60 and vm["heToApproval"]["median"] == 70
    assert vm["reportChangedShare"] == round(2 / 3, 3) and vm["nReports"] == 3
    assert vm["statementsMedian"] == {"median": 20, "n": 3}
    assert vm["consultationDaysMedian"] == {"median": 42, "n": 3}   # 42, 30, 61
    tem = stats["eduskunta"]["byMinistry"]["työ- ja elinkeinoministeriö"]
    assert tem["n"] == 2 and tem["heToReport"]["median"] is None and tem["statementsMedian"] == {"median": None, "n": 0}


# ------------------------------------------------------------------ lainsäädäntösuunnitelma
def test_plan_slip_and_on_time(stats):
    s = stats["suunnitelma"]
    assert s["n"] == 7 and s["nGiven"] == 5
    # given: VM1 week 2 (on time), VM2 planned 50/2025 -> given week 2/2026 (+4, late), VM3 planned 1 -> week 2 (+1, on time), TEM1, TEM2 week 5 (on time)
    assert s["onTimeShare"] == 0.8
    assert s["slippedShare"] == round(3 / 7, 3) and s["nSlipped"] == 3
    assert s["medianSlipWeeks"] == 4          # +4, +1, +5 (VM4: 40 -> 45)
    assert s["droppedShare"] == round(1 / 7, 3)
    vm = s["byMinistry"]["valtiovarainministeriö"]
    assert vm["n"] == 5 and vm["onTimeShare"] == round(2 / 3, 3)
    tem = s["byMinistry"]["työ- ja elinkeinoministeriö"]
    assert tem["onTimeShare"] is None and tem["nGiven"] == 2       # below MIN_N


# ------------------------------------------------------------------ markkinaoikeus
def test_mao_outcomes_upheld_and_groups(stats):
    m = stats["mao"]
    assert m["n"] == 5 and m["nInterim"] == 1 and m["since"] == "2026-03-01"   # history 4 final + cache 1 hankinta; the kilpailu ruling is ignored
    assert m["outcomes"] == {"valitus hylätty": 0.4, "hankintapäätös kumottu": 0.2, "jätetty tutkimatta": 0.2, "hyvitysmaksu": 0.2}
    assert m["upheldShare"] == 0.4
    assert m["byCategory"]["ICT ja ohjelmistot"] == {"n": 3, "upheldShare": round(2 / 3, 3)}
    assert m["byCategory"]["Rakentaminen ja infra"] == {"n": 1, "upheldShare": None}
    assert list(m["byBuyer"]) == ["Oulun kaupunki"] and m["byBuyer"]["Oulun kaupunki"]["n"] == 3 and m["byBuyer"]["Oulun kaupunki"]["upheldShare"] == round(1 / 3, 3)
    assert m["medianDaysFiledToRuling"] == {"median": 90, "n": 3}
    assert m["appealsPerBuyer90"] == {"Oulun kaupunki": 2, "Espoon kaupunki": 1} and m["appeals90"] == 3
    assert m["nAppeals"] == 7


def test_mao_thin_data_gives_none():
    m = bt.mao_stats({"items": {"MAO:1/2026": ruling("MAO:1/2026", "2026-03-01", "valitus hylätty", "X")}}, {}, {}, dt.date(2026, 10, 18))
    assert m["n"] == 1 and m["outcomes"] == {} and m["upheldShare"] is None and m["byBuyer"] == {} and m["medianDaysFiledToRuling"]["median"] is None


# ------------------------------------------------------------------ KKV
def test_kkv_phase_shares_and_days(stats):
    k = stats["kkv"]
    assert k["n"] == 7 and k["since"] == "2026-03-15"        # the 2023 case is before KKV_SINCE; the pending one is not decided
    assert k["nPending"] == 1
    assert k["phase2Share"] == round(3 / 7, 3) and k["conditionsShare"] == round(2 / 7, 3) and k["prohibitedShare"] == round(2 / 7, 3)
    assert k["medianDaysPhase1"] == {"median": 16, "n": 4}    # 14, 19, 24 and the cache case 11
    assert k["medianDaysPhase2"] == {"median": 122, "n": 3}   # 122, 153, 92
    assert k["bySector"]["Kauppa"] == {"n": 3, "phase2Share": 0.0}
    assert k["bySector"]["Terveys- ja sosiaalipalvelut"] == {"n": 3, "phase2Share": 1.0}
    assert k["outcomes"]["hyväksytty"] == round(3 / 7, 3)


# ------------------------------------------------------------------ hankinnat
def test_contract_months_grouped_by_cpv_division(stats):
    h = stats["hankinnat"]
    assert h["contractMonthsByCpv"]["72"] == {"median": 36, "p25": 30, "p75": 42, "n": 3}   # 36, 24, 48 (from the dates)
    assert h["contractMonthsByCpv"]["45"] == {"median": None, "p25": None, "p75": None, "n": 1}
    assert h["tenderDaysByCpv"]["72"] == {"median": 30, "p25": 25, "p75": 35, "n": 3}       # 30, 20, 40
    assert h["tenderDaysByCpv"]["45"]["n"] == 1 and h["tenderDaysByCpv"]["45"]["median"] is None
    assert h["retenderCadenceByBuyer"] is None and h["nAwards"] == 4 and h["nOpen"] == 4


def test_retender_cadence_needs_three_awards_over_a_year():
    thin = {"items": {str(i): {"noticeId": str(i), "buyer": "Kuopion kaupunki", "buyerId": "0171450-7", "cpv": "90910000", "contractStart": f"2026-0{i}-01"} for i in (1, 2, 3)}}
    assert bt.hankinnat_stats(thin, {}, {}, [])["retenderCadenceByBuyer"] is None   # three starts within two months are not a cycle
    long = {"items": {str(y): {"noticeId": str(y), "buyer": "Kuopion kaupunki", "buyerId": "0171450-7", "cpv": "90910000", "contractStart": f"{y}-01-01"} for y in (2020, 2023, 2026)}}
    assert bt.hankinnat_stats(long, {}, {}, [])["retenderCadenceByBuyer"] == {"Kuopion kaupunki": {"n": 3, "medianMonths": 36}}


# ------------------------------------------------------------------ delegoidut
def test_delegated_acts(stats):
    d = stats["delegoidut"]
    assert d["n"] == 9 and d["statuses"] == {"PUBLISHED": 6, "OBJECTED": 1, "WITHDRAWN": 1, "CANCELLED": 1}   # 3 published acts + 6 closed in skip
    assert d["objectedShare"] == round(1 / 9, 3) and d["withdrawnShare"] == round(2 / 9, 3)
    assert d["medianObjectionMonths"] == {"median": 2.0, "n": 4}
    assert d["earlyNonObjectionShare"] == round(1 / 3, 3) and d["nPublished"] == 3    # act 1 published 22 days after adoption
    assert d["extendedShare"] == 0.25


# ------------------------------------------------------------------ context sentences
def test_context_for_he(stats):
    item = {"id": "fi-he-1-2026", "scope": "fi", "laji": "laki", "kind": "HE", "heNumerot": ["1/2026"], "ministry": "valtiovarainministeriö",
            "committees": ["hallintovaliokunta"], "plan": {"week": "2/2026", "state": "ANNETTU_EK"}}
    lines = bt.context_for(item, stats)
    assert lines[0] == "Hallintovaliokunta: mietintö tyypillisesti 60 pv HE:n antamisesta (mediaani, n=3); 67 % mietinnöistä muuttaa esitystä (n=3)"
    assert "Valtiovarainministeriö: HE:n antamisesta eduskunnan hyväksyntään tyypillisesti 70 pv (mediaani, n=3)" in lines
    assert any(line.startswith("Valtiovarainministeriö: lausuntoja tyypillisesti 20 hanketta kohden (mediaani, n=3), lausuntoaika 42 pv") for line in lines)
    assert any("suunnitellulla viikolla" in line and "(±1 vk, n=3)" in line for line in lines)
    assert all("n=" in line for line in lines)
    # a committee without enough data falls back to nothing committee-specific, and EU items get no HE lines
    assert not any(line.startswith("Talousvaliokunta") for line in bt.context_for({**item, "committees": ["talousvaliokunta"], "ministry": ""}, stats))
    assert bt.context_for({"id": "eu-1", "scope": "eu", "laji": "eu", "ministry": "Euroopan komissio"}, stats) == []


def test_context_for_tenders_mergers_and_delegated(stats):
    t = bt.context_for({"id": "hk-EF-1", "scope": "hankinta", "stage": "avoin", "buyer": "Oulun kaupunki", "cpv": "72000000"}, stats)
    assert "Hankintayksikön päätöksistä 2 valitusta markkinaoikeuteen 90 pv:ssä" in t
    assert "Markkinaoikeus: Oulun kaupunki – valittaja menestyi 33 %:ssa ratkaisuista (n=3)" in t
    assert "Sopimuskausi tässä CPV-jaossa tyypillisesti 36 kk (mediaani, n=3; neljännesvälit 30–42 kk)" in t
    assert "Tarjousaika tässä CPV-jaossa tyypillisesti 30 pv ilmoituksesta määräaikaan (mediaani, n=3)" in t
    a = bt.context_for({"id": "mao-v-1", "scope": "hankinta", "stage": "mao", "buyer": "Espoon kaupunki", "topics": ["ICT ja ohjelmistot"]}, stats)
    assert "Markkinaoikeus: valitus hylätty 40 %, hankintapäätös kumottu 20 %, jätetty tutkimatta 20 % ratkaisuista (n=5)" in a
    assert "Markkinaoikeus: valituksesta ratkaisuun tyypillisesti 90 pv (mediaani, n=3)" in a
    assert "Markkinaoikeus (ICT ja ohjelmistot): valittaja menestyi 67 %:ssa ratkaisuista (n=3)" in a
    assert "Hankintayksikön päätöksistä 1 valitus markkinaoikeuteen 90 pv:ssä" in a
    m = bt.context_for({"id": "yk-fi-1", "authority": "KKV", "scope": "yrityskauppa", "topics": ["Kauppa"]}, stats)
    assert m[0] == "KKV: jatkoselvitykseen 43 % ilmoituksista (n=7)"
    assert "KKV (Kauppa): jatkoselvitykseen 0 % ilmoituksista (n=3)" in m
    assert bt.context_for({"id": "yk-eu-1", "authority": "EU", "scope": "yrityskauppa"}, stats) == []
    d = bt.context_for({"id": "eu-da-1", "scope": "eu", "laji": "delegoitu"}, stats)
    assert d[0] == "Delegoidut säädökset: parlamentti tai neuvosto vastusti 11 % säädöksistä, 22 % peruutettiin (n=9)"
    assert bt.context_for({}, stats) == [] and bt.context_for({"scope": "fi"}, {}) == [] and bt.context_for(None, None) == []


def test_context_is_silent_when_thin():
    thin = bt.compute([], [], history={}, today=TODAY)
    assert bt.context_for({"scope": "fi", "laji": "laki", "kind": "HE", "ministry": "valtiovarainministeriö", "committees": ["hallintovaliokunta"]}, thin) == []
    assert bt.context_for({"scope": "hankinta", "stage": "mao", "buyer": "X", "cpv": "72000000"}, thin) == []
    assert bt.context_for({"authority": "KKV"}, thin) == []


# ------------------------------------------------------------------ parsers (trimmed samples)
def test_finlex_mao_listing_sample():
    lst = fh.finlex_mao_entries(sample("finlex_markkinaoikeus_2026_listing.html"), 2026)
    by = {e["number"]: e for e in lst}
    assert len(lst) == 9 and all(e["url"].startswith("https://www.finlex.fi/fi/oikeuskaytanto/markkinaoikeus/2026/") for e in lst)
    assert by["MAO:484/2026"]["procurement"] and by["MAO:484/2026"]["appellant"] == "Kuljetusliike Topi Nikula Oy" and by["MAO:484/2026"]["respondent"] == "Salon kaupunki"
    assert by["MAO:484/2026"]["keywords"] == ["julkinen hankinta", "poikkeuksellisen alhainen tarjoushinta"]
    assert by["MAO:474/2026"]["procurement"]                         # 'julkinen hakinta' – Finlex's typo
    assert by["MAO:485/2026"]["procurement"] and by["MAO:481/2026"]["procurement"]
    assert not by["MAO:483/2026"]["procurement"]                     # sopimaton menettely elinkeinotoiminnassa
    assert not by["MAO:472/2026"]["procurement"]                     # patentti
    assert not by["MAO:256/2026"]["procurement"]                     # seuraamusmaksuesitys (maakaasumarkkina)
    assert not by["MAO:327/2026"]["procurement"]                     # kuluttajansuoja
    assert sum(1 for e in lst if e["procurement"]) == 4


def test_finlex_mao_decision_sample():
    d = fh.finlex_mao_parse_decision(sample("finlex_mao_2026_484.html"))
    assert d["number"] == "MAO:484/2026" and d["date"] == "2026-10-06" and d["diaari"] == "194/2026"
    assert d["appellant"] == "Kuljetusliike Topi Nikula Oy" and d["respondent"] == "Salon kaupunki"
    assert d["keywords"] == ["julkinen hankinta", "poikkeuksellisen alhainen tarjoushinta"]
    assert d["outcome"] == "valitus hylätty" and not d["interim"]    # a third party's claim was left unexamined, the appeal itself dismissed
    assert d["outcomeText"].startswith("Markkinaoikeus jättää tutkimatta Maanrakennus Rannikko Oy:n vaatimuksen")
    assert d["value"] == 1500000 and d["noticeDate"] == "2026-02-11" and d["contestedDates"] == ["2026-04-10"]
    assert d["background"].startswith("Salon kaupunki (jäljempänä myös hankintayksikkö) on ilmoittanut 11.2.2026")


def test_outcome_classification():
    assert fh.classify_outcome("Markkinaoikeus kumoaa Salon kaupungin hankintapäätöksen 10.4.2026 § 6.") == "hankintapäätös kumottu"
    assert fh.classify_outcome("Markkinaoikeus määrää hankintayksikön maksamaan hyvitysmaksuna 20.000 euroa.") == "hyvitysmaksu"
    assert fh.classify_outcome("Markkinaoikeus jättää valituksen tutkimatta.") == "jätetty tutkimatta"
    assert fh.classify_outcome("Markkinaoikeus jättää tutkimatta X Oy:n vaatimuksen. Markkinaoikeus hylkää valituksen.") == "valitus hylätty"
    assert fh.classify_outcome("Markkinaoikeus hylkää valituksen.") == "valitus hylätty"
    assert fh.classify_outcome("Marknadsdomstolen avslår besvären.") == "valitus hylätty"
    assert fh.classify_outcome("") is None
    assert fh.is_procurement(["julkinen hankinta", "liikesalaisuus"]) and not fh.is_procurement(["tavaramerkki", "sekaannusvaara"])
    assert not fh.is_procurement(["Kuluttaja-asiamies > Elisa Oyj", "kuluttajansuoja"]) and not fh.is_procurement([])


def test_kkv_listing_sample():
    lst = fh.kkv_listing_entries(sample("kkv_yrityskauppavalvonta_sivu1.html"))
    assert [e["diaari"] for e in lst] == ["KKV/1410/14.00.10/2026", "KKV/985/14.00.10/2026", "KKV/433/14.00.10/2026", "KKV/815/14.00.10/2022"]
    assert [e["outcome"] for e in lst] == ["hyväksytty", "hyväksytty", "ehdoin", "jatkoselvitys"]
    assert lst[0]["parties"] == "Nimlas Finland Oy / Tammelan Talotekniikka Oy" and lst[0]["date"] == "2026-10-15"
    assert fh.kkv_outcome("Yrityskaupan kieltäminen") == "kielletty" and fh.kkv_outcome("Esitys yrityskaupan kieltämisestä") == "esitys MAO"
    assert fh.kkv_outcome("Muut yrityskaupparatkaisut - Esitys markkinaoikeudelle") == "esitys MAO" and fh.kkv_outcome("Asian käsittelyn raukeaminen") == "rauennut"
    assert fh.kkv_outcome("Muut yrityskauppapäätökset - Ehtomuutoshakemus") == "ehtoja muutettu" and fh.kkv_outcome(None) is None
    assert fh.sector_of("Molemmat osapuolet toimivat taloteknisten palveluiden markkinoilla") == "Rakentaminen"
    assert fh.sector_of("yksityisen suun terveydenhuollon markkinoilla") == "Terveys- ja sosiaalipalvelut" and fh.sector_of("") is None


# ------------------------------------------------------------------ history bookkeeping (injected fetchers)
def test_mao_history_backfill_resumes_and_merges_cache():
    pages = {f"{fh.FINLEX}/fi/oikeuskaytanto/markkinaoikeus/2026": sample("finlex_markkinaoikeus_2026_listing.html"),
             f"{fh.FINLEX}/fi/oikeuskaytanto/markkinaoikeus/2025": ""}
    decision = sample("finlex_mao_2026_484.html")
    calls = []

    def fetch(url):
        calls.append(url)
        return pages.get(url, decision)

    h = fh._load(Path("/nonexistent/mao.json"))
    c = fh.update_mao_history(h, years=[2025, 2026], detail_cap=1, fetch=fetch, first_run=True)
    assert c["procurement"] == 4 and c["fetched"] == 1 and c["pending"] == 3 and len(h["items"]) == 4
    done = [r for r in h["items"].values() if r.get("outcome")]
    assert len(done) == 1 and done[0]["number"] == "MAO:485/2026" and done[0]["respondent"] == "Business Finland Oy ja Innovaatiorahoituskeskus Business Finland"
    assert h["items"]["MAO:484/2026"].get("outcome") is None and h["items"]["MAO:484/2026"]["source"] == "finlex"
    c2 = fh.update_mao_history(h, years=[2025, 2026], detail_cap=10, fetch=fetch, first_run=False)
    assert c2["fetched"] == 3 and c2["pending"] == 0 and all(r.get("outcome") for r in h["items"].values())
    c3 = fh.update_mao_history(h, years=[2025, 2026], detail_cap=10, fetch=fetch, first_run=False)
    assert c3["fetched"] == 0 and len(calls) == 2 * 3 + 4   # listings every run, each decision page once
    cache = {"decisions": {"MAO:484/2026": {"number": "MAO:484/2026", "category": "hankinta", "value": 1500000, "outcome": "valitus hylätty", "respondent": "Salon kaupunki"},
                           "MAO:9/2026": {"number": "MAO:9/2026", "category": "hankinta", "date": "2026-10-01", "outcome": "hankintapäätös kumottu", "respondent": "Turun kaupunki",
                                          "keywords": "julkinen hankinta – vertailu", "appellant": "A Oy"},
                           "MAO:10/2026": {"number": "MAO:10/2026", "category": "kilpailu", "outcome": "esitys hylätty"}}}
    assert fh.merge_mao_cache(h, cache) == 1 and fh.merge_mao_cache(h, cache) == 0
    assert h["items"]["MAO:9/2026"]["source"] == "markkinaoikeus.fi" and h["items"]["MAO:9/2026"]["keywords"] == ["julkinen hankinta", "vertailu"]
    assert "MAO:10/2026" not in h["items"] and len(h["items"]) == 5


def test_mao_history_first_run_raises_when_finlex_is_down():
    def down(url):
        raise RuntimeError("503")

    h = fh._load(Path("/nonexistent/mao.json"))
    with pytest.raises(RuntimeError):
        fh.update_mao_history(h, years=[2026], fetch=down, first_run=True)
    h["items"]["MAO:1/2026"] = {"number": "MAO:1/2026", "outcome": "valitus hylätty"}
    assert fh.update_mao_history(h, years=[2026], fetch=down, first_run=False)["listed"] == 0 and len(h["items"]) == 1


def test_kkv_history_walks_listing_to_since_and_fetches_cases():
    listing = sample("kkv_yrityskauppavalvonta_sivu1.html")
    fetched_pages, fetched_cases = [], []

    def fetch_listing(page):
        fetched_pages.append(page)
        return listing if page == 1 else ""

    def fetch_case(url):
        fetched_cases.append(url)
        return {"notified": "2026-09-01", "parties": "P", "summary": "Molemmat osapuolet toimivat taloteknisten palveluiden markkinoilla. KKV siirsi yrityskaupan jatkoselvitykseen 1.10.2026.", "phase2Start": None}

    h = fh._load(Path("/nonexistent/kkv.json"))
    c = fh.update_kkv_history(h, since="2024-01-01", page_cap=5, detail_cap=1, fetch_listing=fetch_listing, fetch_case=fetch_case, first_run=True)
    assert c["pages"] == 1 and c["entries"] == 3 and c["new"] == 3 and c["details"] == 1      # the 2022 interim entry is before `since`
    assert h["state"]["kkv"]["backfillComplete"] is True
    rows = h["items"]
    assert set(rows) == {"KKV/1410/14.00.10/2026", "KKV/985/14.00.10/2026", "KKV/433/14.00.10/2026"}
    assert rows["KKV/433/14.00.10/2026"]["outcome"] == "ehdoin" and rows["KKV/433/14.00.10/2026"]["decided"] == "2026-09-03"
    newest = rows["KKV/1410/14.00.10/2026"]
    assert newest["detail"] and newest["notified"] == "2026-09-01" and newest["phase"] == 2 and newest["phase2Start"] == "2026-10-01" and newest["sector"] == "Rakentaminen"
    c2 = fh.update_kkv_history(h, since="2024-01-01", page_cap=5, detail_cap=5, fetch_listing=fetch_listing, fetch_case=fetch_case, first_run=False)
    assert c2["new"] == 0 and c2["pages"] == 1 and c2["details"] == 2 and all(r.get("detail") for r in rows.values())
    # the interim listing entry marks phase 2 without closing the case
    fh._kkv_apply_entry(rows, {"url": "https://www.kkv.fi/x/kkv-985-14-00-10-2026-jatkoselvitys/", "diaari": "KKV/985/14.00.10/2026", "parties": "Ambea AB / Humana AB",
                               "date": "2026-08-01", "status": "Muut yrityskaupparatkaisut - jatkoselvitykseen ryhtyminen", "outcome": "jatkoselvitys"})
    assert rows["KKV/985/14.00.10/2026"]["phase"] == 2 and rows["KKV/985/14.00.10/2026"]["decided"] == "2026-09-25"
    # cache merge: pending and decided cases, idempotent
    cache = {"cases": {"KKV/1500/14.00.10/2026": {"diaari": "KKV/1500/14.00.10/2026", "notified": "2026-10-10", "pending": True, "parties": "A / B", "summary": "vähittäiskaupan markkinoilla"},
                       "KKV/433/14.00.10/2026": {"diaari": "KKV/433/14.00.10/2026", "notified": "2026-08-05", "decided": "2026-09-03", "decision": "Yrityskaupan hyväksyminen ehdollisena"}}}
    assert fh.merge_kkv_cache(h, cache) == 1 and fh.merge_kkv_cache(h, cache) == 0
    assert rows["KKV/1500/14.00.10/2026"]["pending"] and rows["KKV/1500/14.00.10/2026"]["sector"] == "Kauppa"
    assert rows["KKV/433/14.00.10/2026"]["notified"] == "2026-09-01"   # a value already in the history is kept


def test_awards_and_appeals_are_idempotent(tmp_path):
    awards = fh._load(tmp_path / "awards.json")
    assert fh.update_awards_history(awards, SOPIMUSKAUDET) == 4 and fh.update_awards_history(awards, SOPIMUSKAUDET) == 0
    row = awards["items"]["2"]
    assert row["cpv"] == "72260000" and row["cpvCodes"] == ["72260000", "48000000"] and row["durationMonths"] == 24 and "5" not in awards["items"]
    fh._save(tmp_path / "awards.json", awards)
    again = fh._load(tmp_path / "awards.json")
    assert again["items"] == awards["items"] and again["updated"]
    appeals = fh._load(tmp_path / "appeals.json")
    assert fh.update_appeals_history(appeals, MAO_CACHE) == 3 and fh.update_appeals_history(appeals, MAO_CACHE) == 0
    linked = {"pending": {"k1": {**MAO_CACHE["pending"]["k1"], "decision": "MAO:1/2026", "lastSeen": "2026-10-18"}}}
    fh.update_appeals_history(appeals, linked)
    assert appeals["items"]["k1"]["decision"] == "MAO:1/2026" and appeals["items"]["k1"]["lastSeen"] == "2026-10-18" and len(appeals["items"]) == 3


def test_build_writes_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(bt, "OUT", tmp_path / "tilastot.json")
    monkeypatch.setattr(bt, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(bt, "HISTORY_DIR", tmp_path / "history")
    stats = bt.build_tilastot({"items": []}, {"items": []})
    saved = json.loads((tmp_path / "tilastot.json").read_text(encoding="utf-8"))
    assert set(saved) >= {"generated", "eduskunta", "suunnitelma", "mao", "kkv", "hankinnat", "delegoidut"} and saved["mao"]["n"] == 0 == stats["mao"]["n"]


def test_samples_small():
    assert sum(f.stat().st_size for f in S.iterdir()) <= 200_000
