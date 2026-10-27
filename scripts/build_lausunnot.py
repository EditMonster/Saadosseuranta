"""Annetut lausunnot sivulle: yksi tiedosto per säädös (docs/data/lausunnot/<id>.json), joka ladataan vasta
kun rivi avataan, ja rivin omiin tietoihin pieni yhteenveto (kantojen lukumäärät) merkkejä varten.

Lähteenä fetch_lausunnot-välimuisti (tiivistelmä ja kanta per asiakirja), johon yhdistetään
* Hankeikkunan lausuntokierroksen lausunnot (`lausunnot.docs`: järjestö, päivä, PDF) ja
* eduskunnan valiokuntien asiantuntijalausunnot – HE:t, U/E-kirjelmät (myös EU-ehdotuksen `kirjelmat`), lakialoitteet,
  kansalaisaloitteet ja muut asiat, joiden tunnus on rivin viite: eduskunta.fi:n asiasivuilta kaikki valiokunnat ja
  jaostot (fetch_asiat, data/cache/asiat/) yhdistettynä VaskiData-syötteeseen (fetch_vaski), sekä
* valiokuntien omat lausunnot ja mietinnöt (PeVL, YmVL … / …M): päätösosa tiivistelmänä, muutetut pykälät ja
  vastalauseet (VaskiData-jäsennys fetch_vaski.parse_report, puuttuvat haettu fetch_asiatissa).

Tiedoston rakenne:
{"id", "kierros": {"n", "kannat": {kanta: n}, "rivit": [{"org", "date", "stance", "gist", "url", "none"}]},
 "eduskunta": {"n", "kannat", "rivit": [{"org", "person", "committee", "date", "stance", "gist", "url", "kind"}]},
 "valiokunnat": [{"tunnus", "kind", "committee", "committeeName", "date", "decision", "gist" (ponsi), "view" (valiokunnan
                  oma kanta asiakirjasta), "yhtyy" (yhtyy valtioneuvoston kantaan), "changedSections", "dissent", "url"}],
 "tiivistetty": <luettujen määrä>, "odottaa": <vielä lukematta>}
Rivit järjestetään kannan mukaan (vastustavat ensin, sitten varaukselliset, muutosehdotukset, kannattavat,
muut kannanotot, virkamiesesittelyt, "ei lausuttavaa" viimeisenä) ja kunkin ryhmän sisällä uusin ensin.
"""
from __future__ import annotations

import re

from common import OUT_DIR, log, save_json
from fetch_lausunnot import load_docs

COMMITTEE_NAMES = {
    "PeV": "perustuslakivaliokunta", "UaV": "ulkoasiainvaliokunta", "VaV": "valtiovarainvaliokunta", "TrV": "tarkastusvaliokunta",
    "HaV": "hallintovaliokunta", "LaV": "lakivaliokunta", "LiV": "liikenne- ja viestintävaliokunta", "MmV": "maa- ja metsätalousvaliokunta",
    "PuV": "puolustusvaliokunta", "SiV": "sivistysvaliokunta", "StV": "sosiaali- ja terveysvaliokunta", "TaV": "talousvaliokunta",
    "TiV": "tiedusteluvalvontavaliokunta", "TuV": "tulevaisuusvaliokunta", "TyV": "työelämä- ja tasa-arvovaliokunta",
    "YmV": "ympäristövaliokunta", "SuV": "suuri valiokunta"}
DOC_URL = "https://www.eduskunta.fi/valtiopaivaasiakirjat/{}"

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


GENERIC_PONSI = re.compile(r"^(että )?\w+valiokunta ottaa (edellä (olevan|esitetyn|todetun)|lausunnossa esitetyn) huomioon\.?$|"
                           r"^(että )?(se|valiokunta) yhtyy (asiassa )?valtioneuvoston kantaan\.?$|^ottaa edellä olevan huomioon", re.I)


