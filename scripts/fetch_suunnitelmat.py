"""Forward-looking procurement plans: what buyers say they will tender, before any notice exists.

Two kinds of source, one cache (data/cache/suunnitelmat.json):

1. Hilma "kilpailutussuunnitelmat" – buyers (Kela, Yle, Helsinki, hospital districts, Istekki…)
   publish their plans in Hilma itself. The same search index fetch_hankinnat.py uses lists them with
   ``$filter=isPlan eq true``; ``expirationDate`` is the planned publication date of the notice. The
   public detail document ``GET /web/api/public/procurementplan/{planId}`` adds per lot the planned
   notice date, the estimated contract start/end, CPV, value and description. Details are fetched only
   for plan ids not yet in the cache; plans that expired more than 30 days ago are dropped.
2. Buyer calendars configured in config/kalenterit.yaml – one parser per page type (``PARSERS``):
   Hansel htmx fragments, HUS monthly xlsx, Espoo and Senaatti HTML tables, Tampere JSON, Tuomi and
   LUVN accordions. Every parser returns rows ``{buyer, title, plannedText, plannedDate, contractStart?,
   contractEnd?, phase?, cpv?, value?, category?, url}`` where ``plannedDate`` is an ISO estimate of the
   free-text timing: quarter → first day of the quarter's second month, month → the 15th, kevät 15.4.,
   kesä 15.7., syksy 15.10., talvi 15.1. When a calendar gives only the contract start, the notice is
   estimated a few months before it (documented per parser). A failing calendar keeps its previous rows
   and is recorded under ``health``; the run fails only if the Hilma plans AND every calendar fail.
"""
from __future__ import annotations

import datetime as dt
import html as htmllib
import io
import re
import time
from zoneinfo import ZoneInfo

from common import CACHE_DIR, CONFIG_DIR, TODAY, http, load_json, load_yaml, log, save_json
from fetch_hankinnat import fetch_filter
from fetch_sopimuskaudet import add_months, g, iso_date

PLAN_DETAIL = "https://www.hankintailmoitukset.fi/web/api/public/procurementplan/{pid}"
PLAN_PAGE = "https://www.hankintailmoitukset.fi/fi/public/plan/{pid}"
OUT = CACHE_DIR / "suunnitelmat.json"
HELSINKI = ZoneInfo("Europe/Helsinki")
PLAN_GRACE_DAYS = 30
MIN_PLANS = 20
DESC_MAX = 600
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_DMY = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
QUARTER_MONTH = {1: 2, 2: 5, 3: 8, 4: 11}
SEASONS = [("kevä", "04-15"), ("kesä", "07-15"), ("syks", "10-15"), ("talv", "01-15"), ("alkuvuo", "02-15"), ("loppuvuo", "11-15")]
FI_MONTHS = ["tammi", "helmi", "maalis", "huhti", "touko", "kesä", "heinä", "elo", "syys", "loka", "marras", "joulu"]


# ---------- text helpers ----------

def strip_tags(s: str) -> str:
    return _WS.sub(" ", htmllib.unescape(_TAG.sub(" ", s or "")).replace("\xa0", " ").replace("​", "")).strip()


