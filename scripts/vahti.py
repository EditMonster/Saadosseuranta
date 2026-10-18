"""Päivitysvahti: varmistaa, että automaattinen päivitys oikeasti pyörii – ja käynnistää sen, jos ei.

Lähdevahti (health_report.py) elää päivitysajon sisällä, joten se ei huomaa tilannetta, jossa ajo ei
käynnisty lainkaan (GitHub ohittaa ajastuksen, työnkulku on poistettu käytöstä 60 päivän
hiljaiselon jälkeen, ajo kaatuu ennen lähdevahtia). Tämä skripti ajetaan omasta, päivittäisestä
työnkulusta (vahti.yml) ja se

1. lukee julkaistun sivun meta.json:n ja laskee aineiston iän,
2. tarkistaa, että update.yml on käytössä (ei "disabled_inactivity"/"disabled_manually") ja
   kutsuu joka tapauksessa GitHubin enable-rajapintaa, mikä nollaa 60 päivän hiljaiselolaskurin,
3. jos aineisto on vanhempaa kuin raja (oletus 30 h), käynnistää päivitysajon heti ja avaa
   issuen "Päivitys on pysähtynyt" (GitHub lähettää siitä sähköpostin); kun aineisto on taas
   tuoretta, issue suljetaan kommentilla.

Lisäksi päivitysajo itse kutsuu tätä `run-result`-tilassa: epäonnistunut ajo avaa issuen
"Päivitysajo epäonnistui" (linkki lokiin) ja onnistunut sulkee sen.

Käyttö:  python scripts/vahti.py check [--max-age-hours 30] [--no-dispatch]
         python scripts/vahti.py run-result --status success|failure --run-url URL
GH_TOKEN ympäristössä (GitHub Actionsissa github.token, oikeudet actions: write, issues: write).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request

SITE = os.environ.get("SITE_URL", "https://editmonster.github.io/Saadosseuranta/")
WORKFLOW = "update.yml"
LABEL_STALE = "paivitysvahti"
LABEL_RUN = "ajovirhe"


def gh(*args: str, check: bool = True) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} epäonnistui: {r.stderr.strip()}")
    return r.stdout.strip()


def repo_name() -> str:
    return os.environ.get("GITHUB_REPOSITORY") or gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")


def ensure_label(repo: str, label: str, color: str, desc: str) -> None:
    subprocess.run(["gh", "label", "create", label, "-R", repo, "--color", color, "--description", desc, "--force"], capture_output=True, text=True)


def open_issue(repo: str, label: str) -> dict | None:
    issues = json.loads(gh("issue", "list", "-R", repo, "--label", label, "--state", "open", "--json", "number,title,createdAt") or "[]")
    return issues[0] if issues else None


def close_issue(repo: str, label: str, comment: str) -> None:
    iss = open_issue(repo, label)
    if iss:
        gh("issue", "comment", str(iss["number"]), "-R", repo, "--body", comment)
        gh("issue", "close", str(iss["number"]), "-R", repo)
        print(f"issue #{iss['number']} suljettu")


def live_meta() -> dict:
    url = SITE.rstrip("/") + "/data/meta.json?vahti=" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "saadosseuranta-vahti/1.0", "Cache-Control": "no-cache"}), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def workflow_state(repo: str) -> dict:
    return json.loads(gh("api", f"repos/{repo}/actions/workflows/{WORKFLOW}"))


def last_runs(repo: str, n: int = 3) -> list[dict]:
    data = json.loads(gh("api", f"repos/{repo}/actions/workflows/{WORKFLOW}/runs?per_page={n}"))
    return [{"id": r["id"], "status": r["status"], "conclusion": r["conclusion"], "created": r["created_at"], "event": r["event"], "url": r["html_url"]}
            for r in data.get("workflow_runs") or []]


def cmd_check(max_age_hours: float, dispatch: bool) -> int:
    repo = repo_name()
    now = dt.datetime.now(dt.timezone.utc)
    problems: list[str] = []
    # 1. the published data's age
    try:
        meta = live_meta()
        gen = dt.datetime.fromisoformat(meta["generated"])
        if gen.tzinfo is None:
            gen = gen.replace(tzinfo=dt.timezone.utc)  # build.py writes local runner time, which is UTC in Actions
        age_h = (now - gen).total_seconds() / 3600
        print(f"julkaistu aineisto: {meta['generated']} ({age_h:.1f} h sitten)")
        stale = age_h > max_age_hours
        if stale:
            problems.append(f"Julkaistu aineisto on {age_h:.0f} tuntia vanhaa (raja {max_age_hours:.0f} h); viimeisin rakennus {meta['generated']}.")
        bad = [k for k, h in (meta.get("health") or {}).items() if int(h.get("streak", 0)) >= 3]
        if bad:
            print(f"lähdevahti: epäonnistuvia lähteitä {bad} (oma issue lähdevahdilta)")
    except Exception as e:  # noqa: BLE001
        stale = True
        problems.append(f"Julkaistua meta.json-tiedostoa ei saatu luettua: {e}")
        print(problems[-1])
    # 2. workflow enabled? (and poke the enable endpoint: it resets GitHub's 60-day inactivity timer)
    try:
        wf = workflow_state(repo)
        print(f"update.yml tila: {wf.get('state')}")
        if wf.get("state") != "active":
            problems.append(f"Työnkulku update.yml oli tilassa `{wf.get('state')}` – otettu uudelleen käyttöön.")
        gh("api", "-X", "PUT", f"repos/{repo}/actions/workflows/{wf['id']}/enable")
        print("enable-kutsu tehty (hiljaiselolaskuri nollattu)")
    except Exception as e:  # noqa: BLE001
        problems.append(f"Työnkulun tilaa ei voitu tarkistaa: {e}")
        print(problems[-1])
    # 3. recent runs
    runs = []
    try:
        runs = last_runs(repo)
        for r in runs:
            print(f"ajo {r['id']}: {r['event']} {r['created']} {r['status']}/{r['conclusion']}")
        if runs and runs[0]["status"] == "completed" and runs[0]["conclusion"] not in ("success", None):
            problems.append(f"Viimeisin päivitysajo päättyi tilaan `{runs[0]['conclusion']}`: {runs[0]['url']}")
    except Exception as e:  # noqa: BLE001
        print(f"ajoja ei voitu listata: {e}")
    # 4. act
    ensure_label(repo, LABEL_STALE, "D93F0B", "Päivitysvahti: automaattinen päivitys ei pyöri")
    if stale:
        if dispatch and not any(r["status"] in ("queued", "in_progress") for r in runs):
            try:
                gh("api", "-X", "POST", f"repos/{repo}/actions/workflows/{WORKFLOW}/dispatches", "-f", "ref=main")
                problems.append("Päivitysajo käynnistettiin uudelleen vahdista.")
                print("päivitysajo käynnistetty")
            except Exception as e:  # noqa: BLE001
                problems.append(f"Päivitysajon käynnistys epäonnistui: {e}")
        body = ("Automaattinen päivitys ei ole tuottanut tuoretta aineistoa.\n\n" + "\n".join(f"- {p}" for p in problems) +
                f"\n\nTarkistettu {now.strftime('%Y-%m-%d %H:%M UTC')}. Issue sulkeutuu itsestään, kun julkaistu aineisto on taas tuoretta. "
                f"Jos tämä toistuu: Actions → *Päivitä säädösaineisto* → Run workflow, ja katso ajon loki.")
        iss = open_issue(repo, LABEL_STALE)
        if iss:
            gh("issue", "comment", str(iss["number"]), "-R", repo, "--body", body)
            print(f"issue #{iss['number']} päivitetty")
        else:
            out = gh("issue", "create", "-R", repo, "--title", "Päivitys on pysähtynyt – aineisto ei päivity", "--label", LABEL_STALE, "--body", body)
            print(f"issue avattu: {out}")
        return 1
    close_issue(repo, LABEL_STALE, f"Aineisto päivittyy taas (viimeisin rakennus {meta['generated']}). Suljetaan automaattisesti.")
    if problems:
        print("huomioita:", *problems, sep="\n- ")
    print("OK: päivitys pyörii")
    return 0


def cmd_run_result(status: str, run_url: str) -> int:
    repo = repo_name()
    ensure_label(repo, LABEL_RUN, "B60205", "Päivitysajo epäonnistui")
    if status == "success":
        close_issue(repo, LABEL_RUN, f"Seuraava päivitysajo onnistui: {run_url}. Suljetaan automaattisesti.")
        return 0
    body = (f"Päivitysajo päättyi virheeseen: {run_url}\n\nSivu näyttää edellistä onnistunutta aineistoa. Yksittäinen epäonnistuminen "
            f"(esim. lähde alhaalla, GitHubin verkko-ongelma) korjaantuu yleensä seuraavassa ajossa; issue sulkeutuu silloin itsestään. "
            f"Jos virhe toistuu, katso ajon loki ja lähdevahdin issue.")
    iss = open_issue(repo, LABEL_RUN)
    if iss:
        gh("issue", "comment", str(iss["number"]), "-R", repo, "--body", body)
        print(f"issue #{iss['number']} päivitetty")
    else:
        print("issue avattu:", gh("issue", "create", "-R", repo, "--title", "Päivitysajo epäonnistui", "--label", LABEL_RUN, "--body", body))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--max-age-hours", type=float, default=float(os.environ.get("MAX_AGE_HOURS", "30")))
    c.add_argument("--no-dispatch", action="store_true")
    r = sub.add_parser("run-result")
    r.add_argument("--status", required=True, choices=["success", "failure"])
    r.add_argument("--run-url", default="")
    a = ap.parse_args()
    if a.cmd == "check":
        sys.exit(cmd_check(a.max_age_hours, not a.no_dispatch))
    sys.exit(cmd_run_result(a.status, a.run_url))
