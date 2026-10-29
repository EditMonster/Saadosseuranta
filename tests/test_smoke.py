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
    pg.wait_for_function("typeof MERGERS_LOADED !== 'undefined' && MERGERS_LOADED === true")
    pg.wait_for_function("typeof SHARED_LOADED !== 'undefined' && SHARED_LOADED === true")
    pg.wait_for_function("typeof RULINGS_LOADED !== 'undefined' && RULINGS_LOADED === true")


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
    ("yk", "#tl-yk .row[data-id]", 5),
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
    assert "147 §" in facts and ("14 päivää" in facts or "14 pv" in facts)
    assert "Valitusaika päättyy" in page.text_content("#dr-list")
    page.keyboard.press("Escape")
    # markkinaoikeus: pending appeals by default, rulings behind the sub-toggle, drawer with the KHO note
    page.click("#hk-stages [data-stage='mao']")
    assert "valitusta markkinaoikeudessa" in page.text_content("#count") and page.locator("#hk-mao-tools").is_visible()
    first = page.locator("#hk-list .hk-row").first
    assert "vireillä" in first.locator(".cd .big").text_content()
    first.click()
    facts = page.text_content("#dr-facts")
    assert "Vireille markkinaoikeudessa" in facts and "148 §" in facts
    assert "Vireillä olevat hankinta-asiat" in page.text_content("#dr-src")
    page.keyboard.press("Escape")
    page.click("#hk-mao-tools [data-mao='ratkaistu']")
    assert "markkinaoikeuden ratkaisua" in page.text_content("#count")
    page.click("#hk-list .hk-row >> nth=0")
    facts = page.text_content("#dr-facts")
    assert "Lopputulos" in facts and "165 §" in facts and "MAO:" in facts
    assert "KHO:een" in page.text_content("#dr-list") and "arvio" in page.text_content("#dr-list")
    page.keyboard.press("Escape")
    page.click("#hk-mao-tools [data-mao='vireilla']")
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


def test_team_folders(page, base_url):
    goto(page, base_url, "#tilannekuva")
    shared = page.evaluate("SHARED.map(f=>({id:f.id,name:f.name,n:f.items.length,ics:f.ics}))")
    assert len(shared) >= 1
    # selector lists them under their own group, Tilannekuva shows them as dashed chips
    assert page.locator("#folder-filter optgroup[label^='Tiimikansiot'] option").count() == len(shared)
    assert page.locator("#l-folders .chip.shared").count() == len(shared)
    assert "tiimi" in page.text_content("#h-folders")
    # choosing a team folder narrows every view to its items and shows the feed + edit links
    f = max(shared, key=lambda x: x["n"])
    page.click(f"#l-folders .chip.shared[data-fid='{f['id']}']")
    info = page.text_content("#l-folder-info")
    assert "tiimikansio" in info and "Outlook" in info and "Jaa Teamsiin" in info
    assert page.locator("#l-folder-info a[href$='" + f["ics"] + "']").count() == 2  # https and webcal
    assert page.evaluate("state.folderFilter") == f["id"]
    visible = page.evaluate("DATA.filter(baseVisible).length + TENDERS.filter(baseVisible).length + MERGERS.filter(baseVisible).length")
    assert 0 < visible <= f["n"]
    # the feed itself is served and is a calendar
    ics = page.request.get(base_url + "/" + f["ics"]).text()
    assert ics.startswith("BEGIN:VCALENDAR") and "X-WR-CALNAME:" in ics
    # manager: team section with feed + GitHub links; own folder gets share + calendar actions
    page.click("#open-folders")
    assert page.locator("#folder-rows .frow.shared").count() == len(shared)
    assert page.locator("#folder-rows .frow.shared a[href$='.ics']").count() == 3 * len(shared)  # Outlook, webcal, .ics
    assert page.locator("#folder-rows .frow.shared [data-fedit]").count() == len(shared)
    page.fill("#folder-new", "Oma kansio"); page.click("#folder-add")
    own = page.locator("#folder-rows .frow:not(.shared)").first
    assert "Jaa tiimikansioksi" in own.text_content() and own.locator("[data-fics]").count() == 1
    page.click("#folders-close")
    # drawer: team folders appear as in-page actions (handled by the key, see test_team_sharing_in_page)
    page.locator("#folder-filter").select_option("")
    page.click("#tab-fi"); page.click("#tl-fi .row[data-id] >> nth=0"); page.wait_for_selector("#drawer:not([hidden])")
    page.click("#dr-fdrop-btn")
    rows = page.locator("#dr-flist .fr.shared")
    assert rows.count() == len(shared) and rows.first.get_attribute("data-fteam") == "t:" + shared[0]["id"].replace("t:", "")
    page.keyboard.press("Escape")


