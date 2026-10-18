"""Builders for the forward-looking EU signals (data/cache/eu_signals.json, fetched by fetch_eu_signals.py).

Pure functions, no network. build.py calls them:

* ``attach_eu_forecasts(eu_items)`` – adds to existing EU procedure rows (matched on ``pid``) the Parliament
  forecast (``forecast`` {plenary, committeeVote}; events of kind "ennuste", never confirmed) and the Council
  agendas the file is on (``coreper`` [{date, body, url}]; events of kind "neuvosto", confirmed because the
  provisional agenda is a published document). The exact EP plenary agenda beats OEIL's indicative date,
  which beats Cellar's projected EP vote.
* ``signal_items(topics_cfg)`` – rows of laji "signaali": the Commission's planned adoptions (weekly list +
  work programme, merged by title similarity), infringement cases against Finland, and the Government's
  Council-meeting memos to Parliament (EUN documents; scope "eu" so they sit on the EU tab).
* ``implementing_items(topics_cfg)`` – laji "taytantoonpano": draft implementing acts in comitology with the
  committee vote, Commission adoption and, when a Have your say feedback period can be matched, its span.
* ``sanction_items(topics_cfg)`` – laji "pakote": EU restrictive-measures acts from the Official Journal.

Ids are stable across runs: "eu-sig-com-<sha12 of the normalised title>", "eu-sig-infr-<year>-<number>",
"fi-eun-<n>-<yyyy>", "eu-ia-<D-number>", "eu-pak-<CELEX>". Dates are ISO. Topics come from
config/topics.yaml keywords via ``classify`` (copied from build.py to avoid a circular import) with the
per-source fallbacks in config/eu_signaalit.yaml.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from difflib import SequenceMatcher

from common import CACHE_DIR, CONFIG_DIR, TODAY, load_json, load_yaml

CACHE = CACHE_DIR / "eu_signals.json"
HYS_CACHE = CACHE_DIR / "hys.json"
CONFIG = CONFIG_DIR / "eu_signaalit.yaml"
OEIL = "https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference="
COMREG_UI = "https://ec.europa.eu/transparency/comitology-register/screen/documents"


# ----------------------------------------------------------------------------- helpers
def classify(text: str, topics_cfg: dict) -> list[str]:
    t = (text or "").lower()
    out = [name for name, kws in (topics_cfg or {}).items() if any(k.lower() in t for k in kws)]
    return out or ["Muut"]


def _signals(signals: dict | None) -> dict:
    return signals if signals is not None else (load_json(CACHE, {}) or {})


def _cfg(cfg: dict | None) -> dict:
    return cfg if cfg is not None else (load_yaml(CONFIG) or {})


def sha12(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def fi_date(iso: str | None) -> str:
    try:
        d = dt.date.fromisoformat((iso or "")[:10])
    except ValueError:
        return iso or ""
    return f"{d.day}.{d.month}.{d.year}"


def quarter_date(q: str | None, month_offset: int = 1) -> str | None:
    """'2026-Q2' -> first day of the quarter's (1 + offset)th month, e.g. 2026-05-01."""
    m = re.match(r"(\d{4})-Q([1-4])$", q or "")
    if not m:
        return None
    month = (int(m.group(2)) - 1) * 3 + 1 + max(0, min(2, month_offset))
    return dt.date(int(m.group(1)), month, 1).isoformat()


def quarter_end(q: str | None) -> str | None:
    m = re.match(r"(\d{4})-Q([1-4])$", q or "")
    if not m:
        return None
    month = int(m.group(2)) * 3
    nxt = dt.date(int(m.group(1)) + (month == 12), (month % 12) + 1, 1)
    return (nxt - dt.timedelta(days=1)).isoformat()


def quarter_text(q: str | None) -> str | None:
    m = re.match(r"(\d{4})-Q([1-4])$", q or "")
    return f"Q{m.group(2)}/{m.group(1)}" if m else None


def similar(a: str | None, b: str | None) -> float:
    """Title similarity in [0, 1]: sequence ratio, lifted when one normalised title contains the other's words."""
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    wa, wb = set(a.split()), set(b.split())
    if wa and wb:
        contain = len(wa & wb) / min(len(wa), len(wb))
        if min(len(wa), len(wb)) >= 2:
            ratio = max(ratio, contain * 0.9)
    return ratio


def celex_parts(celex: str | None) -> tuple[str, str, str] | None:
    m = re.match(r"3(\d{4})([RLD])(\d{4})$", celex or "")
    return (m.group(1), m.group(2), str(int(m.group(3)))) if m else None


def act_ref(celex: str | None) -> str | None:
    """'32014R0833' -> '833/2014' (pre-2015 regulation numbering), '32014D0145' -> '2014/145', '32026R2333' -> '2026/2333'."""
    p = celex_parts(celex)
    if not p:
        return None
    year, typ, num = p
    return f"{num}/{year}" if int(year) < 2015 and typ == "R" else f"{year}/{num}"


