"""Hallituksen esitysten käsittely täysistunnossa: eduskunnan vastauksen lausumat, äänestykset puolueittain ja
puheenvuorojen määrät käsittelyvaiheittain. Kaikki eduskunnan avoimesta datasta (avoindata.eduskunta.fi):

* SaliDBKohtaAsiakirja (LinkkiTekstiFI = "HE n/yyyy vp") -> asian täysistuntokohdat; SaliDBKohta antaa vaiheen
  (lähetekeskustelu, ensimmäinen/toinen käsittely …) ja SaliDBIstunto istunnon päivän; SaliDBPuheenvuoro kohdan
  puheenvuorot eduskuntaryhmän lyhenteineen.
* SaliDBAanestys (AanestysValtiopaivaasia = "HE n/yyyy vp") -> asian äänestykset; SaliDBAanestysJakauma tulos
  eduskuntaryhmittäin sekä hallitus- ja oppositioryhmät yhteensä.
* VaskiData: HE:n käsittelytiedoista eduskunnan vastauksen tunnus (EV n/yyyy vp) ja vastauksesta hyväksytyt
  lausumat (<LausumaKannanotto>: "Eduskunta edellyttää, että …").

Välimuisti data/cache/taysistunto.json {"he": {"n/yyyy": {checked, final, ev, lausumat, kasittelyt, aanestykset}},
"istunnot": {"2026/64": "2026-06-11"}}. Kesken oleva asia luetaan uudelleen kerran päivässä; asia, jonka vastaus on
annettu ja joka on luettu sen jälkeen, on valmis eikä sitä enää haeta. Ajossa käsitellään enintään MAX_PER_RUN asiaa
ja BUDGET_S sekuntia (uusimmat ja kesken olevat ensin).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import time

from common import CACHE_DIR, SourceOutage, get_json, load_json, log, save_json

API = "https://avoindata.eduskunta.fi/api/v1/tables/"
OUT = CACHE_DIR / "taysistunto.json"
MAX_PER_RUN = int(os.environ.get("TAYSISTUNTO_MAX", "60"))
BUDGET_S = int(os.environ.get("TAYSISTUNTO_BUDGET_S", "300"))
FIRST_YEAR = 2023  # the current electoral term's matters; older HEs are not on the page as open items
VERSION = 1

# SaliDBAanestysJakauma names the groups in full; the page shows the usual abbreviations
PARTY = [("kokoomuksen", "kok"), ("Perussuomalaisten", "ps"), ("Sosialidemokraattinen", "sd"), ("Keskustan", "kesk"),
         ("Vihreä", "vihr"), ("Vasemmistoliiton", "vas"), ("Ruotsalainen", "r"), ("Kristillisdemokraattinen", "kd"),
         ("Liike Nyt", "liik"), ("kuulumaton", "ei ryhmää")]
STAGE_ORDER = ["Lähetekeskustelu", "Ensimmäinen käsittely", "Jatkettu ensimmäinen käsittely", "Toinen käsittely",
               "Ainoa käsittely", "Osittain toinen, osittain ainoa käsittely"]
LAUSUMA = re.compile(r"<(?:\w+:)?LausumaKannanotto\b[^>]*>(.*?)</(?:\w+:)?LausumaKannanotto>", re.S)
EV_REF = re.compile(r"\bEV (\d+)/(\d{4}) vp\b")


def _rows(table: str, col: str, val: str, per_page: int = 100, max_pages: int = 20) -> list[dict]:
    out = []
    for page in range(max_pages):
        d = get_json(API + table + "/rows", params={"perPage": per_page, "page": page, "columnName": col, "columnValue": val},
                     timeout=90)
        cols = d.get("columnNames") or []
        out += [dict(zip(cols, r)) for r in d.get("rowData") or []]
        if not d.get("hasMore"):
            break
    return out


def _int(x) -> int:
    try:
        return int(str(x or "0").strip() or 0)
    except ValueError:
        return 0


def local_date(ts: str | None) -> str | None:
    """The tables store the session day as UTC midnight of the Finnish day ("2026-06-10 21:00:00" = 11.6.)."""
    if not ts:
        return None
    try:
        t = dt.datetime.fromisoformat(ts.strip()[:19])
    except ValueError:
        return ts[:10]
    return (t + dt.timedelta(hours=3)).date().isoformat()


def party(name: str) -> str | None:
    for key, short in PARTY:
        if key.lower() in (name or "").lower():
            return short
    return None


def flat(xml: str) -> str:
    t = re.sub(r"<[^>]+>", " ", xml)
    t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def lausumat(xml: str) -> list[str]:
    """Statements the parliament attached to its answer, in order, without duplicates."""
    out = []
    for m in LAUSUMA.finditer(xml or ""):
        t = flat(m.group(1))
        if t and t not in out:
            out.append(t)
    return out


def vote_row(a: dict, jakauma: list[dict]) -> dict:
    groups, blocs = [], {}
    for j in jakauma:
        res = [_int(j.get("Jaa")), _int(j.get("Ei")), _int(j.get("Tyhjia")), _int(j.get("Poissa"))]
        if j.get("Tyyppi") == "eduskuntaryhma":
            p = party(j.get("Ryhma") or "")
            groups.append([p or (j.get("Ryhma") or "").replace(" eduskuntaryhmä", "").replace("Eduskuntaryhmä ", ""), *res])
        elif j.get("Tyyppi") == "hallitusoppositio":
            blocs["hallitus" if "Hallitus" in (j.get("Ryhma") or "") else "oppositio"] = res
    url = a.get("AanestysPoytakirjaUrl") or ""
    rec = {"id": a.get("AanestysId"), "date": local_date(a.get("IstuntoPvm")), "vaihe": (a.get("KohtaKasittelyVaihe") or "").strip(),
           "otsikko": (a.get("AanestysOtsikko") or "").strip(),
           "tulos": [_int(a.get("AanestysTulosJaa")), _int(a.get("AanestysTulosEi")), _int(a.get("AanestysTulosTyhjia")),
                     _int(a.get("AanestysTulosPoissa"))],
           "ryhmat": sorted(groups, key=lambda g: -(g[1] + g[2] + g[3])),
           "url": ("https://www.eduskunta.fi" + url) if url.startswith("/") else (url or None)}
    rec.update(blocs)
    return rec


def read_matter(he: str, cache: dict) -> dict:
    tunnus = f"HE {he} vp"
    istunnot = cache.setdefault("istunnot", {})
    kas = {}
    for k in _rows("SaliDBKohtaAsiakirja", "LinkkiTekstiFI", tunnus):
        key = k.get("KohtaTekninenAvain")
        if not key or key in kas:
            continue
        kohta = next(iter(_rows("SaliDBKohta", "TekninenAvain", key)), None)
        if not kohta:
            continue
        vaihe = (kohta.get("KasittelyotsikkoFI") or "").strip()
        if not vaihe or "pöydällepano" in vaihe.lower():
            continue
        ist = kohta.get("IstuntoTekninenAvain") or ""
        if ist and ist not in istunnot:
            i = next(iter(_rows("SaliDBIstunto", "TekninenAvain", ist)), None)
            istunnot[ist] = ((i.get("IstuntoIlmoitettuAlkuaika") or "")[:10] or local_date(i.get("IstuntoPvm"))) if i else None
        pv = _rows("SaliDBPuheenvuoro", "KohtaTekninenAvain", key)
        spoke = [p for p in pv if str(p.get("Puhunut") or "").strip() != "0"]
        ryhmat: dict[str, int] = {}
        for p in spoke:
            g = (p.get("RyhmaLyhenneFI") or "").strip() or ("ministeri" if (p.get("MinisteriysFI") or "").strip() else "muu")
            ryhmat[g] = ryhmat.get(g, 0) + 1
        kas[key] = {"vaihe": vaihe, "istunto": ist, "date": istunnot.get(ist), "puheenvuorot": len(spoke),
                    "ryhmat": dict(sorted(ryhmat.items(), key=lambda kv: -kv[1]))}
    # a stage that continues in a later session ("ensimmäinen käsittely" 11.6. and its vote 12.6.) is one stage
    merged: dict[str, dict] = {}
    for k in sorted(kas.values(), key=lambda k: k.get("date") or ""):
        m = merged.get(k["vaihe"])
        if not m:
            merged[k["vaihe"]] = {**k, "ryhmat": dict(k["ryhmat"])}
            continue
        m["puheenvuorot"] += k["puheenvuorot"]
        for g, n in k["ryhmat"].items():
            m["ryhmat"][g] = m["ryhmat"].get(g, 0) + n
        if k.get("date") and k["date"] != m.get("date"):
            m["end"] = k["date"]
    for m in merged.values():
        m["ryhmat"] = dict(sorted(m["ryhmat"].items(), key=lambda kv: -kv[1]))
        m.pop("istunto", None)
    order = {s: i for i, s in enumerate(STAGE_ORDER)}
    kasittelyt = sorted(merged.values(), key=lambda k: (k.get("date") or "", order.get(k["vaihe"], 9)))
    votes = []
    for a in _rows("SaliDBAanestys", "AanestysValtiopaivaasia", tunnus):
        if str(a.get("KieliId")) != "1" or str(a.get("AanestysMitatoity") or "0").strip() == "1":
            continue
        votes.append(vote_row(a, _rows("SaliDBAanestysJakauma", "AanestysId", a["AanestysId"])))
    votes.sort(key=lambda v: (v.get("date") or "", int(v.get("id") or 0)))
    return {"kasittelyt": kasittelyt, "aanestykset": votes}


def read_answer(he: str) -> tuple[str | None, list[str]]:
    from fetch_vaski import fetch_by_tunnus
    ev = None
    for r in fetch_by_tunnus(f"HE {he} vp"):
        m = EV_REF.search(r[1] or "")
        if m:
            ev = f"EV {m.group(1)}/{m.group(2)} vp"
            break
    if not ev:
        return None, []
    rows = fetch_by_tunnus(ev)
    doc = max(rows, key=lambda r: len(r[1] or ""), default=None)
    return ev, lausumat(doc[1] if doc else "")


def wanted(ek: dict) -> list[tuple[str, dict]]:
    out = []
    for num, rec in ek.items():
        try:
            year = int(num.split("/")[1])
        except (IndexError, ValueError):
            continue
        if year < FIRST_YEAR:
            continue
        codes = {s.get("code") for s in rec.get("stages") or []}
        if codes - {"ANTO"}:  # something has happened in the plenary
            out.append((num, rec))
    return out


def ev_date(rec: dict) -> str | None:
    return next((s.get("date") for s in reversed(rec.get("stages") or []) if s.get("code") == "EV"), None)


def main() -> None:
    ek = (load_json(CACHE_DIR / "eduskunta.json", {}) or {}).get("items") or {}
    cache = load_json(OUT, {}) or {}
    he = cache.setdefault("he", {})
    today = dt.date.today().isoformat()

    def due(num: str, rec: dict) -> bool:
        c = he.get(num)
        if not c or int(c.get("v") or 0) < VERSION:
            return True
        if c.get("final"):
            return False
        last = max((st.get("date") or "" for st in rec.get("stages") or []), default="")
        quiet = last and (dt.date.today() - dt.date.fromisoformat(last[:10])).days > 60
        if quiet:  # nothing has happened for two months (lapsed, or waiting): weekly is enough
            return (dt.date.today() - dt.date.fromisoformat(c.get("checked") or "2000-01-01")).days >= 7
        return (c.get("checked") or "") < today

    todo = [(n, r) for n, r in wanted(ek) if due(n, r)]
    # matters with no record first, then the ones still in the plenary, newest first
    todo.sort(key=lambda nr: (nr[0] in he, -int(nr[0].split("/")[1]), -int(nr[0].split("/")[0])))
    log(f"täysistunto: {len(he)} asiaa välimuistissa, {len(todo)} luettavana")
    t0, done, outage = time.time(), 0, None
    for num, rec in todo[:MAX_PER_RUN]:
        if time.time() - t0 > BUDGET_S:
            break
        try:
            row = read_matter(num, cache)
            evd = ev_date(rec)
            ev, lau = (None, [])
            if evd:
                ev, lau = read_answer(num)
        except SourceOutage as e:
            outage = e
            break
        except Exception as e:  # noqa: BLE001 – one matter must not stop the rest
            log(f"warn: täysistunto HE {num}: {e}")
            continue
        row.update({"checked": today, "v": VERSION})
        if ev:
            row["ev"], row["lausumat"] = ev, lau
        # done when the answer is out and has been read at least a few days after it (late votes/minutes are in)
        row["final"] = bool(ev and evd and (dt.date.fromisoformat(today) - dt.date.fromisoformat(evd)).days >= 3)
        he[num] = row
        done += 1
        if done % 25 == 0:  # a long first fill keeps what it has read so far
            save_json(OUT, cache)
    cache["fetched"] = dt.datetime.now().isoformat(timespec="seconds")
    save_json(OUT, cache)
    n_v = sum(len(v.get("aanestykset") or []) for v in he.values())
    n_l = sum(len(v.get("lausumat") or []) for v in he.values())
    log(f"täysistunto: {done} asiaa luettu; yhteensä {len(he)} asiaa, {n_v} äänestystä, {n_l} lausumaa -> {OUT}")
    if outage and not done:
        raise SourceOutage(f"eduskunnan avoin data ei vastaa: {outage}")


if __name__ == "__main__":
    main()
