"""Turn the Hilma cache into docs/data/hankinnat.json: one compact row per notice across the whole
procurement lifecycle – stage "tulossa" (prior information / market consultation), "avoin" (open
tender: time left to bid), "ratkaistu" (award notice: winner, value) and "suorahankinta" (ex-ante
transparency notice: exact 14-day appeal window) – with a short extractive summary of what is being
procured, the link to the original notice, and the other notices of the same procedure linked
together as one timeline. Rules that matter:

* open tenders need a bid/participation deadline; cancelled notices are dropped;
* a corrigendum replaces the notice it corrects (Hilma lists both; the old one is dropped);
* dynamic purchasing systems (DPS) are kept but flagged – their "deadline" is the end of the
  system's validity, often years away, and the page hides them behind a toggle;
* notices that disappeared from Hilma or whose deadline passed are carried over from the
  previous published file for a couple of weeks with status "päättynyt"/"poistunut".
"""
from __future__ import annotations

import datetime as dt
import re

from common import CACHE_DIR, CONFIG_DIR, OUT_DIR, TODAY, load_json, load_yaml, log, save_json
from build_mao import mao_rows

CACHE = CACHE_DIR / "hankinnat.json"
OUT = OUT_DIR / "hankinnat.json"
HILMA = "https://www.hankintailmoitukset.fi/fi/public"
_WS = re.compile(r"[ \t ]+")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÅ0-9\"'(])|\n+")
_KOHDE = re.compile(r"(hankinnan kohteena|hankinnan kohde on|hankinta käsittää|hankinta koskee|hankinta sisältää|"
                    r"urakka käsittää|urakkaan kuuluu|pyytää tarjou|pyydämme tarjou|kilpailuttaa|tarkoituksena on hankkia|"
                    r"hankitaan|kohteena on|tarjouspyyntö koskee|osallistumishakemuksia|perustaa dynaamisen)", re.I)


def _cfg():
    c = load_yaml(CONFIG_DIR / "hankinnat.yaml")
    prefixes = []
    for name, codes in (c.get("toimialat") or {}).items():
        for p in codes:
            prefixes.append((str(p), name))
    prefixes.sort(key=lambda x: -len(x[0]))  # longest prefix wins
    return c, prefixes


def category(cpv: str, prefixes) -> str | None:
    code = (cpv or "").strip()
    for p, name in prefixes:
        if code.startswith(p):
            return name
    return None


