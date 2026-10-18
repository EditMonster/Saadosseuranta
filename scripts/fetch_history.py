"""Kertyvä historia (data/history/): the long series behind the statistics layer.

The caches in data/cache keep only a rolling window (markkinaoikeus 90 days, KKV 90 days, award notices a
few months) because the page shows what is current. Base rates need years, so this module keeps four
append-only files that outlive the windows:

* mao.json     – procurement rulings of the Market Court. Backfilled from Finlex's year listings
                 (www.finlex.fi/fi/oikeuskaytanto/markkinaoikeus/<year>, current and previous calendar year;
                 Finlex publishes a selection of the court's rulings, ~170 procurement rulings a year) and
                 extended every run with the rulings fetch_mao.py parsed from markkinaoikeus.fi. Per ruling:
                 number, date, diaari, appellant, respondent (hankintayksikkö), outcome (fetch_mao.OUTCOMES
                 labels: valitus hylätty, jätetty tutkimatta, hankintapäätös kumottu, hyvitysmaksu, tehottomuus-
                 seuraamus, seuraamusmaksu, sopimuskauden lyhentäminen, rauennut, …), value, keywords and the
                 subject category of build_mao.classify_subject. Procurement cases are recognised from the
                 Finlex keywords (the diaarinumero carries no category); detail pages are fetched at ≥ 1.5 s
                 spacing, at most MAO_DETAIL_CAP per run, the rest on the next run.
* kkv.json     – KKV merger decisions since KKV_SINCE from the kkv.fi decision listing (?sivu=N; fetch_kkv
                 parse_case for the case page), merged with data/cache/kkv.json every run. Per case: diaari,
                 notified, decided, phase (1/2), outcome (hyväksytty / ehdoin / kielletty / rauennut / esitys
                 MAO), parties, sector (keyword classification of KKV's summary into the NACE labels of
                 config/yrityskaupat.yaml). Listing pages and case pages are each capped per run.
* awards.json  – award notices with contract periods, appended from data/cache/sopimuskaudet.json
                 (idempotent by noticeId): buyer, CPV, value, contractStart/End, durationMonths, framework,
                 dps, winners.
* appeals.json – every entry ever seen on the Market Court's list of pending procurement appeals
                 (idempotent by the list key): filed, buyer, decisionDate, and later the ruling it was linked to.

Each file is {"version", "updated", "state", "items": {key: row}}. A row is never dropped; new data fills
gaps and refreshes fields. The run raises only when a backfill source is down on the very first run (no
history yet); afterwards a failing source is logged and the history stays as it was.
"""
from __future__ import annotations

import html
import re
import time

from common import CACHE_DIR, CONFIG_DIR, ROOT, TODAY, http, load_json, load_yaml, log, save_json
from fetch_caselaw import FINLEX, UA as FINLEX_UA, _rsc_rows, _rsc_text, _walk, finlex_parse_list
from fetch_kkv import DECISIONS as KKV_DECISIONS, ENTRY as KKV_ENTRY, UA as KKV_UA, parse_case as kkv_parse_case
from fetch_mao import OUTCOMES, VERBS, iso

HISTORY_DIR = ROOT / "data" / "history"
MAO_HISTORY = HISTORY_DIR / "mao.json"
KKV_HISTORY = HISTORY_DIR / "kkv.json"
AWARDS_HISTORY = HISTORY_DIR / "awards.json"
APPEALS_HISTORY = HISTORY_DIR / "appeals.json"

FINLEX_DELAY = 1.5          # Finlex answers 429 when hit faster
MAO_DETAIL_CAP = 400        # Finlex decision pages per run
KKV_SINCE = "2024-01-01"
KKV_PAGE_CAP = 40           # kkv.fi listing pages per run
KKV_DETAIL_CAP = 40         # kkv.fi case pages per run
KKV_DELAY = 0.6

# Finlex keywords that mark a procurement case – and those that mark the court's other business
PROCUREMENT_KW = re.compile(r"hankin|hakinta|tarjo|kilpailuttamis|kynnysarvo|hyvitysmaksu|tehottomuus|sopimuskauden|kokonaistaloudel|"
                            r"soveltuvuus|vertailuperust|poissulkemis|referenssi|puitejärjest|käyttöoikeussopimu", re.I)
OTHER_KW = re.compile(r"tavaramerk|patent|keksin|mallioikeu|tekijänoikeu|hyödyllisyysmall|sopimaton menettely|turvaamistoi|verkkotunnu|"
                      r"kuluttaj|markkinoin|kilpailunrajoit|määräävä|yrityskaup|kartelli|maakaasu|sähkömarkkin|erottamisky|sekaannusvaar|"
                      r"seuraamusmaksuesitys|edustajakanne|maantieteellinen merkintä|hyvän liiketavan", re.I)
