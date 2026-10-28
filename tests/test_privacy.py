"""Tietosuoja: julkaistavasta aineistosta poistetaan tarpeettomat henkilötiedot, eikä sivu käytä kolmansia osapuolia."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import common  # noqa: E402

HTML = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")


def test_personal_contacts_are_redacted_but_role_addresses_kept():
    s = common._scrub_text
    assert s("Lisätietoja: matti.meikalainen@kunta.fi tai kirjaamo@kunta.fi") == "Lisätietoja: [sähköposti] tai kirjaamo@kunta.fi"
    assert s("https://etu.suku@kunta.fi") == "[sähköposti]"
    assert s("puh. 09 1234 5678") == "puh. [puhelin]" and s("040 123 4567 Viranomaisille") == "[puhelin] Viranomaisille"
    assert s("tel. +358 40 123 4567") == "tel. [puhelin]"
    # identifiers that look like numbers stay intact
    for keep in ("HEL 2025-010605 T 02 08 02 00", "HUS 263-2026", "CPV 09310000", "dnro 040/2026", "HE 66/2026 vp", "12 345 euroa"):
        assert s(keep) == keep


def test_hearing_names_and_signers_are_dropped():
    tree = {"kuulemiset": [{"heard": [{"name": "Etu Suku", "org": "Virasto", "title": "johtaja"}]}]}
    out = common.scrub_personal(tree)
    assert out["kuulemiset"][0]["heard"] == [{"org": "Virasto", "title": "johtaja"}]
    assert common.scrub_personal(tree, text=False)["kuulemiset"][0]["heard"][0].get("name") is None


def test_save_json_scrubs_everything_written_to_the_public_site():
    p = common.OUT_DIR / "_privacy_test.json"
    try:
        common.save_json(p, {"t": "yhteyshenkilö etu.suku@virasto.fi, puh. 050 123 4567", "heard": [{"name": "X Y", "org": "O"}]})
        txt = p.read_text(encoding="utf-8")
        assert "etu.suku" not in txt and "050 123" not in txt and "X Y" not in txt
    finally:
        p.unlink(missing_ok=True)


def test_no_third_party_requests_or_tracking():
    assert not re.search(r"fonts\.(googleapis|gstatic)\.com|googletagmanager|google-analytics|gtag\(|plausible|matomo|hotjar|clarity\.ms", HTML)
    assert not re.search(r"<(script|link)[^>]+(src|href)=[\"']https?://", HTML), "ulkoinen skripti tai tyylitiedosto"
    for f in re.findall(r"url\((fonts/[\w.-]+)\)", HTML):
        assert (ROOT / "docs" / f).is_file(), f


def test_page_is_not_indexed_and_has_privacy_notice():
    assert re.search(r'<meta name="robots" content="noindex', HTML)
    assert 'id="open-privacy"' in HTML and 'id="priv"' in HTML


def test_no_credentials_in_tracked_text_files():
    import subprocess
    files = subprocess.check_output(["git", "ls-files", "scripts", "config", ".github", "docs/index.html", "docs/js", "README.md"], cwd=ROOT, text=True).split()
    rx = re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY|sk-ant-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}")
    hits = [f for f in files if (ROOT / f).is_file() and rx.search((ROOT / f).read_text(encoding="utf-8", errors="ignore"))]
    assert not hits, hits


def test_link_fields_holding_only_a_personal_email_are_dropped():
    out = common.scrub_personal({"docsUrl": "https://etu.suku@kunta.fi", "url": "https://www.hankintailmoitukset.fi/fi/x"})
    assert "docsUrl" not in out and out["url"].startswith("https://")
