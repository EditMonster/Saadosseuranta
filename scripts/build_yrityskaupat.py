"""Merge KKV and Commission merger cases into docs/data/yrityskaupat.json – one row per case with
the statutory clock as timeline events:

  KKV:  ilmoitus saapunut → kuuleminen (lausunnot) → 1. vaiheen määräaika (23 työpäivää)
        → [siirretty jatkokäsittelyyn → jatkokäsittelyn määräaika (69 työpäivää)] → päätös
  EU:   notification → OJ notice (third-party observations, 10 days) → provisional deadline
        (25 working days; phase 2: 90+) → clock stops / extensions → decision(s)

EU cases carry the parties with their countries from the Official Journal notice, so cases with a
Finnish party (fiParty) can be filtered and surface in Tilannekuva like KKV cases.

Deadlines are the authorities' own (KKV prints them on the case page, DG COMP publishes the
provisional deadline), never recomputed here – clock stops and extensions are theirs to know.
"""
from __future__ import annotations

import datetime as dt
import re

from common import CACHE_DIR, CONFIG_DIR, OUT_DIR, TODAY, load_json, load_yaml, log, save_json

OUT = OUT_DIR / "yrityskaupat.json"
OPEN_STATES = {"vireillä", "jatkokäsittelyssä", "kieltoesitys markkinaoikeudessa"}
STOP = {"oy", "ab", "oyj", "ky", "ltd", "group", "holding", "yhtiöt", "suomi", "finland", "osakeyhtiö"}


def company_tokens(s: str) -> set[str]:
    return {w for w in re.sub(r"[^a-zåäö0-9 ]+", " ", (s or "").lower()).split() if len(w) >= 4 and w not in STOP}


