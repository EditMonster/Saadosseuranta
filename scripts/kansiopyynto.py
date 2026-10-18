"""Kansiopyyntö: toteuttaa GitHub-issuena tulleen tiimikansion muutosehdotuksen.

Sivun "Ehdota"-painike avaa issuen, jonka otsikko alkaa "[kansio]" ja runko on muotoa

    kansio: hankintatiimi          # kansion tunnus (tiedostonimi config/kansiot/<tunnus>.yaml), tai "uusi"
    toiminto: lisaa | poista | uusi | muokkaa | poista_kansio
    nimi: Hankintatiimi            # uusi / muokkaa
    kuvaus: ...                    # uusi / muokkaa
    saannot: {"aihealueet": ["Verotus"], "vain_avoimet": true}   # uusi / muokkaa – JSON yhdellä rivillä, vain tunnetut avaimet
    ehdottaja: Anna                # vapaamuotoinen nimi commit-viestiin (sivun asetuksista)
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


RULE_KEYS = {"aihealueet": list, "lajit": list, "toimialat": list, "hankintayksikot": list, "kilpailutusvaiheet": list, "hakusanat": list,
             "vain_avoimet": bool, "enintaan": int, "yrityskaupat": dict}
MERGER_KEYS = {"vain_suomalaiset": bool, "osapuolet": list, "toimialat": list}


def clean_rules(raw) -> dict:
    """Keep only known rule keys with sane sizes – the request comes from a browser, not from a trusted editor."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, typ in RULE_KEYS.items():
        v = raw.get(k)
        if v is None or v == "" or v == [] or v == {}:
            continue
        if typ is list:
            vals = [str(x).strip()[:60] for x in (v if isinstance(v, list) else [v]) if str(x).strip()][:30]
            if vals:
                out[k] = vals
        elif typ is bool:
            out[k] = bool(v)
        elif typ is int:
            try:
                out[k] = max(1, min(int(v), 1000))
            except (TypeError, ValueError):
                pass
        elif typ is dict and isinstance(v, dict):
            sub = {}
            for kk, tt in MERGER_KEYS.items():
                vv = v.get(kk)
                if vv in (None, "", [], {}):
                    continue
                sub[kk] = bool(vv) if tt is bool else [str(x).strip()[:60] for x in (vv if isinstance(vv, list) else [vv]) if str(x).strip()][:30]
            if sub:
                out[k] = sub
    return out


