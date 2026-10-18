"""Court of Justice of the European Union: recent judgments and Advocate General opinions, and the
pending preliminary references from Finnish courts – all from the Publications Office's Cellar.

Why Cellar: curia.europa.eu retired its RSS feeds with the new InfoCuria application (10/2026) and offers
no public filter by member state; Cellar loads every judgment and opinion on the day of delivery with
CELEX, ECLI, date, the originating member state (`cdm:case-law_originates_in_country`, set for
preliminary references and for direct actions with the state as party), procedure type, subject-matter
codes, the interpreted acts and a Finnish title. Two caveats drive the design:

* AG opinions get their country/subject metadata only weeks after delivery, so Finnish relevance is
  also decided from the case number (matched against the pending-reference watchlist) and, for the
  rest, from the Finnish text's header "(Ennakkoratkaisupyyntö – Korkein hallinto-oikeus (Suomi))".
* Enrichment (country, subject, interpreted acts, full title) lands days to weeks later, so the same
  window is re-queried on every run and cached rows are updated in place.

Pending references: the Court's OJ C notice "Ennakkoratkaisupyyntö, jonka <court> (Suomi) on esittänyt
<date>" is a sector-6 INFO_JUDICIAL work (CELEX 6YYYYCNnnnn, or TNnnnn for the General Court, which since
1.10.2024 hears references on VAT, excise, customs, passenger rights and ETS). It is published ~9–10 weeks
after lodging and is the only public document with the questions referred in Finnish. A reference stays
in the cache until the judgment with the same case number has been delivered (then `judgmentCelex` is
set and the row ages out with the judgment).

Kept: judgments/opinions originating in Finland, those belonging to a pending Finnish reference, those
interpreting an act that is being monitored (CELEX numbers from data/cache/eu.json and eut.watch_celex),
and those whose subject-matter code is listed in config/tuomioistuimet.yaml (eut.subject_codes).

Cache: data/cache/curia.json {fetched, cases: {celex: {...}}, references: {caseNo: {...}}}.
"""
from __future__ import annotations

import datetime as dt
import re

from common import CACHE_DIR, CONFIG_DIR, TODAY, http, load_json, load_yaml, log, save_json
from eu_notice import UA as CELLAR_UA
from eu_notice import text_of
from fetch_eu import _sparql

