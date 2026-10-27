"""Sector layer (toimialakerros): consultations, guidance and rulings of sector regulators.

Sources are declared in config/toimiala.yaml (one block per source, `enabled` toggles it). Each enabled
source runs in its own try/except: a failing source is logged, recorded in the cache's `health` block and
keeps the rows it produced last time; the run fails (RuntimeError, so update.py keeps the previous cache)
only when every enabled source failed.

* Finanssivalvonta – no feeds exist; the valvottava- and lehdistötiedotteet listings are parsed and the
  titles filtered: "määräykset ja ohjeet N/YYYY" and sanction announcements become guidance rows, a
  tiedote that says "Lausuntoaika päättyy d.m.yyyy" becomes a consultation. The lausuntopyynnöt page lists
  consultations without deadlines; the deadline is borrowed from the announcing tiedote when one was
  published within a few days (lausuntopalvelu.fi, which has the deadline, is Cloudflare-blocked).
* ESMA – Drupal views table "From dd/mm/yyyy to dd/mm/yyyy"; EBA – listing cards with day/month spans
  (deadline confirmed from the detail page, robots.txt Crawl-delay 10 honoured, at most a few detail
  pages per run); EIOPA – RSS for discovery plus the listing's <dt>Deadline</dt>; EDPB – consultation cards
  with two <time> elements and the adopted-guidelines document list (a guideline still under consultation
  is a "luonnos").
* Verohallinto – public JSON search API (syventävät ohjeet typeId 7, KVL rulings typeId 10); antopäivä,
  diaarinumero, validity and "korvaa ohjeen" live on the detail page, fetched only for new ids. A KVL ruling
  marked "Ei lainvoimainen" is re-read every refresh_days because the KHO outcome is edited in place.
* Traficom – JSON search (type=regulation): 47 Määräys, 48 Määräyshankepäätös (an announcement that a
  regulation project starts; the draft's consultation is on lausuntopalvelu.fi).
* Tietosuojavaltuutettu – decisions from Finlex (/fi/viranomaiset/tietosuojavaltuutettu/<year>, Next.js RSC
  payload) because tietosuoja.fi is Cloudflare-blocked.

Politeness: at most one request per second per host (EBA 10 s), detail pages only for new ids, old rows
dropped after keep_days from their publication on the site (so a row is never re-read while it is still
listed); the builder applies the display window (antopäivä, consultations until deadline + grace).
Cache: data/cache/toimiala.json {fetched, rows: {source: [row...]}, health: {source: {ok, error, last_ok, rows}}}.
"""
from __future__ import annotations

import datetime as dt
import html as htmlmod
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from common import CACHE_DIR, CONFIG_DIR, TODAY, http, load_json, load_yaml, log, parse_dmy, save_json

OUT = CACHE_DIR / "toimiala.json"
UA = "saadosseuranta/1.0 (+https://github.com/EditMonster/Saadosseuranta; toimialakerros)"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
           "Accept-Language": "fi,en;q=0.8"}

EN_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
             "oct": 10, "nov": 11, "dec": 12}
FI_MONTHS = {"tammi": 1, "helmi": 2, "maalis": 3, "huhti": 4, "touko": 5, "kesä": 6, "heinä": 7, "elo": 8, "syys": 9,
             "loka": 10, "marras": 11, "joulu": 12}


# ---------------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------------

def strip_tags(h: str) -> str:
    h = re.sub(r"<script.*?</script>|<style.*?</style>", "", h or "", flags=re.S)
    t = re.sub(r"<(br|/p|/h\d|/li|/div|/dd|/dt)[^>]*>", "\n", h)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmlmod.unescape(t)
    t = re.sub(r"[ \t ]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", htmlmod.unescape(s or "")).strip()


def trim(text: str | None, n: int = 500) -> str:
    t = clean(text)
    if len(t) <= n:
        return t
    cut = t[:n]
    i = cut.rfind(". ")
    return cut[: i + 1] if i > n * 0.4 else cut[: n - 1].rstrip() + "…"


def iso_dmy(s: str | None) -> str | None:
    return parse_dmy(s or "")


