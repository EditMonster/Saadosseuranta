"""Municipal procurement decisions (hankintapäätökset) – Helsinki, optionally Oulu.

Helsinki publishes every decision of the city (Ahjo) on paatokset.hel.fi. The site's search is a
React app backed by an open Elasticsearch proxy (no auth):

    POST https://paatokset-elastic-proxy.api.hel.ninja/paatokset_decisions/_search

Every value in a document's _source is a one-element list. We ask for decisions (field_is_decision)
of the last ``days`` whose Ahjo category is a procurement one ("Kilpailutus", "Hankinta ilman
kilpailutusta") or whose issue subject follows the Ahjo convention "Hankinta, …", and read from the
decision text (decision_content, HTML): the winner(s) and excluded tenderers, the VAT-exclusive
amount, Hilma/Cloudia references (HEL yyyy-nnnnnn, tarjouspyyntö nro), the notice date, and the
kind of decision (award, DPS admission, interruption, additional work order, …). The decision page
itself is fetched once per new decision for the parts the index does not carry: the appeal
instructions ("VALITUSOSOITUS MARKKINAOIKEUDELLE", hankintaoikaisu) and the date the decision was
made public ("Päätös tullut nähtäväksi").

Oulu (Tweb RSS of officeholder decisions, latin-1) is behind ``paatokset.oulu`` and off by default;
its items state the tiedoksiantoaika, which Helsinki's do not.

Cache: data/cache/paatokset.json {fetched, decisions: {id: {...}}, health}; the id is the Ahjo
decision GUID (lower case, no braces), Oulu ids are "oulu-<docid>". Decisions older than
``keep_days`` are dropped.
"""
from __future__ import annotations

import datetime as dt
import html
import re
import time

from common import CACHE_DIR, CONFIG_DIR, TODAY, http, load_json, load_yaml, log, post_json, save_json
from fetch_mao import iso, text_of

