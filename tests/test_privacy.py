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
    assert s("kirjaamo.hva@keusote.fi, helsinki.kirjaamo@hel.fi") == "kirjaamo.hva@keusote.fi, helsinki.kirjaamo@hel.fi"
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
    assert not re.search(r"fonts\.(googleapis|gstatic)\.com|googletagmanager|google-analytics|gtag\(|plausible\.io|matomo\.(?:js|php)|_paq\.push|hotjar|clarity\.ms", HTML)
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


def test_private_individuals_are_not_named():
    tree = {"items": [{"lausunnot": {"orgs": ["Kuntaliitto", "Meikäläinen Matti"], "docs": [
        {"id": "a", "org": "Meikäläinen Matti", "title": "Yksityishenkilön lausunto"},
        {"id": "b", "org": "Meikäläinen Matti", "title": "Meikäläinen Matti, lausunto"},
        {"id": "c", "org": "Yksityismetsätalouden Työnantajat ry", "title": "Yksityismetsätalouden Työnantajat ry; lausunto"}]}}]}
    out, n = common.mask_private_givers(tree)
    txt = json.dumps(out, ensure_ascii=False)
    assert n == 1 and "Meikäläinen" not in txt
    assert out["items"][0]["lausunnot"]["orgs"] == ["Kuntaliitto", common.PRIVATE_LABEL]
    assert "Yksityismetsätalouden Työnantajat ry" in txt  # an association whose name merely starts with "Yksityis-" stays
    assert common.scrub_personal({"org": "Etu Suku", "title": "Yksityishenkilö; lausunto"})["org"] == common.PRIVATE_LABEL


def test_public_repo_caches_are_minimised_too():
    p = common.CACHE_DIR / "_privacy_test.json"
    try:
        common.save_json(p, {"gist": "Etu Suku, päällikkö, p. +358 44 123 4567", "org": "Yhtiö Oy", "person": "Etu Suku",
                             "heard": [{"name": "X Y", "org": "O"}]})
        txt = p.read_text(encoding="utf-8")
        assert "123 4567" not in txt and '"person": "[nimi]"' in txt and "X Y" not in txt
    finally:
        p.unlink(missing_ok=True)


def test_no_personal_contacts_in_tracked_caches_or_samples():
    import subprocess
    files = subprocess.run(["git", "ls-files", "data/cache", "tests/samples"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    bad = []
    for f in files:
        if not f.endswith((".json", ".html", ".xml")):
            continue
        t = (ROOT / f).read_text(encoding="utf-8", errors="ignore")
        bad += [f"{f}: {m.group(0)}" for m in common._EMAIL.finditer(t)
                if "." in m.group(1) and not common._is_role(m.group(1)) and not m.group(1).startswith("etunimi.")]
        if f.startswith("data/cache"):
            bad += [f"{f}: {m.group(0)}" for m in common._PHONE.finditer(t)]
    assert not bad, bad[:10]


def test_hankeikkuna_summary_keeps_names_for_the_masker():
    # the masker learns a private giver's name from the marked statement, so the summary must not hide it first
    import fetch_hankeikkuna as fh
    docs = [{"uuid": "a", "laatija": {"fi": "Meikäläinen Matti"}, "nimi": {"fi": "Yksityishenkilön lausunto"}, "laatimispaiva": "2026-01-02"},
            {"uuid": "b", "laatija": {"fi": "Meikäläinen Matti"}, "nimi": {"fi": "Meikäläinen Matti, lausunto"}, "laatimispaiva": "2026-01-03"}]
    s = fh.summarise_statements(docs, None)
    out, n = common.mask_private_givers([{"lausunnot": s}])
    assert n == 1 and "Meikäläinen" not in json.dumps(out, ensure_ascii=False)


def test_sole_traders_are_masked_but_partnerships_kept():
    t = common.scrub_personal({"org": "Esa Esimerkki Tmi", "title": "Esa Esimerkki Tmi, lausunto", "stance": "kannattaa"})
    assert t["org"] == common.SOLE_LABEL and "Esimerkki" not in t["title"]
    assert common.scrub_personal({"org": "Toiminimi Matti M"})["org"] == common.SOLE_LABEL
    assert common.scrub_personal({"org": "Enskild firma Svensson"})["org"] == common.SOLE_LABEL
    lst = common.scrub_personal({"orgs": ["Kuntaliitto", "Mikro Tmi", "Toinen T:mi"]})["orgs"]
    assert lst == ["Kuntaliitto", common.SOLE_LABEL]
    # a limited partnership or general partnership is a company, not a sole trader; no false positives on words
    assert common.scrub_personal({"org": "Lidl Suomi Ky"})["org"] == "Lidl Suomi Ky"
    assert common.scrub_personal({"org": "Tmiaineistot Oy"})["org"] == "Tmiaineistot Oy"


def test_stakeholder_profiles_skip_hidden_givers():
    import build_sidosryhmat as bs
    rows = [{"org": common.SOLE_LABEL, "stance": "kannattaa"}, {"org": "Mikro Tmi", "stance": "vastustaa"},
            {"org": common.PRIVATE_LABEL, "stance": "osin"}, {"org": "Kuntaliitto", "stance": "kannattaa"}]
    res = bs.build({"x": {"kierros": {"rivit": rows}}}, {})
    assert list(res["orgs"]) == ["suomen kuntaliitto"]


def test_individuals_masked_on_rounds_and_never_profiled():
    assert common.looks_like_person("Olli Mäenpää") and common.looks_like_person("Professori Linna Tuula")
    assert common.looks_like_person("Lindgren Juha") and common.looks_like_person("Mari-Pauliina Vainikainen")
    for org in ("Tapio Oy", "Visit Ylläs", "Kirkon Ulkomaanapu", "Felicitas Mehiläinen", "Business Finland", "Suomen Kuntaliitto"):
        assert not common.looks_like_person(org), org
    # a private individual on a consultation round (no "Yksityishenkilön lausunto" title) is masked
    assert common.scrub_personal({"org": "Tapio Räty", "stance": "vastustaa"})["org"] == common.PRIVATE_LABEL
    assert common.scrub_personal({"orgs": ["Kuntaliitto", "Anh Tran", "Annina Vilkas"]})["orgs"] == ["Kuntaliitto", common.PRIVATE_LABEL]
    # an expert heard by Parliament keeps the name in the statement list (public role) ...
    assert common.scrub_personal({"org": "Olli Mäenpää", "stance": "kanta", "committee": "PeV"})["org"] == "Olli Mäenpää"
    assert common.scrub_personal({"org": "Olli Mäenpää", "stance": "kanta", "src": "ek"})["org"] == "Olli Mäenpää"
    # ... but no stakeholder profile is built of any individual
    import build_sidosryhmat as bs
    rows = [{"org": "Olli Mäenpää", "stance": "kannattaa", "committee": "PeV"}, {"org": "Kuntaliitto", "stance": "kannattaa"}]
    assert list(bs.build({"x": {"eduskunta": {"rivit": rows}}}, {})["orgs"]) == ["suomen kuntaliitto"]
