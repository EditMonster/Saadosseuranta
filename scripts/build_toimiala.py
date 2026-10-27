"""Sector layer rows for the web page, built from data/cache/toimiala.json (no network I/O).

build_toimiala(topics_cfg, settings) -> {"items": [...], "rulings": [...]}

* items – SPEC §1 rows: regulator consultations (laji "kuuleminen", status lausunnolla/tulossa/päättynyt,
  one "lausunto" event spanning publication–deadline) and guidance (laji "ohje": Fiva määräykset ja ohjeet,
  sanctions, Verohallinto syventävät ohjeet, Traficom määräykset and määräyshankepäätökset, EDPB guidelines;
  status annettu/voimassa/luonnos, events "Annettu" + "Voimaan"). Every row carries `authority`; ids are
  "fi-toim-<rowid>" / "eu-toim-<rowid>". Topics come from classify() on title+summary+keywords and fall back
  to the source's default aihealueet in config/toimiala.yaml (always included for single-field regulators,
  `aihealueet_aina: true`).
* rulings – SPEC §2 rows for Keskusverolautakunta (court "KVL", status parsed from the ruling's status line:
  "ei lainvoimainen" / "lainvoimainen" / "KHO d.m.yyyy (KHO yyyy:nn): outcome") and Tietosuojavaltuutettu
  decisions from Finlex (court "TSV", status "annettu"). `statutes` stays empty (KVL quotes statute names,
  not numbers); the quoted text is kept in `statuteText`.

Rows older than the source's keep_days are dropped; consultations stay until deadline + grace days.
"""
from __future__ import annotations

import datetime as dt

from common import CACHE_DIR, CONFIG_DIR, TODAY, load_json, load_yaml

COURTS = {"vero_kvl": ("KVL", "Keskusverolautakunta"), "tsv_finlex": ("TSV", "Tietosuojavaltuutettu"),
          "eoa_finlex": ("EOA", "Eduskunnan oikeusasiamies"), "okv_finlex": ("OKV", "Valtioneuvoston oikeuskansleri"),
          "tes_finlex": ("TES", "Työehtosopimuksen yleissitovuuden vahvistamislautakunta")}
LINK_NAMES = {"hankeikkuna_kuulemiset": "hankeikkuna", "vero_kvl": "vero", "vero_ohjeet": "vero", "tsv_finlex": "finlex", "eoa_finlex": "finlex", "okv_finlex": "finlex",
              "tes_finlex": "finlex", "maaraykset_finlex": "finlex"}


def classify(text: str, topics_cfg: dict) -> list[str]:
    """Same rule as build.classify (copied: build.py imports this module, so importing build here would be circular)."""
    t = (text or "").lower()
    out = [name for name, kws in topics_cfg.items() if any(k.lower() in t for k in kws)]
    return out or ["Muut"]


def fmt_fi(iso: str | None) -> str:
    if not iso or len(iso) < 10:
        return iso or ""
    y, m, d = iso[:10].split("-")
    return f"{int(d)}.{int(m)}.{y}"


def _cut(days: int) -> str:
    return (TODAY - dt.timedelta(days=days)).isoformat()


def _topics(r: dict, scfg: dict, topics_cfg: dict) -> list[str]:
    text = " ".join([r.get("title") or "", r.get("summary") or "", " ".join(r.get("keywords") or []), " ".join(r.get("taxTypes") or [])])
    topics = classify(text, topics_cfg)
    defaults = list(r.get("aihealueet") or scfg.get("aihealueet") or [])  # a row's own field (the agency's) wins
    if scfg.get("aihealueet_aina") and defaults:  # single-field regulator: its field always applies
        return defaults + [t for t in topics if t not in defaults and t != "Muut"]
    return topics if topics != ["Muut"] else (defaults or ["Muut"])


def _links(r: dict) -> dict:
    links = {LINK_NAMES.get(r.get("source"), "source"): r["url"]}
    for key, name in (("tiedoteUrl", "tiedote"), ("lausuntopalvelu", "lausuntopalvelu"), ("finlexUrl", "finlex"), ("pdfUrl", "pdf")):
        if r.get(key) and r[key] != r["url"]:
            v = r[key]
            if v.startswith("/"):  # site-relative links (Traficom media files) → absolute on the row's own host
                from urllib.parse import urljoin
                v = urljoin(r.get("url") or "", v)
            if v.startswith("https://"):
                links[name] = v
    return links