def test_team_sharing_in_page(page, base_url):
    """Team-folder changes are filed from the page with the team key (GitHub API stubbed here) and reported back."""
    posted = []

    def gh(route, request):
        url = request.url
        if request.method == "POST" and url.endswith("/issues"):
            posted.append(json.loads(request.post_data))
            route.fulfill(status=201, content_type="application/json", body=json.dumps({"number": 99, "state": "open"}))
        elif url.endswith("/issues/99"):
            route.fulfill(status=201, content_type="application/json", body=json.dumps({"number": 99, "state": "closed", "comments": 1}))
        elif url.endswith("/issues/99/comments"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps([{"body": "Lisätty kansioon **X** (`x`): `y`"}]))
        elif request.method == "GET" and "/repos/" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"full_name": "EditMonster/Saadosseuranta"}),
                          headers={"github-authentication-token-expiration": "2027-06-01 10:00:00 UTC", "access-control-expose-headers": "github-authentication-token-expiration"})
        else:
            route.fulfill(status=404, body="{}")

    page.route("https://api.github.com/**", gh)
    goto(page, base_url, "#kansallinen")
    shared = page.evaluate("SHARED.map(f=>f.key)")
    # without a key, a team action opens the settings dialog instead of failing silently
    page.click("#tl-fi .row[data-id] >> nth=0"); page.wait_for_selector("#drawer:not([hidden])"); page.click("#dr-fdrop-btn")
    page.click("#dr-flist .fr.shared >> nth=0")
    assert page.locator("#share").is_visible() and "avain" in page.text_content("#share-msg")
    page.fill("#share-name", "Testi T."); page.fill("#share-key", "github_pat_TEST"); page.click("#share-test")
    page.wait_for_function("document.getElementById('share-msg').textContent.includes('toimii')")
    assert "2027" in page.text_content("#share-msg")
    page.click("#share-close")
    # with the key, the same click files the request and the row shows it as pending, then applied
    item = page.evaluate("drawer.dataset.id")
    page.click("#dr-flist .fr.shared >> nth=0")
    page.wait_for_function("document.getElementById('toast') && document.getElementById('toast').textContent.includes('#99')")
    assert posted[-1]["title"].startswith("[kansio] Lisää:") and f"- {item} " in posted[-1]["body"] and "ehdottaja: Testi T." in posted[-1]["body"]
    assert f"kansio: {shared[0]}" in posted[-1]["body"]
    page.wait_for_function("document.getElementById('toast').textContent.includes('Lisätty kansioon')", timeout=20000)
    assert page.evaluate(f"SHARED[0].items.includes('{item}')")
    page.keyboard.press("Escape"); page.keyboard.press("Escape")
    # manager: a new team folder with rules is composed in the page
    page.click("#open-folders"); page.click("#team-new")
    page.fill(".teamform [name=nimi]", "Verotiimi"); page.click(".teamform details summary")
    page.check(".teamform [name=aihealueet][value='Verotus']"); page.fill(".teamform [name=hakusanat]", "arvonlisävero, tulovero")
    page.click(".teamform [data-teamsubmit]")
    page.wait_for_function("document.getElementById('toast').textContent.includes('#99')")
    body = posted[-1]["body"]
    assert "toiminto: uusi" in body and "nimi: Verotiimi" in body
    rules = json.loads([l for l in body.split("\n") if l.startswith("saannot:")][0][len("saannot:"):])
    assert rules["aihealueet"] == ["Verotus"] and rules["hakusanat"] == ["arvonlisävero", "tulovero"] and rules["vain_avoimet"] is True
    # team folder rows offer the user's own channels: calendar subscriptions and Teams
    row = page.locator("#folder-rows .frow.shared").first
    for label in ("Outlook", "Google", "webcal", "Jaa Teamsiin", "Teams-ilmoitukset"):
        assert row.locator(f"a:has-text('{label}')").count() == 1, label
    assert "teams.microsoft.com/share" in row.locator("a:has-text('Jaa Teamsiin')").get_attribute("href")
    assert row.locator("a:has-text('Teams-ilmoitukset')").get_attribute("href").endswith(".xml")
    assert page.locator("#folder-rows .frow.shared [data-fedit]").count() == len(shared)
    page.click("#folders-close")
    # the key survives a reload; ?k= opens a team folder directly
    page.goto(base_url + "/?k=" + shared[0] + "#tilannekuva"); page.wait_for_function("typeof SHARED_LOADED !== 'undefined' && SHARED_LOADED === true")
    assert page.evaluate("state.folderFilter") == "t:" + shared[0] and page.evaluate("hasKey()")
    assert ("%3Fk%3D" + shared[0]) in page.evaluate("folderShareLinks(SHARED[0])")  # Teams share link carries ?k=<tunnus>, without the t: prefix