MAIN_APPEAL_DISMISSED = re.compile(r"hylkää (?:valitukset|valituksen)|avslår besvären", re.I)
OUTCOME_HEADS = ("lopputulos", "slutresultat", "domslut", "päätöslauselma")
BACKGROUND_HEADS = ("asian tausta", "asioiden tausta", "asian taustaa", "bakgrund", "ärendets bakgrund")
RULING_HEADS = ("markkinaoikeuden ratkaisu", "marknadsdomstolens avgörande")
VALUE_RE = re.compile(r"kokonaisarvo\b(?:(?!\.\s)[^€])*?\b(\d{1,3}(?:[ .\xa0]\d{3})+|\d{4,})\s*euroa", re.I)
KKV_SLUG = re.compile(r"/kkv-(\d+)-(\d+)-(\d+)-(\d+)-(\d{4})(?:-[a-z0-9-]+)?/?$")
KKV_PHASE2_TEXT = re.compile(r"(?:jatkoselvityk|jatkokäsittely)\w*\s+(\d{1,2}\.\d{1,2}\.\d{4})|(\d{1,2}\.\d{1,2}\.\d{4})\s+\w*\s*(?:jatkoselvityk|jatkokäsittely)", re.I)
KKV_OUTCOMES = (  # listing status (lower-case substring) -> outcome; first match wins
    ("jatkoselvityks", "jatkoselvitys"), ("jatkokäsittely", "jatkoselvitys"), ("markkinaoikeu", "esitys MAO"), ("kieltämis", "esitys MAO"),
    ("ehdollisena", "ehdoin"), ("ehtomuutos", "ehtoja muutettu"), ("sellaisenaan", "hyväksytty"), ("kieltäminen", "kielletty"),
    ("kielletään", "kielletty"), ("raukea", "rauennut"), ("hyväksyminen", "hyväksytty"),
)
FINAL_OUTCOMES = {"hyväksytty", "ehdoin", "kielletty", "rauennut", "esitys MAO"}
# KKV's summaries name the market ("… toimivat taloteknisten palveluiden markkinoilla"); the labels are those of
# config/yrityskaupat.yaml `nace`, so KKV and Commission cases share one sector vocabulary
SECTOR_KW = [
    ("Terveys- ja sosiaalipalvelut", r"terveyden|terveys|lääkäri|hammas|hoiva|sosiaalipalvel|sairaal|apteek|lääke|kuntoutu|hyvinvointi"),
    ("Rakentaminen", r"rakentami|rakennus|talotekn|lvi|sähköurak|urakoin|infra|maanrakenn|asfalt|kiinteistöhuol"),
    ("Televiestintä ja IT", r"ohjelmisto|it-palvel|tietojärjestelm|tietoliikenn|teleoperaat|pilvipalvel|digitaali|sovellus|data|ict"),
    ("Kauppa", r"vähittäis|tukkukau|verkkokau|kaupan|päivittäistavar|myymäl|autokau|ajoneuvojen vähittäis|rauta|kodinkone|huonekal"),
    ("Kuljetus ja varastointi", r"kuljetu|logistiik|varastoin|huolint|rahti|linja-auto|bussi|satama|lento"),
    ("Energia", r"energia|sähkön|sähköverk|kaukoläm|aurinko|tuulivoim|kaasu|polttoain|lämpö"),
    ("Rahoitus ja vakuutus", r"pankki|rahoitu|vakuutu|luotto|sijoitu|rahasto|maksupalvel|perint"),
    ("Kiinteistöala", r"kiinteistösijoit|kiinteistö|asunto|vuokra|toimitil"),
    ("Majoitus ja ravitsemus", r"ravintol|hotell|majoitu|kahvila|catering|ruokapalvel"),
    ("Kustannus- ja mediatoiminta", r"media|kustann|lehti|sanomaleh|televisio|radio|julkaisu|mainon"),
    ("Asiantuntijapalvelut", r"konsult|suunnittelupalvel|insinööri|arkkiteht|tilintark|lakiasiain|asianaj|mainostoimist|tutkimuspalvel"),
    ("Hallinto- ja tukipalvelut", r"henkilöstöpalvel|henkilöstövuokra|siivou|vartioin|turvallisuuspalvel|työvoima|rekrytoin|toimistopalvel"),
    ("Maa- ja metsätalous", r"maatalou|metsä|puunhank|puukau|kalanviljel|viljely|lannoit|rehu"),
    ("Vesi- ja jätehuolto", r"jätehuol|kierrätys|jätteen|vesihuol|romu|ympäristöhuol"),
    ("Koulutus", r"koulutu|oppilaito|opetus|päiväko|varhaiskasvatu"),
    ("Kulttuuri ja virkistys", r"liikunta|kuntosal|urheilu|elokuv|peli|tapahtum|viihde|kulttuur"),
    ("Teollisuus", r"valmist|teollisuu|tuotant|konepaj|metalli|elintarvik|leipom|meijer|lihanjalost|juoma|panim|paperi|sellu|kemia|muovi|betoni|sahatavar|puutuot"),
]


