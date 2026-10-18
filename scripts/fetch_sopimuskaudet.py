"""Contract periods behind Hilma award notices – the raw material for re-tender forecasts.

The Hilma search index that fetch_hankinnat.py reads has no duration fields at all; the contract
period lives only in the per-notice JSON the Hilma SPA loads. This script looks at every award
notice in data/cache/hankinnat.json (mainType ContractAwardNotices: EU and national jälki-ilmoitukset,
old-schema national direct-award notices included), fetches the public detail document once and
extracts, per lot:

* eForms notices (ids ``EF-*``):
  ``GET https://www.hankintailmoitukset.fi/web/api/public/procedure/{procedureId}/enotice/{noticeId}``
  – BT-536/537 start/end date, BT-36 duration, BT-57 renewal description, BT-58 max renewals,
  BT-54 options description, BT-765 framework-agreement flag, BT-145/1451 contract conclusion and
  award-decision dates, the tender → tendering party → organization join that yields the real
  winners with their Y-tunnus, and the award value (BT-118 framework maximum, result total or the
  national extension's contract value).
* old-schema notices (ids ``OLD-*``): ``GET https://www.hankintailmoitukset.fi/web/api/notices/{id}``
  – ``objectDescriptions[].timeFrame`` (type 1 days / 2 months / 3 begin+end), ``optionsAndVariants``,
  ``awardContract.awardedContracts[]`` (contractors, conclusion date, final value) and the framework
  flag. National direct-award notices (type 9905) carry no time frame; a "sopimuskausi dd.mm.yyyy –
  dd.mm.yyyy" sentence in the free text is used when present.

Per notice ``contractEnd`` = the latest lot end date (an end date, or start + duration − 1 day) and
``contractEndWithOptions`` = the end incl. options: the latest dd.mm.yyyy date quoted in the renewal /
options text, else end + option months parsed from that text ("1 + 1 vuotta", "24 kk", "kahdella
yhden (1) vuoden"), else end + maxRenewals × base duration. Only notices whose contractEnd falls
between 30 days ago and 24 months ahead are kept in full; the others leave a small stub so that the
notice is not fetched again while it stays in the Hilma cache. At most 200 new notices per run,
≤ 1 request/s. Cache: data/cache/sopimuskaudet.json {fetched, notices: {noticeId: {...}}}.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
import time

from common import CACHE_DIR, TODAY, http, load_json, log, save_json

ENOTICE = "https://www.hankintailmoitukset.fi/web/api/public/procedure/{pid}/enotice/{nid}"
OLD_NOTICE = "https://www.hankintailmoitukset.fi/web/api/notices/{nid}"
HILMA_CACHE = CACHE_DIR / "hankinnat.json"
OUT = CACHE_DIR / "sopimuskaudet.json"
MAX_NEW = 200
MIN_INTERVAL = 1.0
KEEP_PAST_DAYS = 30
KEEP_AHEAD_MONTHS = 24
TEXT_MAX = 300
_DMY = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_NUM_UNIT = re.compile(r"((?:\d+\s*\+\s*)*\d+)\s*\)?\s*(vuo\w*|v\b|kk\b|kuukau\w*)", re.I)
_WORD_MULT = [(re.compile(r"\b(kahde\w*|kaks\w*)\s*(?:\(\s*2\s*\))?\s*yhden", re.I), 2),
              (re.compile(r"\b(kolme\w*)\s*(?:\(\s*3\s*\))?\s*yhden", re.I), 3),
              (re.compile(r"\b(neljä\w*)\s*(?:\(\s*4\s*\))?\s*yhden", re.I), 4)]
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÅ(])|\n+")  # never inside dates like 1.9.2028
_WORD_VALUES = {"yhden": 1, "yhdellä": 1, "yksi": 1, "kahden": 2, "kahdella": 2, "kaksi": 2, "kolmen": 3, "kolmella": 3, "kolme": 3,
                "neljän": 4, "neljällä": 4, "neljä": 4, "viiden": 5, "viidellä": 5, "viisi": 5}
_NUM_WORDS = "|".join(_WORD_VALUES)
# a spelled-out number, at most two filler words that are not themselves numbers ("enintään", "(1)"), then the unit
_WORD_NUM = re.compile(rf"\b({_NUM_WORDS})\b(?:\s*\(\s*\d\s*\))?(?:\s+(?!vuo|kuukau|kk\b|(?:{_NUM_WORDS})\b)\w+){{0,2}}\s+(vuo\w*|kuukau\w*|kk\b)", re.I)
_NOT_OPTION_BEFORE = ("viimeistään", "irtisano", "ilmoitettava", "ilmoitus", "ennen")
_NOT_OPTION_AFTER = ("ennen", "irtisano")


# ---------- small pure helpers (also used by build_ennakointi.py) ----------

def g(o, *path):
    """Safe nested getter: dict keys and list indices, None when anything is missing."""
    for p in path:
        if o is None:
            return None
        if isinstance(p, int):
            o = o[p] if isinstance(o, list) and len(o) > p else None
        else:
            o = o.get(p) if isinstance(o, dict) else None
    return o


def iso_date(value) -> str | None:
    """'2027-04-01+03:00' / '2023-07-04T00:00:00' -> '2027-04-01'; anything else -> None."""
    s = str(value or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    return None


def add_months(d: dt.date, months: int) -> dt.date:
    """Calendar-month arithmetic with the day clamped to the target month's length."""
    y, m = divmod(d.month - 1 + int(months), 12)
    year, month = d.year + y, m + 1
    return dt.date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def period_end(start: str | None, end: str | None, duration, unit: str | None) -> str | None:
    """End of a contract period: the explicit end date, else start + duration − 1 day (BT-36 semantics:
    a 48-month contract starting 2027-04-01 ends 2031-03-31)."""
    if end:
        return end
    if not start or duration in (None, "", 0):
        return None
    try:
        s = dt.date.fromisoformat(start)
        n = float(duration)
    except (TypeError, ValueError):
        return None
    u = (unit or "MONTH").upper()
    if u.startswith("DAY"):
        return (s + dt.timedelta(days=max(int(round(n)) - 1, 0))).isoformat()
    months = n * 12 if u.startswith("YEAR") or u in ("ANN", "Y") else n
    whole = int(months)
    e = add_months(s, whole)
    if months - whole > 0.01:  # fractional months: approximate the remainder in days
        e += dt.timedelta(days=int(round((months - whole) * 30.44)))
    return (e - dt.timedelta(days=1)).isoformat()


