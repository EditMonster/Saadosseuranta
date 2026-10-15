"""Turn the Hilma cache into docs/data/hankinnat.json: one compact row per open tender with the
time left to bid, a short extractive summary of what is being procured, and the link to the
original notice. Rules that matter:

* only notices with a bid/participation deadline; cancelled notices are dropped;
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

    raw = cache["items"]
    superseded = {pid for n in raw for pid in (n.get("previousSearchIds") or [])}
    rows, by_id = [], {}
    dropped = {"peruttu": 0, "ei määräaikaa": 0, "korvattu": 0}
    for n in raw:
        if n.get("isCancelled"):
            dropped["peruttu"] += 1
            continue
        if not n.get("deadline"):
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
        row = {
            "id": f"hk-{n['id']}", "scope": "hankinta", "laji": "kilpailutus",
            "kind": types.get(str(n.get("type")), "Hankintailmoitus"),
            "title": title[:220], "buyer": _lang(n, "organisationName")[:160] or None,
            "buyerId": n.get("organisationNationalRegistrationNumber") or None,
            "deadline": n["deadline"], "deadlineKind": "osallistumishakemus" if (proc in part or dps) else "tarjous",
            "published": (n.get("datePublished") or "")[:10] or None,
            "procedure": procs.get(proc, proc or None), "nature": nature,
            "cpv": cpv or None, "cpvLabel": labels.get(cpv) or None, "topics": topics,
            "value": value, "currency": cur if value else None,
            "eu": bool(n.get("isEuProcurement")), "small": bool(n.get("isNationalSmallValueProcurement")),
            "framework": bool(n.get("includesFrameworkAgreement")), "dps": dps,
            "corrigendum": bool(n.get("isCorrigendum")), "lots": len(lots) if len(lots) > 1 else 0,
            "lotTitles": [clean(_lang(l, "title"))[:90] for l in lots[:8]] if len(lots) > 1 else [],
            "summary": summarise(title, desc, lots, scfg),
            "url": notice_url(n), "docsUrl": n.get("procurementDocumentsUrl") or None,
            "tedUrl": f"https://ted.europa.eu/fi/notice/-/detail/{ted}" if ted else None,
            "noticeNumber": n.get("noticeNumber") or None, "status": "avoin",
        }
        row = {k: v for k, v in row.items() if v not in (None, "", [], False, 0)} | {"status": "avoin"}
        rows.append(row)
        by_id[row["id"]] = row

    # Carry over what vanished since the previous build (deadline passed or withdrawn)
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    carried = 0
    for o in prev_items:
        if o["id"] in by_id or (o.get("deadline") or "")[:10] < cutoff:
            continue
        o = dict(o)
        o["status"] = "päättynyt" if o.get("deadline", "") < now else "poistunut"
        rows.append(o)
        carried += 1
    rows.sort(key=lambda r: (r.get("deadline") or "", r["id"]))
    open_rows = [r for r in rows if r["status"] == "avoin" and r["deadline"] > now]
    soon = (TODAY + dt.timedelta(days=7)).isoformat()
    counts = {"avoinna": sum(1 for r in open_rows if not r.get("dps")), "dps": sum(1 for r in open_rows if r.get("dps")),
              "sulkeutuu7": sum(1 for r in open_rows if not r.get("dps") and r["deadline"][:10] <= soon),
              "eu": sum(1 for r in open_rows if r.get("eu") and not r.get("dps"))}
    payload = {"items": rows, "counts": counts, "topics": list((cfg.get("toimialat") or {}).keys()) + ["Muut"]}
    minimum = int(hcfg.get("min_items", 100))
    if len(open_rows) < minimum and len(prev_items) >= minimum:
        log(f"ERROR hankinnat: vain {len(open_rows)} avointa (raja {minimum}); edellinen hankinnat.json säilytetään")
        return None
    save_json(OUT, payload, compact=True)
    log(f"hankinnat: {counts} + {carried} säilytettyä; pudotettu {dropped} -> {OUT}")
    return payload


if __name__ == "__main__":
    build_hankinnat(load_yaml(CONFIG_DIR / "settings.yaml"))