def eurlex_url(celex: str) -> str:
    return f"https://eur-lex.europa.eu/legal-content/FI/TXT/?uri=CELEX:{celex}"


def _add_event(events: list[dict], ev: dict) -> None:
    if not ev.get("date"):
        return
    if any(e.get("date") == ev["date"] and e.get("label") == ev["label"] for e in events):
        return
    events.append(ev)


def _sorted_events(events: list[dict]) -> list[dict]:
    return sorted(events, key=lambda e: (e.get("date") or "", e.get("label") or ""))


# ============================================================================= attach to EU procedure rows
def attach_eu_forecasts(eu_items: list[dict], signals: dict | None = None, cfg: dict | None = None) -> None:
    """Add ``forecast`` / ``coreper`` and their events to EU procedure rows in place (matched on ``pid``)."""
    sig = _signals(signals)
    cfg = _cfg(cfg)
    ncfg = cfg.get("neuvosto") or {}
    type_names = ncfg.get("tapahtumat") or {}
    today = TODAY.isoformat()
    oeil = (sig.get("forecasts") or {}).get("items") or {}
    ep_agenda = ((sig.get("forecasts") or {}).get("epAgenda") or {}).get("items") or {}
    council = sig.get("council") or {}
    on_agenda: dict[str, list[dict]] = {}
    for a in council.get("agendas") or []:
        if a.get("kind") == "wp":
            continue
        for it in a.get("items") or []:
            on_agenda.setdefault(it["pid"], []).append({"agenda": a, "item": it})
    cellar_ep: dict[str, list[dict]] = {}
    for ev in council.get("projected") or []:
        if ev.get("type") in ("VOTE_byEP", "DEBATE_byEP") and (ev.get("date") or "") >= today:
            cellar_ep.setdefault(ev["pid"], []).append(ev)
    for item in eu_items:
        pid = item.get("pid")
        if not pid:
            continue
        events = item.setdefault("events", [])
        ref = item.get("procedure") or ""
        # ---- Parliament forecast
        plenary = committee = source = None
        ep_rows = sorted((r for r in ep_agenda.get(pid) or [] if (r.get("date") or "") >= today), key=lambda r: (r["type"] != "vote", r["date"]))
        if ep_rows:
            votes = [r for r in ep_rows if r["type"] == "vote"]
            plenary = (votes or ep_rows)[0]["date"]
            source = "ep-agenda"
        o = oeil.get(pid) or {}
        if not plenary and (o.get("plenary") or "") >= today:
            plenary, source = o["plenary"], "oeil"
        if not plenary and cellar_ep.get(pid):
            votes = [e for e in cellar_ep[pid] if e["type"] == "VOTE_byEP"]
            plenary, source = (votes or cellar_ep[pid])[0]["date"], "cellar"
        if (o.get("committeeVote") or "") >= today:
            committee = o["committeeVote"]
        if plenary or committee:
            fc = {"plenary": plenary, "committeeVote": committee, "source": source if plenary else "oeil"}
            if o.get("stage"):
                fc["stage"] = o["stage"]
            others = [f for f in (o.get("forecasts") or []) if (f.get("date") or "") >= today and f["date"] not in (plenary, committee)]
            if others:
                fc["other"] = others[:3]
            if ep_rows and ep_rows[0].get("title_fi"):
                fc["agendaTitle"] = ep_rows[0]["title_fi"]
            item["forecast"] = fc
            oeil_url = item.get("links", {}).get("oeil") or (OEIL + ref if ref else None)
            if plenary and not any(e.get("date") == plenary and e.get("kind") == "parlamentti" for e in events):
                label = "EP:n täysistuntokäsittely (ennuste)" if source != "ep-agenda" else "EP:n täysistuntokäsittely (ennuste, esityslistalla)"
                _add_event(events, {"date": plenary, "label": label, "kind": "ennuste", "confirmed": False, **({"url": oeil_url} if oeil_url else {})})
            if committee:
                _add_event(events, {"date": committee, "label": "Valiokunnan äänestys (ennuste)", "kind": "ennuste", "confirmed": False, **({"url": oeil_url} if oeil_url else {})})
        # ---- Council / Coreper agendas
        rows = []
        for hit in on_agenda.get(pid) or []:
            a, it = hit["agenda"], hit["item"]
            date = it.get("date") or (a.get("meetingDates") or [None])[0]
            if not date:
                continue
            what = [type_names[t] for t in it.get("types") or [] if t in type_names]
            rows.append({"date": date, "body": a["body"], "url": a.get("urlFi") or a.get("url"), "what": ", ".join(dict.fromkeys(what)) or None, "doc": a.get("id")})
        if rows:
            rows = sorted({(r["date"], r["body"]): r for r in rows}.values(), key=lambda r: (r["date"], r["body"]))
            item["coreper"] = rows
            for r in rows:
                label = f"{r['body']} – esityslistalla" + (f" ({r['what']})" if r.get("what") else "")
                _add_event(events, {"date": r["date"], "label": label, "kind": "neuvosto", "confirmed": True, "src": "neuvosto", **({"url": r["url"]} if r.get("url") else {})})
        if item.get("forecast") or item.get("coreper"):
            item["events"] = _sorted_events(events)


