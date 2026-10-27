"""EU-direktiivien kansalliset täytäntöönpanotoimet (NIM) Suomessa Cellarista (EU:n julkaisutoimiston SPARQL).

Jäsenvaltio ilmoittaa komissiolle säädökset, joilla se on saattanut direktiivin voimaan; Cellar julkaisee
ilmoitukset teoksina (cdm:measure_national_implementing), jotka viittaavat direktiiviin ja maahan. Tämä vaihe hakee
sivun EU-direktiiveille Suomen ilmoittamat säädökset (nimi, säädöskokoelman numero, ilmoituspäivä, voimaantulo) sekä
direktiivin täytäntöönpanon määräajan. Näin direktiivin tiedoissa näkyy, millä Suomen säädöksillä se on pantu
täytäntöön – tai ettei Suomi ole ilmoittanut yhtään toimea, vaikka määräaika on umpeutunut.

Välimuisti data/cache/nim.json {"celex": {"32022L2555": {"deadline", "measures": [{title, sk, type, date, notif, eif}]}}}.
Haetaan kerran päivässä (ilmoituksia tulee harvoin).
"""
from __future__ import annotations

import datetime as dt
import re

from common import CACHE_DIR, OUT_DIR, SourceOutage, get_json, load_json, log, save_json

EP = "https://publications.europa.eu/webapi/rdf/sparql"
OUT = CACHE_DIR / "nim.json"
BATCH = 40
XS = "^^<http://www.w3.org/2001/XMLSchema#string>"
DIRECTIVE = re.compile(r"^3\d{4}L\d{4}$")

Q_MEASURES = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT ?celex ?nim ?title ?oj ?notif ?eif ?type ?date WHERE {
 VALUES ?celex { %s }
 ?w cdm:resource_legal_id_celex ?celex .
 ?nim cdm:measure_national_implementing_implements_resource_legal ?w ;
      cdm:measure_national_implementing_implemented_by_country <http://publications.europa.eu/resource/authority/country/FIN> .
 OPTIONAL { ?nim cdm:work_title ?title }
 OPTIONAL { ?nim cdm:measure_national_implementing_number_official_journal ?oj }
 OPTIONAL { ?nim cdm:measure_national_implementing_date_notification ?notif }
 OPTIONAL { ?nim cdm:resource_legal_date_entry-into-force ?eif }
 OPTIONAL { ?nim cdm:measure_national_implementing_type_act ?type }
 OPTIONAL { ?nim cdm:work_date_document ?date }
}"""
Q_DEADLINE = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT ?celex (MIN(?d) AS ?deadline) WHERE {
 VALUES ?celex { %s }
 ?w cdm:resource_legal_id_celex ?celex ; cdm:directive_date_transposition ?d .
} GROUP BY ?celex"""


def _query(q: str) -> list[dict]:
    d = get_json(EP, params={"query": q, "format": "application/sparql-results+json"}, timeout=180)
    return [{k: v.get("value") for k, v in b.items()} for b in (d.get("results") or {}).get("bindings") or []]


def clean_title(t: str) -> str:
    """Finnish part of a bilingual title, without the "viimeksi muutettuna …" tail of consolidated acts."""
    t = re.split(r"\s+/\s+", t or "", maxsplit=1)[0]
    t = re.sub(r"\s*\((\d+/\d{4})\)\s*\d{1,2}\.\d{1,2}\.\d{4}.*$", r" (\1)", t)
    t = re.sub(r",?\s*viimeksi muutettuna.*$", "", t)
    return re.sub(r"\s+", " ", t).strip()


def measure_row(b: dict) -> dict:
    oj = (b.get("oj") or "").strip()
    sk = oj if re.fullmatch(r"\d{1,4}/\d{4}", oj) else None
    return {k: v for k, v in {"title": clean_title(b.get("title") or ""), "sk": sk, "oj": None if sk else (oj or None),
                              "type": b.get("type"), "date": (b.get("date") or "")[:10] or None,
                              "notif": (b.get("notif") or "")[:10] or None, "eif": (b.get("eif") or "")[:10] or None}.items() if v}


def wanted() -> list[str]:
    """Directive CELEX numbers of the EU items on the page (previous build), plus those already cached."""
    data = load_json(OUT_DIR / "items.json", {}) or {}
    items = data.get("items") if isinstance(data, dict) else data
    out = {it["celex"] for it in items or [] if it.get("scope") == "eu" and DIRECTIVE.match(it.get("celex") or "")}
    out |= set(((load_json(OUT, {}) or {}).get("celex") or {}).keys())
    return sorted(out)


def main() -> None:
    cache = load_json(OUT, {}) or {}
    if (cache.get("fetched") or "")[:10] == dt.date.today().isoformat() and cache.get("celex"):
        log("nim: haettu tänään jo")
        return
    celexes = wanted()
    res: dict[str, dict] = {c: {"measures": []} for c in celexes}
    try:
        for i in range(0, len(celexes), BATCH):
            vals = " ".join(f'"{c}"{XS}' for c in celexes[i:i + BATCH])
            seen = set()
            for b in _query(Q_MEASURES % vals):
                if b["nim"] in seen:
                    continue
                seen.add(b["nim"])
                res[b["celex"]]["measures"].append(measure_row(b))
            for b in _query(Q_DEADLINE % vals):
                if b.get("deadline") and b["deadline"][:4] >= "1990":  # Cellar marks "no deadline" as 1001-01-01
                    res[b["celex"]]["deadline"] = b["deadline"][:10]
    except Exception as e:  # noqa: BLE001
        raise SourceOutage(f"Cellar SPARQL ei vastaa: {e}") from e
    for r in res.values():
        r["measures"].sort(key=lambda m: (m.get("notif") or m.get("date") or ""), reverse=True)
    save_json(OUT, {"fetched": dt.datetime.now().isoformat(timespec="seconds"), "celex": res})
    n = sum(len(r["measures"]) for r in res.values())
    none = sum(1 for r in res.values() if not r["measures"])
    log(f"nim: {len(res)} direktiiviä, {n} Suomen täytäntöönpanotointa, {none} ilman ilmoitettua tointa -> {OUT}")


if __name__ == "__main__":
    main()
