"""European Commission merger control (DG COMP): notified concentrations and their deadlines.

Source: the Commission's case search backend that powers competition-cases.ec.europa.eu – the
public "Search API" (webgate.ec.europa.eu/es/search-api, the same service family as the Funding &
Tenders portal). The key CS_PROD_ODSE_PROD is the one the public site itself embeds; no login.
Per case it returns the notification date, the provisional deadline DG COMP has computed (25
working days in phase 1, 90+ in phase 2), the phase, simplified-procedure flag, NACE sector and the
decisions with their legal basis (Art. 6(1)(b), 6(1)(c), 8(2), …).

Cache: data/cache/eu_mergers.json. Fetched every run (one or two requests), small.
"""
from __future__ import annotations

import datetime as dt
import json

from common import CACHE_DIR, CONFIG_DIR, TODAY, http, load_yaml, log, save_json

API = "https://webgate.ec.europa.eu/es/search-api/rest/search"
KEY = "CS_PROD_ODSE_PROD"
OUT = CACHE_DIR / "eu_mergers.json"
CASE_FIELDS = ["caseNumber", "caseTitle", "caseSectors", "caseNotificationDate", "caseRenotificationDate", "caseSimplified",
               "caseDeadlineDate", "caseInvestigationPhase", "caseLastDecisionDate", "caseInitiationDate", "caseType",
               "caseOfficialJournalPublications", "casePressReleases"]
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
    cases: dict[str, dict] = {}
    for m in recent + phase2:
        num = one(m.get("caseNumber"))
        if not num or num in cases:
            continue
        cases[num] = {
            "caseNumber": num, "title": (one(m.get("caseTitle")) or "").strip(),
            "sector": one(m.get("caseSectors")), "notified": day(m.get("caseNotificationDate")),
            "renotified": day(m.get("caseRenotificationDate")), "deadline": day(m.get("caseDeadlineDate")),
            "phase": one(m.get("caseInvestigationPhase")), "simplified": one(m.get("caseSimplified")),
            "lastDecision": day(m.get("caseLastDecisionDate")), "initiated": day(m.get("caseInitiationDate")),
            "decisions": [],
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
    save_json(OUT, {"fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "cases": kept})
    log(f"eu-mergers: {len(kept)} komission yrityskauppaa (ilmoitettu ≤ {days} pv tai vaihe 2), {sum(1 for v in kept.values() if not v['lastDecision'])} vireillä -> {OUT}")


if __name__ == "__main__":
    main()