def test_eu_council_and_delegated(page, base_url):
    goto(page, base_url, "#eu")
    # delegated acts are a laji chip of their own and render with the objection-window span
    assert page.locator("#lajit .chip[data-laji='delegoitu']").count() == 1
    da = page.locator("#tl-eu .row[data-id^='eu-da-']")
    assert da.count() >= 10
    da.first.click(); page.wait_for_selector("#drawer:not([hidden])")
    kicker = page.text_content("#dr-kicker"); steps = page.text_content("#dr-list")
    assert "Delegoitu" in kicker and "Komissio antoi delegoidun säädöksen" in steps and "Vastustamisaika" in steps
    assert "Delegoitujen säädösten rekisteri" in page.text_content("#dr-src")
    page.keyboard.press("Escape")
    # turning the chip off removes them
    page.click("#lajit .chip[data-laji='delegoitu']")
    assert page.locator("#tl-eu .row[data-id^='eu-da-']").count() == 0
    page.click("#lajit .chip[data-laji='delegoitu']")
    # Council stages appear on ordinary procedures (general approach / adoption by Council)
    it = page.evaluate("(()=>{const i=DATA.find(i=>i.laji==='eu'&&i.events.some(e=>e.label.startsWith('Neuvoston yleisnäkemys'))&&i.events.some(e=>e.label.startsWith('Neuvosto hyväksyi'))); return {id:i.id,title:i.title};})()")
    page.fill("#q", it["title"][:30])
    page.click(f"#tl-eu .row[data-id='{it['id']}']"); page.wait_for_selector("#drawer:not([hidden])")
    steps = page.text_content("#dr-list")
    assert "Neuvoston yleisnäkemys" in steps and "Neuvosto hyväksyi" in steps
    page.keyboard.press("Escape"); page.fill("#q", "")


def test_mergers_tab(page, base_url):
    goto(page, base_url, "#yrityskaupat")
    assert page.locator("#yktopics").is_visible() and page.locator("#yk-tools").is_visible() and page.locator("#lajit").is_hidden()
    total = page.locator("#tl-yk .row[data-id]").count()
    assert total >= 5 and "yrityskauppaa" in page.text_content("#count")
    # KKV rows carry the statutory dates; the hearing shows as an open consultation
    page.click("#yk-tools [data-ykscope='fi']")
    kkv = page.locator("#tl-yk .row[data-id]").count()
    assert 0 < kkv < total
    page.click("#tl-yk .row[data-id] >> nth=0")
    page.wait_for_selector("#drawer:not([hidden])")
    kicker = page.text_content("#dr-kicker")
    assert "KKV" in kicker and "KKV/" in kicker
    vaiheet = page.text_content("#dr-list")
    assert "Ilmoitus saapunut" in vaiheet and "määräaika" in vaiheet
    assert "KKV: tapauksen sivu" in page.text_content("#dr-src")
    page.keyboard.press("Escape")
    # EU rows: provisional deadline from DG COMP
    page.click("#yk-tools [data-ykscope='eu']")
    page.click("#tl-yk .row[data-id] >> nth=0")
    assert "M." in page.text_content("#dr-kicker") and "Komission tapaussivu" in page.text_content("#dr-src")
    page.keyboard.press("Escape")
    # Finnish party filter: KKV rows stay, EU rows reduce to those with a Finnish party (FI-osapuoli badge, bold party)
    page.click("#yk-tools [data-ykscope='all']")
    page.check("#yk-fi")
    fi_rows = page.locator("#tl-yk .row[data-id]").count()
    assert kkv <= fi_rows < total
    assert page.locator("#tl-yk .row[data-id^='yk-eu-'] .pill.fi").count() == fi_rows - kkv
    assert page.locator("#tl-yk .row[data-id^='yk-eu-']:not(:has(.pill.fi))").count() == 0
    page.reload(); page.wait_for_function("typeof MERGERS_LOADED !== 'undefined' && MERGERS_LOADED === true")
    assert page.is_checked("#yk-fi") and page.locator("#tl-yk .row[data-id]").count() == fi_rows
    page.uncheck("#yk-fi")
    # an EU case with the OJ notice shows parties with countries and the observation window in the drawer
    page.click("#yk-tools [data-ykscope='eu']")
    row = page.locator("#tl-yk .row[data-id^='yk-eu-']:has(.parties)").first
    row.click(); page.wait_for_selector("#drawer:not([hidden])")
    facts = page.text_content("#dr-facts")
    assert "Osapuolet" in facts and "Kolmansien huomautukset" in facts and "EUVL:ssä" in facts
    assert "EUVL: ennakkoilmoitus" in page.text_content("#dr-src")
    page.keyboard.press("Escape")
    # decided cases appear when 'Vain vireillä' is off
    page.click("#yk-tools [data-ykscope='all']")
    page.uncheck("#yk-open")
    assert page.locator("#tl-yk .row[data-id]").count() > total
    page.check("#yk-open")
    # follow a case -> Tilannekuva KPI and Seurannassa list
    page.click("#tl-yk .row[data-id] >> nth=0")
    mid = page.evaluate("document.getElementById('drawer').dataset.id")
    page.click("#dr-follow"); page.keyboard.press("Escape")
    page.click("#tab-now")
    assert "Yrityskauppoja vireillä" in page.text_content("#kpis")
    assert page.locator(f"#l-follow li[data-id='{mid}']").count() == 1


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