def extend(end: str, months: int) -> str:
    """The end date after `months` more months of contract (2028-08-31 + 24 -> 2030-08-31)."""
    return (add_months(dt.date.fromisoformat(end) + dt.timedelta(days=1), int(months)) - dt.timedelta(days=1)).isoformat()


def duration_months(start: str | None, end: str | None, duration, unit: str | None) -> int | None:
    """Base contract length in months from the dates when both are known, else from BT-36."""
    if start and end:
        return months_between(start, end)
    if duration in (None, "", 0):
        return None
    u = (unit or "MONTH").upper()
    try:
        n = float(duration)
    except (TypeError, ValueError):
        return None
    if u.startswith("DAY"):
        return int(round(n / 30.4375)) or None
    return int(round(n * (12 if u.startswith("YEAR") else 1)))


def months_between(start: str | None, end: str | None) -> int | None:
    try:
        s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    except (TypeError, ValueError):
        return None
    if e < s:
        return None
    return int(round(((e - s).days + 1) / 30.4375))


def option_dates(text: str) -> list[str]:
    """Every dd.mm.yyyy date quoted in a renewal/options text, as ISO dates."""
    out = []
    for d, m, y in _DMY.findall(text or ""):
        try:
            out.append(dt.date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            continue
    return out


def option_months(text: str) -> int | None:
    """Total option length in months from phrases like '1 + 1 vuotta', '24 kk', 'yhden (1) vuoden',
    'kahdella yhden (1) vuoden pituisella optiokaudella'. None when nothing recognisable."""
    t = text or ""
    if not t:
        return None
    total = 0
    for m in _NUM_UNIT.finditer(t):
        nums = [int(x) for x in re.findall(r"\d+", m.group(1))]
        if not nums or max(nums) > 120 or _not_option(t, m.start(), m.end()):
            continue
        unit = m.group(2).lower()
        months = sum(nums) * (12 if unit.startswith(("vuo", "v")) else 1)
        mult = 1
        for rx, k in _WORD_MULT:
            if rx.search(t[max(0, m.start() - 25):m.end()]):
                mult = k
        total += months * mult
    if not total:  # "kahden vuoden optio", "kahdella enintään vuoden mittaisella optiokaudella" – first spelled-out period only
        for m in _WORD_NUM.finditer(t):
            if _not_option(t, m.start(), m.end()):
                continue
            total = _WORD_VALUES[m.group(1).lower()] * (12 if m.group(2).lower().startswith("vuo") else 1)
            break
    return min(total, 120) or None


def _not_option(t: str, start: int, end: int) -> bool:
    """A period mention that is the base term ("sopimuskausi on 4 vuotta") or a notice period ("viimeistään kuusi (6)
    kuukautta ennen sopimuskauden päättymistä") rather than an option length."""
    before = t[max(0, start - 40):start].lower()
    after = t[end:end + 30].lower()
    optio_next = re.match(r"[\s(),\d]*(?:\w+\s+){0,2}optio", after)  # "…vuoden mittaisella optiokaudella"
    if ("sopimuskau" in before or "voimassa" in before) and not any(k in before for k in ("optio", "jatka")) and not optio_next:
        return True
    return any(k in before for k in _NOT_OPTION_BEFORE) or any(k in after for k in _NOT_OPTION_AFTER)


def option_sentences(text: str) -> str:
    """The sentences of a free text that mention options (optio, optiokausi…), trimmed."""
    sents = [s.strip() for s in _SENT_SPLIT.split(text or "") if s and "optio" in s.lower()]
    return " ".join(sents)[:TEXT_MAX] if sents else ""


def parse_winners(index_value: str) -> list[dict]:
    """'Duni AB (1817866-7)//Kesko Oyj (0109862-8)' -> [{name, id}, …] (Hilma index winnerOrganisations)."""
    out = []
    for part in (index_value or "").split("//"):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", part)
        out.append({"name": (m.group(1) if m else part).strip()[:120], "id": (m.group(2).strip() if m else None) or None})
    return out


# ---------- eForms extraction ----------

def extract_eforms(doc: dict) -> dict:
    """Contract-period fields of a public eForms notice document (see module docstring)."""
    ef = doc.get("eForm") or {}
    ext = g(ef, "ublExtensions", 0, "extensionContent", "eformsExtension") or {}
    nr = ext.get("noticeResult") or {}
    lots = []
    for lot in ef.get("procurementProjectLot") or []:
        pp = lot.get("procurementProject") or {}
        pl = pp.get("plannedPeriod") or {}
        ce = pp.get("contractExtension") or {}
        systems = {g(c, "contractingSystemTypeCode", "listName"): g(c, "contractingSystemTypeCode", "value")
                   for c in (g(lot, "tenderingProcess", "contractingSystem") or [])}
        start, end = iso_date(g(pl, "startDate", "value")), iso_date(g(pl, "endDate", "value"))
        dur, unit = g(pl, "durationMeasure", "value"), g(pl, "durationMeasure", "unitCode")
        renewal = " ".join(g(r, "period", "description", 0, "value") or "" for r in (ce.get("renewal") or [])).strip()
        options = " ".join(o.get("value") or "" for o in (ce.get("optionsDescription") or [])).strip()
        if not renewal and not options:  # buyers often write the options only into the lot note / description
            options = option_sentences(" ".join(n.get("value") or "" for n in (pp.get("note") or []) + (pp.get("description") or [])))
        fa = systems.get("framework-agreement")
        lots.append({
            "lotId": g(lot, "id", "value"), "startDate": start, "endDate": period_end(start, end, dur, unit),
            "durationMonths": duration_months(start, end, dur, unit),
            "renewalText": renewal[:TEXT_MAX] or None, "maxRenewals": g(ce, "maximumNumberNumeric", "value"),
            "optionsText": options[:TEXT_MAX] or None,
            "frameworkAgreement": bool(fa and fa != "none"), "dps": bool(systems.get("dps-usage") and systems.get("dps-usage") != "none"),
            "cpv": g(pp, "mainCommodityClassification", 0, "itemClassificationCode", "value"),
        })
    contracts = []
    for c in nr.get("settledContract") or []:
        contracts.append({"id": g(c, "id", "value"), "contractDate": iso_date(g(c, "issueDate", "value")),
                          "awardDate": iso_date(g(c, "awardDate", "value")),
                          "tenderIds": [g(t, "id", "value") for t in c.get("lotTender") or []]})
    results = [g(r, "tenderResultCode", "value") for r in nr.get("lotResult") or []]
    # winners: settled contract -> tender -> tendering party -> organization (the organizations list
    # also holds the buyer, the Market Court and the eSender, so the join matters)
    orgs = {g(o, "company", "partyIdentification", "id", "value"): o for o in (g(ext, "organizations", "organization") or [])}
    parties = {g(p, "id", "value"): [g(t, "id", "value") for t in p.get("tenderer") or []] for p in nr.get("tenderingParty") or []}
    tenders = {g(t, "id", "value"): t for t in nr.get("lotTender") or []}
    winners, seen = [], set()
    for c in nr.get("settledContract") or []:
        for t in c.get("lotTender") or []:
            party = g(tenders.get(g(t, "id", "value")), "tenderingParty", 0, "id", "value")
            for org_id in parties.get(party, []):
                o = orgs.get(org_id)
                name = g(o, "company", "partyName", 0, "name", "value")
                if name and name not in seen:
                    seen.add(name)
                    winners.append({"name": name[:120], "id": g(o, "company", "partyLegalEntity", 0, "companyID", "value")})
    value = g(nr, "totalAmount", "value") or g(nr, "overallMaximumFrameworkContractsAmount", "value") \
        or g(nr, "overallApproximateFrameworkContractsAmount", "value")
    currency = g(nr, "totalAmount", "currencyID") or g(nr, "overallMaximumFrameworkContractsAmount", "currencyID")
    if not value:
        nat = [g(c, "contractValueAmount", "value") for c in (g(ef, "nationalExtension", "noticeResult", "settledContracts") or [])]
        nat = [v for v in nat if v]
        if nat:
            value, currency = sum(nat), g(ef, "nationalExtension", "noticeResult", "settledContracts", 0, "contractValueAmount", "currencyID")
    if not value:
        tot = [g(t, "legalMonetaryTotal", "payableAmount", "value") for t in nr.get("lotTender") or []]
        tot = [v for v in tot if v]
        value = sum(tot) if tot else None
    return {"schema": "eforms", "title": g(ef, "procurementProject", "name", 0, "value"),
            "noticeType": g(ef, "noticeTypeCode", "value"), "subType": g(ext, "noticeSubType", "subTypeCode", "value"),
            "lots": lots, "contracts": contracts, "lotResults": results, "winners": winners,
            "value": value, "currency": currency or ("EUR" if value else None)}


# ---------- old-schema extraction ----------

_OLD_TF = {1: "DAY", 2: "MONTH", 4: "YEAR"}


def extract_old(doc: dict) -> dict:
    """Contract-period fields of an old-schema Hilma notice (``/web/api/notices/{id}``)."""
    lots, winners, contracts, seen = [], [], [], set()
    values = []
    fa = bool(g(doc, "procedureInformation", "frameworkAgreement", "includesFrameworkAgreement"))
    fa_dur = g(doc, "procedureInformation", "frameworkAgreement", "duration") or {}
    text = " ".join(x for x in (g(doc, "procurementObject", "shortDescription") or []) if isinstance(x, str))
    option_text = text
    for od in doc.get("objectDescriptions") or []:
        tf = od.get("timeFrame") or {}
        start, end = iso_date(tf.get("beginDate")), iso_date(tf.get("endDate"))
        dur, unit = None, None
        if tf.get("type") in (1, 2, 4):
            unit = _OLD_TF[tf["type"]]
            dur = tf.get({"DAY": "days", "MONTH": "months", "YEAR": "years"}[unit])
        if not start and not end and not dur and fa and fa_dur.get("months"):
            dur, unit = fa_dur.get("months"), "MONTH"
        if not start and not end and not dur:  # national forms: only free text, e.g. "Sopimuskausi 1.1.2027–31.12.2028"
            for sent in _SENT_SPLIT.split(text):
                if "sopimuskau" not in sent.lower():
                    continue
                ds = option_dates(sent)
                if len(ds) >= 2:
                    start, end = min(ds), max(ds)
                    option_text = text.replace(sent, _DMY.sub("", sent))  # those dates are the base period, not an option
                    break
        ov = od.get("optionsAndVariants") or {}
        options = " ".join(x for x in (ov.get("optionsDescription") or []) if isinstance(x, str)).strip()
        if not options and ov.get("optionsMonths"):
            options = f"Optio {ov['optionsMonths']} kk"
        renewal = " ".join(x for x in (tf.get("renewalDescription") or []) if isinstance(x, str)).strip()
        lots.append({"lotId": od.get("lotNumber") or od.get("id"), "startDate": start, "endDate": period_end(start, end, dur, unit),
                     "durationMonths": duration_months(start, end, dur, unit),
                     "renewalText": renewal[:TEXT_MAX] or None, "maxRenewals": None,
                     "optionsText": (options or option_sentences(option_text))[:TEXT_MAX] or None,
                     "frameworkAgreement": fa or bool(tf.get("isOverFourYears")), "dps": False,
                     "cpv": g(od, "mainCpvCode", "code")})
        for c in g(od, "awardContract", "awardedContracts") or []:
            contracts.append({"id": c.get("contractNumber"), "contractDate": iso_date(c.get("conclusionDate")), "awardDate": None, "tenderIds": []})
            for k in c.get("contractors") or []:
                name = k.get("officialName")
                if name and name not in seen:
                    seen.add(name)
                    winners.append({"name": name[:120], "id": k.get("nationalRegistrationNumber") or None})
            v = g(c, "finalTotalValue", "value") or g(c, "initialEstimatedValueOfContract", "value")
            if v:
                values.append((v, g(c, "finalTotalValue", "currency") or g(c, "initialEstimatedValueOfContract", "currency") or "EUR"))
    return {"schema": "old", "title": g(doc, "project", "title"), "noticeType": str(doc.get("type")), "subType": str(doc.get("type")),
            "lots": lots, "contracts": contracts, "lotResults": ["selec-w" if winners else None], "winners": winners,
            "value": sum(v for v, _ in values) if values else None, "currency": values[0][1] if values else None}


# ---------- per-notice aggregation ----------

def contract_period(info: dict) -> dict:
    """contractStart / contractEnd / contractEndWithOptions and the texts behind them, from the lots."""
    lots = info.get("lots") or []
    starts = sorted(l["startDate"] for l in lots if l.get("startDate"))
    ends = sorted(l["endDate"] for l in lots if l.get("endDate"))
    start, end = (starts[0] if starts else None), (ends[-1] if ends else None)
    renewal = next((l["renewalText"] for l in lots if l.get("renewalText")), None)
    options = next((l["optionsText"] for l in lots if l.get("optionsText")), None)
    max_renewals = max((l["maxRenewals"] for l in lots if l.get("maxRenewals")), default=None)
    durations = [l["durationMonths"] for l in lots if l.get("durationMonths")]
    duration = max(durations) if durations else months_between(start, end)
    with_options = None
    if end:
        quoted = option_dates((renewal or "") + " " + (options or ""))
        if any(d > end for d in quoted):  # the text names the option period itself ("optiokausi 1.9.2028–31.8.2030")
            with_options = max(quoted)
        elif end in quoted:  # "…optiolla 31.8.2030 asti" = the planned period already includes the options
            with_options = None
        else:
            months = option_months(renewal or "") or option_months(options or "")
            if not months and max_renewals and duration:
                months = int(max_renewals) * duration
            with_options = extend(end, months) if months else None
    return {"contractStart": start, "contractEnd": end, "contractEndWithOptions": with_options, "durationMonths": duration,
            "renewalText": renewal, "maxRenewals": int(max_renewals) if max_renewals else None, "optionsText": options,
            "framework": any(l.get("frameworkAgreement") for l in lots), "dps": any(l.get("dps") for l in lots)}


def summarise_notice(index_row: dict, info: dict) -> dict:
    """One compact cache record per award notice: index metadata + the extracted contract period."""
    period = contract_period(info)
    contracts = info.get("contracts") or []
    award_dates = sorted(c["awardDate"] for c in contracts if c.get("awardDate"))
    contract_dates = sorted(c["contractDate"] for c in contracts if c.get("contractDate"))
    winners = info.get("winners") or parse_winners(index_row.get("winnerOrganisations") or "")
    results = [r for r in (info.get("lotResults") or []) if r]
    rec = {
        "id": index_row.get("id"), "noticeId": index_row.get("noticeId"), "procedureId": index_row.get("procedureId") or None,
        "oldProcurementProjectId": index_row.get("oldProcurementProjectId") or None, "isEForms": bool(index_row.get("isEForms")),
        "type": str(index_row.get("type")), "title": (index_row.get("titleFi") or index_row.get("titleSv") or index_row.get("titleEn") or info.get("title") or "")[:220],
        "buyer": (index_row.get("organisationNameFi") or index_row.get("organisationNameSv") or index_row.get("organisationNameEn") or "")[:160] or None,
        "buyerId": index_row.get("organisationNationalRegistrationNumber") or None,
        "published": (index_row.get("datePublished") or "")[:10] or None,
        "cpv": (index_row.get("cpvCodes") or " ".join(l["cpv"] for l in info.get("lots") or [] if l.get("cpv")) or "").strip() or None,
        "eu": bool(index_row.get("isEuProcurement")), "framework": period["framework"] or bool(index_row.get("includesFrameworkAgreement")),
        "dps": period["dps"] or bool(index_row.get("includesDynamicPurcharingSystem")),
        "lots": len(info.get("lots") or []), "cancelled": bool(results) and all(r == "clos-nw" for r in results),
        "awardDate": award_dates[0] if award_dates else None, "contractDate": contract_dates[0] if contract_dates else None,
        "winners": winners[:10], "value": info.get("value") or index_row.get("noticeResultTotalAmount") or None,
        "currency": info.get("currency") or index_row.get("noticeResultTotalAmountCurrency") or ("EUR" if (info.get("value") or index_row.get("noticeResultTotalAmount")) else None),
        "checked": TODAY.isoformat(),
    }
    rec.update({k: v for k, v in period.items() if k not in ("framework", "dps")})
    return {k: v for k, v in rec.items() if v not in (None, "", [], False)}


def in_window(contract_end: str | None, today: dt.date = TODAY) -> bool:
    if not contract_end:
        return False
    lo = (today - dt.timedelta(days=KEEP_PAST_DAYS)).isoformat()
    hi = add_months(today, KEEP_AHEAD_MONTHS).isoformat()
    return lo <= contract_end <= hi


def fetch_detail(row: dict) -> dict:
    """The public detail document of one award notice, extracted; raises on HTTP/JSON errors."""
    if row.get("isEForms") and row.get("procedureId"):
        r = http("GET", ENOTICE.format(pid=row["procedureId"], nid=row["noticeId"]), timeout=60)
        r.raise_for_status()
        return extract_eforms(r.json())
    r = http("GET", OLD_NOTICE.format(nid=row["noticeId"]), timeout=60)
    r.raise_for_status()
    return extract_old(r.json())


def main():
    hilma = load_json(HILMA_CACHE, {}) or {}
    rows = [n for n in (hilma.get("items") or []) if n.get("mainType") == "ContractAwardNotices" and not n.get("isCancelled") and n.get("noticeId")]
    cache = load_json(OUT, {}) or {}
    notices: dict = cache.get("notices") or {}
    if not rows:
        log("sopimuskaudet: Hilma-välimuistissa ei jälki-ilmoituksia – välimuisti säilytetään ennallaan")
        return
    present = {str(n["noticeId"]) for n in rows}
    # newest first, those with a named winner before the rest (cancelled awards have no period worth fetching)
    todo = [n for n in rows if str(n["noticeId"]) not in notices]
    todo.sort(key=lambda n: n.get("datePublished") or "", reverse=True)   # newest first …
    todo.sort(key=lambda n: 0 if n.get("winnerOrganisations") else 1)     # … but named winners before the rest (stable)
    todo = todo[:MAX_NEW]
    fetched, failed, t0 = 0, 0, time.time()
    last = 0.0
    for n in todo:
        wait = MIN_INTERVAL - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        last = time.time()
        key = str(n["noticeId"])
        try:
            info = fetch_detail(n)
        except Exception as e:  # noqa: BLE001
            failed += 1
            log(f"warn: sopimuskaudet: ilmoituksen {n.get('id')} haku epäonnistui: {str(e)[:160]}")
            continue
        fetched += 1
        rec = summarise_notice(n, info)
        if in_window(rec.get("contractEnd")) and not rec.get("cancelled"):
            notices[key] = rec
        else:
            notices[key] = {"id": rec.get("id"), "checked": rec["checked"], "contractEnd": rec.get("contractEnd"),
                            "skip": ("peruttu" if rec.get("cancelled") else ("ei sopimuskautta" if not rec.get("contractEnd") else "ikkunan ulkopuolella"))}
    # prune: full records drift out of the window as time passes; stubs go when Hilma no longer lists the notice
    kept = {}
    for key, rec in notices.items():
        if rec.get("skip"):
            if key in present:
                kept[key] = rec
        elif in_window(rec.get("contractEnd")):
            kept[key] = rec
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_json(OUT, {"fetched": now, "notices": kept}, compact=True)
    full = sum(1 for r in kept.values() if not r.get("skip"))
    log(f"sopimuskaudet: {len(rows)} jälki-ilmoitusta Hilmassa, {fetched} uutta haettu ({failed} epäonnistui, {time.time() - t0:.0f} s), "
        f"{full} sopimuskautta ikkunassa (−{KEEP_PAST_DAYS} pv … +{KEEP_AHEAD_MONTHS} kk), {len(kept) - full} tynkää -> {OUT}")
    if todo and failed >= 10 and failed > fetched:
        raise RuntimeError(f"Hilman ilmoitusrajapinta näyttää rikkinäiseltä: {failed}/{failed + fetched} hakua epäonnistui")


if __name__ == "__main__":
    main()
