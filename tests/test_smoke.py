"""Savutesti oikeassa selaimessa (Playwright + Chromium): sivu latautuu, jokainen välilehti
näyttää aineistoa, ja käyttäjän tärkeimmät toiminnot – kohteen avaaminen, tähti, kansioon
lisääminen, piilotus, suodattimet, siirtokoodi, teema, pysyvä linkki – toimivat ja säilyvät
sivun uudelleenlatauksen yli. Ajetaan joka pushilla; kesto noin puoli minuuttia.

Paikallisesti:  pip install pytest playwright && playwright install chromium && pytest tests/test_smoke.py
"""
from __future__ import annotations

import functools
import http.server
import json
import socketserver
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PORT = 8765


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401
        pass


@pytest.fixture(scope="module")
def base_url():
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), functools.partial(_Quiet, directory=str(DOCS)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{PORT}/"
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture()
def page(browser, base_url):
    """Tuore selainprofiili joka testiin: tyhjä localStorage, virheet talteen."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 950}, locale="fi-FI", timezone_id="Europe/Helsinki")
    pg = ctx.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
    pg.errors = errors  # type: ignore[attr-defined]
    yield pg
    assert not errors, errors
    ctx.close()


def goto(pg, base_url, hash_=""):
    pg.goto(base_url + hash_, wait_until="networkidle")
    pg.wait_for_function("typeof DATA !== 'undefined' && DATA.length > 0")
    pg.wait_for_function("typeof TENDERS_LOADED !== 'undefined' && TENDERS_LOADED === true")


def ls(pg, key):
    return pg.evaluate(f"JSON.parse(localStorage.getItem('{key}') || 'null')")


# ---------- lataus ja välilehdet ----------

def test_page_loads_with_data(page, base_url):
    goto(page, base_url)
    sys_text = page.text_content("#sys")
    assert "Aineisto" in sys_text and "ei voitu ladata" not in sys_text
    assert page.locator("#tab-now[aria-selected='true']").count() == 1
    assert page.locator("#kpis .kpi").count() >= 5
    assert "Ladataan" not in page.text_content("#l-open")


@pytest.mark.parametrize("tab,selector,minimum", [
    ("fi", "#tl-fi .row[data-id]", 50),
    ("eu", "#tl-eu .row[data-id]", 20),
    ("done", "#done-body tr.r", 20),
    ("hk", "#hk-list .hk-row", 20),
])
def test_tabs_render_rows(page, base_url, tab, selector, minimum):
    goto(page, base_url)
    page.click(f"#tab-{tab}")
    page.wait_for_selector(selector)
    n = page.locator(selector).count()
    assert n >= minimum, f"{tab}: vain {n} riviä"
    assert "Ei säädöksiä" not in page.text_content(f"#view-{tab}") and "Ei kilpailutuksia" not in page.text_content(f"#view-{tab}")


def test_hash_routing(page, base_url):
    goto(page, base_url, "#kilpailutukset")
    assert page.locator("#tab-hk[aria-selected='true']").count() == 1
    assert page.locator("#ptopics").is_visible() and page.locator("#lajit").is_hidden()
    page.click("#tab-eu")
    assert page.evaluate("location.hash") == "#eu"


# ---------- kohde, tähti, pysyvä linkki ----------

def test_drawer_follow_and_permalink(page, base_url):
    goto(page, base_url, "#kansallinen")
    page.click("#tl-fi .row[data-id] >> nth=0")
    page.wait_for_selector("#drawer:not([hidden])")
    item_id = page.evaluate("document.getElementById('drawer').dataset.id")
    assert page.text_content("#dr-title").strip()
    assert page.locator("#dr-src a").count() >= 1
    page.click("#dr-follow")
    assert item_id in ls(page, "saadosseuranta-follow")
    assert page.get_attribute("#dr-follow", "aria-pressed") == "true"
    page.keyboard.press("Escape")
    assert page.locator("#drawer").is_hidden()
    # pysyvä linkki avaa saman kohteen uudessa latauksessa
    goto(page, base_url, "#" + item_id)
    page.wait_for_selector("#drawer:not([hidden])")
    assert page.evaluate("document.getElementById('drawer').dataset.id") == item_id
    # tähti näkyy Tilannekuvan Seurannassa-paneelissa
    page.keyboard.press("Escape")
    page.click("#tab-now")
    assert page.locator(f"#l-follow li[data-id='{item_id}']").count() == 1


# ---------- kansiot ja piilotus ----------

def test_folders_add_filter_hide_persist(page, base_url):
    goto(page, base_url, "#kansallinen")
    # 1) luo kansio kohteen tiedoista ja lisää kohde
    page.click("#tl-fi .row[data-id] >> nth=0")
    first_id = page.evaluate("document.getElementById('drawer').dataset.id")
    page.click("#dr-fdrop-btn")
    page.fill("#dr-fnew", "Testikansio")
    page.click("#dr-fadd")
    folders = ls(page, "saadosseuranta-folders")
    assert [f["name"] for f in folders] == ["Testikansio"] and folders[0]["items"] == [first_id]
    assert "Testikansio" in page.text_content("#dr-fdrop-btn")
    page.keyboard.press("Escape"); page.keyboard.press("Escape")
    # 2) toinen kohde samaan kansioon rivipainikkeella
    page.click("#tl-fi .row[data-id] >> nth=1")
    second_id = page.evaluate("document.getElementById('drawer').dataset.id")
    page.click("#dr-fdrop-btn")
    page.click("#dr-flist .fr >> nth=0")
    assert set(ls(page, "saadosseuranta-folders")[0]["items"]) == {first_id, second_id}
    assert page.locator("#toast:not([hidden])").count() == 1
    page.keyboard.press("Escape"); page.keyboard.press("Escape")
    # 3) kansiomerkki rivillä ja kansiosuodatin
    assert page.locator(f"#tl-fi .row[data-id='{first_id}'] .pill.fold").count() == 1
    fid = folders[0]["id"]
    page.select_option("#folder-filter", fid)
    assert "Kansio: Testikansio" in page.text_content("#count")
    assert page.locator("#tl-fi .row[data-id]").count() == 2
    page.select_option("#folder-filter", "")
    # 4) piilotus rivin ×-painikkeesta, kumoa-ilmoitus, Piilotetut-näkymä ja palautus
    third_id = page.evaluate("document.querySelectorAll('#tl-fi .row[data-id]')[2].dataset.id")
    page.hover(f"#tl-fi .row[data-id='{third_id}']")
    page.click(f"#tl-fi .row[data-id='{third_id}'] [data-hide]")
    assert ls(page, "saadosseuranta-hidden") == [third_id]
    assert page.locator(f"#tl-fi .row[data-id='{third_id}']").count() == 0
    assert page.locator("#toast-undo").count() == 1
    page.select_option("#folder-filter", "__hidden")
    assert page.locator(f"#tl-fi .row[data-id='{third_id}']").count() == 1
    # 5) kaikki säilyy uudelleenlatauksen yli
    page.reload(wait_until="networkidle")
    page.wait_for_function("typeof TENDERS_LOADED !== 'undefined' && TENDERS_LOADED === true")
    assert ls(page, "saadosseuranta-hidden") == [third_id]
    assert set(ls(page, "saadosseuranta-folders")[0]["items"]) == {first_id, second_id}
    assert page.input_value("#folder-filter") == "__hidden"
    page.click(f"#tl-fi .row[data-id='{third_id}'] [data-restore]")
    assert ls(page, "saadosseuranta-hidden") == []
    # 6) Tilannekuvan kansiopainikkeet ja Hallitse-ikkuna
    page.select_option("#folder-filter", "")
    page.click("#tab-now")
    assert page.locator("#l-folders [data-fid]").count() >= 2  # Kaikki + Testikansio
    page.click(f"#l-folders [data-fid='{fid}']")
    assert "Testikansio" in page.text_content("#l-folder-info")
    page.click("#open-folders")
    page.wait_for_selector("#folders:not([hidden])")
    page.fill("#folder-new", "Toinen kansio"); page.click("#folder-add")
    assert [f["name"] for f in ls(page, "saadosseuranta-folders")] == ["Testikansio", "Toinen kansio"]
    page.click("#folders-close")


def test_tender_folder_and_sync_roundtrip(page, base_url):
    goto(page, base_url, "#kilpailutukset")
    page.click("#hk-list .hk-row >> nth=0")
    tid = page.evaluate("document.getElementById('drawer').dataset.id")
    assert tid.startswith("hk-")
    assert "Alkuperäinen ilmoitus Hilmassa" in page.text_content("#dr-src")
    assert page.locator("#dr-facts dl dt").count() >= 6
    page.click("#dr-fdrop-btn"); page.fill("#dr-fnew", "Hankinnat"); page.click("#dr-fadd")
    page.click("#dr-follow")
    page.keyboard.press("Escape"); page.keyboard.press("Escape")
    # siirtokoodi sisältää tähdet, kansiot ja piilotukset ja purkautuu takaisin samaksi
    code = page.evaluate("syncCode()")
    parsed = page.evaluate(f"parseSync({json.dumps(code)})")
    assert parsed["f"] == [tid] and parsed["k"] == [{"n": "Hankinnat", "i": [tid]}] and parsed["h"] == []
    # tuonti uuteen selaimeen linkistä
    ctx2 = page.context.browser.new_context()
    pg2 = ctx2.new_page()
    pg2.goto(base_url + "?s=" + code + "#tilannekuva", wait_until="networkidle")
    pg2.wait_for_function("typeof TENDERS_LOADED !== 'undefined' && TENDERS_LOADED === true")
    assert [f["name"] for f in ls(pg2, "saadosseuranta-folders")] == ["Hankinnat"]
    assert ls(pg2, "saadosseuranta-follow") == [tid]
    assert pg2.locator(f"#l-follow li[data-id='{tid}']").count() == 1
    ctx2.close()


# ---------- suodattimet ----------

def test_tender_filters(page, base_url):
    goto(page, base_url, "#kilpailutukset")
    total = int(page.text_content("#count").split()[0])
    page.select_option("#hk-within", "7")
    within = int(page.text_content("#count").split()[0])
    assert 0 < within < total
    page.select_option("#hk-within", "0")
    page.check("#hk-dps")
    assert int(page.text_content("#count").split()[0]) > total
    page.uncheck("#hk-dps")
    page.click("#hk-tools [data-scope='eu']")
    eu = int(page.text_content("#count").split()[0])
    page.click("#hk-tools [data-scope='fi']")
    fi = int(page.text_content("#count").split()[0])
    assert eu + fi == total
    page.click("#hk-tools [data-scope='all']")
    page.click("#ptopics .chip >> nth=1")
    assert int(page.text_content("#count").split()[0]) < total
    page.fill("#q", "zzzz-ei-osumia")
    assert "Ei kilpailutuksia" in page.text_content("#hk-list")


def test_tender_lifecycle_stages(page, base_url):
    goto(page, base_url, "#kilpailutukset")
    assert page.get_attribute("#hk-stages [data-stage='avoin']", "aria-pressed") == "true"
    open_n = int(page.text_content("#count").split()[0])
    for stage, word in (("tulossa", "tulossa"), ("ratkaistu", "ratkaistua"), ("suorahankinta", "suorahankintaa")):
        page.click(f"#hk-stages [data-stage='{stage}']")
        n = int(page.text_content("#count").split()[0])
        assert n > 0 and word in page.text_content("#count"), stage
        first = page.locator("#hk-list .hk-row").first
        assert page.evaluate("id=>TENDERS.find(t=>t.id===id).stage", first.get_attribute("data-id")) == stage
    # ratkaistu: winner shown, drawer carries the appeal-period note
    page.click("#hk-list .hk-row >> nth=0")
    assert "Valitusaika" in page.text_content("#dr-facts")
    page.keyboard.press("Escape")
    # suorahankinta: appeal deadline = published + 14 days, shown as the countdown
    page.click("#hk-stages [data-stage='suorahankinta']")
    page.click("#hk-list .hk-row >> nth=0")
    facts = page.text_content("#dr-facts")
    assert "147 §" in facts and "14 päivää" in facts
    assert "Valitusaika päättyy" in page.text_content("#dr-list")
    page.keyboard.press("Escape")
    # tab badge keeps counting open tenders regardless of the stage being viewed
    assert int(page.text_content("#n-hk")) == open_n
    # a procedure with several notices links them both ways
    rid = page.evaluate("(TENDERS.find(t=>t.related&&t.related.length)||{}).id")
    if rid:
        goto(page, base_url, "#" + rid)
        page.wait_for_selector("#drawer:not([hidden])")
        assert page.locator("#dr-facts [data-open]").count() >= 1
        page.click("#dr-facts [data-open] >> nth=0")
        assert page.evaluate("document.getElementById('drawer').dataset.id") != rid


def test_legislation_filters(page, base_url):
    goto(page, base_url, "#kansallinen")
    total = page.locator("#tl-fi .row[data-id]").count()
    page.check("#open-only")
    open_n = page.locator("#tl-fi .row[data-id]").count()
    assert 0 < open_n < total
    assert page.locator("#tl-fi .row .pill.open").count() == open_n
    page.uncheck("#open-only")
    page.click("#lajit .chip[data-laji='asetus']")
    assert page.locator("#tl-fi .row[data-id]").count() > total
    page.click("#topics .chip >> nth=1")
    assert page.locator("#tl-fi .row[data-id]").count() < total


# ---------- teema ----------

def test_theme_persists(page, base_url):
    goto(page, base_url)
    page.click("#theme-dark")
    assert page.get_attribute("html", "data-theme") == "dark"
    page.reload(wait_until="networkidle")
    assert page.get_attribute("html", "data-theme") == "dark"
    page.click("#theme-light")
    assert page.get_attribute("html", "data-theme") is None