def fi_date(value) -> str | None:
    """Hilma plan timestamps are UTC midnight-in-Finland ('2026-12-03T22:00:00+00:00' = 4.12.2026)."""
    s = str(value or "")
    if "T" in s and (s.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", s)):
        try:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(HELSINKI).date().isoformat()
        except ValueError:
            return None
    return iso_date(s)


def planned_date(text: str | None) -> str | None:
    """ISO estimate for a free-text timing: '2027/Q2', '2026Q4', 'Q1-Q2/2027' (first quarter), 'lokakuu 2026',
    '11/2026', 'syksy 2026', '15.11.2026', '2027-01-01'. None when nothing recognisable (a bare year is too vague)."""
    t = (text or "").strip().lower().replace("\xa0", " ")
    if not t:
        return None
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return _safe(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _DMY.search(t)
    if m:
        return _safe(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.search(r"\bq\s*([1-4])(?:\s*[-–/]\s*q?\s*[1-4])?\s*/?\s*(\d{4})\b", t) or re.search(r"\b(\d{4})\s*/?\s*q\s*([1-4])\b", t)
    if m:
        q, y = (m.group(1), m.group(2)) if len(m.group(1)) == 1 else (m.group(2), m.group(1))
        return _safe(int(y), QUARTER_MONTH[int(q)], 1)
    for i, stem in enumerate(FI_MONTHS):
        if re.search(rf"\b{stem}kuu\w*\s*(\d{{4}})", t):
            return _safe(int(re.search(rf"\b{stem}kuu\w*\s*(\d{{4}})", t).group(1)), i + 1, 15)
    m = re.search(r"\b(\d{1,2})\s*/\s*(\d{4})\b", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return _safe(int(m.group(2)), int(m.group(1)), 15)
    for stem, md in SEASONS:
        m = re.search(rf"\b{stem}\w*\s*(\d{{4}})", t) or re.search(rf"\b(\d{{4}})\s*{stem}", t)
        if m:
            return f"{m.group(1)}-{md}"
    return None


def _safe(y: int, m: int, d: int) -> str | None:
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


def before(iso: str | None, months: int) -> str | None:
    """An estimate `months` months before an ISO date (notice before contract start)."""
    if not iso:
        return None
    try:
        return add_months(dt.date.fromisoformat(iso), -months).isoformat()
    except ValueError:
        return None


def _row(**kw) -> dict:
    return {k: v for k, v in kw.items() if v not in (None, "", [], False)}


# ---------- calendar parsers (pure: text in, rows out) ----------

def parse_hansel(html: str, url: str, buyer: str = "Hansel Oy") -> tuple[list[dict], int | None]:
    """Hansel joint-procurement cards: title '(00769)', type badge, 'Voimassaoloaika: dd.mm.yyyy - dd.mm.yyyy',
    'Vaihe: Esiselvityksessä|Valmistelussa|Kilpailutuksessa|Käynnissä'. The notice is estimated 9 months before
    the validity start when in pre-study, 6 months when in preparation, 4 months when already tendering; for a
    running agreement the successor's notice is estimated 9 months before the validity end. Returns (rows,
    next page number or None)."""
    rows = []
    for card in re.findall(r'<li class="card-link.*?</li>', html, re.S):
        href = re.search(r'href="([^"]+)"', card)
        title_m = re.search(r'aria-hidden="true"></span>\s*(.*?)\s*</div>', card, re.S)
        title = strip_tags(title_m.group(1)) if title_m else ""
        if not title:
            continue
        badge = re.search(r'rounded-full px-2 py-1 text-xs font-medium">\s*(.*?)\s*</span>', card, re.S)
        validity = re.search(r"Voimassaoloaika:</span>\s*([^<]+)", card)
        phase = re.search(r"Vaihe:</span>\s*([^<]+)", card)
        join = re.search(r'<div class="text-sm">\s*(Liity viimeistään:[^<]+|Liittyminen[^<]+)</div>', card)
        dates = _DMY.findall(validity.group(1)) if validity else []
        start = _safe(int(dates[0][2]), int(dates[0][1]), int(dates[0][0])) if dates else None
        end = _safe(int(dates[1][2]), int(dates[1][1]), int(dates[1][0])) if len(dates) > 1 else None
        ph = strip_tags(phase.group(1)) if phase else ""
        lead = {"Esiselvityksessä": 9, "Valmistelussa": 6, "Kilpailutuksessa": 4}.get(ph)
        if lead is not None:
            planned = before(start, lead)
            text = f"{ph.lower()}, voimassaolo alkaa {_dmy(start)}" if start else ph.lower()
        elif ph.startswith("Käynnissä") and end:
            planned = before(end, 9)
            text = f"käynnissä {_dmy(start)}–{_dmy(end)}, seuraava kilpailutus arviolta {_dmy(planned)}"
        else:
            planned, text = None, ph.lower()
        number = re.search(r"\((\d{5})\)\s*$", title)
        rows.append(_row(buyer=buyer, title=title[:220], plannedText=text, plannedDate=planned, contractStart=start, contractEnd=end,
                         phase=ph or None, category=strip_tags(badge.group(1)) if badge else None, agreement=number.group(1) if number else None,
                         note=strip_tags(join.group(1)) if join else None,
                         url=("https://www.hansel.fi" + href.group(1)) if href and href.group(1).startswith("/") else url))
    nxt = re.search(r'name="page"\s+value="(\d+)"', html)
    return rows, (int(nxt.group(1)) if nxt else None)


def _dmy(iso: str | None) -> str:
    if not iso:
        return "?"
    y, m, d = iso.split("-")
    return f"{int(d)}.{int(m)}.{y}"


def _cells(row_html: str) -> list[str]:
    return [strip_tags(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S | re.I)]


def parse_espoo(html: str, url: str, buyer: str = "Espoon kaupunki") -> list[dict]:
    """Espoo's single table: name | estimated notice quarter (2026Q4) | estimated contract start (2027Q1) | info.
    Rows with only a contract start get the notice estimated 4 months before it."""
    table = re.search(r"<table.*?</table>", html, re.S | re.I)
    if not table:
        raise ValueError("Espoon kalenterista ei löytynyt taulukkoa")
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(0), re.S | re.I):
        cells = _cells(tr)
        if not cells or re.search(r"<th", tr, re.I) or "päivitetty" in cells[0].lower():
            continue
        title = cells[0]
        if not title or len(title) < 4:
            continue
        colspan = re.search(r'<td[^>]*colspan="?2', tr, re.I)
        planned_txt = "" if colspan else (cells[1] if len(cells) > 1 else "")
        start_txt = (cells[1] if colspan else (cells[2] if len(cells) > 2 else "")) or ""
        planned = planned_date(planned_txt)
        start = planned_date(start_txt)
        if not planned and start:
            planned = before(start, 4)
            text = f"sopimus alkaa {start_txt.strip()}"
        else:
            text = planned_txt.strip()
        if not planned:
            continue
        rows.append(_row(buyer=buyer, title=title[:220], plannedText=text, plannedDate=planned, contractStart=start,
                         note=(cells[3] if len(cells) > 3 and "@" not in cells[3] else None), url=url))
    return rows


def parse_senaatti(html: str, url: str, buyer: str = "Senaatti-kiinteistöt") -> list[dict]:
    """Senaatti's table.tender-calendar: title | category | planned publication (2027/Q2) | EU/Kansallinen | contact | info."""
    table = re.search(r'<table class="tender-calendar.*?</table>', html, re.S | re.I)
    if not table:
        raise ValueError("Senaatin kilpailutuskalenterista ei löytynyt taulukkoa")
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(0), re.S | re.I):
        cells = _cells(tr)
        if len(cells) < 3 or re.search(r"<th", tr, re.I) or not cells[0]:
            continue
        planned = planned_date(cells[2])
        if not planned:
            continue
        rows.append(_row(buyer=buyer, title=cells[0][:220], plannedText=cells[2], plannedDate=planned, category=cells[1] or None,
                         eu=(cells[3].strip().upper() == "EU") if len(cells) > 3 else None,
                         note=(cells[5] if len(cells) > 5 and cells[5] else None), url=url))
    return rows


def parse_tampere(data, url: str, buyer: str = "Tampereen kaupunki") -> list[dict]:
    """Tampere's ProcurementCalendar/getall JSON: Title, EstimatedSchedule ('Q4/2026'), ProcurementType, MainCpvCode
    ('Pankkipalvelut (66110000-4)')."""
    if not isinstance(data, list):
        raise ValueError("Tampereen hankintakalenteri ei ole lista")
    rows = []
    for it in data:
        title = (it.get("Title") or "").strip()
        planned = planned_date(it.get("EstimatedSchedule"))
        if not title or not planned:
            continue
        cpv = re.search(r"\((\d{8})(?:-\d)?\)", it.get("MainCpvCode") or "")
        rows.append(_row(buyer=buyer, title=title[:220], plannedText=(it.get("EstimatedSchedule") or "").strip(), plannedDate=planned,
                         cpv=cpv.group(1) if cpv else None, category=it.get("ProcurementType") or None, url=url))
    return rows


def parse_tuomi(html: str, url: str, buyer: str = "Tuomi Logistiikka Oy") -> list[dict]:
    """Tuomi's accordion (button.single-offer): span.offer-title, p.desc, 'Tarjouspyynnön arvioitu julkaisuajankohta:
    2027/Q1', 'Sopimuskauden arvioitu alkamisajankohta: 2027-01-01'. Open DPS entries without a timing are skipped."""
    rows = []
    for block in re.findall(r'<button class="single-accordion[^"]*single-offer".*?</button>', html, re.S):
        title_m = re.search(r'class="text-title offer-title">(.*?)</span>', block, re.S)
        title = strip_tags(title_m.group(1)) if title_m else ""
        if not title:
            continue
        desc_m = re.search(r'<p class="desc">(.*?)</p>', block, re.S)
        planned_m = re.search(r"Tarjouspyynnön arvioitu julkaisuajankohta:\s*</strong>\s*([^<]*)", block)
        start_m = re.search(r"Sopimuskauden arvioitu alkamisajankohta:\s*</strong>\s*([^<]*)", block)
        planned_txt = (planned_m.group(1) if planned_m else "").strip()
        start = planned_date(start_m.group(1) if start_m else "")
        planned = planned_date(planned_txt)
        text = planned_txt
        if not planned and start:
            planned = before(start, 4)
            text = f"sopimus alkaa {_dmy(start)}"
        if not planned:
            continue
        rows.append(_row(buyer=buyer, title=title[:220], plannedText=text, plannedDate=planned, contractStart=start,
                         summary=strip_tags(desc_m.group(1))[:300] if desc_m else None, url=url))
    return rows


def parse_luvn(html: str, url: str, buyer: str = "Länsi-Uudenmaan hyvinvointialue") -> list[dict]:
    """LUVN's category accordion: '<strong>Title</strong>' followed by 'Suunniteltu markkinavuoropuhelu: Q4/2025'
    and 'Suunniteltu julkaisu: Q4/2026' (ranges 'Q1-Q2/2027' → first quarter). 'Jatkuva ilmoittautuminen' = open
    register, skipped. Only the rendered HTML is read (the page repeats everything in __NEXT_DATA__)."""
    body = html.split('<script id="__NEXT_DATA__"', 1)[0]
    rows = []
    for sec in re.finditer(r'<button aria-controls="section-(\d+)"[^>]*><span>(.*?)</span>.*?<div[^>]*id="section-\1"[^>]*>(.*?)</div></div></div>', body, re.S):
        category = strip_tags(sec.group(2))
        parts = re.split(r"<strong>", sec.group(3))
        for part in parts[1:]:
            title = strip_tags(part.split("</strong>", 1)[0])
            rest = strip_tags(part.split("</strong>", 1)[1]) if "</strong>" in part else ""
            if not title:
                continue
            pub = re.search(r"Suunniteltu julkaisu:?\s*([^S]*?)(?:\s*Suunniteltu|$)", rest)
            dialog = re.search(r"Suunniteltu markkinavuoropuhelu:?\s*([^S]*?)(?:\s*Suunniteltu|$)", rest)
            planned_txt = (pub.group(1) if pub else "").strip(" .,")
            planned = planned_date(planned_txt)
            if not planned:
                continue
            rows.append(_row(buyer=buyer, title=title[:220], plannedText=planned_txt, plannedDate=planned, category=category or None,
                             dialogueText=(dialog.group(1).strip(" .,") if dialog else None), dialogueDate=planned_date(dialog.group(1)) if dialog else None,
                             url=url))
    return rows


def hus_rows(sheets: dict[str, list[tuple]], url: str, buyer: str = "HUS-yhtymä") -> list[dict]:
    """HUS's monthly workbook as {sheet title: rows}: header on the row that starts with 'TP-numero'; columns are
    located by header text ('Hankinnan kohde', 'Tarjouspyyntö julkaistu (toteuma)', 'Sopimuskausi alkaa (suunnitelma)',
    'Valmistelu aloitettu', 'Hankintakategoria'). A published notice date is used as is; otherwise the notice is
    estimated 4 months before the planned contract start (spec ready), 5 (preparation under way) or 6 (not started)."""
    rows = []
    for sheet, data in sheets.items():
        phase = re.sub(r"\s*\d{2}_\d{4}\s*$", "", sheet).strip()
        lead = 4 if phase.lower().startswith("speksaus") else (5 if phase.lower().startswith("valmistelu") else 6)
        header_i = next((i for i, r in enumerate(data) if r and str(r[0] or "").lower().startswith("tp-numero")), None)
        if header_i is None:
            continue
        heads = [str(h or "").lower() for h in data[header_i]]

        def col(*keys):
            return next((i for i, h in enumerate(heads) if all(k in h for k in keys)), None)
        c_no, c_title, c_pub = col("tp-numero"), col("hankinnan kohde"), col("tarjouspyyntö julkaistu")
        c_start, c_prep, c_cat = col("sopimuskausi alkaa"), col("valmistelu aloitet"), col("hankintakategoria")
        if c_title is None:
            continue
        for r in data[header_i + 1:]:
            if not r or c_title >= len(r) or not r[c_title]:
                continue
            title = str(r[c_title]).strip()
            start = _xl_date(r[c_start]) if c_start is not None and c_start < len(r) else None
            pub = _xl_date(r[c_pub]) if c_pub is not None and c_pub < len(r) else None
            prep = _xl_date(r[c_prep]) if c_prep is not None and c_prep < len(r) else None
            if pub:
                planned, text, ph = pub, f"tarjouspyyntö julkaistu {_dmy(pub)}", "tarjouspyyntö julkaistu"
            elif start:
                planned, text, ph = before(start, lead), f"sopimuskausi alkaa {_dmy(start)}", phase
            else:
                continue
            rows.append(_row(buyer=buyer, title=title[:220], plannedText=text, plannedDate=planned, contractStart=start, phase=ph,
                             preparationStart=prep, reference=str(r[c_no]).strip() if c_no is not None and c_no < len(r) and r[c_no] else None,
                             category=str(r[c_cat]).strip() if c_cat is not None and c_cat < len(r) and r[c_cat] else None, url=url))
    return rows


def _xl_date(v) -> str | None:
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    return planned_date(str(v)) if v else None


# ---------- fetchers per source type ----------

def fetch_hansel(src: dict) -> list[dict]:
    rows = []
    for base in src.get("urls") or [src.get("url")]:
        page = 1
        while page and page <= 25:
            r = http("GET", f"{base}&page={page}", headers={"HX-Request": "true", "Accept": "text/html"}, timeout=60)
            r.raise_for_status()
            got, nxt = parse_hansel(r.text, src.get("sivu") or base, src["nimi"])
            rows.extend(got)
            page = nxt if (nxt and got) else None
            time.sleep(1)
    return rows


def fetch_hus(src: dict) -> list[dict]:
    try:
        import openpyxl  # optional dependency: only this calendar needs it
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("openpyxl puuttuu (pip install openpyxl)") from e
    r = http("GET", src["url"], timeout=60)
    r.raise_for_status()
    links = re.findall(r'href="([^"]*tulevat-ja-valmistelussa[^"]*\.xlsx)"', r.text)
    if not links:
        raise ValueError("HUS:n sivulta ei löytynyt kilpailutuslistan xlsx-linkkiä")
    href = links[0] if links[0].startswith("http") else "https://www.hus.fi" + links[0]
    time.sleep(1)
    x = http("GET", href, timeout=120)
    x.raise_for_status()
    wb = openpyxl.load_workbook(io.BytesIO(x.content), read_only=True, data_only=True)
    sheets = {ws.title: [tuple(row) for row in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
    rows = hus_rows(sheets, href, src["nimi"])
    for row in rows:
        row["file"] = href.rsplit("/", 1)[-1]
    return rows


def _fetch_html(src: dict) -> str:
    r = http("GET", src["url"], headers={"Accept": "text/html"}, timeout=90)
    r.raise_for_status()
    return r.text


def fetch_tampere(src: dict) -> list[dict]:
    r = http("GET", src["url"], headers={"Accept": "application/json"}, timeout=60)
    r.raise_for_status()
    return parse_tampere(r.json(), src.get("sivu") or src["url"], src["nimi"])


PARSERS = {
    "hansel": fetch_hansel,
    "hus_xlsx": fetch_hus,
    "espoo_table": lambda src: parse_espoo(_fetch_html(src), src["url"], src["nimi"]),
    "senaatti_table": lambda src: parse_senaatti(_fetch_html(src), src["url"], src["nimi"]),
    "tampere_json": fetch_tampere,
    "tuomi_accordion": lambda src: parse_tuomi(_fetch_html(src), src["url"], src["nimi"]),
    "luvn_accordion": lambda src: parse_luvn(_fetch_html(src), src["url"], src["nimi"]),
}


# ---------- Hilma plans ----------

def plan_index_row(n: dict) -> dict:
    lots = n.get("lots") or []
    desc = (n.get("descriptionFi") or "").strip() or " ".join((l.get("descriptionFi") or "") for l in lots).strip()
    return _row(id=n.get("id"), planId=n.get("planId"), title=(n.get("titleFi") or n.get("titleSv") or n.get("titleEn") or "")[:220],
                buyer=(n.get("organisationNameFi") or n.get("organisationNameSv") or n.get("organisationNameEn") or "")[:160],
                buyerId=n.get("organisationNationalRegistrationNumber"), cpv=(n.get("cpvCodes") or "").strip() or None,
                value=n.get("estimatedValue"), currency=(n.get("currency") or "EUR") if n.get("estimatedValue") else None,
                published=(n.get("datePublished") or "")[:10], expires=fi_date(n.get("expirationDate")),
                type=n.get("type"), lots=len(lots) if len(lots) > 1 else None, description=desc[:DESC_MAX],
                url=PLAN_PAGE.format(pid=n.get("planId")))


def plan_detail_fields(doc: dict) -> dict:
    """plannedDate / contractStart / contractEnd / cpv / value / nature from the public plan document."""
    pd = doc.get("planData") or {}
    lots = pd.get("procurementPlanLots") or []
    planned = sorted(fi_date(l.get("plannedENoticeDate")) for l in lots if fi_date(l.get("plannedENoticeDate")))
    starts = sorted(fi_date(l.get("estimatedContractStartDate")) for l in lots if fi_date(l.get("estimatedContractStartDate")))
    ends = sorted(fi_date(l.get("estimatedContractEndDate")) for l in lots if fi_date(l.get("estimatedContractEndDate")))
    cpv = [g(l, "itemClassificationCode", 0, "itemClassificationCode", "value") for l in lots]
    cpv = [c for c in cpv if c]
    desc = " ".join(g(l, "description", 0, "value") or "" for l in lots).strip()
    return _row(plannedDate=planned[0] if planned else None, contractStart=starts[0] if starts else None, contractEnd=ends[-1] if ends else None,
                cpv=" ".join(dict.fromkeys(cpv)) or None,
                value=g(pd, "estimatedMaxContractAmount", "value") or g(pd, "estimatedMinContractAmount", "value"),
                currency=g(pd, "estimatedMaxContractAmount", "currencyID"),
                nature=" ".join(dict.fromkeys(g(l, "procurementTypeCode", "value") or "" for l in lots)).strip() or None,
                buyer=g(pd, "buyerOrganization", "name", 0, "value"), buyerId=g(pd, "buyerOrganization", "companyID", "value"),
                description=desc[:DESC_MAX] or None, likes=len(doc.get("likes") or []) or None, detail=True)


def fetch_hilma_plans(old: dict) -> dict:
    since = (TODAY - dt.timedelta(days=PLAN_GRACE_DAYS)).isoformat()
    raw, total = fetch_filter(f"isPlan eq true and expirationDate ge {since}T00:00:00Z")
    if len(raw) < MIN_PLANS:
        raise RuntimeError(f"Hilma palautti vain {len(raw)} kilpailutussuunnitelmaa (raja {MIN_PLANS})")
    plans, new, failed = {}, 0, 0
    for n in raw:
        key = str(n.get("planId") or "")
        if not key:
            continue
        rec = plan_index_row(n)
        prev = old.get(key) or {}
        if prev.get("detail"):
            rec = {**prev, **rec, **{k: prev[k] for k in ("plannedDate", "contractStart", "contractEnd", "nature", "likes", "detail") if k in prev}}
            if prev.get("description") and len(prev["description"]) >= len(rec.get("description") or ""):
                rec["description"] = prev["description"]
        else:
            try:
                time.sleep(1)
                r = http("GET", PLAN_DETAIL.format(pid=key), timeout=60)
                r.raise_for_status()
                rec.update({k: v for k, v in plan_detail_fields(r.json()).items() if v not in (None, "")})
                new += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                log(f"warn: suunnitelmat: Hilma-suunnitelman {key} tiedot eivät latautuneet: {str(e)[:120]}")
        rec.setdefault("plannedDate", rec.get("expires"))
        rec["checked"] = TODAY.isoformat()
        plans[key] = rec
    log(f"suunnitelmat: Hilma: {len(plans)} aktiivista kilpailutussuunnitelmaa (Hilma: {total}), {new} uutta haettu, {failed} epäonnistui")
    return plans


def main():
    cfg = load_yaml(CONFIG_DIR / "kalenterit.yaml") or {}
    sources = cfg.get("kalenterit") or {}
    cache = load_json(OUT, {}) or {}
    health = dict(cache.get("health") or {})
    kalenterit = dict(cache.get("kalenterit") or {})
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hilma_ok = True
    try:
        hilma = fetch_hilma_plans(cache.get("hilma") or {})
        health["hilma"] = {"ok": True, "n": len(hilma), "fetched": now}
    except Exception as e:  # noqa: BLE001
        hilma_ok = False
        hilma = cache.get("hilma") or {}
        health["hilma"] = {"ok": False, "error": str(e)[:200], "n": len(hilma), "fetched": (cache.get("health") or {}).get("hilma", {}).get("fetched")}
        log(f"warn: suunnitelmat: Hilma-suunnitelmien haku epäonnistui: {e}")
    ok_calendars, tried = 0, 0
    for key, src in sources.items():
        if not src.get("enabled", True):
            continue
        parser = PARSERS.get(src.get("tyyppi"))
        if not parser:
            health[key] = {"ok": False, "error": f"tuntematon tyyppi {src.get('tyyppi')}", "n": len(kalenterit.get(key) or [])}
            continue
        tried += 1
        t0 = time.time()
        try:
            rows = parser(src)
            if not rows:
                raise ValueError("jäsennin ei löytänyt yhtään riviä")
            kalenterit[key] = rows
            health[key] = {"ok": True, "n": len(rows), "fetched": now}
            ok_calendars += 1
            log(f"suunnitelmat: {src['nimi']}: {len(rows)} suunniteltua hankintaa ({time.time() - t0:.0f} s)")
        except Exception as e:  # noqa: BLE001
            prev = (cache.get("health") or {}).get(key) or {}
            health[key] = {"ok": False, "error": str(e)[:200], "n": len(kalenterit.get(key) or []), "fetched": prev.get("fetched")}
            log(f"warn: suunnitelmat: {src.get('nimi', key)} epäonnistui, edelliset rivit säilytetään: {str(e)[:160]}")
        time.sleep(1)
    kalenterit = {k: v for k, v in kalenterit.items() if k in sources and sources[k].get("enabled", True)}
    health = {k: v for k, v in health.items() if k == "hilma" or (k in sources and sources[k].get("enabled", True))}
    save_json(OUT, {"fetched": now, "hilma": hilma, "kalenterit": kalenterit, "health": health}, compact=True)
    total_rows = sum(len(v) for v in kalenterit.values())
    log(f"suunnitelmat: {len(hilma)} Hilma-suunnitelmaa + {total_rows} kalenteririviä {ok_calendars}/{tried} lähteestä -> {OUT}")
    if not hilma_ok and tried and ok_calendars == 0:
        raise RuntimeError("Hilma-suunnitelmat ja kaikki hankintakalenterit epäonnistuivat")


if __name__ == "__main__":
    main()