# ----------------------------------------------------------------------------- files
def _load(path) -> dict:
    h = load_json(path, {}) or {}
    if not isinstance(h, dict) or not isinstance(h.get("items"), dict):
        h = {"version": 1, "items": {}, "state": {}}
    h.setdefault("state", {})
    h.setdefault("version", 1)
    return h


def _save(path, h: dict) -> None:
    h["updated"] = TODAY.isoformat()
    save_json(path, h, compact=True)


def _fill(row: dict, new: dict, *, overwrite: bool = False) -> dict:
    """Merge new values into a history row: empty values never overwrite; with overwrite=False an existing value wins."""
    for k, v in new.items():
        if v in (None, "", [], {}):
            continue
        if overwrite or row.get(k) in (None, "", [], {}):
            row[k] = v
    return row


# ----------------------------------------------------------------------------- Market Court via Finlex
def is_procurement(keywords: list[str] | None) -> bool:
    """Finlex keywords -> is this a hankinta-asia? ('julkinen hankinta', 'tarjoajan soveltuvuus' … but not IPR,
    competition or market-law cases, which also mention e.g. seuraamusmaksu)."""
    text = " ".join(k for k in (keywords or []) if ">" not in k)
    return bool(PROCUREMENT_KW.search(text)) and not OTHER_KW.search(text)


def split_parties(keywords: list[str] | None) -> tuple[str | None, str | None]:
    """The first Finlex keyword is 'Valittaja > Hankintayksikkö'."""
    for k in keywords or []:
        if ">" in k:
            a, b = k.split(">", 1)
            return re.sub(r"\s+", " ", a).strip(" ,") or None, re.sub(r"\s+", " ", b).strip(" ,") or None
    return None, None


def finlex_mao_entries(page: str, year: int | None = None) -> list[dict]:
    """A Finlex markkinaoikeus year listing -> [{number, href, url, keywords, appellant, respondent, procurement}]."""
    out = []
    for it in finlex_parse_list(page):
        href = it.get("href") or ""
        if "/oikeuskaytanto/markkinaoikeus/" not in href:
            continue
        m = re.search(r"/markkinaoikeus/(\d{4})/(\d+)", href)
        number = it.get("number") or (f"MAO:{m.group(2)}/{m.group(1)}" if m else None)
        if not number:
            continue
        kws = [re.sub(r"\s+", " ", k).strip() for k in it.get("keywords") or [] if k and k.strip()]
        a, r = split_parties(kws)
        out.append({"number": number.strip(), "href": href, "url": FINLEX + href, "year": int(m.group(1)) if m else year,
                    "keywords": [k for k in kws if ">" not in k], "appellant": a, "respondent": r, "procurement": is_procurement(kws)})
    return out


def classify_outcome(text: str | None) -> str | None:
    """fetch_mao.OUTCOMES on the operative part. One refinement: when the first match is 'jätetty tutkimatta' only because
    a side claim was left unexamined while the appeal itself was dismissed on the merits, the ruling counts as 'valitus
    hylätty' (both are 'the appeal failed' for the statistics)."""
    low = (text or "").lower()
    if not low:
        return None
    label = next((label for key, label in OUTCOMES if key in low), "ratkaistu")
    if label == "jätetty tutkimatta" and MAIN_APPEAL_DISMISSED.search(low) and "valituksen tutkimatta" not in low and "valitukset tutkimatta" not in low:
        label = "valitus hylätty"
    return label


