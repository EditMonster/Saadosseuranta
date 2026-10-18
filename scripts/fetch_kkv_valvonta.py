"""KKV enforcement beyond merger control: procurement supervision (hankintojen valvonta – illegal
direct awards, huomautukset and proposals to the Market Court), seuraamusmaksu proposals to the
Market Court, prohibition/commitment/supply-obligation decisions and competitive-neutrality
decisions.

All four listings on kkv.fi are the same WordPress archive as the merger decisions, so the entry
regex and the case-page parser of fetch_kkv are reused unchanged. The site-wide rulings feed
(/paatokset/feed/) mixes every ruling type and is read for same-day discovery of new cases. A case
page gives the date, diaarinumero (the task code tells the category: 14.00.60 procurement
supervision, 14.00.00 restrictions, 14.00.40 neutrality), parties (for procurement supervision the
contracting entity) and KKV's one-paragraph tiivistelmä, from which the outcome is classified
(esitys markkinaoikeudelle / seuraamusmaksu / huomautus / kielto / sitoumukset / ei toimenpiteitä).

Cache: data/cache/kkv_valvonta.json {fetched, cases: {diaari_or_slug: {category, date, title,
parties, summary, outcome, url, buyer?, diaari?, seen}}}; cases older than keep_days are dropped.
At most ``pages`` listing pages per category per run plus the details of new cases.
"""
from __future__ import annotations

import datetime as dt
import html
import re
import time

from common import CACHE_DIR, CONFIG_DIR, TODAY, http, load_json, load_yaml, log, save_json
from fetch_kkv import ENTRY, UA, parse_case

BASE = "https://www.kkv.fi/paatokset/kilpailuasiat/"
CATEGORIES = {
    "hankintojen-valvonta": "Hankintojen valvonta",
    "esitykset-markkinaoikeudelle": "Esitys markkinaoikeudelle",
    "kielto-sitoumus-tai-toimitusvelvoiteratkaisut": "Kielto-, sitoumus- tai toimitusvelvoiteratkaisu",
    "kilpailuneutraliteetti": "Kilpailuneutraliteettiratkaisu",
}
FEED = "https://www.kkv.fi/paatokset/feed/"
OUT = CACHE_DIR / "kkv_valvonta.json"
OUTCOMES = [  # first match wins
    (r"esit(?:tää|ys|etään)[^.]{0,40}?markkinaoikeu|markkinaoikeudelle\s+(?:seuraamusmaksu|esity)|seuraamusmaksun määräämis|seuraamusmaksuesit", "esitys markkinaoikeudelle"),
    (r"huomautu", "huomautus"),
    (r"sitoumu", "sitoumukset"),
    (r"toimitusvelvoit", "toimitusvelvoite"),
    (r"kieltää|kielto|määrää\w*\s+\w*\s*lopettamaan|velvoittaa\s+\w+\s+lopettamaan|lopetettava", "kielto"),
    (r"ei ryhdy|ei ole aihetta|ei anna aihetta|ei ole syytä|ei ole tarvetta|lopettaa asian käsittelyn|poistaa asian|käsittely lopetetaan|ei ole todettu|ei ole saatu näyttöä|ei ole menetellyt|ei ole rikkonut|ei ole perusteita", "ei toimenpiteitä"),
    (r"seuraamusmaksu", "seuraamusmaksu"),
]


def slug_of(url: str) -> str:
    return (url or "").rstrip("/").rsplit("/", 1)[-1].lower()


def classify_outcome(text: str) -> str:
    low = re.sub(r"\s+", " ", (text or "").lower())
    for pat, label in OUTCOMES:
        if re.search(pat, low):
            return label
    return "päätös"


def listing(cat: str, pages: int) -> list[dict]:
    out = []
    for page in range(1, pages + 1):
        r = http("GET", BASE + cat + "/", params={"sivu": page} if page > 1 else None, headers=UA, timeout=60)
        r.raise_for_status()
        found = ENTRY.findall(r.text)
        for link, title, date, status in found:
            out.append({"url": link, "title": html.unescape(re.sub(r"<[^>]+>", "", title)).strip(), "date": date,
                        "status": html.unescape(status).strip(), "category": cat})
        if len(found) < 10:
            break
        time.sleep(0.5)
    return out


