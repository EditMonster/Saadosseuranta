"""Forward-looking EU signals: what the institutions have scheduled, not what they have done.

Seven independent sources, each fetched in its own try/except and recorded in the cache's
``health`` block, so one broken source never hides the others. Everything is open data with no
API key (Commission reuse decision 2011/833/EU, Council 2017 reuse decision, EP CC BY 4.0).

(a) ``forward``  – Register of Commission Documents JSON API (ec.europa.eu/transparency/documents-register):
    * the weekly SEC "Liste des points prévus à l'ordre du jour des prochaines réunions de la Commission"
      (type TENTAT_AGENDA_COM_MEETING, a 2–3 page EN table: meeting date | items | responsible EVP | other
      events, horizon ≈ 5 weeks). Parsed with pdfplumber using the table rules, because the meeting date
      sits vertically centred in a merged cell and ``pdftotext`` loses the row grouping.
    * Annex I of the current Commission Work Programme (new initiatives with an indicative quarter,
      "(säädös, SEUT 114 artikla, Q2 2026)"), Finnish version with the English one aligned for matching.
(b) ``council``  – Publications Office Cellar SPARQL: the Council's planning feed (resource type
    AGENDA_DRAFT_CONSIL = provisional agendas of Coreper I/II, Council configurations, SCA, working parties)
    joined to the dossiers (procedure numbers) and the PROJECTED legal events (planned meeting date and what
    is planned: deliberation, negotiating mandate, A-item adoption …). The Council's own open-data endpoints
    are discontinued and www.consilium.europa.eu is behind Cloudflare; data.consilium PDF links still work.
(c) ``forecasts`` – European Parliament: OEIL's "Forecasts" block per procedure (indicative plenary date,
    scheduled debate/vote, committee vote) via the small per-section PDF (``section=FORECAST``, 35 kB, 0.2 s;
    the HTML page is 5–10× slower) with the HTML as fallback, capped per run and refreshed weekly; plus the
    EP open-data API's draft plenary agendas (``/meetings/{sitting}/foreseen-activities``) for the next
    sittings, which give exact vote/debate dates and Finnish item titles. The EP API returns 429 after a
    burst of ~6 requests, so it is called with one worker and a 3 s gap.
(d) ``infringements`` – the Commission's infringement-decisions search backend (undocumented JSON API,
    ``POST …/api/decisions`` and ``…/api/infringements``, member state FI): formal notices, reasoned
    opinions, referrals and closures, with the directive/regulation concerned guessed from the title.
(e) ``comitology`` – Comitology Register: the daily ``draftMeasures`` CSV export (one row per document
    version: status, status date, opinion, voting sheet) filtered to recent dossiers, the JSON search for
    drafts newer than the CSV, the committee vocabulary, and capped per-document detail calls for the basic
    act's CELEX. Mass decisions (grants, marketing authorisations, pesticide approvals …) are excluded by title.
(f) ``sanctions`` – Cellar: OJ L regulations/decisions whose English title contains "restrictive measures",
    with Finnish title, OJ date, entry into force and the amended base act (= the sanctions regime).
(g) ``eun``  – avoindata.eduskunta.fi (VaskiData): the Government's memos to Parliament on forthcoming Council
    meetings, "EUN n/yyyy vp" ("Euroopan unionin neuvoston kokous D.M.YYYY (<kokoonpano>)"), discovered by
    enumerating the running number. This stands in for the EU Ministerial Committee agendas on
    valtioneuvosto.fi, which is Cloudflare-challenged: same meetings, Finland's position, about a week ahead.

Cache: data/cache/eu_signals.json
  {fetched, health: {source: {ok, n, seconds, error?}}, forward, council, forecasts, infringements,
   comitology, sanctions, eun}
Politeness: ≤ 1 request/s per host (EP API ≤ 1 per 3 s). Steady-state runtime ≈ 1–2 min.
"""
from __future__ import annotations

import csv
import datetime as dt
import html as htmllib
import io
import json
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict

import requests

from common import CACHE_DIR, CONFIG_DIR, SESSION, TODAY, days_ago, get_json, http, load_json, load_yaml, log, post_json, save_json

OUT = CACHE_DIR / "eu_signals.json"
EU_CACHE = CACHE_DIR / "eu.json"
CONFIG = CONFIG_DIR / "eu_signaalit.yaml"

REG = "https://ec.europa.eu/transparency/documents-register/api/"
SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
OEIL = "https://oeil.europarl.europa.eu/oeil/en/procedure-file"
EP = "https://data.europarl.europa.eu/api/v2"
INFR = "https://ec.europa.eu/implementing-eu-law/search-infringement-decisions/api/"
COMREG = "https://ec.europa.eu/transparency/comitology-register/core/api/front"
COMREG_UI = "https://ec.europa.eu/transparency/comitology-register/screen/documents"
VASKI = "https://avoindata.eduskunta.fi/api/v1/tables/VaskiData/rows"
CONSIL_DOC = "https://data.consilium.europa.eu/doc/document"

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LAST: dict[str, float] = {}


# ----------------------------------------------------------------------------- small helpers
def polite(key: str, delay: float = 1.0) -> None:
    """Sleep so that consecutive requests to the same host are at least ``delay`` seconds apart."""
    wait = _LAST.get(key, 0.0) + delay - time.time()
    if wait > 0:
        time.sleep(wait)
    _LAST[key] = time.time()


def iso_or_none(s: str | None) -> str | None:
    s = (s or "")[:10]
    return s if ISO.match(s) and "1990" <= s[:4] <= str(TODAY.year + 3) else None


def dmy_to_iso(s: str | None) -> str | None:
    """'8/07/2026', '08.07.2026' -> '2026-07-08'."""
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


FR_MONTHS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
             "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12}


