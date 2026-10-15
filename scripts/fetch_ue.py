"""Eduskunta open data: valtioneuvoston U-kirjelmät ja E-kirjeet (Finland's positions on
EU proposals) — title, date given, Commission document numbers (COM(2025) 981) and
parliamentary stages. Numbers are sequential per year, so they are enumerated until a
run of misses."""
from __future__ import annotations

import datetime as dt
import html
import re

from common import CACHE_DIR, TODAY, days_ago, get_json, load_json, log, save_json
from fetch_eduskunta import parse_kasittely

API = "https://avoindata.eduskunta.fi/api/v1/tables/VaskiData/rows"
OUT = CACHE_DIR / "ue.json"
MISS_RUN = 8          # stop a year's enumeration after this many consecutive missing numbers
PREFIX_TITLE = re.compile(r"^(Valtioneuvoston (kirjelmä eduskunnalle|selvitys:?)\s*)", re.I)


def fetch_doc(tunnus: str) -> dict | None:
    data = get_json(API, params={"perPage": 20, "page": 0, "columnName": "Eduskuntatunnus", "columnValue": tunnus}, timeout=120)
    rows = data.get("rowData") or []
    if not rows:
        return None
    rows.sort(key=lambda r: r[3])
    doc = {"tunnus": tunnus, "fetched": TODAY.isoformat(), "title": "", "anto": None, "com": [], "cod": [], "stages": [],
           "tila": "", "ministry": None}
    for r in rows:
        x = r[1]
        m = re.search(r"(?:[\w.-]+:)?NimekeTeksti>([^<]+)<", x)
        if m and not doc["title"]:
            doc["title"] = html.unescape(m.group(1)).strip()
        m = re.search(r'laadintaPvm="(\d{4}-\d{2}-\d{2})"', x)
        if m and not doc["anto"]:
            doc["anto"] = m.group(1)
        for y, n in re.findall(r"COM\((\d{4})\)\s?(\d+)", x):
            key = f"{y}/{int(n)}"
            if key not in doc["com"]:
                doc["com"].append(key)
        for ref in re.findall(r"(\d{4}/\d{3,4})\s?\((?:COD|NLE|CNS|APP)\)", x):
            y, n = ref.split("/")
            key = f"{y}-{int(n):04d}"
            if key not in doc["cod"]:
                doc["cod"].append(key)
        m = re.search(r"(?:[\w.-]+:)?ToimijaTeksti>([^<]*ministeriö[^<]*)<", x)
        if m and not doc["ministry"]:
            doc["ministry"] = html.unescape(m.group(1)).strip()
        if "KasittelytiedotValtiopaivaasia" in x:
            k = parse_kasittely(x)
            doc["tila"] = k.get("tila") or doc["tila"]
            for s in re.finditer(r'kasittelyvaiheKoodi="([^"]+)"[^>]*tapahtumaPvm="(\d{4}-\d{2}-\d{2})"', x):
                code, date = s.group(1), s.group(2)
                if code in ("ANTO", "VKPL", "SAAEUL", "VKEUP") and (code, date) not in [(a["code"], a["date"]) for a in doc["stages"]]:
                    doc["stages"].append({"code": code, "date": date})
            if not doc["anto"]:
                a = [s for s in doc["stages"] if s["code"] == "ANTO"]
                if a:
                    doc["anto"] = a[0]["date"]
    doc["stages"].sort(key=lambda s: s["date"])
    doc["short"] = PREFIX_TITLE.sub("", doc["title"]).strip()
    doc["short"] = doc["short"][:1].upper() + doc["short"][1:]
    return doc


def main():
    cache = load_json(OUT, {"items": {}})["items"]
    years = [TODAY.year, TODAY.year - 1]
    fetched = 0
    for year in years:
        for prefix in ("U", "E"):
            n, misses = 1, 0
            while misses < MISS_RUN and n < 400:
                tunnus = f"{prefix} {n}/{year} vp"
                n += 1
                old = cache.get(tunnus)
                if old:
                    misses = 0
                    age = days_ago(old.get("fetched")) or 0
                    recent = old.get("anto") and (days_ago(old["anto"]) or 999) < 120
                    if not (recent and age >= 7):
                        continue
                try:
                    doc = fetch_doc(tunnus)
                except Exception as e:  # noqa: BLE001
                    log(f"warn: {tunnus}: {e}")
                    misses += 1
                    continue
                if not doc:
                    misses += 1
                    continue
                misses = 0
                cache[tunnus] = doc
                fetched += 1
                if fetched % 25 == 0:
                    save_json(OUT, {"fetched": dt.datetime.now().isoformat(timespec="seconds"), "items": cache})
    save_json(OUT, {"fetched": dt.datetime.now().isoformat(timespec="seconds"), "items": cache})
    log(f"ue: haettu {fetched}, yhteensä {len(cache)} kirjelmää -> {OUT}")


if __name__ == "__main__":
    main()