OUT = CACHE_DIR / "curia.json"
CONFIG = CONFIG_DIR / "tuomioistuimet.yaml"
SUBJECTS = CONFIG_DIR / "eut_aiheet.yaml"
CELLAR = "https://publications.europa.eu/resource/celex/"
PREFIXES = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX lang: <http://publications.europa.eu/resource/authority/language/>
PREFIX rt: <http://publications.europa.eu/resource/authority/resource-type/>
"""
REF_TITLE = re.compile(r"^Asia (?P<case>[CT]-\d+/\d{2})(?:, (?P<name>[^:]+))?: Ennakkoratkaisupyyntö, jonka (?P<court>.+?) \(Suomi\) on esittänyt "
                       r"(?P<lodged>\d{1,2}[./]\s?(?:\d{1,2}[./]|\w+)\s?\d{4})\s*[–-]\s*(?P<parties>.+)$")
FI_COURTS = [  # genitive stem as it appears in "<X:n> esittämä ennakkoratkaisupyyntö" -> nominative
    ("korkeimman hallinto-oikeuden", "Korkein hallinto-oikeus"), ("korkeimman oikeuden", "Korkein oikeus"),
    ("markkinaoikeuden", "Markkinaoikeus"), ("työtuomioistuimen", "Työtuomioistuin"), ("vakuutusoikeuden", "Vakuutusoikeus"),
]
FI_MONTHS = {"tammikuuta": 1, "helmikuuta": 2, "maaliskuuta": 3, "huhtikuuta": 4, "toukokuuta": 5, "kesäkuuta": 6,
             "heinäkuuta": 7, "elokuuta": 8, "syyskuuta": 9, "lokakuuta": 10, "marraskuuta": 11, "joulukuuta": 12}
ACT = re.compile(r"\b(direktiivi|asetus|päätös|puitepäätös)\w*\s+(?:\((?:EU|EY|ETY|EURATOM|Euratom)\)\s+)?(?:N:o\s+)?(\d{1,4})/(\d{1,4})(?:/(EU|EY|ETY|YOS|Euratom))?", re.I)


def case_no(celex: str) -> str | None:
    """62025CC0390 -> C-390/25, 62025TN0184 -> T-184/25."""
    m = re.fullmatch(r"6(\d{4})([CT])([A-Z])(\d{4})(?:\(\d+\))?", celex or "")
    if not m:
        return None
    return f"{m.group(2)}-{int(m.group(4))}/{m.group(1)[2:]}"


def celex_from_act(kind: str, a: str, b: str, suffix: str | None) -> str | None:
    """'direktiivi 2011/7/EU' -> 32011L0007, 'asetus (EU) 2016/679' -> 32016R0679, 'asetus (EY) N:o 1/2003' -> 32003R0001."""
    k = {"direktiivi": "L", "asetus": "R", "päätös": "D", "puitepäätös": "F"}.get(kind.lower())
    if not k:
        return None
    x, y = int(a), int(b)
    if 1950 <= x <= TODAY.year:        # year first: 2016/679
        year, num = x, y
    elif 1950 <= y <= TODAY.year:      # number first: 1/2003
        year, num = y, x
    elif suffix and y < 100:           # 'direktiivi 95/46/EY' -> 1995
        year, num = 1900 + x, y
    else:
        return None
    return f"3{year}{k}{num:04d}"


def acts_in_text(text: str) -> list[str]:
    out = []
    for m in ACT.finditer(text or ""):
        c = celex_from_act(m.group(1), m.group(2), m.group(3), m.group(4))
        if c and c not in out:
            out.append(c)
    return out[:8]


def parse_fi_dmy(s: str) -> str | None:
    s = (s or "").replace("\xa0", " ")
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})\.\s*(\w+)\s+(\d{4})", s)
    if m and m.group(2).lower() in FI_MONTHS:
        return dt.date(int(m.group(3)), FI_MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
    return None


def nominative_court(s: str) -> str:
    """'Korkeimman hallinto-oikeuden esittämä ennakkoratkaisupyyntö' -> 'Korkein hallinto-oikeus'; other courts: the raw name."""
    t = re.sub(r"\s+esittämä\s+ennakkoratkaisupyyntö.*$", "", (s or "").strip(), flags=re.I).strip(" .")
    low = t.lower()
    for stem, nom in FI_COURTS:
        if low.endswith(stem):
            return nom
    m = re.match(r"^(.*?)(käräjäoikeuden|hovioikeuden|hallinto-oikeuden)$", low)
    if m:
        head = t[: m.start(2)]
        return head + {"käräjäoikeuden": "käräjäoikeus", "hovioikeuden": "hovioikeus", "hallinto-oikeuden": "hallinto-oikeus"}[m.group(2)]
    return t


def parse_case_title(title: str) -> dict:
    """Finnish expression title 'heading#parties#referring court#keywords#Asia C-232/24' -> parts."""
    parts = [p.strip() for p in (title or "").split("#")]
    out = {"heading": parts[0] if parts else ""}
    for p in parts[1:]:
        if not p:
            continue
        low = p.lower()
        if re.match(r"^asia[t]?\s+[ct]-\d", low):
            out["caseLabel"] = p.rstrip(".")
        elif "esittämä ennakkoratkaisupyyntö" in low or low.startswith("ennakkoratkaisupyyntö, jonka") or low.startswith("ennakkoratkaisupyynnöt, jo"):
            out["referring"] = p.rstrip(".")
        elif " – " in p and ("ennakkoratkaisupyyntö" in low or "muutoksenhaku" in low or "kumoamiskanne" in low or "jäsenyysvelvoitteiden" in low or p.count(" – ") >= 2):
            out["keywords"] = p.rstrip(".")
        elif "parties" not in out:
            out["parties"] = p.rstrip(".")
    return out


def judgment_text_facts(text: str) -> dict:
    """Operative part and the referring court from the Finnish judgment / AG opinion text."""
    out: dict = {}
    m = re.search(r"on ratkaissut asian seuraavasti:\s*\n(.*)", text, re.S)
    if m:
        op = re.sub(r"\s+", " ", m.group(1)).strip()
        op = re.sub(r"\s*(Allekirjoitukset|Tuomio julistettiin).*$", "", op)
        out["operative"] = op[:1200]
    m = re.search(r"jonka\s+(.+?)\s+\(Suomi\)\s+on esittänyt", text)
    if m:
        c = m.group(1).strip()
        out["referringCourt"], out["fi"] = c[:1].upper() + c[1:], True
    m = re.search(r"\(Ennakkoratkaisupyyntö\s*[–-]\s*(.+?)\s*\((Suomi|[A-ZÄÖÅ][\wäöå\- ]+)\)\)", text[:4000])
    if m:
        out.setdefault("referringCourt", m.group(1).strip())
        if m.group(2) == "Suomi":
            out["fi"] = True
    return out


def parse_reference_notice(text: str) -> dict:
    """OJ C notice text -> {referringCourt, parties, questions, acts}."""
    out: dict = {}
    m = re.search(r"Ennakkoratkaisua pyytänyt tuomioistuin\s*\n(.+?)\n", text)
    if m:
        out["referringCourt"] = m.group(1).strip()
    m = re.search(r"Pääasian asianosaiset\s*\n(.*?)\n\s*Ennakkoratkaisukysymy", text, re.S)
    if m:
        out["parties"] = re.sub(r"\s+", " ", m.group(1)).strip()[:300]
    m = re.search(r"Ennakkoratkaisukysymy\w*\s*\n(.*?)(?:\n\s*\(\s*1\s*\)\s|\nELI:|\Z)", text, re.S)
    if m:
        q = re.sub(r"\n\s*(\d+\)|[a-z]\))\s*\n", r" \1 ", "\n" + m.group(1))
        q = re.sub(r"\(\s*\d+\s*\)", "", q)  # footnote markers
        out["questions"] = re.sub(r"\s+", " ", q).strip()[:1200]
    foot = text[text.find("( 1 )"):] if "( 1 )" in text else text
    acts = acts_in_text(foot) or acts_in_text(text)
    if acts:
        out["acts"] = acts
    return out


def fetch_text(celex: str) -> str:
    r = http("GET", CELLAR + celex, headers=CELLAR_UA, timeout=90)
    if r.status_code != 200:
        return ""
    return text_of(r.text)


def query_recent(since: str) -> list[dict]:
    q = PREFIXES + f"""