def clean(text: str) -> str:
    t = (text or "").replace("\r", "\n")
    t = _WS.sub(" ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip(" \n,;:-–")


def summarise(title: str, desc: str, lots: list[dict], cfg: dict) -> str:
    """Extractive summary: drop the repeated title, skip boilerplate, start from the sentence that
    says what is procured, stop at max_merkkia on a word boundary."""
    limit = int(cfg.get("max_merkkia", 420))
    skip = [s.lower() for s in cfg.get("ohita", [])]
    text = clean(desc)
    t = clean(title)
    if t and text.lower().startswith(t.lower()):
        text = text[len(t):].lstrip(" \n,.:;–-")
    sents = [s.strip() for s in _SENT.split(text) if s and s.strip()]
    sents = [s for s in sents if len(s) > 2 and not any(k in s.lower() for k in skip)]
    if not sents:
        if lots and len(lots) > 1:
            names = [clean(l.get("titleFi") or l.get("titleSv") or l.get("titleEn") or "") for l in lots]
            names = [n for n in names if n]
            if names:
                return ("Osat: " + "; ".join(names[:8]) + ("…" if len(names) > 8 else ""))[:limit]
        return ""
    start = next((i for i, s in enumerate(sents[:6]) if _KOHDE.search(s)), 0)
    out = ""
    for s in sents[start:]:
        cand = (out + " " + s).strip()
        if len(cand) > limit:
            if not out:
                cut = cand[:limit]
                cut = cut[:cut.rfind(" ")] if " " in cut[limit // 2:] else cut
                out = cut.rstrip(" ,;:(–-") + "…"
            break
        out = cand
        if len(out) >= limit * 0.6 and out.endswith((".", "!", "?")):
            break
    return out


def _lang(n: dict, base: str) -> str:
    return (n.get(base + "Fi") or n.get(base + "Sv") or n.get(base + "En") or n.get(base + "Other") or "").strip()


def notice_url(n: dict) -> str:
    if n.get("isEForms") and n.get("procedureId"):
        return f"{HILMA}/procedure/{n['procedureId']}/enotice/{n['noticeId']}"
    if n.get("oldProcurementProjectId"):
        return f"{HILMA}/procurement/{n['oldProcurementProjectId']}/notice/{n['noticeId']}/overview"
    return f"https://www.hankintailmoitukset.fi/fi/search?q={n.get('noticeNumber') or n.get('noticeId')}"


def build_hankinnat(settings) -> dict | None:
    """Returns the payload written to docs/data/hankinnat.json, or None when nothing was written."""
    cfg, prefixes = _cfg()
    hcfg = settings.get("hankinnat", {})
    keep_days = int(hcfg.get("keep_closed_days", 14))
    cache = load_json(CACHE, None)
    prev = load_json(OUT, {"items": []})
    prev_items = prev.get("items", [])
    if not cache or not cache.get("items"):
        log("hankinnat: ei tuoretta Hilma-hakua, edellinen hankinnat.json säilytetään")
        return None
    fetched = (cache.get("fetched") or "")[:10]
    if fetched and fetched < (TODAY - dt.timedelta(days=2)).isoformat():
        log(f"hankinnat: välimuisti on vanha ({fetched}), edellinen hankinnat.json säilytetään")
        return None
    labels = load_json(CACHE_DIR / "cpv.json", {}).get("labels", {})
    types = {str(k): v for k, v in (cfg.get("tyypit") or {}).items()}
    procs = cfg.get("menettelyt") or {}
    natures = cfg.get("hankintalajit") or {}
    part = set(cfg.get("osallistumishakemus") or [])
    scfg = cfg.get("tiivistelma") or {}
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    direct_types = {str(x) for x in (cfg.get("suorahankinta_tyypit") or [])}
    appeal_days = int(cfg.get("valitusaika_paivia", 14))
    award_days = int(hcfg.get("award_days", 30))

    def stage_of(n: dict) -> str:
        if str(n.get("type")) in direct_types:
            return "suorahankinta"
        mt = n.get("mainType") or ""
        if mt == "ContractAwardNotices":
            return "ratkaistu"
        if mt == "PriorInformationNotices":
            return "tulossa"
        return "avoin"

    raw = cache["items"]
    superseded = {pid for n in raw for pid in (n.get("previousSearchIds") or [])}
    rows, by_id = [], {}
    dropped = {"peruttu": 0, "ei määräaikaa": 0, "korvattu": 0}
    for n in raw:
        stage = stage_of(n)
        if n.get("isCancelled"):
            dropped["peruttu"] += 1
            continue
        if stage == "avoin" and not n.get("deadline"):
            dropped["ei määräaikaa"] += 1
            continue
        if n.get("id") in superseded:
            dropped["korvattu"] += 1
            continue
        title = _lang(n, "title") or "(nimetön ilmoitus)"
        desc = n.get("descriptionFi") or n.get("descriptionAlt") or ""
        lots = n.get("lots") or []
        codes = [c for c in re.split(r"[\s,;]+", n.get("cpvCodes") or "") if c]
        for lot in lots:
            codes += [c for c in re.split(r"[\s,;]+", lot.get("cpvCodes") or "") if c]
        cpv = codes[0] if codes else ""
        cats = []
        for code in codes:
            c = category(code, prefixes)
            if c and c not in cats:
                cats.append(c)
        topics = cats[:3] or ["Muut"]
        proc = (n.get("procedureType") or "").strip()
        dps = bool(n.get("includesDynamicPurcharingSystem"))
        nature = " ja ".join(natures.get(x, x) for x in (n.get("procurementTypeCode") or "").split() if x) or None
        value = n.get("estimatedValue")
        cur = n.get("currency")
        if not value and len(lots) == 1 and lots[0].get("estimatedValue"):
            value, cur = lots[0]["estimatedValue"], lots[0].get("currency")
        ted = n.get("tedPublicationId")
        published = (n.get("datePublished") or "")[:10] or None
        appeal_end = None
        if stage == "suorahankinta" and published:
            appeal_end = (dt.date.fromisoformat(published) + dt.timedelta(days=appeal_days)).isoformat()
        winner = (n.get("winnerOrganisations") or "").strip() or None
        amount = n.get("noticeResultTotalAmount")
        if stage == "ratkaistu" and not amount:
            lot_amounts = [l.get("lotResultTotalAmount") for l in lots if l.get("lotResultTotalAmount")]
            amount = sum(lot_amounts) if lot_amounts else None
        row = {
            "id": f"hk-{n['id']}", "scope": "hankinta", "laji": "kilpailutus", "stage": stage,
            "kind": types.get(str(n.get("type")), {"tulossa": "Ennakkoilmoitus", "ratkaistu": "Jälki-ilmoitus",
                                                 "suorahankinta": "Suorahankintailmoitus"}.get(stage, "Hankintailmoitus")),
            "title": title[:220], "buyer": _lang(n, "organisationName")[:160] or None,
            "buyerId": n.get("organisationNationalRegistrationNumber") or None,
            "deadline": n.get("deadline") if stage in ("avoin", "tulossa") else None,
            "deadlineKind": ("vastaus" if stage == "tulossa" else ("osallistumishakemus" if (proc in part or dps) else "tarjous")),
            "appealEnd": appeal_end, "winner": winner[:200] if winner else None,
            "amount": amount, "amountCurrency": (n.get("noticeResultTotalAmountCurrency") or "EUR") if amount else None,
            "expires": (n.get("expirationDate") or "")[:10] or None,
            "procKey": (f"p{n['procedureId']}" if n.get("procedureId") else (f"o{n['oldProcurementProjectId']}" if n.get("oldProcurementProjectId") else None)),
            "published": published,
            "procedure": procs.get(proc, proc or None), "nature": nature,
            "cpv": cpv or None, "cpvLabel": labels.get(cpv) or None, "topics": topics,
            "value": value, "currency": cur if value else None,
            "eu": bool(n.get("isEuProcurement")), "small": bool(n.get("isNationalSmallValueProcurement")),
            "framework": bool(n.get("includesFrameworkAgreement")), "dps": dps,
            "corrigendum": bool(n.get("isCorrigendum")), "lots": len(lots) if len(lots) > 1 else 0,
            "lotTitles": [clean(_lang(l, "title"))[:90] for l in lots[:8]] if len(lots) > 1 else [],
            "summary": summarise(title, desc, lots, scfg if stage == "avoin" else {**scfg, "max_merkkia": 300}),
            "url": notice_url(n), "docsUrl": n.get("procurementDocumentsUrl") or None,
            "tedUrl": f"https://ted.europa.eu/fi/notice/-/detail/{ted}" if ted else None,
            "noticeNumber": n.get("noticeNumber") or None,
        }
        # status per stage: avoin/tulossa live until their deadline, suorahankinta until the appeal window closes
        keep_from = (TODAY - dt.timedelta(days=keep_days)).isoformat()
        if stage == "avoin":
            status = "avoin"
        elif stage == "tulossa":
            dl = (n.get("deadline") or "")[:10]
            if dl and dl < keep_from:
                continue
            status = "tulossa" if (not dl or dl >= TODAY.isoformat()) else "päättynyt"
        elif stage == "suorahankinta":
            if not appeal_end or appeal_end < keep_from:
                continue
            status = "valitusaika" if appeal_end >= TODAY.isoformat() else "päättynyt"
        else:
            status = "ratkaistu"
            row["lotTitles"] = []
        row = {k: v for k, v in row.items() if v not in (None, "", [], False, 0)} | {"status": status}
        rows.append(row)
        by_id[row["id"]] = row

    # Carry over open tenders that vanished since the previous build (deadline passed or withdrawn)
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    carried = 0
    for o in prev_items:
        if o["id"] in by_id or o.get("stage", "avoin") != "avoin" or (o.get("deadline") or "")[:10] < cutoff:
            continue
        o = dict(o)
        o["stage"] = "avoin"
        o["status"] = "päättynyt" if o.get("deadline", "") < now else "poistunut"
        o.pop("events", None)
        o.pop("related", None)
        rows.append(o)
        by_id[o["id"]] = o
        carried += 1

    # Lifecycle: notices of the same procedure share one timeline and link to each other
    by_proc: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("procKey"):
            by_proc.setdefault(r["procKey"], []).append(r)
    for r in rows:
        group = sorted(by_proc.get(r.get("procKey") or "", [r]), key=lambda x: x.get("published") or "")
        ev = []
        for g in group:
            st, pub = g.get("stage", "avoin"), g.get("published")
            if not pub:
                continue
            if st == "tulossa":
                if g.get("deadline"):
                    ev.append({"date": pub, "end": g["deadline"][:10], "label": "Markkinakartoitus – vastaukset", "kind": "lausunto"})
                else:
                    ev.append({"date": pub, "label": g.get("kind", "Ennakkoilmoitus") + " julkaistu", "kind": "ehdotus"})
            elif st == "avoin":
                ev.append({"date": pub, "label": "Hankintailmoitus julkaistu", "kind": "he"})
                if g.get("deadline"):
                    ev.append({"date": g["deadline"][:10], "label": ("Osallistumishakemukset" if g.get("deadlineKind") == "osallistumishakemus" else "Tarjoukset") + " viimeistään", "kind": "maaraaika"})
            elif st == "ratkaistu":
                ev.append({"date": pub, "label": "Jälki-ilmoitus julkaistu" + (f" – {g['winner'][:60]}" if g.get("winner") else ""), "kind": "hyvaksytty"})
            elif st == "suorahankinta":
                ev.append({"date": pub, "label": "Suorahankinnan ilmoitus julkaistu", "kind": "julkaistu"})
                if g.get("appealEnd"):
                    ev.append({"date": g["appealEnd"], "label": "Valitusaika päättyy (14 pv julkaisusta)", "kind": "maaraaika"})
        ev.sort(key=lambda e: (e["date"], e.get("end") or ""))
        r["events"] = ev
        rel = [{"id": g["id"], "stage": g.get("stage", "avoin"), "kind": g.get("kind"), "published": g.get("published")} for g in group if g["id"] != r["id"]]
        if rel:
            r["related"] = rel

    # Market Court appeals and rulings (stage "mao"), linked to the Hilma notices they concern
    try:
        mao = mao_rows(settings, rows, cfg)
    except Exception as e:  # noqa: BLE001
        log(f"warn: markkinaoikeuden rivit ohitettu: {e}")
        mao = []
    rows.extend(mao)

    def sort_key(r):
        st = r.get("stage", "avoin")
        key = r.get("deadline") or r.get("appealEnd") or r.get("expires") or ""
        if st in ("ratkaistu", "mao"):
            key = "~" + (r.get("published") or "")  # newest decided last in ascending order; page sorts desc
        return (key, r["id"])
    rows.sort(key=sort_key)
    open_rows = [r for r in rows if r["status"] == "avoin" and r.get("deadline", "") > now]
    soon = (TODAY + dt.timedelta(days=7)).isoformat()
    counts = {"avoinna": sum(1 for r in open_rows if not r.get("dps")), "dps": sum(1 for r in open_rows if r.get("dps")),
              "sulkeutuu7": sum(1 for r in open_rows if not r.get("dps") and r["deadline"][:10] <= soon),
              "eu": sum(1 for r in open_rows if r.get("eu") and not r.get("dps")),
              "tulossa": sum(1 for r in rows if r["status"] == "tulossa"),
              "ratkaistu": sum(1 for r in rows if r["status"] == "ratkaistu"),
              "suorahankinta": sum(1 for r in rows if r["status"] == "valitusaika"),
              "mao": sum(1 for r in mao if r["status"] == "vireillä"), "mao_ratkaistu": sum(1 for r in mao if r["status"] == "ratkaistu")}
    payload = {"items": rows, "counts": counts, "topics": list((cfg.get("toimialat") or {}).keys()) + ["Muut"],
               "awardDays": award_days, "appealDays": appeal_days}
    minimum = int(hcfg.get("min_items", 100))
    if len(open_rows) < minimum and len(prev_items) >= minimum:
        log(f"ERROR hankinnat: vain {len(open_rows)} avointa (raja {minimum}); edellinen hankinnat.json säilytetään")
        return None
    save_json(OUT, payload, compact=True)
    log(f"hankinnat: {counts} + {carried} säilytettyä; pudotettu {dropped} -> {OUT}")
    return payload


if __name__ == "__main__":
    build_hankinnat(load_yaml(CONFIG_DIR / "settings.yaml"))
