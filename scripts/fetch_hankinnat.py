"""Hilma (hankintailmoitukset.fi): open public-procurement notices = tenders you can still bid on.

Source: the public search index behind hankintailmoitukset.fi/fi/search (Azure Cognitive Search
fronted by Hilma; no key, same query the site itself issues). It covers every Finnish notice –
national ones and the EU-threshold ones that are also sent to TED – so TED is not needed for
Finnish tenders. The documented "Hilma avoin rajapinta" needs a free API key; if this endpoint
ever disappears, that is the fallback (see README).

The cache (data/cache/hankinnat.json) is not committed: it is rebuilt in seconds on every run.
build.py carries recently closed or withdrawn notices over from the previous published file so
that a followed tender does not silently disappear from the page.
"""
from __future__ import annotations

import datetime as dt
import time

from common import CACHE_DIR, CONFIG_DIR, TODAY, http, load_json, load_yaml, log, save_json

SEARCH = "https://www.hankintailmoitukset.fi/search/eformnotices"
CPV = "https://www.hankintailmoitukset.fi/search/cpv"
OUT = CACHE_DIR / "hankinnat.json"
CPV_OUT = CACHE_DIR / "cpv.json"
PAGE = 1000
HEADERS = {"Cache-Control": "no-cache", "Pragma": "no-cache", "Accept": "application/json"}

KEEP = ("id", "noticeId", "procedureId", "oldProcurementProjectId", "isEForms", "type", "mainType", "datePublished",
        "dateModified", "deadline", "expirationDate", "titleFi", "titleSv", "titleEn", "organisationNameFi",
        "organisationNameSv", "organisationNameEn", "organisationNationalRegistrationNumber", "organisationType",
        "nutsCodes", "cpvCodes", "procedureType", "procurementTypeCode", "estimatedValue", "currency",
        "includesFrameworkAgreement", "includesDynamicPurcharingSystem", "isEuProcurement", "isNationalProcurement",
        "isNationalSmallValueProcurement", "isCorrigendum", "isCancelled", "previousSearchIds", "noticeNumber",
        "tedPublicationId", "noticeOjsNumber", "procurementDocumentsUrl", "tenderingInHilma")
DESC_MAX = 3000
LOT_DESC_MAX = 300


def _trim(n: dict) -> dict:
    out = {k: n.get(k) for k in KEEP}
    out["descriptionFi"] = (n.get("descriptionFi") or "")[:DESC_MAX]
    if not out["descriptionFi"]:
        out["descriptionAlt"] = ((n.get("descriptionSv") or n.get("descriptionEn") or n.get("descriptionOther") or ""))[:DESC_MAX]
    lots = []
    for lot in n.get("lots") or []:
        lots.append({"id": lot.get("id"), "titleFi": lot.get("titleFi") or "", "titleSv": lot.get("titleSv") or "",
                     "titleEn": lot.get("titleEn") or "", "cpvCodes": lot.get("cpvCodes") or "",
                     "estimatedValue": lot.get("estimatedValue"), "currency": lot.get("currency"),
                     "deadline": lot.get("deadline"), "descriptionFi": (lot.get("descriptionFi") or "")[:LOT_DESC_MAX]})
    out["lots"] = lots
    return out


def fetch_open() -> tuple[list[dict], int]:
    """All notices the Hilma search page lists as open (contract notices whose listing has not expired)."""
    flt = (f"(search.in(mainType, 'ContractNotices|NationalNotices', '|') and expirationDate ge {TODAY.isoformat()}T00:00:00Z)"
           " and isPlan eq false")
    items, skip, total = [], 0, None
    while True:
        params = {"queryType": "full", "$top": PAGE, "$skip": skip, "searchMode": "all", "$orderby": "datePublished desc",
                  "$count": "true", "$filter": flt, "_": int(time.time() * 1000)}
        r = http("GET", SEARCH, params=params, headers=HEADERS, timeout=180)
        r.raise_for_status()
        data = r.json()
        if total is None:
            total = int(data.get("@odata.count") or 0)
        page = data.get("value") or []
        items.extend(page)
        if len(page) < PAGE:
            break
        skip += PAGE
        time.sleep(0.5)
    return items, total or len(items)


def refresh_cpv(max_age_days: int):
    """Finnish labels for all CPV codes (≈9 500); refreshed rarely, the list changes almost never."""
    old = load_json(CPV_OUT, {})
    if old.get("labels") and old.get("fetched") and (TODAY - dt.date.fromisoformat(old["fetched"])).days < max_age_days:
        return
    labels, skip = {}, 0
    while True:
        r = http("GET", CPV, params={"queryType": "full", "search": "*", "$top": PAGE, "$skip": skip, "$orderby": "Id",
                                     "$select": "Id,LabelFi"}, headers=HEADERS, timeout=120)
        r.raise_for_status()
        page = r.json().get("value") or []
        for c in page:
            if c.get("Id") and c.get("LabelFi"):
                labels[c["Id"]] = c["LabelFi"]
        if len(page) < PAGE:
            break
        skip += PAGE
    if len(labels) < 5000:
        raise RuntimeError(f"CPV-luettelo epäilyttävän lyhyt ({len(labels)})")
    save_json(CPV_OUT, {"fetched": TODAY.isoformat(), "labels": labels}, compact=True)
    log(f"hilma: {len(labels)} CPV-nimikettä -> {CPV_OUT}")


def main():
    settings = load_yaml(CONFIG_DIR / "settings.yaml").get("hankinnat", {})
    min_items = int(settings.get("min_items", 100))
    try:
        refresh_cpv(int(settings.get("cpv_refresh_days", 90)))
    except Exception as e:  # noqa: BLE001
        log(f"warn: CPV-luettelon haku epäonnistui, käytetään vanhaa: {e}")

    raw, total = fetch_open()
    ids = {n.get("id") for n in raw}
    if len(ids) < min_items:
        raise RuntimeError(f"Hilma palautti vain {len(ids)} ilmoitusta (raja {min_items}); vanha aineisto säilytetään")
    if total and len(ids) < 0.9 * total:
        log(f"warn: hilma ilmoitti {total} ilmoitusta mutta sivutus antoi {len(ids)}")
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen = set()
    items = []
    for n in raw:
        if n.get("id") in seen:
            continue
        seen.add(n.get("id"))
        items.append(_trim(n))
    save_json(OUT, {"fetched": now, "openCount": total, "items": items}, compact=True)
    log(f"hilma: {len(items)} avointa kilpailutusta (Hilma: {total}) -> {OUT}")


if __name__ == "__main__":
    main()