SELECT ?celex ?type ?date ?ecli ?title_fi
       (GROUP_CONCAT(DISTINCT REPLACE(STR(?country), ".*/", ""); separator=",") AS ?countries)
       (GROUP_CONCAT(DISTINCT REPLACE(STR(?proc), ".*/", ""); separator=",") AS ?procedure)
       (GROUP_CONCAT(DISTINCT REPLACE(STR(?sm), ".*/", ""); separator=",") AS ?subject)
       (GROUP_CONCAT(DISTINCT ?legcelex; separator=",") AS ?interprets)
WHERE {{
  VALUES ?type {{ rt:JUDG rt:OPIN_AG }}
  ?w cdm:work_has_resource-type ?type ; cdm:work_date_document ?date ; cdm:resource_legal_id_celex ?celex .
  FILTER(?date >= "{since}"^^xsd:date)
  FILTER NOT EXISTS {{ ?w cdm:work_is_member_of_complex_work ?cw }}
  OPTIONAL {{ ?w cdm:case-law_ecli ?ecli }}
  OPTIONAL {{ ?w cdm:case-law_originates_in_country ?country }}
  OPTIONAL {{ ?w cdm:case-law_has_type_procedure_concept_type_procedure ?proc }}
  OPTIONAL {{ ?w cdm:case-law_is-about_case-law-subject-matter ?sm }}
  OPTIONAL {{ ?w cdm:case-law_interpretes_resource_legal ?leg . ?leg cdm:resource_legal_id_celex ?legcelex }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language lang:FIN ; cdm:expression_title ?title_fi }}
}}
GROUP BY ?celex ?type ?date ?ecli ?title_fi
ORDER BY DESC(?date) ?celex
LIMIT 2000"""
    return _sparql(q)


def query_recent_by_celex(celexes: list[str]) -> list[dict]:
    """The same row shape as query_recent for given CELEX numbers (judgments / AG opinions of pending references,
    which may lie outside the daily window)."""
    if not celexes:
        return []
    vals = " ".join(f'"{c}"^^xsd:string' for c in celexes)
    q = PREFIXES + f"""
