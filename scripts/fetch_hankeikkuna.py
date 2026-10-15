"""Valtioneuvoston Hankeikkuna: every government-proposal preparation project
(lausuntokierrokset, HE numbers, säädöskokoelma numbers, documents).

API: https://api.hankeikkuna.fi/api  (public, no key)
"""
from __future__ import annotations

import datetime as dt

from common import CACHE_DIR, TODAY, get_json, log, post_json, save_json

API = "https://api.hankeikkuna.fi/api/v2"
OUT = CACHE_DIR / "hankeikkuna.json"

ETAPPI_KINDS = {
    "LAUSUNTOKIERROS": ("Lausuntokierros", "lausunto"),
    "KUULEMISTILAISUUS": ("Kuulemistilaisuus", "muu"),
    "VERKKOKESKUSTELU": ("Verkkokeskustelu", "muu"),
    "SAADOS": ("Säädös", "muu"),
}


def _fi(x):
    if isinstance(x, dict):
        return (x.get("fi") or x.get("sv") or x.get("en") or "").strip()
    return (x or "").strip() if isinstance(x, str) else ""


def _lookup(path: str) -> dict[str, str]:
    """uuid -> Finnish name for teemat / asettajat."""
    try:
        data = get_json(f"{API}/{path}")
    except Exception as e:  # noqa: BLE001
        log(f"warn: {path} lookup failed: {e}")
        return {}
    rows = data.get("result", data) if isinstance(data, dict) else data
    out = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        uuid = row.get("uuid")
        name = _fi(row.get("nimi")) or _fi(row.get("otsikko"))
        if uuid and name:
            out[uuid] = name
    return out


def search(body: dict) -> list[dict]:
    """POST /kohteet/haku with searchAfter pagination."""
    results, search_after = [], None
    while True:
        payload = dict(body, size=1000)
        if search_after:
            payload["searchAfter"] = search_after
        data = post_json(f"{API}/kohteet/haku", payload, timeout=120)
        batch = data.get("result", [])
        results.extend(batch)
        search_after = data.get("nextSearchAfter")
        if not batch or not search_after or len(batch) < 1000:
            break
    return results


def normalise(r: dict, teemat: dict, asettajat: dict) -> dict:
    k = r["kohde"]
    he = (r.get("lainsaadanto") or {}).get("heTiedot") or {}
    tila = (he.get("tilatiedot") or [{}])[-1] if he.get("tilatiedot") else {}
    etapit = []
    for e in r.get("etapit") or []:
        if e.get("tyyppi") not in ETAPPI_KINDS or not e.get("alku"):
            continue
        label, kind = ETAPPI_KINDS[e["tyyppi"]]
        etapit.append({"date": e["alku"], "end": e.get("loppu"), "label": _fi(e.get("nimi")) or label,
                       "kind": kind, "tyyppi": e["tyyppi"]})
    docs = []
    for d in r.get("asiakirjat") or []:
        if d.get("tyyppi") in ("LAUSUNTOPYYNTO", "ESITYS", "YHTEENVETO") and d.get("url"):
            docs.append({"tyyppi": d["tyyppi"], "nimi": _fi(d.get("nimi")), "url": d["url"],
                         "pvm": d.get("laatimispaiva") or (d.get("luotu") or "")[:10]})
    return {
        "uuid": k["uuid"],
        "tunnus": k.get("tunnus"),
        "nimi": _fi(k.get("nimi")),
        "tiivistelma": _fi(k.get("tiivistelma")) or _fi(k.get("kuvaus")),
        "ministerio": asettajat.get(k.get("asettajaUuid"), ""),
        "teemat": [teemat[t] for t in k.get("teemaUuids") or [] if t in teemat],
        "asiasanat": [_fi(a) if isinstance(a, dict) else str(a) for a in r.get("asiasanat") or []][:12],
        "valmisteluvaihe": k.get("valmisteluvaihe"),
        "tila": k.get("tila"),
        "asetettu": k.get("asettamisPaiva"),
        "valmistumisPaiva": k.get("valmistumisPaiva"),
        "muokattu": k.get("muokattu"),
        "heNumerot": he.get("heNumerot") or [],
        "skNumerot": he.get("skNumerot") or [],
        "evNumerot": he.get("evNumerot") or [],
        "heTila": ((tila.get("heTila") or {}).get("tila")),
        "annettuEduskunnalle": tila.get("annettuEduskunnallePaiva"),
        "esittelyvuosi": tila.get("esittelyvuosi"),
        "esittelyviikko": tila.get("esittelyviikko"),
        "rauennut": bool(he.get("rauennut")),
        "etapit": sorted(etapit, key=lambda e: e["date"]),
        "asiakirjat": sorted(docs, key=lambda d: d["pvm"] or "")[-6:],
        "url": f"https://valtioneuvosto.fi/hanke?tunnus={k.get('tunnus')}" if k.get("tunnus") else None,
    }


def main():
    teemat = _lookup("teemat")
    asettajat = _lookup("asettajat")
    log(f"hankeikkuna: {len(teemat)} teemaa, {len(asettajat)} asettajaa")
    since = (TODAY - dt.timedelta(days=540)).isoformat() + "T00:00:00"
    base = {"tyyppi": ["LAINSAADANTO"], "lainsaadantoTehtavaluokka": ["HALLITUKSEN_ESITYKSEN_VALMISTELU"]}
    ongoing = search(dict(base, tila=["KAYNNISSA"]))
    finished = search(dict(base, tila=["PAATTYNYT"], muokattuPaivaAlku=since))
    log(f"hankeikkuna: {len(ongoing)} käynnissä, {len(finished)} päättynyt (muokattu {since[:10]} jälkeen)")
    seen, items = set(), []
    for r in ongoing + finished:
        if r["kohde"]["uuid"] in seen:
            continue
        seen.add(r["kohde"]["uuid"])
        items.append(normalise(r, teemat, asettajat))
    save_json(OUT, {"fetched": dt.datetime.now().isoformat(timespec="seconds"), "items": items})
    log(f"hankeikkuna: tallennettu {len(items)} hanketta -> {OUT}")


if __name__ == "__main__":
    main()
