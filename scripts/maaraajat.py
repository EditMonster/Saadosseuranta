"""Computing statutory time limits – one place for every deadline the pipeline calculates itself.

Finnish periods: laki säädettyjen määräaikain laskemisesta (150/1930)
  2 §  A period of N days after a given day does not count that day:            last day = start + N.
  3 §  A period in weeks/months/years ends on the day with the same name/number;
       if the final month has no such day, on the last day of that month.
  5 §  If the given day or the last day of the period falls on a holiday (pyhäpäivä, incl. every Sunday),
       Independence Day, May Day, Christmas Eve, Midsummer Eve or a working Saturday (arkilauantai), the act
       may still be done on the first weekday (arkipäivä) after it. In effect: Saturdays, Sundays and the
       days below move the deadline to the next Monday–Friday that is none of them.
  Holidays: uudenvuodenpäivä 1.1., loppiainen 6.1., pitkäperjantai, pääsiäispäivä, 2. pääsiäispäivä,
  vapunpäivä 1.5., helatorstai (pääsiäinen + 39), helluntaipäivä (Sunday), juhannusaatto (pe 19.–25.6.),
  juhannuspäivä (la 20.–26.6.), pyhäinpäivä (la 31.10.–6.11.), itsenäisyyspäivä 6.12., jouluaatto 24.12.,
  joulupäivä 25.12., tapaninpäivä 26.12.
  The law (1 §) governs periods "vid domstol eller annan myndighet" – appeals, hankintaoikaisu, KHO.

EU periods: Council Regulation (EEC, Euratom) No 1182/71, Article 3
  (1) the day of the event is not counted; (2)(c) a period in months ends with the expiry of the last hour of
  the day in the last month with the same date (or the month's last day); (4) if the last day is a public
  holiday, Saturday or Sunday, the period ends with the expiry of the last hour of the following working day.
  Public holidays are those of the institution concerned; the set below is the common core of the Commission,
  Parliament and Council calendars (New Year, Good Friday, Easter Monday, 1 May, 9 May, Ascension, Whit
  Monday, Christmas, 26 December). Institution-specific extra days (e.g. 24–31 December at the Commission)
  are not shifted for – the deadline shown is therefore never later than the real one.

`fi_deadline` / `eu_deadline` return {"date", "nominal", "shifted"} with ISO dates; `shifted_note_*` give the
clause appended to a deadline's label on the page when the end day was moved.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache


def easter(year: int) -> dt.date:
    """Gregorian Easter Sunday (Anonymous Gregorian / Meeus–Jones–Butcher algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month, day = divmod(h + ll - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def _first_weekday_between(year: int, month: int, d0: int, d1: int, weekday: int) -> dt.date:
    for day in range(d0, d1 + 1):
        x = dt.date(year, month, day)
        if x.weekday() == weekday:
            return x
    raise ValueError("no such weekday")


@lru_cache(maxsize=64)
def fi_holidays(year: int) -> dict[dt.date, str]:
    """Days other than plain Saturdays/Sundays on which a Finnish statutory deadline cannot end (150/1930 5 §)."""
    e = easter(year)
    midsummer_eve = _first_weekday_between(year, 6, 19, 25, 4)  # Friday 19.–25.6.
    all_saints = dt.date(year, 10, 31) + dt.timedelta(days=(5 - dt.date(year, 10, 31).weekday()) % 7)  # Saturday 31.10.–6.11.
    return {
        dt.date(year, 1, 1): "uudenvuodenpäivä", dt.date(year, 1, 6): "loppiainen",
        e - dt.timedelta(days=2): "pitkäperjantai", e: "pääsiäispäivä", e + dt.timedelta(days=1): "2. pääsiäispäivä",
        dt.date(year, 5, 1): "vapunpäivä", e + dt.timedelta(days=39): "helatorstai", e + dt.timedelta(days=49): "helluntaipäivä",
        midsummer_eve: "juhannusaatto", midsummer_eve + dt.timedelta(days=1): "juhannuspäivä", all_saints: "pyhäinpäivä",
        dt.date(year, 12, 6): "itsenäisyyspäivä", dt.date(year, 12, 24): "jouluaatto",
        dt.date(year, 12, 25): "joulupäivä", dt.date(year, 12, 26): "tapaninpäivä",
    }


@lru_cache(maxsize=64)
def eu_holidays(year: int) -> dict[dt.date, str]:
    e = easter(year)
    return {
        dt.date(year, 1, 1): "New Year", e - dt.timedelta(days=2): "Good Friday", e + dt.timedelta(days=1): "Easter Monday",
        dt.date(year, 5, 1): "Labour Day", dt.date(year, 5, 9): "Europe Day", e + dt.timedelta(days=39): "Ascension Day",
        e + dt.timedelta(days=50): "Whit Monday", dt.date(year, 12, 25): "Christmas Day", dt.date(year, 12, 26): "26 December",
    }


def _d(x) -> dt.date:
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x)[:10])


