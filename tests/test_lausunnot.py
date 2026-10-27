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
    assert r["ok"] is True and r["pages"] in (2, None)  # None when pdftotext read it
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
    monkeypatch.setattr(build_lausunnot, "load_docs", lambda: cache["docs"])
    items = [{"id": "fi-he-12-2026", "hankeUuid": "u1", "heNumerot": ["12/2026"]}, {"id": "eu-x", "heNumerot": []}]
    hk = {"u1": {"lausunnot": {"n": 3, "url": "https://www.lausuntopalvelu.fi/FI/Proposal/Participation?proposalId=x",
                               "docs": [{"id": "d1", "org": "Liitto ry", "date": "2026-03-01", "url": "https://api.hankeikkuna.fi/a/d1.PDF"},
                                        {"id": "d2", "org": "Kunta", "date": "2026-03-02", "url": "https://api.hankeikkuna.fi/a/d2.PDF"},
                                        {"id": "d3", "org": "Ministeriö", "date": "2026-02-20", "none": True}]}}}
    vaski = {"statements": {"HE 12/2026 vp": [{"edk": "EDK-1", "org": "Virasto", "person": None, "committee": "TaV", "date": "2026-05-05", "url": "https://www.eduskunta.fi/pdf/EDK-1"}]}}
    out = build_lausunnot.build_lausunnot(items, hk, vaski, {})
    assert out == {"fi-he-12-2026": {"n": 4, "luettu": 4, "kannat": {"vastustaa": 1, "ei": 1, "kannattaa": 1}, "valiokunnat": 0}}
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
    build_lausunnot.build_lausunnot(items, hk, vaski, {})
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
    monkeypatch.setattr(build_lausunnot, "load_docs", lambda: cache["docs"])
    vaski = {"statements": {"U 54/2026 vp": [{"edk": "E1", "org": "valtiovarainministeriö", "person": "A B", "committee": "SuV", "date": "2026-09-01", "url": "u1"},
                                             {"edk": "E2", "org": "Liitto ry", "committee": "SuV", "date": "2026-09-02", "url": "u2"}]}}
    out = build_lausunnot.build_lausunnot([{"id": "eu-x", "ref": "COM(2026) 1", "kirjelmat": ["U 54/2026 vp"]}], {}, vaski, {})
    assert out["eu-x"]["n"] == 2 and out["eu-x"]["luettu"] == 2
    rows = json.loads((tmp_path / "eu-x.json").read_text(encoding="utf-8"))["eduskunta"]["rivit"]
    assert [r["stance"] for r in rows] == ["kannattaa", "esittely"] and rows[0]["asia"] == "U 54/2026"


def test_unpublished_statement_is_not_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(build_lausunnot, "LAUSUNNOT_DIR", tmp_path)
    monkeypatch.setattr(build_lausunnot, "load_docs", lambda: {})
    hk = {"u": {"lausunnot": {"docs": [{"id": "x", "org": "Virasto", "date": "2026-01-01"}]}}}
    out = build_lausunnot.build_lausunnot([{"id": "fi-1", "hankeUuid": "u"}], hk, {}, {})
    assert out["fi-1"] == {"n": 1, "luettu": 1, "kannat": {}, "valiokunnat": 0}
    row = json.loads((tmp_path / "fi-1.json").read_text(encoding="utf-8"))["kierros"]["rivit"][0]
    assert row["noFile"] and "url" not in row


def test_kiitan_is_boilerplate():
    assert fl.BOILER.search("Kiitän mahdollisuudesta esittää lausunto otsikon teemoista.")
    assert not fl.OPPOSE_RE.search("jotka olivat omistajuutta vastustaneet kiivaasti")


def test_shards_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(fl, "SHARD_DIR", tmp_path / "lausunnot")
    monkeypatch.setattr(fl, "OUT", tmp_path / "lausunnot.json")
    (tmp_path / "lausunnot.json").write_text(json.dumps({"docs": {"a": {"src": "hk", "date": "2024-05-01", "ok": True}}}))
    docs = fl.load_docs()
    docs["b"] = {"src": "ek", "date": "2026-10-01", "ok": True}
    fl._save(docs)
    assert sorted(p.name for p in (tmp_path / "lausunnot").glob("*.json")) == ["ek-2026.json", "hk-2024.json"]
    assert not (tmp_path / "lausunnot.json").exists() and set(fl.load_docs()) == {"a", "b"}
    fl._save(fl.load_docs(), keep={"b"})  # a statement no longer listed is dropped, and its empty shard removed
    assert set(fl.load_docs()) == {"b"} and not (tmp_path / "lausunnot" / "hk-2024.json").exists()


