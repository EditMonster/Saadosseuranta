"""Avoimuusrekisteri (Finnish transparency register, VTV): who lobbied whom about which project.

Source: the register's open JSON API (https://public.api.avoimuusrekisteri.fi, no key, CC BY 4.0).
Registrants file one activity notification per half-year term; each notification lists topics, and a
topic of type "project" carries the Hankeikkuna project id (tunnus, e.g. "VM062:00/2025") – the same
id the pipeline keys its projects on – plus the persons contacted (ministers, officials, MPs) and how.
Free-text topics ("other") are scanned for a tunnus or an HE number.

The finest time resolution is the term (6 months), and a term's data lands 1–2 months after the term
ends (filing window Jan–Feb / Jul–Aug). The register asks for light use, so the API is read at most once
per `refresh_days` and only the newest `terms` closed terms are fetched.

Cache: data/cache/avoimuus.json {fetched, terms, byProject: {tunnus: summary}, byHE: {"12/2026": summary}}.
"""
from __future__ import annotations

import datetime as dt
import re

from common import CACHE_DIR, CONFIG_DIR, TODAY, get_json, load_json, load_yaml, log, save_json

API = "https://public.api.avoimuusrekisteri.fi"
OUT = CACHE_DIR / "avoimuus.json"
TUNNUS_RE = re.compile(r"\b([A-Z]{2,3}\d{3}:\d{2}/\d{4})\b")
HE_RE = re.compile(r"\bHE\s*(\d{1,3})\s*/\s*(\d{4})\b", re.I)
METHOD_FI = {"mail": "sähköposti/kirje", "meeting": "tapaaminen", "online": "etäkokous", "phone": "puhelu", "social_media": "some", "other": "muu"}


def _fi(x) -> str:
    if isinstance(x, dict):
        return (x.get("fi") or x.get("sv") or x.get("en") or "").strip()
    return (x or "").strip() if isinstance(x, str) else ""


def closed_terms(terms: list[dict], n: int) -> list[dict]:
    today = TODAY.isoformat()
    done = [t for t in terms if (t.get("reportingEndDate") or "")[:10] < today and (t.get("signUpStartDate") or "")[:10] <= today
            and t.get("status") != "draft"]
    done.sort(key=lambda t: t.get("reportingEndDate") or "", reverse=True)
    return done[:n]


def summarise(notifications: list[dict], targets: dict[int, dict], term_label: dict[int, str]) -> tuple[dict, dict]:
    """-> (byProject, byHE): per topic key the lobbying organisations, their customers, contacted bodies and methods."""
    by_project: dict[str, dict] = {}
    by_he: dict[str, dict] = {}

    def bucket(store: dict, key: str) -> dict:
        return store.setdefault(key, {"n": 0, "orgs": {}, "customers": {}, "targets": {}, "methods": {}, "contacts": 0, "terms": set()})

    for nf in notifications:
        org = (nf.get("companyName") or "").strip()
        term = term_label.get(nf.get("termId"), str(nf.get("termId")))
        for tp in nf.get("topics") or []:
            keys_p, keys_he = set(), set()
            if tp.get("contactTopicType") == "project" and (tp.get("contactTopicProject") or {}).get("projectId"):
                keys_p.add(tp["contactTopicProject"]["projectId"].strip())
            txt = tp.get("contactTopicOther") or ""
            keys_p.update(TUNNUS_RE.findall(txt))
            keys_he.update(f"{int(m.group(1))}/{m.group(2)}" for m in HE_RE.finditer(txt))
            if not keys_p and not keys_he:
                continue
            contacted = tp.get("contactedTargets") or []
            cust = (tp.get("customerCompanyName") or "").strip() if tp.get("activityType") == "contact_for_customer" else ""
            for store, key in [(by_project, k) for k in keys_p] + [(by_he, k) for k in keys_he]:
                b = bucket(store, key)
                b["n"] += 1
                b["terms"].add(term)
                if org:
                    b["orgs"][org] = b["orgs"].get(org, 0) + 1
                if cust:
                    b["customers"][cust] = b["customers"].get(cust, 0) + 1
                for c in contacted:
                    b["contacts"] += 1
                    tgt = targets.get(c.get("contactedTargetId")) or {}
                    body = (tgt.get("organization") or "").strip()
                    if body:
                        b["targets"][body] = b["targets"].get(body, 0) + 1
                    for m in c.get("contactMethods") or []:
                        m = METHOD_FI.get(m, m)
                        b["methods"][m] = b["methods"].get(m, 0) + 1

    def finish(store: dict) -> dict:
        out = {}
        for key, b in store.items():
            out[key] = {"n": b["n"], "contacts": b["contacts"], "terms": sorted(b["terms"]),
                        "orgs": sorted(b["orgs"], key=lambda o: (-b["orgs"][o], o))[:25],
                        "customers": sorted(b["customers"], key=lambda o: (-b["customers"][o], o))[:10],
                        "targets": [{"name": k, "n": v} for k, v in sorted(b["targets"].items(), key=lambda kv: -kv[1])[:6]],
                        "methods": [{"name": k, "n": v} for k, v in sorted(b["methods"].items(), key=lambda kv: -kv[1])]}
        return out

    return finish(by_project), finish(by_he)


def main():
    cfg = (load_yaml(CONFIG_DIR / "settings.yaml").get("vaikuttaminen") or {}).get("avoimuusrekisteri") or {}
    n_terms = int(cfg.get("terms", 2))
    refresh = int(cfg.get("refresh_days", 1))
    cache = load_json(OUT, {}) or {}
    if cache.get("fetched", "")[:10] >= (TODAY - dt.timedelta(days=refresh - 1)).isoformat() and cache.get("byProject"):
        log(f"avoimuus: välimuisti tuore ({cache['fetched'][:10]}), ei haeta uudelleen")
        return
    terms = get_json(f"{API}/open-data-term/all", timeout=120)
    use = closed_terms(terms, n_terms)
    if not use:
        raise RuntimeError("avoimuus: yhtään päättynyttä ilmoituskautta ei löytynyt – rajapinta on ehkä muuttunut")
    label = {t["id"]: f"{(t.get('reportingStartDate') or '')[:7]}–{(t.get('reportingEndDate') or '')[:7]}" for t in terms}
    targets = {t["id"]: (t.get("fi") or {}) for t in get_json(f"{API}/open-data-target/targets", timeout=180)}
    notifications: list[dict] = []
    for t in use:
        rows = get_json(f"{API}/open-data-activity-notification/term/{t['id']}", timeout=180)
        log(f"avoimuus: kausi {label[t['id']]}: {len(rows)} toimintailmoitusta")
        notifications.extend(rows)
    if len(notifications) < 200:
        raise RuntimeError(f"avoimuus: vain {len(notifications)} toimintailmoitusta – rajapinta on ehkä muuttunut")
    by_project, by_he = summarise(notifications, targets, label)
    save_json(OUT, {"fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "terms": [label[t["id"]] for t in use],
                    "byProject": by_project, "byHE": by_he})
    log(f"avoimuus: {len(by_project)} hanketta ja {len(by_he)} HE-viittausta lobbaustiedoilla ({len(notifications)} ilmoitusta) -> {OUT}")


if __name__ == "__main__":
    main()