# ============================================================================= signal rows
def _planned_commission(sig: dict, cfg: dict, topics_cfg: dict) -> list[dict]:
    fwd = sig.get("forward") or {}
    pcfg = cfg.get("planned_initiatives") or {}
    kcfg = cfg.get("komissio") or {}
    names = kcfg.get("vastuuhenkilot") or {}
    threshold = float(pcfg.get("match_threshold", 0.62))
    keep_past = int(pcfg.get("keep_past_days", 60))
    offset = int(pcfg.get("quarter_month_offset", 1))
    past_cutoff = (TODAY - dt.timedelta(days=keep_past)).isoformat()
    lists = fwd.get("lists") or []
    latest = lists[0] if lists else {}
    previous = lists[1] if len(lists) > 1 else {}
    cwp = fwd.get("cwp") or {}
    initiatives = cwp.get("initiatives") or [] if pcfg.get("cwp", True) else []
    prev_dates: dict[str, str] = {}
    for m in previous.get("meetings") or []:
        for it in m.get("items") or []:
            prev_dates.setdefault(it.get("norm") or "", m["date"])
    weekly: list[dict] = []
    if pcfg.get("weekly_list", True):
        for m in latest.get("meetings") or []:
            if (m.get("date") or "") < past_cutoff:
                continue
            for it in m.get("items") or []:
                base = {"date": m["date"], "place": m.get("place"), "responsible": it.get("responsible"), "reference": latest.get("reference"),
                        "url": latest.get("url"), "period": latest.get("period")}
                weekly.append({**base, "title": it["title"], "norm": it.get("norm") or "", "subItems": it.get("subItems") or [], "package": None})
                for s in it.get("subItems") or []:
                    weekly.append({**base, "title": s, "norm": re.sub(r"[^a-z0-9 ]", "", s.lower()), "subItems": [], "package": it["title"]})
    matched_cwp: set[int] = set()
    rows: list[dict] = []

    def best_cwp(norm: str) -> tuple[int, dict] | None:
        best = None
        for i, c in enumerate(initiatives):
            score = max(similar(norm, c.get("norm")), similar(norm, c.get("norm_fi")))
            if score >= threshold and (best is None or score > best[0]):
                best = (score, i, c)
        return (best[1], best[2]) if best else None

    for w in weekly:
        hit = best_cwp(w["norm"])
        c = hit[1] if hit else None
        if hit:
            matched_cwp.add(hit[0])
        key = f"cwp:{c.get('norm') or c.get('norm_fi')}" if c else f"sec:{w['norm']}"
        title = (c or {}).get("title_fi") or w["title"]
        title_en = (c or {}).get("title_en") or w["title"]
        text = " ".join([w["title"], title, title_en, (c or {}).get("objective") or "", (c or {}).get("package") or "", w.get("package") or ""] + w["subItems"])
        who = names.get((w.get("responsible") or "").upper(), w.get("responsible"))
        summary_bits = []
        if w["subItems"]:
            summary_bits.append("Paketti: " + "; ".join(w["subItems"]) + ".")
        if w.get("package"):
            summary_bits.append(f"Osa pakettia ”{w['package']}”.")
        if c:
            summary_bits.append(f"Komission työohjelma {cwp.get('reference', '')}: kohta {c.get('no')} ({c.get('objective')}), "
                                f"{'säädösaloite' if c.get('kind') == 'legislative' else 'muu kuin säädös' if c.get('kind') == 'non-legislative' else 'aloite'}"
                                + (f", viitteellinen ajankohta {quarter_text(c.get('quarter'))}" if c.get("quarter") else "") + ".")
        if w["norm"] in prev_dates and prev_dates[w["norm"]] != w["date"]:
            summary_bits.append(f"Siirtynyt: edellisellä listalla {fi_date(prev_dates[w['norm']])}.")
        if who:
            summary_bits.append(f"Vastuussa: {who}.")
        rows.append({"id": f"eu-sig-com-{sha12(key)}", "scope": "eu", "laji": "signaali", "kind": "Komission suunnitelma", "title": title[:160],
                     "fullTitle": title if title == title_en else f"{title} / {title_en}",
                     "ref": w["reference"] or "", "topics": classify(text, topics_cfg), "status": "suunniteltu", "done": False,
                     "summary": " ".join(summary_bits)[:700], "source": w["url"], "links": {"asiakirjarekisteri": w["url"], **({"tyoohjelma": cwp["url"]} if c and cwp.get("url") else {})},
                     "ministry": "Euroopan komissio", "authority": "Euroopan komissio", "responsible": who,
                     "planned": w["date"], "plannedText": f"{fi_date(w['date'])} (komission kokous{', ' + w['place'] if w.get('place') else ''})",
                     "planType": (c or {}).get("kind"), "policyArea": (c or {}).get("objective"), "quarter": (c or {}).get("quarter"),
                     "previousDate": prev_dates.get(w["norm"]) if prev_dates.get(w["norm"]) != w["date"] else None,
                     "events": [{"date": w["date"], "label": "Komission hyväksyntä (suunniteltu)", "kind": "ennuste", "confirmed": False, "url": w["url"]}],
                     "updated": latest.get("fetched")})
    for i, c in enumerate(initiatives):
        if i in matched_cwp:
            continue
        qend = quarter_end(c.get("quarter"))
        if qend and qend < past_cutoff:
            continue
        date = quarter_date(c.get("quarter"), offset)
        title = c.get("title_fi") or c.get("title_en") or ""
        title_en = c.get("title_en") or ""
        key = f"cwp:{c.get('norm') or c.get('norm_fi')}"
        text = " ".join([title, title_en, c.get("objective") or "", c.get("package") or "", c.get("section") or ""])
        bits = [f"Komission työohjelma {cwp.get('reference', '')}, liite I kohta {c.get('no')} ({c.get('objective')}): "
                f"{'säädösaloite' if c.get('kind') == 'legislative' else 'muu kuin säädös' if c.get('kind') == 'non-legislative' else 'aloite'}"
                + (f", {c['detail']}" if c.get("detail") else "") + "."]
        if c.get("package"):
            bits.append(f"Osa pakettia ”{c['package']}”.")
        rows.append({"id": f"eu-sig-com-{sha12(key)}", "scope": "eu", "laji": "signaali", "kind": "Komission suunnitelma", "title": title[:160],
                     "fullTitle": title if not title_en or title == title_en else f"{title} / {title_en}",
                     "ref": f"{cwp.get('reference', 'CWP')} liite I, {c.get('no')}", "topics": classify(text, topics_cfg), "status": "suunniteltu", "done": False,
                     "summary": " ".join(bits)[:700], "source": cwp.get("url"), "links": {"tyoohjelma": cwp.get("url")} if cwp.get("url") else {},
                     "ministry": "Euroopan komissio", "authority": "Euroopan komissio", "responsible": None,
                     "planned": date, "plannedText": quarter_text(c.get("quarter")) or "ajankohta avoin", "planType": c.get("kind"),
                     "policyArea": c.get("objective"), "quarter": c.get("quarter"), "previousDate": None,
                     "events": [{"date": date, "label": f"Komission hyväksyntä (työohjelman viitteellinen ajankohta {quarter_text(c.get('quarter'))})", "kind": "ennuste", "confirmed": False}] if date else [],
                     "updated": cwp.get("fetched")})
    # the same CWP initiative can be hit by several weekly rows (package + sub-item): keep the one with the earliest date
    uniq: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: r.get("planned") or "9999"):
        uniq.setdefault(r["id"], r)
    return list(uniq.values())