def mao_merger_ruling(title: str, mao_decisions: dict) -> dict | None:
    """The Market Court's ruling on a KKV prohibition proposal, matched by the parties' names."""
    want = company_tokens(title)
    best = None
    for d in mao_decisions.values():
        if not d.get("merger"):
            continue
        have = company_tokens((d.get("parties") or "") + " " + (d.get("keywords") or "") + " " + (d.get("background") or "")[:300])
        hit = len(want & have)
        if hit and (best is None or hit > best[0]):
            best = (hit, d)
    return best[1] if best else None


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def cut(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    if len(s) <= n:
        return s
    c = s[:n]
    return c[: c.rfind(". ") + 1] if ". " in c[n // 3:] else c.rstrip() + "…"


def timeline_event(e: dict) -> dict | None:
    """The Commission's own deadline events (caseTimelineEvents) in Finnish."""
    desc = e.get("description") or ""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", desc)
    date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else e.get("date")
    if not date:
        return None
    typ = e.get("type") or ""
    wd = re.search(r"(\d+)\s+working days", desc)
    if typ == "MEvent59" or "suspended" in desc:
        label = "Määräaika keskeytetty – tietopyyntö (Art. 11(3))"
    elif typ == "MEvent60" or "suspension" in desc and "ended" in desc:
        label = "Määräajan keskeytys päättyi (Art. 11(3))"
    elif typ in ("MEvent10", "MEvent58") or "extension" in desc:
        label = f"Määräaikaa pidennetty {wd.group(1) + ' tp ' if wd else ''}(Art. 10(3))"
    elif typ == "MEvent3" or "Commitments" in desc:
        label = "Sitoumukset toimitettu komissiolle" + (" (vaihe 1)" if "N/1" in desc else "")
    elif typ == "MEvent30" or "Art. 9" in desc:
        label = "Jäsenvaltion siirtopyyntö (Art. 9)"
    else:
        label = "Määräaika muuttunut" + (f": {desc[:80]}" if desc else "")
    return {"date": date, "label": label, "kind": "muu"}


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
    mao_dec = (load_json(CACHE_DIR / "mao.json", {}) or {}).get("decisions") or {}
    mao_months = int(cfg.get("mao_maaraaika_kk", 3))
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
        interim = c.get("interim") or {}
        interim_dates = c.get("interimDates") or {}
        proposal = interim_dates.get("kieltoesitys")
        ruling = mao_merger_ruling(title, mao_dec) if proposal else None
        if ruling and ruling.get("date") and ruling["date"] >= proposal:
            status = ruling.get("outcome") or "ratkaistu markkinaoikeudessa"
            decided, decision = ruling["date"], f"Markkinaoikeus: {ruling.get('outcome') or 'ratkaisu'} ({ruling.get('number')})"
        elif proposal:
            status = "kieltoesitys markkinaoikeudessa"
        elif c.get("pending"):
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
        if c.get("phase2End") and not decided and not proposal:
            ev.append({"date": c["phase2End"], "label": "Jatkokäsittelyn määräaika (69 työpäivää)", "kind": "maaraaika"})
        if proposal:
            ev.append({"date": proposal, "label": "KKV:n kieltoesitys markkinaoikeudelle", "kind": "vahvistettu"})
            pd_ = dt.date.fromisoformat(proposal)
            y, m0 = divmod(pd_.month - 1 + mao_months, 12)
            mao_dl = dt.date(pd_.year + y, m0 + 1, min(pd_.day, 28)).isoformat()
            if not (ruling and ruling.get("date")):
                ev.append({"date": mao_dl, "label": f"Markkinaoikeuden ratkaisun määräaika ({mao_months} kk esityksestä, kilpailulaki 29 §)", "kind": "maaraaika"})
            if ruling and ruling.get("date"):
                ev.append({"date": ruling["date"], "label": f"Markkinaoikeuden ratkaisu {ruling.get('number') or ''} – {ruling.get('outcome') or 'ratkaistu'}".strip(),
                           "kind": "muu" if "kiel" in (ruling.get("outcome") or "") else "hyvaksytty"})
        elif decided:
            ev.append({"date": decided, "label": decision or "Päätös", "kind": "hyvaksytty" if status.startswith("hyväksytty") else "muu"})
        ev.sort(key=lambda e: (e["date"], e.get("end") or ""))
        rows.append({
            "id": cid, "scope": "yrityskauppa", "laji": "yrityskauppa", "authority": "KKV",
            "kind": "Yrityskauppa (KKV)", "title": title[:200], "fullTitle": title, "ref": diaari,
            "status": status, "phase": 2 if c.get("phase2Start") else 1, "done": status not in OPEN_STATES,
            "notified": c.get("notified"), "hearingEnd": c.get("hearingEnd"), "phase1End": c.get("phase1End"),
            "phase2Start": c.get("phase2Start"), "phase2End": c.get("phase2End"), "decided": decided, "decision": decision,
            "topics": ["Kansallinen (KKV)"], "summary": c.get("summary") or "", "fiParty": True,
            "ministry": "Kilpailu- ja kuluttajavirasto · " + ("kilpailulain 25 § – kieltoesitys markkinaoikeudessa" if proposal else ("kilpailulain 26 § – jatkokäsittely" if c.get("phase2Start") else "kilpailulain 26 § – 1. vaihe")),
            "source": c.get("url"), "links": {k: v for k, v in {"kkv": c.get("url"), "kkvpaatos": c.get("decisionUrl") if c.get("decisionUrl") != c.get("url") else None,
                                                                   "kkvesitys": interim.get("kieltoesitys"), "kkvjatko": interim.get("jatkokäsittely"), "mao": (ruling or {}).get("url")}.items() if v},
            "maoProposal": proposal, "maoRuling": (ruling or {}).get("number"),
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
        notice = c.get("notice") or {}
        parties = [{k: v for k, v in p.items() if k in ("name", "short", "country", "fi")} for p in notice.get("parties") or []]
        fi_party = bool(notice.get("fi"))
        ev = []
        if c.get("notified"):
            ev.append({"date": c["notified"], "label": "Ilmoitus komissiolle", "kind": "he"})
        if c.get("renotified"):
            ev.append({"date": c["renotified"], "label": "Ilmoitettu uudelleen", "kind": "muu"})
        if notice.get("published") and notice.get("observationsEnd"):
            ev.append({"date": notice["published"], "end": notice["observationsEnd"], "kind": "lausunto",
                       "label": f"Ennakkoilmoitus EUVL:ssä – kolmansien huomautukset komissiolle ({notice.get('observationDays', 10)} pv)"})
        for te in c.get("timeline") or []:
            x = timeline_event(te)
            if x:
                ev.append(x)
        seen_ext = {(x["date"], x["label"][:18]) for x in ev}  # the timeline names the extension precisely; drop the bare decision twin
        for d in decs:
            if not d.get("date"):
                continue
            lab = dec_labels.get(d["type"], "Päätös")
            st = eu_state.get(d["type"])
            fi = {"jatkokäsittelyssä": "Vaihe 2 aloitettu – " + lab, "hyväksytty": "Hyväksytty – " + lab, "hyväksytty ehdoin": "Hyväksytty sitoumuksin – " + lab,
                  "kielletty": "Kielletty – " + lab, "peruutettu": "Ilmoitus peruutettu"}.get(st)
            if not fi:
                fi = {"DecisionType20545": "Väitetiedoksianto (Art. 18)", "DecisionType20665": "Määräaikaa pidennetty (Art. 10(3))"}.get(d["type"], lab)
            if (d["date"], fi[:18]) in seen_ext:
                continue
            ev.append({"date": d["date"], "label": fi, "kind": "hyvaksytty" if st in ("hyväksytty", "hyväksytty ehdoin") else ("muu" if st not in ("kielletty",) else "vahvistettu")})
        if c.get("deadline") and not concluded:
            ev.append({"date": c["deadline"], "label": "Määräaika" + (" (vaihe 2)" if phase2 else " (vaihe 1, 25 työpäivää)"), "kind": "maaraaika"})
        ev.sort(key=lambda e: (e["date"], e.get("end") or ""))
        simp = {"MEsimplified": "yksinkertaistettu menettely", "MEsupersimplified": "erittäin yksinkertaistettu menettely", "MEnormal": "normaali menettely"}.get(c.get("simplified") or "", "")
        summary = cut(" ".join(x for x in (notice.get("transaction"), notice.get("jv")) if x), 700)
        links = {"comp": f"https://competition-cases.ec.europa.eu/cases/{num}"}
        if notice.get("url"):
            links["euvl"] = notice["url"]
        rows.append({
            "id": f"yk-eu-{num.replace('.', '-')}", "scope": "yrityskauppa", "laji": "yrityskauppa", "authority": "EU",
            "kind": "Yrityskauppa (komissio)", "title": c.get("title") or num, "ref": num,
            "status": status, "phase": 2 if phase2 else 1, "done": concluded,
            "notified": c.get("notified"), "phase1End": c.get("deadline") if not phase2 else None, "phase2End": c.get("deadline") if phase2 else None,
            "decided": decided, "decision": dec_labels.get(last["type"]) if last else None,
            "topics": [sector_label] if sector_label else ["Muut"], "sector": sect or None, "simplified": simp,
            "parties": parties, "fiParty": fi_party, "activities": [cut(a, 500) for a in notice.get("activities") or []],
            "noticeDate": notice.get("published"), "observationsEnd": notice.get("observationsEnd"), "noticeRef": notice.get("reference"),
            "summary": summary, "ministry": "Euroopan komissio, DG COMP · sulautuma-asetus 139/2004" + (f" · {simp}" if simp else "") + (f" · NACE {sect.split('_')[-1]}" if sect else ""),
            "source": f"https://competition-cases.ec.europa.eu/cases/{num}",
            "links": links,
            "events": ev, "updated": None,
        })

    rows.sort(key=lambda r: (0 if r["status"] in OPEN_STATES else 1, r.get("phase1End") or r.get("phase2End") or "9999", r["id"]))
    counts = {"fi": sum(1 for r in rows if r["authority"] == "KKV"), "eu": sum(1 for r in rows if r["authority"] == "EU"),
              "fi_open": sum(1 for r in rows if r["authority"] == "KKV" and r["status"] in OPEN_STATES),
              "eu_open": sum(1 for r in rows if r["authority"] == "EU" and r["status"] in OPEN_STATES),
              "phase2": sum(1 for r in rows if r["status"] == "jatkokäsittelyssä"),
              "mao": sum(1 for r in rows if r["status"] == "kieltoesitys markkinaoikeudessa"),
              "eu_fi": sum(1 for r in rows if r["authority"] == "EU" and r["fiParty"]),
              "eu_fi_open": sum(1 for r in rows if r["authority"] == "EU" and r["fiParty"] and r["status"] in OPEN_STATES)}
    payload = {"items": rows, "counts": counts, "topics": ["Kansallinen (KKV)"] + list(nace.values()) + ["Muut"]}
    if len(rows) < 5 and len(prev.get("items", [])) >= 5:
        log(f"ERROR yrityskaupat: vain {len(rows)} tapausta; edellinen tiedosto säilytetään")
        return None
    save_json(OUT, payload, compact=True)
    log(f"yrityskaupat: {counts} -> {OUT}")
    return payload


if __name__ == "__main__":
    build_yrityskaupat(load_yaml(CONFIG_DIR / "settings.yaml"))