def fr_date(s: str | None) -> str | None:
    m = re.search(r"(\d{1,2})(?:er)?\s+([A-Za-zéû]+)\s+(\d{4})", s or "")
    if not m or m.group(2).lower() not in FR_MONTHS:
        return None
    try:
        return dt.date(int(m.group(3)), FR_MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
    except ValueError:
        return None


_STOP = {"the", "a", "an", "of", "on", "for", "and", "to", "in", "as", "regards", "eu", "european", "proposal", "regulation",
         "directive", "decision", "amending", "council", "parliament", "commission"}


def norm_title(t: str | None) -> str:
    """Lower-cased ASCII title without punctuation and filler words, for fuzzy matching across sources."""
    t = unicodedata.normalize("NFKD", t or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    words = [w for w in t.split() if w not in _STOP]
    return " ".join(words)


def cellar_pid(ident: str) -> tuple[str, str] | None:
    """'procedure:2025_97' -> ('2025-0097', '2025/0097'); the pid matches fetch_eu's keys."""
    m = re.match(r"procedure:(\d{4})_(\d+)([A-Za-z]*)$", ident or "")
    if not m:
        return None
    n = f"{int(m.group(2)):04d}{m.group(3).upper()}"
    return f"{m.group(1)}-{n}", f"{m.group(1)}/{n}"


def sparql(q: str) -> list[dict]:
    polite("cellar", 1.0)
    r = http("GET", SPARQL, params={"query": q, "format": "application/sparql-results+json"}, timeout=120)
    r.raise_for_status()
    return [{k: v["value"] for k, v in b.items()} for b in r.json()["results"]["bindings"]]


def strip_ns(xml: str) -> ET.Element:
    xml = re.sub(r'\sxmlns(:\w+)?="[^"]*"', "", xml)
    xml = re.sub(r"<(/?)[\w.-]+:", r"<\1", xml)
    xml = re.sub(r"\s[\w.-]+:(\w+=)", r" \1", xml)
    return ET.fromstring(xml)


# ============================================================================= (a) Commission forward look
SEC_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def parse_sec_list(src) -> dict:
    """The weekly 'Liste des points prévus' PDF -> {reference, issued, period, meetings:[{date, place, items, otherEvents}]}.

    Row boundaries are the horizontal rules drawn in the date column, columns the vertical rules; words are
    clustered into lines by their vertical position, '-' lines become sub-items of the preceding item.
    ``src`` is a path or a bytes/BytesIO object."""
    import pdfplumber

    if isinstance(src, (bytes, bytearray)):
        src = io.BytesIO(src)
    out = {"reference": None, "issued": None, "period": None, "meetings": []}
    with pdfplumber.open(src) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1.5, y_tolerance=2)
            text = " ".join(w["text"] for w in words)
            m = re.search(r"SEC\((\d{4})\)\s*(\d+)\s*final", text)
            if m and not out["reference"]:
                out["reference"] = f"SEC({m.group(1)}){m.group(2)}"
            m = re.search(r"Bruxelles, le (\d{1,2}(?:er)? \w+ \d{4})", text)
            if m and not out["issued"]:
                out["issued"] = fr_date(m.group(1)) or m.group(1)
            m = re.search(r"Possible items for Commission agendas (.+?\d{4}\s*[–-]\s*.+?\d{4})\b", text)
            if m and not out["period"]:
                out["period"] = m.group(1)
            vr = sorted({round(r["x0"]) for r in page.rects if r["width"] < 3 and r["height"] > 15})
            if len(vr) < 4:
                continue  # cover page
            x_date, x_items, x_resp, x_other = vr[0], vr[1], vr[2], vr[3]
            hr = sorted({round(r["top"], 1) for r in page.rects
                         if r["height"] < 3 and r["x0"] < x_date + 5 and r["x1"] < x_items + 5 and r["x1"] > x_date + 20})
            if len(hr) < 2:
                continue
            for top, bottom in zip(hr, hr[1:]):
                cell = defaultdict(list)
                for w in words:
                    yc = (w["top"] + w["bottom"]) / 2
                    if not (top <= yc < bottom):
                        continue
                    xc = (w["x0"] + w["x1"]) / 2
                    col = "date" if xc < x_items else "items" if xc < x_resp else "resp" if xc < x_other else "other"
                    cell[col].append(w)
                date = next((SEC_DATE.match(w["text"]) for w in cell["date"] if SEC_DATE.match(w["text"])), None)
                if not date:
                    continue  # header row
                try:
                    iso = dt.date(int(date.group(3)), int(date.group(2)), int(date.group(1))).isoformat()
                except ValueError:
                    continue
                place = "Strasbourg" if any(w["text"].startswith("(Str") for w in cell["date"]) else None

                def lines(ws):
                    res: list = []
                    for w in sorted(ws, key=lambda w: (w["top"], w["x0"])):
                        if res and abs(w["top"] - res[-1][0]) <= 4:
                            res[-1][1].append(w)
                        else:
                            res.append((w["top"], [w]))
                    return [(y, sorted(v, key=lambda w: w["x0"])) for y, v in res]

                resp_lines = {k: " ".join(w["text"] for w in v) for k, v in lines(cell["resp"])}
                items: list[dict] = []
                for y, ws in lines(cell["items"]):
                    t = " ".join(w["text"] for w in ws)
                    resp = next((r for k, r in resp_lines.items() if abs(k - y) <= 4), None)
                    if t.startswith("-"):
                        if items:
                            items[-1].setdefault("subItems", []).append(t.lstrip("- ").strip())
                    elif items and not resp and not items[-1].get("subItems") and abs(ws[0]["x0"] - items[-1]["_x0"]) < 2 and y - items[-1]["_y"] < 16:
                        items[-1]["title"] += " " + t
                    elif items and not resp and items[-1].get("subItems") and ws[0]["x0"] > items[-1]["_x0"] + 5:
                        items[-1]["subItems"][-1] += " " + t
                    else:
                        items.append({"title": t, "responsible": resp.replace(" ", "") if resp else None, "_x0": ws[0]["x0"], "_y": y})
                for it in items:
                    it.pop("_x0", None)
                    it.pop("_y", None)
                    it["norm"] = norm_title(it["title"])
                other = " ".join(" ".join(w["text"] for w in ws) for _, ws in lines(cell["other"])) or None
                mt = next((x for x in out["meetings"] if x["date"] == iso), None)
                if mt:
                    mt["items"] += items
                else:
                    out["meetings"].append({"date": iso, "place": place, "items": items, "otherEvents": other})
    return out


PAREN_END = re.compile(r"\(((?:säädös|muu kuin säädös|legislative|non-legislative|lagstiftning)[^()]*)\)\s*$", re.I)
QUARTER = re.compile(r"\bQ([1-4])\s*(\d{4})\b")
NO_RE = re.compile(r"^(\d{1,3})\.$")
ANNEX2 = re.compile(r"^(Liite|Annex|Bilaga)\s+II\b", re.I)


def parse_cwp_annex(src) -> list[dict]:
    """Annex I of a Commission work programme (FI or EN PDF) -> [{no, objective, section, package, title, kind, detail, quarter}].

    Three table columns (No | policy objective | initiatives); each initiative ends with a parenthesis that
    carries the type, legal basis and quarter. Package headlines are followed by '-' sub-items. Stops at Annex II."""
    import pdfplumber

    if isinstance(src, (bytes, bytearray)):
        src = io.BytesIO(src)
    out: list[dict] = []
    state = {"no": None, "objective": None, "section": None, "buf": "", "package": None}

    def flush(force=False):
        buf = state["buf"].strip()
        if not buf:
            return
        m = PAREN_END.search(buf)
        if not m and not force:
            return
        detail = m.group(1) if m else None
        title = buf[:m.start()].strip() if m else buf
        sub = title.startswith(("-", "–"))
        title = title.lstrip("-– ").strip()
        q = QUARTER.search(detail or "") or QUARTER.search(buf)
        kind = None
        if detail:
            kind = "non-legislative" if re.match(r"muu kuin|non-legislative|icke", detail, re.I) else "legislative"
        title = re.sub(r"^\(Q[1-4] \d{4}\)\s*", "", title)
        if title:
            out.append({"section": state["section"], "no": state["no"], "objective": state["objective"],
                        "package": state["package"] if sub else None, "title": title, "kind": kind,
                        "detail": detail, "quarter": f"{q.group(2)}-Q{q.group(1)}" if q else None})
        state["buf"] = ""

    def lines_of(words, tol=3.0):
        res: list[dict] = []
        for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
            if res and abs(w["top"] - res[-1]["top"]) <= tol:
                res[-1]["words"].append(w)
            else:
                res.append({"top": w["top"], "words": [w]})
        for ln in res:
            ln["words"].sort(key=lambda w: w["x0"])
            ln["text"] = " ".join(w["text"] for w in ln["words"])
            ln["x0"] = ln["words"][0]["x0"]
        return res

    with pdfplumber.open(src) as pdf:
        started = False
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=3, y_tolerance=2)
            vr = sorted({round(r["x0"]) for r in page.rects if r["width"] < 3 and r["height"] > 15})
            if len(vr) < 3:
                continue
            x_obj, x_init = vr[1], vr[2]
            for ln in lines_of(words):
                t = ln["text"]
                if ANNEX2.match(t):
                    flush(force=True)
                    return out
                if re.search(r"\b(Aloitteet|Initiatives|Initiativ)\b", t) and re.search(r"\b(Nro|No|Nr)\b", t):
                    started = True
                    continue
                if not started or ln["top"] > page.height - 40:
                    continue
                if re.match(r"^\d+\s*$", t) or (re.match(r"^\d\s+\S", t) and ln["x0"] < x_obj and len(t) > 60):
                    continue  # footnote
                no_w = [w for w in ln["words"] if w["x0"] < x_obj]
                obj_w = [w for w in ln["words"] if x_obj <= w["x0"] < x_init]
                init_w = [w for w in ln["words"] if w["x0"] >= x_init]
                if no_w and NO_RE.match(no_w[0]["text"]):
                    flush(force=True)
                    state["no"] = NO_RE.match(no_w[0]["text"]).group(1)
                    state["objective"] = re.sub(r"^(\w{1,2}) (\w)", r"\1\2", " ".join(w["text"] for w in obj_w)) or None
                    state["package"] = None
                elif no_w and not obj_w and not init_w:
                    flush(force=True)
                    state["section"] = t
                    continue
                elif no_w and ln["x0"] < x_obj and not NO_RE.match(no_w[0]["text"]):
                    flush(force=True)
                    state["section"] = t
                    continue
                elif obj_w and state["objective"] and not init_w:
                    state["objective"] = (state["objective"] + " " + " ".join(w["text"] for w in obj_w)).strip()
                if not init_w:
                    continue
                it = " ".join(w["text"] for w in init_w)
                if it.startswith(("-", "–")):
                    if state["buf"] and not PAREN_END.search(state["buf"]):
                        state["package"] = state["buf"].strip()
                        state["buf"] = ""
                    else:
                        flush(force=True)
                    state["buf"] = it
                else:
                    if state["buf"] and PAREN_END.search(state["buf"]):
                        flush()
                    state["buf"] = (state["buf"] + " " + it).strip()
                if PAREN_END.search(state["buf"]):
                    flush()
        flush(force=True)
    return out


def align_cwp(fi: list[dict], en: list[dict]) -> list[dict]:
    """Merge the Finnish and English annex parses: same row order when both parsed the same number of rows per
    numbered objective, else English titles are left empty."""
    rows = []
    by_no_en: dict = defaultdict(list)
    for e in en:
        by_no_en[e.get("no")].append(e)
    by_no_fi: dict = defaultdict(list)
    for f in fi:
        by_no_fi[f.get("no")].append(f)
    for f in fi:
        same = by_no_en.get(f.get("no")) or []
        idx = by_no_fi[f.get("no")].index(f)
        e = same[idx] if len(same) == len(by_no_fi[f.get("no")]) and idx < len(same) else None
        rows.append({"no": f.get("no"), "objective": f.get("objective"), "section": f.get("section"), "package": f.get("package"),
                     "title_fi": f["title"], "title_en": e["title"] if e else None, "kind": f.get("kind") or (e or {}).get("kind"),
                     "detail": f.get("detail"), "quarter": f.get("quarter") or (e or {}).get("quarter"),
                     "norm": norm_title(e["title"] if e else f["title"]), "norm_fi": norm_title(f["title"])})
    if not fi:
        for e in en:
            rows.append({"no": e.get("no"), "objective": e.get("objective"), "section": e.get("section"), "package": e.get("package"),
                         "title_fi": None, "title_en": e["title"], "kind": e.get("kind"), "detail": e.get("detail"),
                         "quarter": e.get("quarter"), "norm": norm_title(e["title"]), "norm_fi": None})
    return rows


def reg_search(body: dict, size: int = 10, page: int = 1) -> dict:
    polite("ec", 1.0)
    return post_json(REG + f"groupSearch?size={size}&page={page}", body, timeout=60)


def reg_file(reference: str, ers_id: str) -> bytes:
    polite("ec", 1.0)
    r = http("GET", REG + f"files/{reference}", params={"ersIds": ers_id}, timeout=120)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise RuntimeError(f"asiakirjarekisteri: {reference} ei ole PDF ({r.headers.get('content-type')})")
    return r.content


def _search_body(**kw) -> dict:
    body = {"categories": [], "types": [], "departments": [], "language": "en", "keywordsSearchType": "AT_LEAST_ONE",
            "target": "TITLE_AND_CONTENT", "sortBy": "DOCUMENT_DATE_DESC", "isRegular": True, "keywords": "", "reference": "",
            "page": 1, "dateFrom": "2020-01-01T00:00:00.000Z", "dateTo": (TODAY + dt.timedelta(days=1)).isoformat() + "T00:00:00.000Z"}
    body.update(kw)
    return body


