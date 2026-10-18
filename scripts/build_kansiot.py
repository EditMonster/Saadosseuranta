"""Shared team folders: config/kansiot/*.yaml -> docs/data/kansiot.json + docs/data/kansiot/<id>.ics.

A team folder is a list of fixed item ids plus rules (topics, sectors, buyers, keywords, merger
parties …) that are resolved against the freshly built data on every run, so the folder works as a
team's monitoring profile. Every folder gets its own subscribable calendar feed of upcoming deadlines.
The page shows these folders next to the user's own browser-local folders and edits them in place with the
team key: it opens an issue that kansiopyynto.yml applies (the YAML can also be edited directly). Each
folder also gets an Atom feed of upcoming deadlines for Teams notifications via Power Automate.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path

from common import CONFIG_DIR, OUT_DIR, TODAY, load_yaml, log, save_json

KANSIOT_DIR = CONFIG_DIR / "kansiot"
OUT_JSON = OUT_DIR / "kansiot.json"
OUT_ICS = OUT_DIR / "kansiot"
REPO = os.environ.get("GITHUB_REPOSITORY", "EditMonster/Saadosseuranta")
SITE = os.environ.get("SITE_URL", "https://editmonster.github.io/Saadosseuranta/")
OPEN_TENDER = {"avoin", "tulossa", "valitusaika", "vireillä"}
OPEN_MERGER = {"vireillä", "jatkokäsittelyssä", "kieltoesitys markkinaoikeudessa"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


def _lower_list(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        v = [v]
    return [str(x).strip().lower() for x in v if str(x).strip()]


def _text(it: dict) -> str:
    return " ".join(str(it.get(k) or "") for k in ("title", "fullTitle", "summary", "buyer", "appellant", "cpvLabel", "ref")).lower()


def matches(it: dict, rules: dict) -> bool:
    """Does one row satisfy the folder's rules? Rules of different kinds are ANDed only within the same
    row type; a rule that does not apply to the row's type is ignored, and a row needs at least one
    applicable positive rule to be pulled in."""
    scope = it.get("scope")
    pos = 0  # applicable positive rules
    hit = 0
    if scope in ("fi", "eu"):
        aih = _lower_list(rules.get("aihealueet"))
        if aih:
            pos += 1
            hit += any(t.lower() in aih for t in it.get("topics") or [])
        lajit = _lower_list(rules.get("lajit"))
        if lajit and (it.get("laji") or "laki").lower() not in lajit:
            return False
        if rules.get("vain_avoimet") and it.get("done"):
            return False
    elif scope == "hankinta":
        toim = _lower_list(rules.get("toimialat"))
        if toim:
            pos += 1
            hit += any(t.lower() in toim for t in it.get("topics") or [])
        hy = _lower_list(rules.get("hankintayksikot"))
        if hy:
            pos += 1
            b = (it.get("buyer") or "").lower()
            hit += any(b.startswith(x) or x in b for x in hy)
        stages = _lower_list(rules.get("kilpailutusvaiheet"))
        if stages and (it.get("stage") or "avoin") not in stages:
            return False
        if rules.get("vain_avoimet") and it.get("status") not in OPEN_TENDER:
            return False
    elif scope == "yrityskauppa":
        yk = rules.get("yrityskaupat") or {}
        if not yk and not rules.get("hakusanat"):
            return False
        if yk.get("vain_suomalaiset"):
            pos += 1
            hit += bool(it.get("fiParty"))
        osap = _lower_list(yk.get("osapuolet"))
        if osap:
            pos += 1
            names = " ".join([it.get("title") or ""] + [p.get("name") or "" for p in it.get("parties") or []]).lower()
            hit += any(x in names for x in osap)
        toim = _lower_list(yk.get("toimialat"))
        if toim:
            pos += 1
            hit += any(t.lower() in toim for t in it.get("topics") or [])
        if rules.get("vain_avoimet") and it.get("status") not in OPEN_MERGER:
            return False
    else:
        return False
    kws = _lower_list(rules.get("hakusanat"))
    if kws:
        pos += 1
        txt = _text(it)
        hit += any(k in txt for k in kws)
    return pos > 0 and hit > 0


def atom_feed(fid: str, name: str, rows: list[dict], site: str) -> str:
    """Atom feed of the folder's upcoming deadlines (next 60 days): one entry per item+deadline, so a
    Power Automate / Teams "when a feed item is published" flow posts each new deadline once."""
    import html as _h
    today = TODAY.isoformat()
    hi = (TODAY + dt.timedelta(days=60)).isoformat()
    entries = []
    for it in rows:
        for e in it.get("events") or []:
            if e.get("kind") not in ("maaraaika", "lausunto", "voimaan", "soveltaminen"):
                continue
            day = e.get("end") if e.get("kind") == "lausunto" else e.get("date")
            if not day or day < today or day > hi:
                continue
            tag = {"fi": "FI", "eu": "EU", "hankinta": "Hankinta", "yrityskauppa": it.get("authority") or "Yrityskauppa"}.get(it.get("scope"), "")
            link = f"{site}#{it['id']}"
            title = f"{day[8:10].lstrip('0')}.{day[5:7].lstrip('0')}.{day[:4]} · {e.get('label') or e.get('kind')} – {it.get('title')}"
            body = f"[{tag}] {it.get('title')}\n{e.get('label') or ''}: {day}" + (f"\n{it.get('summary')[:300]}" if it.get("summary") else "") + f"\n{link}"
            entries.append((day, f"<entry><title>{_h.escape(title)}</title><link href=\"{_h.escape(link)}\"/><id>urn:saadosseuranta:{fid}:{it['id']}:{e.get('kind')}:{day}</id>"
                            f"<updated>{day}T06:00:00Z</updated><summary>{_h.escape(body)}</summary></entry>"))
    entries.sort(key=lambda x: x[0])
    upd = (entries[0][0] if entries else today) + "T06:00:00Z"
    return ("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<feed xmlns=\"http://www.w3.org/2005/Atom\">"
            f"<title>Säädösseuranta – {_h.escape(name)} – tulevat määräajat</title><link href=\"{site}data/kansiot/{fid}.xml\" rel=\"self\"/>"
            f"<link href=\"{site}\"/><id>urn:saadosseuranta:{fid}</id><updated>{upd}</updated>" + "".join(x[1] for x in entries) + "</feed>\n")


def next_deadline(it: dict) -> dict | None:
    today = TODAY.isoformat()
    best = None
    for e in it.get("events") or []:
        if e.get("kind") not in ("maaraaika", "lausunto", "voimaan", "soveltaminen"):
            continue
        day = e.get("end") if e.get("kind") == "lausunto" else e.get("date")
        if day and day >= today and (best is None or day < best["date"]):
            best = {"date": day, "label": e.get("label") or e.get("kind"), "id": it["id"], "title": it.get("title")}
    return best


def build_kansiot(items: list[dict], tenders: list[dict], mergers: list[dict], ics_fn) -> dict:
    by_id = {it["id"]: it for it in items + tenders + mergers}
    rows_all = items + tenders + mergers
    folders = []
    OUT_ICS.mkdir(parents=True, exist_ok=True)
    wanted_files = set()
    for path in sorted(KANSIOT_DIR.glob("*.yaml")):
        fid = path.stem.lower()
        if not ID_RE.match(fid):
            log(f"warn: kansio {path.name}: tunnuksen on oltava pienet kirjaimet, numerot ja viivat – ohitettu")
            continue
        try:
            cfg = load_yaml(path) or {}
        except Exception as e:  # noqa: BLE001
            log(f"warn: kansio {path.name}: {e}")
            continue
        name = str(cfg.get("nimi") or fid).strip()[:80]
        explicit = [str(x).strip() for x in (cfg.get("kohteet") or []) if str(x).strip()]
        missing = [x for x in explicit if x not in by_id]
        rules = cfg.get("saannot") or {}
        cap = int(rules.get("enintaan") or 300)
        auto = []
        if rules:
            auto = [it["id"] for it in rows_all if it["id"] not in explicit and matches(it, rules)]
            auto.sort(key=lambda i: (by_id[i].get("published") or by_id[i].get("notified") or by_id[i].get("updated") or ""), reverse=True)
            auto = auto[:cap]
        ids = [x for x in explicit if x in by_id] + auto
        rows = [by_id[i] for i in ids]
        nxt = sorted((d for d in (next_deadline(r) for r in rows) if d), key=lambda d: d["date"])
        ics_name = f"Säädösseuranta – {name}"
        (OUT_ICS / f"{fid}.ics").write_text(ics_fn(rows, ics_name, f"-{fid}"), encoding="utf-8")
        (OUT_ICS / f"{fid}.xml").write_text(atom_feed(fid, name, rows, SITE), encoding="utf-8")
        wanted_files.update({f"{fid}.ics", f"{fid}.xml"})
        folders.append({
            "id": fid, "name": name, "desc": str(cfg.get("kuvaus") or "").strip()[:300], "owner": str(cfg.get("omistaja") or "").strip()[:80],
            "example": bool(cfg.get("esimerkki")), "items": ids, "explicit": [x for x in explicit if x in by_id], "missing": missing,
            "ruleCount": len(auto), "rules": rules, "next": nxt[:5],
            "counts": {"fi": sum(1 for r in rows if r.get("scope") == "fi"), "eu": sum(1 for r in rows if r.get("scope") == "eu"),
                       "hankinta": sum(1 for r in rows if r.get("scope") == "hankinta"), "yrityskauppa": sum(1 for r in rows if r.get("scope") == "yrityskauppa")},
            "ics": f"data/kansiot/{fid}.ics", "atom": f"data/kansiot/{fid}.xml", "config": f"config/kansiot/{fid}.yaml",
            "edit": f"https://github.com/{REPO}/edit/main/config/kansiot/{fid}.yaml",
        })
    for old in list(OUT_ICS.glob("*.ics")) + list(OUT_ICS.glob("*.xml")):
        if old.name not in wanted_files:
            old.unlink()
    payload = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "repo": REPO, "site": SITE, "folders": folders,
               "newUrl": f"https://github.com/{REPO}/new/main", "issueUrl": f"https://github.com/{REPO}/issues/new", "apiUrl": f"https://api.github.com/repos/{REPO}/issues"}
    save_json(OUT_JSON, payload, compact=True)
    log(f"kansiot: {len(folders)} tiimikansiota ({', '.join(f'{f['id']}={len(f['items'])}' for f in folders)}) -> {OUT_JSON}")
    return payload


if __name__ == "__main__":
    import json
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from build import build_ics

    rd = lambda n: json.loads((OUT_DIR / n).read_text(encoding="utf-8"))  # noqa: E731
    build_kansiot(rd("items.json")["items"], rd("hankinnat.json")["items"], rd("yrityskaupat.json")["items"], build_ics)