def _dl_meta(node, rows) -> tuple[dict, list[str]]:
    meta, kws = {}, []
    for item in (node[3].get("children") if isinstance(node[3], dict) else None) or []:
        if not (isinstance(item, list) and len(item) == 4 and isinstance(item[3], dict)):
            continue
        pair = item[3].get("children") or []
        dt_ = next((_rsc_text(x, rows) for x in pair if isinstance(x, list) and len(x) == 4 and x[1] == "dt"), None)
        dd = next((x for x in pair if isinstance(x, list) and len(x) == 4 and x[1] == "dd"), None)
        if not dt_ or dd is None:
            continue
        meta[dt_.strip()] = _rsc_text(dd, rows).strip()
        if dt_.strip() == "Asiasanat":
            for e in _walk(dd, rows):
                props = e[3] if isinstance(e[3], dict) else {}
                if e[1] == "span" and str(props.get("className", "")).endswith("bold") and isinstance(props.get("children"), str):
                    kws.append(re.sub(r"\s+", " ", props["children"]).strip())
    return meta, kws


def finlex_mao_sections(page: str) -> tuple[dict, list[str], list[tuple[str, list[str]]]]:
    """Finlex decision page -> (meta of the first <dl>, its keyword chips, [(heading, [paragraphs])] in the order the
    payload streams them: each heading row is followed by the rows of its paragraphs)."""
    rows = _rsc_rows(page)
    meta: dict = {}
    kws: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    cur: tuple[str, list[str]] | None = None
    for v in rows.values():
        if not (isinstance(v, list) and len(v) == 4 and v[0] == "$" and isinstance(v[1], str)):
            continue
        tag = v[1]
        if tag == "dl" and not meta:
            meta, kws = _dl_meta(v, rows)
        elif tag in ("h2", "h3", "h4", "h5", "h6"):
            props = v[3] if isinstance(v[3], dict) else {}
            if not props.get("id"):
                continue  # page chrome (title, navigation) – the document's headings carry ToC ids ("OT2_OT3" or slugs)
            cur = (_rsc_text(v, rows).strip(), [])
            sections.append(cur)
        elif tag == "p":
            t = re.sub(r"\s+", " ", _rsc_text(v, rows)).strip()
            if t.lower().strip(" :") in OUTCOME_HEADS + BACKGROUND_HEADS + RULING_HEADS:
                cur = (t, [])  # some rulings carry "Lopputulos" as a bold paragraph instead of a heading
                sections.append(cur)
            elif t and cur is not None:
                cur[1].append(t)
    return meta, kws, sections


def finlex_mao_parse_decision(page: str) -> dict:
    """A Finlex markkinaoikeus decision page -> ruling fields (number, date, diaari, keywords, parties, background,
    value, contested decision dates, outcomeText, outcome, interim)."""
    meta, kws, sections = finlex_mao_sections(page)
    d: dict = {}
    m = re.search(r"MAO:(\d+)/(\d{4})", page)
    d["number"] = f"MAO:{m.group(1)}/{m.group(2)}" if m else None
    anto = (meta.get("Antopäivä") or "").strip()
    d["date"] = anto[:10] if re.match(r"\d{4}-\d{2}-\d{2}", anto) else iso(anto)
    d["diaari"] = meta.get("Diaarinumero") or meta.get("Diaarinumero(t)") or None
    d["appellant"], d["respondent"] = split_parties(kws)
    d["keywords"] = [k for k in kws if ">" not in k]
    low_heads = [(h.lower().strip(" :"), paras) for h, paras in sections]
    tausta = next((" ".join(p) for h, p in low_heads if h.startswith(BACKGROUND_HEADS) and p), "")
    d["background"] = tausta[:900]
    d["noticeDate"] = iso((re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})\s+julkaistulla", tausta) or [None, None])[1])
    d["contestedDates"] = sorted({iso(x) for x in re.findall(r"(\d{1,2}\.\d{1,2}\.\d{4})\s+tekemäll", tausta) if iso(x)})
    mv = VALUE_RE.search(tausta)
    d["value"] = int(re.sub(r"\D", "", mv.group(1))) if mv else None
    lop = next((" ".join(p) for h, p in reversed(low_heads) if h in OUTCOME_HEADS and p), "")
    d["interim"] = False
    if not lop:
        # interim decisions (suspension, interim prohibition) have no "Lopputulos": the court's operative sentences
        seg = " ".join(" ".join(p) for h, p in low_heads if h.startswith(RULING_HEADS))
        sents = re.findall(r"(?:[Mm]arkkinaoikeus|[Mm]arknadsdomstolen) " + VERBS + r"[^.]*\.", seg)
        lop = " ".join(sents[-3:]) if sents else ""
        d["interim"] = bool(lop)
    d["outcomeText"] = lop[:700]
    d["outcome"] = classify_outcome(lop)
    if d["interim"] and d["outcome"]:
        d["outcome"] = {"valitus hylätty": "välipäätös: keskeytysvaatimus hylätty", "menettely keskeytetty väliaikaisesti": "välipäätös: menettely keskeytetty",
                        "täytäntöönpanokielto": "välipäätös: täytäntöönpanokielto", "täytäntöönpano sallittu": "välipäätös: täytäntöönpano sallittu"}.get(d["outcome"], "välipäätös")
    return d