def _infringements(sig: dict, cfg: dict, topics_cfg: dict) -> list[dict]:
    rcfg = cfg.get("rikkomukset") or {}
    types_fi = rcfg.get("tyypit") or {}
    areas = rcfg.get("politiikanalat") or {}
    dg_topic = (cfg.get("komitologia") or {}).get("paaosastot") or {}
    rows = []
    for num, c in ((sig.get("infringements") or {}).get("cases") or {}).items():
        m = re.match(r"INFR\((\d{4})\)(\d+)", num)
        if not m or not c.get("decisions"):
            continue
        last = c["decisions"][-1]
        active = bool(c.get("active"))
        text = " ".join([c.get("title") or "", " ".join(c.get("policyAreas") or [])])
        topics = classify(text, topics_cfg)
        if topics == ["Muut"]:
            fb = [areas[a] for a in c.get("policyAreas") or [] if a in areas]
            if not fb and dg_topic.get(c.get("leadDg") or ""):
                fb = [dg_topic[c["leadDg"]]]
            if fb:
                topics = list(dict.fromkeys(fb))
        events = []
        for d in c["decisions"]:
            ev = {"date": d["date"], "label": f"Komissio: {d['stage']}", "kind": "muu", "confirmed": True}
            if d.get("memoUrl"):
                ev["url"] = d["memoUrl"]
            events.append(ev)
        case_type = types_fi.get(c.get("caseType") or "", c.get("caseType") or "")
        summary = f"Rikkomusmenettely {num}: {case_type}." if case_type else f"Rikkomusmenettely {num}."
        if c.get("actRef"):
            summary += f" Säädös: {c['actRef']}."
        if c.get("leadDg"):
            summary += f" Vastaava pääosasto: {c['leadDg']}."
        if c.get("policyAreas"):
            summary += f" Politiikanala: {', '.join(c['policyAreas'])}."
        if active and last["stage"].startswith("perusteltu lausunto"):
            summary += " Perusteltu lausunto on kanteen esivaihe: Suomella on tavallisesti kaksi kuukautta aikaa vastata."
        elif active and c.get("nonCommunication"):
            summary += " Täytäntöönpano on myöhässä – hallituksen esitys on odotettavissa."
        links = {}
        if last.get("memoUrl"):
            links["tiedote"] = last["memoUrl"]
        if last.get("pressUrl"):
            links["lehdistotiedote"] = last["pressUrl"]
        if last.get("curiaUrl"):
            links["curia"] = last["curiaUrl"]
        if c.get("celex"):
            links["saados"] = eurlex_url(c["celex"])
        rows.append({"id": f"eu-sig-infr-{m.group(1)}-{m.group(2)}", "scope": "eu", "laji": "signaali", "kind": "Rikkomusmenettely",
                     "title": (c.get("title") or num)[:160], "fullTitle": c.get("title") or num, "ref": num, "topics": topics,
                     "status": "vireillä" if active else "päättynyt", "done": not active, "summary": summary[:700],
                     "source": last.get("memoUrl") or "https://ec.europa.eu/implementing-eu-law/", "links": links,
                     "ministry": "Euroopan komissio" + (f", {c['leadDg']}" if c.get("leadDg") else ""), "authority": "Euroopan komissio",
                     "stage": last["stage"], "stageDate": last["date"], "caseType": case_type or None, "celex": c.get("celex"), "actRef": c.get("actRef"),
                     "curia": last.get("curia"), "events": _sorted_events(events), "updated": (sig.get("infringements") or {}).get("fetched")})
    return rows


