"""Annetut lausunnot: otteen poiminta ja kannan luokittelu (fetch_lausunnot) tallennetuista eduskunnan
asiantuntijalausunnoista sekä sivutiedostojen rakentaminen (build_lausunnot). Ei verkkoa."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_lausunnot  # noqa: E402
import fetch_lausunnot as fl  # noqa: E402

S = Path(__file__).resolve().parent / "samples" / "lausunnot"


def test_clean_text_joins_hyphenation_and_lines():
    t = fl.clean_text("Tie-\ndonannossa esitetään yleisellä tasolla toimia,\njotka ovat tärkeitä.\n\nOtsikko\nToinen kappale alkaa tästä.")
    assert "Tiedonannossa esitetään yleisellä tasolla toimia, jotka ovat tärkeitä." in t
    assert "\nOtsikko\n" in t and "Toinen kappale alkaa tästä." in t


def test_kkv_statement_gist_and_stance():
    r = fl.summarise_pdf((S / "kkv_e35_2026.pdf").read_bytes(), "Kilpailu- ja kuluttajavirasto")
    assert r["ok"] is True and r["pages"] == 2
    assert r["gist"].startswith("KKV yhtyy valtioneuvoston valtiontukia koskeviin päälinjauksiin")
    assert r["stance"] == "varauksin"
    assert len(r["gist"]) <= fl.GIST_MAX + 2
    assert "kiittää" not in r["gist"]


def test_unicef_supports_with_reservations():
    r = fl.summarise_pdf((S / "unicef.pdf").read_bytes(), "Suomen UNICEF ry")
    assert r["stance"] == "varauksin"
    assert "kannatettavina" in r["gist"] and "ongelmallinen" in r["gist"]


def test_turku_opposes_in_part():
    r = fl.summarise_pdf((S / "turku.pdf").read_bytes(), "Turun kaupunki")
    assert r["stance"] == "osin" and "ei kannata" in r["gist"]


def test_classify_vocabulary():
    assert fl.classify("Liitto vastustaa esitystä jyrkästi. Esitys heikentää asemaa.") == "vastustaa"
    assert fl.classify("Yhdistys kannattaa esitystä.") == "kannattaa"
    assert fl.classify("Kannatamme esitystä. Esitämme kuitenkin tarkennusta 3 §:ään. Lisäksi 5 §:ää tulisi täsmentää.") == "varauksin"
    assert fl.classify("Virasto esittää muutosta 2 §:ään, ja 4 § tulisi poistaa.") == "muutoksia"
    assert fl.classify("Ministeriöllä ei ole lausuttavaa.", "Ministeriö; ei lausuttavaa") == "ei"
    assert fl.classify("Virasto toteaa, että asia koskee sen toimialaa.") == "kanta"


def test_pick_gist_skips_boilerplate_and_prefers_position():
    text = ("Lausuntopyyntönne 9.9.2026\nYhdistys kiittää mahdollisuudesta lausua asiasta.\n"
            "Yhdistys pitää esitystä perusteltuna, mutta katsoo, että siirtymäaikaa tulisi pidentää vuodella.\n"
            "Lisätietoja antaa lakimies, puh. 040 123 4567.")
    g = fl.pick_gist(text, "Yhdistys ry")
    assert g.startswith("Yhdistys pitää esitystä perusteltuna") and "kiittää" not in g and "puh." not in g


def test_presentations_are_not_statements():
    assert fl.is_presentation({"org": "työ- ja elinkeinoministeriö", "person": "Markku Kinnunen"})
    assert not fl.is_presentation({"org": "Kilpailu- ja kuluttajavirasto", "person": None})
    assert not fl.is_presentation({"org": "Suomen Kuntaliitto", "person": "Johanna Vilkuna"})


def test_build_lausunnot_files(tmp_path, monkeypatch):
    monkeypatch.setattr(build_lausunnot, "LAUSUNNOT_DIR", tmp_path)
    cache = {"docs": {"d1": {"ok": True, "stance": "vastustaa", "gist": "Liitto vastustaa esitystä."},
                      "d2": {"ok": "noText", "stance": None},
                      "EDK-1": {"ok": True, "stance": "kannattaa", "gist": "Virasto kannattaa esitystä."}}}
    monkeypatch.setattr(build_lausunnot, "load_json", lambda path, default: cache if "lausunnot" in str(path) else default)
    items = [{"id": "fi-he-12-2026", "hankeUuid": "u1", "heNumerot": ["12/2026"]}, {"id": "eu-x", "heNumerot": []}]
    hk = {"u1": {"lausunnot": {"n": 3, "url": "https://www.lausuntopalvelu.fi/FI/Proposal/Participation?proposalId=x",
                               "docs": [{"id": "d1", "org": "Liitto ry", "date": "2026-03-01", "url": "https://api.hankeikkuna.fi/a/d1.PDF"},
                                        {"id": "d2", "org": "Kunta", "date": "2026-03-02", "url": "https://api.hankeikkuna.fi/a/d2.PDF"},
                                        {"id": "d3", "org": "Ministeriö", "date": "2026-02-20", "none": True}]}}}
    vaski = {"statements": {"HE 12/2026 vp": [{"edk": "EDK-1", "org": "Virasto", "person": None, "committee": "TaV", "date": "2026-05-05", "url": "https://www.eduskunta.fi/pdf/EDK-1"}]}}
    out = build_lausunnot.build_lausunnot(items, hk, vaski)
    assert out == {"fi-he-12-2026": {"n": 4, "luettu": 4, "kannat": {"vastustaa": 1, "ei": 1, "kannattaa": 1}}}
    d = json.loads((tmp_path / "fi-he-12-2026.json").read_text(encoding="utf-8"))
    assert d["kierros"]["n"] == 3 and d["kierros"]["url"].startswith("https://www.lausuntopalvelu.fi/")
    rows = d["kierros"]["rivit"]
    assert [r["org"] for r in rows] == ["Liitto ry", "Kunta", "Ministeriö"]  # opposing first, "ei lausuttavaa" last
    assert rows[0]["stance"] == "vastustaa" and rows[0]["gist"] and rows[1]["noText"] and rows[2]["stance"] == "ei"
    assert d["eduskunta"]["rivit"][0]["committee"] == "TaV" and d["tiivistetty"] == 4 and d["odottaa"] == 0
    assert rows[2]["noFile"]  # metadata-only statement: counted as handled, never "pending"
    assert not (tmp_path / "eu-x.json").exists()
    # a stale file from an item that no longer exists is removed
    (tmp_path / "old.json").write_text("{}")
    build_lausunnot.build_lausunnot(items, hk, vaski)
    assert not (tmp_path / "old.json").exists()


def test_oppose_vocabulary_avoids_nouns():
    # "torjunta" (prevention) is not "torjuu" (rejects); "vastustaminen" as a heading is not a position
    assert not fl.OPPOSE_RE.search("harmaan talouden torjunnassa ja torjuntatyötä varten")
    assert fl.OPPOSE_RE.search("Liitto torjuu ehdotuksen") and fl.OPPOSE_RE.search("Vastustamme esitystä")
    assert not fl.OPPOSE_RE.search("5.1 Kansalaisuusvaatimusten vastustaminen")
    assert fl.classify("Ulosottolaitos korostaa harmaan talouden torjunnan merkitystä. Rahoitusta tulisi lisätä.") == "kanta"


def test_reclassify_from_stored_signals():
    rec = {"ok": True, "stance": "vastustaa", "sig": {"none": False, "opp": ["torjunnassa"], "sup": [], "res": ["kuitenkin"], "con": 1}}
    assert fl.reclassify(rec) and rec["stance"] == "muutoksia" and rec["sig"]["opp"] == []
    rec2 = {"ok": True, "stance": "kannattaa", "sig": {"none": False, "opp": [], "sup": ["kannattaa"], "res": [], "con": 0}}
    assert not fl.reclassify(rec2) and rec2["stance"] == "kannattaa"
    assert not fl.reclassify({"ok": "noText"})


def test_parliament_keys_cover_letters_motions_and_eu_links():
    assert build_lausunnot.parliament_keys({"heNumerot": ["12/2026"], "ref": "HE 12/2026 vp"}) == {"HE 12/2026"}
    assert build_lausunnot.parliament_keys({"ref": "U 27/2026 vp"}) == {"U 27/2026"}
    assert build_lausunnot.parliament_keys({"ref": "LA 37/2026"}) == {"LA 37/2026"}
    assert build_lausunnot.parliament_keys({"ref": "COM(2026) 12", "kirjelmat": ["U 54/2026 vp", "U 55/2026 vp"]}) == {"U 54/2026", "U 55/2026"}
    assert build_lausunnot.parliament_keys({"ref": "OM012:00/2026"}) == set()


def test_eu_item_gets_letter_statements_and_presentations_last(tmp_path, monkeypatch):
    monkeypatch.setattr(build_lausunnot, "LAUSUNNOT_DIR", tmp_path)
    cache = {"docs": {"E1": {"ok": True, "stance": "esittely", "gist": "Ministeriö esittelee kantaa."},
                      "E2": {"ok": True, "stance": "kannattaa", "gist": "Liitto kannattaa."}}}
    monkeypatch.setattr(build_lausunnot, "load_json", lambda path, default: cache if "lausunnot" in str(path) else default)
    vaski = {"statements": {"U 54/2026 vp": [{"edk": "E1", "org": "valtiovarainministeriö", "person": "A B", "committee": "SuV", "date": "2026-09-01", "url": "u1"},
                                             {"edk": "E2", "org": "Liitto ry", "committee": "SuV", "date": "2026-09-02", "url": "u2"}]}}
    out = build_lausunnot.build_lausunnot([{"id": "eu-x", "ref": "COM(2026) 1", "kirjelmat": ["U 54/2026 vp"]}], {}, vaski)
    assert out["eu-x"]["n"] == 2 and out["eu-x"]["luettu"] == 2
    rows = json.loads((tmp_path / "eu-x.json").read_text(encoding="utf-8"))["eduskunta"]["rivit"]
    assert [r["stance"] for r in rows] == ["kannattaa", "esittely"] and rows[0]["asia"] == "U 54/2026"


def test_unpublished_statement_is_not_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(build_lausunnot, "LAUSUNNOT_DIR", tmp_path)
    monkeypatch.setattr(build_lausunnot, "load_json", lambda path, default: {"docs": {}} if "lausunnot" in str(path) else default)
    hk = {"u": {"lausunnot": {"docs": [{"id": "x", "org": "Virasto", "date": "2026-01-01"}]}}}
    out = build_lausunnot.build_lausunnot([{"id": "fi-1", "hankeUuid": "u"}], hk, {})
    assert out["fi-1"] == {"n": 1, "luettu": 1, "kannat": {}}
    row = json.loads((tmp_path / "fi-1.json").read_text(encoding="utf-8"))["kierros"]["rivit"][0]
    assert row["noFile"] and "url" not in row


def test_kiitan_is_boilerplate():
    assert fl.BOILER.search("Kiitän mahdollisuudesta esittää lausunto otsikon teemoista.")
    assert not fl.OPPOSE_RE.search("jotka olivat omistajuutta vastustaneet kiivaasti")