def fetch_forward(cfg: dict, prev: dict) -> dict:
    out = {"lists": [], "cwp": prev.get("cwp")}
    n_lists = int(cfg.get("weekly_lists", 2))
    since = (TODAY - dt.timedelta(days=int(cfg.get("search_days", 60)))).isoformat() + "T00:00:00.000Z"
    res = reg_search(_search_body(types=["TENTAT_AGENDA_COM_MEETING"], dateFrom=since), size=n_lists)
    docs = res.get("documents") or []
    if not docs:
        raise RuntimeError("asiakirjarekisteri: viikkolistoja (TENTAT_AGENDA_COM_MEETING) ei löytynyt")
    old = {x.get("reference"): x for x in prev.get("lists") or []}
    for d in docs[:n_lists]:
        ref = d.get("reference")
        if ref in old and old[ref].get("meetings"):
            out["lists"].append(old[ref])
            continue
        att = next((a for a in d.get("attachments") or [] if (a.get("linguisticVersions") or {}).get("en")), None)
        if not att:
            log(f"warn: {ref}: ei englanninkielistä liitettä")
            continue
        pdf = reg_file(ref, att["linguisticVersions"]["en"]["ersId"])
        parsed = parse_sec_list(pdf)
        parsed["reference"] = parsed.get("reference") or ref
        parsed["date"] = iso_or_none(d.get("date"))
        parsed["url"] = d.get("url") or f"https://ec.europa.eu/transparency/documents-register/detail?ref={ref}"
        parsed["fetched"] = TODAY.isoformat()
        if not parsed["meetings"]:
            raise RuntimeError(f"asiakirjarekisteri: {ref} jäsentyi tyhjäksi – PDF:n rakenne on ehkä muuttunut")
        out["lists"].append(parsed)
        log(f"komissio: {ref} ({parsed.get('period')}) {sum(len(m['items']) for m in parsed['meetings'])} kohtaa {len(parsed['meetings'])} kokouksessa")
    # ---- Commission work programme annex
    cw = cfg.get("cwp") or {}
    if cw.get("enabled", True):
        since = (TODAY - dt.timedelta(days=int(cw.get("max_age_days", 450)))).isoformat() + "T00:00:00.000Z"
        res = reg_search(_search_body(categories=["COM"], keywords=cw.get("keywords") or "Commission work programme",
                                      keywordsSearchType="ALL", target="TITLE_ONLY", dateFrom=since), size=10)
        cand = None
        for d in res.get("documents") or []:
            atts = d.get("attachments") or []
            annex = next((a for a in atts if str(a.get("name", "")).endswith("annex")), None)
            main = next((a for a in atts if str(a.get("name", "")).endswith("mainDocument")), None)
            title = ((main or {}).get("linguisticVersions") or {}).get("en", {}).get("title", "") if main else ""
            if annex and re.search(r"work programme", title, re.I) and not re.search(r"\b(report|evaluation)\b", title[:60], re.I):
                cand = (d, annex, title)
                break
        if cand:
            d, annex, title = cand
            ref = d.get("reference")
            if (out["cwp"] or {}).get("reference") == ref and (out["cwp"] or {}).get("initiatives"):
                pass
            else:
                parsed: dict[str, list] = {}
                for lang in cw.get("languages") or ["fi", "en"]:
                    lv = (annex.get("linguisticVersions") or {}).get(lang)
                    if not lv:
                        continue
                    try:
                        parsed[lang] = parse_cwp_annex(reg_file(ref, lv["ersId"]))
                    except Exception as e:  # noqa: BLE001
                        log(f"warn: työohjelma {ref} ({lang}): {e}")
                rows = align_cwp(parsed.get("fi") or [], parsed.get("en") or [])
                if not rows:
                    raise RuntimeError(f"asiakirjarekisteri: työohjelman {ref} liite jäsentyi tyhjäksi")
                out["cwp"] = {"reference": ref, "date": iso_or_none(d.get("date")), "title": title[:200],
                              "url": d.get("url") or f"https://ec.europa.eu/transparency/documents-register/detail?ref={ref}",
                              "languages": sorted(parsed), "fetched": TODAY.isoformat(), "initiatives": rows}
                log(f"komissio: työohjelma {ref}: {len(rows)} aloitetta ({'/'.join(sorted(parsed))})")
        else:
            log("warn: työohjelmaa ei löytynyt asiakirjarekisteristä")
    return out


# ============================================================================= (b) Council / Coreper agendas
PREFIX = "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\nPREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
Q_AGENDAS = PREFIX + """
SELECT ?id ?date ?title (SAMPLE(?fi) AS ?hasFi) (GROUP_CONCAT(DISTINCT ?pid; separator=" ") AS ?dossiers)
       (GROUP_CONCAT(DISTINCT ?evdate; separator=",") AS ?meeting_dates) WHERE {
  ?w cdm:work_created_by_agent <http://publications.europa.eu/resource/authority/corporate-body/CONSIL> ;
     cdm:work_has_resource-type <http://publications.europa.eu/resource/authority/resource-type/AGENDA_DRAFT_CONSIL> ;
     cdm:work_id_document ?id ; cdm:work_date_document ?date .
  FILTER(STRSTARTS(STR(?id), "consil:") && ?date >= "%(since)s"^^xsd:date)
  OPTIONAL { ?e cdm:expression_belongs_to_work ?w ;
                cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
                cdm:expression_title ?title }
  OPTIONAL { ?ef cdm:expression_belongs_to_work ?w ;
                 cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/FIN> . BIND(1 AS ?fi) }
  OPTIONAL { ?w cdm:work_part_of_dossier ?d . ?d cdm:dossier_identifier ?pid . FILTER(STRSTARTS(STR(?pid), "procedure:")) }
  OPTIONAL { ?w cdm:work_part_of_event_legal ?ev . ?ev cdm:event_legal_date ?evdate }
} GROUP BY ?id ?date ?title ORDER BY DESC(?date)
"""
Q_PROJECTED = PREFIX + """
SELECT DISTINCT ?date ?type ?docref ?pid ?dtitle ?dispatch WHERE {
  ?ev a cdm:event_legal_projected ;
      cdm:event_legal_date ?date ;
      cdm:event_legal_type ?type ;
      cdm:event_legal_has-status_event-status <http://publications.europa.eu/resource/authority/event-status/PROJECTED> ;
      cdm:event_legal_part_of_dossier ?d .
  OPTIONAL { ?ev cdm:event_legal_document_reference ?docref }
  OPTIONAL { ?ev cdm:event_legal_projected_date_dispatch ?dispatch }
  ?d cdm:dossier_identifier ?pid . FILTER(STRSTARTS(STR(?pid), "procedure:"))
  OPTIONAL { ?d cdm:dossier_title ?dtitle . FILTER(LANG(?dtitle) = "en" || LANG(?dtitle) = "") }
  FILTER(?date >= "%(since)s"^^xsd:date)
} ORDER BY ?date ?type
"""


def consil_url(doc_id: str, lang: str = "en") -> str | None:
    """'consil:CM_4574_2026_INIT' / 'CM 4574 2026 INIT' -> data.consilium PDF link."""
    m = re.match(r"(?:consil:)?([A-Z]{2})[ _](\d+)[ _](\d{4})[ _](.+)$", (doc_id or "").strip())
    if not m:
        return None
    return f"{CONSIL_DOC}/{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4).replace('_', '-').replace(' ', '-')}/{lang}/pdf"


def body_of(title: str | None, cfg: dict) -> tuple[str, str]:
    """Cellar's English expression title of the agenda -> (Finnish body name, kind in coreper1|coreper2|council|sca|wp)."""
    t = (title or "").strip()
    elimet = cfg.get("elimet") or {}
    if t in elimet:
        fi = elimet[t]
        return fi, ("coreper1" if fi == "Coreper I" else "coreper2" if fi == "Coreper II" else "sca")
    up = t.upper()
    if "PERMANENT REPRESENTATIVES COMMITTEE" in up:
        return ("Coreper II", "coreper2") if "PART 2" in up else ("Coreper I", "coreper1")
    if "SPECIAL COMMITTEE ON AGRICULTURE" in up:
        return "Maatalouden erityiskomitea", "sca"
    m = re.match(r"(?:COUNCIL OF THE EUROPEAN UNION|CONSIL\w*)\s*\((.+)\)\s*$", t, re.I)
    if m:
        conf = m.group(1).strip()
        return (cfg.get("kokoonpanot") or {}).get(conf) or f"Neuvosto ({conf})", "council"
    return t or "Neuvoston valmisteluelin", "wp"