def test_rulings_tab(page, base_url):
    goto(page, base_url, "#ratkaisut")
    assert page.locator("#rk-tools").is_visible() and page.locator("#lajit").is_hidden()
    assert int(page.text_content("#n-rk")) >= 60
    rows = page.locator("#rk-body tr.r")
    assert rows.count() >= 50 and "ratkaisua" in page.text_content("#count")
    courts = page.locator("#rk-courts [data-court]").all_text_contents()
    assert any(c.startswith("KKO") for c in courts) and any(c.startswith("EUT") for c in courts)
    # KKO's leaves to appeal are pending rulings too; the toggle hides them
    page.check("#rk-pending")
    page.wait_for_timeout(200)
    if page.evaluate("RULINGS.some(r=>r.kind==='Valituslupa myönnetty')"):
        assert rows.count() >= 10 and "Valituslupa myönnetty" in page.text_content("#rk-body")
    page.uncheck("#rk-vl")
    page.wait_for_timeout(200)
    # only pending Finnish references
    pend = rows.count()
    assert 1 <= pend <= 30 and "Valituslupa myönnetty" not in page.text_content("#rk-body")
    page.click("#rk-body tr.r >> nth=0")
    page.wait_for_selector("#drawer:not([hidden])")
    facts = page.text_content("#dr-facts")
    assert "Ennakkoratkaisupyynnön esittäjä" in facts and "vireillä" in page.text_content("#dr-kicker")
    assert "Jaa Teamsiin" in page.text_content("#dr-src")
    page.keyboard.press("Escape")
    page.uncheck("#rk-pending")
    # court filter narrows, statute links open the statute row
    page.click("#rk-courts [data-court='KKO']")
    page.wait_for_timeout(200)
    assert 0 < rows.count() < 60
    assert page.evaluate("[...state.rkCourts]") == ["KKO"]
    sid = page.evaluate("(RULINGS.find(r=>r.court==='KKO'&&(r.related||[]).length)||{}).id")
    if sid:
        page.evaluate(f"openItem('{sid}')")
        page.wait_for_selector("#drawer:not([hidden])")
        assert page.locator("#dr-mini a[data-id]").count() >= 1
        page.click("#dr-mini a[data-id] >> nth=0")
        page.wait_for_timeout(300)
        assert page.text_content("#dr-kicker").startswith("FI") or "FI" in page.text_content("#dr-kicker")
        page.keyboard.press("Escape")
    page.click("#rk-courts [data-court='*']")


def test_influence_drawer_and_signals(page, base_url):
    goto(page, base_url, "#kansallinen")
    assert page.locator("#tl-fi .infl-pill").count() >= 5
    iid = page.evaluate("(DATA.find(i=>i.influenceN&&i.influenceN.lausunnot&&i.influenceN.kuulemiset)||{}).id")
    assert iid
    page.evaluate(f"openItem('{iid}')")
    page.wait_for_selector("#drawer:not([hidden])")
    page.wait_for_function("document.querySelector('#dr-influence .grp')!==null")
    txt = page.text_content("#dr-influence")
    assert "Lausuntokierros:" in txt and "Valiokuntakuulemiset:" in txt
    assert page.locator("#dr-influence .orgs span").count() >= 3
    page.keyboard.press("Escape")
    # a planned week is shown as a forecast event and in the plan line
    pid = page.evaluate("(DATA.find(i=>i.plan&&i.events.some(e=>e.kind==='ennuste'))||{}).id")
    assert pid
    page.evaluate(f"openItem('{pid}')")
    page.wait_for_selector("#drawer:not([hidden])")
    assert "Lainsäädäntösuunnitelma" in page.text_content("#dr-src") and "arvio" in page.text_content("#dr-list")
    page.keyboard.press("Escape")
    goto(page, base_url, "#tilannekuva")
    assert page.locator("#l-act li").count() >= 1 and page.locator("#l-sig li").count() >= 1
    assert "Ladataan" not in page.text_content("#l-act")
    tags = page.evaluate("influenceWindows().map(w=>w.tag)")
    assert any(t in ("Lausuntokierros", "Kuuleminen", "Markkinakartoitus", "Valiokuntakuuleminen") for t in tags)
    page.click("#l-sig li >> nth=0")
    page.wait_for_selector("#drawer:not([hidden])")
    page.keyboard.press("Escape")


