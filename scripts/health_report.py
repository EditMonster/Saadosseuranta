"""Lähdevahti: lukee data/cache/health.json ja pitää yllä yhtä GitHub-issueta.

* Kun jokin lähde on epäonnistunut vähintään `threshold` ajoa peräkkäin, avataan issue
  (tai päivitetään olemassa olevaa, jos epäonnistuvien lähteiden joukko muuttui).
* Kun kaikki lähteet toimivat taas, issue suljetaan kommentilla.
* GitHub lähettää issuen avaamisesta sähköposti-ilmoituksen repon omistajalle – siksi tämä
  on ilmainen hälytyskanava ilman salaisuuksia tai ulkoisia palveluja.

Käyttö (GitHub Actionsissa, GH_TOKEN ympäristössä):  python scripts/health_report.py --issue
Ilman --issue tulostaa vain yhteenvedon eikä koske GitHubiin.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEALTH = ROOT / "data" / "cache" / "health.json"
LABEL = "lahdevahti"
THRESHOLD = int(os.environ.get("HEALTH_THRESHOLD", "3"))
ALARM_HOURS = float(os.environ.get("HEALTH_ALARM_HOURS", "20"))
OUTAGE_ALARM_HOURS = float(os.environ.get("HEALTH_OUTAGE_ALARM_HOURS", "48"))
NAMES = {"hankeikkuna": "Hankeikkuna", "eduskunta": "Eduskunnan avoin data", "finlex": "Finlex", "eu": "EP + Cellar",
         "ue": "U/E-kirjelmät (eduskunta)", "hys": "Have your say", "hankinnat": "Hilma", "kkv": "KKV yrityskaupat", "eu_mergers": "Komissio yrityskaupat",
         "regdel": "Delegoitujen säädösten rekisteri", "mao": "Markkinaoikeus",
         "avoimuus": "Avoimuusrekisteri", "vaski": "Eduskunta – valiokunnat (Vaski)", "caselaw": "Oikeuskäytäntö (tuomioistuimet)", "curia": "EU-tuomioistuin (Cellar)",
         "toimiala": "Toimialakerros (Fiva, ESMA/EBA/EIOPA, EDPB, Vero, Traficom)", "sopimuskaudet": "Hilma – sopimuskaudet", "suunnitelmat": "Kilpailutussuunnitelmat ja hankintakalenterit",
         "ted": "TED", "paatokset": "Hankintapäätökset (Helsinki)", "toimittajat": "Tutkihankintoja", "kkv_valvonta": "KKV – kilpailu- ja hankintavalvonta",
         "eu_signals": "EU-ennakointi (neuvosto, komissio, OEIL, rikkomukset, komitologia, pakotteet)",
         "hediff": "HE-diff (rinnakkaistekstit ja mietinnöt)", "history": "Tilastohistoria (MAO, KKV, sopimuskaudet)",
         "lausunnot": "Annetut lausunnot (tiivistelmät, Hankeikkuna ja eduskunta)",
         "asiat": "Eduskunta.fi – asioiden asiantuntijalausunnot ja valiokuntien lausunnot"}


def alarming(v: dict, now: dt.datetime) -> bool:
    """Alarm by elapsed time, not by attempt count: failing sources are retried every two hours, so a streak
    grows fast. A broken source alarms once it has not updated for ALARM_HOURS (about one working day);
    a source that is in a maintenance break (outage) only after OUTAGE_ALARM_HOURS."""
    if v.get("ok", True) or int(v.get("streak", 0)) < 1:
        return False
    last = v.get("last_ok")
    if not last:
        return int(v.get("streak", 0)) >= THRESHOLD
    age_h = (now - dt.datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() / 3600
    return age_h >= (OUTAGE_ALARM_HOURS if v.get("outage") else ALARM_HOURS) and int(v.get("streak", 0)) >= 2


def gh(*args: str, check: bool = True) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} epäonnistui: {r.stderr.strip()}")
    return r.stdout.strip()


def main(manage_issue: bool) -> int:
    health = json.loads(HEALTH.read_text(encoding="utf-8")) if HEALTH.exists() else {}
    now = dt.datetime.now(dt.timezone.utc)
    failing = {k: v for k, v in health.items() if not k.startswith("_") and alarming(v, now)}
    warming = {k: v for k, v in health.items() if not k.startswith("_") and int(v.get("streak", 0)) > 0 and k not in failing}
    for k, v in sorted(health.items()):
        if k.startswith("_"):
            continue
        print(f"{k:12s} streak={v.get('streak', 0)} last_ok={v.get('last_ok', '-')} {('ERR ' + str(v.get('last_error')))[:120] if v.get('last_error') else ''}")
    if not manage_issue:
        print(f"\nhälytysraja {ALARM_HOURS:g} h / katko {OUTAGE_ALARM_HOURS:g} h: hälyttäviä {sorted(failing)} · varoittavia {sorted(warming)}")
        return 0

    repo = os.environ.get("GITHUB_REPOSITORY") or gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
    # Varmista label (virhe = on jo olemassa)
    subprocess.run(["gh", "label", "create", LABEL, "-R", repo, "--color", "B4700C", "--description", "Automaattinen lähdevahti",
                    "--force"], capture_output=True, text=True)
    open_issues = json.loads(gh("issue", "list", "-R", repo, "--label", LABEL, "--state", "open", "--json", "number,title,body") or "[]")
    issue = open_issues[0] if open_issues else None
    key = ",".join(sorted(failing))
    last_key = str((health.get("_issue") or {}).get("key", ""))

    def lines(d):
        return "\n".join(f"- **{NAMES.get(k, k)}** (`{k}`): {v.get('streak')} yritystä peräkkäin{' (huoltokatko lähteessä)' if v.get('outage') else ''}, viimeksi onnistui {v.get('last_ok') or 'ei koskaan'}"
                         f"\n  `{(v.get('last_error') or '')[:200]}`" for k, v in sorted(d.items()))

    if failing:
        body = (f"Seuraavat lähteet eivät ole päivittyneet {ALARM_HOURS:.0f} tuntiin (huoltokatkossa olevat {OUTAGE_ALARM_HOURS:.0f} tuntiin), vaikka haku on yritetty uudelleen kahden tunnin välein. Sivu näyttää niiden osalta edellisen "
                f"onnistuneen haun aineistoa, ja yläpalkissa on varoitus.\n\n{lines(failing)}\n\n"
                "Tarkista ajon loki (Actions → Päivitä säädösaineisto). Issue sulkeutuu itsestään, kun lähteet toimivat taas.\n\n"
                "_Automaattinen ilmoitus: scripts/health_report.py_")
        title = "Lähde ei päivity: " + ", ".join(NAMES.get(k, k) for k in sorted(failing))
        if not issue:
            gh("issue", "create", "-R", repo, "--title", title, "--body", body, "--label", LABEL)
            print(f"issue avattu: {title}")
        elif key != last_key:
            gh("issue", "edit", str(issue["number"]), "-R", repo, "--title", title, "--body", body)
            gh("issue", "comment", str(issue["number"]), "-R", repo, "--body", f"Tilanne muuttui:\n\n{lines(failing)}")
            print(f"issue #{issue['number']} päivitetty: {title}")
        else:
            print(f"issue #{issue['number']} ennallaan")
    elif issue:
        gh("issue", "close", str(issue["number"]), "-R", repo, "--comment", "Kaikki lähteet päivittyvät taas – suljetaan automaattisesti.")
        print(f"issue #{issue['number']} suljettu")
    else:
        print("kaikki lähteet kunnossa, ei avointa issueta")
    health["_issue"] = {"key": key}
    HEALTH.write_text(json.dumps(health, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main("--issue" in sys.argv))