def committee_row(d: dict, rep: dict | None, summ: dict | None = None) -> dict:
    """A committee opinion/report: its decision part (ponsi) and the sentence stating the committee's own view
    (read from the document by fetch_lausunnot). A boilerplate ponsi ("ottaa edellä olevan huomioon") is dropped."""
    rep = rep or {}
    abbr = d.get("committee") or rep.get("committee")
    ponsi = re.sub(r"\s+", " ", rep.get("decisionText") or "").strip()
    if ponsi and len(ponsi) > 420:
        ponsi = ponsi[:420].rsplit(" ", 1)[0].rstrip(",;:") + " …"
    view = (summ or {}).get("gist") if (summ or {}).get("ok") is True else None
    gist = ponsi if ponsi and not GENERIC_PONSI.search(ponsi) else None
    row = {"tunnus": d["tunnus"], "kind": d.get("kind") or rep.get("kind"), "committee": abbr,
           "committeeName": COMMITTEE_NAMES.get(abbr or "") or rep.get("committeeName"), "date": d.get("date") or rep.get("date"),
           "decision": rep.get("decision") if rep.get("decision") not in (None, "muu") else None, "gist": gist or None,
           "view": view if view and view != gist else None, "yhtyy": True if ponsi and re.search(r"yhtyy .*valtioneuvoston kantaan", ponsi) else None,
           "changedSections": (rep.get("changedSections") or [])[:12] or None, "dissent": rep.get("dissent") or None,
           "dissentParties": rep.get("dissentParties") or None, "url": DOC_URL.format(d["tunnus"].replace(" vp", "").replace(" ", "+"))}
    return {k: v for k, v in row.items() if v not in (None, "", [], 0)}


def build_lausunnot(items: list[dict], hk_by_uuid: dict, vaski: dict, asiat: dict | None = None) -> dict[str, dict]:
    """Writes docs/data/lausunnot/<id>.json for every item that has statements or committee documents; returns
    {item_id: summary} where summary = {"n", "luettu", "kannat", "valiokunnat"} for the item's own record."""
    cache = load_docs()
    if asiat is None:
        from fetch_asiat import load_cache
        asiat = load_cache()
    statements: dict[str, list] = {}
    for k, lst in (vaski.get("statements") or {}).items():
        statements.setdefault(_norm(k), []).extend(lst)
    for k, a in (asiat.get("asiat") or {}).items():
        statements.setdefault(_norm(k), []).extend(a.get("statements") or [])
    reports = {**(vaski.get("reports") or {}), **(asiat.get("reports") or {})}
    committee_docs: dict[str, list] = {}
    for k, a in (asiat.get("asiat") or {}).items():
        committee_docs[_norm(k)] = a.get("committeeDocs") or []
    for t, r in (vaski.get("reports") or {}).items():  # reports VaskiData saw for a matter the asia pages have not listed yet
        if r.get("asia") and not any(d["tunnus"] == t for d in committee_docs.get(_norm(r["asia"]), [])):
            committee_docs.setdefault(_norm(r["asia"]), []).append({"tunnus": t, "kind": r.get("kind"), "date": r.get("date"), "committee": r.get("committee")})
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
                                 {"person": s.get("person"), "committee": s.get("committee"), "kind": s.get("kind"),
                                  "asia": key if key != _norm(it.get("ref") or "") and not key.startswith("HE ") else None}))
        sec = _section(rows)
        if sec:
            doc["eduskunta"] = sec
        vk, seen_vk = [], set()
        for key in sorted(parliament_keys(it)):
            for d in committee_docs.get(key) or []:
                if d["tunnus"] in seen_vk:
                    continue
                seen_vk.add(d["tunnus"])
                vk.append(committee_row(d, reports.get(d["tunnus"]), cache.get(d["tunnus"])))
        if vk:
            # opinions first (they come before the lead committee's report), then by date
            doc["valiokunnat"] = sorted(vk, key=lambda r: (r.get("kind") == "mietintö", r.get("date") or "", r["tunnus"]))
        if "kierros" not in doc and "eduskunta" not in doc and "valiokunnat" not in doc:
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
        out[it["id"]] = {"n": n, "luettu": read, "kannat": kannat, "valiokunnat": len(doc.get("valiokunnat") or [])}
    for f in LAUSUNNOT_DIR.glob("*.json"):
        if f.name not in keep:
            f.unlink()
    total = sum(f.stat().st_size for f in LAUSUNNOT_DIR.glob("*.json"))
    read_all = sum(v["luettu"] for v in out.values())
    n_all = sum(v["n"] for v in out.values())
    n_vk = sum(v["valiokunnat"] for v in out.values())
    log(f"lausunnot: {len(out)} säädöstä, {n_all} lausuntoa, {read_all} tiivistetty, {n_vk} valiokunnan lausuntoa/mietintöä "
        f"({total / 1e6:.1f} MB) -> {LAUSUNNOT_DIR}")
    return out
