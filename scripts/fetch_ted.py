"""TED (Tenders Electronic Daily, the EU's public-procurement journal) – notices from the neighbouring
countries in the same CPV divisions that the Finnish Hilma watch covers.

Source: the keyless TED API v3, ``POST https://api.ted.europa.eu/v3/notices/search`` with an expert
query such as
``(buyer-country IN (SWE EST DNK NOR)) AND (publication-date >= 20261011) AND (classification-cpv IN (72* 48*))
AND (notice-type IN (cn-standard cn-social pin-cfc-standard pin-only pin-buyer)) SORT BY publication-date DESC``
and ITERATION paging (``iterationNextToken``), 250 notices per page, at most 1 000 notices per country and run
(one query per country; a country new to the cache is read ``backfill_days`` back once).
Configuration lives in config/settings.yaml → ``ted`` (countries as ISO alpha-2, lookback days, CPV
patterns; an empty list means the CPV divisions of config/hankinnat.yaml's toimialat). Finnish notices
are not fetched here – Hilma already has every one of them.

Per notice the cache keeps the publication number, the title in Finnish, Swedish or English (first
available, in that order; TED titles read "Country – CPV label – title"), the buyer, the alpha-2
country, publication date, the earliest lot deadline, CPV codes, the estimated value, the notice type,
the procedure identifier (BT-04, joins to Hilma's contractFolderID for joint procurements) and the
TED HTML link. Notices stay while their deadline is less than 14 days in the past or they were published
within the lookback window (prior information notices without a deadline for ``pin_days``).
Cache: data/cache/ted.json {fetched, notices: {publicationNumber: {...}}}.
"""
from __future__ import annotations

import datetime as dt
import re

from common import CACHE_DIR, CONFIG_DIR, TODAY, load_json, load_yaml, log, post_json, save_json

SEARCH = "https://api.ted.europa.eu/v3/notices/search"
OUT = CACHE_DIR / "ted.json"
PAGE = 250
MAX_NOTICES = 1000
NOTICE_TYPES = ("cn-standard", "cn-social", "pin-cfc-standard", "pin-only", "pin-buyer")
FIELDS = ["publication-number", "notice-title", "buyer-name", "buyer-country", "publication-date",
          "deadline-receipt-tender-date-lot", "deadline-receipt-tender-time-lot",
          "deadline-receipt-request-date-lot", "deadline-receipt-request-time-lot",
          "classification-cpv", "estimated-value-glo", "estimated-value-cur-glo",
          "estimated-value-lot", "notice-type", "links", "procedure-identifier"]
LANG_ORDER = ("fin", "swe", "eng")
ALPHA3 = {"SE": "SWE", "EE": "EST", "DK": "DNK", "NO": "NOR", "FI": "FIN", "LV": "LVA", "LT": "LTU", "DE": "DEU", "PL": "POL",
          "IS": "ISL", "NL": "NLD", "IE": "IRL", "FR": "FRA", "AT": "AUT", "BE": "BEL", "CZ": "CZE", "ES": "ESP", "IT": "ITA",
          "PT": "PRT", "LU": "LUX", "HU": "HUN", "SK": "SVK", "SI": "SVN", "HR": "HRV", "RO": "ROU", "BG": "BGR", "GR": "GRC",
          "CY": "CYP", "MT": "MLT", "CH": "CHE", "LI": "LIE", "UK": "GBR", "GB": "GBR"}
ALPHA2 = {v: k for k, v in ALPHA3.items() if k != "GB"}
KEEP_PAST_DAYS = 14


def cpv_patterns(ted_cfg: dict, hankinnat_cfg: dict) -> list[str]:
    """'72*'-style patterns: the configured list, else every CPV prefix of hankinnat.yaml's toimialat."""
    pats = [str(p).strip() for p in (ted_cfg.get("cpv") or []) if str(p).strip()]
    if not pats:
        for codes in (hankinnat_cfg.get("toimialat") or {}).values():
            pats += [str(c) for c in codes]
    out = []
    for p in pats:
        p = p if p.endswith("*") else p + "*"
        if p not in out:
            out.append(p)
    return out


def build_query(countries: list[str], since: dt.date, cpv: list[str]) -> str:
    # no "SORT BY": a sort clause breaks ITERATION paging (the third page comes back empty, checked 2026-10-18)
    cc = " ".join(ALPHA3.get(str(c).upper(), str(c).upper()) for c in countries)
    return (f"(buyer-country IN ({cc})) AND (publication-date >= {since.strftime('%Y%m%d')}) "
            f"AND (classification-cpv IN ({' '.join(cpv)})) AND (notice-type IN ({' '.join(NOTICE_TYPES)}))")