def _subject(text: str, hcfg: dict | None) -> tuple[str | None, list[str]]:
    if not hcfg:
        return None, []
    from build_mao import (
        classify_subject,  # lazy: build_mao imports the settings machinery
    )

    topics = classify_subject(text, hcfg)
    return (topics[0] if topics else None), topics


def _finlex_fetch(url: str) -> str:
    r = http("GET", url, headers=FINLEX_UA, timeout=60)
    time.sleep(FINLEX_DELAY)
    if r.status_code == 404:
        return ""
    r.raise_for_status()
    return r.text


def update_mao_history(history: dict, *, years: list[int] | None = None, detail_cap: int = MAO_DETAIL_CAP, hcfg: dict | None = None,
                       fetch=_finlex_fetch, first_run: bool = False) -> dict:
    """Backfill / extend the Market Court series from Finlex. Returns counters."""
    items = history["items"]
    years = years or [TODAY.year - 1, TODAY.year]
    counters = {"listed": 0, "procurement": 0, "fetched": 0, "failed": 0, "pending": 0}
    for y in years:
        try:
            page = fetch(f"{FINLEX}/fi/oikeuskaytanto/markkinaoikeus/{y}")
        except Exception as e:  # noqa: BLE001
            if first_run:
                raise RuntimeError(f"historia: Finlexin markkinaoikeus-luettelo {y} ei vastaa: {e}") from e
            log(f"warn: historia finlex mao {y}: {e}")
            continue
        entries = finlex_mao_entries(page, y) if page else []
        counters["listed"] += len(entries)
        for e in entries:
            if not e["procurement"]:
                continue
            counters["procurement"] += 1
            row = items.setdefault(e["number"], {"number": e["number"], "firstSeen": TODAY.isoformat()})
            _fill(row, {"url": e["url"], "keywords": e["keywords"], "appellant": e["appellant"], "respondent": e["respondent"], "source": "finlex"})
            row.setdefault("category", None)
            if row.get("outcome") or row.get("detail"):
                continue
            if counters["fetched"] >= detail_cap:
                counters["pending"] += 1
                continue
            try:
                d = finlex_mao_parse_decision(fetch(e["url"]))
            except Exception as ex:  # noqa: BLE001
                counters["failed"] += 1
                log(f"warn: historia finlex {e['number']}: {ex}")
                continue
            counters["fetched"] += 1
            _fill(row, {k: d.get(k) for k in ("date", "diaari", "appellant", "respondent", "keywords", "background", "noticeDate", "contestedDates",
                                              "value", "outcomeText", "outcome")})
            row["interim"] = bool(d.get("interim"))
            row["detail"] = True
            row["fetched"] = TODAY.isoformat()
            if not row.get("category"):
                row["category"], row["topics"] = _subject(" ".join(row.get("keywords") or []) + " " + (row.get("background") or ""), hcfg)
    if first_run and not counters["listed"]:
        raise RuntimeError("historia: Finlexin markkinaoikeus-luettelot ovat tyhjiä – sivun rakenne on ehkä muuttunut")
    history["state"]["finlex"] = {"years": years, "pending": counters["pending"], "run": TODAY.isoformat()}
    return counters


def merge_mao_cache(history: dict, cache: dict, hcfg: dict | None = None) -> int:
    """Add the rulings fetch_mao.py parsed from markkinaoikeus.fi (category hankinta) to the history; fills gaps in
    rows Finlex already gave. Returns the number of new rows."""
    items = history["items"]
    new = 0
    for num, d in (cache.get("decisions") or {}).items():
        if not isinstance(d, dict) or d.get("category") != "hankinta":
            continue
        num = d.get("number") or num
        row = items.get(num)
        if row is None:
            row = items[num] = {"number": num, "firstSeen": TODAY.isoformat(), "source": "markkinaoikeus.fi"}
            new += 1
        kws = d.get("keywords")
        if isinstance(kws, str):
            kws = [k.strip() for k in re.split(r"\s+[–-]\s+", kws) if k.strip()]
        _fill(row, {"date": d.get("date"), "diaari": d.get("diaari"), "appellant": d.get("appellant"), "respondent": d.get("respondent"),
                    "keywords": kws, "background": (d.get("background") or "")[:900], "noticeDate": d.get("noticeDate"),
                    "contestedDates": d.get("contestedDates"), "value": d.get("value"), "outcomeText": d.get("outcomeText"),
                    "outcome": d.get("outcome"), "url": d.get("url")})
        if d.get("interim"):
            row["interim"] = True
        row.setdefault("interim", False)
        row["detail"] = True
        if not row.get("category"):
            row["category"], row["topics"] = _subject(" ".join(row.get("keywords") or []) + " " + (row.get("background") or ""), hcfg)
    return new


