"""Unit tests for scripts/fetch_hediff.py and scripts/build_hediff.py against saved samples
(tests/samples/hediff/ and tests/samples/vaski/). No network."""
from __future__ import annotations

import datetime as dt
import difflib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_hediff as B
import fetch_hediff as H
from fetch_vaski import strip_ns

SAMPLES = ROOT / "tests" / "samples" / "hediff"
VASKI = ROOT / "tests" / "samples" / "vaski"


def xml(path: Path):
    return strip_ns(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def he118():
    return H.parse_he_xml(xml(SAMPLES / "he_HE_118_2026_trimmed.xml"))


@pytest.fixture(scope="module")
def pdf118():
    return H.parallel_texts((SAMPLES / "he_HE_118_2026_rinnakkaistekstit_p39-41.pdf").read_bytes())


@pytest.fixture(scope="module")
def tyvm6():
    return H.parse_report_xml(xml(SAMPLES / "report_TyVM_6_2026_trimmed.xml"))


# ------------------------------------------------------------------ text helpers
def test_text_helpers():
    assert H.tidy("  foo ,  bar ( x ) — y  ") == "foo, bar (x) – y"
    assert H.sec_key("27 a § (Uusi)") == "27a§" == H.sec_key("27a §")
    assert H.sec_label("6b §") == "6 b §" and H.sec_label("46 a § (Uusi)") == "46 a §" and H.sec_label("Voimaantulo") == "Voimaantulo"
    assert H.chap_key("5 Luku") == "5" and H.chap_key("2 c luvun") == "2c" and H.chap_key(None) is None
    assert H.norm_name("Laki  vuosilomalain muuttamisesta") == H.norm_name("laki vuosilomalain muuttamisesta")


def test_join_lines_keeps_real_hyphens():
    assert H.join_lines(["yritys- ja", "yhteisötunnus"]) == "yritys- ja yhteisötunnus"
    assert H.join_lines(["tiedot yritys-", "ja yhteisötunnus"]) == "tiedot yritys- ja yhteisötunnus"
    assert H.join_lines(["sekä Senaatti-", "kiinteistöjen"]) == "sekä Senaatti-kiinteistöjen"
    assert H.join_lines(["EU-", "jäsenvaltio"]) == "EU-jäsenvaltio"
    assert H.join_lines(["Hakijan tulee", "", "saapua"]) == "Hakijan tulee saapua"


# ------------------------------------------------------------------ HE XML
def test_parse_he_xml(he118):
    assert [(l["n"], l["name"], l["kind"]) for l in he118] == [
        ("1", "Laki vuosilomalain muuttamisesta", "muutos"), ("2", "Laki opintovapaalain 3 ja 15 §:n muuttamisesta", "muutos")]
    law = he118[0]
    assert [s["id"] for s in law["sections"]] == ["22 §", "27 §", "27 a §", "Voimaantulo"]
    s22 = law["sections"][0]
    assert s22["key"] == "22§" and s22["chapter"] == "5 Luku" and s22["heading"] == "Työntekijöiden kuuleminen"
    assert s22["text"].startswith("Työnantajan on selvitettävä työntekijöille") and "\n" not in s22["text"]
    s27 = law["sections"][1]
    assert s27["text"].split("\n") == ["— — —", "Mitä 25 ja 26 §:ssä säädetään vuosiloman siirtämisestä ja siirretyn loman antamisesta, koskee myös säästövapaata.", "— — —"]
    voim = law["sections"][3]
    assert voim["voimaantulo"] and voim["text"].startswith("Tämä laki tulee voimaan päivänä kuuta 20.")  # Aukko elements -> spaces
    assert "muutetaan vuosilomalain (162/2005) 22 § ja 27 §:n 3 momentti" in law["johtolause"]
    new_law = H.parse_he_xml(xml(SAMPLES / "he_HE_17_2026_trimmed.xml"))[0]
    assert new_law["kind"] == "uusi" and new_law["name"].startswith("Laki eräistä rajat ylittävän")
    assert H.law_kind("Laki vanhan lain kumoamisesta", "kumotaan vanha laki") == "kumoaminen"


# ------------------------------------------------------------------ parallel texts (PDF)
def test_parallel_texts_from_pdf(pdf118):
    assert pdf118["status"] == "ok" and pdf118["start"] == 1 and pdf118["pages"] == 3
    assert [(l["n"], l["name"]) for l in pdf118["laws"]] == [
        ("1", "Laki vuosilomalain muuttamisesta"), ("2", "Laki opintovapaalain 3 ja 15 §:n muuttamisesta")]
    law1 = {s["id"]: s for s in pdf118["laws"][0]["sections"]}
    assert list(law1) == ["22 §", "27 §", "27 a §", "Voimaantulo"]
    s22 = law1["22 §"]
    assert s22["heading"] == "Työntekijöiden kuuleminen"
    assert s22["old"].startswith("Työnantajan on selvitettävä työntekijöille tai heidän edustajilleen vuosiloman antamisessa työpaikalla")
    assert s22["new"].startswith("Työnantajan on selvitettävä työntekijöille tai heidän edustajilleen vuosiloman antamisessa ja säästövapaan pitämisessä")
    assert s22["old"].endswith("tasapuolisuutta lomien sijoittamisessa.")  # the cell continues on the next line of the row
    assert s22["new"].endswith("tasapuolisuutta vuosilomien ja säästövapaan sijoittamisessa.")
    s27 = law1["27 §"]
    assert s27["old"].split("\n")[0] == "— — —" and s27["old"].split("\n")[-1] == "— — —"
    assert "koskee myös säästövapaata." in s27["old"] and s27["new"].split("\n") == [
        "— — —", "Mitä 25 ja 26 §:ssä säädetään vuosiloman siirtämisestä ja siirretyn loman antamisesta, koskee myös säästövapaata.", "— — —"]
    s27a = law1["27 a §"]  # left cell empty -> new section
    assert s27a["old"] is None and s27a["heading"] == "Säästövapaan ajankohta"
    assert s27a["new"].split("\n")[0] == "Säästövapaan ajankohdasta on pyrittävä sopimaan työntekijän ja työnantajan välillä."
    assert len(s27a["new"].split("\n")) == 3
    voim = law1["Voimaantulo"]
    assert voim["old"] is None and voim["new"].startswith("Tämä laki tulee voimaan päivänä kuuta 20.") and "31 päivänä lokakuuta 2027." in voim["new"]
    law2 = {s["id"]: s for s in pdf118["laws"][1]["sections"]}
    assert list(law2) == ["3 §", "15 §", "Voimaantulo"]
    assert "oppisopimuslaissa (422/67)" in law2["3 §"]["old"] and "ammatillisesta koulutuksesta annetussa laissa (531/2017)" in law2["3 §"]["new"]
    assert law2["15 §"]["heading"] is None


def test_pdf_right_column_matches_he_xml(pdf118, he118):
    """The proposed text re-joined from the PDF column equals the HE XML text of the same pykälä."""
    for law, pdf_law in zip(he118, pdf118["laws"]):
        by_key = {s["key"]: s for s in law["sections"]}
        for s in pdf_law["sections"]:
            x = by_key[H.sec_key(s["id"])]
            a, b = B.normalize(x["text"]), B.normalize(s["new"])
            if s["id"] == "Voimaantulo":  # the HE's own PDF and XML differ by a few words in the transition clause
                assert difflib.SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio() > 0.95
            else:  # the PDF print drops a closing parenthesis in 15 § ("(1231/1996.") and the final period of 27 a §
                assert a.replace(")", "").rstrip(".") == b.replace(")", "").rstrip("."), s["id"]


def test_pair_columns_rules():
    def sec(sid, text, page, top, kind="section", mark=None, heading=None):
        return {"id": sid, "key": H.sec_key(sid), "chapter": None, "heading": heading, "text": text, "page": page, "top": top, "kind": kind, "mark": mark}
    law = {"table": True,
           "left": [sec("5 §", "vanha", 0, 100.0), sec("7 §", "", 0, 300.0, mark="uusi"), sec("9 §", "poistuu", 1, 50.0), sec("12 §", "a", 1, 200.0)],
           "right": [sec("5 §", "uusi teksti", 0, 100.0), sec("7 §", "lisätty", 0, 300.0), sec("9 §", "(kumotaan)", 1, 50.0, mark="kumotaan"),
                     sec("12 §", "b", 2, 10.0), sec("Voimaantulo", "Tämä laki", 2, 400.0, kind="voimaantulo")]}
    out = {s["id"]: s for s in H.pair_columns(law)}
    assert out["5 §"]["old"] == "vanha" and out["5 §"]["new"] == "uusi teksti"
    assert out["7 §"]["old"] is None and out["7 §"]["new"] == "lisätty"              # '(uusi) | 7 §' row
    assert out["9 §"]["old"] == "poistuu" and out["9 §"]["new"] == "(kumotaan)"       # '9 § | (kumotaan)' row
    assert out["12 §"]["old"] == "a" and out["12 §"]["new"] == "b"                    # drifted rows pair by number
    assert out["Voimaantulo"]["old"] is None
    law["table"] = False  # free-flowing columns: number pairing only
    out = {s["id"]: s for s in H.pair_columns(law)}
    assert out["5 §"]["old"] == "vanha" and out["7 §"]["old"] is None


# ------------------------------------------------------------------ committee report
def test_parse_report_xml_markers(tyvm6):
    assert tyvm6["tunnus"] == "TyVM 6/2026 vp" and tyvm6["date"] == "2026-09-25" and tyvm6["asia"] == "HE 118/2026 vp"
    assert [(l["n"], l["name"]) for l in tyvm6["laws"]] == [("1", "Laki vuosilomalain muuttamisesta")]  # law 2 has no markers
    s = tyvm6["laws"][0]["sections"]
    assert [x["id"] for x in s] == ["Voimaantulo"]
    assert "voimaan tullessa olleita säännöksiä" in s[0]["base"] and "voimassa olleita säännöksiä" in s[0]["clean"]
    havm = H.parse_report_xml(xml(VASKI / "report_HaVM_15_2026_trimmed.xml"))
    law1 = havm["laws"][0]
    s18 = next(x for x in law1["sections"] if x["id"] == "18 §")
    assert "julkista tehtävää hoitaville" in s18["base"] and "julkista hallintotehtävää hoitaville" in s18["clean"]  # inline insertion
    law19 = next(l for l in havm["laws"] if l["n"] == "19")
    assert law19["sections"][0]["id"] == "10 §" and law19["sections"][0]["new"] and law19["johtolause"]
    assert law19["name"] == "Laki tiettyjen Euroopan unionin ja kansallisten maatalouden tukien toimeenpanosta annetun lain 10 ja 12 §:n muuttamisesta"
    vavm = H.parse_report_xml(xml(VASKI / "report_VaVM_22_2026.xml"))
    assert vavm["laws"] == []  # its only marked Saados is inside a vastalause, not the committee's text


def test_assemble_report_uses_he_text(tyvm6, he118):
    rep = H.assemble_report(tyvm6, he118)
    assert rep["tunnus"] == "TyVM 6/2026 vp" and len(rep["laws"]) == 1
    sec = rep["laws"][0]["sections"][0]
    assert sec["id"] == "Voimaantulo" and "heFrom" not in sec
    assert sec["he"] == he118[0]["sections"][3]["text"]
    assert sec["committee"] != sec["he"] and "voimassa olleita säännöksiä" in sec["committee"]
    # HE 17/2026: the HE text comes from the HE XML; committee-added laws fall back to the report's own base text
    he17 = H.parse_he_xml(xml(SAMPLES / "he_HE_17_2026_trimmed.xml"))
    rep = H.assemble_report(H.parse_report_xml(xml(VASKI / "report_HaVM_15_2026_trimmed.xml")), he17)
    law1 = rep["laws"][0]
    s18 = next(s for s in law1["sections"] if s["id"] == "18 §")
    assert "heFrom" not in s18 and s18["he"] == next(s for s in he17[0]["sections"] if s["id"] == "18 §")["text"]
    assert "hallintotehtävää" in s18["committee"] and "hallintotehtävää" not in s18["he"]
    law2 = next(l for l in rep["laws"] if l["n"] == "2")
    assert law2["sections"][0]["id"] == "Johtolause"
    assert law2["sections"][1]["id"] == "46 a §" and law2["sections"][1]["heFrom"] == "mietintö" and law2["sections"][1]["added"]
    H.shrink_entry({"laws": [], "report": rep})  # flags must survive the size pass


# ------------------------------------------------------------------ cache entry
def test_assemble_laws_and_shrink(he118, pdf118):
    laws = H.assemble_laws(he118, pdf118)
    assert [(l["n"], l["parallel"], [s["id"] for s in l["sections"]]) for l in laws] == [
        ("1", True, ["22 §", "27 §", "27 a §", "Voimaantulo"]), ("2", True, ["3 §", "15 §", "Voimaantulo"])]
    assert laws[0]["sections"][2]["old"] is None and "note" not in laws[0]
    # an amending law without parallel texts keeps the HE text with old = null and a note; a new law gets no note
    no_pdf = H.assemble_laws(he118, {"status": "none", "laws": []})
    assert no_pdf[0]["parallel"] is False and no_pdf[0]["note"] and no_pdf[0]["sections"][0]["old"] is None
    assert H.assemble_laws(he118, None)[0].get("note") is None
    new_law = H.parse_he_xml(xml(SAMPLES / "he_HE_17_2026_trimmed.xml"))
    out = H.assemble_laws(new_law, {"status": "ok", "laws": []})
    assert out[0]["kind"] == "uusi" and "note" not in out[0] and len(out[0]["sections"]) == 7
    big = {"laws": [{"n": "1", "name": "Laki", "kind": "uusi", "parallel": False,
                     "sections": [{"id": f"{i} §", "heading": None, "old": None, "new": "sana " * 3000} for i in range(30)]}], "report": None}
    H.shrink_entry(big)
    assert H.doc_size(big) <= H.HE_CAP
    assert all(len(s["new"]) <= 810 and s["new"].endswith("[…]") for s in big["laws"][0]["sections"])  # new-law text is cut first
    assert big["laws"][0].get("omitted", 0) + len(big["laws"][0]["sections"]) == 30
    huge = {"laws": [{"n": "1", "name": "Laki", "kind": "muutos", "parallel": True,
                      "sections": [{"id": f"{i} §", "heading": None, "old": "a " * 4000, "new": "b " * 4000} for i in range(40)]}], "report": None}
    H.shrink_entry(huge)
    assert H.doc_size(huge) <= H.HE_CAP and all(s["old"].endswith("[…]") for s in huge["laws"][0]["sections"])  # amended sections cut
    huge["laws"][0]["sections"] = [{"id": f"{i} §", "heading": None, "old": "a " * 4000, "new": "b " * 4000} for i in range(80)]
    H.shrink_entry(huge)
    assert H.doc_size(huge) <= H.HE_CAP and huge["laws"][0]["omitted"] >= 1  # and the longest dropped when that is not enough


def test_selection_and_refetch_rules(monkeypatch):
    monkeypatch.setattr(H, "TODAY", dt.date(2026, 10, 18))
    monkeypatch.setattr(H, "days_ago", lambda iso: (dt.date(2026, 10, 18) - dt.date.fromisoformat(iso[:10])).days if iso else None)
    ek = {"1/2026": {"final": False, "stages": [{"code": "ANTO", "date": "2026-02-05"}], "reports": []},
          "2/2026": {"final": True, "vahvistettu": "2026-09-01", "stages": [{"code": "ANTO", "date": "2026-02-05"}], "reports": [{"tunnus": "HaVM 1/2026 vp"}]},
          "3/2026": {"final": True, "vahvistettu": "2026-05-01", "stages": [{"code": "ANTO", "date": "2026-02-05"}]},
          "9/2024": {"final": False, "stages": [{"code": "ANTO", "date": "2024-01-10"}]},
          "4/2026": {"final": False, "tila": "Rauennut", "stages": [{"code": "ANTO", "date": "2026-03-05"}]},
          "HE 5/2026 vp": {"final": False, "stages": [{"code": "ANTO", "date": "2026-03-05"}]}}
    assert H.select_hes(ek) == ["2/2026", "1/2026"]  # with a report first; confirmed > 60 days, > 540 days, lapsed and odd keys dropped
    vaski = {"reports": {"TyVM 6/2026 vp": {"asia": "HE 1/2026 vp", "kind": "mietintö", "date": "2026-09-25"},
                         "TyVL 2/2026 vp": {"asia": "HE 1/2026 vp", "kind": "lausunto", "date": "2026-09-30"}}}
    assert H.report_for("1/2026", vaski) == ("TyVM 6/2026 vp", "2026-09-25") and H.report_for("2/2026", vaski) is None
    assert H.needs_fetch(None, None) == (True, False)
    done = {"fetched": "2026-10-18", "created": "x", "status": "ok", "pdf": "ok", "laws": [], "report": None}
    assert H.needs_fetch(done, None) == (False, False)
    assert H.needs_fetch(done, ("TyVM 6/2026 vp", "2026-09-25")) == (True, True)
    done["report"] = {"tunnus": "TyVM 6/2026 vp", "date": "2026-09-25", "laws": []}
    assert H.needs_fetch(done, ("TyVM 6/2026 vp", "2026-09-25")) == (False, False)
    assert H.needs_fetch(done, ("TyVM 6/2026 vp", "2026-10-01")) == (True, True)  # re-published report
    failed = {"fetched": "2026-10-01", "created": "x", "status": "ok", "pdf": "error", "pdfTries": 1, "laws": [], "report": None}
    assert H.needs_fetch(failed, None) == (True, False)
    failed["fetched"] = "2026-10-17"
    assert H.needs_fetch(failed, None) == (False, False)


# ------------------------------------------------------------------ word diff
def test_word_diff_roundtrip_and_shape():
    old = "Työnantajan on selvitettävä  työntekijöille, mitä laissa säädetään.\nToinen momentti, joka säilyy."
    new = "Työnantajan on selvitettävä työntekijöille ja heidän edustajilleen, mitä laissa säädetään.\nToinen momentti, joka muuttuu."
    ops = B.word_diff(old, new)
    assert all(k in ("=", "-", "+") for k, _ in ops)
    assert B.join_ops(ops, "=-") == B.normalize(old) and B.join_ops(ops, "=+") == B.normalize(new)
    assert any(k == "+" and "ja heidän edustajilleen" in t for k, t in ops)
    assert ["-", "säilyy."] in ops and ["+", "muuttuu."] in ops
    assert "\n" in B.join_ops(ops) and "  " not in B.join_ops(ops)
    assert B.word_diff(None, "Uusi pykälä.") == [["+", "Uusi pykälä."]] and B.word_diff("Vanha.", None) == [["-", "Vanha."]]
    assert B.word_diff("sama teksti", "sama teksti") == [["=", "sama teksti"]]


def test_collapse_long_unchanged_runs():
    words = [f"s{i}" for i in range(100)]
    ops = [["=", " ".join(words[:50]) + "\n" + " ".join(words[50:])], ["-", "pois"], ["+", "tilalle"], ["=", "lyhyt loppu"]]
    out = B.collapse(ops)
    assert out[0] == ["=", " ".join(words[:12])] and out[1] == ["…", "76 sanaa"] and out[2] == ["=", " ".join(words[88:])]
    assert out[3:] == [["-", "pois"], ["+", "tilalle"], ["=", "lyhyt loppu"]]
    assert B.collapse([["=", " ".join(words[:40])]]) == [["=", " ".join(words[:40])]]  # not over the threshold
    head = B.collapse([["=", " ".join(words[:5]) + "\n" + " ".join(words[5:60])]])[0][1]
    assert head.split("\n")[0] == " ".join(words[:5])  # paragraph breaks inside the kept context survive


# ------------------------------------------------------------------ files
def test_build_hediff_writes_files(tmp_path, he118, pdf118, tyvm6):
    entry = {"fetched": "2026-10-18", "created": "2026-06-29", "status": "ok", "pdf": "ok",
             "laws": H.assemble_laws(he118, pdf118), "report": H.assemble_report(tyvm6, he118)}
    cache = {"fetched": "2026-10-18T10:00:00Z", "he": {"118/2026": entry, "999/2026": entry}}
    items = [{"id": "fi-he-118-2026", "heNumerot": ["118/2026"]}, {"id": "fi-he-1-2026", "heNumerot": ["1/2026"]}]
    (tmp_path / "fi-he-stale-2025.json").write_text("{}")
    result = B.build_hediff(items, cache=cache, out_dir=tmp_path)
    assert set(result) == {"fi-he-118-2026"}  # 999/2026 has no item; the stale file is removed
    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["fi-he-118-2026.json"]
    doc = json.loads((tmp_path / "fi-he-118-2026.json").read_text(encoding="utf-8"))
    assert doc["id"] == "fi-he-118-2026" and doc["he"] == "118/2026" and doc["generated"] == H.TODAY.isoformat()
    assert [s["kind"] for s in doc["steps"]] == ["he", "mietinto"]
    he_step, vk_step = doc["steps"]
    assert he_step["label"] == "Voimassa oleva → HE" and vk_step["label"] == "HE → valiokunnan mietintö (TyVM 6/2026 vp)"
    assert vk_step["tunnus"] == "TyVM 6/2026 vp" and vk_step["date"] == "2026-09-25"
    law1 = he_step["laws"][0]
    assert law1["name"] == "Laki vuosilomalain muuttamisesta" and law1["kind"] == "muutos"
    secs = {s["id"]: s for s in law1["sections"]}
    assert secs["27 a §"]["new"] is True and secs["27 a §"]["ops"][0][0] == "+" and secs["22 §"]["new"] is False
    assert secs["Voimaantulo"]["new"] is False  # the entry-into-force clause is not counted as a new pykälä
    assert ["-", "loman"] in secs["22 §"]["ops"] and ["+", "vuosiloman"] in secs["22 §"]["ops"]
    assert all({k for k, _ in s["ops"]} <= {"=", "-", "+", "…"} for law in he_step["laws"] for s in law["sections"])
    assert doc["summary"] == result["fi-he-118-2026"]
    assert doc["summary"]["he"] == {"laws": 2, "sections": 7, "new": 1, "removed": 0}
    assert doc["summary"]["mietinto"] == {"laws": 1, "sections": 1, "tunnus": "TyVM 6/2026 vp"}
    vk = vk_step["laws"][0]["sections"][0]
    assert vk["id"] == "Voimaantulo" and ["+", "voimassa"] in vk["ops"]
    assert (tmp_path / "fi-he-118-2026.json").stat().st_size <= B.FILE_CAP


def test_build_hediff_file_cap(tmp_path):
    big_text = "\n".join(" ".join(f"sana{i}k{j}" for i in range(500)) for j in range(3))
    laws = [{"n": "1", "name": "Laki suuri", "kind": "uusi", "parallel": False,
             "sections": [{"id": f"{i} §", "heading": None, "old": None, "new": big_text} for i in range(60)]}]
    cache = {"he": {"7/2026": {"status": "ok", "pdf": "none", "laws": laws, "report": None}}}
    result = B.build_hediff([{"id": "fi-he-7-2026", "heNumerot": ["7/2026"]}], cache=cache, out_dir=tmp_path)
    f = tmp_path / "fi-he-7-2026.json"
    assert f.stat().st_size <= B.FILE_CAP and result["fi-he-7-2026"]["he"]["new"] == 60
    doc = json.loads(f.read_text(encoding="utf-8"))
    assert all(s.get("truncated") for s in doc["steps"][0]["laws"][0]["sections"])
