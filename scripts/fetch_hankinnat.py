"""Hilma (hankintailmoitukset.fi): the public-procurement lifecycle – prior information notices and
market consultations (what is coming), open contract notices (what you can bid on), award notices
(who won) and ex-ante transparency notices for direct awards (14-day appeal window).

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
        "tedPublicationId", "noticeOjsNumber", "procurementDocumentsUrl", "tenderingInHilma", "winnerOrganisations",
        "noticeResultTotalAmount", "noticeResultTotalAmountCurrency")
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


def fetch_filter(flt: str) -> tuple[list[dict], int]:
    """Page through one Hilma search filter (max 1000 per page)."""
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


def fetch_open() -> tuple[list[dict], int]:
    """Contract notices the Hilma search page lists as open (listing not expired)."""
    return fetch_filter(f"(search.in(mainType, 'ContractNotices|NationalNotices', '|') and expirationDate ge {TODAY.isoformat()}T00:00:00Z)"
                        " and isPlan eq false")


def fetch_prior() -> tuple[list[dict], int]:
    """Prior information notices, market consultations and ex-ante transparency notices still listed."""
    return fetch_filter(f"search.in(mainType, 'PriorInformationNotices', '|') and expirationDate ge {TODAY.isoformat()}T00:00:00Z"
                        " and isPlan eq false")


def fetch_awards(days: int) -> tuple[list[dict], int]:
    """Contract award notices (incl. national direct-award notices) published in the last `days` days."""
    since = (TODAY - dt.timedelta(days=days)).isoformat()
    return fetch_filter(f"search.in(mainType, 'ContractAwardNotices', '|') and datePublished ge {since}T00:00:00Z and isPlan eq false")


def main():
    settings = load_yaml(CONFIG_DIR / "settings.yaml").get("hankinnat", {})
    min_items = int(settings.get("min_items", 100))
    award_days = int(settings.get("award_days", 30))
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
    # The other lifecycle stages are optional: a failure there must not lose the open tenders.
    prior, awards = [], []
    try:
        prior, _ = fetch_prior()
    except Exception as e:  # noqa: BLE001
        log(f"warn: ennakkoilmoitusten haku epäonnistui: {e}")
    try:
        awards, _ = fetch_awards(award_days)
    except Exception as e:  # noqa: BLE001
        log(f"warn: jälki-ilmoitusten haku epäonnistui: {e}")
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen = set()
    items = []
    for n in raw + prior + awards:
        if n.get("id") in seen:
            continue
        seen.add(n.get("id"))
        items.append(_trim(n))
    save_json(OUT, {"fetched": now, "openCount": total, "items": items}, compact=True)
    log(f"hilma: {len(ids)} avointa kilpailutusta (Hilma: {total}), {len(prior)} ennakko-/avoimuusilmoitusta, "
        f"{len(awards)} jälki-ilmoitusta ({award_days} pv) -> {OUT}")


if __name__ == "__main__":
    main()