def pick_title(obj, order=LANG_ORDER) -> tuple[str, str | None]:
    """TED's per-language title object -> (title, language). Finnish, then Swedish, then English, then anything."""
    if isinstance(obj, str):
        return obj.strip(), None
    if not isinstance(obj, dict) or not obj:
        return "", None
    for lang in order:
        v = obj.get(lang)
        if isinstance(v, list):
            v = v[0] if v else None
        if v and str(v).strip():
            return str(v).strip(), lang
    lang, v = next(iter(obj.items()))
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v or "").strip(), lang


def split_title(title: str) -> tuple[str, str | None]:
    """'Tanska – Ohjelmistot ja tietojärjestelmät – Qualified Signature Creation Device' -> (the buyer's own title,
    the CPV label TED prefixed it with). TED separates the parts with en dashes; hyphens inside titles are kept."""
    parts = [p.strip() for p in re.split(r"\s+[–—]\s+", title or "") if p.strip()]
    if len(parts) >= 3:
        rest = " – ".join(parts[2:])
        if len(rest) >= 4:
            return rest, parts[1]
    return (title or "").strip(), None


def short_title(title: str) -> str:
    return split_title(title)[0]


def _first(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _date(v) -> str | None:
    s = str(_first(v) or "")
    return s[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", s) else None


def deadline_utc(dates, times) -> str | None:
    """Earliest lot deadline as an ISO UTC timestamp: TED gives '2026-11-16+02:00' + '23:59:59+02:00' (or 'Z');
    without a time the end of that day is assumed."""
    dates = [str(x) for x in (dates or []) if x]
    times = [str(x) for x in (times or []) if x]
    best = None
    for i, d in enumerate(dates):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})(Z|[+-]\d{2}:\d{2})?$", d)
        if not m:
            continue
        t = times[i] if i < len(times) else (times[0] if len(times) == 1 else None)
        tm = re.match(r"^(\d{2}:\d{2}:\d{2})(Z|[+-]\d{2}:\d{2})?$", t or "")
        clock = tm.group(1) if tm else "23:59:59"
        tz = (tm.group(2) if tm and tm.group(2) else m.group(2)) or "Z"
        try:
            when = dt.datetime.fromisoformat(f"{m.group(1)}T{clock}{tz}".replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        except ValueError:
            continue
        iso = when.strftime("%Y-%m-%dT%H:%M:%SZ")
        best = iso if best is None or iso < best else best
    return best


def trim_notice(n: dict, wanted: set[str] | None = None) -> dict:
    title, lang = pick_title(n.get("notice-title"))
    buyer, _ = pick_title(n.get("buyer-name"), order=("fin", "swe", "eng", "dan", "nor", "est", "lav", "lit"))
    deadline = deadline_utc(n.get("deadline-receipt-tender-date-lot"), n.get("deadline-receipt-tender-time-lot"))
    kind = "tarjous" if deadline else None
    if not deadline:
        deadline = deadline_utc(n.get("deadline-receipt-request-date-lot"), n.get("deadline-receipt-request-time-lot"))
        kind = "osallistumishakemus" if deadline else None
    cpv = list(dict.fromkeys(str(c) for c in (n.get("classification-cpv") or []) if c))
    # a joint procurement lists several buyer countries: the watched one names the notice
    bc = [str(c) for c in (n.get("buyer-country") if isinstance(n.get("buyer-country"), list) else [n.get("buyer-country")]) if c]
    country = next((c for c in bc if wanted and ALPHA2.get(c, c[:2]) in wanted), bc[0] if bc else "")
    value = _first(n.get("estimated-value-glo"))
    if value is None:
        lots = [float(x) for x in (n.get("estimated-value-lot") or []) if str(x).replace(".", "", 1).isdigit()]
        value = sum(lots) if lots else None
    try:
        value = float(value) if value is not None else None
    except (TypeError, ValueError):
        value = None
    links = n.get("links") or {}
    html = links.get("html") or {}
    url = html.get("FIN") or html.get("ENG") or links.get("htmlDirect") or next(iter(html.values()), None)
    short, cpv_text = split_title(title)
    rec = {"pn": n.get("publication-number"), "title": short[:220], "cpvText": cpv_text[:120] if cpv_text else None, "lang": lang, "buyer": buyer[:160] or None, "country": ALPHA2.get(country, country[:2]), "published": _date(n.get("publication-date")),
           "deadline": deadline, "deadlineKind": kind, "cpv": cpv[:12], "value": value,
           "currency": _first(n.get("estimated-value-cur-glo")) or ("EUR" if value else None), "noticeType": n.get("notice-type"),
           "procedureId": n.get("procedure-identifier"), "url": url or f"https://ted.europa.eu/fi/notice/-/detail/{n.get('publication-number')}"}
    return {k: v for k, v in rec.items() if v not in (None, "", [])}


def keep(rec: dict, days: int, pin_days: int, today: dt.date = TODAY) -> bool:
    dl = (rec.get("deadline") or "")[:10]
    if dl:
        return dl >= (today - dt.timedelta(days=KEEP_PAST_DAYS)).isoformat()
    pub = rec.get("published") or ""
    horizon = pin_days if str(rec.get("noticeType", "")).startswith("pin") else days
    return pub >= (today - dt.timedelta(days=horizon)).isoformat()


def search(query: str, limit: int = MAX_NOTICES) -> tuple[list[dict], int]:
    body = {"query": query, "fields": FIELDS, "limit": PAGE, "scope": "ACTIVE", "paginationMode": "ITERATION", "onlyLatestVersions": True}
    notices, token, total = [], None, None
    while len(notices) < limit:
        if token:
            body["iterationNextToken"] = token
        data = post_json(SEARCH, body, timeout=120, headers={"Accept": "application/json"})
        if total is None:
            total = int(data.get("totalNoticeCount") or 0)
        page = data.get("notices") or []
        notices.extend(page)
        token = data.get("iterationNextToken")
        if not page or not token or len(page) < PAGE:
            break
    return notices[:limit], total


def main():
    settings = load_yaml(CONFIG_DIR / "settings.yaml")
    cfg = settings.get("ted") or {}
    if not cfg.get("enabled", True):
        log("ted: pois käytöstä (settings.yaml ted.enabled)")
        return
    countries = [str(c) for c in (cfg.get("maat") or ["SE", "EE", "DK", "NO"])]
    days = int(cfg.get("days", 7))
    pin_days = int(cfg.get("pin_days", 90))
    cpv = cpv_patterns(cfg, load_yaml(CONFIG_DIR / "hankinnat.yaml") or {})
    if not cpv:
        raise RuntimeError("TED: ei yhtään CPV-ehtoa (settings.yaml ted.cpv tai hankinnat.yaml toimialat)")
    backfill_days = int(cfg.get("backfill_days", 45))
    old = (load_json(OUT, {}) or {}).get("notices") or {}
    known = {n.get("country") for n in old.values()}
    # one query per country: together the countries exceed the per-query cap, and without a sort clause (it breaks
    # ITERATION paging) a capped result would drop arbitrary notices. A country new to the cache is read further back
    # once so that tenders already open when it was added are listed at once.
    raw, total, queries = [], 0, []
    for c in countries:
        lookback = days if c.upper() in known else max(days, backfill_days)
        queries.append(build_query([c], TODAY - dt.timedelta(days=lookback), cpv))
        part, n = search(queries[-1])
        raw += part
        total += n
        if n > MAX_NOTICES:
            log(f"warn: ted {c}: {n} ilmoitusta ylittää kyselykohtaisen rajan {MAX_NOTICES} – pienennä settings.yaml ted.days tai rajaa ted.cpv")
        if lookback != days:
            log(f"ted {c}: uusi maa, haettu {lookback} päivän ilmoitukset ({n})")
    if not raw and total == 0 and len(old) > 20:
        raise RuntimeError("TED palautti nolla ilmoitusta – kysely tai rajapinta näyttää rikkinäiseltä")
    notices = dict(old)
    new = 0
    for n in raw:
        rec = trim_notice(n, {c.upper() for c in countries})
        if not rec.get("pn"):
            continue
        if rec["pn"] not in notices:
            new += 1
        notices[rec["pn"]] = rec
    kept = {k: v for k, v in notices.items() if keep(v, days, pin_days)}
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_json(OUT, {"fetched": now, "query": queries, "notices": kept}, compact=True)
    per_country = {}
    for v in kept.values():
        per_country[v.get("country")] = per_country.get(v.get("country"), 0) + 1
    log(f"ted: {len(raw)} ilmoitusta haettu ({days} pv, TED: {total}), {new} uutta, {len(kept)} säilytetty {per_country} -> {OUT}")


if __name__ == "__main__":
    main()
