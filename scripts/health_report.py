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

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEALTH = ROOT / "data" / "cache" / "health.json"
LABEL = "lahdevahti"
THRESHOLD = int(os.environ.get("HEALTH_THRESHOLD", "3"))
NAMES = {"hankeikkuna": "Hankeikkuna", "eduskunta": "Eduskunnan avoin data", "finlex": "Finlex", "eu": "EP + Cellar",
         "ue": "U/E-kirjelmät (eduskunta)", "hys": "Have your say", "hankinnat": "Hilma", "kkv": "KKV yrityskaupat", "eu_mergers": "Komissio yrityskaupat",
         "regdel": "Delegoitujen säädösten rekisteri", "mao": "Markkinaoikeus",
         "avoimuus": "Avoimuusrekisteri", "vaski": "Eduskunta – valiokunnat (Vaski)", "caselaw": "Oikeuskäytäntö (tuomioistuimet)", "curia": "EU-tuomioistuin (Cellar)",
         "toimiala": "Toimialakerros (Fiva, ESMA/EBA/EIOPA, EDPB, Vero, Traficom)", "sopimuskaudet": "Hilma – sopimuskaudet", "suunnitelmat": "Kilpailutussuunnitelmat ja hankintakalenterit",
         "ted": "TED", "paatokset": "Hankintapäätökset (Helsinki)", "toimittajat": "Tutkihankintoja", "kkv_valvonta": "KKV – kilpailu- ja hankintavalvonta",
         "eu_signals": "EU-ennakointi (neuvosto, komissio, OEIL, rikkomukset, komitologia, pakotteet)"}


def gh(*args: str, check: bool = True) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} epäonnistui: {r.stderr.strip()}")
    return r.stdout.strip()


def main(manage_issue: bool) -> int:
    health = json.loads(HEALTH.read_text(encoding="utf-8")) if HEALTH.exists() else {}
    failing = {k: v for k, v in health.items() if not k.startswith("_") and int(v.get("streak", 0)) >= THRESHOLD}
    warming = {k: v for k, v in health.items() if not k.startswith("_") and 0 < int(v.get("streak", 0)) < THRESHOLD}
    for k, v in sorted(health.items()):
        if k.startswith("_"):
            continue
        print(f"{k:12s} streak={v.get('streak', 0)} last_ok={v.get('last_ok', '-')} {('ERR ' + str(v.get('last_error')))[:120] if v.get('last_error') else ''}")
    if not manage_issue:
        print(f"\nhälytysraja {THRESHOLD}: hälyttäviä {sorted(failing)} · varoittavia {sorted(warming)}")
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
        return "\n".join(f"- **{NAMES.get(k, k)}** (`{k}`): {v.get('streak')} ajoa peräkkäin, viimeksi onnistui {v.get('last_ok') or 'ei koskaan'}"
                         f"\n  `{(v.get('last_error') or '')[:200]}`" for k, v in sorted(d.items()))

    if failing:
        body = (f"Seuraavat lähteet ovat epäonnistuneet vähintään {THRESHOLD} ajoa peräkkäin. Sivu näyttää niiden osalta edellisen "
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
