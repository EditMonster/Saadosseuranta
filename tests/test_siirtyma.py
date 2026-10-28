"""Velvoitekalenteri (scripts/build_siirtyma.py): voimaantulosäännöksen virkkeet luokitellaan ja päivätään oikein."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_siirtyma as bs  # noqa: E402


def kinds(text, base=None):
    return [(r["k"], r.get("d"), r.get("r"), r.get("s")) for r in bs.rules_from_text(text, base, "Laki", "HE")]


def test_staggered_entry_into_force_and_section_ranges():
    assert kinds("Tämä laki tulee voimaan päivänä kuuta 20. Lain 12 b–12 d ja 54 j § tulevat kuitenkin voimaan vasta 1 päivänä elokuuta 2027.") == [
        ("voimaan", "2027-08-01", None, "12 b–12 d ja 54 j §")]
    assert kinds("2) 7 luvun 9 b §:n 2 momentti tulee voimaan 1 päivänä tammikuuta 2029;")[0][:2] == ("voimaan", "2029-01-01")
    assert kinds("4) 6 luvun 2 §:n 3 momentti tulevat voimaan valtioneuvoston asetuksella säädettävänä ajankohtana.")[0][:3] == ("voimaan", None, "asetuksella")


def test_relative_dates_are_computed_from_entry_into_force():
    r = kinds("Tämän lain 14 luvun 4 §:n 2 momenttia sovelletaan ensimmäisen kerran vuoden kuluttua lain voimaantulosta.", base="2027-07-01")
    assert r[0][:3] == ("soveltaminen", "2028-07-01", "1 v")
    r = kinds("Muutos on ilmoitettava rekisteröitäväksi viimeistään kolmen vuoden kuluttua tämän lain voimaantulosta.", base="2027-07-01")
    assert r[0][:3] == ("velvoite", "2030-07-01", "3 v")
    assert kinds("Muutos on tehtävä viimeistään kuuden kuukauden kuluttua tämän lain voimaantulosta.")[0][:3] == ("velvoite", None, "6 kk")


def test_temporary_old_law_repealed_and_tax_year():
    assert kinds("Tämän lain 5 §:n 3 ja 4 momentti on voimassa vuoden 2030 loppuun.")[0][:2] == ("voimassa", "2030-12-31")
    assert kinds("Jos oikeus etuuteen on alkanut ennen tämän lain voimaantuloa, sovelletaan tämän lain voimaan tullessa voimassa olleita säännöksiä.")[0][0] == "vanha"
    assert kinds("Kumottua 55 b §:ää sovelletaan kuitenkin 30 päivään syyskuuta 2028.")[0][:2] == ("kumottu", "2028-09-30")
    assert kinds("Lakia sovelletaan ensimmäisen kerran vuodelta 2027 toimitettavassa verotuksessa.")[0][:2] == ("soveltaminen", "2027-01-01")
    assert kinds("Tämä laki tulee voimaan 1 päivänä tammikuuta 2025.") == []  # the main date is already the item's own event


def test_finlex_provision_stops_before_signatures_and_swedish_text():
    page = ('"className":"highlightable","children":"Muu pykälä."'
            '"className":"highlightable","children":"Tämä laki tulee voimaan\\u00a01\\u00a0päivänä\\u00a0tammikuuta\\u00a02025. "'
            '"className":"highlightable","children":"2) 7 luvun 9 b §:n 2 momentti tulee voimaan 1 päivänä tammikuuta 2029;"'
            '"className":"highlightable","children":"Helsingissä 20 päivänä joulukuuta 2024"'
            '"className":"highlightable","children":"Denna lag träder i kraft den 1 januari 2025."')
    vt = bs.finlex_vt_text(page)
    assert vt.startswith("Tämä laki tulee voimaan 1 päivänä tammikuuta 2025") and "2029" in vt and "Helsingissä" not in vt and "träder" not in vt


def test_attach_adds_rules_and_calendar_events():
    it = {"id": "fi-he-1-2027", "scope": "fi", "sk": ["5/2027"], "events": [{"kind": "voimaan", "date": "2027-07-01", "label": "Voimaan"}]}
    finlex = {"5/2027": {"voimaan": "2027-07-01", "title": "Laki X", "vtText": "Tämä laki tulee voimaan 1 päivänä heinäkuuta 2027.\nSen 3 § tulee voimaan 1 päivänä tammikuuta 2028."}}
    assert bs.attach([it], {}, finlex) == 1
    assert it["siirtymat"][0]["k"] == "voimaan" and it["siirtymat"][0]["src"] == "sk"
    ev = [e for e in it["events"] if e["kind"] == "siirtyma"]
    assert ev == [{"date": "2028-01-01", "end": "2028-01-01", "kind": "siirtyma", "label": "Porrastettu voimaantulo: 3 §", "confirmed": True}]
    bs.attach([it], {}, finlex)  # idempotent
    assert len([e for e in it["events"] if e["kind"] == "siirtyma"]) == 1
