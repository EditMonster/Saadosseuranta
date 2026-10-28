"""HE:n lausuntopalaute → lausunnonantajien ehdotusten kohtalo (scripts/build_palaute.py). Pure functions only."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_palaute as bp  # noqa: E402

SECS = [
    {"h": "6.1 Johdanto", "p": ["Lausuntopyynnön vastaanottajia olivat Poliisihallitus, Tulli, Keskusrikospoliisi, ulkoministeriö ja Suomen Kuntaliitto."]},
    {"h": "6.2 Voimassaoloaika", "p": [
        "Poliisihallitus edellytti, ettei pidempää voimassaoloaikaa oteta käyttöön ilman design-uudistusta. "
        "Keskusrikospoliisin mukaan esitysluonnoksesta puuttuu tilannekuva. "
        "Palautteen johdosta jaksoon 4.2.3 on lisätty asiaa koskeva kappale.",
        "Kuntaliitto ehdotti siirtymäajan pidentämistä. Ehdotusta ei ole pidetty perusteltuna, koska direktiivi edellyttää täytäntöönpanoa.",
        "Tulli kannatti esitystä."]},
]


def test_names_are_matched_inflected_and_by_abbreviation():
    p = bp.name_pattern("Keskusrikospoliisi KRP")
    assert p.search("Keskusrikospoliisin mukaan") and p.search("KRP:n lausunnossa") and not p.search("krp-kurssi")
    k = bp.name_pattern("Suomen Kuntaliitto ry")
    assert k.search("Kuntaliiton mukaan") and k.search("Suomen Kuntaliitto katsoi")
    assert bp.name_pattern("Tulli").search("Tullin lausunnossa") and not bp.name_pattern("Tulli").search("tullikoodeksi")
    assert bp.name_pattern("Luonnon-, ympäristö- ja metsätieteilijöiden liitto Loimu ry").search("luonnoksen") is None


def test_ministry_answer_is_attributed_to_the_nearest_mention():
    orgs = ["Poliisihallitus", "Keskusrikospoliisi KRP", "Suomen Kuntaliitto ry", "Tulli", "Ulkoministeriö"]
    m = bp.match_item(SECS, orgs)
    assert m["Keskusrikospoliisi KRP"]["r"] == "h" and "4.2.3" in m["Keskusrikospoliisi KRP"]["s"][0][2]
    assert m["Suomen Kuntaliitto ry"]["r"] == "e"
    assert m["Tulli"]["r"] == "m"
    assert m["Poliisihallitus"]["r"] == "m"  # its own demand; the answer two sentences later concerns KRP's point
    assert "Ulkoministeriö" not in m  # only listed among the recipients


def test_build_writes_per_item_files(tmp_path):
    statements = {"fi-he-1-2026": {"kierros": {"rivit": [{"org": "Tulli"}, {"org": "Suomen Kuntaliitto ry"}, {"org": "Matti Meikäläinen"}]}}}
    items = {"fi-he-1-2026": {"heNumerot": ["1/2026"]}}
    res = bp.build(statements, items, {"1/2026": {"secs": SECS}}, tmp_path)
    assert res == {"fi-he-1-2026": {"Suomen Kuntaliitto ry": "e", "Tulli": "m"}}
    assert (tmp_path / "fi-he-1-2026.json").exists()
