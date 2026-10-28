"""EU legislative procedures.

Sources
* European Parliament open data API  https://data.europarl.europa.eu/api/v2
  (ordinary legislative procedures: Finnish titles, committee/plenary events,
  provisional agreements, signature, OJ publication)
* Publications Office Cellar SPARQL   https://publications.europa.eu/webapi/rdf/sparql
  (dossier -> Commission proposal date, adopted act CELEX, entry into force,
  staged application dates, transposition deadlines, in-force flag; and the dossier's
  legal events from the former PreLex database – this is where the Council's stages live:
  general approach, Coreper negotiating mandate, endorsement of the provisional agreement,
  adoption of the act – typed with the Publications Office's event authority codes)
"""
from __future__ import annotations

import datetime as dt
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import CACHE_DIR, CONFIG_DIR, TODAY, days_ago, get_json, http, is_future, load_json, load_yaml, log, save_json

EP = "https://data.europarl.europa.eu/api/v2"
SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
OUT = CACHE_DIR / "eu.json"
WORKERS = 6          # rinnakkaiset haut (EP API ~3 s/menettely)
REFRESH_DAYS = 3     # keskeneräiset menettelyt haetaan uudelleen näin usein; watchlist päivittäin

EP_EVENTS = {  # had_activity_type suffix -> (label, kind, keep_which)
    "REFERRAL": ("Valiokuntaan (EP)", "parlamentti", "first"),
    "COMMITTEE_ADOPTING_REPORT": ("Valiokunnan mietintö hyväksytty", "parlamentti", "last"),
    "PLENARY_VOTE": ("Parlamentin täysistuntoäänestys", "parlamentti", "all"),
    "COMMITTEE_APPROVE_PROVISIONAL_AGREEMENT": ("Alustava sopu (trilogi) hyväksytty valiokunnassa", "sopu", "last"),
    "SIGNATURE": ("Säädös allekirjoitettu", "neuvosto", "last"),
    "PUBLICATION_OFFICIAL_JOURNAL": ("Julkaistu EUVL:ssä", "julkaistu", "last"),
}


def ep_list(year: int, ptype: str) -> list[str]:
    ids, offset, limit = [], 0, 200
    while True:
        data = get_json(f"{EP}/procedures", params={"year": year, "process-type": ptype, "format": "application/ld+json",
                                                     "limit": limit, "offset": offset}, timeout=90)
        batch = [d["process_id"] for d in data.get("data", []) if d.get("process_id")]
        ids.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return ids


def ep_detail(pid: str) -> dict | None:
    data = get_json(f"{EP}/procedures/{pid}", params={"format": "application/ld+json"}, timeout=90)
    procs = data.get("data") or []
    if not procs:
        return None
    p = procs[0]
    title = p.get("process_title") or {}
    events, seen = [], {}
    for a in sorted(p.get("consists_of") or [], key=lambda a: a.get("activity_date") or ""):
        at = a.get("had_activity_type") or ""
        types = [str(x).split("/")[-1] for x in (at if isinstance(at, list) else [at])]
        t = next((x for x in types if x in EP_EVENTS), types[0] if types else "")
        d = a.get("activity_date")
        if t not in EP_EVENTS or not d:
            continue
        label, kind, which = EP_EVENTS[t]
        ev = {"date": d, "label": label, "kind": kind, "confirmed": True}
        if which == "first" and t in seen:
            continue
        if which == "last" and t in seen:
            events[seen[t]] = ev
            continue
        seen[t] = len(events)
        events.append(ev)
    return {
        "pid": pid,
        "ref": p.get("label") or pid,
        "title_fi": (title.get("fi") or "").strip(),
        "title_en": (title.get("en") or "").strip(),
        "title_sv": (title.get("sv") or "").strip(),
        "title_et": (title.get("et") or "").strip(),
        "title_lt": (title.get("lt") or "").strip(),
        "stage": str((p.get("current_stage") or [""])[0] if isinstance(p.get("current_stage"), list) else (p.get("current_stage") or "")).split("/")[-1],
        "events": events,
    }


def _sparql(q: str) -> list[dict]:
    r = http("GET", SPARQL, params={"query": q, "format": "application/sparql-results+json"}, timeout=90)
    r.raise_for_status()
    return r.json()["results"]["bindings"]