def council_from_rows(agenda_rows: list[dict], projected_rows: list[dict], cfg: dict) -> dict:
    """Join the agenda documents to the projected events via the document reference ('CM 4574 2026 INIT')."""
    keep_from = (TODAY - dt.timedelta(days=int(cfg.get("keep_days", 7)))).isoformat()
    include_wp = bool(cfg.get("include_working_parties", False))
    projected = []
    seen = set()
    titles: dict[str, str] = {}
    for r in projected_rows:
        p = cellar_pid(r.get("pid", ""))
        d = iso_or_none(r.get("date"))
        if not p or not d:
            continue
        typ = str(r.get("type", "")).split("/")[-1]
        docref = re.sub(r"\s+", " ", r.get("docref") or "").strip() or None
        key = (d, typ, p[0], docref)
        if key in seen:
            continue
        seen.add(key)
        if r.get("dtitle"):
            titles.setdefault(p[0], r["dtitle"][:300])
        projected.append({"date": d, "type": typ, "pid": p[0], "ref": p[1], "docref": docref, "dispatch": iso_or_none(r.get("dispatch"))})
    by_docref: dict = defaultdict(list)
    for ev in projected:
        if ev["docref"]:
            by_docref[ev["docref"].replace(" ", "_")].append(ev)
    agendas = []
    for r in agenda_rows:
        doc_id = r.get("id") or ""
        short = doc_id.split(":", 1)[-1]
        body, kind = body_of(r.get("title"), cfg)
        if kind == "wp" and not include_wp:
            continue
        dates = sorted({iso_or_none(x) for x in (r.get("meeting_dates") or "").split(",") if iso_or_none(x)})
        issued = iso_or_none(r.get("date"))
        if dates and max(dates) < keep_from:
            continue
        if not dates and issued and issued < keep_from:
            continue
        items: dict[str, dict] = {}
        for ev in by_docref.get(short, []):
            it = items.setdefault(ev["pid"], {"pid": ev["pid"], "ref": ev["ref"], "title": titles.get(ev["pid"]), "date": ev["date"], "types": []})
            it["date"] = min(it["date"], ev["date"])
            if ev["type"] not in it["types"]:
                it["types"].append(ev["type"])
        for ident in (r.get("dossiers") or "").split():
            p = cellar_pid(ident)
            if p and p[0] not in items:
                items[p[0]] = {"pid": p[0], "ref": p[1], "title": titles.get(p[0]), "date": dates[0] if dates else None, "types": []}
        agendas.append({"id": short.replace("_", " "), "docId": doc_id, "issued": issued, "body": body, "bodyEn": (r.get("title") or "")[:160],
                        "kind": kind, "meetingDates": dates, "url": consil_url(doc_id, "en"),
                        "urlFi": consil_url(doc_id, "fi") if r.get("hasFi") else None,
                        "items": sorted(items.values(), key=lambda i: (i["date"] or "", i["pid"]))})
    agendas.sort(key=lambda a: (a["meetingDates"][0] if a["meetingDates"] else a["issued"] or "", a["id"]))
    return {"agendas": agendas, "projected": projected, "fetched": TODAY.isoformat()}


def fetch_council(cfg: dict, prev: dict) -> dict:
    since = (TODAY - dt.timedelta(days=int(cfg.get("lookback_days", 14)))).isoformat()
    agenda_rows = sparql(Q_AGENDAS % {"since": since})
    projected_rows = sparql(Q_PROJECTED % {"since": (TODAY - dt.timedelta(days=1)).isoformat()})
    if not agenda_rows and not projected_rows:
        raise RuntimeError("Cellar: neuvoston esityslistoja tai suunniteltuja tapahtumia ei löytynyt – kysely tai aineisto on ehkä muuttunut")
    out = council_from_rows(agenda_rows, projected_rows, cfg)
    log(f"neuvosto: {len(out['agendas'])} esityslistaa ({sum(len(a['items']) for a in out['agendas'])} menettelykohtaa), "
        f"{len(out['projected'])} suunniteltua tapahtumaa")
    return out


# ============================================================================= (c) EP forecasts
OEIL_ROW = re.compile(r"<tr>\s*<td class=\"align-middle\">\s*(\d{2}/\d{2}/\d{4})\s*</td>\s*<td class=\"align-middle\">(.*?)</td>", re.S)
OEIL_STAGE = re.compile(r"Stage reached in procedure\s*</th>\s*<td[^>]*>(.*?)</td>", re.S)


def parse_oeil_html(page: str) -> dict:
    """OEIL procedure page -> {stage, forecasts: [{date, text}]} from the 'Forecasts' table (absent when none)."""
    out: dict = {"stage": None, "forecasts": []}
    m = OEIL_STAGE.search(page)
    if m:
        out["stage"] = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() or None
    m = re.search(r"<h2[^>]*>\s*Forecasts\s*</h2>(.*?)</table>", page, re.S)
    if not m:
        return out
    for d, text in OEIL_ROW.findall(m.group(1)):
        iso = dmy_to_iso(d)
        text = htmllib.unescape(re.sub(r"<[^>]+>", "", text)).strip()
        if iso and text:
            out["forecasts"].append({"date": iso, "text": text})
    return out


def parse_oeil_pdf_text(text: str) -> dict:
    """Text of OEIL's per-section PDF (section=FORECAST): 'Basic information' with the stage, then 'Forecasts'
    lines 'dd/mm/yyyy Subject'."""
    out: dict = {"stage": None, "forecasts": []}
    in_forecasts = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^\d{4}/\d{4}\([A-Z]{3}\)\s+(.+)$", line)
        if m and out["stage"] is None:
            out["stage"] = m.group(1).strip()
            continue
        if re.match(r"^Forecasts$", line):
            in_forecasts = True
            continue
        if in_forecasts:
            m = re.match(r"^(\d{2}/\d{2}/\d{4})\s+(.+)$", line)
            if m:
                iso = dmy_to_iso(m.group(1))
                if iso:
                    out["forecasts"].append({"date": iso, "text": m.group(2).strip()})
            elif out["forecasts"] and not re.match(r"^[A-Z][a-z]+( [a-z]+)*$", line):
                out["forecasts"][-1]["text"] += " " + line  # wrapped subject
            else:
                in_forecasts = False
    return out


def classify_forecasts(forecasts: list[dict], cfg: dict) -> dict:
    """-> {plenary, committeeVote, otherForecasts}: the earliest future-or-today date per class."""
    cls = cfg.get("luokat") or {}
    plen = [k.lower() for k in cls.get("plenary") or ["plenary"]]
    com = [k.lower() for k in cls.get("committee") or ["committee"]]
    committee = None
    votes, plenaries, other = [], [], []
    for f in sorted(forecasts, key=lambda f: f["date"]):
        t = f["text"].lower()
        if any(k in t for k in com):
            committee = committee or f["date"]
        elif any(k in t for k in plen):
            (votes if "vote" in t else plenaries).append(f["date"])
        else:
            other.append(f)
    # a scheduled vote is the date that matters; otherwise the debate / indicative sitting date
    plenary = votes[0] if votes else (plenaries[0] if plenaries else None)
    return {"plenary": plenary, "committeeVote": committee, "otherForecasts": other}


def oeil_fetch(ref: str, delay: float = 1.0) -> dict:
    """Forecast section of one procedure: the small PDF first, the HTML page as fallback."""
    import pdfplumber

    polite("oeil", delay)
    r = SESSION.get(OEIL + "/pdf", params={"reference": ref, "section": "FORECAST"}, timeout=60)
    if r.status_code == 200 and r.content.startswith(b"%PDF"):
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        return parse_oeil_pdf_text(text)
    polite("oeil", delay)
    r = http("GET", OEIL, params={"reference": ref}, timeout=60)
    r.raise_for_status()
    return parse_oeil_html(r.text)


def ep_get(path: str, params: dict | None, delay: float) -> dict | None:
    """EP open-data API with one slow worker; a 429 is retried once after a minute, then given up."""
    for attempt in range(2):
        polite("ep", delay)
        r = SESSION.get(f"{EP}{path}", params={"format": "application/ld+json", **(params or {})}, timeout=90)
        if r.status_code == 429:
            log("warn: EP API 429 – odotetaan 60 s")
            time.sleep(60)
            continue
        if r.status_code == 204:
            return None
        r.raise_for_status()
        return r.json()
    raise RuntimeError("EP API: nopeusraja (429) kahdesti peräkkäin")


def parse_ep_foreseen(data: dict, sitting: str) -> list[dict]:
    """foreseen-activities of one sitting -> [{pid, date, type, point, title_fi, title_en, sitting}] for procedure items."""
    out = []
    for a in (data or {}).get("data") or []:
        procs = [p for p in (a.get("inverse_was_scheduled_in") or []) if "/proc/" in str(p)]
        if not procs:
            continue
        at = str(a.get("had_activity_type") or "")
        typ = "vote" if at.endswith("PLENARY_VOTE") else "debate" if at.endswith("PLENARY_DEBATE") else None
        if not typ:
            continue
        lab = a.get("activity_label") or {}
        for p in procs:
            pid = str(p).rsplit("/", 1)[-1]
            out.append({"pid": pid, "date": iso_or_none(a.get("activity_date")), "type": typ, "point": a.get("notation_agendaPoint"),
                        "title_fi": (lab.get("fi") or "")[:250] if isinstance(lab, dict) else None,
                        "title_en": (lab.get("en") or "")[:250] if isinstance(lab, dict) else None, "sitting": sitting})
    return out


def pending_procedures(eu: dict) -> list[dict]:
    """Procedures in data/cache/eu.json that have no adopted act yet (fetch_eu: cellar.acts empty, final false)."""
    out = []
    for pid, rec in eu.items():
        if rec.get("final") or (rec.get("cellar") or {}).get("acts"):
            continue
        out.append({"pid": pid, "ref": rec.get("ref") or pid, "fetched": rec.get("fetched") or ""})
    return out


