"""European Commission merger control (DG COMP): notified concentrations and their deadlines.

Source: the Commission's case search backend that powers competition-cases.ec.europa.eu – the
public "Search API" (webgate.ec.europa.eu/es/search-api, the same service family as the Funding &
Tenders portal). The key CS_PROD_ODSE_PROD is the one the public site itself embeds; no login.
Per case it returns the notification date, the provisional deadline DG COMP has computed (25
working days in phase 1, 90+ in phase 2), the phase, simplified-procedure flag, NACE sector and the
decisions with their legal basis (Art. 6(1)(b), 6(1)(c), 8(2), …).

For each case the Official Journal prior-notification notice (eu_notice.py) is read once from the
Publications Office in Finnish: it names the parties with their countries (→ Finnish involvement),
describes the transaction and the parties' business, and opens the third-party observation window.
The Commission's own timeline events (clock stops under Art. 11(3), extensions under Art. 10(3),
commitments, Art. 9 referral requests) are kept as well.

Cache: data/cache/eu_mergers.json. Case metadata is fetched every run (a few requests); notices
only for cases that lack one (≤ NOTICES_PER_RUN per run).
"""
from __future__ import annotations

import datetime as dt
import json
import time

from common import CACHE_DIR, CONFIG_DIR, TODAY, http, load_json, load_yaml, log, save_json
from eu_notice import fetch_notice

API = "https://webgate.ec.europa.eu/es/search-api/rest/search"
KEY = "CS_PROD_ODSE_PROD"
OUT = CACHE_DIR / "eu_mergers.json"
CASE_FIELDS = ["caseNumber", "caseTitle", "caseSectors", "caseNotificationDate", "caseRenotificationDate", "caseSimplified",
               "caseDeadlineDate", "caseInvestigationPhase", "caseLastDecisionDate", "caseInitiationDate", "caseType",
               "caseOfficialJournalPublications", "casePressReleases", "caseTimelineEvents"]
NOTICES_PER_RUN = 60
NOTICE_TRIES = 4
DEC_FIELDS = ["caseNumber", "decisionTypes", "decisionAdoptionDate", "decisionNumber", "decisionOfficialJournalPublications"]


def search(query: dict, sort: list[dict], fields: list[str], size: int = 100) -> list[dict]:
    out, page = [], 1
    while True:
        files = {"query": ("blob", json.dumps(query), "application/json"), "sort": ("blob", json.dumps(sort), "application/json"),
                 "displayFields": ("blob", json.dumps(fields), "application/json")}
        r = http("POST", API, params={"text": "*", "pageNumber": page, "pageSize": size, "apiKey": KEY}, files=files,
                 headers={"Accept": "application/json"}, timeout=120)
        r.raise_for_status()
        data = r.json()
        rows = [x.get("metadata") or {} for x in data.get("results") or []]
        out.extend(rows)
        if len(rows) < size or page * size >= int(data.get("totalResults") or 0):
            break
        page += 1
    return out


def one(v):
    return v[0] if isinstance(v, list) and v else (None if isinstance(v, list) else v)


def jitems(v) -> list[dict]:
    """The JSON-in-a-string list fields (caseTimelineEvents, caseOfficialJournalPublications)."""
    try:
        return [i for i in (json.loads(one(v) or "{}").get("items") or []) if i]
    except (ValueError, TypeError, AttributeError):
        return []


def day(v) -> str | None:
    s = one(v)
    if not s:
        return None
    # the API stores dates as midnight Brussels time expressed in UTC (…T22:00:00 / T23:00:00); convert to the local date
    try:
        d = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return str(s)[:10]
    return (d + dt.timedelta(hours=2)).date().isoformat()


