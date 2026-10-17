"""KKV (Kilpailu- ja kuluttajavirasto): merger control cases.

Two public listings on kkv.fi, both server-rendered HTML (the site is WordPress; its news and
rulings are a custom post type that is not exposed through the REST API, so the pages are parsed):

* Vireillä olevat yrityskaupat – each case page states the notification date, the hearing
  deadline, the phase-1 deadline (23 working days, computed by KKV itself) and, for cases moved to
  an in-depth investigation, the phase-2 deadline (69 working days). We take KKV's own dates
  instead of recomputing working days.
* Päätökset kilpailuasioissa / yrityskauppavalvonta – decisions (approved as such, approved with
  conditions, prohibited, …) with date, parties and a summary that repeats the notification date.

Cache: data/cache/kkv.json keyed by the diaarinumero (KKV/1467/14.00.10/2026). Pending cases are
re-read every run (a handful of pages); decisions only when new.
"""
from __future__ import annotations

import datetime as dt
import html
import re

from common import CACHE_DIR, CONFIG_DIR, TODAY, http, load_json, load_yaml, log, save_json

PENDING = "https://www.kkv.fi/paatokset/vireilla-olevat-yrityskaupat/"
DECISIONS = "https://www.kkv.fi/paatokset/kilpailuasiat/yrityskauppavalvonta/"
OUT = CACHE_DIR / "kkv.json"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) saadosseuranta/1.0 (+https://github.com/EditMonster/Saadosseuranta)",
      "Accept": "text/html"}
ENTRY = re.compile(r'<h2 class="h3[^"]*"><a href="([^"]+)">(.*?)</a></h2>.*?<time datetime=([0-9-]+)>.*?<span class=entry__meta-info>\s*(.*?)\s*</span>', re.S)
DMY = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