def fetch_forecasts(cfg: dict, prev: dict) -> dict:
    eu = (load_json(EU_CACHE, {}) or {}).get("items") or {}
    if not eu:
        raise RuntimeError("eu.json puuttuu – EP-ennusteita ei voi kohdentaa")
    pending = pending_procedures(eu)
    pending_ids = {p["pid"] for p in pending}
    watch = load_yaml(CONFIG_DIR / "eu_watchlist.yaml") or {}
    watched = set()
    for ref in watch.get("procedures") or []:
        m = re.match(r"(\d{4})/(\d{4})", str(ref))
        if m:
            watched.add(f"{m.group(1)}-{m.group(2)}")
    old = {k: v for k, v in (prev.get("items") or {}).items() if k in pending_ids}
    refresh = int(cfg.get("refresh_days", 7))
    w_refresh = int(cfg.get("watchlist_refresh_days", 1))
    todo = []
    for p in pending:
        rec = old.get(p["pid"])
        age = days_ago(rec.get("fetched")) if rec else None
        limit = w_refresh if p["pid"] in watched else refresh
        if rec and age is not None and age < limit:
            continue
        prio = 0 if p["pid"] in watched else 1 if not rec else 2
        todo.append((prio, -(int(p["fetched"].replace("-", "") or 0)), p))
    todo.sort(key=lambda t: (t[0], t[1], t[2]["pid"]))
    cap = int(cfg.get("max_per_run", 50))
    delay = float(cfg.get("delay_seconds", 1.0))
    done = failed = 0
    for _, _, p in todo[:cap]:
        try:
            parsed = oeil_fetch(p["ref"], delay)
        except Exception as e:  # noqa: BLE001
            failed += 1
            log(f"warn: OEIL {p['ref']}: {e}")
            if failed >= 5 and done == 0:
                raise RuntimeError(f"OEIL: {failed} hakua peräkkäin epäonnistui") from e
            continue
        cls = classify_forecasts(parsed["forecasts"], cfg)
        old[p["pid"]] = {"ref": p["ref"], "fetched": TODAY.isoformat(), "stage": parsed.get("stage"), "plenary": cls["plenary"],
                         "committeeVote": cls["committeeVote"], "forecasts": parsed["forecasts"]}
        done += 1
    log(f"ennusteet: OEIL {done} haettu ({len(todo) - min(len(todo), cap)} jonossa), {failed} epäonnistui, "
        f"{sum(1 for v in old.values() if v.get('plenary') or v.get('committeeVote'))}/{len(old)} menettelyllä ennuste")
    out = {"items": old, "epAgenda": prev.get("epAgenda") or {}, "fetched": TODAY.isoformat()}
    # ---- EP draft plenary agendas (exact dates for the next sittings)
    if cfg.get("ep_agenda", True):
        try:
            n_sit = int(cfg.get("ep_agenda_sittings", 4))
            ep_delay = float(cfg.get("ep_delay_seconds", 3.0))
            sittings = []
            for year in (TODAY.year, TODAY.year + 1):
                data = ep_get("/meetings", {"year": year, "limit": 500}, ep_delay) or {}
                sittings += sorted((x.get("activity_id") or "", x.get("activity_date") or "") for x in data.get("data") or []
                                   if (x.get("activity_date") or "") >= TODAY.isoformat() and str(x.get("activity_id", "")).startswith("MTG-PL-"))
                if len(sittings) >= n_sit or TODAY.month < 11:
                    break
            sittings = sittings[:n_sit]
            agenda_items: dict[str, list] = {}
            errors = []
            for sid, _ in sittings:
                prev_sit = (out["epAgenda"].get("sittings") or {}).get(sid)
                if prev_sit and prev_sit.get("fetched") == TODAY.isoformat():
                    rows = prev_sit.get("items") or []
                else:
                    try:
                        data = ep_get(f"/meetings/{sid}/foreseen-activities", None, ep_delay)
                        rows = parse_ep_foreseen(data, sid) if data else []
                    except Exception as e:  # noqa: BLE001  (a sitting without a draft agenda yet answers 500)
                        errors.append(f"{sid}: {str(e)[:80]}")
                        rows = (prev_sit or {}).get("items") or []
                out["epAgenda"].setdefault("sittings", {})[sid] = {"fetched": TODAY.isoformat(), "items": [r for r in rows if r["pid"] in eu]}
                for r in out["epAgenda"]["sittings"][sid]["items"]:
                    agenda_items.setdefault(r["pid"], []).append(r)
            out["epAgenda"]["sittings"] = {k: v for k, v in out["epAgenda"]["sittings"].items() if k in {s for s, _ in sittings}}
            out["epAgenda"]["items"] = agenda_items
            out["epAgenda"]["fetched"] = TODAY.isoformat()
            out["epAgenda"]["error"] = "; ".join(errors)[:300] if errors else None
            log(f"ennusteet: EP:n esityslistat {len(sittings) - len(errors)}/{len(sittings)} istuntopäivää, {len(agenda_items)} menettelyä"
                + (f" (virheet: {len(errors)})" if errors else ""))
        except Exception as e:  # noqa: BLE001
            log(f"warn: EP:n esityslistat: {e}")
            out["epAgenda"]["error"] = str(e)[:200]
    return out


# ============================================================================= (d) Infringements against Finland
ACT_RE = re.compile(r"\b(Directive|Regulation|Decision)\s*\(?\s*(?:EU|EC|EEC|Euratom)?\s*\)?\s*(?:No\.?\s*)?(\d{2,4})/(\d{1,4})(?:/(EC|EEC|EU|Euratom))?", re.I)
CELEX_RE = re.compile(r"\b3(\d{4})([LRD])(\d{4})\b")


def act_from_title(title: str) -> tuple[str | None, str | None]:
    """'… Directive (EU) 2024/1788 …' -> ('32024L1788', 'Directive (EU) 2024/1788'); None when nothing is cited."""
    m = CELEX_RE.search(title or "")
    if m:
        return m.group(0), m.group(0)
    m = ACT_RE.search(title or "")
    if not m:
        return None, None
    kind = {"directive": "L", "regulation": "R", "decision": "D"}[m.group(1).lower()]
    ref = m.group(0).strip()
    if "(" in ref and ")" not in ref:
        ref = ref.replace("(", "").replace("  ", " ")
    a, b = int(m.group(2)), int(m.group(3))
    if a >= 1950:
        year, num = a, b
    elif b >= 1950:
        year, num = b, a
    elif a < 100:
        year, num = 1900 + a, b
    else:
        return None, ref
    return f"3{year}{kind}{num:04d}", ref


def stage_fi(decision_type: str | None, cfg: dict) -> str:
    t = (decision_type or "").strip()
    for prefix, fi in (cfg.get("vaiheet") or {}).items():
        if t.lower().startswith(prefix.lower()):
            return fi
    return t.lower() or "päätös"


def infringement_cases(decisions: list[dict], cases: list[dict], cfg: dict) -> dict:
    """Merge the per-decision rows and the per-case rows into {number: case} with a dated decision history."""
    out: dict[str, dict] = {}

    def case_of(r: dict) -> dict:
        num = (r.get("infringementNumber") or "").strip()
        c = out.setdefault(num, {"number": num, "title": (r.get("title") or "").strip(), "caseType": r.get("caseType"),
                                 "leadDg": r.get("leadDg"), "policyAreas": [], "active": None, "nonCommunication": None, "decisions": []})
        if r.get("activeInfringementCase") in ("Yes", "No"):
            c["active"] = r["activeInfringementCase"] == "Yes"
        if r.get("nonCommunicationCase") in ("Yes", "No"):
            c["nonCommunication"] = r["nonCommunicationCase"] == "Yes"
        for pa in r.get("policyAreas") or []:
            if pa and pa not in c["policyAreas"]:
                c["policyAreas"].append(pa)
        if r.get("caseType") and (not c["caseType"] or len(r["caseType"]) > len(c["caseType"])):
            c["caseType"] = r["caseType"]
        return c

    def add_decision(c: dict, d: dict):
        date = dmy_to_iso(d.get("decisionDate"))
        typ = (d.get("decisionType") or "").strip()
        if not date or any(x["date"] == date and x["type"] == typ for x in c["decisions"]):
            return
        c["decisions"].append({"date": date, "type": typ, "stage": stage_fi(typ, cfg), "memoUrl": d.get("memoURL"),
                               "pressUrl": d.get("pressReleaseURL") if str(d.get("pressReleaseURL") or "").startswith("http") else None,
                               "curia": d.get("normalCuriaReference"), "curiaUrl": d.get("normalCuriaReferenceURL")})

    for r in decisions:
        if not r.get("infringementNumber"):
            continue
        add_decision(case_of(r), r)
    for r in cases:
        if not r.get("infringementNumber"):
            continue
        c = case_of(r)
        for d in r.get("decisions") or []:
            add_decision(c, d)
    for c in out.values():
        c["decisions"].sort(key=lambda d: (d["date"], d["type"]))
        c["celex"], c["actRef"] = act_from_title(c["title"])
        c["lastDecision"] = c["decisions"][-1]["date"] if c["decisions"] else None
        if c["active"] is None:
            c["active"] = not any(d["stage"].startswith("asian lopettaminen") for d in c["decisions"][-1:])
    return out


def infr_post(path: str, body: dict) -> list[dict]:
    rows: list[dict] = []
    for page in range(20):
        polite("ec", 1.0)
        data = post_json(INFR + path, {**body, "page": page, "size": 200}, timeout=90)
        recs = data.get("records") or []
        rows.extend(recs)
        total = int(data.get("totalRows") or 0)
        if len(rows) >= total or not recs:
            break
    return rows


def fetch_infringements(cfg: dict, prev: dict) -> dict:
    ms = cfg.get("member_state", "FI")
    keep = int(cfg.get("keep_days", 400))
    since = (TODAY - dt.timedelta(days=keep)).strftime("%d/%m/%Y")
    decisions = infr_post("decisions", {"memberState": ms, "decisionDateFrom": since, "decisionDateTo": TODAY.strftime("%d/%m/%Y"),
                                        "orderBy": "decisionDate", "order": "DESC"})
    cases = infr_post("infringements", {"memberState": ms, "activeCase": True})
    if not decisions and not cases:
        raise RuntimeError("rikkomusmenettelyt: rajapinta palautti tyhjää – osoite tai parametrit ovat ehkä muuttuneet")
    merged = infringement_cases(decisions, cases, cfg)
    cutoff = (TODAY - dt.timedelta(days=keep)).isoformat()
    merged = {k: v for k, v in merged.items() if v["active"] or (v["lastDecision"] or "") >= cutoff}
    log(f"rikkomukset: {len(decisions)} päätöstä {keep} pv, {len(cases)} avointa asiaa -> {len(merged)} asiaa")
    return {"cases": merged, "fetched": TODAY.isoformat(), "memberState": ms}


