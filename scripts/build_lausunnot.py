"""Annetut lausunnot sivulle: yksi tiedosto per säädös (docs/data/lausunnot/<id>.json), joka ladataan vasta
kun rivi avataan, ja rivin omiin tietoihin pieni yhteenveto (kantojen lukumäärät) merkkejä varten.

Lähteenä fetch_lausunnot-välimuisti (tiivistelmä ja kanta per asiakirja), johon yhdistetään
* Hankeikkunan lausuntokierroksen lausunnot (`lausunnot.docs`: järjestö, päivä, PDF) ja
* eduskunnan valiokuntien asiantuntijalausunnot (Vaski `statements`) – HE:t, U/E-kirjelmät (myös EU-ehdotuksen
  `kirjelmat`), lakialoitteet, kansalaisaloitteet ja muut asiat, joiden tunnus on rivin viite.

Tiedoston rakenne:
{"id", "kierros": {"n", "kannat": {kanta: n}, "rivit": [{"org", "date", "stance", "gist", "url", "none"}]},
 "eduskunta": {"n", "kannat", "rivit": [{"org", "person", "committee", "date", "stance", "gist", "url"}]},
 "tiivistetty": <luettujen määrä>, "odottaa": <vielä lukematta>}
Rivit järjestetään kannan mukaan (vastustavat ensin, sitten varaukselliset, muutosehdotukset, kannattavat,
muut kannanotot, virkamiesesittelyt, "ei lausuttavaa" viimeisenä) ja kunkin ryhmän sisällä uusin ensin.
"""
from __future__ import annotations

import re

from common import OUT_DIR, log, save_json
from fetch_lausunnot import load_docs

LAUSUNNOT_DIR = OUT_DIR / "lausunnot"
ORDER = {"vastustaa": 0, "osin": 1, "varauksin": 2, "muutoksia": 3, "kannattaa": 4, "kanta": 5, None: 6, "esittely": 7, "ei": 8}
PER_FILE = 1000


def _norm(ref: str) -> str:
    return re.sub(r"\s+vp$", "", (ref or "").strip())


def parliament_keys(it: dict) -> set[str]:
    """Vaski asia ids this item answers to: its HE numbers, its own reference (E/U/LA/KAA … letters and
    motions) and the U/E-kirjelmät linked to an EU proposal."""
    keys = {f"HE {h}" for h in it.get("heNumerot") or []}
    ref = _norm(it.get("ref") or "")
    if re.match(r"^(HE|U|E|UTP|VNS|VNT|K|O|LA|KAA|TPA|TAA|LTA|M) \d+/\d{4}$", ref):
        keys.add(ref)
    keys.update(_norm(k) for k in it.get("kirjelmat") or [])
    return keys


def _row(doc: dict, summ: dict | None, extra: dict) -> dict:
    row = {"org": doc.get("org"), "date": doc.get("date"), "url": doc.get("url"), **extra}
    if doc.get("none"):
        row["stance"] = "ei"
    if not doc.get("url"):
        row["noFile"] = True   # metadata only (the ministry did not publish the file): nothing to summarise
        row["read"] = True
    if summ:
        if summ.get("ok") is True:
            row["stance"] = summ.get("stance") or row.get("stance")
            if summ.get("gist"):
                row["gist"] = summ["gist"]
        elif summ.get("ok") == "noText":
            row["stance"] = summ.get("stance") or row.get("stance")
            row["noText"] = True
        elif summ.get("ok") in ("error", "notPdf"):
            row["fetchError"] = True   # the link does not lead to a readable file (retried on later runs)
        row["read"] = True
    return {k: v for k, v in row.items() if v not in (None, "", False)}


def _section(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    rows.sort(key=lambda r: (ORDER.get(r.get("stance"), 6), "".join(chr(0x10FFFF - ord(c)) for c in (r.get("date") or ""))))
    kannat: dict[str, int] = {}
    for r in rows:
        if r.get("stance"):
            kannat[r["stance"]] = kannat.get(r["stance"], 0) + 1
    return {"n": len(rows), "kannat": kannat, "luettu": sum(1 for r in rows if r.get("read")), "rivit": rows[:PER_FILE]}


def build_lausunnot(items: list[dict], hk_by_uuid: dict, vaski: dict) -> dict[str, dict]:
    """Writes docs/data/lausunnot/<id>.json for every item that has statements; returns {item_id: summary}
    where summary = {"n", "luettu", "kannat"} for the item's own record."""
    cache = load_docs()
    statements: dict[str, list] = {}
    for k, lst in (vaski.get("statements") or {}).items():
        statements.setdefault(_norm(k), []).extend(lst)
    LAUSUNNOT_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict] = {}
    keep: set[str] = set()
    for it in items:
        doc: dict = {"id": it["id"]}
        p = hk_by_uuid.get(it.get("hankeUuid") or "")
        if p and (p.get("lausunnot") or {}).get("docs"):
            rows = [_row(d, cache.get(d["id"]), {}) for d in p["lausunnot"]["docs"]]
            sec = _section(rows)
            if sec:
                sec["url"] = (p["lausunnot"] or {}).get("url")
                doc["kierros"] = sec
        rows, seen = [], set()
        for key in sorted(parliament_keys(it)):
            for s in statements.get(key) or []:
                sid = s.get("edk") or s.get("url")
                if sid in seen:
                    continue
                seen.add(sid)
                rows.append(_row({"org": s.get("org") or s.get("person"), "date": s.get("date"), "url": s.get("url")}, cache.get(sid),
                                 {"person": s.get("person"), "committee": s.get("committee"), "asia": key if key != _norm(it.get("ref") or "") and not key.startswith("HE ") else None}))
        sec = _section(rows)
        if sec:
            doc["eduskunta"] = sec
        if "kierros" not in doc and "eduskunta" not in doc:
            continue
        n = sum(doc[k]["n"] for k in ("kierros", "eduskunta") if k in doc)
        read = sum(doc[k]["luettu"] for k in ("kierros", "eduskunta") if k in doc)
        kannat: dict[str, int] = {}
        for k in ("kierros", "eduskunta"):
            for st, c in (doc.get(k) or {}).get("kannat", {}).items():
                kannat[st] = kannat.get(st, 0) + c
        doc["tiivistetty"], doc["odottaa"] = read, n - read
        save_json(LAUSUNNOT_DIR / f"{it['id']}.json", doc, compact=True)
        keep.add(f"{it['id']}.json")
        out[it["id"]] = {"n": n, "luettu": read, "kannat": kannat}
    for f in LAUSUNNOT_DIR.glob("*.json"):
        if f.name not in keep:
            f.unlink()
    total = sum(f.stat().st_size for f in LAUSUNNOT_DIR.glob("*.json"))
    read_all = sum(v["luettu"] for v in out.values())
    n_all = sum(v["n"] for v in out.values())
    log(f"lausunnot: {len(out)} säädöstä, {n_all} lausuntoa, {read_all} tiivistetty ({total / 1e6:.1f} MB) -> {LAUSUNNOT_DIR}")
    return out