def text_of(h: str) -> str:
    h = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    t = re.sub(r"<(br|/p|/h\d|/li|/div)[^>]*>", "\n", h)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t ]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def iso(dmy: str | None) -> str | None:
    m = DMY.search(dmy or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def field(t: str, label: str) -> str | None:
    """Value on the line after/with a label such as 'Ilmoitus saapunut' (KKV uses both 'Label: value' and 'Label\\nvalue')."""
    m = re.search(re.escape(label) + r"\s*:?\s*\n?\s*([^\n]+)", t, re.I)
    return m.group(1).strip() if m else None


def parse_case(url: str) -> dict:
    r = http("GET", url, headers=UA, timeout=60)
    r.raise_for_status()
    t = text_of(r.text)
    d = {"url": url}
    d["diaari"] = (field(t, "Diaarinumero") or "").strip() or None
    d["parties"] = (field(t, "Osapuolet") or "").strip() or None
    d["notified"] = iso(field(t, "Ilmoitus saapunut"))
    d["phase1End"] = iso(field(t, "Ensimmäisen vaiheen määräaika"))
    d["hearingEnd"] = iso(field(t, "Kuulemisen määräaika"))
    d["phase2Start"] = iso(field(t, "Siirretty jatkoselvitykseen") or field(t, "Siirretty jatkokäsittelyyn"))
    d["phase2End"] = iso(field(t, "Jatkoselvityksen määräaika") or field(t, "Jatkokäsittelyn määräaika"))
    d["decided"] = iso(field(t, "Päivämäärä"))
    # summary: KKV's own tiivistelmä, else the notifier's description of the transaction
    m = re.search(r"Tiivistelmä\s*\n(.+?)(?:\s*\n\s*(?:Julkinen versio|Päätös|Lue lisää|Tiedote|Tulosta|Tallenna)|\Z)", t, re.S)
    if not m:
        # the notifier's description: first paragraphs after the "Ilmoittajan näkemys" heading
        m = re.search(r"Ilmoittajan näkemys yrityskaupasta\s*\n(?:\s*(?:\d[.)]?\s*)?Yrityskaupp[^\n]{0,40}\n)?(.+?)(?:\n\s*(?:\d[.)]?\s+)?[A-ZÄÖ][^\n]{3,60}\n|\Z)", t, re.S)
    summary = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    summary = re.sub(r"\s*\((?:jäljempänä\s*)?[”“\"][^)]*\)", "", summary)  # drop the defined-term parentheses
    summary = re.sub(r"\s*\[\d+\]", "", summary)  # footnote markers
    summary = re.sub(r"\s*(Julkinen versio päätöksestä|Lue lisää|Tulosta|Tallenna pdf)\s*$", "", summary)
    summary = re.sub(r"[”“\"]\s*", "", summary)
    # keep whole sentences up to ~600 characters
    if len(summary) > 600:
        cut = summary[:600]
        summary = cut[:cut.rfind(". ") + 1] if ". " in cut[200:] else cut.rstrip() + "…"
    d["summary"] = summary
    if not d["notified"]:
        m = re.search(r"ilmoitettiin(?: on)?\s+(\d{1,2}\.\d{1,2}\.\d{4})", t)
        d["notified"] = iso(m.group(1)) if m else None
    return d


def listing(url: str, pages: int) -> list[dict]:
    out = []
    for page in range(1, pages + 1):
        r = http("GET", url, params={"sivu": page} if page > 1 else None, headers=UA, timeout=60)
        r.raise_for_status()
        found = ENTRY.findall(r.text)
        for link, title, date, status in found:
            out.append({"url": link, "title": html.unescape(re.sub(r"<[^>]+>", "", title)).strip(), "date": date,
                        "status": html.unescape(status).strip()})
        if len(found) < 10:
            break
    return out


def main():
    settings = load_yaml(CONFIG_DIR / "settings.yaml").get("yrityskaupat", {})
    keep_days = int(settings.get("keep_decided_days", 90))
    old = load_json(OUT, {"cases": {}})
    cases: dict[str, dict] = dict(old.get("cases") or {})
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()

    pending = listing(PENDING, 3)
    fetched_pending = set()
    for p in pending:
        try:
            d = parse_case(p["url"])
        except Exception as e:  # noqa: BLE001
            log(f"warn: kkv {p['url']}: {e}")
            continue
        key = d.get("diaari") or p["url"]
        d.update({"listTitle": re.sub(r"\s*\(kuuleminen.*?\)\s*$", "", p["title"]), "listDate": p["date"], "listStatus": p["status"],
                  "pending": True, "seen": TODAY.isoformat()})
        d.pop("decided", None)
        prev = cases.get(key, {})
        cases[key] = {**prev, **{k: v for k, v in d.items() if v is not None}, "pending": True}
        cases[key].pop("decision", None)
        fetched_pending.add(key)

    decisions = listing(DECISIONS, 4)
    new_dec = 0
    for p in decisions:
        if p["date"] < cutoff:
            continue
        # interim entries ("jatkoselvitykseen ryhtyminen", "Esitys markkinaoikeudelle") move the case on but do not close it
        interim = "jatkoselvityks" in p["status"].lower() or "markkinaoikeu" in p["status"].lower()
        if any(v.get("decisionUrl") == p["url"] or (p["url"] in (v.get("interim") or {}).values()) for v in cases.values()):
            continue
        try:
            d = parse_case(p["url"])
        except Exception as e:  # noqa: BLE001
            log(f"warn: kkv {p['url']}: {e}")
            continue
        key = d.get("diaari") or p["url"]
        prev = cases.get(key, {})
        if interim:
            merged = {**prev, **{k: v for k, v in d.items() if v is not None and not prev.get(k)}}
            kind = "jatkokäsittely" if "jatkoselvityks" in p["status"].lower() else "kieltoesitys"
            merged.setdefault("interim", {})[kind] = p["url"]
            merged.setdefault("interimDates", {})[kind] = d.get("decided") or p["date"]
            if kind == "jatkokäsittely" and not merged.get("phase2Start"):
                merged["phase2Start"] = d.get("decided") or p["date"]
            merged["pending"] = bool(prev.get("pending", True)) if key in fetched_pending else prev.get("pending", kind == "kieltoesitys")
            merged.pop("decided", None) if merged.get("pending") else None
            if key not in fetched_pending and kind == "kieltoesitys":
                merged["pending"] = True  # in the Market Court: still open for our purposes
            merged.update({"listTitle": merged.get("listTitle") or p["title"], "url": merged.get("url") or p["url"], "seen": TODAY.isoformat()})
            cases[key] = merged
            new_dec += 1
            continue
        merged = {**prev, **{k: v for k, v in d.items() if v is not None}}
        merged.update({"listTitle": p["title"], "decision": p["status"], "decided": d.get("decided") or p["date"], "pending": False,
                       "decisionUrl": p["url"], "seen": TODAY.isoformat()})
        if prev.get("url") and prev.get("url") != p["url"]:
            merged["url"] = prev["url"]  # keep the pending-case page (richer dates); decision page in decisionUrl
        cases[key] = merged
        new_dec += 1

    # A case that was pending last run but is no longer listed and has no decision: mark as no longer pending
    # (a case sent to the Market Court by a prohibition proposal stays open until the court rules)
    for k, v in cases.items():
        if v.get("pending") and k not in fetched_pending and "kieltoesitys" not in (v.get("interim") or {}):
            v["pending"] = False
            v.setdefault("missingSince", TODAY.isoformat())
    # forget old decided/missing cases
    cases = {k: v for k, v in cases.items() if v.get("pending") or (v.get("decided") or v.get("missingSince") or "9999") >= cutoff}
    if not pending and not decisions:
        raise RuntimeError("KKV: listaukset tyhjiä – sivuston rakenne on ehkä muuttunut")
    save_json(OUT, {"fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "cases": cases})
    log(f"kkv: {len(fetched_pending)} vireillä olevaa yrityskauppaa, {new_dec} uutta päätöstä, {len(cases)} tapausta välimuistissa -> {OUT}")


if __name__ == "__main__":
    main()