def parse_body(body: str) -> dict:
    req = {"kohteet": []}
    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("("):
            continue
        m = re.match(r"^saannot\s*:\s*(\{.*\})\s*$", line, re.I)
        if m:
            try:
                req["saannot"] = clean_rules(json.loads(m.group(1)))
            except ValueError:
                req["saannot_virhe"] = True
            continue
        m = re.match(r"^(kansio|nimi|toiminto|kuvaus|ehdottaja)\s*:\s*(.+)$", line, re.I)
        if m:
            req[m.group(1).lower()] = m.group(2).strip().strip('"')[:300]
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

    if action not in ("lisaa", "poista", "uusi", "muokkaa", "poista_kansio"):
        comment(f"En tunnistanut toimintoa `{action}` (sallitut: lisaa, poista, uusi, muokkaa, poista_kansio). Pyyntöä ei toteutettu.")
        return 1
    who = (req.get("ehdottaja") or "").strip()[:60] or (issue.get("user", {}).get("login") or "")
    if req.get("saannot_virhe"):
        comment("`saannot:`-rivi ei ollut kelvollista JSON:ia. Pyyntöä ei toteutettu.")
        return 1
    if action == "uusi" or fid in ("", "uusi"):
        name = (req.get("nimi") or "").strip()
        if not name:
            comment("Uudelle kansiolle tarvitaan `nimi:`. Pyyntöä ei toteutettu.")
            return 1
        fid = slug(name)
        path = KANSIOT / f"{fid}.yaml"
        if path.exists():
            comment(f"Kansio `{fid}` on jo olemassa – käytä `kansio: {fid}`.")
            return 1
        cfg = {"nimi": name, "kuvaus": req.get("kuvaus") or "", "omistaja": who, "kohteet": [], "saannot": req.get("saannot") or {}}
        action = "lisaa"
        if not valid:
            # a folder may start empty or rules-only
            path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
            rebuild()
            msg = f"Tiimikansio **{name}** (`{fid}`) luotu" + (" säännöillä" if cfg["saannot"] else " (tyhjä)") + f".\n\nTiedosto: `config/kansiot/{fid}.yaml`. Sivu ja kalenterisyöte päivittyvät julkaisun myötä muutamassa minuutissa."
            if unknown:
                msg += f"\n\nTuntemattomat tunnisteet ohitettiin: {', '.join(f'`{i}`' for i in unknown[:10])}"
            finish(fid, [], "uusi", msg)
            return 0
    else:
        if not ID_RE.match(fid):
            comment(f"Kansion tunnus `{fid}` ei kelpaa. Pyyntöä ei toteutettu.")
            return 1
        path = KANSIOT / f"{fid}.yaml"
        if not path.exists():
            comment(f"Kansiota `{fid}` ei ole (config/kansiot/{fid}.yaml). Pyyntöä ei toteutettu.")
            return 1
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if action == "poista_kansio":
        path.unlink()
        rebuild()
        finish(fid, [], action, f"Tiimikansio **{cfg.get('nimi') or fid}** (`{fid}`) poistettu. Kalenterisyöte lakkaa päivittymästä.")
        return 0
    if action == "muokkaa":
        changed_fields = []
        if req.get("nimi"):
            cfg["nimi"] = req["nimi"].strip()[:80]; changed_fields.append("nimi")
        if "kuvaus" in req:
            cfg["kuvaus"] = req.get("kuvaus") or ""; changed_fields.append("kuvaus")
        if "saannot" in req:
            cfg["saannot"] = req["saannot"]; changed_fields.append("säännöt")
        if not changed_fields:
            comment("Muokkauspyynnössä ei ollut muutettavia kenttiä (nimi, kuvaus, saannot). Pyyntöä ei toteutettu.")
            return 1
        cfg.pop("esimerkki", None)
        path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
        rebuild()
        finish(fid, changed_fields, action, f"Tiimikansio **{cfg.get('nimi') or fid}** (`{fid}`) päivitetty: {', '.join(changed_fields)}." +
               (f"\n\nSäännöt nyt: `{json.dumps(cfg.get('saannot') or {}, ensure_ascii=False)}`" if "säännöt" in changed_fields else "") +
               f"\n\nSivu ja kalenterisyöte päivittyvät julkaisun myötä muutamassa minuutissa.")
        return 0
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
    rebuild()
    verb = "Lisätty kansioon" if action == "lisaa" else "Poistettu kansiosta"
    msg = (f"{verb} **{cfg.get('nimi') or fid}** (`{fid}`): " + (", ".join(f"`{i}`" for i in changed) if changed else "ei muutoksia (kohteet olivat jo tässä tilassa)") +
           (f"\n\nTuntemattomat tunnisteet ohitettiin: {', '.join(f'`{i}`' for i in unknown[:10])}" if unknown else "") +
           f"\n\nTiedosto: `config/kansiot/{fid}.yaml`. Sivu ja kalenterisyöte päivittyvät julkaisun myötä muutamassa minuutissa.")
    finish(fid, changed, action, msg)
    return 0


def rebuild() -> None:
    """Rebuild only the folder outputs from the published data (fast, no source fetches)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from build import build_ics  # noqa: E402
    from build_kansiot import build_kansiot  # noqa: E402
    rd = lambda n: json.loads((DATA / n).read_text(encoding="utf-8"))["items"]  # noqa: E731
    build_kansiot(rd("items.json"), rd("hankinnat.json"), rd("yrityskaupat.json"), build_ics)


def finish(fid: str, changed: list, action: str, msg: str) -> None:
    (ROOT / ".kansiopyynto.json").write_text(json.dumps({"fid": fid, "changed": changed, "action": action, "message": msg}, ensure_ascii=False), encoding="utf-8")
    print(msg)


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1])))
