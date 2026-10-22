"""Ajastin (scripts/ajastus.py) ja huoltokatkon tunnistus (common.http, update.is_outage)."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import ajastus  # noqa: E402
import common  # noqa: E402
import update  # noqa: E402

FI = ZoneInfo("Europe/Helsinki")


def fi(y, m, d, h, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=FI).astimezone(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def health(ran: dt.datetime, failing: dict | None = None, extra: int = 3) -> dict:
    h = {f"s{i}": {"ok": True, "streak": 0, "last_ok": iso(ran)} for i in range(extra)}
    for k, fail_at in (failing or {}).items():
        h[k] = {"ok": False, "streak": 1, "last_ok": iso(ran - dt.timedelta(days=1)), "last_fail": iso(fail_at)}
    h["_issue"] = {"key": ""}
    return h


def test_last_slot_weekday_weekend_and_dst():
    # Wed 21.10.2026 (EEST, UTC+3)
    assert ajastus.last_slot(fi(2026, 10, 21, 6, 59)) == fi(2026, 10, 20, 16)
    assert ajastus.last_slot(fi(2026, 10, 21, 7, 0)) == fi(2026, 10, 21, 7)
    assert ajastus.last_slot(fi(2026, 10, 21, 15, 0)) == fi(2026, 10, 21, 12)
    # Sat 24.10. 08:00 -> Fri 16:00; Sun 25.10. (DST ends 04:00) 10:00 -> Sun 09:00 EET = 07:00 UTC
    assert ajastus.last_slot(fi(2026, 10, 24, 8, 0)) == fi(2026, 10, 23, 16)
    assert ajastus.last_slot(fi(2026, 10, 25, 10, 0)) == dt.datetime(2026, 10, 25, 7, 0, tzinfo=dt.timezone.utc)
    # Mon 26.10. 06:00 -> Sun 09:00
    assert ajastus.last_slot(fi(2026, 10, 26, 6, 0)) == fi(2026, 10, 25, 9)


def test_missed_wakeup_is_caught_up_next_hour():
    # the 07:11 wake-up was dropped by GitHub; at 08:11 the 07:00 slot has not been run -> full run
    d = ajastus.decide(fi(2026, 10, 21, 8, 11), health(fi(2026, 10, 20, 16, 11)))
    assert d["run"] and d["steps"] == "" and "myöhässä" in d["reason"]
    # once run, the next wake-up does nothing
    d = ajastus.decide(fi(2026, 10, 21, 9, 11), health(fi(2026, 10, 21, 8, 11)))
    assert not d["run"]


def test_on_time_run():
    d = ajastus.decide(fi(2026, 10, 21, 12, 11), health(fi(2026, 10, 21, 7, 11)))
    assert d["run"] and d["steps"] == "" and "myöhässä" not in d["reason"]


def test_retry_failing_sources_hourly_in_daytime():
    ran = fi(2026, 10, 21, 7, 11)
    h = health(ran, failing={"mao": ran, "paatokset": ran})
    assert not ajastus.decide(fi(2026, 10, 21, 7, 51), h)["run"]  # 40 min: wait
    d = ajastus.decide(fi(2026, 10, 21, 8, 11), h)                  # 1 h: retry only the failing ones
    assert d["run"] and d["steps"] == "mao paatokset"
    # a retry does not count as the full run: the 12:00 slot still triggers a full run
    h2 = health(ran, failing={"mao": fi(2026, 10, 21, 11, 11), "paatokset": fi(2026, 10, 21, 11, 11)})
    assert not ajastus.decide(fi(2026, 10, 21, 11, 41), h2)["run"]
    d = ajastus.decide(fi(2026, 10, 21, 12, 11), h2)
    assert d["run"] and d["steps"] == ""


def test_no_retries_at_night():
    ran = fi(2026, 10, 21, 16, 11)
    h = health(ran, failing={"mao": ran})
    assert ajastus.decide(fi(2026, 10, 21, 21, 11), h)["run"]       # still in the window
    assert not ajastus.decide(fi(2026, 10, 21, 23, 11), h)["run"]   # night: wait for the morning
    assert ajastus.decide(fi(2026, 10, 22, 7, 11), h)["steps"] == ""  # morning slot: full run


def test_empty_health_runs():
    assert ajastus.decide(fi(2026, 10, 21, 12, 11), {})["run"]


def test_maintenance_redirect_detection():
    assert common.maintenance_redirect("https://www.markkinaoikeus.fi/x", "https://vara.markkinaoikeus.fi/") == "vara.markkinaoikeus.fi"
    assert common.maintenance_redirect("https://paatokset.hel.fi/fi", "https://kopio.hel.fi/fi") == "kopio.hel.fi"
    assert common.maintenance_redirect("https://www.kho.fi/a", "https://www.kho.fi/b") is None
    assert common.maintenance_redirect("https://korkeinoikeus.fi/", "https://www.korkeinoikeus.fi/") is None


class _Resp:
    def __init__(self, url, status=200, history=()):
        self.url, self.status_code, self.history, self.headers = url, status, list(history), {}


def test_http_raises_outage_on_maintenance_page(monkeypatch):
    monkeypatch.setattr(common.SESSION, "request", lambda m, u, **k: _Resp("https://vara.kho.fi/", 200, [_Resp(u, 302)]))
    with pytest.raises(common.SourceOutage):
        common.http("GET", "https://www.kho.fi/paatokset/")


def test_http_raises_outage_after_5xx(monkeypatch):
    monkeypatch.setattr(common.time, "sleep", lambda s: None)
    monkeypatch.setattr(common.SESSION, "request", lambda m, u, **k: _Resp(u, 522))
    with pytest.raises(common.SourceOutage) as e:
        common.http("POST", "https://api.hankeikkuna.fi/api/v2/kohteet/haku")
    assert update.is_outage(e.value)


def test_http_timeout_is_outage(monkeypatch):
    monkeypatch.setattr(common.time, "sleep", lambda s: None)

    def boom(m, u, **k):
        raise requests.ConnectTimeout("timeout")
    monkeypatch.setattr(common.SESSION, "request", boom)
    with pytest.raises(common.SourceOutage):
        common.http("GET", "https://example.org/")


def test_is_outage_follows_cause():
    try:
        try:
            raise common.SourceOutage("huoltokatko")
        except common.SourceOutage as inner:
            raise RuntimeError("markkinaoikeus: haku epäonnistui") from inner
    except RuntimeError as e:
        assert update.is_outage(e)
    assert not update.is_outage(RuntimeError("0 riviä – rakenne muuttunut"))