# ----------------------------------------------------------------------------- KKV merger decisions
def kkv_diaari(url: str) -> str | None:
    m = KKV_SLUG.search(url or "")
    return f"KKV/{m.group(1)}/{m.group(2)}.{m.group(3)}.{m.group(4)}/{m.group(5)}" if m else None


def kkv_outcome(status: str | None) -> str | None:
    low = (status or "").lower()
    return next((o for key, o in KKV_OUTCOMES if key in low), ("muu" if low else None))


def sector_of(text: str | None) -> str | None:
    low = (text or "").lower()
    for label, pat in SECTOR_KW:
        if re.search(pat, low):
            return label
    return None


def kkv_listing_entries(page: str) -> list[dict]:
    """A kkv.fi decision listing page -> [{url, diaari, parties, date, status, outcome}] newest first."""
    out = []
    for link, title, date, status in KKV_ENTRY.findall(page):
        st = html.unescape(re.sub(r"\s+", " ", status)).strip()
        out.append({"url": link, "diaari": kkv_diaari(link), "parties": html.unescape(re.sub(r"<[^>]+>", "", title)).strip(),
                    "date": date, "status": st, "outcome": kkv_outcome(st)})
    return out


def _kkv_apply_entry(items: dict, e: dict) -> bool:
    """Record one listing entry. Returns True when it added something new."""
    key = e.get("diaari") or e["url"]
    row = items.get(key)
    created = row is None
    if created:
        row = items[key] = {"diaari": e.get("diaari"), "firstSeen": TODAY.isoformat()}
    _fill(row, {"parties": e.get("parties"), "url": e["url"] if e["outcome"] != "jatkoselvitys" else None})
    if e["outcome"] == "jatkoselvitys":
        changed = not row.get("phase2Start")
        row["phase"] = 2
        _fill(row, {"phase2Start": e.get("date"), "interimUrl": e["url"]})
        return created or changed
    if e["outcome"] == "ehtoja muutettu":  # a later modification of conditions: note it, do not re-decide the case
        changed = row.get("conditionsModified") != e.get("date")
        row["conditionsModified"] = e.get("date")
        return created or changed
    changed = row.get("decided") != e.get("date") or row.get("outcome") != e.get("outcome")
    row.update({"decided": e.get("date"), "decision": e.get("status"), "outcome": e.get("outcome"), "decisionUrl": e["url"]})
    row.setdefault("phase", 1)
    return created or changed


def _kkv_fetch_listing(page: int) -> str:
    r = http("GET", KKV_DECISIONS, params={"sivu": page} if page > 1 else None, headers=KKV_UA, timeout=60)
    r.raise_for_status()
    time.sleep(KKV_DELAY)
    return r.text


