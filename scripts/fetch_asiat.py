"""Eduskunnan valtiopäiväasiat kokonaisuudessaan: jokaisen seurattavan asian KAIKKI asiantuntijalausunnot
(kaikki valiokunnat ja jaostot) sekä valiokuntien lausunnot ja mietinnöt.

Miksi: avoimen datan VaskiData-syöte (fetch_vaski) kertoo vain sen, mitä on julkaistu syötteen
lukemisen jälkeen – vanhemmista ja pitkään käsittelyssä olleista asioista puuttui suurin osa lausunnoista
(esim. talousarvioesityksestä 109 / 360). Eduskunta.fi:n asiasivu (`…/valtiopaivaasiat/<tunnus>/__data.json`,
SvelteKit-data) listaa asian kaikki asiakirjat:
* `asiantuntijalausunnot.fi[]` – EDK-tunnus, otsikko "<asia> <Vk> <pvm> <titteli nimi, organisaatio>", päivä,
  tyyppi (Asiantuntijalausunto / Lisäselvitys / Asiantuntijalausunnon liite)
* `kasittelynAsiakirjat.fi[][]` – mm. valiokuntien lausunnot (PeVL, YmVL …) ja mietinnöt (…M)
* `tila` – Käsittelyssä / Käsitelty

Mitkä asiat: kaikki asiat, joihin sivun rivit viittaavat (HE-numerot, rivin oma viite U/E/LA/KAA/…, EU-ehdotuksen
U/E-kirjelmät) edellisen rakennuksen items.json:sta sekä VaskiDatan lausuntojen asiat. Käsittelyssä olevat asiat
haetaan uudelleen joka ajossa (kun edellisestä hausta on yli `REFRESH_ACTIVE_H`), käsitellyt viikon välein.
Valiokunnan lausunnot ja mietinnöt, joita VaskiData-välimuistissa ei ole (esim. edellisen vuoden), haetaan
VaskiDatasta tunnuksella ja jäsennetään samalla parse_report-funktiolla (päätös, muutetut pykälät, vastalauseet).

Välimuisti: data/cache/asiat/<tyyppi>-<vuosi>.json {"asiat": {"HE 12/2026 vp": {...}}} ja
data/cache/asiat/_reports.json {"reports": {"PeVL 3/2026 vp": {...}}, "noReport": [...]}; load_cache() kokoaa ne.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sys
import time
from urllib.parse import quote

import devalue
import fetch_vaski as fv
from common import CACHE_DIR, OUT_DIR, SourceOutage, http, load_json, log, save_json

OUT = CACHE_DIR / "asiat"     # asiat/<tyyppi>-<vuosi>.json + asiat/_reports.json: a run rewrites only the shards that changed
DATA_URL = "https://www.eduskunta.fi/asiat-ja-aanestykset/valtiopaivaasiat/{}/__data.json"
HTML_URL = "https://www.eduskunta.fi/valtiopaivaasiakirjat/{}"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) saadosseuranta/1.0 (+https://github.com/EditMonster/Saadosseuranta)",
      "Accept": "application/json"}
BUDGET_S = int(os.environ.get("ASIAT_BUDGET_S", 8 * 60))
REFRESH_ACTIVE_H = 6
REFRESH_DONE_D = 7
STATEMENT_TYPES = {"Asiantuntijalausunto": "lausunto", "Lisäselvitys": "lisäselvitys"}
COMMITTEE_DOCS = {"Valiokunnan lausunto": "lausunto", "Valiokunnan mietintö": "mietintö"}
FETCHABLE = re.compile(r"^(HE|U|E|UTP|VNS|VNT|K|O|M|LA|KAA|TPA|TAA|LTA|KAA) \d+/\d{4} vp$")


def _fi(x):
    return (x or {}).get("fi") if isinstance(x, dict) else x


def wanted_asiat() -> list[str]:
    """Parliamentary matters the page shows (from the last build), plus those VaskiData already has statements for."""
    from build_lausunnot import parliament_keys
    keys: set[str] = set()
    for it in (load_json(OUT_DIR / "items.json", {}) or {}).get("items") or []:
        keys.update(f"{k} vp" for k in parliament_keys(it))
    keys.update((load_json(CACHE_DIR / "vaski.json", {}) or {}).get("statements") or {})
    return sorted(k for k in keys if FETCHABLE.match(k))


def parse_asia(doc: dict) -> dict:
    """Decoded __data.json -> compact record."""
    nodes = devalue.decode(doc)
    va = next((n["valtiopaivaasia"] for n in nodes if isinstance(n, dict) and n.get("valtiopaivaasia")), None)
    if not va:
        raise ValueError("asiasivulta puuttuu valtiopaivaasia")
    statements = []
    for a in (_fi(va.get("asiantuntijalausunnot")) or []):
        kind = STATEMENT_TYPES.get(a.get("asiakirjatyyppinimi") or "")
        edk = a.get("edktunnus")
        if not kind or not edk:
            continue
        title = re.sub(r"\s+", " ", a.get("nimeketeksti") or "").strip()
        m = fv.STATEMENT_TITLE.match(title)
        person, org = fv.split_author(m.group("who") if m else title)
        statements.append({k: v for k, v in {
            "edk": edk, "date": (a.get("laadintapvm") or "")[:10] or None, "committee": m.group("vk") if m else None,
            "org": org, "person": person, "title": title[:300], "url": fv.PDF + edk, "kind": None if kind == "lausunto" else kind,
        }.items() if v})
    docs = []
    for group in (_fi(va.get("kasittelynAsiakirjat")) or []):
        for a in group or []:
            kind = COMMITTEE_DOCS.get(a.get("asiakirjatyyppinimi") or "")
            tunnus = (a.get("eduskuntatunnus") or "").strip()
            if not kind or not tunnus.endswith(" vp"):
                continue
            abbr = re.match(r"^([A-Za-zÄÖ]+?)[LM] ", tunnus)
            docs.append({"tunnus": tunnus, "kind": kind, "date": (a.get("laadintapvm") or "")[:10] or None,
                         "committee": abbr.group(1) if abbr else None})
    docs = list({d["tunnus"]: d for d in docs}.values())
    tila = _fi(va.get("tila")) or ""
    title = _fi(va.get("nimeke"))
    return {"tila": tila, "title": (title if isinstance(title, str) else "")[:300],
            "statements": sorted(statements, key=lambda s: (s.get("date") or "", s["edk"])),
            "committeeDocs": sorted(docs, key=lambda d: (d.get("date") or "", d["tunnus"]))}


def fetch_asia(tunnus: str) -> dict:
    r = http("GET", DATA_URL.format(quote(tunnus, safe="")), headers=UA, timeout=60)
    if r.status_code == 404:
        return {"tila": "ei löydy", "statements": [], "committeeDocs": []}
    r.raise_for_status()
    return parse_asia(r.json())


def stale(rec: dict | None, now: dt.datetime) -> bool:
    if not rec or not rec.get("fetched"):
        return True
    age = now - dt.datetime.fromisoformat(rec["fetched"].replace("Z", "+00:00"))
    if rec.get("tila") == "Käsitelty" or rec.get("tila") == "ei löydy":
        return age > dt.timedelta(days=REFRESH_DONE_D)
    return age > dt.timedelta(hours=REFRESH_ACTIVE_H)


def fetch_missing_reports(cache: dict, deadline: float) -> int:
    """Committee opinions/reports named by the asia pages but absent from the VaskiData cache: fetch by tunnus."""
    have = set(((load_json(CACHE_DIR / "vaski.json", {}) or {}).get("reports") or {})) | set(cache["reports"])
    todo = sorted({d["tunnus"] for a in cache["asiat"].values() for d in a.get("committeeDocs") or []} - have - set(cache.get("noReport") or []),
                  reverse=True)
    n = 0
    stats = {"bad": 0, "agendas": 0, "statements": 0, "reports": 0, "motions": 0}
    for tunnus in todo:
        if time.time() > deadline:
            break
        try:
            rows = fv.fetch_by_tunnus(tunnus)
        except Exception as e:  # noqa: BLE001
            log(f"warn: asiat: {tunnus}: {e}")
            continue
        tmp = {"reports": {}, "statements": {}, "agendas": {}, "motions": []}
        for row in rows:
            if (row[4] or "").strip() == tunnus:
                fv.absorb(tmp, row[1] or "", row[4], None, stats)
        if tunnus in tmp["reports"]:
            cache["reports"][tunnus] = tmp["reports"][tunnus]
            n += 1
        else:
            cache.setdefault("noReport", []).append(tunnus)  # not (yet) in VaskiData: the page link still works
        time.sleep(0.15)
    return n


def _shard(tunnus: str) -> str:
    m = re.match(r"^(\w+) \d+/(\d{4})", tunnus)
    return f"{m.group(1)}-{m.group(2)}" if m else "muut"


def load_cache() -> dict:
    """{"asiat": {...}, "reports": {...}, "noReport": [...]} from the shards."""
    out: dict = {"asiat": {}, "reports": {}, "noReport": []}
    for f in sorted(OUT.glob("*.json")) if OUT.is_dir() else []:
        d = load_json(f, {}) or {}
        out["asiat"].update(d.get("asiat") or {})
        out["reports"].update(d.get("reports") or {})
        out["noReport"] += d.get("noReport") or []
    return out


def save_cache(cache: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    shards: dict[str, dict] = {}
    for k, v in cache["asiat"].items():
        shards.setdefault(_shard(k), {})[k] = v
    for name, part in shards.items():
        save_json(OUT / f"{name}.json", {"asiat": part}, compact=True)
    save_json(OUT / "_reports.json", {"reports": cache["reports"], "noReport": sorted(set(cache.get("noReport") or []))}, compact=True)
    for f in OUT.glob("*.json"):
        if f.stem != "_reports" and f.stem not in shards:
            f.unlink()


def main():
    sys.setrecursionlimit(20000)
    cache = load_cache()
    legacy = CACHE_DIR / "asiat.json"
    if legacy.exists():  # one-off migration from the single-file cache
        old = load_json(legacy, {}) or {}
        cache["asiat"].update(old.get("asiat") or {})
        cache["reports"].update(old.get("reports") or {})
        cache["noReport"] += old.get("noReport") or []
    cache["noReport"] = (cache.get("noReport") or [])[-500:]
    now = dt.datetime.now(dt.timezone.utc)
    wanted = wanted_asiat()
    todo = [a for a in wanted if stale(cache["asiat"].get(a), now)]
    # new and active matters first, then the weekly refresh of finished ones
    todo.sort(key=lambda a: (a in cache["asiat"], cache["asiat"].get(a, {}).get("tila") == "Käsitelty"))
    log(f"asiat: {len(wanted)} seurattavaa asiaa, {len(todo)} haetaan (budjetti {BUDGET_S} s)")
    t0, done, errors, outage = time.time(), 0, 0, None
    for a in todo:
        if time.time() - t0 > BUDGET_S * 0.8:
            break
        try:
            rec = fetch_asia(a)
        except SourceOutage as e:
            outage = e
            errors += 1
            if errors >= 5:
                log(f"warn: asiat: eduskunta.fi ei vastaa – lopetetaan tältä ajolta ({e})")
                break
            continue
        except Exception as e:  # noqa: BLE001
            errors += 1
            log(f"warn: asiat: {a}: {e}")
            continue
        rec["fetched"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        cache["asiat"][a] = rec
        done += 1
        errors = 0
        time.sleep(0.3)
    reports = fetch_missing_reports(cache, t0 + BUDGET_S)
    keep = set(wanted)
    cache["asiat"] = {k: v for k, v in cache["asiat"].items() if k in keep}
    wanted_docs = {d["tunnus"] for v in cache["asiat"].values() for d in v.get("committeeDocs") or []}
    cache["reports"] = {k: v for k, v in cache["reports"].items() if k in wanted_docs}
    save_cache(cache)
    if legacy.exists():
        legacy.unlink()
    n_st = sum(len(v.get("statements") or []) for v in cache["asiat"].values())
    n_docs = len(wanted_docs)
    log(f"asiat: {done} asiaa haettu, {reports} valiokunnan lausuntoa/mietintöä lisätty; välimuistissa {len(cache['asiat'])} asiaa, "
        f"{n_st} asiantuntijalausuntoa, {n_docs} valiokunnan asiakirjaa -> {OUT}")
    if outage and not done:
        raise SourceOutage(f"asiat: eduskunta.fi ei vastaa ({outage})") from outage


if __name__ == "__main__":
    main()
