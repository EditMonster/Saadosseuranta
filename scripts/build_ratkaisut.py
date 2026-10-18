"""Case law as rows of docs/data/ratkaisut.json (SPEC §2) from data/cache/caselaw.json (Finnish courts)
and data/cache/curia.json (CJEU judgments, AG opinions and pending Finnish preliminary references).

Pure: reads the two caches and the config, no network. `build_ratkaisut(items)` also returns, for
build.py to attach to the statute rows, `byItem = {itemId: [{id, court, date, title}]}` (the five newest
decisions per item). A decision is related to a statute row when a statute it applies has the same
säädösnumero as one of the row's `sk` numbers or as the statute the row's title amends (Finnish rows:
"laki rikoslain muuttamisesta" -> 39/1889 through the name table), or when an EU act it interprets has the
row's `celex` (EU rows). Pending Finnish references are kept regardless of age until the judgment is
delivered; everything else ages out after keep_days (config/tuomioistuimet.yaml). Statute references
left unresolved at fetch time (`rawRefs`) are re-resolved here with the current tables, so adding an
abbreviation or name to the config takes effect on the next build without refetching.

Legal notes behind the fields: KKO precedents (ennakkopäätös) and KHO yearbook decisions (vuosikirja-
päätös) are the published, final rulings of the supreme courts; HO/HaO/MAO rulings may still be appealed,
which the public pages do not state, so their status is "annettu" rather than "lainvoimainen". For the
CJEU, an AG opinion is advisory and precedes the judgment; a pending reference's `date` is the date it
was lodged, and `published` the OJ C notice date.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from build import classify
from common import CACHE_DIR, CONFIG_DIR, OUT_DIR, TODAY, load_json, load_yaml, log, save_json
from fetch_caselaw import StatuteResolver

OUT = OUT_DIR / "ratkaisut.json"
EUT_NAME = {"C": "Euroopan unionin tuomioistuin", "T": "Unionin yleinen tuomioistuin"}
UNIT = {"HO": ("HO", "hovioikeus"), "HaO": ("HAO", "hallinto-oikeus")}


ALWAYS = {"summary", "keywords", "statutes", "links", "topics"}


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if k in ALWAYS or v not in (None, "", [], {})}


def case_id(prefix: str, case_no: str) -> str:
    """('eut', 'C-390/25') -> r-eut-c-390-25; ('eut-ag', …) -> r-eut-ag-c-390-25; ('erp', 'C-463/26') -> r-erp-c-463-26."""
    return f"r-{prefix}-" + re.sub(r"[^a-z0-9]+", "-", case_no.lower()).strip("-")


def court_name(court: str, rec: dict, cfg: dict) -> str:
    base = ((cfg.get("courts") or {}).get(court) or {}).get("name") or court
    unit = rec.get("courtUnit")
    if court in UNIT and unit:
        abbr, full = UNIT[court]
        return re.sub(rf"\b{abbr}\b", full, unit, flags=re.I).strip() or base
    return base


def fi_row(rid: str, rec: dict, cfg: dict, topics_cfg: dict, resolver: StatuteResolver | None = None) -> dict:
    court = rec["court"]
    statutes = list(rec.get("statutes") or [])
    raw = list(rec.get("rawRefs") or [])
    if resolver is not None:  # re-resolve with the current tables, so additions to the config take effect without refetching
        more, raw = resolver.resolve(raw, (rec.get("abstract") or "") + " " + (rec.get("outcome") or ""))
        for r in more:
            if r not in statutes and not any(x["sk"] == r["sk"] and (x.get("section") or "").startswith(r.get("section") or "") for x in statutes):
                statutes.append(r)
    keywords = rec.get("keywords") or []
    title = " – ".join(keywords) if keywords else (rec.get("ref") or rid)
    if court == "MAO" and rec.get("parties"):
        title = f"{rec['parties']}: {title}" if keywords else rec["parties"]
    summary = (rec.get("abstract") or rec.get("outcome") or "")[:600]
    links = {"finlex": rec.get("finlexUrl")} if rec.get("finlexUrl") else {}
    if rec.get("url") and "finlex.fi" not in (rec.get("url") or ""):
        links[{"MAO": "mao", "KKO": "kko", "KHO": "kho", "TT": "tt", "VakO": "vako"}.get(court, "court")] = rec["url"]
    elif rec.get("url"):
        links.setdefault("finlex", rec["url"])
    row = {
        "id": rid, "scope": "ratkaisu", "court": court, "courtName": court_name(court, rec, cfg), "kind": rec.get("kind") or "Ratkaisu",
        "ref": rec.get("ref"), "ecli": rec.get("ecli"), "date": rec.get("date"), "title": title[:200], "summary": summary,
        "keywords": keywords, "topics": classify(" ".join([title, summary, " ".join(keywords)]), topics_cfg),
        "statutes": statutes, "rawRefs": raw, "citedCases": rec.get("citedCases") or [],
        "diaari": rec.get("diaari"), "parties": rec.get("parties"), "outcome": rec.get("outcome") if court == "MAO" or not summary else None,
        "status": "annettu", "url": rec.get("url") or rec.get("finlexUrl"), "links": links, "fi": True, "related": [],
    }
    if rec.get("caseNo"):
        row["caseNo"] = rec["caseNo"]
    return _clean(row)


def eut_row(rec: dict, topics_cfg: dict, names: dict[str, str] | None = None) -> dict:
    ag = rec.get("type") == "OPIN_AG"
    cn = rec["caseNo"]
    kw = [k.strip() for k in re.split(r"\s+–\s+", rec.get("keywords") or "") if k.strip()]
    heading = (rec.get("title") or "").split("#")[0].strip()
    name = (names or {}).get(cn)  # the case name from the Finnish reference notice, when the opinion/judgment is not yet enriched
    title = f"{cn} {rec['parties']}" if rec.get("parties") else (f"{cn} {name} – {heading}" if name and heading else f"{cn} – {heading}" if heading else cn)
    summary = (rec.get("operative") or rec.get("keywords") or heading or "")[:600]
    statutes = [{"celex": c} for c in rec.get("interprets") or []]
    row = {
        "id": case_id("eut-ag" if ag else "eut", cn), "scope": "ratkaisu", "court": "EUT", "courtName": EUT_NAME.get(rec.get("court") or "C", EUT_NAME["C"]),
        "kind": "Julkisasiamiehen ratkaisuehdotus" if ag else "Tuomio", "ref": cn, "ecli": rec.get("ecli"), "celex": rec.get("celex"),
        "date": rec.get("date"), "title": title[:200], "summary": summary, "keywords": kw[:12],
        "topics": classify(" ".join([title, rec.get("keywords") or "", " ".join(rec.get("subjectsFi") or [])]), topics_cfg),
        "statutes": statutes, "subjects": rec.get("subjectsFi") or [], "procedure": rec.get("procedure") or [],
        "referringCourt": rec.get("referringCourt"), "caseNo": cn, "countries": rec.get("countries") or [], "why": rec.get("why") or [],
        "status": "annettu", "url": (rec.get("links") or {}).get("curia"), "links": rec.get("links") or {}, "fi": bool(rec.get("fi")), "related": [],
    }
    return _clean(row)


def erp_row(ref: dict, topics_cfg: dict) -> dict:
    cn = ref["caseNo"]
    name = ref.get("name") or ""
    parties = ref.get("parties") or ""
    title = f"{cn} {name}" if name else cn
    if parties and parties != name:
        title += f" – {parties}"
    summary = (ref.get("questions") or ref.get("title") or "")[:600]
    links = {k: v for k, v in (("eurlex", ref.get("url")), ("curia", ref.get("curia"))) if v}
    row = {
        "id": case_id("erp", cn), "scope": "ratkaisu", "court": "EUT", "courtName": EUT_NAME["T" if cn.startswith("T-") else "C"],
        "kind": "Ennakkoratkaisupyyntö", "ref": cn, "celex": ref.get("celex"), "date": ref.get("lodged") or ref.get("published"),
        "published": ref.get("published"), "lodged": ref.get("lodged"), "title": title[:200], "summary": summary, "keywords": [],
        "topics": classify(" ".join([title, ref.get("questions") or ""]), topics_cfg),
        "statutes": [{"celex": c} for c in ref.get("acts") or []], "referringCourt": ref.get("referringCourt"), "caseNo": cn,
        "parties": parties, "status": ref.get("status") or "vireillä", "url": ref.get("url") or ref.get("curia"), "links": links,
        "fi": True, "related": [],
    }
    if ref.get("judgmentCelex"):
        row["judgmentId"] = case_id("eut", cn)
        row["judgmentDate"] = ref.get("judgmentDate")
    if ref.get("agCelex"):
        row["agId"] = case_id("eut-ag", cn)
        row["agDate"] = ref.get("agDate")
    return _clean(row)


def build_ratkaisut(items: list[dict], extra: list[dict] | None = None) -> dict:
    """`extra`: ruling rows from other builders (KVL, TSV – build_toimiala) merged into the same file."""
    cfg = load_yaml(CONFIG_DIR / "tuomioistuimet.yaml") or {}
    topics_cfg = dict((load_yaml(CONFIG_DIR / "topics.yaml") or {}).get("topics") or {})
    for name, kws in (cfg.get("aihealueet") or {}).items():  # case-law-specific keyword additions
        topics_cfg[name] = list(topics_cfg.get(name) or []) + list(kws or [])
    keep_days = int(cfg.get("keep_days", 120))
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    caselaw = load_json(CACHE_DIR / "caselaw.json", {}) or {}
    curia = load_json(CACHE_DIR / "curia.json", {}) or {}

    resolver = StatuteResolver(cfg)
    rows: list[dict] = []
    for rid, rec in (caselaw.get("decisions") or {}).items():
        if (rec.get("date") or "") < cutoff or not rec.get("date"):
            continue
        rows.append(fi_row(rid, rec, cfg, topics_cfg, resolver))
    names = {cn: r.get("name") for cn, r in (curia.get("references") or {}).items() if r.get("name")}
    for rec in (curia.get("cases") or {}).values():
        if (rec.get("date") or "") < cutoff or not rec.get("date"):
            continue
        rows.append(eut_row(rec, topics_cfg, names))
    for ref in (curia.get("references") or {}).values():
        if ref.get("status") == "annettu" and (ref.get("judgmentDate") or "") < cutoff:
            continue
        rows.append(erp_row(ref, topics_cfg))

    # related statute rows: säädösnumero for Finnish rows (the row's own `sk` numbers, plus the statute its
    # title names – "laki rikoslain 24 luvun muuttamisesta" amends 39/1889), CELEX for EU rows
    by_sk: dict[str, list[str]] = {}
    by_celex: dict[str, list[str]] = {}
    for it in items or []:
        if it.get("scope") == "fi":
            for sk in set(str(x) for x in it.get("sk") or []) | resolver.mentions(" ".join([it.get("title") or "", it.get("fullTitle") or ""])):
                by_sk.setdefault(sk, []).append(it["id"])
        if it.get("celex"):
            by_celex.setdefault(str(it["celex"]), []).append(it["id"])
    by_item: dict[str, list[dict]] = {}
    for r in rows:
        rel: list[str] = []
        for s in r.get("statutes") or []:
            for iid in by_sk.get(s.get("sk") or "", []) + by_celex.get(s.get("celex") or "", []):
                if iid not in rel:
                    rel.append(iid)
        if rel:
            r["related"] = rel[:12]
            for iid in rel:
                by_item.setdefault(iid, []).append({"id": r["id"], "court": r["court"], "date": r.get("date"), "title": r["title"]})
        else:
            r.pop("related", None)
    for iid, lst in by_item.items():
        lst.sort(key=lambda x: x.get("date") or "", reverse=True)
        del lst[5:]

    seen_ids = {r["id"] for r in rows}
    for r in extra or []:
        if r.get("id") and r["id"] not in seen_ids and r.get("date") and r.get("date") >= cutoff:
            r.setdefault("scope", "ratkaisu")
            r.setdefault("topics", classify(" ".join([r.get("title") or "", r.get("summary") or "", " ".join(r.get("keywords") or [])]), topics_cfg) or ["Muut"])
            rows.append(r)
            seen_ids.add(r["id"])
    rows.sort(key=lambda r: (r.get("date") or "", r["id"]), reverse=True)
    counts = {k: 0 for k in ("kko", "kho", "ho", "hao", "tt", "vako", "mao", "eut", "eut_ag", "erp_vireilla")}
    for r in rows:
        if r["court"] == "EUT":
            key = {"Tuomio": "eut", "Julkisasiamiehen ratkaisuehdotus": "eut_ag"}.get(r["kind"])
            if key is None:
                if r.get("status") == "vireillä":
                    counts["erp_vireilla"] += 1
                continue
        else:
            key = r["court"].lower()
        counts[key] = counts.get(key, 0) + 1
    counts["fi"] = sum(1 for r in rows if r.get("fi"))
    counts["total"] = len(rows)
    payload = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "keepDays": keep_days, "counts": counts,
               "health": caselaw.get("health") or {}, "items": rows}
    save_json(OUT, payload, compact=True)
    log(f"ratkaisut: {len(rows)} riviä {counts} -> {OUT}; {len(by_item)} säädösriville oikeuskäytäntöä")
    return {"payload": payload, "byItem": by_item}


if __name__ == "__main__":
    data = load_json(OUT_DIR / "items.json", {"items": []})
    res = build_ratkaisut(data.get("items") or [])
    p = res["payload"]
    print(json.dumps(p["counts"], ensure_ascii=False))
    for r in p["items"][:5]:
        print(r["id"], r["date"], r["court"], r["kind"], r["title"][:70], r.get("statutes"), r.get("related"))