def test_msg_statement_reads_the_attachment():
    import cfb
    data = (S / "liitteella.msg").read_bytes()
    parts = cfb.msg_parts(data)
    assert parts["attachments"] and any(n.lower().endswith((".pdf", ".docx")) for n, _ in parts["attachments"])
    r = fl.summarise_file(data, "https://x/LAUSUNTO_1.MSG", "", "Suomen Monikkoperheet ry")
    assert r["ok"] is True and r["via"].startswith("liite ") and r["gist"].startswith("Ehdotamme")


def test_msg_body_when_there_is_no_attachment():
    r = fl.summarise_file((S / "ei_lausuttavaa.msg").read_bytes(), "https://x/L.MSG", "", "Turvallisuus- ja kemikaalivirasto")
    assert r["ok"] is True and r["stance"] == "ei" and "ei ole lausuttavaa" in r["gist"]


def test_office_zip_and_plain_text(tmp_path):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ppt/slides/slide1.xml", "<p:sld><a:p><a:t>Otsikko</a:t></a:p></p:sld>")
        z.writestr("ppt/slides/slide2.xml", "<p:sld><a:p><a:t>Liitto vastustaa esitystä, koska se heikentää työntekijöiden asemaa merkittävästi ja lisää kustannuksia.</a:t></a:p>"
                   "<a:p><a:t>Esitys tulee hylätä ja valmistella uudelleen yhdessä työmarkkinaosapuolten kanssa.</a:t></a:p></p:sld>")
    r = fl.summarise_file(buf.getvalue(), "https://x/L.pptx", "", "Liitto ry")
    assert r["ok"] is True and r["stance"] == "vastustaa" and "vastustaa" in r["gist"]
    rtf = rb"{\rtf1\ansi Yhdistys kannattaa esitysluonnosta ja pit\'e4\'e4 sit\'e4 tarpeellisena uudistuksena, joka parantaa asiakkaiden asemaa merkitt\'e4v\'e4sti.}"
    r = fl.summarise_file(rtf, "https://x/L.RTF", "", "Yhdistys")
    assert r["ok"] is True and r["stance"] == "kannattaa" and "pitää" in r["gist"]
    assert fl.summarise_file(b"\x00\x01binary", "https://x/L.bin", "", "x") == {"ok": "notPdf"}


def test_parse_asia_page():
    import fetch_asiat
    rec = fetch_asiat.parse_asia(json.loads((Path(__file__).resolve().parent / "samples" / "asiat" / "E_48_2026.json").read_text(encoding="utf-8")))
    assert rec["tila"] in ("Käsittelyssä", "Käsitelty") and len(rec["statements"]) >= 15
    s0 = rec["statements"][0]
    assert s0["edk"].startswith("EDK-") and s0["url"].endswith(s0["edk"]) and s0["committee"] and (s0.get("org") or s0.get("person"))
    tunnukset = {d["tunnus"] for d in rec["committeeDocs"]}
    assert {"YmVL 29/2026 vp", "MmVL 24/2026 vp"} <= tunnukset
    assert all(d["kind"] == "lausunto" and d["committee"] in ("YmV", "MmV") for d in rec["committeeDocs"])


def test_committee_docs_in_item_file(tmp_path, monkeypatch):
    monkeypatch.setattr(build_lausunnot, "LAUSUNNOT_DIR", tmp_path)
    monkeypatch.setattr(build_lausunnot, "load_docs", lambda: {"EDK-9": {"ok": True, "stance": "muutoksia", "gist": "Liitto ehdottaa muutosta."}})
    asiat = {"asiat": {"HE 12/2026 vp": {"statements": [{"edk": "EDK-9", "org": "Liitto ry", "committee": "PeV", "date": "2026-03-01", "url": "u9", "kind": "lisäselvitys"}],
                                         "committeeDocs": [{"tunnus": "LiVM 1/2026 vp", "kind": "mietintö", "date": "2026-04-01", "committee": "LiV"},
                                                           {"tunnus": "PeVL 3/2026 vp", "kind": "lausunto", "date": "2026-03-20", "committee": "PeV"}]}},
             "reports": {"PeVL 3/2026 vp": {"decisionText": "että lakiehdotus voidaan käsitellä tavallisen lain säätämisjärjestyksessä.", "decision": "muu", "dissent": 0}}}
    vaski = {"reports": {"LiVM 1/2026 vp": {"asia": "HE 12/2026 vp", "decision": "muutettuna", "decisionText": "että lakiehdotus hyväksytään muutettuna.",
                                            "changedSections": ["3 §"], "dissent": 1, "dissentParties": ["ps"], "kind": "mietintö"}}}
    out = build_lausunnot.build_lausunnot([{"id": "fi-he-12-2026", "heNumerot": ["12/2026"]}], {}, vaski, asiat)
    assert out["fi-he-12-2026"]["valiokunnat"] == 2 and out["fi-he-12-2026"]["n"] == 1
    d = json.loads((tmp_path / "fi-he-12-2026.json").read_text(encoding="utf-8"))
    pev, livm = d["valiokunnat"]
    assert pev["tunnus"] == "PeVL 3/2026 vp" and pev["committeeName"] == "perustuslakivaliokunta" and "tavallisen lain" in pev["gist"]
    assert "decision" not in pev and pev["url"] == "https://www.eduskunta.fi/valtiopaivaasiakirjat/PeVL+3/2026"
    assert livm["decision"] == "muutettuna" and livm["changedSections"] == ["3 §"] and livm["dissent"] == 1
    assert d["eduskunta"]["rivit"][0]["kind"] == "lisäselvitys"