def act_dates(celex: str) -> dict:
    q = f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?sig ?oj ?eif ?transp ?deadline ?inforce ?eov ?ftitle WHERE {{
  ?a cdm:resource_legal_id_celex "{celex}"^^xsd:string .
  OPTIONAL {{ ?a cdm:resource_legal_date_signature ?sig }}
  OPTIONAL {{ ?a cdm:official-journal-act_date_publication ?oj }}
  OPTIONAL {{ ?a cdm:resource_legal_date_entry-into-force ?eif }}
  OPTIONAL {{ ?a cdm:directive_date_transposition ?transp }}
  OPTIONAL {{ ?a cdm:resource_legal_date_deadline ?deadline }}
  OPTIONAL {{ ?a cdm:resource_legal_in-force ?inforce }}
  OPTIONAL {{ ?a cdm:resource_legal_date_end-of-validity ?eov }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?a ; cdm:expression_uses_language
              <http://publications.europa.eu/resource/authority/language/FIN> ; cdm:expression_title ?ftitle }}
}} LIMIT 300"""
    a = {"celex": celex, "signature": None, "oj": None, "eif": set(), "transposition": set(), "deadlines": set(),
         "inForce": None, "endOfValidity": None, "title_fi": None}
    for b in _sparql(q):
        g = lambda k: b[k]["value"] if k in b else None  # noqa: E731
        a["signature"] = a["signature"] or (g("sig") or "")[:10] or None
        a["oj"] = a["oj"] or (g("oj") or "")[:10] or None
        a["inForce"] = a["inForce"] if a["inForce"] is not None else g("inforce")
        a["endOfValidity"] = a["endOfValidity"] or g("eov")
        a["title_fi"] = a["title_fi"] or g("ftitle")
        for k, s in (("eif", "eif"), ("transp", "transposition"), ("deadline", "deadlines")):
            if g(k):
                a[s].add(g(k)[:10])
    for k in ("eif", "transposition", "deadlines"):
        a[k] = sorted(a[k])
    return a


def cellar(pid: str) -> dict:
    """Dossier facts from Cellar for '2021-0106' -> procedure:2021_106."""
    year, num = pid.split("-", 1)
    m = re.match(r"(\d+)([A-Za-z]*)$", num)
    out = {"proposal": None, "proposalDate": None, "adopted": None, "acts": {}}
    if not m:
        return out
    ident = f"procedure:{year}_{int(m.group(1))}{m.group(2).upper()}"
    q = f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?pcelex ?pdate ?adopted ?acelex WHERE {{
  ?d cdm:dossier_identifier ?id . FILTER(STR(?id) = "{ident}")
  OPTIONAL {{ ?d cdm:dossier_initiated_by_act_preparatory ?p . ?p cdm:resource_legal_id_celex ?pcelex .
             OPTIONAL {{ ?p cdm:work_date_document ?pdate }} }}
  OPTIONAL {{ ?d cdm:dossier_date_adopted ?adopted }}
  OPTIONAL {{ {{ ?a cdm:resource_legal_produced_by_dossier ?d }} UNION {{ ?a cdm:work_part_of_dossier ?d }}
             UNION {{ ?d cdm:dossier_produces_resource_legal ?a }} UNION {{ ?d cdm:dossier_contains_work ?a }}
             ?a cdm:resource_legal_id_celex ?acelex . FILTER(STRSTARTS(STR(?acelex), "3")) }}
}} LIMIT 200"""
    celexes = []
    for b in _sparql(q):
        g = lambda k: b[k]["value"] if k in b else None  # noqa: E731
        out["proposal"] = out["proposal"] or g("pcelex")
        out["proposalDate"] = out["proposalDate"] or g("pdate")
        out["adopted"] = out["adopted"] or g("adopted")
        ac = g("acelex")
        if ac and re.fullmatch(r"3\d{4}[RLD]\d{4}", ac) and ac not in celexes:
            celexes.append(ac)
    for ac in celexes[:3]:
        out["acts"][ac] = act_dates(ac)
    return out


COUNCIL_TYPES = ("CONSIL", "AGRPROV", "NGT_INST")   # event type codes worth keeping (Council + trilogue milestones)


def council_events(pids: list[str]) -> dict[str, list[dict]]:
    """Dossier legal events (PreLex) for many procedures in a few batched queries: {pid: [{date, type}]}."""
    out: dict[str, list[dict]] = {}
    idents = {}
    for pid in pids:
        year, num = pid.split("-", 1)
        m = re.match(r"(\d+)([A-Za-z]*)$", num)
        if m:
            idents[f"procedure:{year}_{int(m.group(1))}{m.group(2).upper()}"] = pid
    keys = list(idents)
    for i in range(0, len(keys), 100):
        chunk = keys[i:i + 100]
        vals = ", ".join(f'"{k}"' for k in chunk)
        q = f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT ?id ?date ?type ?st WHERE {{
  ?d cdm:dossier_identifier ?id . FILTER(STR(?id) IN ({vals}))
  ?e cdm:event_legal_part_of_dossier ?d . ?e cdm:event_legal_date ?date . ?e cdm:event_legal_type ?type .
  OPTIONAL {{ ?e cdm:event_legal_has-status_event-status ?st }}
  FILTER({" || ".join(f'CONTAINS(STR(?type), "{t}")' for t in COUNCIL_TYPES)})
}}"""
        try:
            rows = _sparql(q)
        except Exception as e:  # noqa: BLE001
            log(f"warn: neuvoston vaiheet (erä {i // 100 + 1}): {e}")
            continue
        for b in rows:
            pid = idents.get(b["id"]["value"])
            if not pid:
                continue
            typ = str(b["type"]["value"]).split("/")[-1]
            date = b["date"]["value"][:10]
            status = str((b.get("st") or {}).get("value") or "").split("/")[-1]  # PROJECTED = planned (Council agenda), CANCELLED = dropped
            if status == "CANCELLED":
                continue
            if re.match(r"\d{4}-\d{2}-\d{2}$", date):
                ev = {"date": date, "type": typ}
                if status == "PROJECTED":
                    ev["projected"] = True
                out.setdefault(pid, []).append(ev)
    for pid, evs in out.items():
        evs.sort(key=lambda e: (e["date"], e["type"]))
    return out


def is_final(rec: dict) -> bool:
    acts = rec.get("cellar", {}).get("acts", {})
    if not acts:
        return False
    for a in acts.values():
        if a.get("inForce") != "1":
            return False
        if any(is_future(d) for d in a.get("eif", []) + a.get("transposition", [])):
            return False
    return True


def main():
    settings = load_yaml(CONFIG_DIR / "settings.yaml")
    watch = load_yaml(CONFIG_DIR / "eu_watchlist.yaml") or {}
    years = settings["eu"]["years"]
    ptypes = settings["eu"]["procedure_types"]
    pids = []
    for y in years:
        for t in ptypes:
            try:
                ids = ep_list(y, t)
            except Exception as e:  # noqa: BLE001
                log(f"warn: EP list {y}/{t}: {e}")
                continue
            pids.extend(ids)
            log(f"EP {y} {t}: {len(ids)} menettelyä")
    for ref in watch.get("procedures") or []:
        m = re.match(r"(\d{4})/(\d{4})", ref)
        if m:
            pids.append(f"{m.group(1)}-{m.group(2)}")
    pids = sorted(set(pids))
    cache = load_json(OUT, {"items": {}})["items"]
    watched = set()
    for ref in watch.get("procedures") or []:
        m = re.match(r"(\d{4})/(\d{4})", ref)
        if m:
            watched.add(f"{m.group(1)}-{m.group(2)}")
    todo = []
    for pid in pids:
        old = cache.get(pid)
        if old:
            age = days_ago(old.get("fetched")) or 0
            limit = 60 if old.get("final") else (1 if pid in watched else REFRESH_DAYS)
            if age < limit and "title_lt" in old:  # records from before the Estonian/Lithuanian titles are read once more
                continue
        todo.append(pid)
    log(f"eu: haetaan {len(todo)} menettelyä ({len(pids) - len(todo)} välimuistista)")

    def work(pid):
        rec = ep_detail(pid)
        if not rec:
            return pid, None
        rec["cellar"] = cellar(pid)
        rec["fetched"] = TODAY.isoformat()
        rec["final"] = is_final(rec)
        return pid, rec

    done, failed = 0, 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(work, pid): pid for pid in todo}
        for f in as_completed(futs):
            pid = futs[f]
            try:
                pid, rec = f.result()
            except Exception as e:  # noqa: BLE001
                failed += 1
                log(f"warn: {pid}: {e}")
                continue
            if rec:
                cache[pid] = rec
                done += 1
                if done % 25 == 0:
                    save_json(OUT, {"fetched": dt.datetime.now().isoformat(timespec="seconds"), "items": cache})
    # Council stages for every procedure that is not long finished (a handful of batched Cellar queries)
    active = [pid for pid, rec in cache.items() if not rec.get("final") or (days_ago(rec.get("fetched")) or 0) < 60]
    council = council_events(active)
    for pid in active:
        if pid in council:
            cache[pid]["council"] = council[pid]
    log(f"eu: neuvoston vaiheet {sum(len(v) for v in council.values())} tapahtumaa {len(council)} menettelyssä")
    save_json(OUT, {"fetched": dt.datetime.now().isoformat(timespec="seconds"), "items": cache})
    log(f"eu: päivitetty {done}, epäonnistui {failed}, yhteensä {len(cache)} -> {OUT}")


if __name__ == "__main__":
    main()
