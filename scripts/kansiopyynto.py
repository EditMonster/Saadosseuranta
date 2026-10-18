"""Kansiopyyntö: toteuttaa GitHub-issuena tulleen tiimikansion muutosehdotuksen.

Sivun "Ehdota"-painike avaa issuen, jonka otsikko alkaa "[kansio]" ja runko on muotoa

    kansio: hankintatiimi          # kansion tunnus (tiedostonimi config/kansiot/<tunnus>.yaml), tai "uusi"
    nimi: Hankintatiimi            # vain uudelle kansiolle
    toiminto: lisaa | poista
    kohteet:
    - fi-he-129-2026 — otsikko (viiva ja otsikko ovat vain luettavuuden vuoksi)
    - hk-EF-28755

kansiopyynto.yml ajaa tämän, kun issue avataan (tai kun ylläpitäjä kommentoi /hyvaksy). Skripti
muokkaa YAML-tiedostoa, rakentaa kansiot.json:n ja kalenterisyötteet uudelleen julkaistusta aineistosta,
committaa ja kommentoi issueen; työnkulku sulkee issuen. Tunnisteet tarkistetaan aineistoa vasten,
joten mielivaltaista sisältöä ei pääse konfiguraatioon.

Käyttö: python scripts/kansiopyynto.py <issue-numero>   (GH_TOKEN ja GITHUB_REPOSITORY ympäristössä)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
KANSIOT = ROOT / "config" / "kansiot"
DATA = ROOT / "docs" / "data"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
ITEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{2,80}$")


def gh(*args: str) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def parse_body(body: str) -> dict:
    req = {"kohteet": []}
    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("("):
            continue
        m = re.match(r"^(kansio|nimi|toiminto|kuvaus)\s*:\s*(.+)$", line, re.I)
        if m:
            req[m.group(1).lower()] = m.group(2).strip().strip('"')
            continue
        m = re.match(r"^[-*]\s*([A-Za-z0-9][A-Za-z0-9-]+)", line)
        if m:
            req["kohteet"].append(m.group(1))
    return req


def known_ids() -> set[str]:
    ids = set()
    for name, key in (("items.json", "items"), ("hankinnat.json", "items"), ("yrityskaupat.json", "items")):
        p = DATA / name
        if p.exists():
            ids.update(i["id"] for i in json.loads(p.read_text(encoding="utf-8")).get(key) or [])
    return ids


def slug(s: str) -> str:
    s = s.lower().replace("ä", "a").replace("ö", "o").replace("å", "a")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")[:40] or "kansio"


def main(issue_no: int) -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    issue = json.loads(gh("api", f"repos/{repo}/issues/{issue_no}"))
    title, body = issue.get("title") or "", issue.get("body") or ""
    if not title.lower().startswith("[kansio]"):
        print("ei kansiopyyntö, ohitetaan")
        return 0
    req = parse_body(body)
    action = (req.get("toiminto") or "lisaa").lower()
    fid = (req.get("kansio") or "").lower()
    ids = known_ids()
    wanted = [i for i in req["kohteet"] if ITEM_RE.match(i)]
    valid = [i for i in wanted if i in ids]
    unknown = [i for i in wanted if i not in ids]

    def comment(msg: str) -> None:
        gh("issue", "comment", str(issue_no), "-R", repo, "--body", msg)

    if action not in ("lisaa", "poista"):
        comment(f"En tunnistanut toimintoa `{action}` (sallitut: lisaa, poista). Pyyntöä ei toteutettu.")
        return 1
    if fid in ("", "uusi"):
        name = (req.get("nimi") or "").strip()
        if not name:
            comment("Uudelle kansiolle tarvitaan `nimi:`. Pyyntöä ei toteutettu.")
            return 1
        fid = slug(name)
        path = KANSIOT / f"{fid}.yaml"
        if path.exists():
            comment(f"Kansio `{fid}` on jo olemassa – käytä `kansio: {fid}`.")
            return 1
        cfg = {"nimi": name, "kuvaus": req.get("kuvaus") or "", "omistaja": issue.get("user", {}).get("login") or "", "kohteet": [], "saannot": {}}
    else:
        if not ID_RE.match(fid):
            comment(f"Kansion tunnus `{fid}` ei kelpaa. Pyyntöä ei toteutettu.")
            return 1
        path = KANSIOT / f"{fid}.yaml"
        if not path.exists():
            comment(f"Kansiota `{fid}` ei ole (config/kansiot/{fid}.yaml). Pyyntöä ei toteutettu.")
            return 1
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not valid:
        comment("Yhtään tunnistettua kohdetta ei löytynyt aineistosta" + (f" (tuntemattomat: {', '.join(unknown[:10])})" if unknown else "") + ". Pyyntöä ei toteutettu.")
        return 1
    items = [str(x) for x in (cfg.get("kohteet") or [])]
    if action == "lisaa":
        added = [i for i in valid if i not in items]
        items += added
        changed = added
    else:
        changed = [i for i in valid if i in items]
        items = [i for i in items if i not in valid]
    cfg["kohteet"] = items
    if cfg.get("esimerkki"):
        cfg.pop("esimerkki", None)  # an edited example is no longer an example
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    # rebuild only the folder outputs from the published data (fast, no source fetches)
    sys.path.insert(0, str(ROOT / "scripts"))
    from build import build_ics  # noqa: E402
    from build_kansiot import build_kansiot  # noqa: E402
    rd = lambda n: json.loads((DATA / n).read_text(encoding="utf-8"))["items"]  # noqa: E731
    build_kansiot(rd("items.json"), rd("hankinnat.json"), rd("yrityskaupat.json"), build_ics)
    verb = "Lisätty kansioon" if action == "lisaa" else "Poistettu kansiosta"
    msg = (f"{verb} **{cfg.get('nimi') or fid}** (`{fid}`): " + (", ".join(f"`{i}`" for i in changed) if changed else "ei muutoksia (kohteet olivat jo tässä tilassa)") +
           (f"\n\nTuntemattomat tunnisteet ohitettiin: {', '.join(f'`{i}`' for i in unknown[:10])}" if unknown else "") +
           f"\n\nTiedosto: `config/kansiot/{fid}.yaml`. Sivu ja kalenterisyöte päivittyvät julkaisun myötä muutamassa minuutissa.")
    (ROOT / ".kansiopyynto.json").write_text(json.dumps({"fid": fid, "changed": changed, "action": action, "message": msg}, ensure_ascii=False), encoding="utf-8")
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1])))