def feed_items() -> list[dict]:
    """Rulings-feed items that belong to one of our categories: [{url, title, category, date}]."""
    r = http("GET", FEED, headers={**UA, "Accept": "application/rss+xml, application/xml, text/xml"}, timeout=60)
    r.raise_for_status()
    out = []
    for m in re.finditer(r"<item>(.*?)</item>", r.text, re.S):
        it = m.group(1)
        link = (re.search(r"<link>\s*(\S+?)\s*</link>", it) or [None, ""])[1]
        cat = next((c for c in CATEGORIES if f"/kilpailuasiat/{c}/" in link), None)
        if not cat:
            continue
        title = html.unescape(re.sub(r"<[^>]+>|<!\[CDATA\[|\]\]>", "", (re.search(r"<title>(.*?)</title>", it, re.S) or [None, ""])[1])).strip()
        pub = (re.search(r"<pubDate>(.*?)</pubDate>", it) or [None, ""])[1]
        date = None
        try:
            date = dt.datetime.strptime(pub.strip()[:25], "%a, %d %b %Y %H:%M:%S").date().isoformat()
        except ValueError:
            pass
        out.append({"url": link, "title": title, "category": cat, "date": date, "status": CATEGORIES[cat]})
    return out


def main():
    cfg = (load_yaml(CONFIG_DIR / "settings.yaml") or {}).get("kkv_valvonta", {}) or {}
    keep_days = int(cfg.get("keep_days", 180))
    pages = int(cfg.get("pages", 3))
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    old = load_json(OUT, {}) or {}
    cases: dict[str, dict] = dict(old.get("cases") or {})
    known_urls = {v.get("url") for v in cases.values()}

    entries: list[dict] = []
    failed = 0
    for cat in CATEGORIES:
        try:
            entries += listing(cat, pages)
        except Exception as e:  # noqa: BLE001
            failed += 1
            log(f"warn: kkv_valvonta listaus {cat}: {e}")
        time.sleep(0.5)
    try:
        entries += feed_items()
    except Exception as e:  # noqa: BLE001
        log(f"warn: kkv_valvonta syöte: {e}")
    if not entries:
        raise RuntimeError("KKV valvonta: listaukset ja syöte tyhjiä – sivuston rakenne on ehkä muuttunut")

    new = 0
    seen_urls = set()
    for e in entries:
        if e["url"] in seen_urls:
            continue
        seen_urls.add(e["url"])
        if e.get("date") and e["date"] < cutoff:
            continue
        if e["url"] in known_urls:
            continue
        try:
            d = parse_case(e["url"])
        except Exception as ex:  # noqa: BLE001
            log(f"warn: kkv_valvonta {e['url']}: {ex}")
            continue
        time.sleep(0.6)
        summary = re.sub(r"\s*Lisää aiheesta:?\s*$", "", d.get("summary") or "").strip()
        key = d.get("diaari") or slug_of(e["url"])
        cat = e["category"]
        c = {
            "category": cat, "date": d.get("decided") or e.get("date"), "listDate": e.get("date"), "title": e["title"][:220],
            "parties": d.get("parties"), "summary": summary[:600], "outcome": classify_outcome(e["title"] + ". " + summary),
            "url": e["url"], "slug": slug_of(e["url"]), "diaari": d.get("diaari"), "seen": TODAY.isoformat(),
        }
        if cat == "hankintojen-valvonta" or (d.get("diaari") or "").find("14.00.60") >= 0:
            c["buyer"] = d.get("parties")
        cases[key] = {k: v for k, v in c.items() if v not in (None, "")}
        known_urls.add(e["url"])
        new += 1
    cases = {k: v for k, v in cases.items() if (v.get("date") or "9999") >= cutoff}
    save_json(OUT, {"fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "cases": cases}, compact=True)
    by_cat = {c: sum(1 for v in cases.values() if v.get("category") == c) for c in CATEGORIES}
    log(f"kkv_valvonta: {len(entries)} listariviä, {new} uutta tapausta, {len(cases)} välimuistissa {by_cat}"
        + (f", {failed} listausta epäonnistui" if failed else "") + f" -> {OUT}")


if __name__ == "__main__":
    main()