def _eun(sig: dict, cfg: dict, topics_cfg: dict) -> list[dict]:
    ecfg = cfg.get("eun") or {}
    conf_topic = ecfg.get("kokoonpano_aihealue") or {}
    rows = []
    today = TODAY.isoformat()
    for key, d in ((sig.get("eun") or {}).get("docs") or {}).items():
        n, year = d.get("n"), d.get("year")
        if not n or not year:
            continue
        council = d.get("council") or ""
        title = d.get("title") or d.get("memoTitle") or d.get("tunnus")
        # the configuration's name ("…kuluttaja-asioiden neuvosto") would hit the keyword lists; classify on the
        # subject words only and fall back to the configuration -> topic map
        text = " ".join([re.sub(r"\(.*?\)", " ", title or ""), " ".join(d.get("keywords") or [])])
        topics = classify(text, topics_cfg)
        if topics == ["Muut"]:
            hay = (council or title or "").lower()
            fb = next((v for k, v in conf_topic.items() if k.lower() in hay), None)
            if fb:
                topics = [fb]
        date = d.get("date")
        events = []
        if date:
            ev = {"date": date, "label": f"{council or 'Neuvoston kokous'} – kokous", "kind": "neuvosto", "confirmed": True}
            if d.get("end"):
                ev["end"] = d["end"]
            events.append(ev)
        if d.get("submitted"):
            ev = {"date": d["submitted"], "label": "Valtioneuvoston muistio eduskunnalle (EUN)", "kind": "muu", "confirmed": True}
            if d.get("pdf"):
                ev["url"] = d["pdf"]
            events.append(ev)
        for h in d.get("handling") or []:
            if h.get("label") in ("Asiantuntijakuuleminen", "Käsittely SuV tai UaV") and h.get("committee"):
                _add_event(events, {"date": h["date"], "label": f"{h['label']} – {h['committee']}", "kind": "eduskunta", "confirmed": True})
        held = bool((d.get("end") or date or "") < today) if date else False
        bits = []
        if d.get("keywords"):
            bits.append("Asiasanat: " + ", ".join(d["keywords"][:8]) + ".")
        if d.get("eutori"):
            bits.append(f"EUTORI {d['eutori']}.")
        if not d.get("hasMemo"):
            bits.append("Valtioneuvoston muistio ei ole vielä julkinen / liitetty.")
        bits.append("Suomen kannat kokouksen asialistaan; EU-ministerivaliokunta käsittelee saman kokouksen yleensä viikkoa aiemmin.")
        links = {"eduskunta": d.get("url")} if d.get("url") else {}
        if d.get("pdf"):
            links["muistio"] = d["pdf"]
        rows.append({"id": f"fi-eun-{n}-{year}", "scope": "eu", "laji": "signaali", "kind": "Neuvoston kokous (VNK:n muistio)",
                     "title": (title or "")[:160], "fullTitle": title, "ref": d.get("tunnus") or f"EUN {n}/{year} vp", "topics": topics,
                     "status": "pidetty" if held else "tulossa", "done": held, "summary": " ".join(bits)[:700],
                     "source": d.get("pdf") or d.get("url"), "links": links, "ministry": "Valtioneuvoston kanslia", "authority": "Valtioneuvosto",
                     "council": council or None, "meetingDate": date, "meetingEnd": d.get("end"), "keywords": (d.get("keywords") or [])[:10],
                     "events": _sorted_events(events), "updated": d.get("fetched")})
    return rows


