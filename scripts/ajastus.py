"""Ajastin: päättää tunnin välein, ajetaanko päivitys nyt – ja mitkä lähteet.

GitHubin ajastetut työnkulut eivät ole luotettavia: ajo voi myöhästyä tunteja tai jäädä kokonaan
väliin, kun Actionsissa on ruuhkaa. Siksi update.yml herää joka tunti (eri minuutilla kuin tasatunnit)
ja tämä skripti päättää, mitä tehdään. Päätös tehdään repoon tallennetusta data/cache/health.json:sta,
jossa on jokaisen lähteen viimeisin onnistuminen ja epäonnistuminen – eli se näkee, milloin viimeksi
oikeasti ajettiin, vaikka edellinen herätys olisi pudonnut.

1. **Täysi ajo**, kun viimeisin aikataulun mukainen ajohetki (Suomen aikaa, kesä- ja talviaika
   huomioiden) on ohitettu eikä sen jälkeen ole ajettu. Väliin jäänyt herätys korjaantuu siis
   seuraavalla tunnilla.
2. **Uusintayritys** epäonnistuneille lähteille, kun edellisestä yrityksestä on kulunut vähintään
   `RETRY_HOURS` tuntia ja kello on päiväaikaan. Lähteen huoltokatko (esim. tuomioistuinten varasivu)
   ei siis jätä aineistoa vanhaksi seuraavaan aikataulun mukaiseen ajoon asti.
3. Muuten ei tehdä mitään (herätys kestää ~15 s).

Käyttö:  python scripts/ajastus.py            -> tulostaa GitHub Actions -outputit (run, steps, reason)
         python scripts/ajastus.py --explain  -> selitys ihmiselle
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
HEALTH = ROOT / "data" / "cache" / "health.json"
TZ = ZoneInfo("Europe/Helsinki")
WEEKDAY_SLOTS = ["07:00", "12:00", "16:00"]   # ma–pe (herätys tunnin 11. minuutilla)
WEEKEND_SLOTS = ["09:00"]                     # la–su
RETRY_HOURS = float(os.environ.get("RETRY_HOURS", "1"))
RETRY_WINDOW = (7, 22)                        # uusintayrityksiä vain klo 7–22 Suomen aikaa
NEVER_RETRY = {"history"}                     # johdettu aineisto: kulkee täysien ajojen mukana


def _ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def last_slot(now: dt.datetime) -> dt.datetime:
    """The latest scheduled run time at or before `now` (aware datetime)."""
    local = now.astimezone(TZ)
    for back in range(0, 8):
        day = (local - dt.timedelta(days=back)).date()
        slots = WEEKDAY_SLOTS if day.weekday() < 5 else WEEKEND_SLOTS
        for hm in sorted(slots, reverse=True):
            h, m = map(int, hm.split(":"))
            t = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=TZ)
            if t <= local:
                return t.astimezone(dt.timezone.utc)
    raise RuntimeError("no slot in a week")


def last_run(health: dict) -> dt.datetime | None:
    """When the pipeline last actually ran: the newest success or failure of any source."""
    times = [t for k, v in health.items() if not k.startswith("_") and isinstance(v, dict)
             for t in (_ts(v.get("last_ok")), _ts(v.get("last_fail"))) if t]
    return max(times) if times else None


def last_full_run(health: dict) -> dt.datetime | None:
    """A full run touches every source; a retry only the failing ones. The full run's time is therefore the
    oldest 'latest attempt' over the sources (each source's own newest ok/fail)."""
    per = []
    for k, v in health.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        ts = [t for t in (_ts(v.get("last_ok")), _ts(v.get("last_fail"))) if t]
        if ts:
            per.append(max(ts))
    return min(per) if per else None


def decide(now: dt.datetime, health: dict) -> dict:
    slot = last_slot(now)
    full = last_full_run(health)
    if full is None or full < slot - dt.timedelta(minutes=5):
        late = (now - slot).total_seconds() / 3600
        return {"run": True, "steps": "", "reason": f"aikataulun mukainen ajo {slot.astimezone(TZ):%a %d.%m. %H:%M}"
                + (f" (myöhässä {late:.1f} h)" if late >= 1 else "")}
    failing = sorted(k for k, v in health.items() if not k.startswith("_") and isinstance(v, dict) and v.get("ok") is False
                     and k not in NEVER_RETRY)
    if failing:
        local = now.astimezone(TZ)
        latest = max((_ts(health[k].get("last_fail")) or full) for k in failing)
        since = (now - latest).total_seconds() / 3600
        if RETRY_WINDOW[0] <= local.hour < RETRY_WINDOW[1] and since >= RETRY_HOURS:
            return {"run": True, "steps": " ".join(failing), "reason": f"uusintayritys epäonnistuneille lähteille ({since:.1f} h edellisestä)"}
        return {"run": False, "steps": "", "reason": f"epäonnistuneita lähteitä {failing}; seuraava yritys aikaisintaan "
                f"{RETRY_HOURS:g} h edellisestä, klo {RETRY_WINDOW[0]}–{RETRY_WINDOW[1]}"}
    return {"run": False, "steps": "", "reason": f"ajettu {full.astimezone(TZ):%d.%m. %H:%M}, kaikki lähteet kunnossa"}


def main() -> int:
    health = json.loads(HEALTH.read_text(encoding="utf-8")) if HEALTH.exists() else {}
    now = dt.datetime.now(dt.timezone.utc)
    if os.environ.get("FORCE_RUN") == "true":
        d = {"run": True, "steps": os.environ.get("FORCE_STEPS", "").strip(), "reason": "käsin käynnistetty"}
    else:
        d = decide(now, health)
    print(f"ajastin: {'AJA' if d['run'] else 'ohita'} – {d['reason']}" + (f" – vaiheet: {d['steps']}" if d["steps"] else ""))
    out = os.environ.get("GITHUB_OUTPUT")
    if out and "--explain" not in sys.argv:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"run={'true' if d['run'] else 'false'}\nsteps={d['steps']}\nreason={d['reason']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