def consultation_item(r: dict, scfg: dict, topics_cfg: dict, defaults: dict) -> dict:
    scope = r.get("scope") or scfg.get("scope") or "fi"
    today = TODAY.isoformat()
    date, deadline = r.get("date"), r.get("deadline")
    if deadline:
        status = "tulossa" if date and date > today else ("lausunnolla" if deadline >= today else "päättynyt")
    else:
        status = "lausunnolla" if (date or "") >= _cut(int(defaults.get("unknown_deadline_days", 45))) else "päättynyt"
    label = "Lausuntoaika" if scope == "fi" else "Palauteaika"
    ev = {"date": date, "label": label, "kind": "lausunto", "confirmed": bool(deadline), "url": r["url"]}
    if deadline:
        ev["end"] = deadline
    ref = r.get("ref") or f"{r.get('authority')} {fmt_fi(date)}".strip()
    title = r.get("title") or ""
    item = {
        "id": f"{scope}-toim-{r['id']}", "scope": scope, "laji": "kuuleminen", "kind": r.get("kind") or "Kuuleminen", "authority": r.get("authority"),
        "title": title[:200], "fullTitle": title if len(title) > 200 else None, "ref": ref, "topics": _topics(r, scfg, topics_cfg),
        "status": status, "done": False, "summary": (r.get("summary") or "")[:500], "source": r["url"], "links": _links(r),
        "events": [ev] if date else [], "deadline": deadline, "deadlineUnknown": True if not deadline else None,
        "keywords": r.get("keywords") or None, "updated": None,
    }
    return {k: v for k, v in item.items() if v is not None}


def guidance_item(r: dict, scfg: dict, topics_cfg: dict) -> dict:
    scope = r.get("scope") or scfg.get("scope") or "fi"
    date, valid_from = r.get("date"), r.get("validFrom")
    status = r.get("status") or "annettu"
    if status not in ("annettu", "voimassa", "luonnos"):
        status = "annettu"
    kind = r.get("kind") or "Ohje"
    ev = []
    if date:
        label = {"Määräyshankepäätös": "Määräyshankepäätös annettu", "Hallinnollinen seuraamus": "Päätös julkaistu", "luonnos": "Luonnos julkaistu"}
        ev.append({"date": date, "label": label.get(kind) or (label["luonnos"] if status == "luonnos" else "Annettu"), "kind": "julkaistu", "confirmed": True})
    if valid_from and valid_from > (date or ""):  # entry into force after publication (an earlier valid_from is already covered by status "voimassa")
        if kind == "EU-valvontaviranomaisen ohjeet":
            ev.append({"date": valid_from, "label": "Soveltaminen alkaa", "kind": "soveltaminen", "confirmed": True})
        else:
            ev.append({"date": valid_from, "label": "Voimaan", "kind": "voimaan", "confirmed": True})
    if r.get("validTo") and r["validTo"] >= (date or ""):
        ev.append({"date": r["validTo"], "label": "Voimassaolo päättyy", "kind": "muu", "confirmed": True})
    ev.sort(key=lambda e: e["date"])
    ref = r.get("ref") or r.get("diary") or f"{r.get('authority')} {fmt_fi(date)}".strip()
    title = r.get("title") or ""
    item = {
        "id": f"{scope}-toim-{r['id']}", "scope": scope, "laji": "ohje", "kind": kind, "authority": r.get("authority"),
        "title": title[:200], "fullTitle": title if len(title) > 200 else None, "ref": ref, "topics": _topics(r, scfg, topics_cfg),
        "status": status, "done": False, "summary": (r.get("summary") or "")[:500], "source": r["url"], "links": _links(r), "events": ev,
        "diary": r.get("diary"), "replaces": r.get("replaces"), "validFrom": valid_from, "plannedText": r.get("plannedText"),
        "keywords": r.get("keywords") or None, "updated": None,
    }
    return {k: v for k, v in item.items() if v is not None}