def signal_items(topics_cfg: dict, signals: dict | None = None, cfg: dict | None = None) -> list[dict]:
    """laji 'signaali' rows: Commission plans, infringement cases against Finland, EUN Council-meeting memos."""
    sig = _signals(signals)
    cfg = _cfg(cfg)
    rows = _planned_commission(sig, cfg, topics_cfg) + _infringements(sig, cfg, topics_cfg) + _eun(sig, cfg, topics_cfg)
    return rows


# ============================================================================= implementing acts (comitology)
IA_PREFIX = re.compile(r"^(?:draft\s+)?(commission\s+)?(implementing\s+)?(regulation|decision|directive)\b\s*(\(E[UC]\)|\(EU,\s*Euratom\))?\s*(?:No\.?)?\s*(?:[…./xX ]+|\d{4}/\d+)?\s*(?:of\s+(?:XXX|\d{1,2}(?:\.\d{1,2}\.\d{4})?|[\d.]+)\s*)?", re.I)
IA_KINDS = {("implementing", "regulation"): "Täytäntöönpanoasetus", ("implementing", "decision"): "Täytäntöönpanopäätös",
            ("implementing", "directive"): "Täytäntöönpanodirektiivi", ("", "regulation"): "Komission asetus (komitologia)",
            ("", "decision"): "Komission päätös (komitologia)", ("", "directive"): "Komission direktiivi (komitologia)"}


def ia_title(raw: str) -> tuple[str, str]:
    """'COMMISSION IMPLEMENTING REGULATION (EU) …/... of XXX on the methodology …' -> (kind FI, cleaned title)."""
    t = re.sub(r"\s+", " ", raw or "").strip()
    t = re.sub(r"^(?:EN\s+\d+\s+EN\s+|EN\s*-\s*|Draft\s*(?:to|-)\s*(?:CID\s*-\s*)?)", "", t).strip()
    m = IA_PREFIX.match(t)
    kind = "Täytäntöönpanosäädös"
    if m:
        kind = IA_KINDS.get(("implementing" if m.group(2) else "", m.group(3).lower()), kind)
        rest = t[m.end():].strip()
        head = {"Täytäntöönpanoasetus": "Commission Implementing Regulation", "Täytäntöönpanopäätös": "Commission Implementing Decision",
                "Täytäntöönpanodirektiivi": "Commission Implementing Directive", "Komission asetus (komitologia)": "Commission Regulation",
                "Komission päätös (komitologia)": "Commission Decision", "Komission direktiivi (komitologia)": "Commission Directive"}.get(kind, "Commission act")
        t = f"{head} {rest}".strip() if rest else head
    t = re.sub(r"\s*\(Text with EEA relevance\)\s*$", "", t, flags=re.I)
    return kind, t


def _hys_match(title: str, hys_items: list[dict]) -> dict | None:
    """Best Have your say draft-act initiative for a comitology draft, by word overlap of the titles."""
    words = {w for w in re.sub(r"[^a-z0-9 ]", " ", title.lower()).split() if len(w) > 3}
    words -= {"commission", "implementing", "regulation", "decision", "directive", "laying", "down", "rules", "application", "european",
              "parliament", "council", "regards", "amending", "certain", "with", "text", "relevance", "annex", "annexes"}
    best, best_score = None, 0.0
    for h in hys_items:
        hw = {w for w in re.sub(r"[^a-z0-9 ]", " ", (h.get("title_en") or "").lower()).split() if len(w) > 3}
        if not hw or not words:
            continue
        score = len(words & hw) / min(len(words), len(hw))
        if score > best_score and len(words & hw) >= 3:
            best, best_score = h, score
    return best if best_score >= 0.6 else None