# ============================================================================= (e) Comitology (implementing acts)
def comreg_csv_rows(text: str, cutoff: str) -> dict[str, dict]:
    """draftMeasures CSV (';'-separated, one row per document version × attachment) -> {D-number: record} for
    dossiers started or updated since ``cutoff``. The version history gives the timeline: submission, opinion
    (vote) and adoption are separate rows with their own status date."""
    docs: dict[str, dict] = {}
    # pass 1: which documents have anything newer than the cutoff; pass 2: their whole version history
    wanted: set[str] = set()
    for r in csv.DictReader(io.StringIO(text), delimiter=";"):
        m = re.match(r"(D\d+)", (r.get("Document") or "").strip())
        start = iso_or_none(r.get("Dossier start date"))
        sdate = iso_or_none(r.get("Status Date"))
        if m and ((start and start >= cutoff) or (sdate and sdate >= cutoff)):
            wanted.add(m.group(1))
    for r in csv.DictReader(io.StringIO(text), delimiter=";"):
        doc = (r.get("Document") or "").strip()
        m = re.match(r"(D\d+)(?:/(\d+))?", doc)
        if not m or m.group(1) not in wanted:
            continue
        start = iso_or_none(r.get("Dossier start date"))
        sdate = iso_or_none(r.get("Status Date"))
        ref = m.group(1)
        rec = docs.setdefault(ref, {"ref": ref, "title": "", "committeeCode": (r.get("Committee Code") or "").strip() or None,
                                    "meetingCode": (r.get("Dossier") or "").strip() or None, "meetingStart": start,
                                    "meetingEnd": iso_or_none(r.get("Dossier end date")),
                                    "basicAct": {"title": re.sub(r"Â?\xa0", " ", r.get("Basic legal act") or "").strip()[:300] or None, "celex": None, "code": None},
                                    "procedure": (r.get("Procedure") or "").strip() or None, "dg": (r.get("Service") or "").strip() or None,
                                    "history": [], "url": None, "version": None})
        title = re.sub(r"\s+", " ", (r.get("Document title") or "")).strip()
        title = re.sub(r"^(?:EN\s+\d+\s+EN\s+|EN\s*-\s*|Draft\s*(?:to|-)\s*(?:CID\s*-\s*)?)", "", title).strip()
        if title and not re.match(r"^(annex|annexe|annexes|liite|draft annex|corrigendum)\b", title, re.I) and len(title) > len(rec["title"]):
            rec["title"] = title
        ver = int(m.group(2) or 0)
        h = {"status": (r.get("Status") or "").strip(), "date": sdate, "opinion": (r.get("Opinion") or "").strip() or None,
             "sheet": (r.get("Voting Sheet") or "").strip() or None, "version": ver}
        if h["status"] and h not in rec["history"]:
            rec["history"].append(h)
        if ver >= (rec["version"] or 0):
            rec["version"] = ver
            if r.get("URL"):
                rec["url"] = r["URL"].strip()
        if start and (not rec["meetingStart"] or start > rec["meetingStart"]):
            rec["meetingStart"], rec["meetingEnd"] = start, iso_or_none(r.get("Dossier end date"))
    for rec in docs.values():
        rec["history"].sort(key=lambda h: ((h["date"] or ""), h["version"]))
        comreg_summarise(rec)
    return docs


OPINION_STATUSES = {"Positive opinion", "Adoption", "Opinion of the committee (if necessary by vote)", "Cmte fav. opinion and measure sent to EP and Council",
                    "No opinion", "Negative opinion", "No opinion of the Appeal Committee"}
ADOPTED_STATUSES = {"Adopted by Commission", "Act adopted remains in Force"}


def comreg_summarise(rec: dict) -> None:
    """Derive status / voteDate / voteResult / adoptionDate from the version history."""
    hist = rec.get("history") or []
    last = hist[-1] if hist else {}
    rec["status"] = last.get("status") or rec.get("status")
    rec["statusDate"] = last.get("date") or rec.get("statusDate")
    vote = next((h for h in hist if h.get("opinion") or h["status"] in OPINION_STATUSES), None)
    rec["voteDate"] = vote["date"] if vote else None
    rec["voteResult"] = (vote.get("opinion") or vote["status"]) if vote else None
    rec["votingSheet"] = vote.get("sheet") if vote else None
    adopted = next((h for h in hist if h["status"] in ADOPTED_STATUSES), None)
    rec["adoptionDate"] = adopted["date"] if adopted else None
    rec["submitted"] = next((h["date"] for h in hist if h["date"]), None) or rec.get("meetingStart")


def comreg_search(type_id: int, since_iso: str, size: int = 100) -> list[dict]:
    rows: list[dict] = []
    for page in range(5):
        polite("ec", 1.0)
        data = post_json(f"{COMREG}/documents/search?page={page}&size={size}&sort=creationDate,desc",
                         {"documentTypeId": type_id, "documentStartDate": f"{since_iso}T00:00:00Z",
                          "documentEndDate": f"{(TODAY + dt.timedelta(days=1)).isoformat()}T23:59:59Z", "reset": False}, timeout=120)
        rows.extend(data.get("content") or [])
        if data.get("last", True) or not data.get("content"):
            break
    return rows


def comreg_detail(rec: dict, data: dict) -> None:
    """Fill a record from GET /documents/{reference}/{version}: basic act CELEX, DG code, stage, status."""
    ia = data.get("implementingAct") or {}
    ba = ia.get("basicActId") or {}
    if ba:
        rec["basicAct"] = {"title": (ba.get("title") or rec["basicAct"].get("title") or "")[:300] or None, "celex": ba.get("celexNumber"), "code": ba.get("code")}
    mt = data.get("meeting") or {}
    if (mt.get("dg") or {}).get("code"):
        rec["dgCode"] = mt["dg"]["code"]
    st = ia.get("stage") or {}
    if st.get("stage"):
        rec["stage"] = str(st["stage"]).replace("label.", "")
        rec["stageDate"] = iso_or_none(st.get("stageDate"))
    if (ia.get("legislativeProcedure") or {}).get("article") and not rec.get("procedure"):
        rec["procedure"] = ia["legislativeProcedure"]["article"]
    if data.get("documentStatus", {}).get("description"):
        rec["docStatus"] = str(data["documentStatus"]["description"]).replace("label.", "")
    if not rec.get("title") and data.get("title"):
        rec["title"] = re.sub(r"\s+", " ", data["title"]).strip()
    rec["detailFetched"] = TODAY.isoformat()


def excluded_title(title: str, patterns: list[str]) -> bool:
    return any(re.search(p, title or "", re.I) for p in patterns or [])