def update_kkv_history(history: dict, *, since: str = KKV_SINCE, page_cap: int = KKV_PAGE_CAP, detail_cap: int = KKV_DETAIL_CAP,
                       fetch_listing=_kkv_fetch_listing, fetch_case=kkv_parse_case, first_run: bool = False) -> dict:
    """Walk the kkv.fi decision listing (newest first) back to `since`, then fetch case pages for rows that still lack
    the notification date. Returns counters."""
    items = history["items"]
    state = history["state"].setdefault("kkv", {})
    complete = bool(state.get("backfillComplete"))
    counters = {"pages": 0, "entries": 0, "new": 0, "details": 0, "failed": 0}
    page = 1
    reached_since = False
    resume = int(state.get("resumePage") or 0)
    pages = [1] + list(range(max(2, resume), 10_000)) if resume > 2 else list(range(1, 10_000))
    for page in pages:
        if counters["pages"] >= page_cap:
            break
        try:
            entries = kkv_listing_entries(fetch_listing(page))
        except Exception as e:  # noqa: BLE001
            if first_run and counters["pages"] == 0:
                raise RuntimeError(f"historia: kkv.fi:n päätöslistaus ei vastaa: {e}") from e
            log(f"warn: historia kkv sivu {page}: {e}")
            break
        counters["pages"] += 1
        if not entries:
            if first_run and page == 1:
                raise RuntimeError("historia: kkv.fi:n päätöslistaus on tyhjä – sivun rakenne on ehkä muuttunut")
            reached_since = True
            break
        new_here = 0
        for e in entries:
            if (e.get("date") or "") < since:
                reached_since = True
                continue
            counters["entries"] += 1
            if _kkv_apply_entry(items, e):
                new_here += 1
        counters["new"] += new_here
        if reached_since:
            break
        if complete and new_here == 0:
            break  # incremental mode: nothing new on this page, older pages were read before
        if len(entries) < 10:
            reached_since = True
            break
    if reached_since:
        state["backfillComplete"] = True
        state.pop("resumePage", None)
    elif counters["pages"] >= page_cap and not complete:
        state["resumePage"] = page
    # case pages: notification date, phase-2 dates, summary (sector)
    todo = [k for k, r in items.items() if r.get("decisionUrl") and not r.get("detail") and (r.get("decided") or "") >= since]
    for key in sorted(todo, key=lambda k: items[k].get("decided") or "", reverse=True)[:detail_cap]:
        row = items[key]
        try:
            d = fetch_case(row["decisionUrl"])
            time.sleep(KKV_DELAY)
        except Exception as e:  # noqa: BLE001
            counters["failed"] += 1
            log(f"warn: historia kkv {key}: {e}")
            continue
        counters["details"] += 1
        _fill(row, {"notified": d.get("notified"), "parties": d.get("parties"), "phase2Start": d.get("phase2Start"), "summary": (d.get("summary") or "")[:400]})
        if not row.get("phase2Start"):
            m = KKV_PHASE2_TEXT.search(d.get("summary") or "")
            if m:
                row["phase2Start"] = iso(m.group(1) or m.group(2))
        if row.get("phase2Start"):
            row["phase"] = 2
        row["detail"] = True
        row["sector"] = row.get("sector") or sector_of((d.get("summary") or "") + " " + (row.get("parties") or ""))
    state["run"] = TODAY.isoformat()
    return counters


def merge_kkv_cache(history: dict, cache: dict) -> int:
    """Add the cases fetch_kkv.py follows (pending and decided) to the history. Returns the number of new rows."""
    items = history["items"]
    new = 0
    for key, c in (cache.get("cases") or {}).items():
        if not isinstance(c, dict):
            continue
        diaari = c.get("diaari") or kkv_diaari(c.get("url") or "") or key
        row = items.get(diaari)
        if row is None:
            row = items[diaari] = {"diaari": diaari, "firstSeen": TODAY.isoformat()}
            new += 1
        phase2 = bool(c.get("phase2Start")) or "jatko" in str(c.get("listStatus") or "").lower() or "jatkokäsittely" in (c.get("interim") or {})
        _fill(row, {"parties": c.get("parties") or c.get("listTitle"), "notified": c.get("notified"), "url": c.get("url"),
                    "phase2Start": c.get("phase2Start") or (c.get("interimDates") or {}).get("jatkokäsittely"), "summary": (c.get("summary") or "")[:400]})
        if c.get("decided") and c.get("decision"):
            _fill(row, {"decided": c["decided"], "decision": c["decision"], "outcome": kkv_outcome(c["decision"]), "decisionUrl": c.get("decisionUrl")}, overwrite=True)
        elif c.get("pending") and not row.get("decided"):
            row["pending"] = True
        if row.get("decided"):
            row.pop("pending", None)
        if phase2 or row.get("phase2Start"):
            row["phase"] = 2
        row.setdefault("phase", 1)
        if row.get("notified"):
            row["detail"] = True  # the cache already read the case page
        row["sector"] = row.get("sector") or sector_of((c.get("summary") or "") + " " + (row.get("parties") or ""))
    return new


# ----------------------------------------------------------------------------- award notices and pending appeals
def update_awards_history(history: dict, sopimuskaudet: dict) -> int:
    """Append award notices with a contract period from data/cache/sopimuskaudet.json. Returns the number of new rows."""
    items = history["items"]
    new = 0
    for k, n in (sopimuskaudet.get("notices") or {}).items():
        if not isinstance(n, dict) or n.get("skip") or not (n.get("buyer") or n.get("contractEnd")):
            continue
        key = str(n.get("noticeId") or n.get("id") or k)
        row = items.get(key)
        if row is None:
            row = items[key] = {"noticeId": key, "firstSeen": TODAY.isoformat()}
            new += 1
        cpv = str(n.get("cpv") or "").split()
        _fill(row, {"id": n.get("id"), "buyer": n.get("buyer"), "buyerId": n.get("buyerId"), "cpv": cpv[0] if cpv else None, "cpvCodes": cpv or None,
                    "title": (n.get("title") or "")[:160], "value": n.get("value"), "currency": n.get("currency"), "contractStart": n.get("contractStart"),
                    "contractEnd": n.get("contractEnd"), "contractEndWithOptions": n.get("contractEndWithOptions"), "durationMonths": n.get("durationMonths"),
                    "published": n.get("published"), "awardDate": n.get("awardDate"), "contractDate": n.get("contractDate"), "lots": n.get("lots"),
                    "winners": [w.get("name") for w in (n.get("winners") or []) if isinstance(w, dict) and w.get("name")] or None}, overwrite=True)
        for flag in ("framework", "dps", "eu"):
            if n.get(flag):
                row[flag] = True
    return new