def implementing_items(topics_cfg: dict, signals: dict | None = None, cfg: dict | None = None, hys: list[dict] | None = None) -> list[dict]:
    """laji 'taytantoonpano' rows from the comitology cache."""
    sig = _signals(signals)
    cfg = _cfg(cfg)
    kcfg = cfg.get("komitologia") or {}
    states = kcfg.get("tilat") or {}
    opinions = kcfg.get("lausunnot") or {}
    dg_topic = kcfg.get("paaosastot") or {}
    if hys is None:
        hys = (load_json(HYS_CACHE, {}) or {}).get("items") or []
    hys_drafts = [h for h in hys if str(h.get("actType") or "").endswith("_IMPL") or any(p.get("stage") in ("DRAFT_ACT", "ISC_WORKFLOW") for p in h.get("periods") or [])]
    today = TODAY.isoformat()
    committees = (sig.get("comitology") or {}).get("committees") or {}
    rows = []
    for ref, d in ((sig.get("comitology") or {}).get("documents") or {}).items():
        if not d.get("title"):
            continue
        d = {**d, "url": d.get("url") or f"{COMREG_UI}/{ref[1:]}/{d.get('version') or 1}/consult",
             "committee": d.get("committee") or (committees.get(d.get("committeeCode") or "") or {}).get("title")}
        kind, title = ia_title(d["title"])
        ba = d.get("basicAct") or {}
        text = " ".join([title, ba.get("title") or "", d.get("committee") or ""])
        topics = classify(text, topics_cfg)
        if topics == ["Muut"] and dg_topic.get(d.get("dg") or ""):
            topics = [dg_topic[d["dg"]]]
        status = states.get(d.get("status") or "", "äänestys tulossa")
        vote_fi = opinions.get(d.get("voteResult") or "", d.get("voteResult"))
        if status == "hyväksytty komiteassa" and vote_fi and vote_fi != "puoltava" and vote_fi in ("kielteinen", "ei lausuntoa"):
            status = "kielteinen lausunto" if vote_fi == "kielteinen" else "ei lausuntoa"
        events: list[dict] = []
        if d.get("submitted"):
            _add_event(events, {"date": d["submitted"], "label": "Luonnos toimitettu komitealle", "kind": "ehdotus", "confirmed": True, **({"url": d["url"]} if d.get("url") else {})})
        if d.get("voteDate"):
            _add_event(events, {"date": d["voteDate"], "label": f"Komitean äänestys: {vote_fi or 'tulos kirjattu'}", "kind": "muu", "confirmed": True})
        elif d.get("meetingStart") and status in ("äänestys tulossa", "lykätty"):
            ev = {"date": d["meetingStart"], "label": "Komitean äänestys (kokous tai kirjallinen menettely)", "kind": "muu", "confirmed": False}
            if d.get("meetingEnd") and d["meetingEnd"] != d["meetingStart"]:
                ev["end"] = d["meetingEnd"]
            _add_event(events, ev)
        if d.get("adoptionDate"):
            _add_event(events, {"date": d["adoptionDate"], "label": "Annettu", "kind": "julkaistu", "confirmed": True})
        h = _hys_match(title, hys_drafts) if hys_drafts else None
        links = {"komitologia": d.get("url")} if d.get("url") else {}
        if h:
            p = (h.get("periods") or [{}])[-1]
            if p.get("start") and p.get("end"):
                _add_event(events, {"date": p["start"], "end": p["end"], "label": "Palauteaika (Have your say)", "kind": "lausunto", "confirmed": True, **({"url": h["url"]} if h.get("url") else {})})
            if h.get("url"):
                links["hys"] = h["url"]
        if ba.get("celex"):
            links["perussaados"] = eurlex_url(ba["celex"])
        done = status in ("annettu", "peruutettu")
        bits = [f"Komitea: {d['committee']}." if d.get("committee") else "", f"Menettely: {d['procedure']}." if d.get("procedure") else "",
                f"Perussäädös: {ba['title']}." if ba.get("title") else "", f"Komitean lausunto {fi_date(d['voteDate'])}: {vote_fi}." if d.get("voteDate") and vote_fi else "",
                "Komitean puoltava lausunto tarkoittaa, että komissio antaa säädöksen tavallisesti muutaman viikon kuluessa." if status == "hyväksytty komiteassa" else ""]
        rows.append({"id": f"eu-ia-{ref.lower()}", "scope": "eu", "laji": "taytantoonpano", "kind": kind, "title": title[:160], "fullTitle": title,
                     "ref": f"{ref}" + (f"/{d['version']:02d}" if isinstance(d.get("version"), int) and d["version"] else ""), "topics": topics, "status": status, "done": done,
                     "summary": " ".join(b for b in bits if b)[:700], "source": d.get("url"), "links": links,
                     "ministry": "Euroopan komissio" + (f", {d['dg']}" if d.get("dg") else "") + (f" · perussäädös {ba.get('code') or act_ref(ba.get('celex'))}" if ba.get("code") or ba.get("celex") else ""),
                     "committee": d.get("committee"), "committeeCode": d.get("committeeCode"), "voteResult": vote_fi, "voteDate": d.get("voteDate"),
                     "procedure": d.get("procedure"), "basicAct": {"title": ba.get("title"), "celex": ba.get("celex")}, "celex": ba.get("celex"),
                     "events": _sorted_events(events), "updated": d.get("statusDate") or today})
    return rows