SELECT ?celex ?type ?date ?ecli ?title_fi
       (GROUP_CONCAT(DISTINCT REPLACE(STR(?country), ".*/", ""); separator=",") AS ?countries)
       (GROUP_CONCAT(DISTINCT REPLACE(STR(?proc), ".*/", ""); separator=",") AS ?procedure)
       (GROUP_CONCAT(DISTINCT REPLACE(STR(?sm), ".*/", ""); separator=",") AS ?subject)
       (GROUP_CONCAT(DISTINCT ?legcelex; separator=",") AS ?interprets)
WHERE {{
  VALUES ?celex {{ {vals} }}
  VALUES ?type {{ rt:JUDG rt:OPIN_AG }}
  ?w cdm:resource_legal_id_celex ?celex ; cdm:work_has_resource-type ?type ; cdm:work_date_document ?date .
  FILTER NOT EXISTS {{ ?w cdm:work_is_member_of_complex_work ?cw }}
  OPTIONAL {{ ?w cdm:case-law_ecli ?ecli }}
  OPTIONAL {{ ?w cdm:case-law_originates_in_country ?country }}
  OPTIONAL {{ ?w cdm:case-law_has_type_procedure_concept_type_procedure ?proc }}
  OPTIONAL {{ ?w cdm:case-law_is-about_case-law-subject-matter ?sm }}
  OPTIONAL {{ ?w cdm:case-law_interpretes_resource_legal ?leg . ?leg cdm:resource_legal_id_celex ?legcelex }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language lang:FIN ; cdm:expression_title ?title_fi }}
}}
GROUP BY ?celex ?type ?date ?ecli ?title_fi
LIMIT 500"""
    return _sparql(q)


def celex_for_case(case: str, kind: str) -> str | None:
    """('C-232/24', 'JUDG') -> 62024CJ0232; ('T-184/25', 'OPIN_AG') -> 62025TC0184."""
    m = re.fullmatch(r"([CT])-(\d+)/(\d{2})", case or "")
    if not m:
        return None
    year = int(m.group(3))
    year += 2000 if year < 70 else 1900
    return f"6{year}{m.group(1)}{'J' if kind == 'JUDG' else 'C'}{int(m.group(2)):04d}"


def query_references(since: str) -> list[dict]:
    q = PREFIXES + f"""
SELECT ?celex ?oj ?pub ?lodged ?title_fi
       (GROUP_CONCAT(DISTINCT ?legcelex; separator=",") AS ?legislation)
       (GROUP_CONCAT(DISTINCT REPLACE(STR(?ev), ".*/", ""); separator=",") AS ?eurovoc)