def fetch_comitology(cfg: dict, prev: dict) -> dict:
    days = int(cfg.get("days", 120))
    cutoff = (TODAY - dt.timedelta(days=days)).isoformat()
    patterns = cfg.get("exclude_title_patterns") or []
    now = dt.datetime.now(dt.timezone.utc)
    out = {"documents": {}, "committees": prev.get("committees") or {}, "committeesFetched": prev.get("committeesFetched"),
           "csvFetched": prev.get("csvFetched"), "fetched": TODAY.isoformat()}
    old = prev.get("documents") or {}
    # daily CSV with the status history
    csv_age_h = None
    if out["csvFetched"]:
        try:
            csv_age_h = (now - dt.datetime.fromisoformat(out["csvFetched"].replace("Z", "+00:00"))).total_seconds() / 3600
        except ValueError:
            csv_age_h = None
    docs: dict[str, dict] = {}
    if csv_age_h is None or csv_age_h >= float(cfg.get("csv_refresh_hours", 20)):
        polite("ec", 1.0)
        t0 = time.time()
        r = http("GET", f"{COMREG}/datasets/draftMeasures", params={"lang": "en"}, timeout=600, retries=2)
        r.raise_for_status()
        text = r.content.decode("utf-8-sig", errors="replace")
        docs = comreg_csv_rows(text, cutoff)
        if len(docs) < 20:
            raise RuntimeError(f"komitologia: CSV-aineistosta löytyi vain {len(docs)} tuoretta luonnosta – muoto on ehkä muuttunut")
        out["csvFetched"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        log(f"komitologia: CSV {len(r.content) // 1024} kB {time.time() - t0:.0f} s -> {len(docs)} luonnosta {days} pv")
        del text
    else:
        docs = {k: v for k, v in old.items() if (v.get("statusDate") or v.get("meetingStart") or "") >= cutoff}
    # drafts created since the CSV snapshot (the JSON search; same shape as the register's list view)
    since = max(cutoff, ((out["csvFetched"] or TODAY.isoformat())[:10]))
    since = (dt.date.fromisoformat(since) - dt.timedelta(days=1)).isoformat()
    try:
        fresh = comreg_search(2, since)
    except Exception as e:  # noqa: BLE001
        log(f"warn: komitologia haku: {e}")
        fresh = []
    added = 0
    for d in fresh:
        ref = f"D{d.get('documentReference')}"
        if ref in docs or not d.get("documentReference"):
            continue
        created = iso_or_none(d.get("creationDate"))
        docs[ref] = {"ref": ref, "version": d.get("version"), "title": re.sub(r"\s+", " ", d.get("title") or "").strip(),
                     "committeeCode": d.get("committeeCode"), "committee": d.get("committeeTitle"), "meetingCode": d.get("meetingCode"),
                     "meetingStart": iso_or_none(d.get("meetingStartDate")), "meetingEnd": iso_or_none(d.get("meetingEndDate")),
                     "basicAct": {"title": None, "celex": None, "code": None}, "procedure": None, "dg": None,
                     "history": [{"status": "Draft Implementing Act submitted to Committee", "date": created, "opinion": None, "sheet": None, "version": d.get("version") or 1}],
                     "url": f"{COMREG_UI}/{d.get('documentReference')}/{d.get('version') or 1}/consult"}
        comreg_summarise(docs[ref])
        added += 1
    # drop excluded titles; committee vocabulary (code -> title, DG) weekly or when a code is unknown
    for ref, rec in list(docs.items()):
        if excluded_title(rec.get("title"), patterns):
            del docs[ref]
    used = {r.get("committeeCode") for r in docs.values() if r.get("committeeCode") and not r.get("committee")}
    if used - set(out["committees"]) or (days_ago(out["committeesFetched"]) or 99) >= 7:
        polite("ec", 1.0)
        try:
            data = post_json(f"{COMREG}/committees/search?page=0&size=2000", {}, timeout=90)
            rows = data.get("content") if isinstance(data, dict) else data
            if rows:
                out["committees"] = {r["committeeCode"]: {"title": (r.get("committeeTitle") or "")[:140], "dg": r.get("dgCode")} for r in rows if r.get("committeeCode")}
                out["committeesFetched"] = TODAY.isoformat()
        except Exception as e:  # noqa: BLE001
            log(f"warn: komitologia komiteat: {e}")
    # carry over details from the previous cache
    for ref, rec in docs.items():
        o = old.get(ref) or {}
        for k in ("dgCode", "stage", "stageDate", "docStatus", "detailFetched", "detailError"):
            if o.get(k) and not rec.get(k):
                rec[k] = o[k]
        if (o.get("basicAct") or {}).get("celex") and not rec["basicAct"].get("celex"):
            rec["basicAct"] = o["basicAct"]
        if not rec.get("committee"):
            rec["committee"] = (out["committees"].get(rec.get("committeeCode") or "") or {}).get("title")
        if not rec.get("dgCode"):
            rec["dgCode"] = (out["committees"].get(rec.get("committeeCode") or "") or {}).get("dg")
        if not rec.get("url"):
            rec["url"] = f"{COMREG_UI}/{ref[1:]}/{rec.get('version') or 1}/consult"
    # capped detail calls for the basic act's CELEX, newest first
    todo = sorted((r for r in docs.values() if not r["basicAct"].get("celex") and not r.get("detailFetched")),
                  key=lambda r: r.get("statusDate") or "", reverse=True)[:int(cfg.get("max_detail_per_run", 40))]
    got = 0
    for rec in todo:
        polite("ec", 1.0)
        try:
            data = get_json(f"{COMREG}/documents/{rec['ref'][1:]}/{rec.get('version') or 1}", timeout=60)
            comreg_detail(rec, data)
            got += 1
        except Exception as e:  # noqa: BLE001
            rec["detailFetched"] = TODAY.isoformat()
            rec["detailError"] = str(e)[:120]
    log(f"komitologia: {len(docs)} täytäntöönpanosäädösluonnosta ({added} uutta haulla, {got} tarkennettu, "
        f"{sum(1 for r in docs.values() if r.get('voteDate'))} äänestetty)")
    # compact: the summary fields carry the timeline, the history and derivable fields are dropped
    for rec in docs.values():
        rec.pop("history", None)
        rec.pop("url", None)
        rec.pop("docStatus", None)
        rec["title"] = (rec.get("title") or "")[:300]
        if rec.get("committeeCode") in out["committees"]:
            rec.pop("committee", None)  # the builder resolves it from the vocabulary
        elif rec.get("committee"):
            rec["committee"] = rec["committee"][:140]
        if (rec.get("basicAct") or {}).get("title"):
            rec["basicAct"]["title"] = rec["basicAct"]["title"][:150]
    used = {r.get("committeeCode") for r in docs.values()}
    out["committees"] = {k: v for k, v in out["committees"].items() if k in used}
    out["documents"] = docs
    return out


# ============================================================================= (f) Sanctions via Cellar
Q_SANCTIONS = PREFIX + """
SELECT ?celex ?oj ?eif ?inforce ?title_fi ?title_en (GROUP_CONCAT(DISTINCT ?amended; separator=" ") AS ?amends) WHERE {
  ?w cdm:resource_legal_id_celex ?celex ; cdm:official-journal-act_date_publication ?oj .
  FILTER(?oj >= "%(since)s"^^xsd:date)
  FILTER(REGEX(STR(?celex), "^3\\\\d{4}[RD]\\\\d{4}$"))
  ?e cdm:expression_belongs_to_work ?w ;
     cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
     cdm:expression_title ?title_en .
  FILTER(CONTAINS(LCASE(STR(?title_en)), "restrictive measures"))
  OPTIONAL { ?w cdm:resource_legal_date_entry-into-force ?eif }
  OPTIONAL { ?w cdm:resource_legal_in-force ?inforce }
  OPTIONAL { ?ef cdm:expression_belongs_to_work ?w ;
                 cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/FIN> ;
                 cdm:expression_title ?title_fi }
  OPTIONAL { ?w cdm:resource_legal_amends_resource_legal ?a . ?a cdm:resource_legal_id_celex ?amended }
} GROUP BY ?celex ?oj ?eif ?inforce ?title_fi ?title_en ORDER BY DESC(?oj) ?celex
"""


def regime_of(act: dict, regimes: list[dict]) -> str:
    amends = set(act.get("amends") or [])
    for r in regimes or []:
        if amends & set(r.get("celex") or []):
            return r["label"]
    text = f"{act.get('title_en') or ''} {act.get('title_fi') or ''}".lower()
    for r in regimes or []:
        if any(k.lower() in text for k in r.get("keywords") or []):
            return r["label"]
    return "muu"


def parse_sanctions_rows(rows: list[dict], regimes: list[dict]) -> list[dict]:
    acts: dict[str, dict] = {}
    for r in rows:
        celex = r.get("celex")
        if not celex or not re.fullmatch(r"3\d{4}[RD]\d{4}", celex):
            continue
        a = acts.setdefault(celex, {"celex": celex, "oj": iso_or_none(r.get("oj")), "eif": iso_or_none(r.get("eif")), "inForce": r.get("inforce"),
                                    "title_fi": None, "title_en": None, "amends": []})
        a["title_fi"] = a["title_fi"] or (r.get("title_fi") or "").replace("\xa0", " ").strip() or None
        a["title_en"] = a["title_en"] or (r.get("title_en") or "").replace("\xa0", " ").strip() or None
        a["eif"] = a["eif"] or iso_or_none(r.get("eif"))
        for x in (r.get("amends") or "").split():
            if re.fullmatch(r"3\d{4}[RDE]\d{4}", x) and x not in a["amends"]:
                a["amends"].append(x)
    for a in acts.values():
        a["regime"] = regime_of(a, regimes)
    return sorted(acts.values(), key=lambda a: (a["oj"] or "", a["celex"]), reverse=True)


def fetch_sanctions(cfg: dict, prev: dict) -> dict:
    since = (TODAY - dt.timedelta(days=int(cfg.get("days", 60)))).isoformat()
    rows = sparql(Q_SANCTIONS % {"since": since})
    acts = parse_sanctions_rows(rows, cfg.get("regimes") or [])
    if not acts:
        raise RuntimeError("Cellar: pakotesäädöksiä ei löytynyt – kysely tai aineisto on ehkä muuttunut")
    keep = (TODAY - dt.timedelta(days=int(cfg.get("keep_days", 120)))).isoformat()
    merged = {a["celex"]: a for a in prev.get("acts") or [] if (a.get("oj") or "") >= keep}
    for a in acts:
        merged[a["celex"]] = a
    out = sorted(merged.values(), key=lambda a: (a["oj"] or "", a["celex"]), reverse=True)
    log(f"pakotteet: {len(acts)} säädöstä {cfg.get('days', 60)} pv, yhteensä {len(out)} välimuistissa")
    return {"acts": out, "fetched": TODAY.isoformat()}


# ============================================================================= (g) EUN documents (eduskunta)
EUN_RANGE = re.compile(r"(\d{1,2})\.(?:\s*[-–]\s*(\d{1,2})\.)?(\d{1,2})\.(\d{4})")
EUN_RANGE_X = re.compile(r"(\d{1,2})\.(\d{1,2})\.\s*[-–]\s*(\d{1,2})\.(\d{1,2})\.(\d{4})")


def meeting_from_title(title: str) -> dict:
    """'Euroopan unionin neuvoston kokous 24.2.2026 (Yleisten asioiden neuvosto)' -> {council, date, end}.
    Also 'Epävirallinen energiaministerikokous 28.–29.9.2026', 'Eurooppa-neuvosto 15.–16.10.2026'."""
    t = (title or "").strip()
    council = None
    m = re.search(r"\(([^()]+)\)\s*$", t)
    if m:
        council = m.group(1).strip()
    date = end = None
    mx = EUN_RANGE_X.search(t)
    if mx:
        try:
            y = int(mx.group(5))
            date = dt.date(y, int(mx.group(2)), int(mx.group(1))).isoformat()
            end = dt.date(y, int(mx.group(4)), int(mx.group(3))).isoformat()
        except ValueError:
            date = end = None
    if not date:
        m2 = EUN_RANGE.search(t)
        if m2:
            try:
                y, mo = int(m2.group(4)), int(m2.group(3))
                date = dt.date(y, mo, int(m2.group(1))).isoformat()
                end = dt.date(y, mo, int(m2.group(2))).isoformat() if m2.group(2) else None
            except ValueError:
                date = end = None
    if not council:
        head = re.split(r"\s\d{1,2}\.", t, maxsplit=1)[0]
        head = re.sub(r"^Euroopan unionin neuvoston kokous\s*", "", head).strip(" ,;:")
        head = re.sub(r"\s+kokous$", "", head).strip()
        head = re.sub(r"^Eurooppa-neuvoston$", "Eurooppa-neuvosto", head)
        council = head or None
    return {"council": council, "date": date, "end": end}


def parse_eun_rows(data: dict) -> dict | None:
    """VaskiData rows of one 'EUN n/yyyy vp' (handling row + the Government's memo row) -> record."""
    cols = data.get("columnNames") or []
    rows = [dict(zip(cols, r)) for r in data.get("rowData") or []]
    if not rows:
        return None
    rec: dict = {"tunnus": None, "title": None, "memoTitle": None, "submitted": None, "keywords": [], "handling": [], "eutori": None,
                 "docId": None, "pdf": None, "url": None, "hasMemo": False, "status": None}
    for r in rows:
        xml = r.get("XmlData") or ""
        tunnus = (r.get("Eduskuntatunnus") or "").strip()
        rec["tunnus"] = rec["tunnus"] or tunnus
        m = re.search(r"SanomatyyppiNimi[^>]*>([^<]+)<", xml)
        typ = m.group(1) if m else ""
        try:
            root = strip_ns(xml)
        except ET.ParseError:
            continue
        nimeke = root.find(".//IdentifiointiOsa/Nimeke/NimekeTeksti")
        title = (nimeke.text or "").strip() if nimeke is not None and nimeke.text else None
        for a in root.iter("AiheTeksti"):
            if a.text and a.text.strip() and a.text.strip() not in rec["keywords"]:
                rec["keywords"].append(a.text.strip())
        if "KasittelytiedotValtiopaivaasia" in typ:
            rec["title"] = title or rec["title"]
            body = root.find(".//KasittelytiedotValtiopaivaasia")
            if body is not None:
                rec["status"] = body.get("tilaKoodi") or rec["status"]
            for tp in root.iter("ToimenpideJulkaisu"):
                d = iso_or_none(tp.get("tapahtumaPvm"))
                code = tp.get("kasittelyvaiheKoodi")
                label = (tp.findtext("ValiotsikkoTeksti") or "").strip()
                who = (tp.findtext("KokousToimija/Toimija/YhteisoTeksti") or "").strip()
                if not d:
                    continue
                if code == "ANTO":
                    rec["submitted"] = rec["submitted"] or d
                elif code in ("ATKUUL", "KASYEU", "ATRAPO", "KASVKP") and len(rec["handling"]) < 8:
                    h = {"date": d, "label": label or code, "committee": who or None}
                    if h not in rec["handling"]:
                        rec["handling"].append(h)
            if not rec["submitted"]:
                lp = root.find(".//IdentifiointiOsa/LaadintaPvmTeksti")
                rec["submitted"] = dmy_to_iso(lp.text) if lp is not None and lp.text else None
        elif "EuropeanUnionCouncilMeetings" in typ:
            rec["hasMemo"] = True
            rec["memoTitle"] = title or rec["memoTitle"]
            eut = root.find(".//EutoriTunnus")
            rec["eutori"] = (eut.text or "").strip() if eut is not None and eut.text else rec["eutori"]
            nid = root.find(".//Document/NativeId")
            if nid is not None and nid.text:
                rec["docId"] = nid.text.strip().strip("{}")
            if not rec["submitted"]:
                lp = root.find(".//IdentifiointiOsa/LaadintaPvmTeksti")
                rec["submitted"] = dmy_to_iso(lp.text) if lp is not None and lp.text else None
    if not rec["tunnus"]:
        return None
    m = re.match(r"EUN (\d+)/(\d{4})", rec["tunnus"])
    if m:
        rec["n"], rec["year"] = int(m.group(1)), int(m.group(2))
        rec["url"] = f"https://www.eduskunta.fi/valtiopaivaasiat/EUN+{m.group(1)}/{m.group(2)}"
        if rec["hasMemo"]:
            rec["pdf"] = f"https://www.eduskunta.fi/pdf/EUN+{m.group(1)}/{m.group(2)}"
    rec["title"] = rec["title"] or rec["memoTitle"]
    rec.update({"meetingTitle": rec["title"]})
    rec.update(meeting_from_title(rec["title"] or rec["memoTitle"] or ""))
    rec["handling"].sort(key=lambda h: h["date"])
    rec["fetched"] = TODAY.isoformat()
    return rec


def eun_lookup(n: int, year: int) -> dict | None:
    polite("eduskunta", 1.0)
    data = get_json(VASKI, params={"perPage": 10, "page": 0, "columnName": "Eduskuntatunnus", "columnValue": f"EUN {n}/{year} vp"}, timeout=60)
    return parse_eun_rows(data)


def fetch_eun(cfg: dict, prev: dict) -> dict:
    keep = int(cfg.get("keep_days", 30))
    cutoff = (TODAY - dt.timedelta(days=keep)).isoformat()
    miss_limit = int(cfg.get("miss_limit", 4))
    docs: dict[str, dict] = {k: v for k, v in (prev.get("docs") or {}).items()
                             if (v.get("date") or v.get("submitted") or "") >= cutoff or (v.get("date") or "") >= TODAY.isoformat()}
    last = dict(prev.get("lastN") or {})
    year = TODAY.year
    requests_made = 0
    ykey = str(year)
    if ykey not in last:
        # cold start: gallop to an upper bound, binary-search the highest existing number, then backfill
        lo, hi = 0, 1
        while True:
            rec = eun_lookup(hi, year)
            requests_made += 1
            if rec:
                lo, hi = hi, hi * 2
                if hi > 512:
                    break
            else:
                break
        while hi - lo > 1:
            mid = (lo + hi) // 2
            rec = eun_lookup(mid, year)
            requests_made += 1
            if rec:
                lo = mid
            else:
                hi = mid
        top = lo
        start = max(1, top - int(cfg.get("backfill", 40)) + 1)
        for n in range(start, top + 1):
            rec = eun_lookup(n, year)
            requests_made += 1
            if rec:
                docs[f"{n}/{year}"] = rec
        last[ykey] = top
        log(f"eun: {year}: ensimmäinen ajo, ylin numero {top}, haettu {top - start + 1} ({requests_made} pyyntöä)")
    # new numbers since the last run
    n = int(last.get(ykey) or 0) + 1
    misses = 0
    new = 0
    while misses < miss_limit and requests_made < 150:
        rec = eun_lookup(n, year)
        requests_made += 1
        if rec:
            docs[f"{n}/{year}"] = rec
            last[ykey] = n
            misses = 0
            new += 1
        else:
            misses += 1
        n += 1
    # refresh: memo not yet attached, or the meeting is still ahead (handling dates get added)
    retry_days = int(cfg.get("partial_retry_days", 21))
    refreshed = 0
    for key, rec in sorted(docs.items(), key=lambda kv: kv[1].get("date") or "", reverse=True):
        if rec.get("fetched") == TODAY.isoformat() or requests_made >= 150:
            continue
        stale_partial = not rec.get("hasMemo") and (days_ago(rec.get("submitted")) or 99) <= retry_days
        ahead = (rec.get("date") or "") >= TODAY.isoformat()
        if stale_partial or ahead:
            upd = eun_lookup(rec["n"], rec["year"])
            requests_made += 1
            if upd:
                docs[key] = upd
                refreshed += 1
    docs = {k: v for k, v in docs.items() if (v.get("date") or v.get("submitted") or "") >= cutoff or (v.get("date") or "") >= TODAY.isoformat()}
    if not docs and new == 0 and TODAY.month not in (1, 7, 8):
        raise RuntimeError("eun: yhtään EUN-asiakirjaa ei löytynyt – VaskiData-haku on ehkä muuttunut")
    log(f"eun: {new} uutta, {refreshed} päivitetty, {len(docs)} seurannassa (ylin EUN {last.get(ykey)}/{year}, {requests_made} pyyntöä)")
    return {"docs": docs, "lastN": last, "fetched": TODAY.isoformat()}


# ============================================================================= main
SOURCES = [  # (cache key, config key, fetcher)
    ("forward", "komissio", fetch_forward),
    ("council", "neuvosto", fetch_council),
    ("forecasts", "ennusteet", fetch_forecasts),
    ("infringements", "rikkomukset", fetch_infringements),
    ("comitology", "komitologia", fetch_comitology),
    ("sanctions", "pakotteet", fetch_sanctions),
    ("eun", "eun", fetch_eun),
]


def count_of(key: str, block: dict) -> int:
    return {"forward": lambda b: sum(len(m["items"]) for lst in b.get("lists") or [] for m in lst.get("meetings") or []) + len((b.get("cwp") or {}).get("initiatives") or []),
            "council": lambda b: len(b.get("agendas") or []), "forecasts": lambda b: len(b.get("items") or {}),
            "infringements": lambda b: len(b.get("cases") or {}), "comitology": lambda b: len(b.get("documents") or {}),
            "sanctions": lambda b: len(b.get("acts") or []), "eun": lambda b: len(b.get("docs") or {})}[key](block or {})


def main():
    cfg = load_yaml(CONFIG) or {}
    prev = load_json(OUT, {}) or {}
    out: dict = {"fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "health": {}}
    old_health = prev.get("health") or {}
    failed, enabled = [], 0
    for key, cfg_key, fn in SOURCES:
        scfg = cfg.get(cfg_key) or {}
        if not scfg.get("enabled", True):
            out[key] = prev.get(key) or {}
            out["health"][key] = {"ok": None, "disabled": True, "n": count_of(key, out[key])}
            continue
        enabled += 1
        t0 = time.time()
        try:
            out[key] = fn(scfg, prev.get(key) or {})
            out["health"][key] = {"ok": True, "n": count_of(key, out[key]), "seconds": round(time.time() - t0, 1), "last_ok": out["fetched"], "streak": 0}
        except Exception as e:  # noqa: BLE001
            failed.append(key)
            out[key] = prev.get(key) or {}
            streak = int((old_health.get(key) or {}).get("streak") or 0) + 1
            out["health"][key] = {"ok": False, "n": count_of(key, out[key]), "seconds": round(time.time() - t0, 1), "error": f"{type(e).__name__}: {e}"[:300],
                                  "last_ok": (old_health.get(key) or {}).get("last_ok"), "streak": streak}
            log(f"ERROR eu_signals/{key}: {type(e).__name__}: {e}")
    save_json(OUT, out, compact=True)
    size_kb = OUT.stat().st_size // 1024
    log(f"eu_signals: {enabled - len(failed)}/{enabled} lähdettä ok" + (f", epäonnistui {failed}" if failed else "") + f" -> {OUT} ({size_kb} kB)")
    if enabled and len(failed) == enabled:
        raise RuntimeError(f"eu_signals: kaikki lähteet epäonnistuivat: {failed}")


if __name__ == "__main__":
    main()
