"""Commission delegated acts after adoption: the scrutiny (objection) period in Parliament and Council.

Source: the Commission's Register of Delegated Acts (webgate.ec.europa.eu/regdel) – the public web app's
own JSON backend (/regdel/web/). One POST lists every delegated act (≈2 200, ~300 kB); per act two small
GETs give the events (adoption, notification, extensions, early non-objection, objection, publication) and
the objection periods per institution (months; 2+2 is the norm, 1/3 for financial RTS, 3+3 in some acts).
The session needs the register's CSRF cookie, obtained with one GET; no login.

Dates in the register are Brussels-midnight epochs; they are converted to local dates. The objection
period runs from the transmission to Parliament and Council – the register records the adoption date
and, when it differs, a separate notification event; the later of the two is used as the start.

Cache: data/cache/regdel.json. Kept: acts under scrutiny, scrutiny finished (awaiting publication), and
acts published / objected / withdrawn within keep_days. Per-act details are refetched only when the
register's updateDate changes.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from zoneinfo import ZoneInfo

import requests

from common import CACHE_DIR, CONFIG_DIR, TODAY, load_json, load_yaml, log, save_json
from fetch_eu import act_dates

BASE = "https://webgate.ec.europa.eu/regdel/web/"
OUT = CACHE_DIR / "regdel.json"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) saadosseuranta/1.0 (+https://github.com/EditMonster/Saadosseuranta)", "Accept": "application/json"}
BXL = ZoneInfo("Europe/Brussels")
OPEN = {"ADOPTED", "NOTIFIED"}
WAITING = {"SCRUTINY_FINISHED", "SCRUTINY_FINISHED_URGENCY_PROCEDURE"}
CLOSED = {"PUBLISHED", "PUBLISHED_URGENCY_PROCEDURE", "OBJECTED", "WITHDRAWN", "CANCELLED"}
KEEP_FIELDS = ("id", "shortTitle", "completeTitle", "cCode", "celexNumber", "updateDate", "delegatedActStatus", "delegatedActPhase",
               "delegatedActType", "summary", "adoptionDate")


def day(ms) -> str | None:
    if not ms:
        return None
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000, tz=dt.timezone.utc).astimezone(BXL).date().isoformat()
    except (ValueError, OSError, TypeError):
        return None


def session() -> tuple[requests.Session, str]:
    s = requests.Session()
    s.headers.update(UA)
    r = s.get(BASE + "security/status", timeout=60)
    r.raise_for_status()
    tok = s.cookies.get("XSRF-TOKEN")
    if not tok:
        raise RuntimeError("regdel: CSRF-evästettä ei saatu – rekisterin rajapinta on ehkä muuttunut")
    return s, tok


def get(s: requests.Session, path: str, tries: int = 3):
    last = None
    for i in range(tries):
        try:
            r = s.get(BASE + path, timeout=60)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"{r.status_code} {path}")
        except requests.RequestException as e:
            last = e
        time.sleep(2 * (i + 1))
    raise last  # type: ignore[misc]


def main():
    settings = load_yaml(CONFIG_DIR / "settings.yaml").get("delegoidut", {})
    keep_days = int(settings.get("keep_days", 90))
    stale_days = int(settings.get("stale_days", 400))
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    stale = (TODAY - dt.timedelta(days=stale_days)).isoformat()
    s, tok = session()
    r = s.post(BASE + "delegatedActs", data=json.dumps({"language": "en"}), headers={"Content-Type": "application/json", "X-XSRF-TOKEN": tok}, timeout=180)
    r.raise_for_status()
    acts = r.json().get("list") or []
    if len(acts) < 500:
        raise RuntimeError(f"regdel: vain {len(acts)} delegoitua säädöstä – rajapinta on ehkä muuttunut")
    cache = load_json(OUT, {}) or {}
    old = cache.get("acts") or {}
    skip = cache.get("skip") or {}   # acts looked at and found too old: {id: status} – not fetched again unless the status changes
    new_skip: dict[str, str] = {}
    keep: dict[str, dict] = {}
    for a in acts:
        st = a.get("delegatedActStatus")
        aid = str(a.get("id"))
        if st in OPEN or st in WAITING:
            pass
        elif st in CLOSED:
            # recently concluded acts: before we have the events, the act's own year (C-number / CELEX) is the
            # only cheap signal – the register's updateDate is touched in bulk and would make us fetch everything
            prev = old.get(aid)
            years = re.findall(r"C\((\d{4})\)|^3(\d{4})", (a.get("cCode") or "") + " " + (a.get("celexNumber") or ""))
            year = max((int(y[0] or y[1]) for y in years), default=0)
            if skip.get(aid) == st:
                new_skip[aid] = st
                continue
            if prev:
                if (prev.get("publication") or prev.get("objection") or prev.get("adoption") or "0000") < cutoff:
                    new_skip[aid] = st
                    continue
            elif year < TODAY.year - 1:
                new_skip[aid] = st
                continue
        else:
            continue  # PLANNED / ON_HOLD: not yet adopted (the feedback phase is covered by Have your say)
        rec = {k: a.get(k) for k in KEEP_FIELDS}
        ba = a.get("basicAct") or {}
        rec["basicAct"] = {"code": ba.get("code"), "celex": ba.get("celexNumber"), "title": ba.get("completeTitle"),
                           "procedure": ba.get("procedureCode"), "deadlineRaw": ba.get("deadlineRaw")}
        pa = a.get("policyArea") or a.get("author") or {}
        rec["policyArea"] = pa.get("shortName")
        rec["policyAreaName"] = pa.get("longName")
        prev = old.get(aid) or {}
        fresh = prev.get("events") is not None and prev.get("delegatedActStatus") == st and (
            st in CLOSED or prev.get("eventsFetched") == TODAY.isoformat())
        if fresh:
            rec["events"], rec["deadlines"], rec["eventsFetched"] = prev["events"], prev["deadlines"], prev.get("eventsFetched")
        else:
            rec["eventsFetched"] = TODAY.isoformat()
            try:
                evs = get(s, f"delegatedActs/{aid}/events")
                dls = get(s, f"delegatedActs/{aid}/deadlines")
            except Exception as e:  # noqa: BLE001
                log(f"warn: regdel {aid} ({rec['cCode']}): {e}")
                rec["events"], rec["deadlines"] = prev.get("events") or [], prev.get("deadlines") or []
            else:
                rec["events"] = sorted(({"date": day(e.get("eventDate")), "type": e.get("eventType"), "institution": (e.get("eventInstitution") or "").replace("INSTITUTION_", ""),
                                         "months": (e.get("deadline") or {}).get("deadlineRaw")} for e in evs if e.get("eventDate")), key=lambda e: e["date"] or "")
                rec["deadlines"] = [{"type": d.get("deadlineType"), "months": d.get("deadlineRaw"), "institution": (d.get("deadlineInstitution") or "").replace("INSTITUTION_", "")} for d in dls]
                time.sleep(0.2)
        # quick lookups for the keep rule next run
        rec["adoption"] = next((e["date"] for e in rec["events"] if e["type"] in ("DA_ADOPTION", "DA_URGENT_ADOPTION")), None)
        rec["publication"] = next((e["date"] for e in rec["events"] if e["type"] in ("DA_PUBLICATION", "DA_URGENT_PUB")), None)
        rec["objection"] = next((e["date"] for e in rec["events"] if e["type"] in ("DA_OBJECTION", "DA_WITHDRAWAL", "DA_CANCELLATION")), None)
        if st in CLOSED and (rec["publication"] or rec["objection"] or rec["adoption"] or "0000") < cutoff:
            new_skip[aid] = st
            continue
        if st not in CLOSED and (rec["adoption"] or "0000") < stale:
            new_skip[aid] = st
            continue  # the register holds a few never-closed records from years ago
        # Finnish title and entry into force from Cellar once the act is in the Official Journal (cached by CELEX)
        if rec.get("celexNumber"):
            if (prev.get("cellar") or {}).get("celex") == rec["celexNumber"]:
                rec["cellar"] = prev["cellar"]
            else:
                try:
                    c = act_dates(rec["celexNumber"])
                    rec["cellar"] = {"celex": c["celex"], "title_fi": c["title_fi"], "oj": c["oj"], "eif": c["eif"], "deadlines": c["deadlines"], "inForce": c["inForce"]}
                except Exception as e:  # noqa: BLE001
                    log(f"warn: regdel cellar {rec['celexNumber']}: {e}")
        keep[aid] = rec
    save_json(OUT, {"fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "acts": keep, "skip": new_skip})
    n_open = sum(1 for v in keep.values() if v["delegatedActStatus"] in OPEN)
    log(f"regdel: {len(acts)} delegoitua säädöstä rekisterissä, {len(keep)} seurannassa ({n_open} vastustamisaika käynnissä, "
        f"{sum(1 for v in keep.values() if v['delegatedActStatus'] in WAITING)} odottaa julkaisua) -> {OUT}")


if __name__ == "__main__":
    main()
