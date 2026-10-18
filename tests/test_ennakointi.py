"""Unit tests for the forward-looking procurement sources: contract-period extraction from saved Hilma
notice documents (tests/samples/hankinnat/), the buyers' calendar parsers, the planned-date estimator, TED
title/deadline handling and the shape of the rows build_ennakointi.py produces. No network."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_ennakointi as be  # noqa: E402
import fetch_sopimuskaudet as fs  # noqa: E402
import fetch_suunnitelmat as fsu  # noqa: E402
import fetch_ted as ft  # noqa: E402
from common import TODAY  # noqa: E402

SAMPLES = ROOT / "tests" / "samples" / "hankinnat"
EVENT_KINDS = {"lausunto", "he", "eduskunta", "hyvaksytty", "vahvistettu", "voimaan", "maaraaika", "muu", "ehdotus", "sopu",
               "parlamentti", "neuvosto", "julkaistu", "soveltaminen", "kanta", "ennuste"}


def load_json(name: str):
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


def load_text(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def iso(d: dt.date) -> str:
    return d.isoformat()


# ---------- 1. contract periods from Hilma notice documents ----------

def test_eforms_framework_with_options_in_note():
    info = fs.extract_eforms(load_json("enotice_59652.json"))
    assert info["schema"] == "eforms" and len(info["lots"]) == 4
    lot = info["lots"][0]
    assert (lot["startDate"], lot["endDate"], lot["durationMonths"]) == ("2026-09-01", "2028-08-31", 24)
    assert lot["frameworkAgreement"] is True and lot["dps"] is False
    assert "optiokaudella" in lot["optionsText"]  # BT-57/54 absent: options picked up from the lot note
    assert {w["name"] for w in info["winners"]} == {"Kesko Oyj", "Duni AB"}
    assert {w["id"] for w in info["winners"]} == {"0109862-8", "1817866-7"}  # not the buyer, the Market Court or the eSender
    assert info["value"] == 1600000.0 and info["currency"] == "EUR"
    assert info["lotResults"] == ["selec-w"] * 4
    assert [c["contractDate"] for c in info["contracts"]] == ["2026-09-03", "2026-09-03", "2026-08-27", "2026-08-27"]
    period = fs.contract_period(info)
    assert period["contractEnd"] == "2028-08-31" and period["contractEndWithOptions"] == "2030-08-31"
    assert period["framework"] is True and period["durationMonths"] == 24


def test_eforms_renewal_dates_already_inside_period():
    info = fs.extract_eforms(load_json("enotice_59519.json"))
    lot = info["lots"][0]
    assert (lot["startDate"], lot["endDate"], lot["maxRenewals"]) == ("2027-07-01", "2037-06-30", 1.0)
    assert "1.7.2035 - 30.6.2037" in lot["renewalText"]
    assert info["winners"] == [{"name": "V-S Bussipalvelut Oy", "id": "1481717-7"}]
    assert info["contracts"][0]["awardDate"] == "2026-06-11" and info["contracts"][0]["contractDate"] == "2026-07-13"
    period = fs.contract_period(info)
    assert period["contractEnd"] == "2037-06-30"
    assert period["contractEndWithOptions"] is None  # the quoted option period ends on the end date itself
    assert period["maxRenewals"] == 1 and period["durationMonths"] == 120


def test_eforms_duration_without_end_date_and_cancelled_result():
    info = fs.extract_eforms(load_json("enotice_59517.json"))
    lot = info["lots"][0]
    assert lot["startDate"] == "2027-04-01" and lot["endDate"] == "2031-03-31" and lot["durationMonths"] == 48
    assert info["lotResults"] == ["clos-nw"] and info["winners"] == []
    row = {"id": "EF-59517", "noticeId": 59517, "procedureId": 38230, "isEForms": True, "type": "29", "titleFi": "HUS 028-2026 Käsihuuhteet",
           "organisationNameFi": "HUS-yhtymä", "datePublished": "2026-10-16T02:05:02Z", "cpvCodes": "33631600"}
    rec = fs.summarise_notice(row, info)
    assert rec["cancelled"] is True and rec["contractEnd"] == "2031-03-31" and "winners" not in rec
    assert rec["published"] == "2026-10-16" and rec["buyer"] == "HUS-yhtymä"


def test_old_schema_award_notice():
    info = fs.extract_old(load_json("old_notice_138744.json"))
    assert info["schema"] == "old" and info["title"].startswith("Prosessoriohjattu proteesi")
    assert info["lots"][0]["startDate"] == "2023-07-04" and info["lots"][0]["endDate"] is None  # timeFrame type 3 with begin only
    assert info["lots"][0]["cpv"] == "33196000"
    assert info["winners"] == [{"name": "Respecta Oy", "id": "1623211-3"}]
    assert info["value"] == 41720.0 and info["currency"] == "EUR"
    assert info["contracts"][0]["contractDate"] == "2023-07-04"
    assert fs.contract_period(info)["contractEnd"] is None


def test_old_schema_synthetic_time_frames():
    doc = {"type": 300, "project": {"title": "Siivous"}, "procurementObject": {"shortDescription": []},
           "procedureInformation": {"frameworkAgreement": {"includesFrameworkAgreement": True, "duration": {"type": 2, "months": 48}}},
           "objectDescriptions": [
               {"timeFrame": {"type": 3, "beginDate": "2027-01-01T00:00:00", "endDate": "2028-12-31T00:00:00", "canBeRenewed": True,
                              "renewalDescription": ["Optio 1 + 1 vuotta."]},
                "optionsAndVariants": {"options": True, "optionsDescription": []}, "awardContract": {"awardedContracts": [
                   {"conclusionDate": "2026-11-02T00:00:00", "contractors": [{"officialName": "Puhdas Oy", "nationalRegistrationNumber": "1234567-8"}],
                    "finalTotalValue": {"value": 100000.0, "currency": "EUR"}}]}},
               {"timeFrame": {"type": 2, "months": 24, "beginDate": "2027-01-01T00:00:00"}, "awardContract": {"awardedContracts": []}}]}
    info = fs.extract_old(doc)
    assert info["lots"][0]["endDate"] == "2028-12-31" and info["lots"][0]["durationMonths"] == 24
    assert info["lots"][1]["endDate"] == "2028-12-31" and info["lots"][1]["frameworkAgreement"] is True
    period = fs.contract_period(info)
    assert period["contractEnd"] == "2028-12-31" and period["contractEndWithOptions"] == "2030-12-31"
    assert info["winners"] == [{"name": "Puhdas Oy", "id": "1234567-8"}] and info["value"] == 100000.0


def test_old_schema_national_direct_award_free_text_period():
    doc = {"type": 9905, "project": {"title": "Huolto"}, "procedureInformation": {},
           "procurementObject": {"shortDescription": ["Hankinnan kohteena on huoltosopimus.", "Sopimuskausi on 1.1.2027–31.12.2028 ja optio yhden vuoden."]},
           "objectDescriptions": [{"timeFrame": {"type": 0}, "awardContract": {"awardedContracts": [{"contractors": [{"officialName": "Roche Oy"}]}]}}]}
    info = fs.extract_old(doc)
    assert info["lots"][0]["startDate"] == "2027-01-01" and info["lots"][0]["endDate"] == "2028-12-31"
    period = fs.contract_period(info)
    assert period["contractEnd"] == "2028-12-31" and period["contractEndWithOptions"] == "2029-12-31"


# ---------- 2. contractEnd / options arithmetic ----------

def test_period_arithmetic():
    assert fs.period_end("2027-04-01", None, 48.0, "MONTH") == "2031-03-31"
    assert fs.period_end("2027-01-01", None, 2, "YEAR") == "2028-12-31"
    assert fs.period_end("2027-01-01", None, 30, "DAY") == "2027-01-30"
    assert fs.period_end("2027-01-01", "2027-06-30", 48, "MONTH") == "2027-06-30"  # an explicit end wins
    assert fs.period_end(None, None, 48, "MONTH") is None
    assert fs.add_months(dt.date(2027, 1, 31), 1) == dt.date(2027, 2, 28)
    assert fs.add_months(dt.date(2027, 3, 15), -3) == dt.date(2026, 12, 15)
    assert fs.extend("2028-08-31", 24) == "2030-08-31" and fs.extend("2028-02-29", 12) == "2029-02-28"
    assert fs.months_between("2026-09-01", "2028-08-31") == 24 and fs.months_between("2027-07-01", "2037-06-30") == 120
    assert fs.duration_months(None, None, 48, "MONTH") == 48 and fs.duration_months(None, None, 2, "YEAR") == 24


@pytest.mark.parametrize("text, months", [
    ("Sopimusta voidaan jatkaa 1 + 1 vuotta", 24), ("optio 24 kk", 24), ("kahdella yhden (1) vuoden pituisella optiokaudella", 24),
    ("yhden (1) vuoden optiokausi", 12), ("kahden vuoden optiolla", 24), ("ei optiota", None),
    ("Sopimuskausi on 4 vuotta ja sen jälkeen optio 2 vuotta", 24), ("Sopimuskausi on kaksi vuotta. Ei optiota.", None),
    ("jatkaa sopimuskautta enintään kahdella enintään vuoden mittaisella optiokaudella", 24),
    ("enintään yhdellä (1) kahden (2) vuoden jaksolla. Jatkamisesta sovitaan viimeistään kuusi (6) kuukautta ennen sopimuskauden päättymistä.", 24),
    ("Optiona puisen esiintymislavarakenteen rakentaminen.", None),
])
def test_option_months(text, months):
    assert fs.option_months(text) == months


def test_contract_period_fallbacks():
    lots = [{"startDate": "2027-01-01", "endDate": "2028-12-31", "durationMonths": 24, "maxRenewals": 2.0, "renewalText": "Sopimusta voidaan jatkaa.",
             "optionsText": None, "frameworkAgreement": False, "dps": False}]
    p = fs.contract_period({"lots": lots})
    assert p["contractEndWithOptions"] == "2032-12-31"  # maxRenewals × base duration when the text gives nothing
    lots[0]["renewalText"] = "Optiokausi 1.1.2029–31.12.2029."
    assert fs.contract_period({"lots": lots})["contractEndWithOptions"] == "2029-12-31"  # quoted dates win
    lots[0]["renewalText"] = "Sopimusta voidaan jatkaa 31.12.2028 asti."  # the quoted date is the end itself: options already inside
    assert fs.contract_period({"lots": lots})["contractEndWithOptions"] is None
    lots[0]["renewalText"] = "Optiokausi 1.1.2028–30.6.2028."  # dates before the end say nothing: the maxRenewals fallback applies
    assert fs.contract_period({"lots": lots})["contractEndWithOptions"] == "2032-12-31"
    multi = {"lots": [{"startDate": "2027-01-01", "endDate": "2027-12-31", "durationMonths": 12, "frameworkAgreement": False},
                      {"startDate": "2027-03-01", "endDate": "2029-02-28", "durationMonths": 24, "frameworkAgreement": True}]}
    p = fs.contract_period(multi)
    assert (p["contractStart"], p["contractEnd"], p["durationMonths"], p["framework"]) == ("2027-01-01", "2029-02-28", 24, True)


def test_window_and_winner_parsing():
    assert fs.in_window(iso(TODAY + dt.timedelta(days=10)))
    assert fs.in_window(iso(TODAY - dt.timedelta(days=29))) and not fs.in_window(iso(TODAY - dt.timedelta(days=31)))
    assert not fs.in_window(iso(fs.add_months(TODAY, 25))) and not fs.in_window(None)
    assert fs.parse_winners("Duni AB (1817866-7)//Kesko Oyj (0109862-8)") == [{"name": "Duni AB", "id": "1817866-7"}, {"name": "Kesko Oyj", "id": "0109862-8"}]
    assert fs.parse_winners("Firma ilman tunnusta") == [{"name": "Firma ilman tunnusta", "id": None}]


# ---------- 3. calendar parsers ----------

def test_hansel_fragment():
    rows, nxt = fsu.parse_hansel(load_text("hansel_fragment_tulossa.html"), "https://www.hansel.fi/yhteishankinnat/")
    assert len(rows) == 10 and nxt == 2
    first = rows[0]
    assert first["title"] == "Hyvinvointialueiden leasingpalvelut 2027 (00862)" and first["agreement"] == "00862"
    assert first["phase"] == "Kilpailutuksessa" and first["contractStart"] == "2027-01-01" and first["contractEnd"] == "2028-12-31"
    assert first["plannedDate"] == "2026-09-01" and first["url"].startswith("https://www.hansel.fi/yhteishankinnat/")
    last = rows[-1]
    assert last["phase"] == "Valmistelussa" and last["plannedDate"] == "2026-10-01" and last["note"] == "Liity viimeistään: 15.11.2026"
    assert all(r["buyer"] == "Hansel Oy" and r["category"] in ("Puitejärjestely", "DPS") for r in rows)


def test_hansel_running_agreement_predicts_successor():
    card = ('<li class="card-link x"><a href="/yhteishankinnat/x-00704/"><div class="text-xl"><span aria-hidden="true"></span>'
            'Ajoneuvovakuutukset 2025–2027 (2029)</div></a><div><span class="bg-light-blue text-graphite rounded-full px-2 py-1 text-xs font-medium">'
            'Puitejärjestely</span><div class="text-sm"><span class="font-medium">Voimassaoloaika:</span> 05.03.2025 - 31.03.2029</div>'
            '<div class="text-sm"><span class="font-medium">Vaihe:</span> Käynnissä</div></div></li>')
    rows, nxt = fsu.parse_hansel(card, "u")
    assert nxt is None and rows[0]["plannedDate"] == "2028-06-30" and rows[0]["contractEnd"] == "2029-03-31"
    assert "seuraava kilpailutus" in rows[0]["plannedText"]


def test_espoo_table():
    rows = fsu.parse_espoo(load_text("espoo_table.html"), "u")
    assert len(rows) == 74
    assert rows[0] == {"buyer": "Espoon kaupunki", "title": "HRM- ja palkkajärjestelmän hankinta", "plannedText": "2026Q3", "plannedDate": "2026-08-01",
                       "contractStart": "2027-02-01", "url": "u"}
    only_start = next(r for r in rows if r["title"].startswith("Vihersisustuksen"))
    assert only_start["plannedText"] == "sopimus alkaa 2027Q3" and only_start["plannedDate"] == "2027-04-01" and only_start["contractStart"] == "2027-08-01"
    colspan = next(r for r in rows if r["title"].startswith("Viherkunnossapidon suurteho"))
    assert colspan["contractStart"] == "2027-08-01"
    assert not any("päivitetty" in r["title"] for r in rows)


def test_senaatti_table():
    rows = fsu.parse_senaatti(load_text("senaatti_table.html"), "u")
    assert len(rows) == 60
    assert rows[0]["title"].startswith("Rakennusurakka, Päävartiokorttelin") and rows[0]["plannedText"] == "2027/Q2"
    assert rows[0]["plannedDate"] == "2027-05-01" and rows[0]["category"] == "Rakennuttaminen" and rows[0]["eu"] is True
    assert any(r.get("eu") is None for r in rows)  # "Kansallinen" rows carry no eu flag (compact rows drop False)


def test_tampere_json():
    rows = fsu.parse_tampere(load_json("tampere_calendar.json"), "u")
    assert len(rows) == 7  # items without an EstimatedSchedule are skipped
    assert rows[0]["title"] == "Tuore kala, kalatuotteet ja äyriäiset" and rows[0]["plannedDate"] == "2026-11-01" and rows[0]["cpv"] == "15250000"
    assert all(r["category"] in ("Tavarahankinnat", "Palvelut") for r in rows)


def test_tuomi_accordion():
    rows = fsu.parse_tuomi(load_text("tuomi_accordion.html"), "u")
    assert len(rows) == 8 and all(r["plannedDate"] == "2026-11-01" and r["plannedText"] == "2026/Q4" for r in rows)
    assert all(not r["title"].startswith("DPS") for r in rows)  # the two open DPS entries have no planned timing
    assert [r.get("contractStart") for r in rows[:4]] == ["2027-01-01", "2027-08-16", "2027-07-19", "2027-01-01"]
    assert all(r["buyer"] == "Tuomi Logistiikka Oy" and r.get("summary") for r in rows)


def test_luvn_accordion():
    rows = fsu.parse_luvn(load_text("luvn_accordion.html"), "u")
    assert len(rows) == 29
    first = rows[0]
    assert first["title"] == "Pilaantuneen maan vastaanotto ja loppusijoituspalvelut" and first["category"] == "Asiantuntijapalvelut"
    assert first["plannedText"] == "Q4/2026" and first["plannedDate"] == "2026-11-01" and first["dialogueDate"] == "2025-11-01"
    ranged = next(r for r in rows if r["plannedText"] == "Q1-Q2/2027")
    assert ranged["plannedDate"] == "2027-02-01"
    no_colon = next(r for r in rows if r["title"] == "Henkilöstön muistamisen hankinta")
    assert no_colon["plannedDate"] == "2027-02-01"
    assert not any("Jatkuva" in r.get("plannedText", "") for r in rows)


def test_hus_row_mapping_on_synthetic_sheets():
    sheets = {
        "Speksaus valmis 08_2026": [("intro",), (None,),
                                    ("TP-numero (HUS tunniste)", "Hankinnan kohde", "Speksaus/palvelukuvaus tehty (toteuma)", "Tarjouspyyntö julkaistu (toteuma)", "Sopimuskausi alkaa (suunnitelma)", "Hankintakategoria"),
                                    ("HUS 213-2025", "Instrumentit endoskopiaan", dt.datetime(2026, 1, 12), dt.datetime(2026, 3, 25), dt.datetime(2026, 12, 15), "Anestesia"),
                                    ("HUS 103-2025", "Huuhteleva ventrikulostomia", dt.datetime(2026, 4, 3), None, dt.datetime(2026, 10, 26), "Anestesia"),
                                    (None, None, None, None, None, None)],
        "Valmistelu kesken 08_2026": [("intro",), (None,), ("TP-numero (HUS tunniste)", "Hankinnan kohde", "Sopimuskausi alkaa (suunnitelma)", "Hankintakategoria"),
                                      ("HUS 250-2024", "Elastomeeri-infuusiopumput", dt.datetime(2027, 7, 1), "Anestesia")],
        "Tulevat kilpailutukset 08_2026": [("intro",), (None,), ("TP-numero (HUS tunniste)", "Hankinnan kohde", "Valmistelu aloitettu (suunnitelma)", "Sopimuskausi alkaa (suunnitelma)", "Hankintakategoria"),
                                           ("HUS 375-2026", "Happirikastimen tarvikkeet", dt.datetime(2026, 8, 24), dt.datetime(2027, 4, 1), "Anestesia"),
                                           ("HUS 999-2026", "Ilman päivää", None, None, "Anestesia")],
    }
    rows = fsu.hus_rows(sheets, "https://www.hus.fi/x.xlsx")
    assert [r["title"] for r in rows] == ["Instrumentit endoskopiaan", "Huuhteleva ventrikulostomia", "Elastomeeri-infuusiopumput", "Happirikastimen tarvikkeet"]
    assert rows[0]["phase"] == "tarjouspyyntö julkaistu" and rows[0]["plannedDate"] == "2026-03-25" and rows[0]["reference"] == "HUS 213-2025"
    assert rows[1]["phase"] == "Speksaus valmis" and rows[1]["plannedDate"] == "2026-06-26" and rows[1]["contractStart"] == "2026-10-26"
    assert rows[2]["phase"] == "Valmistelu kesken" and rows[2]["plannedDate"] == "2027-02-01"
    assert rows[3]["phase"] == "Tulevat kilpailutukset" and rows[3]["plannedDate"] == "2026-10-01" and rows[3]["preparationStart"] == "2026-08-24"
    assert all(r["buyer"] == "HUS-yhtymä" and r["category"] == "Anestesia" for r in rows)


# ---------- 4. planned-date estimation ----------

@pytest.mark.parametrize("text, expected", [
    ("2027/Q2", "2027-05-01"), ("2026Q4", "2026-11-01"), ("Q1-Q2/2027", "2027-02-01"), ("Q4/2026", "2026-11-01"), ("Q 3 / 2027", "2027-08-01"),
    ("lokakuu 2026", "2026-10-15"), ("Lokakuussa 2026", "2026-10-15"), ("kesäkuu 2027", "2027-06-15"), ("11/2026", "2026-11-15"),
    ("kevät 2027", "2027-04-15"), ("kesä 2027", "2027-07-15"), ("syksy 2026", "2026-10-15"), ("Syksyn 2026 aikana", "2026-10-15"), ("talvi 2027", "2027-01-15"),
    ("alkuvuosi 2027", "2027-02-15"), ("loppuvuodesta 2026", "2026-11-15"), ("15.11.2026", "2026-11-15"), ("2027-01-01", "2027-01-01"),
    ("2027", None), ("", None), (None, None), ("Jatkuva ilmoittautuminen", None),
])
def test_planned_date(text, expected):
    assert fsu.planned_date(text) == expected


def test_plan_detail_dates_are_finnish_midnight():
    assert fsu.fi_date("2026-12-03T22:00:00+00:00") == "2026-12-04"
    assert fsu.fi_date("2026-11-11T22:00:00Z") == "2026-11-12"
    assert fsu.fi_date("2027-04-01+03:00") == "2027-04-01" and fsu.fi_date(None) is None
    fields = fsu.plan_detail_fields(load_json("hilma_plan_1305.json"))
    assert fields["plannedDate"] == "2026-12-04" and fields["contractStart"] == "2027-02-01" and fields["contractEnd"] == "2031-01-31"
    assert fields["cpv"] == "37535200" and fields["value"] == 1800000.0 and fields["buyerId"] == "3022425-9" and fields["detail"] is True
    row = fsu.plan_index_row(load_json("hilma_plans_index.json")["value"][0])
    assert row["id"] == "PLAN-1321" and row["expires"] == "2026-11-12" and row["url"].endswith("/public/plan/1321") and row["cpv"] == "90000000"


# ---------- 5. TED ----------

def test_ted_title_language_and_split():
    assert ft.pick_title({"hun": "x", "eng": "English", "fin": "Suomi – CPV – Otsikko"}) == ("Suomi – CPV – Otsikko", "fin")
    assert ft.pick_title({"eng": "English", "swe": "Svenska"}) == ("Svenska", "swe")
    assert ft.pick_title({"dan": ["Dansk"]}) == ("Dansk", "dan")
    assert ft.pick_title({}) == ("", None) and ft.pick_title("plain") == ("plain", None)
    assert ft.split_title("Tanska – Ohjelmistot ja tietojärjestelmät – Qualified Signature Creation Device (QSCD)") == \
        ("Qualified Signature Creation Device (QSCD)", "Ohjelmistot ja tietojärjestelmät")
    assert ft.short_title("Norja – Rakennustyöt – Bridge maintenance area mid 2027 - 2028") == "Bridge maintenance area mid 2027 - 2028"
    assert ft.short_title("Ruotsi – Palvelut – A – B") == "A – B" and ft.short_title("Lyhyt") == "Lyhyt"


def test_ted_sample_notices():
    sample = load_json("ted_search_sample.json")
    recs = [ft.trim_notice(n) for n in sample["notices"]]
    assert len(recs) == 5 and {r["country"] for r in recs} == {"DK", "NO", "SE"}
    by_pn = {r["pn"]: r for r in recs}
    assert by_pn["700734-2026"]["deadline"] == "2026-10-21T23:59:59Z" and by_pn["700734-2026"]["deadlineKind"] == "tarjous"
    assert by_pn["700789-2026"]["deadline"] == "2026-11-13T22:59:59Z"  # '2026-11-13+01:00' without a time: end of that day, in UTC
    assert by_pn["700665-2026"]["value"] == 10000000.0 and by_pn["700665-2026"]["buyer"] == "Trafikselskabet Movia"
    assert by_pn["700551-2026"]["cpv"][:3] == ["48814000", "85100000", "72000000"] and by_pn["700551-2026"]["url"].endswith("/detail/700551-2026")
    assert all(r["lang"] in ("fin", "swe", "eng") and r["published"] == "2026-10-12" for r in recs)


def test_ted_deadline_utc_and_keep():
    assert ft.deadline_utc(["2026-11-11Z"], ["22:59:59Z"]) == "2026-11-11T22:59:59Z"
    assert ft.deadline_utc(["2026-11-16+02:00"], ["23:59:59+02:00"]) == "2026-11-16T21:59:59Z"
    assert ft.deadline_utc(["2026-11-20+01:00", "2026-11-18+01:00"], ["12:00:00+01:00", "12:00:00+01:00"]) == "2026-11-18T11:00:00Z"
    assert ft.deadline_utc(None, None) is None
    assert ft.keep({"deadline": iso(TODAY + dt.timedelta(days=3)) + "T10:00:00Z"}, 7, 90)
    assert not ft.keep({"deadline": iso(TODAY - dt.timedelta(days=15)) + "T10:00:00Z"}, 7, 90)
    assert ft.keep({"published": iso(TODAY - dt.timedelta(days=5)), "noticeType": "cn-standard"}, 7, 90)
    assert not ft.keep({"published": iso(TODAY - dt.timedelta(days=8)), "noticeType": "cn-standard"}, 7, 90)
    assert ft.keep({"published": iso(TODAY - dt.timedelta(days=60)), "noticeType": "pin-only"}, 7, 90)


def test_ted_query_building():
    cpv = ft.cpv_patterns({"cpv": []}, {"toimialat": {"ICT": ["48", "72"], "Laki": ["791"]}})
    assert cpv == ["48*", "72*", "791*"]
    assert ft.cpv_patterns({"cpv": ["33*", "85"]}, {}) == ["33*", "85*"]
    q = ft.build_query(["SE", "EE", "DK", "NO"], dt.date(2026, 10, 11), ["72*", "48*"])
    assert q.startswith("(buyer-country IN (SWE EST DNK NOR)) AND (publication-date >= 20261011) AND (classification-cpv IN (72* 48*))")
    assert "notice-type IN (cn-standard cn-social pin-cfc-standard pin-only pin-buyer)" in q and "SORT BY" not in q


# ---------- 6. builders ----------

def _settings():
    return {"hankinnat": {"keep_closed_days": 14}, "ennusteet": {}, "kalenterit": {}, "ted": {"enabled": True, "maat": ["SE", "EE", "DK", "NO"]}}


def _award_tender(hid="EF-59652"):
    return {"id": f"hk-{hid}", "scope": "hankinta", "laji": "kilpailutus", "stage": "ratkaistu", "kind": "Jälki-ilmoitus", "title": "Kertakäyttövälineet",
            "buyer": "Kaarea Oy", "buyerId": "2904395-8", "published": iso(TODAY - dt.timedelta(days=2)), "status": "ratkaistu",
            "url": "https://www.hankintailmoitukset.fi/fi/public/procedure/32747/enotice/59652", "topics": ["Koneet, laitteet ja tarvikkeet"], "events": []}


def _sopimuskaudet_cache():
    end = fs.add_months(TODAY, 10)
    return {"notices": {
        "59652": {"id": "EF-59652", "noticeId": 59652, "procedureId": 32747, "isEForms": True, "type": "29", "title": "Kertakäyttövälineet ja rasiapakkauslaitteet",
                  "buyer": "Kaarea Oy", "buyerId": "2904395-8", "published": iso(TODAY - dt.timedelta(days=2)), "cpv": "39222100 39222000",
                  "framework": True, "lots": 4, "awardDate": "2026-07-01", "contractDate": "2026-08-27",
                  "winners": [{"name": "Kesko Oyj", "id": "0109862-8"}, {"name": "Duni AB", "id": "1817866-7"}], "value": 1600000.0, "currency": "EUR",
                  "contractStart": iso(fs.add_months(end, -24) + dt.timedelta(days=1)), "contractEnd": iso(end), "contractEndWithOptions": iso(fs.add_months(end, 24)),
                  "durationMonths": 24, "optionsText": "kahdella yhden (1) vuoden optiokaudella", "checked": iso(TODAY)},
        "1": {"id": "EF-1", "noticeId": 1, "procedureId": 1, "isEForms": True, "title": "Liian kaukana", "contractEnd": iso(fs.add_months(TODAY, 20)), "cpv": "72000000"},
        "2": {"id": "EF-2", "noticeId": 2, "procedureId": 2, "isEForms": True, "title": "Jo päättynyt", "contractEnd": iso(TODAY - dt.timedelta(days=1)), "cpv": "72000000"},
        "3": {"id": "EF-3", "checked": iso(TODAY), "skip": "ei sopimuskautta"},
        "4": {"id": "EF-4", "noticeId": 4, "procedureId": 4, "isEForms": True, "title": "Minikilpailutus", "contractEnd": iso(TODAY + dt.timedelta(days=40)),
              "contractStart": iso(TODAY + dt.timedelta(days=10)), "durationMonths": 1, "cpv": "60140000"},
    }}


def test_forecast_rows_shape():
    tenders = [_award_tender()]
    rows = be.forecast_rows(_settings(), tenders, None, cache=_sopimuskaudet_cache())
    assert [r["id"] for r in rows] == ["hk-enn-EF-59652"]  # 20 months away, already ended and a 1-month delivery are out
    r = rows[0]
    end = fs.add_months(TODAY, 10)
    assert r["stage"] == "ennuste" and r["status"] == "ennuste" and r["kind"] == "Uudelleenkilpailutuksen ennuste"
    assert r["scope"] == "hankinta" and r["laji"] == "kilpailutus" and r["title"] == "Kertakäyttövälineet ja rasiapakkauslaitteet"
    assert r["incumbent"] == "Kesko Oyj; Duni AB" and r["lastValue"] == 1600000.0 and r["currency"] == "EUR" and r["framework"] is True
    assert r["contractEnd"] == iso(end) and r["contractEndWithOptions"] == iso(fs.add_months(end, 24))
    assert r["forecastWindow"] == {"from": iso(fs.add_months(end, -9)), "to": iso(fs.add_months(end, -3))}
    assert r["topics"] == ["Koneet, laitteet ja tarvikkeet"] and r["cpv"] == "39222100"
    assert r["url"] == tenders[0]["url"] and r["related"] == [{"id": "hk-EF-59652", "stage": "ratkaistu", "kind": "Jälki-ilmoitus", "published": tenders[0]["published"]}]
    labels = [e["label"] for e in r["events"]]
    assert labels == ["Jälki-ilmoitus julkaistu – Kesko Oyj; Duni AB", "Uusi kilpailutus odotettavissa (arvio)", "Sopimuskausi päättyy", "Sopimuskausi päättyy optiot käytettynä"]
    assert [e["date"] for e in r["events"]] == sorted(e["date"] for e in r["events"])
    for e in r["events"]:
        assert e["kind"] in EVENT_KINDS
        if e["kind"] in ("ennuste", "maaraaika"):
            assert e["confirmed"] is False
    assert "Nykyinen toimittaja" in r["summary"] and len(r["summary"]) <= 500
    # without the award row on the page the Hilma URL is derived from the notice ids and there is no related link
    r2 = be.forecast_rows(_settings(), [], None, cache=_sopimuskaudet_cache())[0]
    assert r2["url"] == "https://www.hankintailmoitukset.fi/fi/public/procedure/32747/enotice/59652" and "related" not in r2
    assert be.forecast_rows(_settings(), [], None, cache={}) == []


def _suunnitelmat_cache():
    planned = iso(TODAY + dt.timedelta(days=45))
    return {"hilma": {"1305": {"id": "PLAN-1305", "planId": 1305, "title": "Leikkikenttävälineet ja peliareenat H26010TP", "buyer": "Tampereen Infra Oy",
                               "buyerId": "3022425-9", "cpv": "37535200", "value": 1800000.0, "currency": "EUR", "published": iso(TODAY - dt.timedelta(days=4)),
                               "expires": planned, "plannedDate": planned, "contractStart": iso(fs.add_months(TODAY, 4)), "contractEnd": iso(fs.add_months(TODAY, 52)),
                               "type": "EU", "nature": "supplies", "description": "Hankinnan kohteena ovat leikkikenttävälineet.", "likes": 3, "detail": True,
                               "url": "https://www.hankintailmoitukset.fi/fi/public/plan/1305"},
                      "1306": {"id": "PLAN-1306", "planId": 1306, "title": "Peltolammin alueurakka H26025TP", "buyer": "Tampereen Infra Oy", "buyerId": "3022425-9",
                               "cpv": "90000000", "published": iso(TODAY - dt.timedelta(days=30)), "expires": planned, "plannedDate": planned, "type": "EU",
                               "url": "https://www.hankintailmoitukset.fi/fi/public/plan/1306"},
                      "1307": {"id": "PLAN-1307", "planId": 1307, "title": "Vanha suunnitelma", "buyer": "X", "plannedDate": iso(TODAY - dt.timedelta(days=60)), "cpv": "72000000"}},
            "kalenterit": {"espoo": [{"buyer": "Espoon kaupunki", "title": "Ateriapalveluiden hankinta 2027", "plannedText": "2026Q4", "plannedDate": planned,
                                      "contractStart": iso(fs.add_months(TODAY, 5)), "url": "https://www.espoo.fi/kalenteri"},
                                     {"buyer": "Espoon kaupunki", "title": "Ateriapalveluiden hankinta 2027", "plannedText": "2027Q1", "plannedDate": planned,
                                      "url": "https://www.espoo.fi/kalenteri"},
                                     {"buyer": "Espoon kaupunki", "title": "Kaukainen", "plannedText": "2029/Q1", "plannedDate": iso(fs.add_months(TODAY, 30)), "url": "u"}],
                           "senaatti": [{"buyer": "Senaatti-kiinteistöt", "title": "Tietoturvatarkastukset ja konsultointi", "plannedText": "2026/Q4", "plannedDate": planned,
                                         "category": "Tietohallinto", "eu": True, "url": "https://www.senaatti.fi/kalenteri"}]},
            "health": {}}


def _open_tenders():
    return [{"id": "hk-EF-70001", "stage": "avoin", "status": "avoin", "kind": "Hankintailmoitus", "title": "Peltolammin alueurakka H26025TP – kunnossapito",
             "buyer": "Tampereen Infra Oy", "buyerId": "3022425-9", "published": iso(TODAY - dt.timedelta(days=1)), "events": [], "topics": ["Muut"]},
            {"id": "hk-EF-70002", "stage": "avoin", "status": "avoin", "kind": "Hankintailmoitus", "title": "Tietoturvatarkastukset ja konsultointi 2027–2030",
             "buyer": "Senaatti-kiinteistöt", "published": iso(TODAY - dt.timedelta(days=3)), "events": [], "topics": ["Muut"]},
            {"id": "hk-EF-70003", "stage": "avoin", "status": "avoin", "kind": "Hankintailmoitus", "title": "Peltolammin alueurakka H26025TP",
             "buyer": "Tampereen Infra Oy", "buyerId": "3022425-9", "published": iso(TODAY - dt.timedelta(days=400)), "events": [], "topics": ["Muut"]}]


KCAL = {"espoo": {"nimi": "Espoon kaupunki", "hilma_nimet": ["Espoon kaupunki"]}, "senaatti": {"nimi": "Senaatti-kiinteistöt", "hilma_nimet": ["Senaatti-kiinteistöt"]}}


def test_plan_rows_shape_and_matching():
    rows = be.plan_rows(_settings(), _open_tenders(), None, cache=_suunnitelmat_cache(), kcal=KCAL)
    by_title = {}
    for r in rows:
        by_title.setdefault(r["title"], []).append(r)
    assert "Vanha suunnitelma" not in by_title and "Kaukainen" not in by_title  # outside −30 d … +24 months
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)) and all(i.startswith("hk-kal-") and len(i) == len("hk-kal-") + 12 for i in ids)
    hilma = by_title["Leikkikenttävälineet ja peliareenat H26010TP"][0]
    assert hilma["stage"] == "kalenteri" and hilma["kind"] == "Kilpailutussuunnitelma (Hilma)" and hilma["status"] == "suunniteltu" and hilma["source"] == "hilma"
    assert hilma["topics"] == ["Koneet, laitteet ja tarvikkeet"] and hilma["value"] == 1800000.0 and hilma["eu"] is True and hilma["likes"] == 3
    assert hilma["url"].endswith("/public/plan/1305") and hilma["plannedText"] == be.fmt_date(hilma["plannedDate"])
    assert [e["label"] for e in hilma["events"]] == ["Kilpailutussuunnitelma julkaistu Hilmassa", "Hankintailmoitus suunniteltu (arvio)", "Sopimuskausi alkaa (suunnitelma)"]
    assert all(e["kind"] in EVENT_KINDS for e in hilma["events"]) and hilma["events"][1]["kind"] == "ennuste" and hilma["events"][1]["confirmed"] is False
    matched = by_title["Peltolammin alueurakka H26025TP"][0]
    assert matched["status"] == "julkaistu Hilmassa" and matched["related"][0]["id"] == "hk-EF-70001"  # the newer notice, not the year-old one
    hilma_event = next(e for e in matched["events"] if e["kind"] == "he")
    assert hilma_event["label"] == "Hankintailmoitus julkaistu Hilmassa" and hilma_event["date"] == _open_tenders()[0]["published"]
    assert [e["date"] for e in matched["events"]] == sorted(e["date"] for e in matched["events"])
    assert matched["topics"] == ["Ympäristö, viheralueet ja jätehuolto"]
    espoo = by_title["Ateriapalveluiden hankinta 2027"]
    assert len(espoo) == 2 and espoo[0]["id"] != espoo[1]["id"]  # a repeated title keeps both rows with stable ids
    assert {r["plannedText"] for r in espoo} == {"2026Q4", "2027Q1"} and all(r["status"] == "suunniteltu" for r in espoo)
    assert all(r["kind"] == "Hankintakalenteri (Espoon kaupunki)" and "Elintarvikkeet ja ruokapalvelut" in r["topics"] for r in espoo)  # keyword topics without CPV
    assert any("Sopimuskausi alkaa" in r.get("summary", "") for r in espoo)
    senaatti = by_title["Tietoturvatarkastukset ja konsultointi"][0]
    assert senaatti["status"] == "julkaistu Hilmassa" and senaatti["related"][0]["id"] == "hk-EF-70002" and senaatti["category"] == "Tietohallinto"
    assert rows == sorted(rows, key=lambda r: (r["plannedDate"], r["id"]))


def test_plan_ids_are_stable_and_matching_is_strict():
    assert be._plan_id("hilma", "Tampereen Infra Oy", "Peltolammin  alueurakka") == be._plan_id("hilma", "tampereen infra oy", "peltolammin alueurakka")
    assert be._plan_id("hilma", "A", "T") != be._plan_id("espoo", "A", "T")
    assert be.title_overlap("Sairaalakalusteet DPS", "Äänieriöt Kirurgiseen sairaalaan 2 kpl") == 0.0  # one shared stem is not a match
    assert be.title_overlap("Peltolammn alueurakka H26025TP", "Peltolammin alueurakka H26025TP") >= 0.6
    assert be.title_overlap("Rekrytointijärjestelmän hankinta", "Rekrytointijärjestelmän hankinta") == 1.0
    assert be.title_overlap("HUS 463-2025 Instrumentit", "Instrumentit endoskopiaan (DPS sisäinen kilpailutus HUS 463-2025)", drop={"hus"}) == 0.0


def _ted_cache():
    sample = load_json("ted_search_sample.json")
    notices = {}
    for i, n in enumerate(sample["notices"]):
        rec = ft.trim_notice(n)
        rec["deadline"] = iso(TODAY + dt.timedelta(days=5 + i)) + "T10:00:00Z"
        rec["published"] = iso(TODAY - dt.timedelta(days=2))
        notices[rec["pn"]] = rec
    notices["700551-2026"]["noticeType"] = "pin-only"
    notices["700551-2026"].pop("deadline")
    notices["700665-2026"]["deadline"] = iso(TODAY - dt.timedelta(days=3)) + "T10:00:00Z"
    notices["700734-2026"]["deadline"] = iso(TODAY - dt.timedelta(days=20)) + "T10:00:00Z"
    notices["999999-2026"] = {"pn": "999999-2026", "title": "Saksalainen", "country": "DE", "noticeType": "cn-standard", "deadline": iso(TODAY + dt.timedelta(days=9)) + "T10:00:00Z", "cpv": ["72000000"]}
    return {"notices": notices}


def test_ted_rows_shape():
    rows = be.ted_rows(_settings(), None, cache=_ted_cache())
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {"hk-ted-700551-2026", "hk-ted-700665-2026", "hk-ted-700789-2026", "hk-ted-700878-2026"}  # 20 days past and DE dropped
    pin = by_id["hk-ted-700551-2026"]
    assert pin["stage"] == "tulossa" and pin["status"] == "tulossa" and pin["kind"] == "Ennakkoilmoitus" and pin["country"] == "NO"
    assert pin["events"] == [{"date": pin["published"], "label": "Ennakkoilmoitus julkaistu (TED)", "kind": "ehdotus"}]
    closed = by_id["hk-ted-700665-2026"]
    assert closed["stage"] == "avoin" and closed["status"] == "päättynyt" and closed["country"] == "DK"
    open_row = by_id["hk-ted-700789-2026"]
    assert open_row["stage"] == "avoin" and open_row["status"] == "avoin" and open_row["deadlineKind"] == "tarjous" and open_row["country"] == "SE"
    assert open_row["topics"][0] == "Suunnittelu ja tekninen konsultointi" and open_row["cpv"] == "71313000" and open_row["eu"] is True and open_row["ted"] is True
    assert open_row["url"].startswith("https://ted.europa.eu/") and open_row["tedUrl"] == open_row["url"] and open_row["title"] == "Klimatberäkningsverktyg"
    assert [e["kind"] for e in open_row["events"]] == ["he", "maaraaika"] and open_row["events"][1]["date"] == open_row["deadline"][:10]
    assert "Ruotsi" in open_row["summary"] and open_row["value"] == 1500000.0
    for r in rows:
        assert r["scope"] == "hankinta" and r["laji"] == "kilpailutus" and r["title"] and r["topics"]
        assert all(e["kind"] in EVENT_KINDS and e["date"] and e["label"] for e in r["events"])
    assert be.ted_rows({"ted": {"enabled": False}}, None, cache=_ted_cache()) == []


def test_link_back_makes_links_mutual():
    tenders = [_award_tender()] + _open_tenders()
    rows = be.forecast_rows(_settings(), tenders, None, cache=_sopimuskaudet_cache()) + \
        be.plan_rows(_settings(), tenders, None, cache=_suunnitelmat_cache(), kcal=KCAL)
    added = be.link_back(tenders, rows)
    assert added == 3
    by_id = {t["id"]: t for t in tenders}
    for r in rows:
        for rel in r.get("related") or []:
            back = by_id[rel["id"]]["related"]
            assert any(b["id"] == r["id"] and b["stage"] == r["stage"] for b in back)
    assert be.link_back(tenders, rows) == 0  # idempotent
