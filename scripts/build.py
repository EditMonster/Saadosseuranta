"""Merge the cached sources into docs/data/items.json for the web page."""
from __future__ import annotations

import datetime as dt
import re

from build_hankinnat import build_hankinnat
from common import CACHE_DIR, CONFIG_DIR, OUT_DIR, TODAY, days_ago, is_future, load_json, load_yaml, log, save_json

HE_PREFIX = re.compile(r"^hallituksen esitys (eduskunnalle )?", re.I)


def classify(text: str, topics_cfg: dict) -> list[str]:
    t = (text or "").lower()
    out = [name for name, kws in topics_cfg.items() if any(k.lower() in t for k in kws)]
    return out or ["Muut"]


def short_title(title: str) -> str:
    t = HE_PREFIX.sub("", (title or "").strip())
    t = re.sub(r"^(laiksi|laeiksi|lain|lakien)\s+", lambda m: m.group(1).capitalize() + " ", t)
    return (t[:1].upper() + t[1:]) if t else title


def he_num(s: str) -> str | None:
    m = re.search(r"(\d+)/(\d{4})", s or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None


def status_class_fi(ev: list[dict], has_he: bool, vahvistettu: bool, rauennut: bool) -> str:
    if rauennut:
        return "rauennut"
    if vahvistettu:
        return "vahvistettu"
    if any(e["kind"] == "hyvaksytty" for e in ev):
        return "hyväksytty"
    if has_he:
        return "eduskunnassa"
    if any(e["kind"] == "lausunto" and e.get("end") and e["date"] <= TODAY.isoformat() <= e["end"] for e in ev):
        return "lausunnolla"
    return "valmistelussa"


def build_fi(topics_cfg, settings) -> list[dict]:
    hk = load_json(CACHE_DIR / "hankeikkuna.json", {"items": []})["items"]
    ek = load_json(CACHE_DIR / "eduskunta.json", {"items": {}})["items"]
    fx = load_json(CACHE_DIR / "finlex.json", {"items": {}})["items"]
    items, used_he = [], set()

    def eduskunta_events(rec: dict) -> list[dict]:
        ev = []
        last = {}
        for s in rec.get("stages", []):
            last[s["code"]] = s
        if "ANTO" in last:
            ev.append({"date": last["ANTO"]["date"], "label": "HE annettu eduskunnalle", "kind": "he", "confirmed": True})
        if "LK" in last:
            ev.append({"date": last["LK"]["date"], "label": "Lähetekeskustelu", "kind": "eduskunta", "confirmed": True})
        if "VKPM" in last:
            c = last["VKPM"].get("committee")
            ev.append({"date": last["VKPM"]["date"], "label": "Valiokunnan mietintö" + (f" ({c})" if c else ""), "kind": "eduskunta", "confirmed": True})
        fin = last.get("2K") or last.get("AK")
        if fin:
            ev.append({"date": fin["date"], "label": "Hyväksytty eduskunnassa", "kind": "hyvaksytty", "confirmed": True})
        if "EV" in last and (not fin or last["EV"]["date"] != fin["date"]):
            ev.append({"date": last["EV"]["date"], "label": "Eduskunnan vastaus", "kind": "hyvaksytty", "confirmed": True})
        if rec.get("vahvistettu"):
            ev.append({"date": rec["vahvistettu"], "label": "Vahvistettu", "kind": "vahvistettu", "confirmed": True})
        return ev

    def finlex_events(sks: list[str]) -> list[dict]:
        ev, seen = [], set()
        for sk in sks:
            f = fx.get(sk)
            if f and f.get("voimaan") and f["voimaan"] not in seen:
                seen.add(f["voimaan"])
                ev.append({"date": f["voimaan"], "label": f"Voimaan ({sk})", "kind": "voimaan", "confirmed": True, "url": f["url"]})
        return ev

    def make(base_id, title, ref, ev, *, has_he, vahvistettu, rauennut, summary, source, links, ministry, text, extra):
        ev = sorted({(e["date"], e["label"]): e for e in ev}.values(), key=lambda e: e["date"])
        status = status_class_fi(ev, has_he, vahvistettu, rauennut)
        done = status == "vahvistettu"
        if done:
            v = [e["date"] for e in ev if e["kind"] == "voimaan"]
            if v and not is_future(v[0]) and (days_ago(v[0]) or 0) >= 0:
                status = "voimassa"
        item = {"id": base_id, "scope": "fi", "laji": "laki", "kind": "HE" if has_he else "Lakiluonnos", "title": short_title(title),
                "fullTitle": title, "ref": ref, "topics": classify(text, topics_cfg), "status": status, "done": done,
                "summary": summary, "source": source, "links": links, "ministry": ministry, "events": ev}
        item.update(extra)
        if done:
            item["kind"] = "Laki"
        return item

    for p in hk:
        if p.get("laji") == "asetus":
            continue
        hes = [he_num(h) for h in p.get("heNumerot") or []]
        hes = [h for h in hes if h]
        rec = ek.get(hes[0]) if hes else None
        ev = []
        for e in p.get("etapit", []):
            ev.append({"date": e["date"], "end": e.get("end"), "label": e["label"], "kind": e["kind"], "confirmed": True})
        if not any(e["kind"] == "lausunto" for e in ev):
            for d in p.get("asiakirjat", []):
                if d["tyyppi"] == "LAUSUNTOPYYNTO" and d.get("pvm"):
                    ev.append({"date": d["pvm"], "label": "Lausuntopyyntö lähetetty", "kind": "lausunto", "confirmed": True, "url": d["url"]})
                    break
        if rec:
            ev += eduskunta_events(rec)
        elif p.get("annettuEduskunnalle"):
            ev.append({"date": p["annettuEduskunnalle"], "label": "HE annettu eduskunnalle", "kind": "he", "confirmed": True})
        sks = list(dict.fromkeys((rec.get("sk", []) if rec else []) + (p.get("skNumerot") or [])))
        vev = finlex_events(sks)
        ev += vev
        if not vev and rec and rec.get("ehdotettuVoimaantulo"):
            ev.append({"date": rec["ehdotettuVoimaantulo"], "label": "Ehdotettu voimaantulo", "kind": "voimaan", "confirmed": True})
        title = (rec or {}).get("title") or p["nimi"]
        ref = f"HE {hes[0]} vp" if hes else (p.get("tunnus") or "")
        if (rec or {}).get("vahvistettu") and sks:
            ref = f"{sks[0]} · HE {hes[0]} vp" if hes else sks[0]
        links = {"hankeikkuna": p.get("url")}
        if hes:
            n, y = hes[0].split("/")
            links["finlex"] = f"https://www.finlex.fi/fi/hallituksen-esitykset/{y}/{n}"
            used_he.update(hes)
        for sk in sks:
            if fx.get(sk):
                links.setdefault("saadoskokoelma", fx[sk]["url"])
        summary = (p.get("tiivistelma") or "")[:400]
        if not summary and rec and rec.get("laws"):
            summary = "Lakiehdotukset: " + "; ".join(l["name"] for l in rec["laws"][:4] if l.get("name"))
        text = " ".join([title, p.get("nimi", ""), summary, " ".join(p.get("teemat", [])), " ".join(p.get("asiasanat", [])),
                         " ".join(l.get("name", "") for l in (rec or {}).get("laws", []))])
        rauennut = bool(p.get("rauennut")) or ((rec or {}).get("tila") == "Rauennut")
        items.append(make(f"fi-he-{hes[0].replace('/', '-')}" if hes else f"fi-hanke-{p['uuid'][:8]}", title, ref, ev,
                          has_he=bool(hes), vahvistettu=bool((rec or {}).get("vahvistettu")), rauennut=rauennut,
                          summary=summary, source=links.get("finlex") or p.get("url"), links=links, ministry=p.get("ministerio", ""),
                          text=text, extra={"tunnus": p.get("tunnus"), "sk": sks, "heNumerot": hes, "teemat": p.get("teemat", []),
                                             "committees": (rec or {}).get("committees", []), "updated": p.get("muokattu")}))
    # proposals known to Eduskunta/Finlex but not linked to a Hankeikkuna project
    for num, rec in ek.items():
        if num in used_he or not rec.get("title"):
            continue
        ev = eduskunta_events(rec) + finlex_events(rec.get("sk", []))
        if not any(e["kind"] == "voimaan" for e in ev) and rec.get("ehdotettuVoimaantulo"):
            ev.append({"date": rec["ehdotettuVoimaantulo"], "label": "Ehdotettu voimaantulo", "kind": "voimaan", "confirmed": True})
        if rec.get("lausuntoaika") and all(rec["lausuntoaika"]):
            ev.append({"date": rec["lausuntoaika"][0], "end": rec["lausuntoaika"][1], "label": "Lausuntokierros", "kind": "lausunto", "confirmed": True})
        n, y = num.split("/")
        links = {"finlex": f"https://www.finlex.fi/fi/hallituksen-esitykset/{y}/{n}"}
        summary = "Lakiehdotukset: " + "; ".join(l["name"] for l in rec.get("laws", [])[:4] if l.get("name")) if rec.get("laws") else ""
        text = " ".join([rec["title"], summary])
        ref2 = f"{rec['sk'][0]} · HE {num} vp" if rec.get("vahvistettu") and rec.get("sk") else f"HE {num} vp"
        items.append(make(f"fi-he-{n}-{y}", rec["title"], ref2, ev, has_he=True, vahvistettu=bool(rec.get("vahvistettu")),
                          rauennut=rec.get("tila") == "Rauennut", summary=summary, source=links["finlex"], links=links, ministry="",
                          text=text, extra={"sk": rec.get("sk", []), "heNumerot": [num], "committees": rec.get("committees", [])}))
    return items


def build_asetukset(topics_cfg, settings) -> list[dict]:
    hk = load_json(CACHE_DIR / "hankeikkuna.json", {"items": []})["items"]
    fx = load_json(CACHE_DIR / "finlex.json", {"items": {}})["items"]
    items = []
    for p in hk:
        if p.get("laji") != "asetus":
            continue
        ev = []
        for e in p.get("etapit", []):
            if e.get("tyyppi") == "SAADOS":
                ev.append({"date": e["date"], "label": "Asetus annettu", "kind": "vahvistettu", "confirmed": True})
            else:
                ev.append({"date": e["date"], "end": e.get("end"), "label": e["label"], "kind": e["kind"], "confirmed": True})
        if not any(e["kind"] == "lausunto" for e in ev):
            for d in p.get("asiakirjat", []):
                if d["tyyppi"] == "LAUSUNTOPYYNTO" and d.get("pvm"):
                    ev.append({"date": d["pvm"], "label": "Lausuntopyyntö lähetetty", "kind": "lausunto", "confirmed": True, "url": d["url"]})
                    break
        sks = list(p.get("skNumerot") or [])
        voimaan = None
        for sk in sks:
            f = fx.get(sk)
            if f and f.get("voimaan"):
                voimaan = voimaan or f["voimaan"]
                ev.append({"date": f["voimaan"], "label": f"Voimaan ({sk})", "kind": "voimaan", "confirmed": True, "url": f["url"]})
        ev = sorted({(e["date"], e["label"]): e for e in ev}.values(), key=lambda e: e["date"])
        annettu = bool(sks) or any(e["kind"] == "vahvistettu" for e in ev)
        if annettu:
            status = "voimassa" if voimaan and not is_future(voimaan) else "annettu"
        elif any(e["kind"] == "lausunto" and e.get("end") and e["date"] <= TODAY.isoformat() <= e["end"] for e in ev):
            status = "lausunnolla"
        else:
            status = "valmistelussa"
        done = status == "voimassa"
        if done:
            last = max((e["date"] for e in ev), default=None)
            if last and (days_ago(last) or 0) > settings["completed"]["max_age_days"]:
                continue
        if p.get("tila") == "PAATTYNYT" and not done:
            continue
        title = p["nimi"]
        links = {"hankeikkuna": p.get("url")}
        for sk in sks:
            if fx.get(sk):
                links.setdefault("saadoskokoelma", fx[sk]["url"])
        summary = (p.get("tiivistelma") or "")[:400]
        text = " ".join([title, summary, " ".join(p.get("teemat", [])), " ".join(p.get("asiasanat", []))])
        items.append({"id": f"fi-asetus-{p['uuid'][:8]}", "scope": "fi", "laji": "asetus", "kind": "Asetus" if annettu else "Asetusluonnos",
                      "title": short_title(title), "fullTitle": title, "ref": (sks[0] if sks else (p.get("tunnus") or "")),
                      "topics": classify(text, topics_cfg), "status": status, "done": done, "summary": summary,
                      "source": links.get("saadoskokoelma") or p.get("url"), "links": links, "ministry": p.get("ministerio", ""),
                      "events": ev, "tunnus": p.get("tunnus"), "sk": sks, "updated": p.get("muokattu")})
    return items


def attach_ue(eu_items: list[dict], topics_cfg) -> list[dict]:
    """Attach U/E letters to the EU procedures they concern (by COM number or procedure
    reference); letters without a tracked procedure become items of their own."""
    ue = load_json(CACHE_DIR / "ue.json", {"items": {}})["items"]
    by_com, by_pid = {}, {}
    for it in eu_items:
        if it.get("proposalCom"):
            by_com.setdefault(it["proposalCom"], it)
        if it.get("pid"):
            by_pid[it["pid"]] = it
    standalone = []
    for tunnus, d in ue.items():
        if not d.get("anto"):
            continue
        kind_u = tunnus.startswith("U")
        label = f"{tunnus.replace(' vp', '')} annettu – Suomen kanta" if kind_u else f"{tunnus.replace(' vp', '')} – valtioneuvoston selvitys"
        url = f"https://www.eduskunta.fi/FI/search/Sivut/Vaskiresults.aspx?k={tunnus.replace(' vp', '').replace(' ', '+')}"
        targets = []
        for c in d.get("com", []):
            if c in by_com and by_com[c] not in targets:
                targets.append(by_com[c])
        for pid in d.get("cod", []):
            if pid in by_pid and by_pid[pid] not in targets:
                targets.append(by_pid[pid])
        ev = {"date": d["anto"], "label": label, "kind": "kanta", "confirmed": True, "url": url}
        if targets:
            for it in targets:
                if not any(e["label"] == label for e in it["events"]):
                    it["events"].append(ev)
                    it["events"].sort(key=lambda e: e["date"])
                it.setdefault("kirjelmat", []).append(tunnus)
            continue
        if (days_ago(d["anto"]) or 0) > 365:
            continue
        text0 = d.get("short", "") + " " + d.get("title", "")
        if not kind_u and classify(text0, topics_cfg) == ["Muut"]:
            continue
        evs = [ev]
        for s in d.get("stages", []):
            if s["code"] == "VKPL":
                evs.append({"date": s["date"], "label": "Valiokunnan lausunto", "kind": "eduskunta", "confirmed": True})
        text = d.get("short", "") + " " + d.get("title", "")
        standalone.append({"id": "fi-" + tunnus.replace(" vp", "").replace(" ", "-").replace("/", "-").lower(), "scope": "eu", "laji": "kirjelma",
                           "kind": "U-kirjelmä" if kind_u else "E-kirje", "title": d.get("short") or d.get("title"), "fullTitle": d.get("title"),
                           "ref": tunnus, "topics": classify(text, topics_cfg), "status": "käsitelty" if d.get("tila") == "Valmis" else "eduskunnassa",
                           "done": False, "summary": ("Komission asiakirjat: " + ", ".join(f"COM({c.split('/')[0]}) {c.split('/')[1]}" for c in d.get("com", [])[:6])) if d.get("com") else "",
                           "source": url, "links": {"eduskunta": url}, "ministry": d.get("ministry") or "", "events": sorted(evs, key=lambda e: e["date"]),
                           "updated": d.get("fetched")})
    return standalone


def build_hys(topics_cfg, settings) -> list[dict]:
    hys = load_json(CACHE_DIR / "hys.json", {"items": []})["items"]
    items = []
    for h in hys:
        title = h.get("title_fi") or h.get("title_en") or ""
        text = " ".join([title, h.get("title_en") or ""])
        topics = classify(text, topics_cfg)
        if topics == ["Muut"]:
            continue
        ev = []
        for p in h.get("periods", []):
            stage = STAGE_LABELS.get(p.get("stage"), "Palauteaika")
            ev.append({"date": p["start"], "end": p["end"], "label": stage, "kind": "lausunto", "confirmed": True, "url": h["url"]})
        ev.sort(key=lambda e: e["date"])
        now_open = any(e["date"] <= TODAY.isoformat() <= e["end"] for e in ev)
        upcoming = any(e["date"] > TODAY.isoformat() for e in ev)
        status = "lausunnolla" if now_open else ("palauteaika tulossa" if upcoming else "palauteaika päättynyt")
        items.append({"id": f"eu-hys-{h['id']}", "scope": "eu", "laji": "kuuleminen", "kind": "EU-kuuleminen", "title": title[:160],
                      "fullTitle": h.get("title_en") or title, "ref": h.get("actTypeLabel") or "Komission aloite", "topics": topics,
                      "status": status, "done": False, "summary": (f"{h.get('actTypeLabel') or ''} · {h.get('reference') or ''}").strip(" ·"),
                      "source": h["url"], "links": {"haveyoursay": h["url"]}, "events": ev, "updated": None})
    return items


STAGE_LABELS = {
    "CALL_FOR_EVIDENCE": "Kannanottopyyntö (call for evidence)", "PUBLIC_CONSULTATION": "Julkinen kuuleminen",
    "ADOPTION_WORKFLOW": "Palaute hyväksytystä ehdotuksesta", "DRAFT_ACT": "Palaute säädösluonnoksesta",
    "ISC_WORKFLOW": "Palaute säädösluonnoksesta", "DELEGATED_ACT": "Palaute delegoidusta säädöksestä",
}


def celex_ref(celex: str) -> tuple[str, str]:
    m = re.match(r"3(\d{4})([RLD])(\d{4})", celex)
    if not m:
        return celex, "Säädös"
    kind = {"R": "Asetus", "L": "Direktiivi", "D": "Päätös"}[m.group(2)]
    return f"(EU) {m.group(1)}/{int(m.group(3))}", kind


def build_eu(topics_cfg, settings, watch) -> list[dict]:
    eu = load_json(CACHE_DIR / "eu.json", {"items": {}})["items"]
    watched = {re.sub(r"\(.*\)", "", w).strip().replace("/", "-") for w in (watch.get("procedures") or [])}
    watched = {f"{a}-{b}" for a, b in (w.split("-") for w in watched)}
    items = []
    for pid, rec in eu.items():
        c = rec.get("cellar") or {}
        acts = c.get("acts") or {}
        title = rec.get("title_fi") or rec.get("title_en") or rec.get("ref")
        text = " ".join([title, rec.get("title_en", "")] + [a.get("title_fi") or "" for a in acts.values()])
        topics = classify(text, topics_cfg)
        if topics == ["Muut"] and pid not in watched:
            continue
        ev = []
        if c.get("proposalDate"):
            ev.append({"date": c["proposalDate"][:10], "label": f"Komission ehdotus{(' ' + c['proposal']) if c.get('proposal') else ''}", "kind": "ehdotus", "confirmed": True})
        ev += rec.get("events", [])
        act = None
        if acts:
            act = sorted(acts.values(), key=lambda a: a["celex"])[0]
            if act.get("oj") and not any(e["kind"] == "julkaistu" for e in ev):
                ev.append({"date": act["oj"][:10], "label": "Julkaistu EUVL:ssä", "kind": "julkaistu", "confirmed": True})
            eifs = act.get("eif", [])
            if eifs:
                ev.append({"date": eifs[0], "label": "Voimaan", "kind": "voimaan", "confirmed": True})
                for d in eifs[1:]:
                    ev.append({"date": d, "label": "Soveltaminen (vaihe)", "kind": "soveltaminen", "confirmed": True})
            for d in act.get("transposition", []):
                ev.append({"date": d, "label": "Täytäntöönpanon määräaika", "kind": "maaraaika", "confirmed": True})
            for d in act.get("deadlines", []):
                if d not in eifs and d not in act.get("transposition", []):
                    ev.append({"date": d, "label": "Säädöksen määräaika (esim. arviointi, siirtymäsäännös)", "kind": "maaraaika", "confirmed": True, "soft": True})
        ev = sorted({(e["date"], e["label"]): e for e in ev}.values(), key=lambda e: e["date"])
        if act:
            ref, kind = celex_ref(act["celex"])
            in_force = act.get("inForce") == "1"
            pending = any(is_future(e["date"]) and not e.get("soft") for e in ev)
            status = ("voimassa, soveltaminen vaiheittain" if pending else "voimassa") if in_force else "hyväksytty"
            done = bool(rec.get("final")) or (in_force and not pending)
            m = re.match(r"3(\d{4})([RLD])(\d{4})", act["celex"])
            source = f"https://eur-lex.europa.eu/eli/{ {'R':'reg','L':'dir','D':'dec'}[m.group(2)] }/{m.group(1)}/{int(m.group(3))}/oj" if m else None
        else:
            ref, kind = rec.get("ref", pid), "Ehdotus"
            status = "neuvotteluissa" if any(e["kind"] in ("sopu", "parlamentti") and e["label"].startswith(("Parlamentin", "Alustava")) for e in ev) else "komission ehdotus"
            done = False
            source = f"https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference={rec.get('ref', pid)}"
        if done:
            lastdate = max((e["date"] for e in ev), default=None)
            if lastdate and (days_ago(lastdate) or 0) > settings["completed"]["max_age_days"]:
                continue
        pc = c.get("proposal") or ""
        mpc = re.match(r"5(\d{4})PC(\d{4})", pc)
        items.append({"id": f"eu-{pid}", "scope": "eu", "laji": "eu", "pid": pid, "proposalCom": f"{mpc.group(1)}/{int(mpc.group(2))}" if mpc else None,
                      "kind": kind, "title": title[:160], "fullTitle": title,
                      "ref": ref, "procedure": rec.get("ref"), "topics": topics, "status": status, "done": done,
                      "summary": (rec.get("title_en") or ""), "source": source,
                      "links": {"oeil": f"https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference={rec.get('ref', pid)}",
                                **({"eurlex": source} if act else {})},
                      "events": ev, "celex": act["celex"] if act else None, "updated": rec.get("fetched")})
    return items


ICS_KINDS = {"voimaan": "Voimaan", "soveltaminen": "Soveltaminen", "maaraaika": "Määräaika", "lausunto": "Lausuntoaika päättyy"}


def build_ics(items: list[dict]) -> str:
    """All-day calendar events for upcoming deadlines (next 400 days), importable into any calendar."""
    def esc_(s):
        return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", " ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//saadosseuranta//FI", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:Säädösseuranta – määräajat", "X-WR-TIMEZONE:Europe/Helsinki"]
    lo, hi = (TODAY - dt.timedelta(days=7)).isoformat(), (TODAY + dt.timedelta(days=400)).isoformat()
    # DTSTAMP is required by RFC 5545; deriving it from the event date (instead of "now") keeps the
    # file byte-identical between runs unless a deadline actually changes, so git stays quiet.
    for it in items:
        for e in it["events"]:
            kind = e.get("kind")
            if kind not in ICS_KINDS:
                continue
            day = e.get("end") if kind == "lausunto" else e["date"]
            if not day or day < lo or day > hi:
                continue
            d = dt.date.fromisoformat(day)
            nxt = (d + dt.timedelta(days=1)).strftime("%Y%m%d")
            summary = f"[{'FI' if it['scope'] == 'fi' else 'EU'}] {ICS_KINDS[kind]}: {it['title']}"
            desc = f"{e.get('label', '')} · {it['ref']}" + (f" · {it['source']}" if it.get("source") else "")
            lines += ["BEGIN:VEVENT", f"UID:{it['id']}-{kind}-{day}@saadosseuranta", f"DTSTAMP:{d.strftime('%Y%m%d')}T000000Z",
                      f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{nxt}",
                      f"SUMMARY:{esc_(summary)}", f"DESCRIPTION:{esc_(desc)}"]
            if it.get("source"):
                lines.append(f"URL:{it['source']}")
            lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


CHANGE_KINDS = {"voimaan", "soveltaminen", "maaraaika", "lausunto", "he", "hyvaksytty", "vahvistettu", "julkaistu", "sopu"}


def compute_changes(old_items: list[dict], new_items: list[dict], day: str) -> list[dict]:
    """Diff two data sets into human-readable change rows (what the Tilannekuva 'Muutokset' panel shows)."""
    old = {i["id"]: i for i in old_items}
    old_lajit = {i.get("laji", "laki") for i in old_items}
    out = []

    def add(it, typ, text):
        out.append({"date": day, "id": it["id"], "scope": it["scope"], "title": it["title"], "type": typ, "text": text})

    def fmt(d):
        y, m, dd = d.split("-")
        return f"{int(dd)}.{int(m)}.{y}"

    for it in new_items:
        o = old.get(it["id"])
        if not o:
            if it.get("laji", "laki") in old_lajit:
                add(it, "uusi", f"Uusi: {it.get('kind', 'säädös')} ({it['status']})")
            continue
        if it.get("status") != o.get("status"):
            add(it, "tila", f"Tila: {o.get('status')} → {it.get('status')}")
        old_ev = {(e["date"], e.get("end"), e["label"]) for e in o.get("events", [])}
        old_by_label = {e["label"]: e for e in o.get("events", []) if e.get("kind") in CHANGE_KINDS}
        seen_labels = set()
        for e in it.get("events", []):
            if e.get("kind") not in CHANGE_KINDS:
                continue
            key = (e["date"], e.get("end"), e["label"])
            if key in old_ev:
                continue
            prev = old_by_label.get(e["label"])
            if prev and e["label"] not in seen_labels and (prev["date"] != e["date"] or prev.get("end") != e.get("end")):
                seen_labels.add(e["label"])
                if e.get("end") and prev.get("end"):
                    add(it, "siirto", f"{e['label']}: {fmt(prev['date'])}–{fmt(prev['end'])} → {fmt(e['date'])}–{fmt(e['end'])}")
                else:
                    add(it, "siirto", f"{e['label']}: {fmt(prev['date'])} → {fmt(e['date'])}")
            else:
                span = f" ({fmt(e['date'])}–{fmt(e['end'])})" if e.get("end") else f" ({fmt(e['date'])})"
                add(it, "vaihe", f"Uusi vaihe: {e['label']}{span}")
    return out


def update_changelog(new_items: list[dict], settings) -> list[dict]:
    prev_path = OUT_DIR / "items.json"
    log_path = OUT_DIR / "changes.json"
    old_items = load_json(prev_path, {"items": []}).get("items", [])
    log_rows = load_json(log_path, {"changes": []}).get("changes", [])
    day = TODAY.isoformat()
    fresh = compute_changes(old_items, new_items, day) if old_items else []
    keep_days = settings.get("changelog", {}).get("keep_days", 90)
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    existing = {(r["date"], r["id"], r["type"], r["text"]) for r in log_rows}
    merged = [r for r in log_rows if r["date"] >= cutoff] + [r for r in fresh if (r["date"], r["id"], r["type"], r["text"]) not in existing]
    merged.sort(key=lambda r: (r["date"], r["id"]), reverse=True)
    save_json(log_path, {"changes": merged}, compact=True)
    log(f"changelog: {len(fresh)} uutta muutosta, {len(merged)} lokissa")
    return merged


def apply_overrides(items: list[dict]):
    ov = load_json(CONFIG_DIR / "overrides.json", {})
    by_id = {i["id"]: i for i in items}
    for k, o in ov.items():
        if k.startswith("_") or k not in by_id:
            continue
        it = by_id[k]
        for f in ("topics", "summary", "title", "status"):
            if f in o:
                if f == "title":
                    it.setdefault("fullTitle", it["title"])
                it[f] = o[f]
        for e in o.get("events", []):
            e = dict(e)
            e.setdefault("confirmed", False)
            if not any(x["date"] == e["date"] and x["label"] == e["label"] for x in it["events"]):
                it["events"].append(e)
        it["events"].sort(key=lambda e: e["date"])


def main():
    settings = load_yaml(CONFIG_DIR / "settings.yaml")
    topics_cfg = load_yaml(CONFIG_DIR / "topics.yaml")["topics"]
    watch = load_yaml(CONFIG_DIR / "eu_watchlist.yaml") or {}
    fi = build_fi(topics_cfg, settings)
    asetukset = build_asetukset(topics_cfg, settings)
    eu = build_eu(topics_cfg, settings, watch)
    kirjelmat = attach_ue(eu, topics_cfg)
    kuulemiset = build_hys(topics_cfg, settings)
    items = fi + asetukset + eu + kirjelmat + kuulemiset
    # drop lapsed proposals older than 90 days and completed national items beyond max age
    keep = []
    for it in items:
        if it["status"] == "rauennut":
            continue
        if it["scope"] == "fi" and it["done"]:
            last = max((e["date"] for e in it["events"]), default=None)
            if last and (days_ago(last) or 0) > settings["completed"]["max_age_days"]:
                continue
        if it["scope"] == "fi" and not it["events"] and not settings["site"].get("show_items_without_dates", True):
            continue
        keep.append(it)
    apply_overrides(keep)
    changes = update_changelog(keep, settings)
    # Tenders live in their own file (docs/data/hankinnat.json): a different rhythm (hundreds of new
    # notices a week) and a different page segment. None written = previous file stays in place.
    hank = build_hankinnat(settings) or load_json(OUT_DIR / "hankinnat.json", {})
    open_now = [i for i in keep if i["scope"] == "fi" and i["status"] == "lausunnolla"]
    meta = {"generated": dt.datetime.now().isoformat(timespec="seconds"), "today": TODAY.isoformat(),
            "counts": {"fi": sum(i["scope"] == "fi" and not i["done"] for i in keep),
                       "eu": sum(i["scope"] == "eu" and not i["done"] for i in keep),
                       "done": sum(i["done"] for i in keep), "lausunnolla": len(open_now),
                       "changes7": sum(1 for r in changes if r["date"] >= (TODAY - dt.timedelta(days=7)).isoformat()),
                       "hankinnat": (hank.get("counts") or {}).get("avoinna", 0),
                       "hankinnat7": (hank.get("counts") or {}).get("sulkeutuu7", 0)},
            "topics": list(topics_cfg.keys()) + ["Muut"],
            "hankintaTopics": hank.get("topics") or [],
            # per-source health from update.py: the page warns when a source keeps failing
            "health": {k: {"ok": bool(v.get("ok", True)), "streak": int(v.get("streak", 0)), "last_ok": v.get("last_ok")}
                       for k, v in load_json(CACHE_DIR / "health.json", {}).items() if not k.startswith("_")},
            "lajit": {"laki": sum(i.get("laji") == "laki" for i in keep), "asetus": sum(i.get("laji") == "asetus" for i in keep),
                      "eu": sum(i.get("laji") == "eu" for i in keep), "kirjelma": sum(i.get("laji") == "kirjelma" for i in keep),
                      "kuuleminen": sum(i.get("laji") == "kuuleminen" for i in keep)},
            "sources": ["Valtioneuvoston Hankeikkuna (api.hankeikkuna.fi)", "Eduskunnan avoin data (avoindata.eduskunta.fi)",
                        "Finlex (finlex.fi)", "Euroopan parlamentin avoin data (data.europarl.europa.eu)",
                        "EU:n julkaisutoimiston Cellar (publications.europa.eu)", "Komission Have your say (ec.europa.eu)",
                        "Hilma – julkiset hankinnat (hankintailmoitukset.fi)"]}
    # Sanity gate: never publish an obviously broken data set (a source returning garbage would
    # otherwise wipe the page). Thresholds are deliberately low; adjust in settings.yaml.
    minimums = settings.get("sanity", {"fi": 100, "eu": 30, "done": 50})
    c = meta["counts"]
    if c["fi"] < minimums["fi"] or c["eu"] < minimums["eu"] or c["done"] < minimums["done"]:
        log(f"ERROR build: aineisto epäilyttävän pieni {c} (rajat {minimums}); items.json EI päivitetty")
        raise SystemExit(2)
    # items.json is deterministic (no timestamp) so git only records real content changes;
    # meta.json carries the run timestamp and counts.
    save_json(OUT_DIR / "items.json", {"items": keep}, compact=True)
    save_json(OUT_DIR / "meta.json", meta, compact=True)
    (OUT_DIR / "saadosseuranta.ics").write_text(build_ics(keep), encoding="utf-8")
    log(f"build: {c} -> {OUT_DIR / 'items.json'} + meta.json")


if __name__ == "__main__":
    main()
