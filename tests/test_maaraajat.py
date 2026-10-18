"""Määräaikojen laskenta: laki säädettyjen määräaikain laskemisesta (150/1930) ja EU:n asetus 1182/71.
Pyhäpäivät tarkistettu almanakasta (2026: pääsiäinen 5.4., juhannusaatto 19.6., pyhäinpäivä 31.10.)."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import maaraajat as m  # noqa: E402

D = dt.date


def test_easter():
    assert [m.easter(y) for y in (2024, 2025, 2026, 2027, 2028, 2038)] == [D(2024, 3, 31), D(2025, 4, 20), D(2026, 4, 5), D(2027, 3, 28), D(2028, 4, 16), D(2038, 4, 25)]


def test_fi_holidays_2026_and_2027():
    h = m.fi_holidays(2026)
    expect = {D(2026, 1, 1): "uudenvuodenpäivä", D(2026, 1, 6): "loppiainen", D(2026, 4, 3): "pitkäperjantai", D(2026, 4, 5): "pääsiäispäivä",
              D(2026, 4, 6): "2. pääsiäispäivä", D(2026, 5, 1): "vapunpäivä", D(2026, 5, 14): "helatorstai", D(2026, 5, 24): "helluntaipäivä",
              D(2026, 6, 19): "juhannusaatto", D(2026, 6, 20): "juhannuspäivä", D(2026, 10, 31): "pyhäinpäivä", D(2026, 12, 6): "itsenäisyyspäivä",
              D(2026, 12, 24): "jouluaatto", D(2026, 12, 25): "joulupäivä", D(2026, 12, 26): "tapaninpäivä"}
    assert h == expect
    h7 = m.fi_holidays(2027)
    assert h7[D(2027, 6, 25)] == "juhannusaatto" and h7[D(2027, 11, 6)] == "pyhäinpäivä" and h7[D(2027, 3, 26)] == "pitkäperjantai"


def test_closed_days():
    assert m.why_closed_fi("2026-10-17") == "lauantai" and m.why_closed_fi("2026-10-18") == "sunnuntai"
    assert m.why_closed_fi("2026-10-19") is None
    assert m.why_closed_fi("2026-12-24") == "jouluaatto"  # Thursday, still closed (5 §)
    assert m.why_closed_eu("2026-12-24") is None and m.why_closed_eu("2026-05-09") == "Europe Day"


def test_fi_deadline_days_2_and_5():
    # 2 §: the start day is not counted
    assert m.fi_deadline("2026-10-05", days=14) == {"date": "2026-10-19", "nominal": "2026-10-19", "shifted": None}
    # ends on Saturday -> Monday
    r = m.fi_deadline("2026-10-03", days=14)
    assert r["nominal"] == "2026-10-17" and r["date"] == "2026-10-19" and r["shifted"] == "lauantai"
    # juhannusaatto Fri 19.6.2026 -> Mon 22.6.
    assert m.fi_deadline("2026-06-05", days=14)["date"] == "2026-06-22"
    # jouluaatto Thu 24.12.2026 -> Mon 28.12. (25., 26., 27. closed)
    r = m.fi_deadline("2026-12-10", days=14)
    assert r["date"] == "2026-12-28" and r["shifted"] == "jouluaatto"
    # pitkäperjantai 3.4.2026 -> Tue 7.4. (Easter Monday closed too)
    assert m.fi_deadline("2026-03-20", days=14)["date"] == "2026-04-07"
    # helatorstai 14.5.2026 -> Fri 15.5.
    assert m.fi_deadline("2026-04-30", days=14)["date"] == "2026-05-15"
    # itsenäisyyspäivä on Sunday 6.12.2026 -> Mon 7.12.
    assert m.fi_deadline("2026-11-06", days=30)["date"] == "2026-12-07"
    # vappu Fri 1.5.2026 -> Mon 4.5.
    assert m.fi_deadline("2026-04-17", days=14)["date"] == "2026-05-04"
    # uudenvuodenpäivä Fri 1.1.2027 -> Mon 4.1.
    assert m.fi_deadline("2026-12-18", days=14)["date"] == "2027-01-04"


def test_months_3():
    assert m.add_months("2026-01-31", 1) == D(2026, 2, 28)
    assert m.add_months("2028-01-31", 1) == D(2028, 2, 29)
    assert m.add_months("2026-10-18", 2) == D(2026, 12, 18)
    assert m.add_months("2026-11-30", 3) == D(2027, 2, 28)
    assert m.add_months(D(2027, 3, 15), -3) == D(2026, 12, 15)
    # a month period ending on a Saturday moves to Monday
    assert m.fi_deadline("2026-08-17", months=2)["date"] == "2026-10-19"


def test_eu_deadline():
    # 10 days after publication on Fri 9.10.2026 = Mon 19.10. (no shift)
    assert m.eu_deadline("2026-10-09", days=10)["date"] == "2026-10-19"
    # ends Sat 17.10. -> Mon 19.10.
    r = m.eu_deadline("2026-10-07", days=10)
    assert r["nominal"] == "2026-10-17" and r["date"] == "2026-10-19" and r["shifted"] == "Saturday"
    # 2 + 2 months from 25.10.2026 = Thu 25.2.2027 (no shift); from 26.10.2026: 26.12.2026 Sat -> 28.12. Mon
    assert m.eu_deadline("2026-10-25", months=4)["date"] == "2027-02-25"
    assert m.eu_deadline("2026-10-26", months=2)["date"] == "2026-12-28"
    # Ascension 14.5.2026 and Whit Monday 25.5.2026 are EU holidays
    assert m.eu_deadline("2026-05-04", days=10)["date"] == "2026-05-15"
    assert m.eu_deadline("2026-05-15", days=10)["date"] == "2026-05-26"


def test_notes():
    assert m.shifted_note_fi(m.fi_deadline("2026-12-10", days=14)) == " – siirtyy, 24.12.2026 on jouluaatto (määräaikalaki 5 §)"
    assert m.shifted_note_fi(m.fi_deadline("2026-10-05", days=14)) == ""
    assert "1182/71" in m.shifted_note_eu(m.eu_deadline("2026-10-07", days=10))
