"""Valtioneuvoston Hankeikkuna: every government-proposal preparation project
(lausuntokierrokset, HE numbers, säädöskokoelma numbers, documents).

API: https://api.hankeikkuna.fi/api  (public, no key)
"""
from __future__ import annotations

import datetime as dt
import re

from common import CACHE_DIR, TODAY, SourceOutage, get_json, log, post_json, save_json

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
    except SourceOutage:
        raise  # the whole API is down: fail fast instead of waiting through every call's retries
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


NO_STATEMENT_RE = re.compile(r"ei lausu(?:ttavaa|ntoa)|inget utlåtande|ingenting att yttra", re.I)


def summarise_statements(docs: list[dict], lausuntopalvelu: str | None) -> dict | None:
    """Who answered the consultation: the LAUSUNTO documents ministries file in Hankeikkuna (organisation,
    date, PDF). Kept as a compact summary – counts, the organisations (≤80), the latest date – not the texts."""
    if not docs:
        return None
    orgs: dict[str, int] = {}
    none = 0
    latest = ""
    files = []
    for d in docs:
        org = _fi(d.get("laatija")) or _fi(d.get("nimi")).split(";")[0].strip()
        org = re.sub(r"\s*\(\d+\)\s*$", "", org).strip()
        no = bool(NO_STATEMENT_RE.search(_fi(d.get("nimi"))))
        none += no
        if org:
            orgs[org] = orgs.get(org, 0) + 1
        date = d.get("laatimispaiva") or (d.get("luotu") or "")[:10] or ""
        latest = max(latest, date)
        if d.get("uuid"):  # one row per statement for fetch_lausunnot (the PDF is read once, summarised and cached)
            files.append({k: v for k, v in {"id": d["uuid"], "org": org or None, "date": date or None, "url": d.get("url") or None,
                                            "title": _fi(d.get("nimi"))[:160] or None, "none": no or None}.items() if v})
    return {"n": len(docs), "eiLausuttavaa": none, "orgs": sorted(orgs, key=lambda o: (-orgs[o], o))[:80],
            "viimeisin": latest or None, "url": lausuntopalvelu, "docs": sorted(files, key=lambda f: f.get("date") or "", reverse=True)}


PREP_MAX = 150  # newest documents kept per project (a long työryhmä can publish a hundred pöytäkirjat)


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
    statements = []
    prep = []  # every other public document of the project (asettamispäätös, pöytäkirjat, HE-luonnos, mietintö …)
    for d in r.get("asiakirjat") or []:
        if d.get("tyyppi") != "LAUSUNTO" and d.get("url"):
            prep.append({"t": d.get("tyyppi"), "n": _fi(d.get("nimi")) or "", "u": d["url"],
                         "d": d.get("laatimispaiva") or (d.get("luotu") or "")[:10] or None})
        if d.get("tyyppi") in ("LAUSUNTOPYYNTO", "ESITYS", "YHTEENVETO") and d.get("url"):
            docs.append({"tyyppi": d["tyyppi"], "nimi": _fi(d.get("nimi")), "url": d["url"],
                         "pvm": d.get("laatimispaiva") or (d.get("luotu") or "")[:10]})
        elif d.get("tyyppi") == "LAUSUNTO":
            statements.append(d)
    lausuntopalvelu = next((_fi(l.get("url")) for l in r.get("linkit") or [] if "lausuntopalvelu" in (_fi(l.get("url")) or "")), None)
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
        "vanhaEsittelyviikko": tila.get("vanhaEsittelyviikko"),
        "vanhaEsittelyvuosi": tila.get("vanhaEsittelyvuosi"),
        "lisattyPaiva": tila.get("ilmoitettuLisattavaksiPaiva"),
        "poistettuPaiva": tila.get("ilmoitettuPoistettavaksiPaiva"),
        "kiireellinen": bool(he.get("kiireellinen")),
        "pevLausunto": he.get("perustuslakivaliokunnanLausuntoVaaditaan") == "KYLLA",
        "arviointineuvosto": bool((r.get("lainsaadanto") or {}).get("lainsaadannonArviointineuvosto")),
        "rauennut": bool(he.get("rauennut")),
        "etapit": sorted(etapit, key=lambda e: e["date"]),
        "asiakirjat": sorted(docs, key=lambda d: d["pvm"] or "")[-6:],
        "valmistelu": sorted(prep, key=lambda d: d["d"] or "")[-PREP_MAX:],
        "lausunnot": summarise_statements(statements, lausuntopalvelu),
        "url": f"https://valtioneuvosto.fi/hanke?tunnus={k.get('tunnus')}" if k.get("tunnus") else None,
    }


KUULEMINEN_GRACE_D = 30   # a closed round stays listed this many days after its deadline


