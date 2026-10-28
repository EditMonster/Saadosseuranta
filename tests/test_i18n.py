"""Kielivalinta FI/SV/EN/ET/LT: sanakirjan eheys ja sivuun upotetun kopion ajantasaisuus."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_i18n  # noqa: E402

D = json.loads((ROOT / "config" / "i18n" / "en.json").read_text(encoding="utf-8"))
SV = json.loads((ROOT / "config" / "i18n" / "sv.json").read_text(encoding="utf-8"))
ET = json.loads((ROOT / "config" / "i18n" / "et.json").read_text(encoding="utf-8"))
LT = json.loads((ROOT / "config" / "i18n" / "lt.json").read_text(encoding="utf-8"))
TOPICS = re.findall(r"^  ([A-ZÄÖ][^:\n]+):\s*$", (ROOT / "config" / "topics.yaml").read_text(encoding="utf-8"), re.M)


def test_placeholders_survive_translation():
    for d in (D, SV, ET, LT):
        for k, v in d.items():
            for ph in ("{n}", "{d}"):
                assert k.count(ph) == v.count(ph), (k, v)
            assert v.strip() and v != k, k


def test_core_vocabulary():
    for fi, en in {"Tilannekuva": "Overview", "Kansallinen": "National", "Kilpailutukset": "Tenders", "Ratkaisut": "Rulings",
                   "Lausuttavissa nyt": "Open for comment now", "Asetukset": "Decrees", "Hallituksen esitys": "Government bill",
                   "{n} lausuntoa": "{n} statements"}.items():
        assert D[fi] == en
    # every topic and tender sector on the page has a translation
    assert TOPICS and all(t in D for t in TOPICS), [t for t in TOPICS if t not in D]


def test_core_vocabulary_sv():
    for fi, sv in {"Tilannekuva": "Lägesbild", "Kansallinen": "Nationell", "Kilpailutukset": "Upphandlingar",
                   "Ratkaisut": "Avgöranden", "Lausuttavissa nyt": "Öppna för remissvar nu", "Asetukset": "Förordningar",
                   "Hallituksen esitys": "Regeringens proposition", "{n} lausuntoa": "{n} utlåtanden"}.items():
        assert SV[fi] == sv
    assert all(t in SV for t in TOPICS), [t for t in TOPICS if t not in SV]


def test_dictionaries_cover_the_same_ui():
    # a key added for one language only would leave the other half-translated
    missing = sorted(set(D) - set(SV))
    assert len(missing) < 40, missing[:40]


def test_embedded_copy_is_current():
    assert build_i18n.main(check=True) == 0, "aja python scripts/build_i18n.py"


def test_core_vocabulary_et_lt():
    for fi, et, lt in (("Tilannekuva", "Ülevaade", "Apžvalga"), ("Kilpailutukset", "Hanked", "Pirkimai"),
                       ("Hallituksen esitys", "Valitsuse eelnõu", "Vyriausybės įstatymo projektas"), ("Kansiot", "Kaustad", "Aplankai"),
                       ("Alkuperäinen", "Originaal", "Originalas")):
        assert ET[fi] == et and LT[fi] == lt
    for d in (ET, LT):
        assert all(t in d for t in TOPICS), [t for t in TOPICS if t not in d]
        assert len(set(D) - set(d)) < 40, sorted(set(D) - set(d))[:40]
        assert not [k for k, v in d.items() if "<unk>" in v]
