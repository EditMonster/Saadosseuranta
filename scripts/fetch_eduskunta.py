"""Eduskunta open data (avoindata.eduskunta.fi, VaskiData): parliamentary stages
for each government proposal (annettu, lähetekeskustelu, mietintö, käsittelyt,
eduskunnan vastaus, vahvistus, säädöskokoelman numerot).

Also enumerates pending proposals from Finlex ministry lists so that nothing
Hankeikkuna misses is skipped.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re

from common import CACHE_DIR, TODAY, days_ago, get_json, http, load_json, log, parse_fi_date, save_json

API = "https://avoindata.eduskunta.fi/api/v1/tables/VaskiData/rows"
OUT = CACHE_DIR / "eduskunta.json"
FINLEX_MINISTRIES = [
    "eduskunta", "liikenne-ja-viestintaministerio", "maa-ja-metsatalousministerio", "oikeusministerio",
    "opetus-ja-kulttuuriministerio", "puolustusministerio", "sisaministerio", "sosiaali-ja-terveysministerio",
    "suomen-pankki", "tyo-ja-elinkeinoministerio", "ulkoministerio", "valtioneuvoston-kanslia",
    "valtiovarainministerio", "ymparistoministerio",
]
STAGES = {  # kasittelyvaiheKoodi -> (label, kind)
    "ANTO": ("HE annettu eduskunnalle", "he"),
    "LK": ("Lähetekeskustelu", "eduskunta"),
    "VKPM": ("Valiokunnan mietintö", "eduskunta"),
    "1K": ("Ensimmäinen käsittely", "eduskunta"),
    "2K": ("Toinen käsittely", "hyvaksytty"),
    "AK": ("Ainoa käsittely", "hyvaksytty"),
    "EV": ("Eduskunnan vastaus", "hyvaksytty"),
}
TAG = r"(?:[\w.-]+:)?"


def _text(x: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x))).strip()


def finlex_pending() -> set[str]:
    """HE numbers ('129/2026') currently listed as vireillä on Finlex."""
    nums = set()
    for m in FINLEX_MINISTRIES:
        try:
            r = http("GET", f"https://www.finlex.fi/fi/hallituksen-esitykset/vireilla/{m}", timeout=60)
            found = re.findall(r"/fi/hallituksen-esitykset/(\d{4})/(\d+)", r.text)
            nums.update(f"{n}/{y}" for y, n in found)
        except Exception as e:  # noqa: BLE001
            log(f"warn: finlex list {m}: {e}")
    return nums


def parse_kasittely(x: str) -> dict:
    out = {"title": "", "tila": "", "vaihe": "", "stages": [], "laws": [], "sk": [], "vahvistettu": None,
           "committees": []}
    m = re.search(rf"<{TAG}NimekeTeksti>([^<]+)<", x)
    out["title"] = html.unescape(m.group(1)).strip() if m else ""
    m = re.search(r'tilaKoodi="([^"]+)"', x)
    out["tila"] = m.group(1) if m else ""
    m = re.search(r'viimeisinKasittelyvaiheKoodi="([^"]+)"', x)
    out["vaihe"] = m.group(1) if m else ""
    for m in re.finditer(rf"<{TAG}LakiehdotusJulkaisu[^>]*>(.*?)</{TAG}LakiehdotusJulkaisu>", x, re.S):
        body = m.group(1)
        name = re.search(rf"<{TAG}NimekeTeksti>([^<]+)<", body)
        dec = re.search(r'lakiehdotusPaatosKoodi="([^"]+)"', body)
        vah = re.search(rf"<{TAG}VahvistusPvmTeksti>([^<]+)<", body)
        sk = re.findall(rf"<{TAG}SaadoskokoelmaViiteTunnus>([^<]+)<", body)
        out["laws"].append({"name": html.unescape(name.group(1)).strip() if name else "", "decision": dec.group(1) if dec else None,
                            "vahvistettu": vah.group(1).strip() if vah else None, "sk": sk})
        out["sk"].extend(sk)
        if vah and not out["vahvistettu"]:
            d = vah.group(1).strip()
            dd = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", d)
            out["vahvistettu"] = f"{dd.group(3)}-{int(dd.group(2)):02d}-{int(dd.group(1)):02d}" if dd else None
    for m in re.finditer(rf'<{TAG}ToimenpideJulkaisu[^>]*kasittelyvaiheKoodi="([^"]+)"[^>]*tapahtumaPvm="([^"]+)"[^>]*>(.*?)</{TAG}ToimenpideJulkaisu>', x, re.S):
        code, date, body = m.group(1), m.group(2), m.group(3)
        if code not in STAGES:
            continue
        txt = _text(body)
        com = re.search(r"((?:[\wäöå-]+\s+ja\s+)?[\wäöå-]+valiokunta)", txt)
        out["stages"].append({"code": code, "date": date, "committee": com.group(1) if com else None})
        if com and com.group(1) not in out["committees"]:
            out["committees"].append(com.group(1))
    out["stages"].sort(key=lambda s: s["date"])
    return out


def parse_proposal_text(x: str) -> dict:
    txt = _text(x)
    out = {}
    m = re.search(r"(?:tarkoitet\w+ tul\w+ voimaan|tul\w+ voimaan)\s+(\d{1,2}\s+päivänä\s+\w+kuuta\s+\d{4}|\d{1,2}\.\d{1,2}\.\d{4})", txt)
    if m:
        from common import parse_dmy
        out["ehdotettuVoimaantulo"] = parse_fi_date(m.group(1)) or parse_dmy(m.group(1))
    m = re.search(r"lausunto\w*\s+(?:oli|olivat|ol\w+ )?\s*(\d{1,2}\.\d{1,2}\.\d{4})\s*[–-]\s*(\d{1,2}\.\d{1,2}\.\d{4})", txt)
    if m:
        from common import parse_dmy
        out["lausuntoaika"] = [parse_dmy(m.group(1)), parse_dmy(m.group(2))]
    return out


def fetch_he(num: str) -> dict | None:
    tunnus = f"HE {num} vp"
    data = get_json(API, params={"perPage": 20, "page": 0, "columnName": "Eduskuntatunnus", "columnValue": tunnus},
                    timeout=120)
    rows = data.get("rowData") or []
    kas = [r for r in rows if "KasittelytiedotValtiopaivaasia" in r[1]]
    prop = [r for r in rows if "GovernmentProposal" in r[1] and "Kasittelytiedot" not in r[1]]
    if not kas and not prop:
        return None
    out = {"he": num, "fetched": TODAY.isoformat()}
    if kas:
        kas.sort(key=lambda r: r[3])  # Created
        out.update(parse_kasittely(kas[-1][1]))
    if prop:
        prop.sort(key=lambda r: r[3])
        out.update(parse_proposal_text(prop[-1][1]))
        if not out.get("title"):
            out["title"] = parse_kasittely(prop[-1][1]).get("title", "")
    out["final"] = bool(out.get("vahvistettu")) or out.get("tila") in ("Rauennut",) or \
        any(l.get("decision") == "Rejected" for l in out.get("laws", []))
    return out


def main():
    hk = load_json(CACHE_DIR / "hankeikkuna.json", {"items": []})["items"]
    nums = set()
    for it in hk:
        for h in it.get("heNumerot") or []:
            m = re.search(r"(\d+)/(\d{4})", h)
            if m:
                nums.add(f"{m.group(1)}/{m.group(2)}")
    pending = finlex_pending()
    log(f"eduskunta: {len(nums)} HE-numeroa hankeikkunasta, {len(pending)} vireillä Finlexissä")
    nums |= pending
    cache = load_json(OUT, {"items": {}})["items"]
    done, failed = 0, 0
    for num in sorted(nums, key=lambda n: (int(n.split("/")[1]), int(n.split("/")[0]))):
        old = cache.get(num)
        if old:
            age = days_ago(old.get("fetched")) or 0
            if (old.get("final") and age < 60) or (not old.get("final") and age < 1):
                continue
        try:
            rec = fetch_he(num)
        except Exception as e:  # noqa: BLE001
            failed += 1
            log(f"warn: HE {num}: {e}")
            continue
        if rec:
            rec["pendingFinlex"] = num in pending
            cache[num] = rec
            done += 1
    for num in pending:
        if num in cache:
            cache[num]["pendingFinlex"] = True
    for num, rec in cache.items():
        if num not in pending:
            rec["pendingFinlex"] = False
    save_json(OUT, {"fetched": dt.datetime.now().isoformat(timespec="seconds"), "items": cache})
    log(f"eduskunta: päivitetty {done}, epäonnistui {failed}, yhteensä {len(cache)} -> {OUT}")


if __name__ == "__main__":
    main()