WHERE {{
  ?w cdm:work_has_resource-type rt:INFO_JUDICIAL ; cdm:resource_legal_id_celex ?celex ; cdm:official-journal-act_date_publication ?pub .
  FILTER(?pub >= "{since}"^^xsd:date)
  FILTER(REGEX(STR(?celex), "^6[0-9]{{4}}(CN|TN)[0-9]{{4}}$"))
  ?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language lang:FIN ; cdm:expression_title ?title_fi .
  FILTER(CONTAINS(?title_fi, "Ennakkoratkaisupyyntö") && CONTAINS(?title_fi, "(Suomi)"))
  OPTIONAL {{ ?w cdm:resource_legal_reference_oj-act ?oj }}
  OPTIONAL {{ ?w cdm:resource_legal_date_request_opinion ?lodged }}
  OPTIONAL {{ ?w cdm:communication_case_new_submits_preliminary_question ?leg . ?leg cdm:resource_legal_id_celex ?legcelex }}
  OPTIONAL {{ ?w cdm:work_is_about_concept_eurovoc ?ev }}
}}
GROUP BY ?celex ?oj ?pub ?lodged ?title_fi
ORDER BY DESC(?pub)
LIMIT 300"""
    return _sparql(q)


def _g(b: dict, k: str) -> str:
    return (b.get(k) or {}).get("value", "") or ""


def rows_to_cases(rows: list[dict]) -> dict[str, dict]:
    """SPARQL rows -> {celex: record}; several rows per CELEX (title variants) are merged."""
    out: dict[str, dict] = {}
    for b in rows:
        celex = _g(b, "celex")
        cn = case_no(celex)
        if not cn:
            continue
        typ = _g(b, "type").rsplit("/", 1)[-1]
        date = _g(b, "date")[:10]
        if date > TODAY.isoformat():
            date = TODAY.isoformat()  # Cellar occasionally carries a future document date
        rec = out.get(celex) or {"celex": celex, "caseNo": cn, "type": typ, "date": date, "court": "T" if cn.startswith("T-") else "C",
                                 "countries": [], "procedure": [], "subjects": [], "interprets": [], "title": ""}
        for key, field in (("countries", "countries"), ("procedure", "procedure"), ("subject", "subjects"), ("interprets", "interprets")):
            for v in _g(b, key).split(","):
                if v and v not in rec[field]:
                    rec[field].append(v)
        if _g(b, "ecli"):
            rec["ecli"] = _g(b, "ecli")
        t = _g(b, "title_fi")
        if len(t) > len(rec["title"]):
            rec["title"] = t
        out[celex] = rec
    return out


def links_for(rec: dict) -> dict:
    cn = rec["caseNo"]
    return {"curia": f"https://curia.europa.eu/juris/documents.jsf?num={cn}&language=fi",
            "eurlex": f"https://eur-lex.europa.eu/legal-content/FI/TXT/?uri=CELEX:{rec['celex']}"}


def main():
    cfg = load_yaml(CONFIG) or {}
    ecfg = cfg.get("eut") or {}
    keep_days = int(cfg.get("keep_days", 120))
    days = int(ecfg.get("days", 45))
    budget = int(ecfg.get("text_fetches_per_run", 12))        # judgment / AG-opinion texts
    budget_refs = int(ecfg.get("text_fetches_per_run", 12))   # notice texts (questions referred)
    labels = (load_yaml(SUBJECTS) or {}).get("subjects") or {}
    want_subjects = {str(s) for s in ecfg.get("subject_codes") or []}
    watch = {str(c) for c in ecfg.get("watch_celex") or []}
    for rec in (load_json(CACHE_DIR / "eu.json", {}).get("items") or {}).values():
        watch.update(((rec.get("cellar") or {}).get("acts") or {}).keys())
    old = load_json(OUT, {}) or {}
    cases: dict[str, dict] = dict(old.get("cases") or {})
    references: dict[str, dict] = dict(old.get("references") or {})
    checked: dict[str, str] = dict(old.get("checkedAg") or {})  # AG opinions whose Finnish text was read and found non-Finnish
    failures = []

    # 1. pending Finnish preliminary references (OJ C notices)
    try:
        rows = query_references(str(ecfg.get("references_since") or "2024-01-01"))
        for b in rows:
            title = _g(b, "title_fi").replace("\xa0", " ")
            m = REF_TITLE.match(title)
            if not m:
                log(f"warn: ennakkoratkaisupyynnön otsikkoa ei tunnistettu: {title[:120]}")
                continue
            cn = m.group("case")
            prev = references.get(cn) or {}
            ref = {**prev, "caseNo": cn, "celex": _g(b, "celex"), "oj": _g(b, "oj") or prev.get("oj"), "published": _g(b, "pub")[:10],
                   "lodged": _g(b, "lodged")[:10] or parse_fi_dmy(m.group("lodged")) or prev.get("lodged"),
                   "name": (m.group("name") or "").strip() or prev.get("name"), "referringCourt": prev.get("referringCourt") or m.group("court").strip(),
                   "parties": prev.get("parties") or m.group("parties").strip(), "title": title}
            ref["referringCourt"] = ref["referringCourt"][:1].upper() + ref["referringCourt"][1:]
            acts = [a for a in _g(b, "legislation").split(",") if a]
            ref["acts"] = sorted(set(acts) | set(prev.get("acts") or []))
            ev = [a for a in _g(b, "eurovoc").split(",") if a]
            if ev:
                ref["eurovoc"] = ev
            if ref.get("oj"):
                mo = re.match(r"C/(\d{4})/(\d+)", ref["oj"])
                if mo:
                    ref["url"] = f"https://eur-lex.europa.eu/eli/C/{mo.group(1)}/{int(mo.group(2))}/oj/fin"
            ref["curia"] = f"https://curia.europa.eu/juris/liste.jsf?num={cn}&language=fi"
            if "questions" not in ref and budget_refs > 0:
                budget_refs -= 1
                try:
                    facts = parse_reference_notice(fetch_text(ref["celex"]))
                    ref.update({k: v for k, v in facts.items() if v and k not in ("acts", "parties")})
                    ref["partiesDetail"] = facts.get("parties")  # with roles ("Valittaja: … Vastapuoli: …"); `parties` keeps the title's short form
                    ref["acts"] = sorted(set(ref["acts"]) | set(facts.get("acts") or []))
                    ref.setdefault("questions", "")
                except Exception as e:  # noqa: BLE001
                    log(f"warn: ilmoituksen {ref['celex']} teksti: {e}")
            references[cn] = ref
        log(f"EUT: {len(rows)} suomalaista ennakkoratkaisupyyntöä (ilmoitukset {ecfg.get('references_since')} alkaen)")
    except Exception as e:  # noqa: BLE001
        failures.append("references")
        log(f"warn: ennakkoratkaisupyynnöt: {e}")

    # 2. judgments and AG opinions of the window
    since = (TODAY - dt.timedelta(days=days)).isoformat()
    try:
        rows = query_recent(since)
        fresh = rows_to_cases(rows)
        if not fresh:
            raise RuntimeError("Cellar palautti 0 tuomiota – kysely tai palvelu rikki")
        # judgments / AG opinions of the pending references may be older than the window: ask for them by CELEX
        wanted = [celex_for_case(cn, k) for cn, r in references.items() if r.get("status") != "annettu" for k in ("JUDG", "OPIN_AG")]
        try:
            for celex, rec in rows_to_cases(query_recent_by_celex([c for c in wanted if c and c not in fresh])).items():
                fresh[celex] = rec
        except Exception as e:  # noqa: BLE001
            log(f"warn: ennakkoratkaisupyyntöjen tuomiot: {e}")
        kept = 0
        for celex, rec in fresh.items():
            prev = cases.get(celex) or {}
            cn = rec["caseNo"]
            why = []
            if "FIN" in rec["countries"]:
                why.append("FIN")
            if cn in references:
                why.append("ennakkoratkaisupyyntö")
            if want_subjects & set(rec["subjects"]):
                why.append("aihe")
            if watch & set(rec["interprets"]):
                why.append("seurattu säädös")
            if not why and not prev and rec["type"] == "OPIN_AG" and not rec["countries"] and celex not in checked and budget > 0:
                # a fresh AG opinion carries no metadata yet: the Finnish text's header names the referring court
                budget -= 1
                try:
                    facts = judgment_text_facts(fetch_text(celex)[:6000])
                    checked[celex] = rec["date"]
                except Exception as e:  # noqa: BLE001
                    facts = {}
                    log(f"warn: ratkaisuehdotuksen {celex} teksti: {e}")
                if facts.get("fi"):
                    why.append("FIN (tekstistä)")
                    rec["referringCourt"] = facts.get("referringCourt")
                    rec["fiText"] = True
                    checked.pop(celex, None)
            if not why and not prev:
                continue
            merged = {**prev, **{k: v for k, v in rec.items() if v not in ("", [], None)}}
            merged["why"] = sorted(set(prev.get("why") or []) | set(why)) or prev.get("why") or []
            parts = parse_case_title(merged.get("title", ""))
            merged["parties"] = parts.get("parties") or merged.get("parties")
            merged["keywords"] = parts.get("keywords") or merged.get("keywords")
            if not merged.get("interprets"):  # Cellar's interpreted-act links arrive late; the title's keyword string names the act
                merged["interprets"] = acts_in_text(merged.get("keywords") or "")
            if parts.get("referring") and not merged.get("referringCourt"):
                merged["referringCourt"] = nominative_court(parts["referring"])
            merged["fi"] = bool("FIN" in merged.get("countries", []) or cn in references or merged.get("fiText"))
            if cn in references:
                merged["referringCourt"] = references[cn].get("referringCourt") or merged.get("referringCourt")
            merged["subjectsFi"] = [labels.get(s, s) for s in merged.get("subjects", [])]
            merged["links"] = links_for(merged)
            if merged["fi"] and merged["type"] == "JUDG" and "operative" not in merged and budget > 0:
                budget -= 1
                try:
                    facts = judgment_text_facts(fetch_text(celex))
                    merged["operative"] = facts.get("operative", "")
                    if facts.get("referringCourt") and not merged.get("referringCourt"):
                        merged["referringCourt"] = facts["referringCourt"]
                except Exception as e:  # noqa: BLE001
                    log(f"warn: tuomion {celex} teksti: {e}")
            merged["fetched"] = TODAY.isoformat()
            cases[celex] = merged
            kept += 1
        log(f"EUT: {len(fresh)} tuomiota/ratkaisuehdotusta {days} päivän ikkunassa, {kept} seurannassa, "
            f"{sum(1 for c in checked.values() if c >= since)} ratkaisuehdotusta tarkistettu tekstistä (ei Suomea)")
    except Exception as e:  # noqa: BLE001
        failures.append("recent")
        log(f"warn: EUT:n tuomiot: {e}")

    # 3. link references to their AG opinion / judgment; age out
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    by_case: dict[str, dict[str, str]] = {}
    for celex, c in cases.items():
        by_case.setdefault(c["caseNo"], {})[c["type"]] = celex
    for cn, ref in references.items():
        if by_case.get(cn, {}).get("JUDG"):
            ref["judgmentCelex"] = by_case[cn]["JUDG"]
            ref["judgmentDate"] = cases[ref["judgmentCelex"]].get("date")
        if by_case.get(cn, {}).get("OPIN_AG"):
            ref["agCelex"] = by_case[cn]["OPIN_AG"]
            ref["agDate"] = cases[ref["agCelex"]].get("date")
        ref["status"] = "annettu" if ref.get("judgmentCelex") else "vireillä"
    cases = {k: v for k, v in cases.items() if (v.get("date") or "9999") >= cutoff}
    checked = {k: v for k, v in checked.items() if v >= since}
    references = {k: v for k, v in references.items() if v.get("status") != "annettu" or (v.get("judgmentDate") or "9999") >= cutoff}
    save_json(OUT, {"fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "cases": cases, "references": references,
                    "checkedAg": checked}, compact=True)
    n_fi = sum(1 for c in cases.values() if c.get("fi"))
    log(f"EUT: välimuistissa {len(cases)} ratkaisua ({n_fi} Suomea koskevaa), {sum(1 for r in references.values() if r['status'] == 'vireillä')} "
        f"vireillä olevaa ennakkoratkaisupyyntöä -> {OUT}")
    if len(failures) == 2:
        raise RuntimeError("EUT: sekä tuomio- että ennakkoratkaisupyyntökysely epäonnistuivat")
    if "recent" in failures and not cases:
        raise RuntimeError("EUT: tuomiokysely epäonnistui eikä välimuistia ole")


if __name__ == "__main__":
    main()
