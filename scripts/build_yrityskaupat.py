"""Merge KKV and Commission merger cases into docs/data/yrityskaupat.json – one row per case with
the statutory clock as timeline events:

  KKV:  ilmoitus saapunut → kuuleminen (lausunnot) → 1. vaiheen määräaika (23 työpäivää)
        → [siirretty jatkokäsittelyyn → jatkokäsittelyn määräaika (69 työpäivää)] → päätös
  EU:   notification → provisional deadline (25 working days; phase 2: 90+) → decision(s)

Deadlines are the authorities' own (KKV prints them on the case page, DG COMP publishes the
provisional deadline), never recomputed here – clock stops and extensions are theirs to know.
"""
from __future__ import annotations

import datetime as dt
import re

from common import CACHE_DIR, CONFIG_DIR, OUT_DIR, TODAY, load_json, load_yaml, log, save_json

OUT = OUT_DIR / "yrityskaupat.json"
OPEN_STATES = {"vireillä", "jatkokäsittelyssä"}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def build_yrityskaupat(settings) -> dict | None:
    cfg = load_yaml(CONFIG_DIR / "yrityskaupat.yaml") or {}
    dec_labels = cfg.get("eu_paatostyypit") or {}
    eu_state = cfg.get("eu_tila") or {}
    kkv_state = cfg.get("kkv_tila") or {}
    nace = cfg.get("nace") or {}
    ycfg = settings.get("yrityskaupat", {})
    keep_days = int(ycfg.get("keep_decided_days", 90))
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    kkv = load_json(CACHE_DIR / "kkv.json", {}).get("cases") or {}
    eu = load_json(CACHE_DIR / "eu_mergers.json", {}).get("cases") or {}
    prev = load_json(OUT, {"items": []})
    if not kkv and not eu:
        log("yrityskaupat: ei välimuistia, edellinen tiedosto säilytetään")
        return None
    rows: list[dict] = []

    # ---------- KKV ----------
    for key, c in kkv.items():
        diaari = c.get("diaari") or key
        m = re.search(r"KKV/(\d+)/[\d.]+/(\d{4})", diaari)
        cid = f"yk-fi-{m.group(1)}-{m.group(2)}" if m else f"yk-fi-{slug(diaari)[:40]}"
        title = (c.get("parties") or c.get("listTitle") or diaari).strip()
        decided = c.get("decided") if not c.get("pending") else None
        decision = c.get("decision")
        if c.get("pending"):
            status = "jatkokäsittelyssä" if c.get("phase2Start") else "vireillä"
        elif decision:
            status = kkv_state.get(decision, "päätetty")
        else:
            status = "poistunut listalta"
        if not c.get("pending") and (decided or c.get("missingSince") or "9999") < cutoff:
            continue
        ev = []
        if c.get("notified"):
            ev.append({"date": c["notified"], "label": "Ilmoitus saapunut KKV:lle", "kind": "he"})
            if c.get("hearingEnd") and c["hearingEnd"] >= c["notified"]:
                ev.append({"date": c["notified"], "end": c["hearingEnd"], "label": "Kuuleminen – lausunnot KKV:lle", "kind": "lausunto"})
        if c.get("phase1End") and not (decided and decided <= c["phase1End"] and not c.get("phase2Start")):
            ev.append({"date": c["phase1End"], "label": "1. vaiheen määräaika (23 työpäivää)", "kind": "maaraaika"})
        if c.get("phase2Start"):
            ev.append({"date": c["phase2Start"], "label": "Siirretty jatkokäsittelyyn", "kind": "muu"})
        if c.get("phase2End") and not decided:
            ev.append({"date": c["phase2End"], "label": "Jatkokäsittelyn määräaika (69 työpäivää)", "kind": "maaraaika"})
        if decided:
            ev.append({"date": decided, "label": decision or "Päätös", "kind": "hyvaksytty" if status.startswith("hyväksytty") else "muu"})
        ev.sort(key=lambda e: (e["date"], e.get("end") or ""))
        rows.append({
            "id": cid, "scope": "yrityskauppa", "laji": "yrityskauppa", "authority": "KKV",
            "kind": "Yrityskauppa (KKV)", "title": title[:200], "fullTitle": title, "ref": diaari,
            "status": status, "phase": 2 if c.get("phase2Start") else 1, "done": status not in OPEN_STATES,
            "notified": c.get("notified"), "hearingEnd": c.get("hearingEnd"), "phase1End": c.get("phase1End"),
            "phase2Start": c.get("phase2Start"), "phase2End": c.get("phase2End"), "decided": decided, "decision": decision,
            "topics": ["Kansallinen (KKV)"], "summary": c.get("summary") or "",
            "ministry": "Kilpailu- ja kuluttajavirasto · " + ("kilpailulain 26 § – jatkokäsittely" if c.get("phase2Start") else "kilpailulain 26 § – 1. vaihe"),
            "source": c.get("url"), "links": {k: v for k, v in {"kkv": c.get("url"), "kkvpaatos": c.get("decisionUrl") if c.get("decisionUrl") != c.get("url") else None}.items() if v},
            "events": ev, "updated": c.get("seen"),
        })

    # ---------- European Commission ----------
    for num, c in eu.items():
        decs = sorted(c.get("decisions") or [], key=lambda d: d.get("date") or "")
        last = decs[-1] if decs else None
        last_state = eu_state.get(last["type"]) if last else None
        phase2 = c.get("phase") == "FormalInvestigationPhase2Merger" or any(d["type"] == "DecisionType20320" for d in decs)
        concluded = bool(c.get("lastDecision")) and last_state not in (None, "jatkokäsittelyssä") and last["type"] not in ("DecisionType20545", "DecisionType20665")
        if concluded:
            status = last_state or "päätetty"
            decided = last["date"]
        else:
            status = "jatkokäsittelyssä" if phase2 else "vireillä"
            decided = None
        if concluded and (decided or "") < cutoff:
            continue
        sect = (c.get("sector") or "")
        m = re.search(r"Sector_([A-V])_", sect)
        letter = m.group(1) if m else None
        sector_label = nace.get(letter) if letter else None
        ev = []
        if c.get("notified"):
            ev.append({"date": c["notified"], "label": "Ilmoitus komissiolle", "kind": "he"})
        if c.get("renotified"):
            ev.append({"date": c["renotified"], "label": "Ilmoitettu uudelleen", "kind": "muu"})
        for d in decs:
            if not d.get("date"):
                continue
            lab = dec_labels.get(d["type"], "Päätös")
            st = eu_state.get(d["type"])
            fi = {"jatkokäsittelyssä": "Vaihe 2 aloitettu – " + lab, "hyväksytty": "Hyväksytty – " + lab, "hyväksytty ehdoin": "Hyväksytty sitoumuksin – " + lab,
                  "kielletty": "Kielletty – " + lab, "peruutettu": "Ilmoitus peruutettu"}.get(st)
            if not fi:
                fi = {"DecisionType20545": "Väitetiedoksianto (Art. 18)", "DecisionType20665": "Määräaikaa pidennetty (Art. 10(3))"}.get(d["type"], lab)
            ev.append({"date": d["date"], "label": fi, "kind": "hyvaksytty" if st in ("hyväksytty", "hyväksytty ehdoin") else ("muu" if st not in ("kielletty",) else "vahvistettu")})
        if c.get("deadline") and not concluded:
            ev.append({"date": c["deadline"], "label": "Määräaika" + (" (vaihe 2)" if phase2 else " (vaihe 1, 25 työpäivää)"), "kind": "maaraaika"})
        ev.sort(key=lambda e: (e["date"], e.get("end") or ""))
        simp = {"MEsimplified": "yksinkertaistettu menettely", "MEsupersimplified": "erittäin yksinkertaistettu menettely", "MEnormal": "normaali menettely"}.get(c.get("simplified") or "", "")
        rows.append({
            "id": f"yk-eu-{num.replace('.', '-')}", "scope": "yrityskauppa", "laji": "yrityskauppa", "authority": "EU",
            "kind": "Yrityskauppa (komissio)", "title": c.get("title") or num, "ref": num,
            "status": status, "phase": 2 if phase2 else 1, "done": concluded,
            "notified": c.get("notified"), "phase1End": c.get("deadline") if not phase2 else None, "phase2End": c.get("deadline") if phase2 else None,
            "decided": decided, "decision": dec_labels.get(last["type"]) if last else None,
            "topics": [sector_label] if sector_label else ["Muut"], "sector": sect or None, "simplified": simp,
            "summary": "", "ministry": "Euroopan komissio, DG COMP · sulautuma-asetus 139/2004" + (f" · {simp}" if simp else "") + (f" · NACE {sect.split('_')[-1]}" if sect else ""),
            "source": f"https://competition-cases.ec.europa.eu/cases/{num}",
            "links": {"comp": f"https://competition-cases.ec.europa.eu/cases/{num}"},
            "events": ev, "updated": None,
        })

    rows.sort(key=lambda r: (0 if r["status"] in OPEN_STATES else 1, r.get("phase1End") or r.get("phase2End") or "9999", r["id"]))
    counts = {"fi": sum(1 for r in rows if r["authority"] == "KKV"), "eu": sum(1 for r in rows if r["authority"] == "EU"),
              "fi_open": sum(1 for r in rows if r["authority"] == "KKV" and r["status"] in OPEN_STATES),
              "eu_open": sum(1 for r in rows if r["authority"] == "EU" and r["status"] in OPEN_STATES),
              "phase2": sum(1 for r in rows if r["status"] == "jatkokäsittelyssä")}
    payload = {"items": rows, "counts": counts, "topics": ["Kansallinen (KKV)"] + list(nace.values()) + ["Muut"]}
    if len(rows) < 5 and len(prev.get("items", [])) >= 5:
        log(f"ERROR yrityskaupat: vain {len(rows)} tapausta; edellinen tiedosto säilytetään")
        return None
    save_json(OUT, payload, compact=True)
    log(f"yrityskaupat: {counts} -> {OUT}")
    return payload


if __name__ == "__main__":
    build_yrityskaupat(load_yaml(CONFIG_DIR / "settings.yaml"))