def ruling_row(r: dict, scfg: dict, topics_cfg: dict) -> dict:
    court, court_name = COURTS.get(r.get("source"), (r.get("authority", "?")[:4].upper(), r.get("authority")))
    rid = r["id"]
    prefix = court.lower() + "-"
    rid = rid[len(prefix):] if rid.startswith(prefix) else rid
    kws = r.get("keywords") or []
    title = r.get("title") or ""
    if court == "KVL":
        title = " – ".join(kws) if kws else (r.get("ref") or title)
        status = r.get("status") or "ei lainvoimainen"
    else:
        status = r.get("status") or "annettu"
    row = {
        "id": f"r-{court.lower()}-{rid}", "scope": "ratkaisu", "court": court, "courtName": court_name, "kind": r.get("kind") or "Ratkaisu",
        "ref": r.get("ref"), "date": r.get("date"), "title": title[:200], "summary": (r.get("summary") or "")[:600], "keywords": kws,
        "topics": _topics(r, scfg, topics_cfg), "statutes": [], "statuteText": r.get("statutes"), "validity": r.get("validity"),
        "diary": r.get("diary"), "kho": r.get("kho"), "status": status, "url": r["url"], "links": _links(r), "fi": True, "related": [],
        "authority": r.get("authority"),
    }
    return {k: v for k, v in row.items() if v is not None}


def build_toimiala(topics_cfg: dict, settings: dict) -> dict:
    cfg_all = load_yaml(CONFIG_DIR / "toimiala.yaml") or {}
    defaults = dict(cfg_all.get("defaults") or {})
    defaults.update(settings.get("toimiala") or {})
    sources = cfg_all.get("sources") or {}
    cache = load_json(CACHE_DIR / "toimiala.json", {}) or {}
    rows_by_source = cache.get("rows") or {}
    ruling_keep = (settings.get("ratkaisut") or {}).get("keep_days")
    # a lausuntopyyntö-row that borrowed its deadline from a tiedote replaces that tiedote's own consultation row
    matched = {r["matchedId"] for rows in rows_by_source.values() for r in rows if r.get("matchedId")}
    items, rulings = [], []
    for name, rows in rows_by_source.items():
        scfg = sources.get(name) or {}
        if scfg and scfg.get("enabled") is False:
            continue
        keep_days = int(scfg.get("keep_days", defaults.get("keep_days", 120)))
        grace = int(defaults.get("consultation_grace_days", 30))
        cut, cut_dl = _cut(keep_days), _cut(grace)
        for r in rows:
            if not r.get("url") or r["id"] in matched:
                continue
            laji = r.get("laji") or scfg.get("laji")
            if laji == "kuuleminen":
                if (r.get("deadline") and r["deadline"] < cut_dl) or (not r.get("deadline") and (r.get("date") or "9999") < cut):
                    continue
                items.append(consultation_item(r, scfg, topics_cfg, defaults))
            elif laji == "ratkaisu":
                # a source's own keep_days wins (yleissitovat TES stay a year); otherwise the rulings view's window
                if (r.get("date") or "9999") < _cut(int(scfg["keep_days"]) if "keep_days" in scfg else int(ruling_keep or keep_days)):
                    continue
                row = ruling_row(r, scfg, topics_cfg)
                if "keep_days" in scfg and int(scfg["keep_days"]) > int(ruling_keep or defaults.get("keep_days", 120)):
                    row["ownWindow"] = True
                rulings.append(row)
            elif laji == "ohje":
                if (r.get("date") or "9999") < cut:
                    continue
                items.append(guidance_item(r, scfg, topics_cfg))
    # lausuntokierrokset of Hankeikkuna projects other than HE/asetus projects (selvitykset, strategiat, työryhmät)
    hk = load_json(CACHE_DIR / "hankeikkuna.json", {}) or {}
    grace = int(defaults.get("consultation_grace_days", 30))
    for r in hk.get("kuulemiset") or []:
        if (r.get("deadline") or r.get("date") or "") < _cut(grace):
            continue
        items.append(consultation_item(r, {"scope": "fi"}, topics_cfg, defaults))
    items.sort(key=lambda i: ((i.get("events") or [{}])[0].get("date") or "", i["id"]), reverse=True)
    rulings.sort(key=lambda i: (i.get("date") or "", i["id"]), reverse=True)
    return {"items": items, "rulings": rulings}


if __name__ == "__main__":
    settings = load_yaml(CONFIG_DIR / "settings.yaml")
    topics = load_yaml(CONFIG_DIR / "topics.yaml")["topics"]
    out = build_toimiala(topics, settings)
    from collections import Counter
    print(len(out["items"]), "items", Counter((i["laji"], i["authority"]) for i in out["items"]))
    print(len(out["rulings"]), "rulings", Counter(r["court"] for r in out["rulings"]))
    for i in out["items"][:5]:
        print(i["id"], i["status"], i["title"][:60], [(e["label"], e["date"], e.get("end")) for e in i["events"]])
