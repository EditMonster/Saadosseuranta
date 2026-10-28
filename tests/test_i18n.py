"""Kielivalinta FI/EN: sanakirjan eheys ja sivuun upotetun kopion ajantasaisuus."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_i18n  # noqa: E402

D = json.loads((ROOT / "config" / "i18n" / "en.json").read_text(encoding="utf-8"))


def test_placeholders_survive_translation():
    for k, v in D.items():
        for ph in ("{n}", "{d}"):
            assert k.count(ph) == v.count(ph), (k, v)
        assert v.strip() and v != k, k


def test_core_vocabulary():
    for fi, en in {"Tilannekuva": "Overview", "Kansallinen": "National", "Kilpailutukset": "Tenders", "Ratkaisut": "Rulings",
                   "Lausuttavissa nyt": "Open for comment now", "Asetukset": "Decrees", "Hallituksen esitys": "Government bill",
                   "{n} lausuntoa": "{n} statements"}.items():
        assert D[fi] == en
    # every topic and tender sector on the page has a translation
    topics = re.findall(r"^  ([A-ZÄÖ][^:\n]+):\s*$", (ROOT / "config" / "topics.yaml").read_text(encoding="utf-8"), re.M)
    assert topics and all(t in D for t in topics), [t for t in topics if t not in D]


def test_embedded_copy_is_current():
    assert build_i18n.main(check=True) == 0, "aja python scripts/build_i18n.py"