def test_tender_forward_stages_and_ted(page, base_url):
    goto(page, base_url, "#kilpailutukset")
    labels = page.locator("#hk-stages button").all_text_contents()
    assert any(l.startswith("Päätökset") for l in labels) and any(l.startswith("Ennusteet") for l in labels) and any(l.startswith("Kalenterit") for l in labels)
    page.click("#hk-stages [data-stage='ennuste']")
    page.wait_for_timeout(200)
    assert page.locator(".hk-row").count() >= 5 and "ennustetta" in page.text_content("#count")
    first = page.locator(".hk-row").first.inner_text()
    assert "sopimus päättyy" in first and "arvio" in first.lower()
    page.click(".hk-row >> nth=0")
    page.wait_for_selector("#drawer:not([hidden])")
    assert "Sopimuskausi päättyy" in page.text_content("#dr-list") and "arvio" in page.text_content("#dr-list")
    page.keyboard.press("Escape")
    page.click("#hk-stages [data-stage='kalenteri']")
    page.wait_for_timeout(200)
    assert page.locator(".hk-row").count() >= 20 and "suunniteltua" in page.text_content("#count")
    page.click("#hk-stages [data-stage='paatos']")
    page.wait_for_timeout(200)
    assert page.locator(".hk-row").count() >= 10
    assert "valitusaika päättyy" in page.locator(".hk-row").first.inner_text().lower()
    # TED: another country shows its own notices, Finland hides them
    opts = page.locator("#hk-country option").all_text_contents()
    assert len(opts) >= 2 and opts[0].startswith("Suomi")
    page.click("#hk-stages [data-stage='avoin']")
    page.select_option("#hk-country", "SE")
    page.wait_for_timeout(200)
    assert "Ruotsi (TED)" in page.text_content("#count") and page.locator(".hk-row").count() >= 10
    if page.locator("#hk-country option[value='BALT']").count():  # a region lists all its countries
        page.select_option("#hk-country", "BALT")
        page.wait_for_timeout(200)
        assert "Baltia (TED)" in page.text_content("#count")
        assert page.evaluate("TENDERS.filter(matchesTender).every(t=>['EE','LV','LT'].includes(t.country))")
        page.select_option("#hk-country", "SE")
        page.wait_for_timeout(200)
    assert "TED:ssä" in page.locator(".hk-row").first.inner_text()
    page.select_option("#hk-country", "FI")
    page.wait_for_timeout(200)
    assert page.evaluate("TENDERS.filter(matchesTender).every(t=>!t.country)")


def test_competition_enforcement_segment(page, base_url):
    goto(page, base_url, "#yrityskaupat")
    page.click("#yk-segment [data-yksegment='kilpailunrajoitus']")
    page.wait_for_timeout(200)
    assert "kilpailunrajoitusasiaa" in page.text_content("#count")
    n = page.locator("#tl-yk .row[data-id]").count()
    if n:
        page.click("#tl-yk .row[data-id] >> nth=0")
        page.wait_for_selector("#drawer:not([hidden])")
        assert "KKV" in page.text_content("#dr-kicker") and "Osapuolet" in page.text_content("#dr-facts")
        page.keyboard.press("Escape")
    page.click("#yk-segment [data-yksegment='yrityskauppa']")
    page.wait_for_timeout(200)
    assert "yrityskauppaa" in page.text_content("#count")


def test_action_drafts(page, base_url):
    goto(page, base_url, "#kansallinen")
    iid = page.evaluate("(DATA.find(i=>i.scope==='fi'&&i.laji==='laki'&&openConsultation(i))||{}).id")
    assert iid
    page.evaluate(f"openItem('{iid}')")
    page.wait_for_selector("#drawer:not([hidden])")
    labels = page.locator("#dr-actions [data-act]").all_text_contents()
    assert "Lausuntoluonnos" in labels and any("Tiivistelmä" in l for l in labels)
    page.click("#dr-actions [data-act='lausunto']")
    page.wait_for_selector("#act:not([hidden])")
    body = page.input_value("#act-body")
    assert "LAUSUNTO LUONNOKSESTA" in body and "Yksityiskohtaiset huomiot" in body and iid in body
    assert page.get_attribute("#act-mail", "href").startswith("mailto:") and "teams.microsoft.com/share" in page.get_attribute("#act-teams", "href")
    page.fill("#act-subject", "Testi")
    assert "subject=Testi" in page.get_attribute("#act-mail", "href")
    page.click("#act-close")
    assert page.locator("#act").is_hidden()
    page.keyboard.press("Escape")
    # procurement decision → document request and appeal skeleton with the statutory references
    pid = page.evaluate("(TENDERS.find(t=>t.stage==='paatos'&&t.status==='valitusaika')||{}).id")
    if pid:
        page.evaluate(f"openItem('{pid}')")
        page.wait_for_selector("#drawer:not([hidden])")
        page.click("#dr-actions [data-act='asiakirjapyynto']")
        page.wait_for_selector("#act:not([hidden])")
        assert "621/1999" in page.input_value("#act-body") and "14 § 4 mom." in page.input_value("#act-body")
        page.click("#act-close")
        page.click("#dr-actions [data-act='oikaisu']")
        page.wait_for_selector("#act:not([hidden])")
        assert "146–148 §" in page.input_value("#act-body")
        page.click("#act-close")
        page.keyboard.press("Escape")
    mid = page.evaluate("(MERGERS.find(m=>m.authority==='EU'&&openConsultation(m))||{}).id")
    if mid:
        page.evaluate(f"openItem('{mid}')")
        page.wait_for_selector("#drawer:not([hidden])")
        page.click("#dr-actions [data-act='huomautus']")
        page.wait_for_selector("#act:not([hidden])")
        assert page.input_value("#act-to") == "COMP-MERGER-REGISTRY@ec.europa.eu"
        page.click("#act-close")
        page.keyboard.press("Escape")


