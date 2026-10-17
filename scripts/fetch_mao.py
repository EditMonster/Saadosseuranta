"""Markkinaoikeus (Market Court): public procurement appeals and rulings, plus competition rulings.

Sources on markkinaoikeus.fi (WordPress; these post types are not in its REST API, so HTML is parsed):

* Vireillä olevat hankinta-asiat – the statutory list of pending procurement appeals (hankintalaki
  148 § 3 mom.): date filed, contracting entity, the contested procurement decision. Updated daily;
  the court itself notes the list carries no legal effect. No case number or appellant is published.
* Ratkaisut – newest rulings per category (hankinta-asiat, kilpailu- ja valvonta-asiat), 30 per page,
  plus an RSS feed. Each ruling page gives the parties (valittaja > hankintayksikkö), keywords, case
  number, date, the background (notice date, contested decision, estimated value) and the operative
  part ("Lopputulos"), from which the outcome is classified.

Pending entries are matched to rulings by contracting entity + the date of the contested decision.

Cache: data/cache/mao.json – pending entries with first/last seen dates (an entry that disappears is
kept for keep_days as "poistunut listalta" unless a ruling was found); rulings are fetched once.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
import time

from common import CACHE_DIR, CONFIG_DIR, TODAY, http, load_json, load_yaml, log, save_json

PENDING = "https://www.markkinaoikeus.fi/vireilla-olevat-hankinta-asiat/"
LISTS = {"hankinta": "https://www.markkinaoikeus.fi/ratkaisut/hankinta-asiat/",
         "kilpailu": "https://www.markkinaoikeus.fi/ratkaisut/kilpailu-ja-valvonta-asiat/"}
RSS = "https://www.markkinaoikeus.fi/feed/rss-feed?post_type=ratkaisu"
OUT = CACHE_DIR / "mao.json"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) saadosseuranta/1.0 (+https://github.com/EditMonster/Saadosseuranta)", "Accept": "text/html,application/xml"}
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
ROW = re.compile(r"VIREILLE:\s*(.+?)\s*<br\s*/?>\s*HANKINTAYKSIKK[ÖO]:\s*(.*?)\s*<br\s*/?>\s*HA[NK]{2}INTAP[ÄA]{2}T[ÖO]S:\s*(.*)$", re.S | re.I)  # the list has had typos
DEC_LINK = re.compile(r"https://www\.markkinaoikeus\.fi/(?:sv/avgoranden/avgorandearkiv|ratkaisut/ratkaisujen-arkisto)/mao(\d+)-(\d{4})/")
DMY = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4,5})")
OUTCOMES = [  # first match wins, in order of legal weight (Finnish, then Swedish-language rulings)
    ("tehottomuus", "tehottomuusseuraamus"), ("seuraamusmaksu", "seuraamusmaksu"), ("sopimuskau", "sopimuskauden lyhentäminen"),
    ("hyvitysmaksu", "hyvitysmaksu"), ("kumoaa", "hankintapäätös kumottu"), ("keskeyttää", "menettely keskeytetty väliaikaisesti"),
    ("kieltää", "täytäntöönpanokielto"), ("sallii", "täytäntöönpano sallittu"),
    ("jättää valituksen tutkimatta", "jätetty tutkimatta"), ("jättää tutkimatta", "jätetty tutkimatta"),
    ("hylkää valituksen", "valitus hylätty"), ("hylkää", "valitus hylätty"), ("raukea", "rauennut"), ("poistaa", "poistettu käsittelystä"),
    ("gottgörelse", "hyvitysmaksu"), ("upphäver", "hankintapäätös kumottu"), ("avvisar", "jätetty tutkimatta"), ("avslår", "valitus hylätty"),
    ("förbjuder", "täytäntöönpanokielto"), ("förfaller", "rauennut"),
]
VERBS = r"(?:hylkää|kieltää|keskeyttää|määrää|sallii|kumoaa|velvoittaa|jättää|poistaa|avslår|upphäver|avvisar|förbjuder|ålägger)"


def text_of(h: str) -> str:
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", h, flags=re.S)
    t = re.sub(r"<(br|/p|/h\d|/li|/div|/tr|/td|/th)[^>]*>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def iso(s: str | None) -> str | None:
    m = DMY.search(s or "")
    if not m:
        return None
    y = m.group(3)
    y = y[-4:] if len(y) == 5 else y  # the list once read "14.10.12026"
    try:
        return dt.date(int(y), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\b(oy|ab|oyj|ky|ry|ab oy|oy ab|kunta|kaupunki|kuntayhtymä|hyvinvointialue|yhtymä)\b", " ", s)
    s = re.sub(r"[^a-zåäö0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def pending_key(filed: str, buyer: str, decision: str) -> str:
    return hashlib.sha1(f"{filed}|{norm(buyer)}|{norm(decision)[:120]}".encode()).hexdigest()[:12]


def fetch_pending() -> list[dict]:
    r = http("GET", PENDING, headers=UA, timeout=60)
    r.raise_for_status()
    out = []
    for cell in CELL.findall(r.text):
        m = ROW.search(cell)
        if not m:
            continue
        filed, buyer, decision = m.groups()
        clean = lambda s: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()  # noqa: E731
        d = iso(filed)
        if not d:
            continue
        b, dec = clean(buyer), clean(decision)
        out.append({"key": pending_key(d, b, dec), "filed": d, "buyer": b, "decisionText": dec,
                    "decisionDate": iso(dec), "hilmaNo": (re.search(r"Kilpailutusnumero\s*(\d{5,7})", dec) or [None, None])[1]})
    return out


def fetch_lists() -> dict[str, dict]:
    """{number: {url, date, keywords, category}} from the category pages and the RSS feed."""
    found: dict[str, dict] = {}
    for cat, url in LISTS.items():
        try:
            r = http("GET", url, headers=UA, timeout=60)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            log(f"warn: mao list {cat}: {e}")
            continue
        for m in re.finditer(r'href="(https://www\.markkinaoikeus\.fi/ratkaisut/ratkaisujen-arkisto/mao(\d+)-(\d{4})/)".*?</a>.*?(?:<div class="content-lift__excerpt">.*?<div[^>]*>(.*?)</div>)?.*?datetime="([^"]+)"', r.text, re.S):
            num = f"MAO:{m.group(2)}/{m.group(3)}"
            found.setdefault(num, {"url": m.group(1), "date": iso(m.group(5)), "keywords": re.sub(r"\s+", " ", html.unescape(m.group(4) or "")).strip(), "category": cat})
    try:
        r = http("GET", RSS, headers=UA, timeout=60)
        for m in re.finditer(r"<item>(.*?)</item>", r.text, re.S):
            it = m.group(1)
            lm = DEC_LINK.search(it)
            if not lm:
                continue
            num = f"MAO:{lm.group(1)}/{lm.group(2)}"
            found.setdefault(num, {"url": f"https://www.markkinaoikeus.fi/ratkaisut/ratkaisujen-arkisto/mao{lm.group(1)}-{lm.group(2)}/", "date": None, "keywords": "", "category": None})
    except Exception as e:  # noqa: BLE001
        log(f"warn: mao rss: {e}")
    return found


def parse_decision(url: str) -> dict:
    r = http("GET", url, headers=UA, timeout=60)
    r.raise_for_status()
    t = text_of(r.text)
    d: dict = {"url": url}
    m = re.search(r"MAO:(\d+)/(\d{4})", t)
    d["number"] = f"MAO:{m.group(1)}/{m.group(2)}" if m else None
    i = t.find("Asianomaiset")
    t = t[i:] if i >= 0 else t  # skip the site navigation (it repeats the heading "Käsiteltävät asiat")
    f = lambda label: (re.search(re.escape(label) + r"\s*:?\s*\n\s*([^\n]+)", t) or [None, None])[1]  # noqa: E731
    parties = (f("Asianomaiset") or "").strip()
    d["parties"] = parties
    if ">" in parties:
        a, b = parties.split(">", 1)
        d["appellant"], d["respondent"] = a.strip(" ,"), b.strip(" ,")
    else:
        d["appellant"], d["respondent"] = None, parties or None
    d["keywords"] = (f("Asiasanat") or "").strip()
    d["diaari"] = (f("Diaarinumero(t)") or f("Diaarinumero") or "").strip() or None
    d["date"] = iso(f("Antopäivä"))
    cat = f("Käsiteltävät asiat") or ""
    d["category"] = "kilpailu" if "ilpailu" in cat else ("hankinta" if "ankinta" in cat else cat.strip() or None)
    m = re.search(r"\n\s*Asi(?:an|oiden) tausta\s*\n(.*?)\n\s*Asi(?:an|oiden) käsittely markkinaoikeudessa", t, re.S)
    tausta = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    if not tausta:  # interim decisions: the first paragraphs after the category line
        m = re.search(r"Käsiteltävät asiat\s*\n[^\n]+\n(?:[^\n]*(?:käsittely|tausta)[^\n]*\n)?(.*?)(?:\n\s*(?:Valitus|Vaatimukset|Markkinaoikeuden ratkaisu)\s*\n|\Z)", t, re.S)
        tausta = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    d["background"] = tausta[:900]
    d["noticeDate"] = iso((re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})\s+julkaistulla", tausta) or [None, None])[1])
    d["contestedDates"] = sorted({iso(x) for x in re.findall(r"(\d{1,2}\.\d{1,2}\.\d{4})\s+tekemäll", tausta) if iso(x)})
    mv = re.search(r"kokonaisarvo[^.]*?noin\s+([\d\s.,]+)\s*euroa", tausta)
    d["value"] = int(re.sub(r"[^\d]", "", mv.group(1))) if mv and re.sub(r"[^\d]", "", mv.group(1)) else None
    if "annettu ruotsinkielisenä" in t:
        sv = re.search(r"https://www\.markkinaoikeus\.fi/sv/[^\s<\"']+", t)
        d["language"] = "sv"
        if sv:
            d["url"] = sv.group(0)
            try:
                r2 = http("GET", sv.group(0), headers=UA, timeout=60)
                t2 = text_of(r2.text)
                i2 = t2.find("Parter")
                t = t2[i2:] if i2 >= 0 else t2
                m = re.search(r"\n\s*(?:Bakgrund|Ärendets bakgrund)\s*\n(.*?)\n\s*(?:Ärendets behandling|Handläggning)", t, re.S)
                if m and not d["background"]:
                    d["background"] = re.sub(r"\s+", " ", m.group(1)).strip()[:900]
            except Exception:  # noqa: BLE001
                pass
    m = re.search(r"\n\s*(?:Lopputulos|Slutresultat|Domslut)\s*\n(.*?)(?:\n\s*(?:Muutoksenhaku|Ändringssökande|Sökande av ändring)\s*\n|\Z)", t, re.S)
    lop = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    if not lop:
        # interim decisions (e.g. suspension of the procedure) have no "Lopputulos": take the court's operative sentences
        m = re.search(r"\n\s*(?:Markkinaoikeuden ratkaisu|Marknadsdomstolens avgörande)\s*\n(.*?)(?:\n\s*(?:Muutoksenhaku|Ändringssökande)\s*\n|\Z)", t, re.S)
        seg = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        sents = re.findall(r"(?:[Mm]arkkinaoikeus|[Mm]arknadsdomstolen) " + VERBS + r"[^.]*\.", seg)
        lop = " ".join(sents[-3:]) if sents else ""
        if lop:
            d["interim"] = True
    d["outcomeText"] = lop[:700]
    low = lop.lower()
    d["outcome"] = next((label for key, label in OUTCOMES if key in low), "ratkaistu" if lop else None)
    if d.get("interim") and d["outcome"]:
        d["outcome"] = {"valitus hylätty": "välipäätös: keskeytysvaatimus hylätty", "menettely keskeytetty väliaikaisesti": "välipäätös: menettely keskeytetty",
                        "täytäntöönpanokielto": "välipäätös: täytäntöönpanokielto", "täytäntöönpano sallittu": "välipäätös: täytäntöönpano sallittu"}.get(d["outcome"], "välipäätös")
    if d["category"] == "kilpailu":
        low2 = (d["keywords"] + " " + lop).lower()
        if "yrityskaup" in low2:
            d["merger"] = True
            d["outcome"] = "yrityskauppa kielletty" if "kielt" in low and "hylkää" not in low else ("hyväksytty ehdoin" if "ehdo" in low else "esitys hylätty" if "hylkää" in low else d["outcome"])
    return d


def main():
    settings = load_yaml(CONFIG_DIR / "settings.yaml").get("markkinaoikeus", {})
    keep_days = int(settings.get("keep_days", 90))
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    old = load_json(OUT, {}) or {}
    pending: dict[str, dict] = dict(old.get("pending") or {})
    decisions: dict[str, dict] = dict(old.get("decisions") or {})

    rows = fetch_pending()
    if len(rows) < 20:
        raise RuntimeError(f"markkinaoikeus: vireillä-luettelosta löytyi vain {len(rows)} riviä – sivun rakenne on ehkä muuttunut")
    now = TODAY.isoformat()
    seen = set()
    for p in rows:
        seen.add(p["key"])
        prev = pending.get(p["key"]) or {"firstSeen": now}
        pending[p["key"]] = {**prev, **p, "lastSeen": now}
        pending[p["key"]].pop("missingSince", None)
    for k, v in pending.items():
        if k not in seen and not v.get("missingSince"):
            v["missingSince"] = now

    lists = fetch_lists()
    new = 0
    for num, meta in lists.items():
        if num in decisions:
            continue
        if meta.get("date") and meta["date"] < cutoff:
            continue
        try:
            d = parse_decision(meta["url"])
        except Exception as e:  # noqa: BLE001
            log(f"warn: mao {num}: {e}")
            continue
        d["number"] = d.get("number") or num
        d["date"] = d.get("date") or meta.get("date")
        d["keywords"] = d.get("keywords") or meta.get("keywords") or ""
        d["category"] = d.get("category") or meta.get("category")
        if d["category"] not in ("hankinta", "kilpailu"):
            continue  # IPR and market-law rulings are out of scope
        decisions[num] = d
        new += 1
        time.sleep(0.4)

    # match pending entries to rulings: same contracting entity and the contested decision's date in the ruling
    by_buyer: dict[str, list[dict]] = {}
    for d in decisions.values():
        if d.get("category") == "hankinta" and d.get("respondent"):
            by_buyer.setdefault(norm(d["respondent"]), []).append(d)
    linked = 0
    for p in pending.values():
        if p.get("decision"):
            continue
        cands = by_buyer.get(norm(p["buyer"])) or []
        words = {w for w in norm(p["decisionText"]).split() if len(w) >= 6}
        for d in cands:
            dd = p.get("decisionDate")
            bg = norm(d.get("background") or "")
            if (dd and dd in d.get("contestedDates", [])) or (len(words) >= 3 and len(words & set(bg.split())) >= max(3, len(words) // 2)):
                p["decision"] = d["number"]
                linked += 1
                break

    # forget old material
    pending = {k: v for k, v in pending.items() if not v.get("missingSince") or v["missingSince"] >= cutoff}
    keep_dec = {p["decision"] for p in pending.values() if p.get("decision")}
    decisions = {k: v for k, v in decisions.items() if (v.get("date") or "9999") >= cutoff or k in keep_dec}
    save_json(OUT, {"fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "pending": pending, "decisions": decisions})
    log(f"markkinaoikeus: {len(seen)} vireillä olevaa hankinta-asiaa, {new} uutta ratkaisua ({len(decisions)} välimuistissa), "
        f"{sum(1 for p in pending.values() if p.get('decision'))} yhdistetty ratkaisuun (+{linked}) -> {OUT}")


if __name__ == "__main__":
    main()