def why_closed_fi(day) -> str | None:
    """Reason a day cannot be the last day of a Finnish statutory period, or None for an ordinary weekday."""
    d = _d(day)
    name = fi_holidays(d.year).get(d)
    if name:
        return name
    if d.weekday() == 5:
        return "lauantai"
    if d.weekday() == 6:
        return "sunnuntai"
    return None


def why_closed_eu(day) -> str | None:
    d = _d(day)
    name = eu_holidays(d.year).get(d)
    if name:
        return name
    return {5: "Saturday", 6: "Sunday"}.get(d.weekday())


def next_open_fi(day) -> dt.date:
    d = _d(day)
    while why_closed_fi(d):
        d += dt.timedelta(days=1)
    return d


def next_open_eu(day) -> dt.date:
    d = _d(day)
    while why_closed_eu(d):
        d += dt.timedelta(days=1)
    return d


def add_months(start, months: float) -> dt.date:
    """150/1930 3 § and Reg. 1182/71 art. 3(2)(c): same day number in the final month, or that month's last day."""
    base = _d(start)
    whole = int(months)
    y, m = divmod(base.month - 1 + whole, 12)
    y, m = base.year + y, m + 1
    last = (dt.date(y + (m == 12), (m % 12) + 1, 1) - dt.timedelta(days=1)).day
    out = dt.date(y, m, min(base.day, last))
    if months != whole:  # fractional months do not occur in statutes; keep arithmetic defined
        out += dt.timedelta(days=round((months - whole) * 30))
    return out


def fi_deadline(start, days: int | None = None, months: float | None = None) -> dict:
    """Finnish statutory period from `start` (the day of the event, not counted). Returns
    {"date": ISO last day after 5 §, "nominal": ISO last day before shifting, "shifted": reason or None}."""
    s = _d(start)
    nominal = s + dt.timedelta(days=days) if days is not None else add_months(s, months or 0)
    final = next_open_fi(nominal)
    return {"date": final.isoformat(), "nominal": nominal.isoformat(), "shifted": why_closed_fi(nominal) if final != nominal else None}


def eu_deadline(start, days: int | None = None, months: float | None = None) -> dict:
    s = _d(start)
    nominal = s + dt.timedelta(days=days) if days is not None else add_months(s, months or 0)
    final = next_open_eu(nominal)
    return {"date": final.isoformat(), "nominal": nominal.isoformat(), "shifted": why_closed_eu(nominal) if final != nominal else None}


def shifted_note_fi(res: dict) -> str:
    return f" – siirtyy, {_fmt(res['nominal'])} on {res['shifted']} (määräaikalaki 5 §)" if res.get("shifted") else ""


def shifted_note_eu(res: dict) -> str:
    return f" – siirtyy, {_fmt(res['nominal'])} on vapaapäivä (asetus 1182/71 3 art. 4 kohta)" if res.get("shifted") else ""


def _fmt(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{int(d)}.{int(m)}.{y}"