def test_language_switch(page, base_url):
    goto(page, base_url, "")
    page.click("#lang-en")
    page.wait_for_timeout(300)
    assert page.evaluate("document.documentElement.lang") == "en"
    assert page.text_content("#tab-now").strip() == "Overview" and page.text_content("#tab-hk").strip().startswith("Tenders")
    assert page.locator("#lang-note").is_visible()
    # new content rendered in English mode is translated as it appears
    page.click("#tab-fi")
    page.wait_for_timeout(300)
    assert "National legislation" in page.text_content("#view-fi")
    # EU items use the EU's English title
    eu = page.evaluate("(DATA.find(i=>i.scope==='eu'&&i.titleEn&&i._o)||{}).id")
    if page.evaluate("DATA.some(i=>i.titleEn)"):  # data built after titleEn was added
        assert eu
    page.click("#lang-fi")
    page.wait_for_timeout(300)
    assert page.evaluate("document.documentElement.lang") == "fi"
    assert page.text_content("#tab-now").strip() == "Tilannekuva" and "Kansallinen lainsäädäntö" in page.text_content("#view-fi")
    if eu:  # back in Finnish: the Finnish title again (an English EU summary may stay machine-translated into Finnish)
        assert page.evaluate(f"(()=>{{const i=DATA.find(x=>x.id==='{eu}'); return !i._o || i.title===i._o.title}})()")
    page.evaluate("localStorage.removeItem('saadosseuranta-lang')")


def test_swedish_switch(page, base_url):
    goto(page, base_url, "")
    fi_titles = page.evaluate("Object.fromEntries(DATA.filter(i=>i.titleSv).map(i=>[i.id,i.title]))")
    page.click("#lang-sv")
    page.wait_for_timeout(300)
    assert page.evaluate("document.documentElement.lang") == "sv"
    assert page.text_content("#tab-now").strip() == "Lägesbild" and page.text_content("#tab-hk").strip().startswith("Upphandlingar")
    assert page.locator("#lang-note-sv").is_visible() and not page.locator("#lang-note").is_visible()
    page.click("#tab-fi")
    page.wait_for_timeout(300)
    assert "Nationell lagstiftning" in page.text_content("#view-fi")
    # bills use their official Swedish titles from Projektfönstret
    sv = page.evaluate("(DATA.find(i=>i.titleSv&&i._o)||{}).id")
    if page.evaluate("DATA.some(i=>i.titleSv)"):
        assert sv
    # straight to English: Swedish titles are restored before the English pass
    page.click("#lang-en")
    page.wait_for_timeout(300)
    assert page.text_content("#tab-now").strip() == "Overview" and page.locator("#lang-note").is_visible()
    assert not page.locator("#lang-note-sv").is_visible()
    if sv and not page.evaluate(f"(()=>{{const it=DATA.find(i=>i.id==='{sv}'); return it.titleEn||it._o}})()"):
        assert page.evaluate(f"DATA.find(i=>i.id==='{sv}').title") == fi_titles[sv]
    page.click("#lang-fi")
    page.wait_for_timeout(300)
    assert page.text_content("#tab-now").strip() == "Tilannekuva" and "Kansallinen lainsäädäntö" in page.text_content("#view-fi")
    page.evaluate("localStorage.removeItem('saadosseuranta-lang')")