def iso_uk(s: str | None) -> str | None:
    """'15/01/2027' -> '2027-01-15'."""
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def iso_en(s: str | None) -> str | None:
    """'15 October 2026', '26 AUGUST 2026', '08 July 2026' -> ISO."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})", s or "")
    if not m:
        return None
    mon = EN_MONTHS.get(m.group(2).lower()[:4]) or EN_MONTHS.get(m.group(2).lower()[:3])
    if not mon:
        return None
    try:
        return dt.date(int(m.group(3)), mon, int(m.group(1))).isoformat()
    except ValueError:
        return None


def iso_fi_long(s: str | None) -> str | None:
    """'11. tammikuuta 2027' / '1.1.2027' -> ISO (the first date found)."""
    m = re.search(r"(\d{1,2})\.\s*([a-zäö]+)kuuta\s+(\d{4})", s or "", re.I)
    if m and m.group(2).lower() in FI_MONTHS:
        try:
            return dt.date(int(m.group(3)), FI_MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
        except ValueError:
            return None
    return iso_dmy(s)


def iso_rfc822(s: str | None) -> str | None:
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return None


def en_day_month_year(day: str, mon: str, year: str) -> str | None:
    m = EN_MONTHS.get(mon.lower()[:4]) or EN_MONTHS.get(mon.lower()[:3])
    if not m:
        return None
    try:
        return dt.date(int(year), m, int(day)).isoformat()
    except ValueError:
        return None


def slug_of(url: str, n: int = 70) -> str:
    s = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    s = re.sub(r"_(en|fi|sv)$", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:n].rstrip("-")


def compact(row: dict) -> dict:
    return {k: v for k, v in row.items() if v not in (None, "", [], {})}


def fmt_dmy(iso: str | None) -> str:
    """'2026-10-12' -> '12.10.2026' (Finlex gives the decision no number, so the date is the reference)."""
    if not iso or len(iso) < 10:
        return iso or ""
    y, m, d = iso[:10].split("-")
    return f"{int(d)}.{int(m)}.{y}"


def days_before(iso: str, days: int) -> str:
    return (dt.date.fromisoformat(iso) - dt.timedelta(days=days)).isoformat()


class Client:
    """Polite GET: one request per `interval` seconds per host (per-host overrides for Crawl-delay)."""

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.delays: dict[str, float] = {}
        self.last: dict[str, float] = {}
        self.requests = 0

    def set_delay(self, url: str, seconds: float):
        self.delays[urlparse(url).netloc] = float(seconds)

    def get(self, url: str, **kw):
        host = urlparse(url).netloc
        wait = self.delays.get(host, self.interval) - (time.monotonic() - self.last.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        try:
            r = http("GET", url, headers=HEADERS, timeout=kw.pop("timeout", 60), **kw)
        finally:
            self.last[host] = time.monotonic()
            self.requests += 1
        r.raise_for_status()
        return r

    def text(self, url: str, **kw) -> str:
        r = self.get(url, **kw)
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding or "utf-8"
        return r.text

    def json(self, url: str, **kw):
        return self.get(url, **kw).json()


# ---------------------------------------------------------------------------------------------------
# Finanssivalvonta
# ---------------------------------------------------------------------------------------------------

FIVA = "https://www.finanssivalvonta.fi"
FIVA_ROW = re.compile(r'<li>\s*<div class="page-list-block-time">\s*<span>([^<]*)</span>\s*<time[^>]*?datetime="\s*([0-9-]+)\s*"[^>]*>'
                      r'\s*([^<]+?)\s*</time>.*?<a href="([^"]+)">(.*?)</a>', re.S)
FIVA_LP = re.compile(r'<li>\s*<a href="(https://www\.lausuntopalvelu\.fi/[^"]*proposalId=([0-9a-f-]+)[^"]*)"[^>]*>\s*(\d{1,2}\.\d{1,2}\.\d{4})\s*</a>\s*(.*?)</li>', re.S)
FIVA_HEAD = re.compile(r"(Valvottavatiedote|Lehdistötiedote)\s+(\d{1,2}\.\d{1,2}\.\d{4})\s*-\s*(\d{1,3})/(\d{4})")
FIVA_DEADLINE = re.compile(r"Lausuntoaika päättyy\s+(\d{1,2}\.\d{1,2}\.\d{4})")
FIVA_MOK_NO = re.compile(r"\b(\d{1,2})/(20\d{2})\b")
RE_LAUSUNTO = re.compile(r"pyytää lausunto|lausuntopyyntö|lausunnolle|lausuntokierro", re.I)
RE_MOK = re.compile(r"määräykset ja ohjeet|määräyksiin ja ohjeisiin|määräysten ja ohjeiden|määräys- ja ohje|määräyksi[äl]\b", re.I)
RE_SANCTION = re.compile(r"seuraamusmaksu|julkinen varoitus|julkisen varoituksen|rikemaksu|uhkasak|toimilup\w+ peru|"
                         r"hallinto-oikeus (?:hylkäsi|hyväksyi|kumosi|piti)|korkein hallinto-oikeus antoi", re.I)
RE_ESA = re.compile(r"(?:\b(?:eba|esma|eiopa|ekp|amla)\S*\b.*?\bohje)|(?:\bohje.*?\b(?:eba|esma|eiopa)\b)|viranomaisen ohjeet", re.I)
RE_VOIMAAN = re.compile(r"(?:voimaan|soveltaminen alkaa|sovelletaan|sovellettava)\s+(\d{1,2}\.\s*(?:\d{1,2}\.\d{4}|[a-zäö]+kuuta\s+\d{4}))", re.I)


def fiva_kind(title: str, esa_guidelines: bool = True) -> str | None:
    """Which tiedotteet the sector layer keeps: Lausuntopyyntö | Määräykset ja ohjeet | Hallinnollinen seuraamus | EU-ohje."""
    t = title or ""
    if RE_LAUSUNTO.search(t):
        return "Lausuntopyyntö"
    if RE_MOK.search(t):
        return "Määräykset ja ohjeet"
    if RE_SANCTION.search(t):
        return "Ohje" if re.search(r"periaatte|ohje", t, re.I) else "Hallinnollinen seuraamus"
    if esa_guidelines and RE_ESA.search(t):
        return "EU-valvontaviranomaisen ohjeet"
    return None


def parse_fiva_listing(h: str) -> list[dict]:
    out = []
    for typ, iso, dmy, href, title in FIVA_ROW.findall(h):
        url = href if href.startswith("http") else FIVA + href
        out.append({"type": clean(typ), "date": iso.strip() or iso_dmy(dmy), "url": url, "title": clean(re.sub(r"<[^>]+>", "", title))})
    return out


def parse_fiva_tiedote(h: str) -> dict:
    """Header number, lead/body text, deadline, entry-into-force hint and tags of one tiedote page."""
    m = re.search(r'<article class="col-sm-12">(.*?)<footer class="meta"', h, re.S)
    art = m.group(1) if m else h
    text = strip_tags(art)
    d: dict = {}
    hm = FIVA_HEAD.search(text)
    if hm:
        d.update({"type": hm.group(1), "date": iso_dmy(hm.group(2)), "number": f"{int(hm.group(3))}/{hm.group(4)}"})
    tm = re.search(r'<h1 class="h1-content-page">(.*?)</h1>', art, re.S)
    d["title"] = clean(re.sub(r"<[^>]+>", "", tm.group(1))) if tm else None
    lead = re.search(r'<span class="lead-text">(.*?)</span>', art, re.S)
    body = art[tm.end():] if tm else art
    body = re.split(r"<h3>\s*(?:<strong>)?\s*Lisätietoja", body, maxsplit=1)[0]
    body_text = " ".join(line for line in strip_tags(body).split("\n") if line.strip() and not line.strip().startswith("*"))
    lead_text = clean(re.sub(r"<[^>]+>", " ", lead.group(1))) if lead else ""
    d["summary"] = trim(lead_text or body_text, 500)
    dm = FIVA_DEADLINE.search(text)
    d["deadline"] = iso_dmy(dm.group(1)) if dm else None
    vm = RE_VOIMAAN.search(text)
    d["validFrom"] = iso_fi_long(vm.group(1)) if vm else None
    tags = re.search(r'aria-label="Asiasanat">(.*?)</section>', h, re.S)
    d["tags"] = [clean(t) for t in re.findall(r'class="tag"[^>]*>(.*?)</a>', tags.group(1), re.S)] if tags else []
    lp = re.search(r'href="(https://www\.lausuntopalvelu\.fi/[^"]+)"', art)
    d["lausuntopalvelu"] = htmlmod.unescape(lp.group(1)) if lp else None
    return d


def mok_refs(title: str) -> tuple[str | None, str | None]:
    """'Määräykset ja ohjeet 3/2016 on korvattu uusilla … 1/2026' -> (ref '1/2026', replaces '3/2016')."""
    nums = [f"{int(a)}/{b}" for a, b in FIVA_MOK_NO.findall(title or "")]
    if not nums:
        return None, None
    if len(nums) >= 2 and re.search(r"korva", title, re.I):
        return nums[-1], nums[0]
    return nums[0], None


def fiva_rows_from_listing(listing: list[dict], cfg: dict) -> list[dict]:
    """Listing rows filtered to the kinds the sector layer keeps (before detail pages)."""
    out = []
    for e in listing:
        kind = fiva_kind(e["title"], bool(cfg.get("esa_guidelines", True)))
        if not kind:
            continue
        lehdisto = "lehdistotiedotteet" in e["url"]
        ref, replaces = mok_refs(e["title"]) if kind == "Määräykset ja ohjeet" else (None, None)
        out.append(compact({
            "id": f"fiva-{'lt-' if lehdisto else ''}{slug_of(e['url'])}", "source": "fiva_tiedotteet", "authority": cfg["authority"],
            "scope": cfg["scope"], "laji": "kuuleminen" if kind == "Lausuntopyyntö" else "ohje",
            "kind": kind, "title": e["title"], "date": e["date"], "url": e["url"], "tiedote": e["type"],
            "ref": f"MOK {ref}" if ref else None, "replaces": f"MOK {replaces}" if replaces else None,
            "status": "annettu", "keywords": [],
        }))
    return out


def run_fiva_tiedotteet(cfg: dict, prev: list[dict], rows_all: dict, client: Client, defaults: dict) -> list[dict]:
    listing = []
    for name, url in (cfg.get("urls") or {}).items():
        part = parse_fiva_listing(client.text(url))
        if len(part) < 5:
            raise RuntimeError(f"Finanssivalvonta: {name}-listaus antoi vain {len(part)} riviä – sivurakenne lienee muuttunut")
        listing += part
    rows = fiva_rows_from_listing(listing, cfg)
    by_url = {r["url"]: r for r in prev}  # the id switches from slug to the running number once the page has been read
    budget = int(cfg.get("max_details_per_run", defaults.get("max_details_per_run", 30)))
    keep_cut = days_before(TODAY.isoformat(), int(cfg.get("keep_days", defaults.get("keep_days", 120))))
    merged: dict[str, dict] = {}
    for r in rows:
        old = by_url.get(r["url"])
        if old and not old.get("detailPending"):
            merged[old["id"]] = {**old, "title": r["title"], "date": old.get("date") or r["date"], "tiedote": r.get("tiedote")}
            continue
        if (r.get("date") or "") < keep_cut:
            continue
        if budget <= 0:
            r["detailPending"] = True
            merged[r["id"]] = r
            continue
        budget -= 1
        try:
            d = parse_fiva_tiedote(client.text(r["url"]))
        except Exception as e:  # noqa: BLE001
            log(f"warn: fiva {r['url']}: {e}")
            r["detailPending"] = True
            merged[r["id"]] = r
            continue
        r.update({"summary": d.get("summary"), "deadline": d.get("deadline"), "validFrom": d.get("validFrom"), "keywords": d.get("tags") or [],
                  "number": d.get("number"), "lausuntopalvelu": d.get("lausuntopalvelu"), "checked": TODAY.isoformat()})
        if d.get("date"):
            r["date"] = d["date"]
        if d.get("number"):
            r["id"] = f"fiva-{'lt-' if 'lehdistotiedotteet' in r['url'] else ''}{d['number'].replace('/', '-')}"
            r["ref"] = r.get("ref") or f"Fiva {d['number']}"
        if d.get("deadline"):
            r["laji"], r["kind"], r["status"] = "kuuleminen", "Lausuntopyyntö", "lausunnolla"
        elif r["laji"] == "kuuleminen":
            r["deadlineUnknown"] = True
        if r["laji"] == "ohje" and r.get("validFrom") and r["validFrom"] <= TODAY.isoformat():
            r["status"] = "voimassa"
        merged[r["id"]] = compact(r)
    done_urls = {r["url"] for r in merged.values()}
    for old in prev:  # rows that scrolled off the 60-item listing stay until keep_days prunes them
        if old["url"] not in done_urls:
            merged.setdefault(old["id"], old)
    return list(merged.values())


def parse_fiva_lausuntopyynnot(h: str) -> list[dict]:
    m = re.search(r'id="page-main-content"(.*?)<footer class="meta"', h, re.S)
    body = m.group(1) if m else h
    out = []
    for url, guid, dmy, title in FIVA_LP.findall(body):
        out.append({"guid": guid, "url": htmlmod.unescape(url), "date": iso_dmy(dmy), "title": clean(re.sub(r"<[^>]+>", "", title))})
    return out


def run_fiva_lausuntopyynnot(cfg: dict, prev: list[dict], rows_all: dict, client: Client, defaults: dict) -> list[dict]:
    entries = parse_fiva_lausuntopyynnot(client.text(cfg["url"]))
    if len(entries) < 5:
        raise RuntimeError(f"Finanssivalvonta: lausuntopyyntölista antoi vain {len(entries)} riviä – sivurakenne lienee muuttunut")
    window = int(cfg.get("match_window_days", 10))
    tiedotteet = [r for r in rows_all.get("fiva_tiedotteet", []) if r.get("laji") == "kuuleminen" and r.get("date")]
    by_id = {r["id"]: r for r in prev}
    out = []
    for e in entries:
        if not e["date"]:
            continue
        rid = f"fiva-lp-{e['guid'][:8]}"
        row = compact({"id": rid, "source": "fiva_lausuntopyynnot", "authority": cfg["authority"], "scope": cfg["scope"], "laji": "kuuleminen",
                       "kind": "Lausuntopyyntö", "title": e["title"], "date": e["date"], "url": e["url"], "ref": f"Fiva lausuntopyyntö {e['date']}",
                       "status": "lausunnolla", "keywords": []})
        d0 = dt.date.fromisoformat(e["date"])
        cands = [t for t in tiedotteet if abs((dt.date.fromisoformat(t["date"]) - d0).days) <= window
                 and (not t.get("lausuntopalvelu") or e["guid"] in t["lausuntopalvelu"])]
        cands.sort(key=lambda t: (0 if e["guid"] in (t.get("lausuntopalvelu") or "") else 1, abs((dt.date.fromisoformat(t["date"]) - d0).days)))
        if cands:
            t = cands[0]
            row.update(compact({"deadline": t.get("deadline"), "summary": t.get("summary"), "tiedoteUrl": t.get("url"), "matchedId": t["id"],
                                "keywords": t.get("keywords") or []}))
        old = by_id.get(rid) or {}
        row = {**old, **row}
        if not row.get("deadline"):
            row["deadlineUnknown"] = True
        else:
            row.pop("deadlineUnknown", None)
        out.append(compact(row))
    return out


# ---------------------------------------------------------------------------------------------------
# ESMA
# ---------------------------------------------------------------------------------------------------

ESMA = "https://www.esma.europa.eu"
ESMA_ROW = re.compile(r'From (\d{2}/\d{2}/\d{4}) to (\d{2}/\d{2}/\d{4})\s*</td>.*?<a href="(/press-news/consultations/[^"]+)" hreflang="en">(.*?)</a>'
                      r'.*?consultation-section">(.*?)</td>', re.S)
ESMA_REF = re.compile(r"/sites/default/files/\d{4}-\d{2}/(ESMA\d{2}-\d+-\d+)")


def eu_kind(title: str, default: str = "Consultation paper") -> str:
    t = (title or "").lower()
    if "call for evidence" in t or "call to participate" in t or "call for input" in t:
        return "Call for evidence"
    if "discussion paper" in t:
        return "Discussion paper"
    if "survey" in t:
        return "Survey"
    return default


def parse_esma(h: str) -> list[dict]:
    out = []
    matches = list(ESMA_ROW.finditer(h))
    for i, m in enumerate(matches):
        seg = h[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(h)]
        rm = ESMA_REF.search(seg)
        title = clean(re.sub(r"<[^>]+>", "", m.group(4)))
        out.append({"start": iso_uk(m.group(1)), "end": iso_uk(m.group(2)), "url": ESMA + m.group(3), "title": title,
                    "section": clean(m.group(5)), "ref": rm.group(1) if rm else None})
    return out


def run_esma(cfg: dict, prev: list[dict], rows_all: dict, client: Client, defaults: dict) -> list[dict]:
    entries = []
    for page in range(int(cfg.get("pages", 1))):
        part = parse_esma(client.text(cfg["url"], params={"page": page} if page else None))
        if page == 0 and len(part) < 5:
            raise RuntimeError(f"ESMA: kuulemislista antoi vain {len(part)} riviä – sivurakenne lienee muuttunut")
        entries += part
    by_id = {r["id"]: r for r in prev}
    out = {}
    for e in entries:
        rid = f"esma-{slug_of(e['url'])}"
        row = compact({"id": rid, "source": "esma_consultations", "authority": cfg["authority"], "scope": cfg["scope"], "laji": "kuuleminen",
                       "kind": eu_kind(e["title"]), "title": e["title"], "date": e["start"], "deadline": e["end"], "url": e["url"],
                       "ref": e.get("ref"), "status": "lausunnolla", "keywords": [s.strip() for s in e["section"].split(",") if s.strip()]})
        out[rid] = {**by_id.get(rid, {}), **row}
    for rid, old in by_id.items():
        out.setdefault(rid, old)
    return list(out.values())


# ---------------------------------------------------------------------------------------------------
# EBA
# ---------------------------------------------------------------------------------------------------

EBA = "https://www.eba.europa.eu"
EBA_CARD = re.compile(r'<article class="teaser-event-calendar teaser-event-calendar--consultation".*?</article>', re.S)
EBA_DM = re.compile(r'calendar-day">\s*(\d+)\s*</span>\s*<span class="teaser-event-calendar__calendar-month">\s*(\w+)\s*</span>')
EBA_YEAR = re.compile(r'calendar-year"[^>]*>\s*(\d{4})(?:\s*-\s*(\d{4}))?')
EBA_DEADLINE = re.compile(r"Deadline for submitting responses:\s*(?:<[^>]+>\s*)*(\d{2}/\d{2}/\d{4})")


def parse_eba_listing(h: str) -> list[dict]:
    out = []
    for c in EBA_CARD.findall(h):
        href = re.search(r'href="([^"]+)"', c)
        dm = EBA_DM.findall(c)
        ym = EBA_YEAR.search(c)
        tm = re.search(r'__title"[^>]*>\s*<a[^>]*>\s*<span>(.*?)</span>', c, re.S)
        rf = re.search(r"<small>\(([^)]+)\)</small>", c)
        if not (href and dm and ym and tm):
            continue
        y1, y2 = ym.groups()
        start = en_day_month_year(dm[0][0], dm[0][1], y1)
        end = None
        if len(dm) > 1:
            end = en_day_month_year(dm[1][0], dm[1][1], y2 or y1)
            if end and start and end < start and not y2:
                end = en_day_month_year(dm[1][0], dm[1][1], str(int(y1) + 1))
        url = href.group(1) if href.group(1).startswith("http") else EBA + href.group(1)
        out.append({"url": url, "start": start, "end": end, "title": clean(tm.group(1)), "ref": rf.group(1).strip() if rf else None})
    return out


def parse_eba_detail(h: str) -> dict:
    d: dict = {}
    m = EBA_DEADLINE.search(h)
    d["deadline"] = iso_uk(m.group(1)) if m else None
    m = re.search(r"<b>(EBA/[A-Z]+/\d{4}/[\d/]+)</b>", h)
    d["ref"] = m.group(1) if m else None
    m = re.search(r"Consultation\s*<b>(OPEN|CLOSED)</b>", h)
    d["status"] = m.group(1).lower() if m else None
    m = re.search(r"<b>(\d{1,2} [A-Z]+(?: \d{4})? - \d{1,2} [A-Z]+ \d{4})</b>", h)
    d["period"] = m.group(1) if m else None
    m = re.search(r'<h1 class="page-title">\s*<span>(.*?)</span>', h, re.S)
    d["title"] = clean(m.group(1)) if m else None
    return d


def run_eba(cfg: dict, prev: list[dict], rows_all: dict, client: Client, defaults: dict) -> list[dict]:
    client.set_delay(cfg["url"], float(cfg.get("crawl_delay", 10)))
    entries = parse_eba_listing(client.text(cfg["url"]))
    if len(entries) < 3:
        raise RuntimeError(f"EBA: kuulemislista antoi vain {len(entries)} korttia – sivurakenne lienee muuttunut")
    by_id = {r["id"]: r for r in prev}
    budget = int(cfg.get("max_details_per_run", 5))
    keep_cut = days_before(TODAY.isoformat(), int(cfg.get("keep_days", defaults.get("keep_days", 120))))
    grace_cut = days_before(TODAY.isoformat(), int(cfg.get("consultation_grace_days", defaults.get("consultation_grace_days", 30))))
    out = {}
    for e in entries:
        ref_slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"^EBA/", "", e.get("ref") or "", flags=re.I).lower()).strip("-")
        rid = f"eba-{ref_slug or slug_of(e['url'])}"  # EBA/CP/2026/19 -> eba-cp-2026-19
        if rid not in by_id and (e.get("start") or "") < keep_cut and (e.get("end") or "") < grace_cut:
            continue  # closed long ago and outside the window: not worth a 10-second detail fetch
        kind = "Discussion paper" if "/DP/" in (e.get("ref") or "") else eu_kind(e["title"])
        row = compact({"id": rid, "source": "eba_consultations", "authority": cfg["authority"], "scope": cfg["scope"], "laji": "kuuleminen",
                       "kind": kind, "title": e["title"], "date": e["start"], "deadline": e["end"], "url": e["url"], "ref": e.get("ref"),
                       "status": "lausunnolla", "keywords": []})
        old = by_id.get(rid)
        if old and not old.get("detailPending"):
            out[rid] = {**old, **row, "deadline": row.get("deadline") or old.get("deadline")}  # the live listing reflects extensions
            continue
        if budget <= 0:
            row["detailPending"] = True
            out[rid] = row
            continue
        budget -= 1
        try:
            d = parse_eba_detail(client.text(e["url"]))
            if d.get("deadline"):
                row["deadline"] = d["deadline"]
            if d.get("ref") and not row.get("ref"):
                row["ref"] = d["ref"]
            row["checked"] = TODAY.isoformat()
        except Exception as ex:  # noqa: BLE001
            log(f"warn: eba {e['url']}: {ex}")
            row["detailPending"] = True
        out[rid] = compact(row)
    for rid, old in by_id.items():
        out.setdefault(rid, old)
    return list(out.values())


# ---------------------------------------------------------------------------------------------------
# EIOPA
# ---------------------------------------------------------------------------------------------------

EIOPA = "https://www.eiopa.europa.eu"
EIOPA_ART = re.compile(r"<article\s+class=\"ecl-content-item\".*?</article>", re.S)
EIOPA_TIME = re.compile(r"<dt[^>]*>\s*(Opening date|Deadline|Status)\s*</dt>\s*<dd[^>]*>\s*<div>\s*(?:<time datetime=\"([^\"]+)\"|<span[^>]*>\s*([^<]*)<)")


def rss_items(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    out = []
    for it in root.iter("item"):
        cats = [(c.get("domain") or "", clean(c.text)) for c in it.findall("category")]
        out.append({"title": clean(it.findtext("title")), "url": clean(it.findtext("link")), "date": iso_rfc822(it.findtext("pubDate")),
                    "description": clean(strip_tags(htmlmod.unescape(it.findtext("description") or ""))), "categories": cats,
                    "guid": clean(it.findtext("guid"))})
    return out


def parse_eiopa_rss(xml_text: str) -> list[dict]:
    out = []
    for it in rss_items(xml_text):
        topics = [v for d, v in it["categories"] if d == "Topics"]
        typ = next((v for d, v in it["categories"] if d.startswith("Type")), None)
        out.append({"title": it["title"], "url": it["url"], "date": it["date"], "topics": topics, "type": typ})
    return out


def parse_eiopa_dl(block: str) -> dict:
    d: dict = {}
    for key, iso, txt in EIOPA_TIME.findall(block):
        if key == "Status":
            d["status"] = clean(txt).lower() or None
        elif key == "Opening date":
            d["start"] = (iso or "")[:10] or None
        else:
            d["deadline"] = (iso or "")[:10] or None
    return d


def parse_eiopa_listing(h: str) -> list[dict]:
    out = []
    for a in EIOPA_ART.findall(h):
        tm = re.search(r'ecl-content-block__title">\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>', a, re.S)
        if not tm:
            continue
        st = re.search(r">\s*Status:\s*(\w+)\s*<", a)
        d = parse_eiopa_dl(a)
        url = tm.group(1) if tm.group(1).startswith("http") else EIOPA + tm.group(1)
        out.append({"url": url, "title": clean(tm.group(2)), "status": st.group(1).lower() if st else d.get("status"),
                    "start": d.get("start"), "deadline": d.get("deadline")})
    return out


def parse_eiopa_detail(h: str) -> dict:
    return parse_eiopa_dl(h)


def run_eiopa(cfg: dict, prev: list[dict], rows_all: dict, client: Client, defaults: dict) -> list[dict]:
    feed = parse_eiopa_rss(client.text(cfg["rss"]))
    if len(feed) < 5:
        raise RuntimeError(f"EIOPA: RSS antoi vain {len(feed)} kohdetta – syöte lienee muuttunut")
    listing: dict[str, dict] = {}
    for page in range(int(cfg.get("pages", 2))):
        try:
            for e in parse_eiopa_listing(client.text(cfg["listing"], params={"page": page} if page else None)):
                listing[e["url"]] = e
        except Exception as ex:  # noqa: BLE001
            log(f"warn: eiopa listaus sivu {page}: {ex}")
            break
    by_id = {r["id"]: r for r in prev}
    budget = int(cfg.get("max_details_per_run", defaults.get("max_details_per_run", 30)))
    keep_cut = days_before(TODAY.isoformat(), int(cfg.get("keep_days", defaults.get("keep_days", 120))))
    out = {}
    for f in feed:
        rid = f"eiopa-{slug_of(f['url'])}"
        if rid not in by_id and (f.get("date") or "") < keep_cut:
            continue  # the listing shows open consultations only; an old closed one is not worth a detail fetch
        li = listing.get(f["url"]) or {}
        row = compact({"id": rid, "source": "eiopa_consultations", "authority": cfg["authority"], "scope": cfg["scope"], "laji": "kuuleminen",
                       "kind": eu_kind(f["title"], "Consultation paper" if (f.get("type") or "").lower().startswith("consult") else (f.get("type") or "Consultation")),
                       "title": f["title"], "date": li.get("start") or f["date"], "published": f["date"], "deadline": li.get("deadline"),
                       "url": f["url"], "status": "lausunnolla", "keywords": f.get("topics") or []})
        old = by_id.get(rid) or {}
        if not row.get("deadline") and old.get("deadline"):
            row["deadline"] = old["deadline"]
        if not row.get("deadline") and not old.get("checked") and budget > 0:
            budget -= 1
            try:
                d = parse_eiopa_detail(client.text(f["url"]))
                row.update(compact({"deadline": d.get("deadline"), "date": d.get("start") or row.get("date")}))
            except Exception as ex:  # noqa: BLE001
                log(f"warn: eiopa {f['url']}: {ex}")
            row["checked"] = TODAY.isoformat()
        if not row.get("deadline"):
            row["deadlineUnknown"] = True
        out[rid] = compact({**old, **row})
        if row.get("deadline"):
            out[rid].pop("deadlineUnknown", None)
    for rid, old in by_id.items():
        out.setdefault(rid, old)
    return list(out.values())


# ---------------------------------------------------------------------------------------------------
# EDPB
# ---------------------------------------------------------------------------------------------------

EDPB = "https://www.edpb.europa.eu"
EDPB_CARD = re.compile(r'<div class="node-public-consultation-card">(.*?)node-public-consultation-card__link" href="([^"]+)"', re.S)
EDPB_DOC = re.compile(r'<div class="document-card document-card--([^"]*)">(.*?)document-card__link" href="([^"]+)"', re.S)
EDPB_REF = re.compile(r"\b(Guidelines|Recommendations|Opinion|Statement|Template|Decision)\s+(\d{1,3}/\d{4})", re.I)


def edpb_ref(title: str) -> str | None:
    m = EDPB_REF.search(title or "")
    if not m:
        return None
    num, year = m.group(2).split("/")
    return f"{m.group(1)[:1].upper() + m.group(1)[1:].lower()} {int(num)}/{year}"  # '04/2026' and '4/2026' are the same document


def parse_edpb_consultations(h: str) -> list[dict]:
    out = []
    for body, href in EDPB_CARD.findall(h):
        st = re.search(r"public-consultation-status-(\w+)", body)
        tm = re.search(r'__title">\s*<span>(.*?)</span>', body, re.S)
        times = re.findall(r'<time datetime="([^"]+)"', body)
        if not tm or not times:
            continue
        out.append({"status": st.group(1) if st else "closed", "title": clean(tm.group(1)), "start": times[0][:10],
                    "end": times[1][:10] if len(times) > 1 else None, "url": href if href.startswith("http") else EDPB + href})
    return out


def parse_edpb_documents(h: str) -> list[dict]:
    out = []
    for typ, body, href in EDPB_DOC.findall(h):
        tm = re.search(r'<div class="document-card__title">\s*(.*?)\s*</div>', body, re.S)
        dm = re.search(r'<time datetime="([^"]+)"', body)
        ty = re.search(r'document-card__document-type">\s*(.*?)\s*<', body)
        if not tm or not dm:
            continue
        out.append({"type": clean(ty.group(1)) if ty else typ, "title": clean(tm.group(1)), "date": dm.group(1)[:10],
                    "topics": [clean(t) for t in re.findall(r"<span>#(.*?)</span>", body)], "url": href if href.startswith("http") else EDPB + href})
    return out


def run_edpb_consultations(cfg: dict, prev: list[dict], rows_all: dict, client: Client, defaults: dict) -> list[dict]:
    entries = parse_edpb_consultations(client.text(cfg["url"]))
    if len(entries) < 3:
        raise RuntimeError(f"EDPB: kuulemissivu antoi vain {len(entries)} korttia – sivurakenne lienee muuttunut")
    by_id = {r["id"]: r for r in prev}
    out = {}
    for e in entries:
        rid = f"edpb-{slug_of(e['url'])}"
        status = {"open": "lausunnolla", "upcoming": "tulossa"}.get(e["status"], "päättynyt")
        row = compact({"id": rid, "source": "edpb_consultations", "authority": cfg["authority"], "scope": cfg["scope"], "laji": "kuuleminen",
                       "kind": "Public consultation", "title": e["title"], "date": e["start"], "deadline": e["end"], "url": e["url"],
                       "ref": edpb_ref(e["title"]), "status": status, "keywords": []})
        out[rid] = {**by_id.get(rid, {}), **row}
    for rid, old in by_id.items():
        out.setdefault(rid, old)
    return list(out.values())


def run_edpb_guidelines(cfg: dict, prev: list[dict], rows_all: dict, client: Client, defaults: dict) -> list[dict]:
    docs = parse_edpb_documents(client.text(cfg["url"]))
    if len(docs) < 3:
        raise RuntimeError(f"EDPB: ohjeluettelo antoi vain {len(docs)} korttia – sivurakenne lienee muuttunut")
    under_consultation = {r.get("ref") for r in rows_all.get("edpb_consultations", []) if r.get("status") in ("lausunnolla", "tulossa") and r.get("ref")}
    by_id = {r["id"]: r for r in prev}
    out = {}
    for d in docs:
        rid = f"edpb-gl-{slug_of(d['url'])}"
        ref = edpb_ref(d["title"])
        row = compact({"id": rid, "source": "edpb_guidelines", "authority": cfg["authority"], "scope": cfg["scope"], "laji": "ohje",
                       "kind": "Ohje (EDPB)", "title": d["title"], "date": d["date"], "url": d["url"], "ref": ref,
                       "status": "luonnos" if ref and ref in under_consultation else "annettu", "keywords": d.get("topics") or []})
        out[rid] = {**by_id.get(rid, {}), **row}
    for rid, old in by_id.items():
        out.setdefault(rid, old)
    return list(out.values())


# ---------------------------------------------------------------------------------------------------
# Verohallinto (syventävät ohjeet, KVL)
# ---------------------------------------------------------------------------------------------------

VERO = "https://www.vero.fi"
VERO_DL = re.compile(r"<dt>(.*?)</dt>\s*<dd>\s*(.*?)\s*</dd>", re.S)
KVL_STATUS = re.compile(r"\((Ei lainvoimainen|Lainvoimainen)\)", re.I)
KVL_KHO = re.compile(r"KHO\s+(\d{1,2}\.\d{1,2}\.\d{4})\s+taltio(?:numero)?\s+(\d+)(?:\s+\((KHO\s*\d{4}:\d+)\))?\s*\(([^)]+)\)")


def vero_search_params(cfg: dict, page: int = 1) -> dict:
    return {"query": "", "language": "fi", "page": page, "pageSize": int(cfg.get("pageSize", 50)), "rootFilter": int(cfg["rootFilter"]),
            "sort": 1, "typeId": int(cfg["typeId"]), "showAllVersions": "false"}


def vero_hits(data: dict) -> list[dict]:
    out = []
    for h in data.get("Hits") or []:
        out.append({"contentId": h.get("ContentId"), "title": clean(h.get("Title")), "date": iso_dmy(h.get("Date")),
                    "url": VERO + (h.get("FriendlyUrl") or ""), "tags": h.get("TagNames") or [], "proTags": h.get("TaxProTagNames") or [],
                    "glossary": h.get("KVLGlossaryTags") or [], "contentType": h.get("ContentType")})
    return out


def vero_meta(h: str) -> dict:
    m = re.search(r'<div class="page-version__info">(.*?)<div class="row content-wrapper', h, re.S)
    block = m.group(1) if m else h
    return {clean(k): clean(re.sub(r"<[^>]+>", " ", v)) for k, v in VERO_DL.findall(block)}


def vero_paragraphs(h: str) -> list[str]:
    m = re.search(r'<div class="main-body">(.*?)</div>\s*<div class="(?:contentarea-main|page-modified)', h, re.S)
    body = m.group(1) if m else ""
    paras = [clean(re.sub(r"<[^>]+>", " ", p)) for p in re.findall(r"<p[^>]*>(.*?)</p>", body, re.S)]
    return [p for p in paras if p]


def parse_vero_ohje(h: str) -> dict:
    meta = vero_meta(h)
    validity = meta.get("Voimassaolo") or ""
    vdates = re.findall(r"\d{1,2}\.\d{1,2}\.\d{4}", validity)
    paras = vero_paragraphs(h)
    tm = re.search(r"<title>(.*?)(?: - vero\.fi)?</title>", h, re.S)
    pm = re.search(r'name="pageID" content="(\d+)"', h)
    return compact({"title": clean(tm.group(1)) if tm else None, "pageId": int(pm.group(1)) if pm else None,
                    "date": iso_dmy(meta.get("Antopäivä")), "diary": meta.get("Diaarinumero") or None,
                    "validFrom": iso_dmy(vdates[0]) if vdates else None, "validTo": iso_dmy(vdates[1]) if len(vdates) > 1 else None,
                    "validity": validity or None, "replaces": meta.get("Korvaa ohjeen") or None, "authorisation": meta.get("Valtuutussäännös") or None,
                    "summary": trim(" ".join(paras[:2]), 500), "old": "Tämä on vanha versio" in h})


def parse_vero_kvl(h: str) -> dict:
    meta = vero_meta(h)
    paras = vero_paragraphs(h)
    status, kho, statutes, validity = None, None, None, None
    if paras:
        last = paras[-1]
        sm, km = KVL_STATUS.search(last), KVL_KHO.search(last)
        if km:
            status = f"KHO {km.group(1)}" + (f" ({km.group(3)})" if km.group(3) else "") + f": {km.group(4).strip()}"
            kho = {"date": iso_dmy(km.group(1)), "taltio": km.group(2), "ref": km.group(3), "outcome": km.group(4).strip()}
            paras = paras[:-1]
        elif sm:
            status = sm.group(1).lower()
            paras = paras[:-1]
        elif re.fullmatch(r"\(?[^.]{0,60}\)?", last) and len(paras) > 2:
            status = last.strip("() ").lower()
            paras = paras[:-1]
    for i, p in enumerate(paras):
        if re.match(r"Ennakkoratkaisu (ajalle|verovuo)", p):
            validity = p
            statutes = " ".join(paras[i + 1:]) or None
            paras = paras[:i]
            break
    hm = re.search(r"<h1>\s*(KVL:\d{4}/\d+)\s*</h1>", h)
    kw = [k.strip() for k in re.split(r",\s*", meta.get("Avainsanat") or "") if k.strip()]
    return compact({"ref": hm.group(1) if hm else None, "date": iso_dmy(meta.get("Antopäivä")), "diary": meta.get("Diaarinumero") or None,
                    "keywords": kw, "summary": trim(" ".join(paras), 600), "validity": validity, "statutes": statutes, "status": status, "kho": kho})


def run_vero_ohjeet(cfg: dict, prev: list[dict], rows_all: dict, client: Client, defaults: dict) -> list[dict]:
    hits = vero_hits(client.json(cfg["api"], params=vero_search_params(cfg)))
    if len(hits) < 10:
        raise RuntimeError(f"Verohallinto: ohjehaku antoi vain {len(hits)} osumaa – rajapinta lienee muuttunut")
    by_id = {r["id"]: r for r in prev}
    budget = int(cfg.get("max_details_per_run", defaults.get("max_details_per_run", 30)))
    keep_cut = days_before(TODAY.isoformat(), int(cfg.get("keep_days", defaults.get("keep_days", 120))))
    out = {}
    for hit in hits:
        if not hit["contentId"]:
            continue
        rid = f"vero-{hit['contentId']}"
        row = compact({"id": rid, "source": "vero_ohjeet", "authority": cfg["authority"], "scope": cfg["scope"], "laji": "ohje",
                       "kind": "Syventävä vero-ohje", "title": hit["title"], "date": hit["date"], "published": hit["date"], "url": hit["url"],
                       "status": "voimassa", "keywords": list(dict.fromkeys(hit["tags"] + hit["proTags"]))})
        old = by_id.get(rid)
        if old and not old.get("detailPending"):
            out[rid] = {**old, **row, "date": old.get("date") or row["date"]}
            continue
        if (row.get("date") or "") < keep_cut:
            continue
        if budget <= 0:
            row["detailPending"] = True
            out[rid] = row
            continue
        budget -= 1
        try:
            d = parse_vero_ohje(client.text(hit["url"]))
            row.update(compact({"date": d.get("date"), "diary": d.get("diary"), "validFrom": d.get("validFrom"), "validTo": d.get("validTo"),
                                "replaces": d.get("replaces"), "summary": d.get("summary"), "authorisation": d.get("authorisation")}))
            if d.get("validFrom") and d["validFrom"] > TODAY.isoformat():
                row["status"] = "annettu"
            row["checked"] = TODAY.isoformat()
        except Exception as ex:  # noqa: BLE001
            log(f"warn: vero {hit['url']}: {ex}")
            row["detailPending"] = True
        out[rid] = compact(row)
    for rid, old in by_id.items():
        out.setdefault(rid, old)
    return list(out.values())


def run_vero_kvl(cfg: dict, prev: list[dict], rows_all: dict, client: Client, defaults: dict) -> list[dict]:
    hits = vero_hits(client.json(cfg["api"], params=vero_search_params(cfg)))
    if len(hits) < 10:
        raise RuntimeError(f"Keskusverolautakunta: haku antoi vain {len(hits)} osumaa – rajapinta lienee muuttunut")
    by_id = {r["id"]: r for r in prev}
    budget = int(cfg.get("max_details_per_run", defaults.get("max_details_per_run", 30)))
    refresh_cut = days_before(TODAY.isoformat(), int(cfg.get("refresh_days", 30)))
    keep_cut = days_before(TODAY.isoformat(), int(cfg.get("keep_days", defaults.get("keep_days", 120))))
    out = {}
    for hit in hits:
        m = re.match(r"KVL:(\d{4})/(\d+)", hit["title"])
        if not m:
            continue
        rid = f"kvl-{m.group(1)}-{int(m.group(2))}"
        row = compact({"id": rid, "source": "vero_kvl", "authority": cfg["authority"], "scope": cfg["scope"], "laji": "ratkaisu",
                       "kind": "Ennakkoratkaisu (KVL)", "ref": f"KVL:{m.group(1)}/{int(m.group(2))}", "title": hit["title"], "date": hit["date"],
                       "published": hit["date"], "url": hit["url"], "keywords": hit["glossary"], "taxTypes": hit["tags"], "status": "ei lainvoimainen"})
        old = by_id.get(rid)
        stale = old and old.get("status") == "ei lainvoimainen" and (old.get("checked") or "") < refresh_cut
        if old and not old.get("detailPending") and not stale:
            out[rid] = {**old, **row, "date": old.get("date") or row["date"], "status": old.get("status") or row["status"]}
            continue
        if (row.get("date") or "") < keep_cut and not old:
            continue
        if budget <= 0:
            row["detailPending"] = True
            out[rid] = {**(old or {}), **row}
            continue
        budget -= 1
        try:
            d = parse_vero_kvl(client.text(hit["url"]))
            row.update(compact({"date": d.get("date"), "diary": d.get("diary"), "summary": d.get("summary"), "validity": d.get("validity"),
                                "statutes": d.get("statutes"), "status": d.get("status"), "kho": d.get("kho"),
                                "keywords": d.get("keywords") or hit["glossary"]}))
            row["checked"] = TODAY.isoformat()
        except Exception as ex:  # noqa: BLE001
            log(f"warn: kvl {hit['url']}: {ex}")
            row["detailPending"] = True
        out[rid] = compact({**(old or {}), **row})
    for rid, old in by_id.items():
        out.setdefault(rid, old)
    return list(out.values())


# ---------------------------------------------------------------------------------------------------
# Traficom
# ---------------------------------------------------------------------------------------------------

TRAFICOM = "https://www.traficom.fi"
RE_PLANNED = re.compile(r"(?:antaa|annetaan|annettaisiin|valmistu\w+|voimaan)[^.]{0,80}?\b((?:alku|loppu)?(?:kevä|kesä|syks|talv|vuo(?:nna|den)|"
                        r"tammi|helmi|maalis|huhti|touko|heinä|elo|syys|loka|marras|joulu)\w*\s+\d{4})", re.I)


def parse_traficom(data: dict, cfg: dict) -> list[dict]:
    types = {int(k): v for k, v in (cfg.get("regulation_types") or {47: "Määräys", 48: "Määräyshankepäätös"}).items()}
    out = []
    for it in data.get("items") or []:
        kind = (it.get("regulation_type_name") or [None])[0]
        if kind not in types.values():
            continue
        number = it.get("regulation_number") or ""
        nm = re.search(r"/(\d{4,})/", number)
        rid = f"traficom-{nm.group(1)}" if nm else f"traficom-id-{it.get('id')}"
        text = strip_tags(it.get("text") or "")
        pm = RE_PLANNED.search(text) if kind == "Määräyshankepäätös" else None
        valid_from = (it.get("valid_from") or "")[:10] or None
        date = (it.get("listing_sort_date") or it.get("created") or "")[:10] or None
        link = it.get("link") or {}
        status = "luonnos" if kind == "Määräyshankepäätös" else ("annettu" if valid_from and valid_from > TODAY.isoformat() else "voimassa")
        out.append(compact({"id": rid, "source": "traficom_maaraykset", "authority": cfg.get("authority", "Traficom"), "scope": cfg.get("scope", "fi"),
                            "laji": "ohje", "kind": kind, "title": clean(it.get("title")), "date": date, "validFrom": None if kind == "Määräyshankepäätös" else valid_from,
                            "validTo": (it.get("expire") or "")[:10] or None, "diary": number or None, "url": TRAFICOM + (it.get("path") or ""),
                            "finlexUrl": link.get("url") if "finlex.fi" in (link.get("url") or "") else None, "pdfUrl": link.get("url") if (link.get("extension") or "").lower() == "pdf" else None,
                            "summary": trim(text, 500), "plannedText": pm.group(1) if pm else None, "status": status, "keywords": []}))
    return out


def run_traficom(cfg: dict, prev: list[dict], rows_all: dict, client: Client, defaults: dict) -> list[dict]:
    params = [("langcode", "fi"), ("size", int(cfg.get("size", 50))), ("offset", 0), ("type", "regulation")]
    params += [("regulationType", int(k)) for k in (cfg.get("regulation_types") or {47: 1, 48: 1})]
    data = client.json(cfg["api"], params=params)
    rows = parse_traficom(data, cfg)
    if len(rows) < 5:
        raise RuntimeError(f"Traficom: määräyshaku antoi vain {len(rows)} riviä – rajapinta lienee muuttunut")
    by_id = {r["id"]: r for r in prev}
    out = {r["id"]: {**by_id.get(r["id"], {}), **r} for r in rows}
    for rid, old in by_id.items():
        out.setdefault(rid, old)
    return list(out.values())


# ---------------------------------------------------------------------------------------------------
# Tietosuojavaltuutettu (Finlex)
# ---------------------------------------------------------------------------------------------------

FINLEX = "https://www.finlex.fi"
TSV_ROW = re.compile(r'"aria-label":"(\d{1,2}\.\d{1,2}\.\d{4}), ([^"]+)"[^}]*?"href":"(/fi/viranomaiset/tietosuojavaltuutettu/(\d{4})/(\d+))"')


def parse_tsv(h: str) -> list[dict]:
    h2 = h.replace('\\"', '"')
    seen: dict[str, dict] = {}
    for dmy, title, href, year, n in TSV_ROW.findall(h2):
        if href in seen:
            continue
        seen[href] = {"date": iso_dmy(dmy), "title": clean(re.sub(r"(\\+n|\s)+", " ", title)), "url": FINLEX + href, "year": int(year), "n": int(n)}
    return list(seen.values())


def run_tsv(cfg: dict, prev: list[dict], rows_all: dict, client: Client, defaults: dict) -> list[dict]:
    years = [TODAY.year] + ([TODAY.year - 1] if TODAY.month <= 2 else [])
    entries = []
    for y in years:
        part = parse_tsv(client.text(cfg["url"].format(year=y)))
        if y == TODAY.year and not part and TODAY.month > 2:
            raise RuntimeError(f"Finlex: tietosuojavaltuutetun {y}-sivulta ei löytynyt yhtään ratkaisua – sivurakenne lienee muuttunut")
        entries += part
    by_id = {r["id"]: r for r in prev}
    out = {}
    for e in entries:
        rid = f"tsv-{e['year']}-{e['n']}"
        row = compact({"id": rid, "source": "tsv_finlex", "authority": cfg["authority"], "scope": cfg["scope"], "laji": "ratkaisu",
                       "kind": "Ratkaisu", "ref": f"TSV {fmt_dmy(e['date'])}", "title": e["title"], "date": e["date"], "url": e["url"],
                       "status": "annettu", "keywords": []})
        out[rid] = {**by_id.get(rid, {}), **row}
    for rid, old in by_id.items():
        out.setdefault(rid, old)
    return list(out.values())


# ---------------------------------------------------------------------------------------------------
# Finlex authority listings: oikeusasiamies, oikeuskansleri, yleissitovat työehtosopimukset, määräyskokoelmat
# (the authorities' own sites oikeusasiamies.fi, oikeuskansleri.fi, energiavirasto.fi … answer GitHub's and this
# environment's network with a Cloudflare challenge; Finlex publishes the same decisions and regulations)
# ---------------------------------------------------------------------------------------------------

FINLEX_ROW = re.compile(r'"aria-label":"(\d{1,2}\.\d{1,2}\.\d{4}) ([^"]{3,400}?)"[^}]*?"href":"(/fi/viranomaiset/[^"]+?/(\d{4})/(\d+))"')
REF_LEAD = re.compile(r"^([A-ZÄÖa-zäö0-9./ -]{3,80}?),\s+(.+)$")  # "6819/2026, …", "OKV/1439/10/2025 ja OKV/…, …", "VK/ 24949/2026, …"


def parse_finlex_list(h: str) -> list[dict]:
    """A Finlex authority listing (Next.js payload): one entry per document – date, reference, title, url."""
    h2 = h.replace('\\"', '"')
    seen: dict[str, dict] = {}
    for dmy, label, href, year, n in FINLEX_ROW.findall(h2):
        if href in seen:
            continue
        label = clean(re.sub(r"(\\+n|\s)+", " ", label))
        m = REF_LEAD.match(label)
        ref, title = (m.group(1), m.group(2)) if m and "/" in m.group(1) and re.search(r"\d", m.group(1)) else (None, label)
        ref = re.sub(r"/\s+", "/", ref) if ref else None
        seen[href] = {"date": iso_dmy(dmy), "ref": ref, "title": title, "url": FINLEX + href, "year": int(year), "n": int(n),
                      "path": href}
    return list(seen.values())


def run_finlex_list(cfg: dict, prev: list[dict], rows_all: dict, client: Client, defaults: dict) -> list[dict]:
    """config: url (with {year}: the current year, and the previous one in January–February) or
    agencies {slug: name} (each agency's latest regulations from its määräyskokoelma page); id_prefix, kind,
    ref_prefix, empty_ok (a listing that may legitimately be empty)."""
    client.set_delay(FINLEX, 1.5)  # Finlex answers 429 when hit faster
    pages: list[tuple[str, str | None]] = []
    if cfg.get("agencies"):
        pages = [(cfg["url"].format(agency=slug), name) for slug, name in cfg["agencies"].items()]
    else:
        years = [TODAY.year] + ([TODAY.year - 1] if TODAY.month <= 2 else [])
        pages = [(cfg["url"].format(year=y), None) for y in years]
    entries, failures = [], []
    for url, agency in pages:
        try:
            part = parse_finlex_list(client.text(url))
        except Exception as e:  # noqa: BLE001 – one agency's page must not stop the others
            failures.append(f"{url}: {e}")
            continue
        entries += [dict(e, agency=agency) for e in part]
    if failures and len(failures) == len(pages):
        raise RuntimeError(f"Finlex: yhtään listausta ei saatu – {failures[0]}")
    if not entries and not cfg.get("empty_ok") and TODAY.month > 2:
        raise RuntimeError(f"Finlex: listaukselta {pages[0][0]} ei löytynyt yhtään asiakirjaa – sivurakenne lienee muuttunut")
    by_id = {r["id"]: r for r in prev}
    out = {}
    for e in entries:
        slug = e["path"].split("/")[-3] if cfg.get("agencies") else None
        rid = "-".join(x for x in (cfg["id_prefix"], slug, str(e["year"]), str(e["n"])) if x)
        kind = cfg.get("kind") or "Ratkaisu"
        if cfg.get("lausunto_kind") and re.match(r"Lausunto\b", e["title"]):
            kind = cfg["lausunto_kind"]
        title = e["title"]
        if cfg.get("agencies") and (mk := re.match(r"(Ohje|Suositus|Päätös|Määräys)\s*:\s*(.+)$", title)):
            kind, title = (mk.group(1) if mk.group(1) != "Määräys" else kind), mk.group(2)
        ref = " ".join(x for x in (cfg.get("ref_prefix"), e.get("ref")) if x) or f"{e.get('agency') or cfg['authority']} {fmt_dmy(e['date'])}"
        row = compact({"id": rid, "source": cfg.get("_name") or cfg.get("name"), "authority": e.get("agency") or cfg["authority"], "scope": cfg["scope"],
                       "laji": cfg["laji"], "kind": kind, "ref": ref, "title": title, "date": e["date"], "url": e["url"],
                       "status": "annettu", "keywords": [], "aihealueet": (cfg.get("agency_topics") or {}).get(slug)})
        out[rid] = {**by_id.get(rid, {}), **row}
    for rid, old in by_id.items():
        out.setdefault(rid, old)
    if failures:
        log(f"warn: Finlex {len(failures)}/{len(pages)} listausta epäonnistui: {failures[0][:160]}")
    return list(out.values())


KKO_VL_ITEM = re.compile(r'__documentListItem"')
KKO_VL_HREF = re.compile(r'"href":"(/fi/oikeuskaytanto/korkein-oikeus/valitusluvat/(\d{4})/(\d+))"')
KKO_VL_REF = re.compile(r'"children":"(KKO VL:\d{4}-\d+)"')
KKO_VL_TOKEN = re.compile(r'\["\$","div","([^"]+)",\{"className":"[^"]*__chip|\["\$","\$1","([^"]+)",\{')
KKO_VL_TITLE = re.compile(r"<title>\s*KKO VL:[^|]*\|\s*(\d{1,2}\.\d{1,2}\.\d{4})")
KKO_VL_MAX_DETAIL = 40  # new cards whose date and question are read per run (Finlex is rate limited)


def parse_kko_valitusluvat(h: str) -> list[dict]:
    """The supreme court's leave-to-appeal listing: one entry per card – reference, url and keywords ("Todistelu –
    Hyödyntämiskielto"). The listing has no dates; they come from each card's own page."""
    h2 = h.replace('\\"', '"')
    parts = KKO_VL_ITEM.split(h2)[1:]
    out, seen = [], set()
    for part in parts:
        m = KKO_VL_HREF.search(part)
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        ref = KKO_VL_REF.search(part)
        kws: list[str] = []
        for chip, sub in KKO_VL_TOKEN.findall(part):
            if chip:
                kws.append(chip)
            elif sub and kws:
                kws[-1] = f"{kws[-1]} – {sub}" if " – " not in kws[-1] else f"{kws[-1]}, {sub}"
        out.append({"path": m.group(1), "year": int(m.group(2)), "n": int(m.group(3)),
                    "ref": ref.group(1) if ref else f"KKO VL:{m.group(2)}-{m.group(3)}", "keywords": kws})
    return out


def parse_kko_valituslupa(h: str) -> dict:
    """A card's own page: the date (page title) and the question the leave was granted on."""
    out: dict = {}
    m = KKO_VL_TITLE.search(h)
    if m:
        out["date"] = iso_dmy(m.group(1))
    h2 = h.replace('\\"', '"')
    start = h2.find("Valitusluvat | Korkein oikeus")
    stop = h2.find("Valituslupakortti sisältää")
    window = h2[start:stop] if 0 <= start < stop else h2
    texts = [clean(re.sub(r"(\\+n|\s)+", " ", t)) for t in re.findall(r'"children":"([^"]{40,})"', window)]
    texts = [t for t in texts if not t.startswith(("KKO VL:", "Finlex on", "Voit antaa"))]
    q = next((t for t in texts if re.match(r"(Kysymys|Kysymykset|Onko|Oliko|Voiko|Saako|Miten|Mitä)\b", t)), texts[-1] if texts else None)
    if q:
        out["summary"] = q
    return out


def run_kko_valitusluvat(cfg: dict, prev: list[dict], rows_all: dict, client: Client, defaults: dict) -> list[dict]:
    client.set_delay(FINLEX, 1.5)
    years = [TODAY.year] + ([TODAY.year - 1] if TODAY.month <= 2 else [])
    entries = []
    for y in years:
        entries += parse_kko_valitusluvat(client.text(cfg["url"].format(year=y)))
    if not entries and TODAY.month > 1:
        raise RuntimeError("Finlex: KKO:n valituslupalistalta ei löytynyt yhtään korttia – sivurakenne lienee muuttunut")
    by_id = {r["id"]: r for r in prev}
    out, read = {}, 0
    for e in entries:
        rid = f"kko-vl-{e['year']}-{e['n']}"
        old = by_id.get(rid, {})
        row = {"id": rid, "source": cfg.get("_name") or cfg.get("name"), "authority": cfg["authority"], "scope": cfg["scope"],
               "laji": cfg["laji"], "kind": cfg.get("kind") or "Valituslupa myönnetty", "ref": e["ref"],
               "title": "; ".join(e["keywords"][:4]) or e["ref"], "keywords": e["keywords"], "url": FINLEX + e["path"],
               "status": "vireillä", "date": old.get("date"), "summary": old.get("summary")}
        if not old.get("date") and read < KKO_VL_MAX_DETAIL:
            try:
                row.update({k: v for k, v in parse_kko_valituslupa(client.text(row["url"])).items() if v})
            except Exception as ex:  # noqa: BLE001 – the card is listed again next run
                log(f"warn: KKO VL {e['ref']}: {ex}")
            read += 1
        if row.get("date"):
            out[rid] = compact(row)
    for rid, old in by_id.items():
        out.setdefault(rid, old)
    return list(out.values())


RSS_ITEM = re.compile(r"<item>(.*?)</item>", re.S)


def parse_rss_items(xml: str) -> list[dict]:
    """title, link, date (pubDate) and guid number of each <item> of a WordPress feed."""
    out = []
    for it in RSS_ITEM.findall(xml or ""):
        g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", it, re.S) or [None, None])[1]  # noqa: E731
        title = clean(re.sub(r"<!\[CDATA\[|\]\]>", "", g("title") or ""))
        link = clean(re.sub(r"<!\[CDATA\[|\]\]>", "", g("link") or ""))
        pid = re.search(r"[?&](?:amp;|#038;)?p=(\d+)", g("guid") or "")
        if title and link:
            out.append({"title": title, "url": link, "date": iso_rfc822(g("pubDate")), "pid": pid.group(1) if pid else None})
    return out


def run_rss_rulings(cfg: dict, prev: list[dict], rows_all: dict, client: Client, defaults: dict) -> list[dict]:
    """Decisions a board publishes as a WordPress feed (Kuluttajariitalautakunta, Yhdenvertaisuus- ja
    tasa-arvolautakunta). config: feeds [{url, kind}], id_prefix, authority, aihealueet."""
    by_id = {r["id"]: r for r in prev}
    out, failures = {}, []
    for feed in cfg["feeds"]:
        try:
            items = parse_rss_items(client.text(feed["url"]))
        except Exception as e:  # noqa: BLE001
            failures.append(f"{feed['url']}: {e}")
            continue
        for e in items:
            key = e["pid"] or re.sub(r"\W+", "-", e["url"].rstrip("/").rsplit("/", 1)[-1])[:60]
            rid = f"{cfg['id_prefix']}-{key}"
            row = compact({"id": rid, "source": cfg.get("_name") or cfg.get("name"), "authority": cfg["authority"], "scope": cfg["scope"],
                           "laji": cfg["laji"], "kind": feed.get("kind") or cfg.get("kind") or "Ratkaisu", "ref": None,
                           "title": e["title"], "date": e["date"], "url": e["url"], "status": "annettu", "keywords": []})
            out[rid] = {**by_id.get(rid, {}), **row}
    if failures and len(failures) == len(cfg["feeds"]):
        raise RuntimeError(failures[0])
    for rid, old in by_id.items():
        out.setdefault(rid, old)
    return list(out.values())


# ---------------------------------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------------------------------

RUNNERS = {
    "fiva_tiedotteet": run_fiva_tiedotteet, "fiva_lausuntopyynnot": run_fiva_lausuntopyynnot, "esma_consultations": run_esma,
    "eba_consultations": run_eba, "eiopa_consultations": run_eiopa, "edpb_consultations": run_edpb_consultations,
    "edpb_guidelines": run_edpb_guidelines, "vero_ohjeet": run_vero_ohjeet, "vero_kvl": run_vero_kvl,
    "traficom_maaraykset": run_traficom, "tsv_finlex": run_tsv,
    "eoa_finlex": run_finlex_list, "okv_finlex": run_finlex_list, "tes_finlex": run_finlex_list, "maaraykset_finlex": run_finlex_list,
    "kko_valitusluvat": run_kko_valitusluvat, "kril_ratkaisut": run_rss_rulings, "yvtltk_ratkaisut": run_rss_rulings,
}
# dependents after their providers: lausuntopyynnöt borrow deadlines from tiedotteet, guidelines check open consultations
ORDER = ["fiva_tiedotteet", "fiva_lausuntopyynnot", "esma_consultations", "eba_consultations", "eiopa_consultations",
         "edpb_consultations", "edpb_guidelines", "vero_ohjeet", "vero_kvl", "traficom_maaraykset", "tsv_finlex",
         "eoa_finlex", "okv_finlex", "tes_finlex", "maaraykset_finlex", "kko_valitusluvat", "kril_ratkaisut", "yvtltk_ratkaisut"]


def prune(rows: list[dict], cfg: dict, defaults: dict) -> list[dict]:
    keep_days = int(cfg.get("keep_days", defaults.get("keep_days", 120)))
    grace = int(cfg.get("consultation_grace_days", defaults.get("consultation_grace_days", 30)))
    cut = days_before(TODAY.isoformat(), keep_days)
    cut_dl = days_before(TODAY.isoformat(), grace)
    out = []
    for r in rows:
        # a row stays cached for keep_days from its publication on the site (a closed consultation, a KVL ruling
        # whose antopäivä is older than its publication) so that its detail page is not re-read while it is
        # still in the feed; the builder shows rows by antopäivä and consultations until deadline + grace
        ok = (max(r.get("date") or "", r.get("published") or "") or "9999") >= cut or (r.get("laji") == "kuuleminen" and (r.get("deadline") or "") >= cut_dl)
        if ok:
            out.append(r)
    out.sort(key=lambda r: (r.get("date") or "", r["id"]), reverse=True)
    return out


def main():
    cfg_all = load_yaml(CONFIG_DIR / "toimiala.yaml") or {}
    defaults = cfg_all.get("defaults") or {}
    sources = cfg_all.get("sources") or {}
    old = load_json(OUT, {}) or {}
    rows_all: dict[str, list[dict]] = dict(old.get("rows") or {})
    health: dict[str, dict] = dict(old.get("health") or {})
    client = Client(float(defaults.get("request_interval", 1.0)))
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    enabled = [s for s in ORDER if (sources.get(s) or {}).get("enabled")] + [s for s in sources if s not in ORDER and sources[s].get("enabled")]
    ok_count, failed = 0, []
    for name in enabled:
        cfg = dict(sources[name], _name=name)
        runner = RUNNERS.get(name)
        h = health.setdefault(name, {})
        if not runner:
            h.update({"ok": False, "error": "ei toteutusta (RUNNERS)", "last_fail": now})
            failed.append(name)
            continue
        t0 = time.monotonic()
        r0 = client.requests
        try:
            rows = runner(cfg, rows_all.get(name) or [], rows_all, client, defaults)
            rows = prune(rows, cfg, defaults)
            rows_all[name] = rows
            h.update({"ok": True, "error": None, "last_ok": now, "rows": len(rows), "seconds": round(time.monotonic() - t0, 1),
                      "requests": client.requests - r0})
            ok_count += 1
            log(f"toimiala/{name}: {len(rows)} riviä, {client.requests - r0} pyyntöä, {h['seconds']} s")
        except Exception as e:  # noqa: BLE001
            failed.append(name)
            h.update({"ok": False, "error": f"{type(e).__name__}: {e}"[:300], "last_fail": now, "seconds": round(time.monotonic() - t0, 1)})
            log(f"toimiala/{name}: VIRHE {type(e).__name__}: {e} – edelliset {len(rows_all.get(name) or [])} riviä säilytetään")
    for name in list(rows_all):  # sources switched off keep their last rows in the cache but are marked
        if name not in enabled:
            health.setdefault(name, {})["ok"] = None
    if enabled and ok_count == 0:
        raise RuntimeError(f"toimialakerros: kaikki {len(enabled)} lähdettä epäonnistuivat: {failed}")
    save_json(OUT, {"fetched": now, "rows": rows_all, "health": health}, compact=True)
    total = sum(len(v) for v in rows_all.values())
    log(f"toimiala: {total} riviä {len(enabled) - len(failed)}/{len(enabled)} lähteestä" + (f", epäonnistuneet: {failed}" if failed else "") + f" -> {OUT}")


if __name__ == "__main__":
    main()