def consultation_rows(r: dict, asettajat: dict) -> list[dict]:
    """Lausuntokierrokset of a project that is not a HE/asetus project (selvitykset, strategiat, työryhmät,
    talousarviot, other legislation): rows in the sector layer's consultation format."""
    k = r["kohde"]
    cut = (TODAY - dt.timedelta(days=KUULEMINEN_GRACE_D)).isoformat()
    lp = next((_fi(l.get("url")) for l in r.get("linkit") or [] if "lausuntopalvelu" in (_fi(l.get("url")) or "")), None)
    req = next((d for d in r.get("asiakirjat") or [] if d.get("tyyppi") == "LAUSUNTOPYYNTO" and d.get("url")), None)
    out = []
    for e in r.get("etapit") or []:
        if e.get("tyyppi") != "LAUSUNTOKIERROS" or not e.get("alku") or (e.get("loppu") or e["alku"]) < cut:
            continue
        name = _fi(k.get("nimi"))
        out.append({"id": f"hk-{k['uuid'][:8]}-{e.get('uuid', '')[:6]}", "source": "hankeikkuna_kuulemiset",
                    "authority": asettajat.get(k.get("asettajaUuid"), "") or "Valtioneuvosto", "scope": "fi", "laji": "kuuleminen",
                    "kind": "Lausuntokierros", "ref": k.get("tunnus"), "title": name, "summary": _fi(k.get("tiivistelma")) or _fi(k.get("kuvaus")),
                    "date": e["alku"], "deadline": e.get("loppu"), "lausuntopalvelu": lp,
                    "pdfUrl": req["url"] if req else None,
                    "url": f"https://valtioneuvosto.fi/hanke?tunnus={k.get('tunnus')}" if k.get("tunnus") else (lp or ""),
                    "keywords": [_fi(a) if isinstance(a, dict) else str(a) for a in r.get("asiasanat") or []][:8]})
    return [{kk: v for kk, v in row.items() if v not in (None, "", [])} for row in out if row["url"]]


def fetch_consultations(asettajat: dict, since: str) -> list[dict]:
    """Every other project with a lausuntokierros: lausuntopalvelu.fi itself is closed to automated reads
    (Cloudflare), but the ministries record their rounds in Hankeikkuna."""
    rows, seen = [], set()
    for body in ({"tyyppi": ["HANKE", "STRATEGIA", "TOIMIELIN"], "tila": ["KAYNNISSA"]},
                 {"tyyppi": ["HANKE", "STRATEGIA", "TOIMIELIN"], "tila": ["PAATTYNYT"], "muokattuPaivaAlku": since},
                 {"tyyppi": ["LAINSAADANTO"], "tila": ["KAYNNISSA"]},
                 {"tyyppi": ["LAINSAADANTO"], "tila": ["PAATTYNYT"], "muokattuPaivaAlku": since}):
        for r in search(body):
            luokka = (r.get("lainsaadanto") or {}).get("tehtavaluokka")
            if r["kohde"].get("tyyppi") == "LAINSAADANTO" and luokka in ("HALLITUKSEN_ESITYKSEN_VALMISTELU", "ASETUKSEN_ANTAMINEN"):
                continue  # the HE and asetus projects are items of their own
            if r["kohde"]["uuid"] in seen:
                continue
            seen.add(r["kohde"]["uuid"])
            rows += consultation_rows(r, asettajat)
    return rows


def main():
    teemat = _lookup("teemat")
    asettajat = _lookup("asettajat")
    log(f"hankeikkuna: {len(teemat)} teemaa, {len(asettajat)} asettajaa")
    since = (TODAY - dt.timedelta(days=540)).isoformat() + "T00:00:00"
    seen, items = set(), []
    for laji, luokka in (("laki", "HALLITUKSEN_ESITYKSEN_VALMISTELU"), ("asetus", "ASETUKSEN_ANTAMINEN")):
        base = {"tyyppi": ["LAINSAADANTO"], "lainsaadantoTehtavaluokka": [luokka]}
        ongoing = search(dict(base, tila=["KAYNNISSA"]))
        finished = search(dict(base, tila=["PAATTYNYT"], muokattuPaivaAlku=since))
        log(f"hankeikkuna {laji}: {len(ongoing)} käynnissä, {len(finished)} päättynyt (muokattu {since[:10]} jälkeen)")
        for r in ongoing + finished:
            if r["kohde"]["uuid"] in seen:
                continue
            seen.add(r["kohde"]["uuid"])
            rec = normalise(r, teemat, asettajat)
            rec["laji"] = laji
            items.append(rec)
    kuul_since = (TODAY - dt.timedelta(days=120)).isoformat() + "T00:00:00"
    try:
        kuulemiset = fetch_consultations(asettajat, kuul_since)
    except SourceOutage:
        raise
    except Exception as e:  # noqa: BLE001 – the HE/asetus projects are saved even if this extra query fails
        log(f"warn: hankeikkuna: muiden hankkeiden lausuntokierrokset epäonnistuivat: {e}")
        from common import load_json
        kuulemiset = (load_json(OUT, {}) or {}).get("kuulemiset") or []
    save_json(OUT, {"fetched": dt.datetime.now().isoformat(timespec="seconds"), "items": items, "kuulemiset": kuulemiset})
    log(f"hankeikkuna: tallennettu {len(items)} hanketta ja {len(kuulemiset)} muun hankkeen lausuntokierrosta -> {OUT}")


if __name__ == "__main__":
    main()