ES = "https://paatokset-elastic-proxy.api.hel.ninja/paatokset_decisions/_search"
SITE = "https://paatokset.hel.fi"
OULU_RSS = "https://asiakirjat.ouka.fi/ktwebscr/vpar_rssfeed.htm?text=&vin=&1009_2615=&1009_2606=&1009_2607="
OUT = CACHE_DIR / "paatokset.json"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) saadosseuranta/1.0 (+https://github.com/EditMonster/Saadosseuranta)"}
CATEGORIES = ("Kilpailutus", "Hankinta ilman kilpailutusta")
FIELDS = ["id", "unique_issue_id", "issue_subject", "subject", "organization_name", "organization_above_name", "organization_type",
          "meeting_date", "field_is_decision", "field_decision_section", "decision_url", "decision_content", "decision_motion", "category_name"]

# --- text patterns -------------------------------------------------------------------------------
FORM = r"(?:Oy\s+Ab|Ab\s+Oy|Oyj\s+Abp|Oyj|Oy|Ab|Abp|Ky|Osk|ry|rf|sr|OÜ|Oü|AS|A/S|ApS|AB|GmbH|Ltd\.?|Limited|Inc\.?|Plc|S\.A\.|SE|B\.V\.|BV|säätiö)"
TOKEN = r"[A-ZÅÄÖ0-9][\w&'’.]*(?:-[\w&'’.]+)*"
NAME = rf"{TOKEN}(?:\s+(?:{TOKEN}|ja|and|of|de|&))*"
COMPANY = re.compile(rf"\b({NAME}\s+{FORM})(?=[\s,.;:()\-]|$)")
YTUNNUS = re.compile(r"\(?\s*(?:[Yy]-tunnus\s*:?\s*)?(\d{7}-\d)\s*\)?")
LEAD = ("Palveluntuottaja", "Toimittaja", "Tarjoaja", "Urakoitsija", "Konsultti", "Yritys", "Osa-alue", "Ryhmä", "Päiväkoti", "Kohde", "Hankinta")
EXCLUDE_CATEGORIES = ("Pankkipalveluiden hallinta",)  # payment cards are filed under "Hankinta, …" too
LOSS = re.compile(r"sulke|sulje|hylk|poissulk|ei täyt|tarjouskilpailusta|ei valit", re.I)
WIN = re.compile(r"hyväksy|valit|tila(?:ta|si|a)|hankk|jatka|korott|otetaan käyttöön|sopimus tehdään|toimittaja on", re.I)
AMOUNT = re.compile(r"(\d{1,3}(?:[ . ]\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*euro")
VAT = re.compile(r"arvonlisäverot|alv\.?\s*0|alv 0|veroton", re.I)
HEL = re.compile(r"HEL[\s-]?(\d{4})-(\d{6})")
CLOUDIA = re.compile(r"(?:tarjouspyyn\w*|kilpailutus\w*|osallistumispyyn\w*)\s*(?:nro\.?|numero|n:o|tunnus)?\s*:?\s*#?(\d{5,7})\b", re.I)
NOTICE = re.compile(r"hankintailmoitu\w*[^.\n]{0,80}?(\d{1,2}\.\d{1,2}\.\d{4})", re.I)
RFQ_DATE = re.compile(r"(\d{1,2}\.\d{1,2}\.\d{4})\s+päivät\w+\s+(?:tarjouspyyn|osallistumispyyn)", re.I)
DMY = re.compile(r"\d{1,2}\.\d{1,2}\.\d{4}")
OULU_KW = re.compile(r"hankin|urakoitsijavalin|toimittajan valin|tarjou|kilpailut|puitesopimu|puitejärjest|suorahank|optio", re.I)


def _one(src: dict, key: str, default=None):
    v = src.get(key)
    if isinstance(v, list):
        return v[0] if v else default
    return v if v is not None else default


def epoch_date(epoch) -> str | None:
    """meeting_date (epoch seconds, UTC) -> Helsinki calendar date."""
    try:
        t = dt.datetime.fromtimestamp(int(epoch), dt.timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    try:
        from zoneinfo import ZoneInfo
        return t.astimezone(ZoneInfo("Europe/Helsinki")).date().isoformat()
    except Exception:  # noqa: BLE001 – no tz database: Finland is UTC+2/+3, meetings are daytime
        return (t + dt.timedelta(hours=2)).date().isoformat()


def sections(content_html: str) -> dict[str, str]:
    """{'Päätös': text, 'Päätöksen perustelut': text, …} from the Ahjo HTML; the first occurrence of a heading wins."""
    out: dict[str, str] = {}
    parts = re.split(r'<h3 class="SisaltoOtsikko"[^>]*>(.*?)</h3>', content_html or "")
    for i in range(1, len(parts) - 1, 2):
        head = html.unescape(re.sub(r"<[^>]+>", "", parts[i])).strip()
        out.setdefault(head, text_of(parts[i + 1]))
    if not out and content_html:
        out["Päätös"] = text_of(content_html)
    return out


def clean_name(name: str) -> str:
    n = re.sub(r"\s+", " ", name).strip(" ,.;:-–")
    n = re.sub(r"^(?:\d{1,2}\.\d{1,2}\.\d{4}\s*|\d{1,2}[.)]\s*|[•·*\-–]\s*)+", "", n)  # list numbers, bullets, dates
    for w in LEAD:
        if n.startswith(w + " ") and len(n.split()) > 2:
            n = n[len(w) + 1:]
    return n


def companies(text: str) -> list[tuple[str, str | None]]:
    """[(name, y-tunnus|None)] in order of appearance, deduplicated."""
    out, seen = [], set()
    for m in COMPANY.finditer(text or ""):
        name = clean_name(m.group(1))
        key = name.lower()
        if key in seen or len(name) < 4:
            continue
        seen.add(key)
        tail = text[m.end():m.end() + 40]
        ym = YTUNNUS.match(tail.lstrip(" :n"))
        out.append((name, ym.group(1) if ym else None))
    return out


def winners_losers(paatos: str) -> tuple[list[dict], list[dict]]:
    """Companies named in the operative part, split by the verb of the line they appear on; list items
    without a verb inherit the previous line's class (numbered winner lists, bullet lists)."""
    winners, losers, seen = [], [], set()
    mode = "win"
    for line in (paatos or "").split("\n"):
        if LOSS.search(line):
            mode = "loss"
        elif WIN.search(line):
            mode = "win"
        if not LOSS.search(line) and not WIN.search(line) and len(line.strip()) > 120:
            continue  # a long sentence without a verb only mentions a company (e.g. the other buyer of a joint procurement)
        for name, yt in companies(line):
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            entry = {"name": name} | ({"yTunnus": yt} if yt else {})
            (losers if mode == "loss" else winners).append(entry)
    return winners[:12], losers[:12]


def tenderers(perustelut: str) -> list[str]:
    """The list of tenders received ('Määräaikaan mennessä saapui viisi (5) tarjousta: - A Oy - B Oy')."""
    m = re.search(r"(?:saapui|jätti\w*|saatiin|vastaanotettiin)[^\n]{0,80}?tarjou\w*\s*:\s*\n((?:[^\n]*\n){1,20})", perustelut or "")
    if not m:
        return []
    names = []
    for line in m.group(1).split("\n"):
        line = line.strip(" -•·*\t")
        if not line or len(line) > 160:
            break
        if not re.match(r"[\dA-ZÅÄÖ]", line) or re.search(r"\.\s*$", line) and len(line) > 90:
            break
        c = companies(line)
        if c:
            names.append(c[0][0])
        elif re.match(r"^[A-ZÅÄÖ][\w .&'’\-]{2,80}(?:,\s*y-tunnus.*)?$", line, re.I):
            names.append(clean_name(re.sub(r",?\s*y-tunnus.*$", "", line, flags=re.I)))
        else:
            break
    return names[:15]


def parse_amount(text: str) -> float | int | None:
    """First VAT-exclusive euro amount: 'arvonlisäveroton kokonaisarvo on 89 100 euroa', '12 841,95 euron
    arvonlisäverottomaan hintaan', '193 000 euroa (alv 0 %)'."""
    for m in AMOUNT.finditer(text or ""):
        ctx = text[max(0, m.start() - 110): m.end() + 60]
        if not VAT.search(ctx):
            continue
        raw = m.group(1)
        if "," in raw:
            whole, frac = raw.rsplit(",", 1)
            digits = re.sub(r"\D", "", whole)
            if not digits:
                continue
            val = float(f"{digits}.{frac}")
        else:
            digits = re.sub(r"\D", "", raw)
            if not digits:
                continue
            val = float(digits)
        if val <= 0:
            continue
        return int(val) if val == int(val) else round(val, 2)
    return None


def decision_type(subject: str, paatos: str, category: str | None) -> str:
    s, p = (subject or "").lower(), (paatos or "").lower()
    if "hankintaoikaisu" in s:
        return "oikaisu"
    if re.search(r"keskeytt|keskeytet", s + " " + p[:300]):
        return "keskeytys"
    if re.search(r"lisätyö|muutostyö|lisä- ja muutos", s):
        return "lisätyö"
    if "dynaamiseen hankintajärjestelmään" in p or "osallistumishakemu" in s:
        return "dps"
    if re.search(r"\boptio", s) or "otetaan käyttöön optio" in p:
        return "optio"
    if re.search(r"irtisano|purka", s):
        return "irtisanominen"
    if category == "Hankinta ilman kilpailutusta" or "suorahankin" in s or "suorahankin" in p[:400]:
        return "suorahankinta"
    if "pienhankinta" in s or "pienhankin" in p[:400]:
        return "pienhankinta"
    return "valinta"


def parse_content(content_html: str, motion_html: str, subject: str, category: str | None = None) -> dict:
    """Everything we read from the decision text (pure; used by tests on a saved _source)."""
    sec = sections(content_html)
    nbsp = lambda x: re.sub(r"[\u202f\u2009\u00a0]", " ", x or "")  # noqa: E731 – thin spaces as thousands separators
    paatos = nbsp(sec.get("Päätös"))
    perustelut = nbsp(sec.get("Päätöksen perustelut"))
    motion = nbsp(text_of(motion_html or ""))
    rest = perustelut or motion
    full = paatos + "\n" + rest
    winners, losers = winners_losers(paatos)
    tend = tenderers(rest)
    won = {w["name"].lower() for w in winners}
    lost = {l["name"].lower() for l in losers}
    for name in tend:
        if name.lower() not in won and name.lower() not in lost:
            losers.append({"name": name})
            lost.add(name.lower())
    value = parse_amount(paatos) or parse_amount(subject or "") or parse_amount(rest)
    hel = []
    for m in HEL.finditer(full):
        ref = f"HEL {m.group(1)}-{m.group(2)}"
        if ref not in hel:
            hel.append(ref)
    cloudia = CLOUDIA.search(full)
    notice = NOTICE.search(full)
    rfq = RFQ_DATE.search(full)
    summary = re.sub(r"\s+", " ", paatos).strip()
    if len(summary) > 420:
        c = summary[:420]
        summary = c[: c.rfind(". ") + 1] if ". " in c[150:] else c.rstrip() + "…"
    return {
        "summary": summary, "winners": winners, "losers": losers[:12], "tenderers": len(tend) or None, "value": value,
        "helRefs": hel[:5], "hilmaNo": cloudia.group(1) if cloudia else None,
        "noticeDate": iso(notice.group(1)) if notice else None, "rfqDate": iso(rfq.group(1)) if rfq else None,
        "dps": "dynaami" in full.lower() or None, "framework": "puitejärjestely" in full.lower() or None,
        "type": decision_type(subject, paatos, category),
    }


def parse_page(page_html: str) -> dict:
    """Appeal instructions and publication date from the decision page (pure; used by tests)."""
    t = text_of(page_html or "")
    up = t.upper()
    m = re.search(r"Päätös tullut nähtäväksi\s*(\d{1,2}\.\d{1,2}\.\d{4})", t)
    pdf = re.search(r'href="(https://ahjojulkaisu\.hel\.fi/[^"]+\.pdf)"[^>]*>\s*Lataa tulostusversio', page_html or "")
    att = re.findall(r'<div class="issue__attachment">', page_html or "")
    return {
        "valitusosoitus": "VALITUSOSOITUS MARKKINAOIKEUDELLE" in up,
        "oikaisuohje": "HANKINTAOIKAISUVAATIMUKSEN" in up or "HANKINTAOIKAISU" in up,
        "muutoksenhakukielto": "MUUTOKSENHAKUKIELTO" in up and "VALITUSOSOITUS MARKKINAOIKEUDELLE" not in up,
        "visible": iso(m.group(1)) if m else None,
        "pdf": pdf.group(1) if pdf else None,
        "attachments": len(att) or None,
    }


def from_hit(hit: dict) -> dict | None:
    """One Elasticsearch hit -> compact cache entry (without the page-only fields)."""
    s = hit.get("_source") or {}
    guid = (_one(s, "id") or "").strip("{}").lower()
    if not guid or not _one(s, "field_is_decision", True):
        return None
    subject = (_one(s, "subject") or "").strip()
    issue_subject = (_one(s, "issue_subject") or "").strip()
    category = _one(s, "category_name")
    if category in EXCLUDE_CATEGORIES:
        return None
    if not (category in CATEGORIES or issue_subject.lower().startswith("hankinta") or "hankinta" in subject.lower()):
        return None
    d = {
        "id": guid, "city": "Helsinki", "issueId": (_one(s, "unique_issue_id") or "").replace("HEL-", "HEL "),
        "issueSubject": issue_subject[:200], "title": subject[:220] or issue_subject[:220],
        "maker": _one(s, "organization_name"), "makerUnit": _one(s, "organization_above_name"), "makerType": _one(s, "organization_type"),
        "date": epoch_date(_one(s, "meeting_date")), "section": _one(s, "field_decision_section"),
        "category": category, "url": SITE + (_one(s, "decision_url") or ""),
    }
    d.update(parse_content(_one(s, "decision_content") or "", _one(s, "decision_motion") or "", subject, category))
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def search(days: int, size: int = 100, max_hits: int = 3000) -> list[dict]:
    body = {
        "size": size, "from": 0, "track_total_hits": True, "sort": [{"meeting_date": "desc"}],
        "_source": {"includes": FIELDS},
        "query": {"bool": {
            "filter": [{"range": {"meeting_date": {"gte": f"now-{int(days)}d"}}}, {"term": {"field_is_decision": True}}],
            "should": [{"term": {"category_name": c}} for c in CATEGORIES] + [{"match_phrase_prefix": {"issue_subject": "Hankinta"}}],
            "minimum_should_match": 1}},
    }
    hits: list[dict] = []
    total = None
    while True:
        body["from"] = len(hits)
        r = post_json(ES, body, headers={**UA, "Content-Type": "application/json"}, timeout=60)
        page = (r.get("hits") or {}).get("hits") or []
        total = ((r.get("hits") or {}).get("total") or {}).get("value", total)
        hits.extend(page)
        if len(page) < size or len(hits) >= min(total or 0, max_hits):
            break
        time.sleep(1.0)
    return hits


def fetch_oulu() -> list[dict]:
    """Procurement-looking officeholder decisions from Oulu's Tweb RSS (latin-1)."""
    r = http("GET", OULU_RSS, headers=UA, timeout=60)
    r.raise_for_status()
    raw = r.content.decode("latin-1", errors="replace")
    def tag(it: str, name: str) -> str:
        return html.unescape((re.search(rf"<{name}>(.*?)</{name}>", it, re.S) or [None, ""])[1]).strip()

    out = []
    for m in re.finditer(r"<item>(.*?)</item>", raw, re.S):
        it = m.group(1)
        title, desc, link = tag(it, "title"), text_of(tag(it, "description")), tag(it, "link")
        if not OULU_KW.search(title + " " + desc):
            continue
        docid = (re.search(r"docid=(\d+)", link) or [None, None])[1]
        if not docid:
            continue
        date = iso((re.search(r"Päätöspvm:\s*([^\n]+)", desc) or [None, ""])[1])
        maker = (re.search(r"Viranhaltija:\s*([^\n]+)", desc) or [None, ""])[1].strip()
        served = re.search(r"Tiedoksiantoaika:\s*(\d{1,2}\.\d{1,2}\.\d{4})\s*-\s*(\d{1,2}\.\d{1,2}\.\d{4})", desc)
        out.append({k: v for k, v in {
            "id": f"oulu-{docid}", "city": "Oulu", "title": title[:220], "maker": maker.split(",")[0].strip() or None, "makerUnit": maker,
            "date": date, "url": link, "served": iso(served.group(1)) if served else None, "servedUntil": iso(served.group(2)) if served else None,
            "section": (re.search(r"Päätösnro:\s*(\d+)", desc) or [None, None])[1], "type": "valinta",
        }.items() if v})
    return out


def main():
    cfg = (load_yaml(CONFIG_DIR / "settings.yaml") or {}).get("paatokset", {}) or {}
    days = int(cfg.get("days", 45))
    keep_days = int(cfg.get("keep_days", 60))
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    old = load_json(OUT, {}) or {}
    decisions: dict[str, dict] = dict(old.get("decisions") or {})
    health = {"hits": 0, "kept": 0, "pages": 0, "pageErrors": 0, "oulu": None}
    now = TODAY.isoformat()

    if cfg.get("helsinki", True):
        hits = search(days)
        health["hits"] = len(hits)
        if not hits:
            raise RuntimeError("paatokset: Helsingin Elasticsearch-haku ei palauttanut yhtään hankintapäätöstä – rajapinta on ehkä muuttunut")
        new = 0
        for h in hits:
            d = from_hit(h)
            if not d or not d.get("date"):
                continue
            prev = decisions.get(d["id"]) or {}
            if not prev:
                new += 1
            decisions[d["id"]] = {**{k: v for k, v in prev.items() if k in ("valitusosoitus", "oikaisuohje", "muutoksenhakukielto", "visible", "pdf", "attachments", "page", "firstSeen")},
                                  **d, "firstSeen": prev.get("firstSeen") or now, "seen": now}
        health["kept"] = sum(1 for v in decisions.values() if v.get("city") == "Helsinki")
        # decision pages: appeal instructions + publication date, once per decision (polite: ≤1 req/s, ≤150 per run)
        pending = [v for v in decisions.values() if v.get("city") == "Helsinki" and not v.get("page") and v.get("url", "").startswith(SITE)]
        pending.sort(key=lambda v: v.get("date") or "", reverse=True)
        for v in pending[:150]:
            try:
                r = http("GET", v["url"], headers=UA, timeout=60)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                v.update({k: x for k, x in parse_page(r.text).items() if x not in (None, False)})
                v["page"] = now
                health["pages"] += 1
            except Exception as e:  # noqa: BLE001
                health["pageErrors"] += 1
                log(f"warn: paatokset sivu {v['url']}: {e}")
            time.sleep(1.0)
        log(f"paatokset: Helsinki {len(hits)} osumaa ({new} uutta), {health['pages']} päätössivua luettu, {health['pageErrors']} virhettä")

    if cfg.get("oulu", False):
        try:
            items = fetch_oulu()
            for d in items:
                prev = decisions.get(d["id"]) or {}
                decisions[d["id"]] = {**prev, **d, "firstSeen": prev.get("firstSeen") or now, "seen": now}
            health["oulu"] = len(items)
            log(f"paatokset: Oulu {len(items)} hankintapäätöstä RSS:stä")
        except Exception as e:  # noqa: BLE001
            health["oulu"] = f"virhe: {e}"
            log(f"warn: paatokset Oulu: {e}")

    decisions = {k: v for k, v in decisions.items() if (v.get("date") or "9999") >= cutoff}
    save_json(OUT, {"fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "decisions": decisions, "health": health}, compact=True)
    log(f"paatokset: {len(decisions)} päätöstä välimuistissa -> {OUT}")


if __name__ == "__main__":
    main()