# ---------- lataukset: lakianalyysi ja johtoryhmäraportti (Word ja PowerPoint) ----------
def test_law_analysis_and_report_downloads(page, base_url, tmp_path):
    import zipfile
    goto(page, base_url, "")
    # the heavy libraries stay out of the initial page load
    assert page.evaluate("typeof window.docx === 'undefined' && typeof window.PptxGenJS === 'undefined' && !window.Raportit")
    iid = page.evaluate("(DATA.find(i=>i.scope==='fi'&&i.laji==='laki'&&i.lausunnotN&&i.events.length>3)||DATA.find(i=>i.scope==='fi')).id")
    page.evaluate(f"openItem('{iid}')")
    page.wait_for_selector("#drawer:not([hidden]) [data-export=docx]")
    title = page.evaluate(f"DATA.find(i=>i.id==='{iid}').fullTitle||DATA.find(i=>i.id==='{iid}').title").split()[0]
    for kind, inner in (("docx", "word/document.xml"), ("pptx", "ppt/slides/slide1.xml")):
        with page.expect_download(timeout=30000) as d:
            page.click(f"#drawer [data-export={kind}]")
        f = tmp_path / f"law.{kind}"
        d.value.save_as(f)
        assert d.value.suggested_filename.endswith("." + kind)
        with zipfile.ZipFile(f) as z:
            assert inner in z.namelist()
            body = z.read(inner).decode("utf-8")
            assert title in body
    page.click("#dr-close")
    page.click("#open-report")
    assert page.locator("#rep").is_visible()
    opts = page.eval_on_selector_all("#rep-scope option", "os=>os.map(o=>o.value)")
    assert opts[:3] == ["all", "filters", "follow"]
    for kind, inner in (("docx", "word/document.xml"), ("pptx", "ppt/slides/slide2.xml")):
        with page.expect_download(timeout=30000) as d:
            page.click(f"#rep-{kind}")
        f = tmp_path / f"rep.{kind}"
        d.value.save_as(f)
        with zipfile.ZipFile(f) as z:
            assert inner in z.namelist()
    page.keyboard.press("Escape")
    assert page.locator("#rep").is_hidden()


def test_estonian_lithuanian_and_original_texts(page, base_url):
    et = json.loads((ROOT / "config" / "i18n" / "et.json").read_text(encoding="utf-8"))
    lt = json.loads((ROOT / "config" / "i18n" / "lt.json").read_text(encoding="utf-8"))
    goto(page, base_url, "")
    page.click("#lang-et")
    page.wait_for_timeout(800)
    assert page.evaluate("document.documentElement.lang") == "et"
    assert page.text_content("#tab-now").strip() == et["Tilannekuva"]
    assert page.locator("#lang-note-et").is_visible()
    # content in Estonian once the translation file is there: the card says how it was translated and keeps the original
    iid = page.evaluate("(DATA.find(i=>i._o&&(i.scope==='fi'||i.scope==='eu'))||{}).id")
    if iid:
        page.evaluate(f"openItem('{iid}')")
        page.wait_for_selector("#dr-orig .mtnote")
        assert any(w in page.text_content("#dr-orig") for w in ("Masintõlge", "Ametlik tõlge"))
        page.click("#dr-close")
        page.click("#orig-toggle")
        page.wait_for_timeout(300)
        assert page.evaluate("DATA.filter(i=>i._o).length") == 0 and page.get_attribute("#orig-toggle", "aria-pressed") == "true"
        assert not page.locator("#lang-note-et").is_visible()
        page.click("#orig-toggle")
        page.wait_for_timeout(300)
        assert page.evaluate("DATA.some(i=>i._o)")
    page.click("#lang-lt")
    page.wait_for_timeout(500)
    assert page.text_content("#tab-now").strip() == lt["Tilannekuva"] and page.locator("#lang-note-lt").is_visible()
    page.click("#lang-fi")
    page.wait_for_timeout(300)
    assert page.text_content("#tab-now").strip() == "Tilannekuva"
    page.evaluate("localStorage.removeItem('saadosseuranta-lang');localStorage.removeItem('saadosseuranta-orig')")


def test_obligations_calendar_and_stakeholder_profiles(page, base_url):
    goto(page, base_url, "")
    # Velvoitekalenteri on the overview, and the statute's own section in its card
    assert page.locator("#l-siirt").count() == 1
    iid = page.evaluate("(DATA.find(i=>(i.siirtymat||[]).some(r=>r.d))||{}).id")
    if iid:
        assert page.evaluate("document.querySelectorAll('#l-siirt li[data-id]').length") >= 0
        page.evaluate(f"openItem('{iid}')")
        page.wait_for_selector("#dr-siirtyma .siirt li")
        assert "Siirtymäsäännökset" in page.text_content("#dr-siirtyma")
        page.click("#dr-close")
    # stakeholder profile: search, open, filter, open a bill from the list (the file exists after the first data build)
    if not (ROOT / "docs" / "data" / "sidosryhmat.json").exists():
        return
    page.fill("#org-q2", "kunta")
    page.wait_for_selector("#org:not([hidden])")
    page.wait_for_function("window.ORGS!==null||true")
    page.wait_for_timeout(800)
    if page.evaluate("ORGS && Object.keys(ORGS.orgs).length > 0"):
        page.wait_for_selector("#org-sugg button")
        page.keyboard.press("Enter")
        page.wait_for_selector("#org-body .org-bar")
        assert page.text_content("#org-title").strip() != "Sidosryhmät"
        page.click("[data-orgf=O]")
        rows = page.locator(".org-pos li[data-id]")
        if rows.count():
            rows.first.click()
            page.wait_for_selector("#drawer:not([hidden])")
            assert page.locator("#org").is_hidden()