def update_appeals_history(history: dict, mao_cache: dict) -> int:
    """Append the Market Court's pending list (every entry ever seen) from data/cache/mao.json. Returns new rows."""
    items = history["items"]
    new = 0
    for key, p in (mao_cache.get("pending") or {}).items():
        if not isinstance(p, dict) or not p.get("filed"):
            continue
        row = items.get(key)
        if row is None:
            row = items[key] = {"key": key, "firstSeen": p.get("firstSeen") or TODAY.isoformat()}
            new += 1
        _fill(row, {"filed": p.get("filed"), "buyer": p.get("buyer"), "decisionDate": p.get("decisionDate"), "decisionText": (p.get("decisionText") or "")[:240],
                    "hilmaNo": p.get("hilmaNo")})
        _fill(row, {"lastSeen": p.get("lastSeen"), "decision": p.get("decision"), "missingSince": p.get("missingSince")}, overwrite=True)
    return new


# ----------------------------------------------------------------------------- wiring
def main() -> dict:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        hcfg = load_yaml(CONFIG_DIR / "hankinnat.yaml") or {}
    except Exception:  # noqa: BLE001
        hcfg = {}
    report: dict = {}

    mao = _load(MAO_HISTORY)
    first = not mao["items"]
    try:
        c = update_mao_history(mao, hcfg=hcfg, first_run=first)
        report["finlex"] = c
    except RuntimeError:
        _save(MAO_HISTORY, mao)
        raise
    except Exception as e:  # noqa: BLE001
        log(f"warn: historia finlex: {e}")
    report["maoFromCache"] = merge_mao_cache(mao, load_json(CACHE_DIR / "mao.json", {}) or {}, hcfg)
    _save(MAO_HISTORY, mao)
    rulings = sum(1 for r in mao["items"].values() if r.get("outcome"))
    log(f"historia: markkinaoikeus {len(mao['items'])} hankinta-asiaa, {rulings} ratkaisua ({report.get('finlex', {}).get('fetched', 0)} haettu Finlexistä, "
        f"{report.get('finlex', {}).get('pending', 0)} odottaa seuraavaa ajoa, {report['maoFromCache']} uutta välimuistista) -> {MAO_HISTORY}")

    kkv = _load(KKV_HISTORY)
    first = not kkv["items"]
    try:
        report["kkv"] = update_kkv_history(kkv, first_run=first)
    except RuntimeError:
        _save(KKV_HISTORY, kkv)
        raise
    except Exception as e:  # noqa: BLE001
        log(f"warn: historia kkv: {e}")
    report["kkvFromCache"] = merge_kkv_cache(kkv, load_json(CACHE_DIR / "kkv.json", {}) or {})
    _save(KKV_HISTORY, kkv)
    decided = sum(1 for r in kkv["items"].values() if r.get("decided"))
    log(f"historia: KKV {len(kkv['items'])} yrityskauppaa, {decided} ratkaistua ({report.get('kkv', {}).get('pages', 0)} listaussivua, "
        f"{report.get('kkv', {}).get('details', 0)} tapaussivua, takautuva haku {'valmis' if kkv['state'].get('kkv', {}).get('backfillComplete') else 'kesken'}) -> {KKV_HISTORY}")

    awards = _load(AWARDS_HISTORY)
    report["awards"] = update_awards_history(awards, load_json(CACHE_DIR / "sopimuskaudet.json", {}) or {})
    _save(AWARDS_HISTORY, awards)
    appeals = _load(APPEALS_HISTORY)
    report["appeals"] = update_appeals_history(appeals, load_json(CACHE_DIR / "mao.json", {}) or {})
    _save(APPEALS_HISTORY, appeals)
    log(f"historia: {len(awards['items'])} jälki-ilmoitusta (+{report['awards']}), {len(appeals['items'])} markkinaoikeuden valitusta (+{report['appeals']})")
    return report


if __name__ == "__main__":
    main()
