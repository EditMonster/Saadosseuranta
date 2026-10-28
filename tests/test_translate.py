"""Sisällön käännökset (scripts/translate.py, scripts/mt.py): viralliset käännökset ensin, konekäännös välimuistiin,
sivun käännöstiedostot vain kun teksti ei jo ole valitulla kielellä. Testit käyttävät valemoottoria – ei malleja."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import mt  # noqa: E402
import translate  # noqa: E402


class FakeEngine:
    available = True
    calls = 0

    def __init__(self, *a, **k):
        pass

    def to_english(self, texts, src):
        FakeEngine.calls += len(texts)
        return [f"EN({src}):{t}" for t in texts]

    def from_english(self, texts, tgt):
        FakeEngine.calls += len(texts)
        return [f"{tgt.upper()}:{t}" for t in texts]


def _setup(tmp_path, monkeypatch, items, tenders):
    out, cache = tmp_path / "docs", tmp_path / "cache"
    out.mkdir()
    cache.mkdir()
    (out / "items.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    (out / "hankinnat.json").write_text(json.dumps({"items": tenders}), encoding="utf-8")
    monkeypatch.setattr(translate, "OUT_DIR", out)
    monkeypatch.setattr(translate, "TR_DIR", out / "tr")
    monkeypatch.setattr(translate, "CACHE", cache / "kaannokset")
    monkeypatch.setattr(mt, "Engine", FakeEngine)
    return out, cache


def test_official_first_machine_otherwise_and_cached(tmp_path, monkeypatch):
    items = [{"id": "fi-he-1", "scope": "fi", "title": "Laki tupakkalain muuttamisesta", "summary": "Esityksessä ehdotetaan muutettavaksi tupakkalakia.",
              "titleSv": "Lag om ändring av tobakslagen", "fullTitleSv": "RP med förslag till lag om ändring av tobakslagen"},
             {"id": "eu-1", "scope": "eu", "title": "Asetus tekoälystä", "titleEn": "Regulation on artificial intelligence", "titleLt": "Reglamentas dėl dirbtinio intelekto"}]
    tenders = [{"id": "hk-ted-1", "scope": "hankinta", "country": "LV", "stage": "avoin", "title": "Ceļu uzturēšanas pakalpojumi / Road maintenance services"}]
    out, cache = _setup(tmp_path, monkeypatch, items, tenders)
    translate.main(budget_s=60)
    tr = {l: json.loads((out / "tr" / f"{l}.json").read_text(encoding="utf-8"))["items"] for l in translate.LANGS}
    # Swedish title of a Finnish bill: the official one, not a machine translation
    assert tr["sv"]["fi-he-1"]["t"] == "Lag om ändring av tobakslagen" and tr["sv"]["fi-he-1"]["o"] == "fi"
    assert tr["sv"]["fi-he-1"]["s"].startswith("SV:") and tr["sv"]["fi-he-1"]["m"] == 1  # the summary has no official version
    # EU: official English and Lithuanian titles; Estonian by machine
    assert tr["en"]["eu-1"]["t"] == "Regulation on artificial intelligence" and "m" not in tr["en"]["eu-1"]
    assert tr["lt"]["eu-1"]["t"] == "Reglamentas dėl dirbtinio intelekto"
    assert tr["et"]["eu-1"]["t"].startswith("ET:") and tr["et"]["eu-1"]["m"] == 1
    # a Finnish text is not "translated" into Finnish
    assert "fi-he-1" not in tr["fi"]
    # a bilingual tender title is translated from its English half; Finnish readers get it in Finnish
    assert tr["fi"]["hk-ted-1"]["t"] == "FI:EN(en):Road maintenance services" and tr["fi"]["hk-ted-1"]["o"] == "lv"
    # everything is cached: a second run translates nothing
    before = FakeEngine.calls
    translate.main(budget_s=60)
    assert FakeEngine.calls == before
    assert list((cache / "kaannokset").glob("*.json"))


def test_budget_zero_still_writes_official_translations(tmp_path, monkeypatch):
    items = [{"id": "fi-he-2", "scope": "fi", "title": "Laki arvonlisäverolain muuttamisesta", "titleSv": "Lag om ändring av mervärdesskattelagen"}]
    out, _ = _setup(tmp_path, monkeypatch, items, [])
    translate.main(budget_s=0)
    sv = json.loads((out / "tr" / "sv.json").read_text(encoding="utf-8"))["items"]
    assert sv["fi-he-2"]["t"] == "Lag om ändring av mervärdesskattelagen"
    assert "fi-he-2" not in json.loads((out / "tr" / "et.json").read_text(encoding="utf-8"))["items"]


def test_pivot_glossary_repairs():
    fix = mt._fix_pivot
    assert fix("Laki tuloverolain 93 §:n muuttamisesta", "Act amending Article 93 of the Income Tax Act", "fi") == "Act amending section 93 of the Income Tax Act"
    assert "artikla" in "EU-asetuksen 5 artikla" and fix("EU-asetuksen 5 artikla", "Article 5 of the EU Regulation", "fi") == "Article 5 of the EU Regulation"
    assert fix("Hallituksen esitys eduskunnalle", "Government proposal to the European Parliament", "fi") == "Government proposal to the Parliament of Finland"
    assert fix("x", "HE 173 / 2026 vp", "fi") == "HE 173/2026 vp"
    assert mt._fix_target("amending the Act") == "Amending the Act"


def test_language_guess_without_model():
    assert mt._guess("Kelių priežiūros paslaugos", ("lt", "en")) == "lt"
    assert mt._guess("Supply of laboratory equipment", ("lt", "en")) == "en"
    assert mt._guess("Ramavtal avseende konsulttjänster", ("sv", "en")) == "sv"