def test_drawer_can_be_widened_by_dragging(page, base_url):
    goto(page, base_url, "")
    page.set_viewport_size({"width": 1440, "height": 900})
    page.evaluate("openItem(DATA[0].id)")
    page.wait_for_selector("#dr-resize:not([hidden])")
    w0 = page.evaluate("document.getElementById('drawer').getBoundingClientRect().width")
    hb = page.locator("#dr-resize").bounding_box()
    page.mouse.move(hb["x"] + 7, hb["y"] + hb["height"] / 2)
    page.mouse.down()
    page.mouse.move(hb["x"] - 300, hb["y"] + hb["height"] / 2, steps=6)
    page.mouse.up()
    w1 = page.evaluate("document.getElementById('drawer').getBoundingClientRect().width")
    assert w1 > w0 + 250
    page.dblclick("#dr-resize")
    assert abs(page.evaluate("document.getElementById('drawer').getBoundingClientRect().width") - w0) < 2
    page.click("#dr-close")
    page.wait_for_function("document.getElementById('dr-resize').hidden")


def test_search_placeholder_is_never_cut(page, base_url):
    for width, tab in ((1440, "kilpailutukset"), (390, "kilpailutukset"), (1440, "kansallinen")):
        page.set_viewport_size({"width": width, "height": 860})
        goto(page, base_url, "#" + tab)
        page.wait_for_timeout(300)
        ok = page.evaluate("""()=>{const q=document.getElementById('q'); if(!q.offsetParent) return true; const cs=getComputedStyle(q);
          const c=document.createElement('canvas').getContext('2d'); c.font=`${cs.fontWeight} ${q.style.getPropertyValue('--phfs')||cs.fontSize} ${cs.fontFamily}`;
          return c.measureText(q.placeholder).width <= q.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);}""")
        assert ok, (width, tab)


def test_new_logo_and_global_search_placeholder(page, base_url):
    for width in (1440, 1300, 1000, 800):
        page.set_viewport_size({"width": width, "height": 860})
        goto(page, base_url, "")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(1500)
        r = page.evaluate("""()=>{const q=document.getElementById('gq'); const cs=getComputedStyle(q);
          const c=document.createElement('canvas').getContext('2d'); c.font=`${cs.fontWeight} ${q.style.getPropertyValue('--phfs')||cs.fontSize} ${cs.fontFamily}`;
          const lg=document.querySelector('#gbar .glogo img').getBoundingClientRect(), ctl=document.querySelector('#gbar .ctl').getBoundingClientRect();
          const tw=c.measureText(q.placeholder).width, inner=q.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);
          return {fits: tw <= inner, ph: q.placeholder, fs: q.style.getPropertyValue('--phfs')||cs.fontSize, tw: Math.round(tw), inner: Math.round(inner), font: c.font,
                  square: Math.abs(lg.width-lg.height)<1, inside: ctl.right<=innerWidth+1};}""")
        assert r["fits"] and r["square"] and r["inside"], (width, r)
    assert page.evaluate("[...document.querySelectorAll('link[rel~=icon]')].some(l=>l.href.endsWith('logo.svg'))")


def test_stakeholders_tab(page, base_url):
    if not (ROOT / "docs" / "data" / "sidosryhmat.json").exists():
        return
    goto(page, base_url, "#lausunnonantajat")
    page.wait_for_selector("#lg-body tr td .orglink")
    assert page.locator("#lg-body tr").count() > 10
    page.select_option("#lg-sort", "o")
    if page.evaluate("Object.values(ORGS.orgs).some(o=>o.ty==='kunta')"):  # data built with types
        page.select_option("#lg-type", "kunta")
        page.wait_for_selector("#lg-body tr td .orglink")
    page.fill("#q", "kaupunki")
    page.wait_for_timeout(200)
    names = page.eval_on_selector_all("#lg-body .orglink", "els=>els.map(e=>e.textContent.toLowerCase())")
    assert names and all("kaupunki" in n for n in names)
    page.locator("#lg-body .orglink").first.click()
    page.wait_for_selector("#org-body .lg-rec")
    assert "Miten asiat menivät" in page.text_content("#org-body")
    pv = page.locator("#org-body .lg-pv")
    if pv.count():
        pv.first.click()
        page.wait_for_selector(".lg-quote")