def test_committee_row_drops_boilerplate_ponsi_and_keeps_view():
    r = build_lausunnot.committee_row({"tunnus": "LaVL 13/2026 vp", "kind": "lausunto", "committee": "LaV"},
                                      {"decisionText": "että valtiovarainvaliokunta ottaa edellä olevan huomioon."},
                                      {"ok": True, "gist": "Valiokunta pitää tilannetta ongelmallisena."})
    assert "gist" not in r and r["view"].startswith("Valiokunta pitää") and r["committeeName"] == "lakivaliokunta"
    r = build_lausunnot.committee_row({"tunnus": "TaVL 30/2026 vp", "kind": "lausunto", "committee": "TaV"},
                                      {"decisionText": "että se yhtyy asiassa valtioneuvoston kantaan."}, None)
    assert r["yhtyy"] is True and "gist" not in r and "view" not in r


def test_committee_view_from_pdf_text():
    text = ("VALTIONEUVOSTON SELVITYS\nValtioneuvosto kannattaa ehdotusta ja pitää sitä hyvänä kokonaisuutena koko unionin kannalta.\n"
            "VALIOKUNNAN KANNANOTOT\nValiokunta pitää ehdotuksen tavoitetta kannatettavana mutta katsoo, että siirtymäaika on liian lyhyt.")
    assert fl.pick_gist(text.split("VALIOKUNNAN KANNANOTOT")[1], "Valiokunta", prefer=fl.COMMITTEE_VIEW).startswith("Valiokunta pitää")


def test_committee_view_ignores_dissent_after_signature(monkeypatch):
    # YmVL 29/2026 vp: after the signature come the members' "Eriävä mielipide" with its own "Perustelut"
    text = ("Ympäristövaliokunta\nVALIOKUNNAN KANNANOTOT\nPerustelut\n"
            "Valiokunta pitää tätä hyvänä ja katsoo, että lohikannan tilaa koskevat uusimmat tiedot tulee ottaa huomioon.\n"
            "Lausunto\nYmpäristövaliokunta ilmoittaa, että se yhtyy valtioneuvoston kantaan. Helsingissä 14.10.2026 "
            "Asian ratkaisevaan käsittelyyn ovat ottaneet osaa.\nEriävä mielipide\nPerustelut\n"
            "Valiokunnan enemmistön kanta on mielestämme virheellinen kalakantojen kannalta.\n"
            "Mielipide\nEdellä olevan perusteella esitämme, että suuri valiokunta muuttaa valtioneuvoston kantaa.\n")
    monkeypatch.setattr(fl, "pdf_text", lambda data, n: (text, 3))
    gist = fl.summarise_committee(b"%PDF")["gist"]
    assert gist.startswith("Valiokunta pitää tätä hyvänä") and "esitämme" not in gist and "enemmistön" not in gist


def test_committee_docs_reread_when_reader_improves():
    assert fl.COMMITTEE_VERSION >= 2


def test_committee_ponsi_gets_its_subject():
    import build_lausunnot as bl
    row = bl.committee_row({"tunnus": "YmVL 29/2026 vp", "committee": "YmV", "kind": "lausunto"},
                           {"decisionText": "että se yhtyy asiassa valtioneuvoston kantaan edellä esitetyin painotuksin."})
    assert row["gist"].startswith("Ympäristövaliokunta esittää, että se yhtyy") and row["yhtyy"]
