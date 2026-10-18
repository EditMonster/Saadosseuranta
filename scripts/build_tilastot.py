"""Kertyvä data → todennäköisyydet: base rates and medians from the caches and data/history/.

build_tilastot(items, tenders) reads the source caches (data/cache) and the long series fetch_history.py keeps
(data/history), computes docs/data/tilastot.json and returns it; compute() is the pure core (no network, no
files) and context_for() turns the payload into short Finnish sentences for a row's drawer.

Every statistic carries its sample size `n`; a value computed from fewer than MIN_N (3) observations is None.
Durations are calendar days (int, the median unless stated); shares are fractions rounded to three decimals.
A quantile object is {"median", "p25", "p75", "n"}; a single-median object {"median", "n"}.

What the numbers mean – and their caveats
* eduskunta.overall / byCommittee / byMinistry: for every HE in data/cache/eduskunta.json the days from
  ANTO (the HE was given) to VKPM (the committee report), to 2K (second reading = approval; AK for
  one-reading matters) and to the confirmation of the act (vahvistettu). byCommittee groups by the
  committee that wrote the report; byMinistry by the drafting ministry via Hankeikkuna's heNumerot (an HE
  without a Hankeikkuna project is counted in overall only). reportChangedShare = share of committee
  reports (Vaski, kind mietintö, decision muutettuna/muuttamattomana) that amend the proposal; nReports its
  n; dissentShare = reports with at least one vastalause among reports whose dissent count is known. The
  Vaski series is younger than the HE series (reports of the current and previous year), so the shares and
  the medians rest on different windows. byMinistry also gives statementsMedian (Hankeikkuna lausunnot.n
  per project, projects with ≥ 1 statement) and consultationDaysMedian (LAUSUNTOKIERROS end − start).
* suunnitelma: Hankeikkuna projects with a planned presentation week (esittelyviikko). onTimeShare = HEs
  given to Parliament within ± 1 week of the planned ISO week (among planned projects that were given).
  Hankeikkuna overwrites esittelyviikko with the actual week when the HE is given, so the plan compared
  against is vanhaEsittelyviikko (the plan before the last move) when present – a project moved twice
  is measured against its second plan, which flatters the share. slippedShare = projects whose planned
  week was moved at least once (vanhaEsittelyviikko present) among all planned projects;
  medianSlipWeeks = signed median of the last move in weeks (negative = brought forward); droppedShare =
  removed from the session's list (poistettuPaiva or heTila POISTETTU_ISTUNTOKAUDEN_AIKANA). byMinistry
  repeats these per ministry.
* mao: procurement rulings (history mao.json ∪ data/cache/mao.json), counted per ruling – one appeal can
  produce several rulings (interim + final) and one ruling can decide several joined appeals. Interim
  decisions (välipäätös) are excluded from outcomes and upheldShare. outcomes = share per
  fetch_mao.OUTCOMES label; upheldShare = the appeal succeeded (hankintapäätös kumottu, hyvitysmaksu,
  tehottomuusseuraamus, seuraamusmaksu, sopimuskauden lyhentäminen) – 'upheld' is the appellant's
  perspective. Finlex publishes a selection of the court's rulings and markkinaoikeus.fi the newest; the
  selection may over-represent rulings with a point of law. byCategory uses build_mao.classify_subject on
  keywords + background; byBuyer groups by the normalised respondent name (top 25 by n, n ≥ 3).
  medianDaysFiledToRuling joins the pending list (appeals.json) to rulings via the link fetch_mao.py makes,
  so it is null until enough appeals seen on the list have been ruled. appealsPerBuyer90 counts entries
  filed in the last 90 days on the court's list of pending appeals (statutory list, no legal effect).
* kkv: KKV merger decisions since fetch_history.KKV_SINCE (history kkv.json ∪ data/cache/kkv.json) with a
  final outcome (hyväksytty / ehdoin / kielletty / rauennut / esitys MAO). phase2Share = share moved to an
  in-depth investigation; conditionsShare = approved with conditions; medianDaysPhase1/2 = calendar days
  from notification to the final decision (the statutory clocks run in working days: 23 + 69, and stop
  while KKV waits for information, so calendar days overstate the statutory time). Notification dates come
  from the case pages, which the backfill fetches a few per run – n grows over the first runs. bySector is a
  keyword classification of KKV's summary (NACE labels of config/yrityskaupat.yaml) and is approximate.
* hankinnat: contractMonthsByCpv = contract length by CPV division (first two digits of the main CPV code)
  from award notices (durationMonths, else contractEnd − contractStart), options excluded and spans under a
  month dropped (call-offs within a framework or DPS, not contract periods); tenderDaysByCpv =
  days from publication to the deadline of open notices (both bids and requests to participate);
  retenderCadenceByBuyer = median months between consecutive contract starts of the same buyer in the same
  CPV division when the history holds ≥ 3 such awards spanning at least a year – null until it does.
* delegoidut: Commission delegated acts in the register (acts kept in the cache plus the status list of
  the ones only scanned): objectedShare = objected by Parliament or Council among acts with a final status;
  withdrawnShare = withdrawn or cancelled; medianObjectionMonths = the statutory objection period
  (Parliament's original deadline in months); earlyNonObjectionShare = published in the Official Journal
  before the objection period could have lapsed (early non-objection by both institutions), among published
  acts with known dates; extendedShare = the period was extended at least once.

Everything is an estimate from what the pipeline happened to see; the series start when the pipeline
started following a source and the history grows by one run at a time.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
import statistics
from collections import Counter, defaultdict

from common import CACHE_DIR, OUT_DIR, ROOT, TODAY, load_json, log, save_json
from fetch_mao import norm

HISTORY_DIR = ROOT / "data" / "history"
OUT = OUT_DIR / "tilastot.json"
MIN_N = 3
KKV_SINCE = "2024-01-01"
NOTE = "Arvio seurannan kertyneestä aineistosta: mediaaneja ja osuuksia, n = havaintojen määrä; alle 3 havainnon luvut ovat null"
APPEAL_UPHELD = re.compile(r"kumottu|kumoaa|hyvitysmaksu|tehottom|seuraamusmaksu|sopimuskauden lyhent", re.I)
INTERIM = re.compile(r"välipäätös|keskeytetty väliaikaisesti|täytäntöönpanokielto|täytäntöönpano sallittu", re.I)
KKV_FINAL = {"hyväksytty", "ehdoin", "kielletty", "rauennut", "esitys MAO"}
DROPPED_STATE = "POISTETTU_ISTUNTOKAUDEN_AIKANA"
REGDEL_CLOSED = {"PUBLISHED", "PUBLISHED_URGENCY_PROCEDURE", "OBJECTED", "WITHDRAWN", "CANCELLED"}
_HE = re.compile(r"(\d+)/(\d{4})")
_CITY = re.compile(r"^\s*([A-Za-zÄÖÅäöå-]+n)\s+kaupun")


# ----------------------------------------------------------------------------- small helpers
def _rows(x) -> list[dict]:
    if isinstance(x, dict):
        x = x.get("items") or x.get("acts") or []
    if isinstance(x, dict):
        x = list(x.values())
    return [r for r in (x or []) if isinstance(r, dict)]


def _date(s) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _days(a, b) -> int | None:
    da, db = _date(a), _date(b)
    return (db - da).days if da and db else None


def _nums(values) -> list[float]:
    return [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]


def quantiles(values, *, digits: int = 0) -> dict:
    """{"median", "p25", "p75", "n"}; None values below MIN_N."""
    vals = sorted(_nums(values))
    n = len(vals)
    if n < MIN_N:
        return {"median": None, "p25": None, "p75": None, "n": n}
    q1, q2, q3 = statistics.quantiles(vals, n=4, method="inclusive")
    rnd = (lambda x: int(round(x))) if digits == 0 else (lambda x: round(x, digits))
    return {"median": rnd(q2), "p25": rnd(q1), "p75": rnd(q3), "n": n}


def median(values, *, digits: int = 0) -> dict:
    """{"median", "n"}; None below MIN_N."""
    vals = _nums(values)
    n = len(vals)
    if n < MIN_N:
        return {"median": None, "n": n}
    m = statistics.median(vals)
    return {"median": int(round(m)) if digits == 0 else round(m, digits), "n": n}


def share(num: int, den: int) -> float | None:
    return None if den < MIN_N else round(num / den, 3)


def he_key(s) -> str | None:
    """'HE 248/2026 vp' / 'HE 248/2026' / '248/2026' -> '248/2026'."""
    m = _HE.search(str(s or ""))
    return f"{int(m.group(1))}/{m.group(2)}" if m else None


def cpv_division(cpv) -> str | None:
    s = re.sub(r"\D", "", str(cpv or "").split()[0] if str(cpv or "").split() else "")
    return s[:2] if len(s) >= 2 and s[:2] != "00" else None


def week_delta(date_iso, week, year) -> int | None:
    """Signed weeks between the planned ISO week and the week of the date."""
    d = _date(date_iso)
    try:
        planned = dt.date.fromisocalendar(int(year), int(week), 1)
    except (TypeError, ValueError):
        return None
    if not d:
        return None
    return (d - dt.timedelta(days=d.weekday()) - planned).days // 7


def weeks_between(year1, week1, year2, week2) -> int | None:
    try:
        return (dt.date.fromisocalendar(int(year2), int(week2), 1) - dt.date.fromisocalendar(int(year1), int(week1), 1)).days // 7
    except (TypeError, ValueError):
        return None


def buyer_keys(name) -> list[str]:
    """Lookup keys for a contracting entity, most specific first: the whole name, the part before a comma or dash,
    and the city behind a city department ('Helsingin kaupunki – Stara' -> 'helsingin', 'helsingin kaupunki')."""
    out = []
    for cand in (name or "", re.split(r",| – | - |/", name or "")[0]):
        k = norm(cand)
        if k and k not in out:
            out.append(k)
    m = _CITY.match(name or "")
    if m:
        k = norm(m.group(1) + " kaupunki")
        if k and k not in out:
            out.append(k)
    return out


# ----------------------------------------------------------------------------- eduskunta
def _he_records(eduskunta: dict) -> dict[str, dict]:
    out = {}
    for he, r in (eduskunta.get("items") or {}).items():
        if not isinstance(r, dict):
            continue
        stages = [s for s in r.get("stages") or [] if isinstance(s, dict) and s.get("date")]
        by = defaultdict(list)
        for s in stages:
            by[s.get("code")].append(s)
        anto = min((s["date"] for s in by.get("ANTO", [])), default=None)
        vkpm = min(by.get("VKPM", []), key=lambda s: s["date"], default=None)
        approval = max((s["date"] for s in by.get("2K", [])), default=None) or max((s["date"] for s in by.get("AK", [])), default=None)
        out[he_key(he) or str(he)] = {"anto": anto, "report": vkpm["date"] if vkpm else None, "reportCommittee": (vkpm or {}).get("committee"),
                                      "approval": approval, "confirmed": (r.get("vahvistettu") or "")[:10] or None, "committees": r.get("committees") or []}
    return out


def _timing(recs: list[dict]) -> dict:
    pos = lambda xs: [x for x in xs if x is not None and x >= 0]  # noqa: E731
    return {"n": len(recs),
            "heToReport": quantiles(pos(_days(r["anto"], r["report"]) for r in recs)),
            "heToApproval": quantiles(pos(_days(r["anto"], r["approval"]) for r in recs)),
            "heToConfirmation": quantiles(pos(_days(r["anto"], r["confirmed"]) for r in recs))}


def _report_stats(reports: list[dict]) -> dict:
    decided = [r for r in reports if r.get("decision") in ("muutettuna", "muuttamattomana")]
    with_dissent = [r for r in reports if isinstance(r.get("dissent"), int)]
    return {"reportChangedShare": share(sum(1 for r in decided if r["decision"] == "muutettuna"), len(decided)), "nReports": len(decided),
            "dissentShare": share(sum(1 for r in with_dissent if r["dissent"] > 0), len(with_dissent))}


def _he_ministries(hankeikkuna, items) -> dict[str, str]:
    m: dict[str, str] = {}
    for p in _rows(hankeikkuna):
        for h in p.get("heNumerot") or []:
            k, mi = he_key(h), (p.get("ministerio") or "").strip().lower()
            if k and mi:
                m.setdefault(k, mi)
    for it in _rows(items):
        if it.get("scope") == "fi":
            for h in it.get("heNumerot") or []:
                k, mi = he_key(h), (it.get("ministry") or "").strip().lower()
                if k and mi:
                    m.setdefault(k, mi)
    return m


def eduskunta_stats(eduskunta: dict, vaski: dict, hankeikkuna, items) -> dict:
    recs = _he_records(eduskunta or {})
    with_anto = [r for r in recs.values() if r["anto"]]
    reports = [r for r in (vaski or {}).get("reports", {}).values() if isinstance(r, dict) and (r.get("kind") or "mietintö") == "mietintö"]
    overall = _timing(with_anto)
    overall.update(_report_stats(reports))
    overall["since"] = min((r["anto"] for r in with_anto), default=None)
    by_committee: dict[str, dict] = {}
    groups = defaultdict(list)
    for r in with_anto:
        if r["reportCommittee"]:
            groups[str(r["reportCommittee"]).lower()].append(r)
    rep_groups = defaultdict(list)
    for r in reports:
        name = (r.get("committeeName") or "").strip().lower()
        if name:
            rep_groups[name].append(r)
    for name in sorted(set(groups) | set(rep_groups)):
        e = _timing(groups.get(name, []))
        e.update(_report_stats(rep_groups.get(name, [])))
        by_committee[name] = e
    he_min = _he_ministries(hankeikkuna, items)
    by_ministry: dict[str, dict] = {}
    mgroups = defaultdict(list)
    for key, r in recs.items():
        if r["anto"] and he_min.get(key):
            mgroups[he_min[key]].append(r)
    mreports = defaultdict(list)
    for r in reports:
        k = he_key(r.get("asia"))
        if k and he_min.get(k):
            mreports[he_min[k]].append(r)
    projects = defaultdict(list)
    for p in _rows(hankeikkuna):
        mi = (p.get("ministerio") or "").strip().lower()
        if mi:
            projects[mi].append(p)
    for mi in sorted(set(mgroups) | set(projects)):
        e = _timing(mgroups.get(mi, []))
        e.update(_report_stats(mreports.get(mi, [])))
        ps = projects.get(mi, [])
        e["statementsMedian"] = median(p["lausunnot"]["n"] for p in ps if isinstance(p.get("lausunnot"), dict) and isinstance(p["lausunnot"].get("n"), int) and p["lausunnot"]["n"] > 0)
        cons = []
        for p in ps:
            for et in p.get("etapit") or []:
                if isinstance(et, dict) and et.get("tyyppi") == "LAUSUNTOKIERROS":
                    d = _days(et.get("date"), et.get("end"))
                    if d is not None and 0 < d <= 365:
                        cons.append(d)
        e["consultationDaysMedian"] = median(cons)
        by_ministry[mi] = e
    return {"overall": overall, "byCommittee": by_committee, "byMinistry": by_ministry}


# ----------------------------------------------------------------------------- lainsäädäntösuunnitelma
def _plan_stats(projects: list[dict]) -> dict:
    planned = [p for p in projects if p.get("esittelyviikko") and p.get("esittelyvuosi")]
    given = []
    for p in planned:
        if p.get("annettuEduskunnalle"):
            # Hankeikkuna overwrites esittelyviikko with the actual week once the HE is given, so the plan to measure
            # against is the previous week when one is recorded (the last plan before the move), else the current one
            week, year = (p["vanhaEsittelyviikko"], p.get("vanhaEsittelyvuosi") or p["esittelyvuosi"]) if p.get("vanhaEsittelyviikko") else (p["esittelyviikko"], p["esittelyvuosi"])
            d = week_delta(p["annettuEduskunnalle"], week, year)
            if d is not None:
                given.append(d)
    slips = []
    for p in planned:
        if p.get("vanhaEsittelyviikko"):
            w = weeks_between(p.get("vanhaEsittelyvuosi") or p["esittelyvuosi"], p["vanhaEsittelyviikko"], p["esittelyvuosi"], p["esittelyviikko"])
            if w is not None:
                slips.append(w)
    dropped = sum(1 for p in planned if p.get("poistettuPaiva") or p.get("heTila") == DROPPED_STATE)
    return {"n": len(planned), "nGiven": len(given), "onTimeShare": share(sum(1 for d in given if abs(d) <= 1), len(given)),
            "slippedShare": share(len(slips), len(planned)), "medianSlipWeeks": median(slips)["median"] if len(slips) >= MIN_N else None, "nSlipped": len(slips),
            "droppedShare": share(dropped, len(planned))}


def suunnitelma_stats(hankeikkuna) -> dict:
    projects = _rows(hankeikkuna)
    out = _plan_stats(projects)
    by = defaultdict(list)
    for p in projects:
        mi = (p.get("ministerio") or "").strip().lower()
        if mi:
            by[mi].append(p)
    out["byMinistry"] = {mi: _plan_stats(ps) for mi, ps in sorted(by.items())}
    return out


# ----------------------------------------------------------------------------- markkinaoikeus
def _rulings(mao_history: dict, mao_cache: dict) -> dict[str, dict]:
    rulings: dict[str, dict] = {}
    for k, r in (mao_history.get("items") or {}).items():
        if isinstance(r, dict) and r.get("outcome"):
            rulings[r.get("number") or k] = dict(r)
    for k, d in (mao_cache.get("decisions") or {}).items():
        if not isinstance(d, dict) or d.get("category") != "hankinta" or not d.get("outcome"):
            continue
        num = d.get("number") or k
        row = rulings.setdefault(num, {"number": num})
        for f in ("date", "outcome", "respondent", "appellant", "value", "keywords", "interim"):
            if row.get(f) in (None, "", []) and d.get(f) not in (None, "", []):
                row[f] = d[f]
    return rulings


def _is_interim(r: dict) -> bool:
    return bool(r.get("interim")) or bool(INTERIM.search(str(r.get("outcome") or "")))


def _group_upheld(rows: list[dict]) -> dict:
    return {"n": len(rows), "upheldShare": share(sum(1 for r in rows if APPEAL_UPHELD.search(str(r.get("outcome") or ""))), len(rows))}


def mao_stats(mao_history: dict, mao_cache: dict, appeals_history: dict, today: dt.date) -> dict:
    rulings = _rulings(mao_history or {}, mao_cache or {})
    final = [r for r in rulings.values() if not _is_interim(r)]
    n = len(final)
    outcomes = {o: round(c / n, 3) for o, c in Counter(r["outcome"] for r in final).most_common()} if n >= MIN_N else {}
    by_cat: dict[str, dict] = {}
    cats = defaultdict(list)
    for r in final:
        cat = r.get("category") or (r.get("topics") or [None])[0]
        if cat:
            cats[cat].append(r)
    for cat, rows in sorted(cats.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        by_cat[cat] = _group_upheld(rows)
    buyers = defaultdict(list)
    names: dict[str, Counter] = defaultdict(Counter)
    for r in final:
        k = norm(r.get("respondent") or "")
        if k:
            buyers[k].append(r)
            names[k][r["respondent"]] += 1
    by_buyer: dict[str, dict] = {}
    for k, rows in sorted(buyers.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:25]:
        if len(rows) >= MIN_N:
            by_buyer[names[k].most_common(1)[0][0]] = {**_group_upheld(rows), "key": k}
    # appeals: the pending list, history and cache
    appeals: dict[str, dict] = {}
    for k, a in (appeals_history.get("items") or {}).items() if appeals_history else []:
        if isinstance(a, dict):
            appeals[k] = dict(a)
    for k, p in (mao_cache.get("pending") or {}).items() if mao_cache else []:
        if isinstance(p, dict):
            row = appeals.setdefault(k, {})
            for f in ("filed", "buyer", "decisionDate", "decision", "missingSince"):
                if p.get(f) and not row.get(f):
                    row[f] = p[f]
    durations = []
    for a in appeals.values():
        ruled = (rulings.get(a.get("decision") or "") or {}).get("date")
        d = _days(a.get("filed"), ruled)
        if d is not None and d >= 0:
            durations.append(d)
    cutoff = (today - dt.timedelta(days=90)).isoformat()
    recent = [a for a in appeals.values() if (a.get("filed") or "") >= cutoff]
    per_buyer: Counter = Counter()
    disp: dict[str, Counter] = defaultdict(Counter)
    for a in recent:
        k = norm(a.get("buyer") or "")
        if k:
            per_buyer[k] += 1
            disp[k][a["buyer"]] += 1
    dec_to_filed = [d for d in (_days(a.get("decisionDate"), a.get("filed")) for a in appeals.values()) if d is not None and 0 <= d <= 120]
    return {"since": min((r["date"] for r in final if r.get("date")), default=None), "n": n, "nInterim": len(rulings) - n, "outcomes": outcomes,
            "upheldShare": share(sum(1 for r in final if APPEAL_UPHELD.search(str(r["outcome"]))), n), "byCategory": by_cat, "byBuyer": by_buyer,
            "medianDaysFiledToRuling": median(durations), "medianDaysDecisionToFiled": median(dec_to_filed),
            "appeals90": len(recent), "appealsPerBuyer90": {disp[k].most_common(1)[0][0]: c for k, c in per_buyer.most_common()},
            "nAppeals": len(appeals)}


# ----------------------------------------------------------------------------- KKV
def _kkv_cases(kkv_history: dict, kkv_cache: dict) -> dict[str, dict]:
    cases: dict[str, dict] = {}
    for k, r in (kkv_history.get("items") or {}).items() if kkv_history else []:
        if isinstance(r, dict):
            cases[r.get("diaari") or k] = dict(r)
    for k, c in (kkv_cache.get("cases") or {}).items() if kkv_cache else []:
        if not isinstance(c, dict):
            continue
        key = c.get("diaari") or k
        row = cases.setdefault(key, {"diaari": key})
        if c.get("decided") and c.get("decision") and not row.get("decided"):
            low = c["decision"].lower()
            row["decided"] = c["decided"]
            row["outcome"] = "ehdoin" if "ehdollisena" in low else "kielletty" if "kieltäminen" in low else "rauennut" if "raukea" in low else "esitys MAO" if "markkinaoikeu" in low else "hyväksytty" if "hyväksy" in low else "muu"
        for f in ("notified", "parties", "phase2Start"):
            if c.get(f) and not row.get(f):
                row[f] = c[f]
        if c.get("phase2Start") or "jatko" in str(c.get("listStatus") or "").lower():
            row["phase"] = 2
        row.setdefault("phase", 1)
    return cases


def kkv_stats(kkv_history: dict, kkv_cache: dict, *, since: str = KKV_SINCE) -> dict:
    cases = _kkv_cases(kkv_history or {}, kkv_cache or {})
    decided = [c for c in cases.values() if c.get("decided") and c.get("outcome") in KKV_FINAL and (c["decided"] >= since or (c.get("notified") or "") >= since)]
    n = len(decided)
    p2 = [c for c in decided if c.get("phase") == 2]
    p1 = [c for c in decided if c.get("phase") != 2]
    days = lambda rows: [d for d in (_days(c.get("notified"), c.get("decided")) for c in rows) if d is not None and d >= 0]  # noqa: E731
    sectors = defaultdict(list)
    for c in decided:
        if c.get("sector"):
            sectors[c["sector"]].append(c)
    return {"since": min((c["decided"] for c in decided), default=None), "n": n, "nPending": sum(1 for c in cases.values() if not c.get("decided")),
            "phase2Share": share(len(p2), n), "conditionsShare": share(sum(1 for c in decided if c["outcome"] == "ehdoin"), n),
            "prohibitedShare": share(sum(1 for c in decided if c["outcome"] in ("kielletty", "esitys MAO")), n),
            "medianDaysPhase1": median(days(p1)), "medianDaysPhase2": median(days(p2)),
            "outcomes": {o: round(c / n, 3) for o, c in Counter(c["outcome"] for c in decided).most_common()} if n >= MIN_N else {},
            "bySector": {s: {"n": len(rows), "phase2Share": share(sum(1 for c in rows if c.get("phase") == 2), len(rows))}
                         for s, rows in sorted(sectors.items(), key=lambda kv: (-len(kv[1]), kv[0]))}}


# ----------------------------------------------------------------------------- hankinnat
def _contract_months(a: dict) -> float | None:
    m = a.get("durationMonths")
    if isinstance(m, (int, float)) and not isinstance(m, bool) and 0 < m <= 240:
        return float(m)
    d = _days(a.get("contractStart"), a.get("contractEnd"))
    if d is not None and 30 <= d <= 240 * 30.44:  # shorter spans are call-offs (a charter trip, a delivery), not contract periods
        return round(d / 30.44, 1)
    return None


def hankinnat_stats(awards_history: dict, sopimuskaudet: dict, hankinnat_cache: dict, tenders: list[dict]) -> dict:
    # award notices: history, the current contract-period cache and award rows of the published list
    awards: dict[str, dict] = {}
    for k, a in (awards_history.get("items") or {}).items() if awards_history else []:
        if isinstance(a, dict):
            awards[str(a.get("noticeId") or k)] = dict(a)
    for k, n in (sopimuskaudet.get("notices") or {}).items() if sopimuskaudet else []:
        if isinstance(n, dict) and n.get("buyer") and not n.get("skip"):
            key = str(n.get("noticeId") or n.get("id") or k)
            awards.setdefault(key, {"noticeId": key, "buyer": n.get("buyer"), "buyerId": n.get("buyerId"), "cpv": str(n.get("cpv") or "").split()[0] if n.get("cpv") else None,
                                    "contractStart": n.get("contractStart"), "contractEnd": n.get("contractEnd"), "durationMonths": n.get("durationMonths")})
    for t in tenders:
        if t.get("stage") in ("ratkaistu", "suorahankinta", "ennuste") and (t.get("durationMonths") or (t.get("contractStart") and t.get("contractEnd"))):
            key = re.sub(r"^hk-(enn-)?", "", str(t.get("id") or ""))
            key = key[3:] if key.startswith("EF-") and key[3:].isdigit() else key
            awards.setdefault(key, {"noticeId": key, "buyer": t.get("buyer"), "buyerId": t.get("buyerId"), "cpv": t.get("cpv"), "contractStart": t.get("contractStart"),
                                    "contractEnd": t.get("contractEnd"), "durationMonths": t.get("durationMonths")})
    by_div = defaultdict(list)
    for a in awards.values():
        div, m = cpv_division(a.get("cpv")), _contract_months(a)
        if div and m is not None:
            by_div[div].append(m)
    contract_months = {div: quantiles(vals) for div, vals in sorted(by_div.items())}
    # open notices: days from publication to the deadline
    opens: dict[str, dict] = {}
    for r in _rows(hankinnat_cache):
        if r.get("datePublished") and r.get("deadline"):
            opens[str(r.get("id") or r.get("noticeId"))] = {"published": r["datePublished"], "deadline": r["deadline"], "cpv": r.get("cpvCodes")}
    for t in tenders:
        if t.get("stage") == "avoin" and t.get("published") and t.get("deadline"):
            opens.setdefault(str(t.get("id")), {"published": t["published"], "deadline": t["deadline"], "cpv": t.get("cpv")})
    tdays = defaultdict(list)
    for o in opens.values():
        div, d = cpv_division(o.get("cpv")), _days(o.get("published"), o.get("deadline"))
        if div and d is not None and 0 < d <= 365:
            tdays[div].append(d)
    tender_days = {div: quantiles(vals) for div, vals in sorted(tdays.items())}
    # re-tender cadence: gaps between contract starts of the same buyer in the same CPV division (history only)
    starts: dict[tuple[str, str], set[str]] = defaultdict(set)
    disp: dict[str, Counter] = defaultdict(Counter)
    for a in (awards_history.get("items") or {}).values() if awards_history else []:
        if not isinstance(a, dict):
            continue
        bk, div, st = (a.get("buyerId") or norm(a.get("buyer") or "")), cpv_division(a.get("cpv")), (a.get("contractStart") or "")[:10]
        if bk and div and _date(st):
            starts[(bk, div)].add(st)
            disp[bk][a.get("buyer")] += 1
    gaps: dict[str, list[float]] = defaultdict(list)
    counts: Counter = Counter()
    for (bk, div), ds in starts.items():
        s = sorted(ds)
        if len(s) < MIN_N or (_days(s[0], s[-1]) or 0) < 365:
            continue
        gaps[bk] += [(_days(a, b) or 0) / 30.44 for a, b in zip(s, s[1:])]
        counts[bk] += len(s)
    cadence = {disp[bk].most_common(1)[0][0]: {"n": counts[bk], "medianMonths": int(round(statistics.median(g)))} for bk, g in gaps.items() if g}
    return {"contractMonthsByCpv": contract_months, "tenderDaysByCpv": tender_days, "retenderCadenceByBuyer": cadence or None,
            "nAwards": len(awards), "nOpen": len(opens)}


# ----------------------------------------------------------------------------- delegoidut säädökset
def _add_months(d: dt.date, months: float) -> dt.date:
    whole = int(months)
    y, m = divmod(d.month - 1 + whole, 12)
    y += d.year
    m += 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return dt.date(y, m, day) + dt.timedelta(days=round((months - whole) * 30.44))


def delegoidut_stats(regdel: dict) -> dict:
    acts = [a for a in (regdel.get("acts") or {}).values() if isinstance(a, dict)] if regdel else []
    statuses = Counter()
    for a in acts:
        if a.get("delegatedActStatus") in REGDEL_CLOSED:
            statuses[a["delegatedActStatus"]] += 1
    for st in (regdel.get("skip") or {}).values() if regdel else []:
        if st in REGDEL_CLOSED:
            statuses[st] += 1
    n = sum(statuses.values())
    months_list, early, published, extended, with_deadline = [], 0, 0, 0, 0
    for a in acts:
        dls = [d for d in a.get("deadlines") or [] if isinstance(d, dict) and isinstance(d.get("months"), (int, float))]
        orig = [d["months"] for d in dls if d.get("type") == "ORIGINAL" and d.get("institution") == "PARLIAMENT"] or [d["months"] for d in dls if d.get("type") == "ORIGINAL"]
        if orig:
            with_deadline += 1
            months_list.append(max(orig))
            if any(d.get("type") != "ORIGINAL" for d in dls) or any(e.get("type") == "DA_EXTENSION" for e in a.get("events") or []):
                extended += 1
        if a.get("delegatedActStatus") in ("PUBLISHED", "PUBLISHED_URGENCY_PROCEDURE") and a.get("publication") and orig:
            start = max(x for x in (a.get("adoption"), next((e.get("date") for e in a.get("events") or [] if e.get("type") == "DA_NOTIFICATION"), None)) if x)
            d0, pub = _date(start), _date(a["publication"])
            if d0 and pub:
                published += 1
                total = max(orig) + (max((d["months"] for d in dls if d.get("type") != "ORIGINAL"), default=0))
                if pub < _add_months(d0, total) or any(e.get("type") in ("DA_EARLY_NON_OBJECTION", "DA_NON_OBJECTION") for e in a.get("events") or []):
                    early += 1
    return {"n": n, "objectedShare": share(statuses.get("OBJECTED", 0), n), "withdrawnShare": share(statuses.get("WITHDRAWN", 0) + statuses.get("CANCELLED", 0), n),
            "medianObjectionMonths": median(months_list, digits=1), "extendedShare": share(extended, with_deadline), "nWithDeadline": with_deadline,
            "earlyNonObjectionShare": share(early, published), "nPublished": published, "statuses": dict(statuses)}


# ----------------------------------------------------------------------------- compute + wiring
def compute(items, tenders, *, eduskunta=None, hankeikkuna=None, vaski=None, mao=None, kkv=None, sopimuskaudet=None, hankinnat=None, regdel=None,
            history: dict | None = None, today: dt.date | str | None = None) -> dict:
    """The statistics payload from in-memory inputs (pure). `history` = {"mao", "kkv", "awards", "appeals"} as the
    data/history files are; missing inputs count as empty."""
    today = _date(today) if isinstance(today, str) else (today or TODAY)
    h = history or {}
    tl = _rows(tenders)
    return {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "today": today.isoformat(), "minN": MIN_N, "note": NOTE,
        "eduskunta": eduskunta_stats(eduskunta or {}, vaski or {}, hankeikkuna or {}, items),
        "suunnitelma": suunnitelma_stats(hankeikkuna or {}),
        "mao": mao_stats(h.get("mao") or {}, mao or {}, h.get("appeals") or {}, today),
        "kkv": kkv_stats(h.get("kkv") or {}, kkv or {}),
        "hankinnat": hankinnat_stats(h.get("awards") or {}, sopimuskaudet or {}, hankinnat or {}, tl),
        "delegoidut": delegoidut_stats(regdel or {}),
    }


def load_history() -> dict:
    return {name: (load_json(HISTORY_DIR / f"{name}.json", {}) or {}) for name in ("mao", "kkv", "awards", "appeals")}


def build_tilastot(items, tenders) -> dict:
    """Read the caches and data/history, write docs/data/tilastot.json and return the payload. No network."""
    cache = lambda name: load_json(CACHE_DIR / f"{name}.json", {}) or {}  # noqa: E731
    stats = compute(items, tenders, eduskunta=cache("eduskunta"), hankeikkuna=cache("hankeikkuna"), vaski=cache("vaski"), mao=cache("mao"), kkv=cache("kkv"),
                    sopimuskaudet=cache("sopimuskaudet"), hankinnat=cache("hankinnat"), regdel=cache("regdel"), history=load_history())
    save_json(OUT, stats, compact=True)
    e, m, k, hk = stats["eduskunta"], stats["mao"], stats["kkv"], stats["hankinnat"]
    log(f"tilastot: {e['overall']['n']} HE:tä ({len(e['byCommittee'])} valiokuntaa, {len(e['byMinistry'])} ministeriötä), {m['n']} MAO-ratkaisua, "
        f"{k['n']} KKV-päätöstä, {hk['nAwards']} jälki-ilmoitusta, {len(hk['contractMonthsByCpv'])} CPV-jakoa, {stats['delegoidut']['n']} delegoitua säädöstä -> {OUT}")
    return stats


# ----------------------------------------------------------------------------- context sentences (Finnish)
def _pct(x) -> str:
    if 0 < x < 0.01:
        return "alle 1 %"
    return f"{int(round(x * 100))} %"


def _fi(x, digits: int = 1) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _ok(stat) -> bool:
    return isinstance(stat, dict) and stat.get("median") is not None


def _he_lines(row: dict, stats: dict) -> list[str]:
    out = []
    ed = stats.get("eduskunta") or {}
    plan = stats.get("suunnitelma") or {}
    ministry = (row.get("ministry") or "").strip().lower()
    is_he = row.get("kind") == "HE" or bool(row.get("heNumerot")) or (row.get("laji") == "laki")
    if is_he:
        found = False
        for c in row.get("committees") or []:
            cs = (ed.get("byCommittee") or {}).get(str(c).strip().lower())
            if not cs:
                continue
            parts = []
            if _ok(cs.get("heToReport")):
                parts.append(f"mietintö tyypillisesti {cs['heToReport']['median']} pv HE:n antamisesta (mediaani, n={cs['heToReport']['n']})")
            if cs.get("reportChangedShare") is not None:
                parts.append(f"{_pct(cs['reportChangedShare'])} mietinnöistä muuttaa esitystä (n={cs['nReports']})")
            if parts:
                out.append(f"{_cap(str(c))}: " + "; ".join(parts))
                found = True
        ov = ed.get("overall") or {}
        if not found and _ok(ov.get("heToReport")) and _ok(ov.get("heToApproval")):
            out.append(f"Kaikki HE:t: mietintö tyypillisesti {ov['heToReport']['median']} pv ja hyväksyntä {ov['heToApproval']['median']} pv antamisesta "
                       f"(mediaanit, n={ov['heToReport']['n']})")
    ms = (ed.get("byMinistry") or {}).get(ministry)
    if ms:
        name = _cap(ministry)
        if is_he and _ok(ms.get("heToApproval")):
            out.append(f"{name}: HE:n antamisesta eduskunnan hyväksyntään tyypillisesti {ms['heToApproval']['median']} pv (mediaani, n={ms['heToApproval']['n']})")
        parts = []
        if _ok(ms.get("statementsMedian")):
            parts.append(f"lausuntoja tyypillisesti {ms['statementsMedian']['median']} hanketta kohden (mediaani, n={ms['statementsMedian']['n']})")
        if _ok(ms.get("consultationDaysMedian")):
            parts.append(f"lausuntoaika {ms['consultationDaysMedian']['median']} pv (mediaani, n={ms['consultationDaysMedian']['n']})")
        if parts:
            out.append(f"{name}: " + ", ".join(parts))
    if is_he and (row.get("plan") or row.get("planned")):
        ps = (plan.get("byMinistry") or {}).get(ministry) or plan
        label = _cap(ministry) if ps is not plan else "Lainsäädäntösuunnitelma"
        if ps.get("onTimeShare") is not None:
            line = f"{label}: {_pct(ps['onTimeShare'])} HE:istä annettiin suunnitellulla viikolla (±1 vk, n={ps['nGiven']})"
            if ps.get("slippedShare") is not None:
                line += f"; suunniteltu viikko siirtyi {_pct(ps['slippedShare'])}:lla hankkeista (n={ps['n']})"
            out.append(line)
    return out


def _tender_lines(row: dict, stats: dict) -> list[str]:
    out = []
    mo = stats.get("mao") or {}
    hk = stats.get("hankinnat") or {}
    stage = row.get("stage")
    buyer = row.get("buyer") or ""
    keys = buyer_keys(buyer)
    per90 = {norm(b): c for b, c in (mo.get("appealsPerBuyer90") or {}).items()}
    for k in keys:
        if per90.get(k):
            out.append(f"Hankintayksikön päätöksistä {per90[k]} valitus{'ta' if per90[k] != 1 else ''} markkinaoikeuteen 90 pv:ssä")
            break
    by_buyer = {v.get("key"): (name, v) for name, v in (mo.get("byBuyer") or {}).items()}
    for k in keys:
        if k in by_buyer and by_buyer[k][1].get("upheldShare") is not None:
            name, v = by_buyer[k]
            out.append(f"Markkinaoikeus: {name} – valittaja menestyi {_pct(v['upheldShare'])}:ssa ratkaisuista (n={v['n']})")
            break
    if stage in ("mao", "paatos") or row.get("maoNumber") or row.get("appealed"):
        top = list((mo.get("outcomes") or {}).items())[:3]
        if top:
            out.append("Markkinaoikeus: " + ", ".join(f"{o} {_pct(s)}" for o, s in top) + f" ratkaisuista (n={mo['n']})")
        if mo.get("upheldShare") is not None:
            out.append(f"Markkinaoikeus: valittaja menestyi {_pct(mo['upheldShare'])}:ssa ratkaisuista (n={mo['n']})")
        if _ok(mo.get("medianDaysFiledToRuling")):
            out.append(f"Markkinaoikeus: valituksesta ratkaisuun tyypillisesti {mo['medianDaysFiledToRuling']['median']} pv (mediaani, n={mo['medianDaysFiledToRuling']['n']})")
        for t in row.get("topics") or []:
            cs = (mo.get("byCategory") or {}).get(t)
            if cs and cs.get("upheldShare") is not None:
                out.append(f"Markkinaoikeus ({t}): valittaja menestyi {_pct(cs['upheldShare'])}:ssa ratkaisuista (n={cs['n']})")
                break
    div = cpv_division(row.get("cpv"))
    if div:
        cm = (hk.get("contractMonthsByCpv") or {}).get(div)
        if _ok(cm):
            out.append(f"Sopimuskausi tässä CPV-jaossa tyypillisesti {cm['median']} kk (mediaani, n={cm['n']}; neljännesvälit {cm['p25']}–{cm['p75']} kk)")
        td = (hk.get("tenderDaysByCpv") or {}).get(div)
        if _ok(td) and stage in ("avoin", "tulossa", "kalenteri", "ennuste", None):
            out.append(f"Tarjousaika tässä CPV-jaossa tyypillisesti {td['median']} pv ilmoituksesta määräaikaan (mediaani, n={td['n']})")
    cad = hk.get("retenderCadenceByBuyer") or {}
    cad_norm = {norm(b): v for b, v in cad.items()}
    for k in keys:
        if k in cad_norm and cad_norm[k].get("medianMonths"):
            out.append(f"Hankintayksikkö on kilpailuttanut saman CPV-jaon tyypillisesti {cad_norm[k]['medianMonths']} kk välein (n={cad_norm[k]['n']})")
            break
    return out


def _merger_lines(row: dict, stats: dict) -> list[str]:
    out = []
    if (row.get("authority") or "KKV") != "KKV":
        return out  # only KKV has a history series here
    ks = stats.get("kkv") or {}
    if ks.get("phase2Share") is not None:
        out.append(f"KKV: jatkoselvitykseen {_pct(ks['phase2Share'])} ilmoituksista (n={ks['n']})")
    if _ok(ks.get("medianDaysPhase1")):
        out.append(f"KKV: 1. vaiheen päätös tyypillisesti {ks['medianDaysPhase1']['median']} pv ilmoituksesta (mediaani kalenteripäivinä, n={ks['medianDaysPhase1']['n']})")
    if (row.get("phase") == 2 or row.get("status") == "jatkokäsittelyssä") and _ok(ks.get("medianDaysPhase2")):
        out.append(f"KKV: jatkoselvitykseen siirretyt ratkaistu tyypillisesti {ks['medianDaysPhase2']['median']} pv ilmoituksesta (mediaani, n={ks['medianDaysPhase2']['n']})")
    if ks.get("conditionsShare") is not None:
        out.append(f"KKV: ehdollisena hyväksytty {_pct(ks['conditionsShare'])} päätöksistä (n={ks['n']})")
    for s in [row.get("sector")] + list(row.get("topics") or []):
        ss = (ks.get("bySector") or {}).get(s) if s else None
        if ss and ss.get("phase2Share") is not None:
            out.append(f"KKV ({s}): jatkoselvitykseen {_pct(ss['phase2Share'])} ilmoituksista (n={ss['n']})")
            break
    return out


def _delegated_lines(stats: dict) -> list[str]:
    out = []
    ds = stats.get("delegoidut") or {}
    if ds.get("objectedShare") is not None:
        line = f"Delegoidut säädökset: parlamentti tai neuvosto vastusti {_pct(ds['objectedShare'])} säädöksistä"
        if ds.get("withdrawnShare") is not None:
            line += f", {_pct(ds['withdrawnShare'])} peruutettiin"
        out.append(line + f" (n={ds['n']})")
    if _ok(ds.get("medianObjectionMonths")):
        line = f"Vastustamisaika tyypillisesti {_fi(ds['medianObjectionMonths']['median'])} kk (mediaani, n={ds['medianObjectionMonths']['n']})"
        if ds.get("earlyNonObjectionShare") is not None:
            line += f"; julkaistu ennen määräajan päättymistä {_pct(ds['earlyNonObjectionShare'])}:ssa (n={ds['nPublished']})"
        out.append(line)
    return out


def context_for(row: dict | None, stats: dict | None) -> list[str]:
    """Short Finnish sentences for a row's drawer: the base rates and medians that apply to this HE, tender, appeal,
    merger or delegated act. Pure; every sentence states its n and nothing is said below MIN_N observations."""
    if not isinstance(row, dict) or not isinstance(stats, dict) or not row or not stats:
        return []
    scope, laji = row.get("scope"), row.get("laji")
    if row.get("authority") in ("KKV", "EU") or scope == "yrityskauppa" or laji == "yrityskauppa":
        lines = _merger_lines(row, stats)
    elif scope == "hankinta" or laji == "kilpailutus" or row.get("stage") in ("avoin", "tulossa", "ratkaistu", "suorahankinta", "mao", "paatos", "ennuste", "kalenteri"):
        lines = _tender_lines(row, stats)
    elif laji == "delegoitu":
        lines = _delegated_lines(stats)
    elif scope == "fi" or row.get("heNumerot") or row.get("committees") or row.get("ministry"):
        lines = _he_lines(row, stats)
    else:
        lines = []
    out = []
    for line in lines:
        if line not in out:
            out.append(line)
    return out


def main() -> dict:
    items = load_json(OUT_DIR / "items.json", {}) or {}
    tenders = load_json(OUT_DIR / "hankinnat.json", {}) or {}
    return build_tilastot(items, tenders)


if __name__ == "__main__":
    main()