# ============================================================================= sanctions
SANCTION_KIND = re.compile(r"^(Neuvoston täytäntöönpanoasetus|Neuvoston asetus|Neuvoston täytäntöönpanopäätös|Neuvoston päätös|Komission täytäntöönpanoasetus|Komission asetus|Komission täytäntöönpanopäätös)", re.I)


def sanction_title(a: dict) -> tuple[str, str]:
    """(kind, short title): drops the ', annettu 15 päivänä lokakuuta 2026,' clause from the Finnish title."""
    fi = (a.get("title_fi") or "").strip()
    en = (a.get("title_en") or "").strip()
    m = SANCTION_KIND.match(fi)
    if m:
        kind = m.group(1)[0].upper() + m.group(1)[1:]
        if "(YUTP)" in fi[:80] and "päätös" in kind.lower():
            kind += " (YUTP)"
    else:
        p = celex_parts(a.get("celex"))
        impl = "implementing" in en.lower() or "täytäntöönpano" in fi.lower()
        kind = ("Täytäntöönpanoasetus" if impl else "Asetus") if p and p[1] == "R" else ("Täytäntöönpanopäätös" if impl else "Päätös (YUTP)")
    title = re.sub(r",\s*annettu\s+\d{1,2}\s+päivänä\s+\w+\s+\d{4},?\s*", ", ", fi).strip() if fi else en
    return kind, title or a.get("celex", "")


def sanction_items(topics_cfg: dict, signals: dict | None = None, cfg: dict | None = None) -> list[dict]:
    """laji 'pakote' rows: restrictive-measures acts from the OJ (Cellar)."""
    sig = _signals(signals)
    cfg = _cfg(cfg)
    pcfg = cfg.get("pakotteet") or {}
    default = list(pcfg.get("topics_default") or ["Turvallisuus ja puolustus"])
    today = TODAY.isoformat()
    rows = []
    for a in (sig.get("sanctions") or {}).get("acts") or []:
        celex = a.get("celex")
        p = celex_parts(celex)
        if not p:
            continue
        kind, title = sanction_title(a)
        amended = (a.get("amends") or [None])[0]
        regime = a.get("regime") or "muu"
        regime_text = f"{regime} {act_ref(amended)}" if amended and act_ref(amended) else regime
        events = []
        if a.get("oj"):
            events.append({"date": a["oj"], "label": "Julkaistu EUVL:ssä", "kind": "julkaistu", "confirmed": True, "url": eurlex_url(celex)})
        if a.get("eif"):
            events.append({"date": a["eif"], "label": "Voimaan", "kind": "voimaan", "confirmed": True})
        in_force = bool(a.get("eif")) and a["eif"] <= today and a.get("inForce") != "0"  # Cellar's flag lags a day or two
        status = "voimassa" if in_force else "julkaistu"
        extra = [t for t in classify(" ".join([title, a.get("title_en") or ""]), topics_cfg) if t != "Muut" and t not in default]
        year, typ, num = p
        impl = "implementing" in (a.get("title_en") or "").lower() or "täytäntöönpano" in (a.get("title_fi") or "").lower()
        eli = f"https://eur-lex.europa.eu/eli/{'reg_impl' if impl and typ == 'R' else 'reg' if typ == 'R' else 'dec_impl' if impl else 'dec'}/{year}/{num}/oj"
        bits = [f"Pakotejärjestelmä: {regime_text}." if regime != "muu" else "Rajoittavat toimenpiteet (pakotejärjestelmä tunnistamatta).",
                f"Muuttaa tai panee täytäntöön säädöstä {act_ref(amended)} (CELEX {amended})." if amended else "",
                f"EUVL L {year}/{num}, {fi_date(a['oj'])}." if a.get("oj") else ""]
        if a.get("title_en"):
            bits.append(a["title_en"])
        ref = f"(EU) {year}/{num}" if typ == "R" else f"(YUTP) {year}/{num}"
        short = f"{kind} {ref} – {regime_text}" if regime != "muu" else title
        rows.append({"id": f"eu-pak-{celex}", "scope": "eu", "laji": "pakote", "kind": kind, "title": short[:160], "fullTitle": a.get("title_fi") or a.get("title_en"),
                     "ref": ref, "topics": default + extra, "status": status, "done": in_force,
                     "summary": " ".join(b for b in bits if b)[:700], "source": eurlex_url(celex),
                     "links": {"eurlex": eurlex_url(celex), "eli": eli, **({"perussaados": eurlex_url(amended)} if amended else {})},
                     "ministry": "Euroopan unionin neuvosto" if kind.lower().startswith("neuvoston") else "Euroopan komissio",
                     "regime": regime_text, "regimeLabel": regime, "celex": celex, "amendedAct": amended, "ojDate": a.get("oj"), "entryIntoForce": a.get("eif"),
                     "events": _sorted_events(events), "updated": a.get("oj")})
    return rows
