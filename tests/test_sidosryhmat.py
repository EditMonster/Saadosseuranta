"""Sidosryhmien kannat (scripts/build_sidosryhmat.py): nimet yhdistyvät, yksityishenkilöt jäävät pois, yhtäpitävyys lasketaan."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_sidosryhmat as bs  # noqa: E402


def test_name_variants_merge():
    k = bs.key_of
    assert k("Elinkeinoelämän keskusliitto EK ry") == k("Elinkeinoelämän keskusliitto ry") == k("EK") == "elinkeinoelämän keskusliitto ek"
    assert k("Suomen Kuntaliitto ry") == k("Suomen Kuntaliitto") == k("Kuntaliitto")
    assert k("Kansaneläkelaitos (Kela)") == k("Kansaneläkelaitos")
    assert k("Finanssiala ry täydentävä lausunto") == k("Finanssiala ry")
    assert k("Uudenmaan Sairasautokeskus Oy edustaen myös Suomen Sairaankuljetusliitto SSK ry:tä") == "uudenmaan sairasautokeskus"
    assert k("Director Tuomas Haapakoski, Wärtsilä edustaen Teknologiateollisuus ry:tä ja EK:ta") == "teknologiateollisuus"


def _row(org, st, date="2026-01-01"):
    return {"org": org, "stance": st, "date": date}


def test_build_positions_agreement_and_privacy():
    st = {}
    for i in range(6):  # Alfa and Beta agree on six bills, Gamma opposes what they support
        st[f"fi-he-{i}"] = {"kierros": {"rivit": [_row("Alfa ry", "kannattaa"), _row("Beta ry", "kannattaa"), _row("Gamma", "vastustaa"), _row("Yksityishenkilö", "vastustaa")]}}
    for i in range(6, 9):  # enough non-neutral positions for everyone
        st[f"fi-he-{i}"] = {"kierros": {"rivit": [_row("Alfa ry", "varauksin"), _row("Beta", "varauksin"), _row("Gamma ry", "vastustaa")]}}
    res = bs.build(st, {})
    orgs = res["orgs"]
    assert set(orgs) == {"alfa", "beta", "gamma"} and "yksityishenkilö" not in orgs
    assert orgs["alfa"]["c"] == 9 and orgs["alfa"]["st"] == {"kannattaa": 6, "varauksin": 3}
    assert orgs["alfa"]["al"][0][0] == "beta" and orgs["alfa"]["al"][0][1] == 100
    assert orgs["alfa"]["op"][0][0] == "gamma"
    assert res["alias"]["Alfa ry"] == "alfa" and res["ids"][orgs["alfa"]["p"][0][0]].startswith("fi-he-")


def test_record_against_outcome_and_type():
    import build_sidosryhmat as bs
    rows = lambda st: [{"org": "Alfa ry", "stance": st}, {"org": "Beta Oy", "stance": "kannattaa"}]
    statements, items = {}, {}
    for i in range(12):  # Alfa asks for changes; the committee changed 9 of 12, all enacted
        iid = f"fi-he-{i}-2026"
        statements[iid] = {"kierros": {"rivit": rows("muutoksia")},
                           "valiokunnat": [{"kind": "mietintö", "decision": "muutettuna" if i < 9 else "muuttamattomana"}]}
        items[iid] = {"status": "voimassa", "topics": ["Työoikeus"]}
    statements["fi-he-99-2026"] = {"kierros": {"rivit": rows("vastustaa")}}  # still in Parliament: no outcome yet
    items["fi-he-99-2026"] = {"status": "eduskunnassa"}
    res = bs.build(statements, items, {"fi-he-0-2026": {"Alfa ry": "h"}, "fi-he-1-2026": {"Alfa ry": "e"}})
    a = res["orgs"]["alfa"]
    assert a["ty"] == "järjestö" and res["orgs"]["beta"]["ty"] == "yritys"
    n, score, exp, by = a["rec"]
    assert n == 12 and score == 75 and by["R"] == [12, 9, 0]
    assert a["pal"] == [1, 1, 0] and any(len(p) == 5 and p[4] == "h" for p in a["p"])
    assert res["oc"][res["ids"].index("fi-he-0-2026")] == "a" and res["oc"][res["ids"].index("fi-he-99-2026")] == "-"
    assert "akt1" in a["tg"] and res["orgs"]["beta"]["rec"][1] == 100
    assert bs.org_type("Helsingin käräjäoikeus") == "viranomainen" and bs.org_type("Diakonissalaitos") == "järjestö"
