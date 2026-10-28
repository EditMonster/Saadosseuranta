"""Finlex säädöskokoelma: entry-into-force date for each confirmed statute number
('1390/2025' -> 'Tämä laki tulee voimaan 1 päivänä tammikuuta 2026')."""
from __future__ import annotations

import datetime as dt
import json
import re
import time

from common import CACHE_DIR, http, load_json, log, parse_fi_date, save_json

OUT = CACHE_DIR / "finlex.json"
MAX_PER_RUN = 200
DELAY = 1.5


def page_text(url: str) -> str:
    r = http("GET", url, timeout=60)
    if r.status_code != 200:
        return ""
    # Finlex is a Next.js app: body text sits in RSC payload chunks.
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', r.text, re.S)
    parts = []
    for c in chunks:
        try:
            parts.append(json.loads('"' + c + '"'))
        except ValueError:
            parts.append(c)
    return " ".join(parts)


def voimaantulo(sk: str) -> dict | None:
    m = re.match(r"(\d+)/(\d{4})", sk)
    if not m:
        return None
    url = f"https://www.finlex.fi/fi/lainsaadanto/saadoskokoelma/{m.group(2)}/{m.group(1)}"
    txt = page_text(url)
    if not txt:
        return None
    dates = []
    for mm in re.finditer(r"tulee voimaan\s+(\d{1,2}\s+päivänä\s+\w+kuuta\s+\d{4})", txt):
        d = parse_fi_date(mm.group(1))
        if d and d not in dates:
            dates.append(d)
    title = re.search(r'"title":"([^"]{5,200}?)\s*\|\s*' + re.escape(sk), txt)
    from build_siirtyma import finlex_vt_text  # the entry-into-force provision itself: staggered dates, transition periods
    return {"sk": sk, "url": url, "voimaan": dates[0] if dates else None, "muutVoimaantulot": dates[1:4],
            "title": title.group(1) if title else None, "vtText": finlex_vt_text(txt) or None, "fetched": dt.date.today().isoformat()}


def main():
    ek = load_json(CACHE_DIR / "eduskunta.json", {"items": {}})["items"]
    hk = load_json(CACHE_DIR / "hankeikkuna.json", {"items": []})["items"]
    wanted = set()
    for rec in ek.values():
        wanted.update(rec.get("sk") or [])
    for it in hk:
        wanted.update(it.get("skNumerot") or [])
    cache = load_json(OUT, {"items": {}})["items"]
    n = 0
    # Finlex rate-limits (HTTP 429): one page every ~1.5 s and at most MAX_PER_RUN new pages per run;
    # the remainder is picked up on the next scheduled run (newest statutes first).
    wanted = {s.strip() for s in wanted if re.fullmatch(r"\d+/\d{4}", s.strip())}
    todo = [sk for sk in sorted(wanted, key=lambda s: (-int(s.split("/")[1]), -int(s.split("/")[0])))
            if not (sk in cache and "vtText" in cache[sk] and (cache[sk].get("voimaan") or
                    (dt.date.today() - dt.date.fromisoformat(cache[sk]["fetched"])).days < 14))]
    # statutes read before the provision text was kept are read once more, newest first (a few runs)
    for sk in todo[:MAX_PER_RUN]:
        try:
            rec = voimaantulo(sk)
        except Exception as e:  # noqa: BLE001
            log(f"warn: finlex {sk}: {e}")
            time.sleep(10)
            continue
        if rec:
            cache[sk] = rec
            n += 1
            if n % 25 == 0:
                save_json(OUT, {"fetched": dt.datetime.now().isoformat(timespec="seconds"), "items": cache})
        time.sleep(DELAY)
    save_json(OUT, {"fetched": dt.datetime.now().isoformat(timespec="seconds"), "items": cache})
    if len(todo) > MAX_PER_RUN:
        log(f"finlex: {len(todo) - MAX_PER_RUN} säädöstä jää seuraavaan ajoon")
    log(f"finlex: {n} säädöstä päivitetty, {len(cache)} yhteensä -> {OUT}")


if __name__ == "__main__":
    main()