def main():
    settings = load_yaml(CONFIG_DIR / "settings.yaml").get("yrityskaupat", {})
    days = int(settings.get("eu_notified_days", 120))
    keep_days = int(settings.get("keep_decided_days", 90))
    since = (TODAY - dt.timedelta(days=days)).isoformat()
    base = [{"exists": {"field": "caseNumber"}}, {"term": {"caseInstrument": "M"}}, {"term": {"metadataType": "METADATA_CASE"}}]
    recent = search({"bool": {"must": base + [{"range": {"caseNotificationDate": {"gte": since + "T00:00:00.000Z"}}}]}},
                    [{"field": "caseNotificationDate", "order": "DESC"}], CASE_FIELDS)
    phase2 = search({"bool": {"must": base + [{"term": {"caseInvestigationPhase": "FormalInvestigationPhase2Merger"}}]}},
                    [{"field": "caseNotificationDate", "order": "DESC"}], CASE_FIELDS)
    old = (load_json(OUT, {}) or {}).get("cases") or {}
    cases: dict[str, dict] = {}
    for m in recent + phase2:
        num = one(m.get("caseNumber"))
        if not num or num in cases:
            continue
        oj = sorted(({"reference": i.get("reference"), "published": day(i.get("publishedDate"))} for i in jitems(m.get("caseOfficialJournalPublications"))
                     if i.get("reference") and (i.get("referenceSeries") or "C") == "C"), key=lambda i: i["published"] or "")
        timeline = [{"date": day(e.get("date")), "type": e.get("type"), "description": (e.get("description") or "").strip()}
                    for e in jitems(m.get("caseTimelineEvents")) if e.get("date")]
        prev = old.get(num) or {}
        cases[num] = {
            "caseNumber": num, "title": (one(m.get("caseTitle")) or "").strip(),
            "sector": one(m.get("caseSectors")), "notified": day(m.get("caseNotificationDate")),
            "renotified": day(m.get("caseRenotificationDate")), "deadline": day(m.get("caseDeadlineDate")),
            "phase": one(m.get("caseInvestigationPhase")), "simplified": one(m.get("caseSimplified")),
            "lastDecision": day(m.get("caseLastDecisionDate")), "initiated": day(m.get("caseInitiationDate")),
            "oj": oj, "timeline": timeline, "decisions": [],
            # the notice is carried over unless a newer OJ publication (re-notification) has appeared
            "notice": prev.get("notice") if prev.get("notice") and oj and prev["notice"].get("oj") == oj[-1]["reference"] else None,
            "noticeTries": prev.get("noticeTries", 0) if prev.get("oj") == oj else 0,
        }
    if len(cases) < 10:
        raise RuntimeError(f"komission tapaushaku palautti vain {len(cases)} yrityskauppaa – rajapinta on ehkä muuttunut")
    # decisions for these cases (phase-2 cases may have old 6(1)(c) decisions, so query by case number, in chunks)
    nums = list(cases)
    for i in range(0, len(nums), 60):
        chunk = nums[i:i + 60]
        decs = search({"bool": {"must": [{"term": {"caseInstrument": "M"}}, {"term": {"metadataType": "METADATA_DECISION"}},
                                           {"terms": {"caseNumber": chunk}}]}},
                      [{"field": "decisionAdoptionDate", "order": "ASC"}], DEC_FIELDS)
        for d in decs:
            num = one(d.get("caseNumber"))
            if num in cases:
                cases[num]["decisions"].append({"date": day(d.get("decisionAdoptionDate")), "type": one(d.get("decisionTypes"))})
    # drop cases decided long ago (recent query is by notification, so a quick clearance months ago may be in it)
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    kept = {k: v for k, v in cases.items() if not v["lastDecision"] or v["lastDecision"] >= cutoff or v["phase"] == "FormalInvestigationPhase2Merger"}
    # Official Journal notices: open cases first, newest first; a notice that cannot be parsed is retried a few runs
    todo = [v for v in sorted(kept.values(), key=lambda v: (bool(v["lastDecision"]), v["notified"] or ""), reverse=False)
            if v["oj"] and not v["notice"] and v["noticeTries"] < NOTICE_TRIES]
    todo.sort(key=lambda v: (1 if v["lastDecision"] else 0, -(int((v["notified"] or "0000-00-00").replace("-", "") or 0))))
    got = failed = 0
    for v in todo[:NOTICES_PER_RUN]:
        ref = v["oj"][-1]["reference"]
        try:
            n = fetch_notice(ref)
        except Exception as e:  # noqa: BLE001
            log(f"warn: eu-mergers notice {v['caseNumber']} {ref}: {e}")
            n = None
        v["noticeTries"] += 1
        if n and n.get("parties"):
            n["oj"] = ref
            n["published"] = n.get("published") or v["oj"][-1]["published"]
            v["notice"] = n
            got += 1
        else:
            failed += 1
        time.sleep(0.3)
    save_json(OUT, {"fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "cases": kept})
    with_notice = sum(1 for v in kept.values() if v.get("notice"))
    fi = sum(1 for v in kept.values() if (v.get("notice") or {}).get("fi"))
    log(f"eu-mergers: {len(kept)} komission yrityskauppaa (ilmoitettu ≤ {days} pv tai vaihe 2), {sum(1 for v in kept.values() if not v['lastDecision'])} vireillä, "
        f"EUVL-ilmoitus {with_notice} tapauksella (+{got} uutta, {failed} ei saatu), suomalainen osapuoli {fi} -> {OUT}")


if __name__ == "__main__":
    main()
