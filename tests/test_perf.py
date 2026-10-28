"""Vierityksen sujuvuus: tyylit, jotka pakottavat koko näkymän uudelleenpiirron joka vierityskuvassa."""
from __future__ import annotations

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "docs" / "index.html").read_text(encoding="utf-8")
CSS = re.sub(r"/\*.*?\*/", "", "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", HTML, re.S)), flags=re.S)


def test_no_fixed_attachment_backgrounds():
    # background-attachment:fixed (tai lyhenne "... fixed") repaintaa koko ikkunan joka kuvassa;
    # kiinteä tausta tehdään position:fixed-kerroksena (body::before)
    bad = [m.group(0) for m in re.finditer(r"background(?:-attachment)?\s*:[^;}]*\bfixed\b[^;}]*", CSS)]
    assert not bad, bad


def test_page_tall_view_has_no_backdrop_blur():
    rules = re.findall(r"(?:^|})\s*\.view\s*\{([^}]*)\}", CSS)
    assert any(re.search(r"(?<!-)backdrop-filter\s*:\s*none", r) for r in rules)
