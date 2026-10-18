"""Finnish case law: published decisions of the Supreme Court (KKO), the Supreme Administrative Court
(KHO), the Labour Court (TT), the Insurance Court (VakO), the Market Court (MAO; IPR and market-law
rulings only – procurement and competition rulings are fetch_mao.py's business), the courts of appeal
(HO) and the administrative courts (HaO).

Why these sources
* The courts themselves publish first. korkeinoikeus.fi, tyotuomioistuin.fi, vakuutusoikeus.fi and
  markkinaoikeus.fi share one WordPress theme with an RSS feed of the 30 newest rulings
  (`/feed/rss-feed?post_type=ratkaisu`, keywords in <category>, Finnish and Swedish items side by
  side) and decision pages that carry the case number, taltio, date, ECLI, keywords, the headnote
  (tiivistelmä) and the applied statutes as short lines ("RL 24 luku 12 §"). kho.fi's feed is broken,
  so its archive listing (the same `content-lift` markup fetch_mao.py parses) is read instead.
* Hovioikeudet and hallinto-oikeudet have no publication channel of their own; Finlex's year
  listings (`www.finlex.fi/fi/oikeuskaytanto/<court>/<year>`, a Next.js RSC payload) are complete and
  carry number, date (in the number) and keywords; the decision page adds the headnote. Finlex also
  serves as a fallback for the supreme courts when a court site is down (1–7 days behind).
* The Finlex open-data API does not yet expose court decisions (only ombudsman decisions, 10/2026);
  re-check `opendata.finlex.fi/.../judgment/supreme-court-precedent/list` quarterly.

Statute references are plain text without säädösnumero. They are resolved with the abbreviation and
full-name tables in config/tuomioistuimet.yaml into {sk: "1397/2016", section: "147 §"} so that the
build can join decisions to the statutes being monitored; unknown references stay in `rawRefs`.

Cache: data/cache/caselaw.json {fetched, health: {court: {ok, error, n}}, decisions: {id: {...}}}.
A decision page is fetched once per id; decisions older than keep_days (antopäivä) are dropped. The
run raises RuntimeError only when every enabled court failed, or when a court lists 0 decisions where
it listed some before (structure change) – the cache is saved first, so nothing is lost, and
update.py records the failure in health.json. Finlex is paced at ≥1.5 s per page (it answers 429 when
hit faster) and capped per run; the remainder is picked up on the next run.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import html
import json
import re
import time

from common import CACHE_DIR, CONFIG_DIR, TODAY, http, load_json, load_yaml, log, save_json
from fetch_mao import iso, text_of

OUT = CACHE_DIR / "caselaw.json"
CONFIG = CONFIG_DIR / "tuomioistuimet.yaml"
FINLEX = "https://www.finlex.fi"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) saadosseuranta/1.0 (+https://github.com/EditMonster/Saadosseuranta)",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "fi"}
SITE_DELAY = 0.6     # court sites (WordPress) – polite spacing between decision pages

# Case-number patterns per court (as the sites and Finlex print them)
REF_RE = {
    "KKO": re.compile(r"\bKKO:(\d{4}):(\d+)\b"),
    "KHO": re.compile(r"\bKHO:(\d{4}):(\d+)\b"),
    "TT": re.compile(r"\bTT\s?(\d{4}):(\d+)\b"),
    "VakO": re.compile(r"\bVakO\s?(\d+):(\d{4})\b"),
    "MAO": re.compile(r"\bMAO:(\d+)/(\d{4})\b"),
}
LABELS = ("Diaarinumero(t)", "Diaarinumero", "Taltionumero", "Taltio", "Antopäivä", "ECLI-tunnus", "Ennakkopäätösnumero",
          "Julkaisunumero", "Asianomaiset", "Asiasanat", "Käsiteltävät asiat", "Sovellettu lainsäädäntö")
LABEL_RE = re.compile(r"^(" + "|".join(re.escape(l) for l in LABELS) + r")\s*:?\s*$")
# section headings that end the headnote block on a decision page
STOP = ("asian käsittely alemmissa oikeuksissa", "asian käsittely", "asian aikaisempi käsittely", "asian tausta", "asian taustaa",
        "muutoksenhaku korkeimmassa oikeudessa", "korkeimman oikeuden ratkaisu", "päätös, jota muutoksenhaut koskevat",
        "päätös, jota muutoksenhaku koskee", "päätös, josta valitetaan", "korkeimman hallinto-oikeuden ratkaisu",
        "vaatimukset korkeimmassa hallinto-oikeudessa", "asia", "kantaja", "esitiedot", "hakemus", "vaatimukset", "kanne", "valitus",
        "markkinaoikeuden ratkaisu", "vakuutusoikeuden ratkaisu", "käsittely työtuomioistuimessa", "oikeudenkäynti", "ratkaisu")
OUTCOME_HEAD = re.compile(r"^(Lopputulos|Päätöslauselma|Tuomiolauselma|Slutresultat|Domslut)\s*$", re.I)
OUTCOME_END = re.compile(r"^(Täytäntöönpano|Muutoksenhaku|Lainvoimaisuus|Ändringssökande|Sökande av ändring|Asian ovat|Asian on|"
                         r"Asian ratkaisemiseen|Tuomion ovat|Tuomiosta on|Ratkaisuun ovat|Päätöksen ovat|Ks\.)", re.I)
# "RL 24 luku 12 §", "TutkintavankeusL 2 luku 1 § 3 mom", "Tuloverolaki 53 a §", "Laki eläkkeensaajan asumistuesta 5 § ja 9 §"
REF_LINE = re.compile(r"^(?P<name>[A-ZÄÖÅ][^§\n]{0,100}?)\s+(?P<secs>(?:\d+\s?[a-z]?\s+lu(?:ku|vun)\s+)?\d+\s?[a-z]?\s*§.{0,80})$")
SECTION = re.compile(r"(?:(?P<ch>\d+\s?[a-z]?)\s+lu(?:ku|vun)\s+)?(?P<sec>\d+\s?[a-z]?)\s*§(?::?\w*)?(?:\s*(?P<mom>\d+)\s*mom)?")
SK_IN_TEXT = re.compile(r"\((\d{1,4}/\d{4})\)(?P<tail>[^.;)]{0,60})")
CITED = re.compile(r"\b(KKO|KHO)\s?:?\s?(\d{4}):(\d+)\b|\b([CT]-\d{1,4}/\d{2})\b")
KW_SPLIT = re.compile(r"\s+[–-]\s+|\s*,\s+")


def load_config() -> dict:
    return load_yaml(CONFIG) or {}


# ---------------------------------------------------------------- statute references

class StatuteResolver:
    """Maps the courts' plain-text statute references to säädösnumero using the YAML tables."""

    def __init__(self, cfg: dict):
        self.abbr = {str(k): str(v) for k, v in (cfg.get("statutes") or {}).items()}
        self.names = {str(k).lower(): str(v) for k, v in (cfg.get("names") or {}).items()}
        self.text_patterns = self._text_patterns()

    def _text_patterns(self) -> list[tuple[re.Pattern, str]]:
        """Inflected in-text forms: 'tuloverolain 53 a §', 'oikeudenkäymiskaaren 7 luvun 3 §',
        'eläkkeensaajan asumistuesta annetun lain 9 §'."""
        out = []
        tail = r"\s+(?:(?P<ch>\d+\s?[a-z]?)\s+lu(?:ku|vun)\s+)?(?P<sec>\d+(?:\s?[a-z](?![a-zäöå]))?)\s*§"
        for name, sk in sorted(self.names.items(), key=lambda kv: -len(kv[0])):
            if name.startswith("laki "):
                comp = re.escape(name[5:])
                pat = rf"\b{comp}\s+annet(?:un\s+lain|ussa\s+laissa|tua\s+lakia)" + tail
            elif name.endswith("laki"):
                pat = rf"\b{re.escape(name[:-4])}la(?:ki|in|kia|issa|ista)" + tail
            elif name.endswith("kaari"):
                pat = rf"\b{re.escape(name[:-5])}kaar(?:i|en|ta|essa|esta)" + tail
            else:
                continue
            out.append((re.compile(pat, re.I), sk))
        return out

    def _mention_patterns(self) -> list[tuple[re.Pattern, str]]:
        out = []
        for name, sk in self.names.items():
            if name.startswith("laki "):
                pat = rf"(?<![\w-]){re.escape(name[5:])}\s+annet(?:un\s+lain|tu\s+laki|ua\s+lakia|ussa\s+laissa)\b"
            elif name.endswith("laki"):
                pat = rf"(?<![\w-]){re.escape(name[:-4])}la(?:ki|in|kia|issa|ista|iksi)\b"
            elif name.endswith("kaari"):
                pat = rf"(?<![\w-]){re.escape(name[:-5])}kaar(?:i|en|ta|essa|esta)\b"
            else:
                continue
            out.append((re.compile(pat, re.I), sk))
        return out

    def mentions(self, text: str) -> set[str]:
        """Säädösnumerot of the statutes a title names ('laki rikoslain 24 luvun muuttamisesta' -> {'39/1889'})."""
        if not hasattr(self, "_mentions"):
            self._mentions = self._mention_patterns()
        t = text or ""
        return {sk for pat, sk in self._mentions if pat.search(t)}

    @staticmethod
    def _sections(secs: str) -> list[str]:
        out = []
        for m in SECTION.finditer(secs):
            s = (f"{m.group('ch').replace(' ', '')} luku " if m.group("ch") else "") + f"{m.group('sec').strip()} §"
            if m.group("mom"):
                s += f" {m.group('mom')} mom"
            if s not in out:
                out.append(s)
        return out

    def resolve_name(self, name: str) -> str | None:
        n = re.sub(r"\s+", " ", name).strip(" ,;:")
        if n in self.abbr:
            return self.abbr[n]
        if n.rstrip(".") in self.abbr:
            return self.abbr[n.rstrip(".")]
        m = re.search(r"\((\d{1,4}/\d{4})\)", n)
        if m:
            return m.group(1)
        alias = re.search(r"\(([^()]*laki)\)", n, re.I)  # "Laki viranomaisten toiminnan julkisuudesta (julkisuuslaki)"
        low = re.sub(r"\s*\([^()]*\)", "", n).lower().strip()
        m = re.match(r"^(.+?) annettu laki$", low)  # "Sosiaali- ja terveydenhuollon asiakasmaksuista annettu laki"
        if m:
            low = "laki " + m.group(1)
        for cand in (low, low.replace("suomen ", ""), alias.group(1).lower() if alias else None):
            if cand and cand in self.names:
                return self.names[cand]
        squeezed = low.replace(" ", "")  # HTML hyphenation artefacts ("viranomais t en")
        for key, sk in self.names.items():
            if key.replace(" ", "") == squeezed:
                return sk
        # "Laki oikeudenkäynnistä hallintoasioissa" vs names key without a trailing qualifier
        for key, sk in self.names.items():
            if key.startswith("laki ") and low.startswith(key + " "):
                return sk
        return None

    def resolve_lines(self, lines: list[str]) -> tuple[list[dict], list[str]]:
        """Dedicated reference lines -> ([{sk, section}], rawRefs)."""
        refs, raw = [], []
        for line in lines:
            if re.search(r"\b\d+\s+kap\b|\bmom\.?\s*$", line) and re.search(r"\bkap\b", line):
                continue  # the Swedish duplicate ("HäktningsL 2 kap 1 § 3 mom") of a Finnish reference line
            m = REF_LINE.match(line.strip())
            if not m:
                raw.append(line.strip()[:120])
                continue
            sk = self.resolve_name(m.group("name"))
            secs = self._sections(m.group("secs"))
            if not sk:
                raw.append(line.strip()[:120])
                continue
            for s in secs or [None]:
                r = {"sk": sk}
                if s:
                    r["section"] = s
                if r not in refs:
                    refs.append(r)
        return refs, raw

    def resolve_text(self, text: str) -> list[dict]:
        """References inside running text (headnote / operative part)."""
        refs: list[dict] = []
        t = text or ""
        for pat, sk in self.text_patterns:
            for m in pat.finditer(t):
                s = (f"{m.group('ch').replace(' ', '')} luku " if m.group("ch") else "") + f"{m.group('sec').strip()} §"
                r = {"sk": sk, "section": s}
                if r not in refs:
                    refs.append(r)
        for m in SK_IN_TEXT.finditer(t):
            sk = m.group(1)
            if not (1 <= int(sk.split("/")[1]) <= TODAY.year and int(sk.split("/")[1]) >= 1734):
                continue
            secs = self._sections(m.group("tail"))
            for s in secs or [None]:
                r = {"sk": sk}
                if s:
                    r["section"] = s
                if r not in refs:
                    refs.append(r)
        return refs

    def resolve(self, lines: list[str], text: str) -> tuple[list[dict], list[str]]:
        refs, raw = self.resolve_lines(lines)
        for r in self.resolve_text(text):
            if r not in refs and not any(x["sk"] == r["sk"] and (x.get("section") or "").startswith(r.get("section") or "") for x in refs):
                refs.append(r)
        return refs[:25], raw[:10]


def cited_cases(text: str) -> list[str]:
    out = []
    for m in CITED.finditer(text or ""):
        c = f"{m.group(1)}:{m.group(2)}:{m.group(3)}" if m.group(1) else m.group(4)
        if c not in out:
            out.append(c)
    return out[:12]


def split_keywords(s: str) -> list[str]:
    return [k.strip(" .") for k in KW_SPLIT.split(s or "") if k.strip(" .")]


# ---------------------------------------------------------------- identifiers

def make_id(court: str, ref: str, href: str | None = None) -> str:
    """KKO:2026:75 -> r-kko-2026-75, TT 2026:34 -> r-tt-2026-34, VakO 1642:2025 -> r-vako-1642-2025,
    MAO:482/2026 -> r-mao-482-2026, KHO 29.9.2026/2501 -> r-kho-2026-t2501,
    Finlex /fi/oikeuskaytanto/hovioikeudet/2026/helsinki/10640647 -> r-ho-2026-helsinki-10640647."""
    c = court.lower()
    if href and court in ("HO", "HaO"):
        m = re.search(r"/(\d{4})/([a-z\-]+)/([\w\-]+)/?$", href)
        if m:
            return f"r-{c}-{m.group(1)}-{m.group(2)}-{m.group(3).lower()}"
    if court == "KHO":
        m = re.search(r"KHO\s+\d{1,2}\.\d{1,2}\.(\d{4})/(\d+)", ref)
        if m:
            return f"r-kho-{m.group(1)}-t{m.group(2)}"
    body = re.sub(r"^" + re.escape(court.lower()), "", ref.lower()).strip(" :")
    return f"r-{c}-" + re.sub(r"[^a-z0-9]+", "-", body).strip("-")


def finlex_url(court: str, cfg: dict, ref: str, date: str | None) -> str | None:
    """Canonical Finlex address of a decision (it appears there 1–7 days after the court's own page)."""
    sect = (cfg.get("courts", {}).get(court) or {}).get("finlex")
    if not sect:
        return None
    m = REF_RE.get(court, re.compile("$^")).search(ref)
    if not m:
        return None
    if court in ("KKO", "KHO", "TT"):
        return f"{FINLEX}/fi/oikeuskaytanto/{sect}/{m.group(1)}/{m.group(2)}"
    if court == "MAO":
        return f"{FINLEX}/fi/oikeuskaytanto/{sect}/{m.group(2)}/{m.group(1)}"
    if court == "VakO" and date:
        return f"{FINLEX}/fi/oikeuskaytanto/{sect}/{date[:4]}/{m.group(1)}-{m.group(2)}"
    return None


# ---------------------------------------------------------------- court sites (WordPress "oikeus" theme)

def fetch_rss(host: str, court: str) -> list[dict]:
    """[{ref, url, date, keywords}] from the 30 newest Finnish-language items."""
    r = http("GET", f"https://{host}/feed/rss-feed?post_type=ratkaisu", headers=UA, timeout=60)
    r.raise_for_status()
    out, seen = [], set()
    for m in re.finditer(r"<item>(.*?)</item>", r.text, re.S):
        it = m.group(1)
        g = lambda tag: html.unescape((re.search(rf"<{tag}>(.*?)</{tag}>", it, re.S) or [None, ""])[1]).strip()  # noqa: E731
        link = g("link")
        if "/sv/" in link:
            continue
        mm = REF_RE[court].search(g("title"))
        if not mm:
            continue
        ref = mm.group(0)
        if ref in seen:
            continue
        seen.add(ref)
        date = None
        try:
            date = email.utils.parsedate_to_datetime(g("pubDate")).date().isoformat()
        except (TypeError, ValueError):
            pass
        out.append({"ref": ref, "url": link, "date": date, "keywords": split_keywords(g("category"))})
    return out


def fetch_lift_list(url: str, link_re: str, court: str) -> list[dict]:
    """kho.fi archive / markkinaoikeus.fi category page: <li class="content-lift"> blocks with a link, keyword
    excerpt and <time datetime="dd.mm.yyyy">."""
    r = http("GET", url, headers=UA, timeout=60)
    r.raise_for_status()
    out, seen = [], set()
    for block in re.split(r'<li class="content-lift', r.text)[1:]:
        lm = re.search(rf'href="({link_re})"', block)
        if not lm:
            continue
        ref = REF_RE[court].search(text_of(block[lm.end():lm.end() + 400]))
        if not ref:
            continue
        ref = ref.group(0)
        if ref in seen:
            continue
        seen.add(ref)
        ex = re.search(r'content-lift__excerpt">(.*?)</div>\s*(?:</div>|<div class="flex gap)', block, re.S)
        kw = text_of(ex.group(1)) if ex else ""
        dm = re.search(r'datetime="([^"]+)"', block)
        out.append({"ref": ref, "url": lm.group(1), "date": iso(dm.group(1)) if dm else None, "keywords": split_keywords(kw)})
    return out


def parse_site_decision(page: str, court: str) -> dict:
    """Decision page of a court site -> {ref, date, diaari, taltio, ecli, keywords, abstract, refLines, outcome, parties, category}."""
    t = text_of(page)
    lines = [l.strip() for l in t.split("\n") if l.strip()]
    rr = REF_RE[court]
    heads = [i for i, l in enumerate(lines[:400]) if rr.fullmatch(l) or rr.fullmatch(l.replace("MAO: ", "MAO:"))]
    # the number appears as breadcrumb + <h1> (two consecutive lines) and again as the value of
    # "Ennakkopäätösnumero"/"Julkaisunumero"; the content starts after the consecutive pair
    head = next((i for i in reversed(heads) if i - 1 in heads), heads[0] if heads else None)
    start = head + 1 if head is not None else 0
    ref = rr.search(lines[head]).group(0) if head is not None else None
    d: dict = {"ref": ref, "keywords": [], "refLines": [], "abstract": "", "outcome": ""}
    i = start
    kws: list[str] = []
    # keyword chips / line(s) until the first label
    while i < len(lines) and not LABEL_RE.match(lines[i]) and i - start < 12:
        kws.extend(split_keywords(lines[i]))
        i += 1
    meta: dict[str, str] = {}
    while i < len(lines):
        m = LABEL_RE.match(lines[i])
        if not m:
            break
        label = m.group(1)
        i += 1
        vals = []
        while i < len(lines) and not LABEL_RE.match(lines[i]) and (not vals or label == "Sovellettu lainsäädäntö"):
            vals.append(lines[i])
            i += 1
        meta[label] = "\n".join(vals)
    d["keywords"] = kws or split_keywords(meta.get("Asiasanat", ""))
    if meta.get("Asiasanat") and not kws:
        d["keywords"] = split_keywords(meta["Asiasanat"])
    d["diaari"] = (meta.get("Diaarinumero(t)") or meta.get("Diaarinumero") or "").strip() or None
    d["taltio"] = (meta.get("Taltionumero") or meta.get("Taltio") or "").strip() or None
    d["date"] = iso(meta.get("Antopäivä", ""))
    d["ecli"] = (re.search(r"ECLI:[A-Z]{2}:[A-Z0-9]+:\d{4}:[\w.]+", meta.get("ECLI-tunnus", "")) or [None])[0]
    d["ref"] = d["ref"] or (meta.get("Ennakkopäätösnumero") or meta.get("Julkaisunumero") or "").strip() or None
    if meta.get("Asianomaiset"):
        d["parties"] = meta["Asianomaiset"].strip()
    if meta.get("Käsiteltävät asiat"):
        d["category"] = meta["Käsiteltävät asiat"].strip()
    ref_lines = [l for l in meta.get("Sovellettu lainsäädäntö", "").split("\n") if l.strip()]
    # headnote: paragraphs after the meta block until a section heading; short "§" lines are statute references
    abstract = []
    while i < len(lines):
        l = lines[i]
        low = l.lower().rstrip(":")
        if low in STOP or low.startswith("asian käsittely") or re.fullmatch(r"[A-ZÄÖÅ0-9 ,\-–]{8,}", l) or OUTCOME_HEAD.match(l):
            break
        if len(l) < 110 and REF_LINE.match(l) and "§" in l:
            ref_lines.append(l)
        elif abstract and len(l) < 40 and not l.endswith("."):
            pass  # "Verovuodet 2020 ja 2021", "Äänestys" – labels after the headnote
        elif sum(len(a) for a in abstract) < 1800:
            abstract.append(l)
        i += 1
        if i - start > 60:
            break
    d["abstract"] = re.sub(r"\s+", " ", " ".join(abstract)).strip()
    d["refLines"] = ref_lines
    # operative part (needed for MAO rulings, which have no headnote)
    for j in range(len(lines) - 1, start, -1):
        if OUTCOME_HEAD.match(lines[j]):
            seg = []
            for l in lines[j + 1:j + 12]:
                if OUTCOME_END.match(l):
                    break
                seg.append(l)
            d["outcome"] = re.sub(r"\s+", " ", " ".join(seg)).strip()[:700]
            break
    body = t[t.find(lines[start]) if start < len(lines) else 0:]
    d["citedCases"] = [c for c in cited_cases(body) if c != ref]
    return d


# ---------------------------------------------------------------- Finlex (Next.js RSC payload)

def _rsc_rows(page: str) -> dict:
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', page, re.S)
    parts = []
    for c in chunks:
        try:
            parts.append(json.loads('"' + c + '"'))
        except ValueError:
            parts.append(c)
    rows = {}
    for line in "".join(parts).split("\n"):
        m = re.match(r"^([0-9a-f]+):(.*)$", line)
        if not m:
            continue
        key, body = m.groups()
        if body[:1] in "[{":
            try:
                rows[key] = json.loads(body)
            except ValueError:
                pass
        elif body.startswith("T") and "," in body:
            rows[key] = body.split(",", 1)[1]
    return rows


def _walk(node, rows, depth=0):
    if depth > 80:
        return
    if isinstance(node, list):
        if len(node) == 4 and node[0] == "$" and isinstance(node[1], str):
            yield node
            yield from _walk(node[3], rows, depth + 1)
        else:
            for x in node:
                yield from _walk(x, rows, depth + 1)
    elif isinstance(node, dict):
        for v in node.values():
            yield from _walk(v, rows, depth + 1)
    elif isinstance(node, str) and node.startswith("$L") and node[2:] in rows:
        yield from _walk(rows[node[2:]], rows, depth + 1)


def _rsc_text(node, rows, depth=0) -> str:
    if depth > 80 or node is None or isinstance(node, bool):
        return ""
    if isinstance(node, str):
        if node.startswith("$L") and node[2:] in rows:
            return _rsc_text(rows[node[2:]], rows, depth + 1)
        return "" if node.startswith("$") else node
    if isinstance(node, (int, float)):
        return str(node)
    if isinstance(node, list):
        if len(node) == 4 and node[0] == "$":
            props = node[3] if isinstance(node[3], dict) else {}
            if node[1] == "time" and props.get("dateTime"):
                return props["dateTime"]
            return _rsc_text(props.get("children"), rows, depth + 1)
        return re.sub(r"\s+", " ", " ".join(_rsc_text(x, rows, depth + 1) for x in node)).strip()
    if isinstance(node, dict):
        return _rsc_text(node.get("children"), rows, depth + 1)
    return ""


def finlex_parse_list(page: str) -> list[dict]:
    """Year listing -> [{number, href, keywords}] newest first (only /oikeuskaytanto/ links; the sidebar lists statutes)."""
    rows = _rsc_rows(page)
    out, seen = [], set()
    for root in rows.values():
        for el in _walk(root, rows):
            props = el[3] if isinstance(el[3], dict) else {}
            if el[1] != "li" or not str(props.get("className", "")).endswith("documentListItem"):
                continue
            href = next((e[3].get("href") for e in _walk(el, rows) if isinstance(e[3], dict) and e[3].get("href")), None)
            if not href or "/oikeuskaytanto/" not in href or href in seen:
                continue
            seen.add(href)
            number = next((_rsc_text(e, rows) for e in _walk(el, rows) if e[1] == "h3"), None)
            kws = [_rsc_text(c, rows) for e in _walk(el, rows)
                   if e[1] == "div" and isinstance(e[3], dict) and str(e[3].get("className", "")).endswith("keywordChips")
                   for c in (e[3].get("children") or []) if isinstance(c, list)]
            out.append({"number": number, "href": href, "keywords": [k for k in kws if k]})
    return out


def finlex_parse_decision(page: str) -> dict:
    """Decision page -> {meta: {Asiasanat, Antopäivä, Diaarinumero, Taltio, ECLI-tunnus, Hovioikeus, Asianumero…},
    pageTitle, keywords, refLines, abstract, citedCases}."""
    rows = _rsc_rows(page)
    meta, paras, keywords, seen = {}, [], [], set()
    for root in rows.values():
        for el in _walk(root, rows):
            tag, props = el[1], el[3] if isinstance(el[3], dict) else {}
            if tag == "dl":
                for item in props.get("children") or []:
                    if isinstance(item, list) and len(item) == 4 and isinstance(item[3], dict):
                        pair = item[3].get("children") or []
                        dt_ = next((_rsc_text(x, rows) for x in pair if isinstance(x, list) and len(x) == 4 and x[1] == "dt"), None)
                        dd = next((x for x in pair if isinstance(x, list) and len(x) == 4 and x[1] == "dd"), None)
                        if dt_ and dd is not None and dt_ not in meta:  # the Finnish <dl> comes first; the Swedish one repeats the keys
                            meta[dt_] = _rsc_text(dd, rows)
            elif tag == "span" and props.get("className") == "highlightable":
                t = props.get("children")
                if isinstance(t, str) and t not in seen:
                    seen.add(t)
                    paras.append(t)
            elif tag == "div" and str(props.get("className", "")).endswith("keywordChips"):
                for chip in props.get("children") or []:
                    if isinstance(chip, list) and len(chip) == 4:
                        kw = _rsc_text(chip, rows)
                        if kw and kw not in keywords:
                            keywords.append(kw)
    m = re.search(r"<title>(.*?)</title>", page, re.S)
    ref_lines, abstract = [], []
    for p in paras[:40]:
        low = p.lower().rstrip(":")
        if low in STOP or low.startswith("asian käsittely") or re.fullmatch(r"[A-ZÄÖÅ0-9 ,\-–]{8,}", p):
            break
        if len(p) < 110 and REF_LINE.match(p) and "§" in p:
            ref_lines.append(p)
        elif sum(len(a) for a in abstract) < 1800:
            abstract.append(p)
    return {"pageTitle": html.unescape(m.group(1)).strip() if m else None, "meta": meta,
            "keywords": keywords or split_keywords(meta.get("Asiasanat", "")),
            "refLines": ref_lines, "abstract": re.sub(r"\s+", " ", " ".join(abstract)).strip(),
            "citedCases": cited_cases(" ".join(paras))}


def finlex_get(url: str, delay: float) -> str:
    r = http("GET", url, headers=UA, timeout=60)
    time.sleep(delay)
    if r.status_code == 404:
        return ""
    r.raise_for_status()
    return r.text


def finlex_years(keep_days: int) -> list[int]:
    first = (TODAY - dt.timedelta(days=keep_days)).year
    return list(range(first, TODAY.year + 1))


def finlex_list_court(section: str, keep_days: int, delay: float) -> list[dict]:
    """All decisions of the current (and, near New Year, previous) year from the Finlex year listings."""
    out = []
    for y in finlex_years(keep_days):
        page = finlex_get(f"{FINLEX}/fi/oikeuskaytanto/{section}/{y}", delay)
        if not page:
            continue
        for it in finlex_parse_list(page):
            if f"/oikeuskaytanto/{section}/" not in it["href"]:
                continue
            num = it.get("number") or ""
            it["date"] = iso(num)  # HO/HaO numbers carry the date ("Helsingin HO 7.9.2026 1064 0647"); the supreme courts' don't
            it["year"] = y
            out.append(it)
    return out


# ---------------------------------------------------------------- per-court drivers

def _normalise(court: str, ccfg: dict, cfg: dict, resolver: StatuteResolver, base: dict, page: dict | None, *,
               finlex_page: bool = False, href: str | None = None) -> dict:
    """Merge listing data and the parsed decision page into the compact cache record."""
    page = page or {}
    if finlex_page:
        meta = page.get("meta", {})
        date = (meta.get("Antopäivä") or "")[:10] or base.get("date")
        d = {"ref": base.get("ref"), "date": date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or "") else iso(date or ""),
             "diaari": meta.get("Diaarinumero") or None, "taltio": meta.get("Taltio") or meta.get("Ratkaisunumero") or None,
             "ecli": (re.search(r"ECLI:[A-Z]{2}:[A-Z0-9]+:\d{4}:[\w.]+", meta.get("ECLI-tunnus", "")) or [None])[0],
             "keywords": base.get("keywords") or page.get("keywords") or [], "abstract": page.get("abstract", ""),  # listing chips split the keywords; the page's <dl> joins them with spaces
             "refLines": page.get("refLines", []), "citedCases": page.get("citedCases", []), "outcome": ""}
        if meta.get("Asianumero"):
            d["caseNo"] = meta["Asianumero"]
        if court in ("HO", "HaO"):
            m = re.match(r"^(.*?\b(?:HO|HAO|hovioikeus|hallinto-oikeus))\b", base.get("ref") or "", re.I)
            d["courtUnit"] = (meta.get("Hovioikeus") or meta.get("Hallinto-oikeus") or (m.group(1) if m else "")).strip() or None
    else:
        d = dict(page)
        d["ref"] = d.get("ref") or base.get("ref")
        d["date"] = d.get("date") or base.get("date")
        d["keywords"] = d.get("keywords") or base.get("keywords") or []
    refs, raw = resolver.resolve(d.pop("refLines", []) or [], (d.get("abstract") or "") + " " + (d.get("outcome") or ""))
    rec = {"court": court, "kind": ccfg.get("kind") or "Ratkaisu", "ref": d.get("ref"), "date": d.get("date"), "ecli": d.get("ecli"),
           "diaari": d.get("diaari"), "taltio": d.get("taltio"), "keywords": [k for k in d.get("keywords") or [] if k][:12],
           "abstract": (d.get("abstract") or "")[:1500], "outcome": (d.get("outcome") or "")[:600] or None,
           "statutes": refs, "rawRefs": raw, "citedCases": [c for c in d.get("citedCases") or [] if c != d.get("ref")], "url": base.get("url"),
           "finlexUrl": (FINLEX + href) if href else finlex_url(court, cfg, d.get("ref") or "", d.get("date")),
           "fetched": TODAY.isoformat()}
    for k in ("parties", "category", "caseNo", "courtUnit"):
        if d.get(k):
            rec[k] = d[k]
    if court == "KHO" and rec["ref"] and not REF_RE["KHO"].search(rec["ref"]):
        rec["kind"] = "Muu julkaistu päätös"
    return {k: v for k, v in rec.items() if v not in (None, "", [])}


def run_site_court(court: str, ccfg: dict, cfg: dict, resolver: StatuteResolver, decisions: dict, cutoff: str) -> tuple[int, int]:
    """KKO/TT/VakO (RSS), KHO (archive) and MAO (category pages): returns (listed, new)."""
    src = ccfg.get("source")
    if src == "rss":
        listed = fetch_rss(ccfg["host"], court)
    elif src == "kho":
        listed = fetch_lift_list(ccfg["archive"], r"https://www\.kho\.fi/paatokset/kho\d+/", "KHO")
        if ccfg.get("muut") and ccfg.get("muut_archive"):
            listed += fetch_lift_list(ccfg["muut_archive"], r"https://www\.kho\.fi/paatokset/kho-[\d\-]+/", "KHO")
    elif src == "mao":
        listed = []
        for cat, url in (ccfg.get("categories") or {}).items():
            for it in fetch_lift_list(url, r"https://www\.markkinaoikeus\.fi/ratkaisut/ratkaisujen-arkisto/mao\d+-\d{4}/", "MAO"):
                it["category"] = cat
                listed.append(it)
    else:
        raise RuntimeError(f"tuntematon lähde {src}")
    new = 0
    for it in listed:
        rid = make_id(court, it["ref"])
        if rid in decisions or (it.get("date") and it["date"] < cutoff):
            continue
        try:
            page = parse_site_decision(http("GET", it["url"], headers=UA, timeout=60).text, court)
        except Exception as e:  # noqa: BLE001
            log(f"warn: {court} {it['ref']}: {e}")
            continue
        rec = _normalise(court, ccfg, cfg, resolver, it, page)
        if court == "MAO":
            rec["category"] = it.get("category") or rec.get("category")
            if rec.get("category") not in ("ipr", "markkinaoikeudellinen") and not any(
                    k in (rec.get("category") or "").lower() for k in ("teollis", "tekijän", "markkinaoikeudelli")):
                continue  # a procurement/competition ruling that slipped into the feed – fetch_mao.py's domain
        if rec.get("date") and rec["date"] < cutoff:
            continue
        decisions[rid] = rec
        new += 1
        time.sleep(SITE_DELAY)
    return len(listed), new


def run_finlex_court(court: str, ccfg: dict, cfg: dict, resolver: StatuteResolver, decisions: dict, cutoff: str, budget: list[int]) -> tuple[int, int]:
    """HO/HaO (and the fallback for the other courts) through the Finlex year listings; budget[0] = pages left this run."""
    fcfg = cfg.get("finlex") or {}
    delay = float(fcfg.get("delay", 1.5))
    listed = finlex_list_court(ccfg["finlex"], int(cfg.get("keep_days", 120)), delay)
    new = 0
    for it in listed:
        ref = it.get("number") or it["href"].rsplit("/", 1)[-1]
        rid = make_id(court, ref, it["href"])
        if rid in decisions:
            continue
        if it.get("date") and it["date"] < cutoff:
            continue
        if budget[0] <= 0:
            break
        budget[0] -= 1
        try:
            page = finlex_get(FINLEX + it["href"], delay)
            parsed = finlex_parse_decision(page) if page else None
        except Exception as e:  # noqa: BLE001
            log(f"warn: finlex {court} {ref}: {e}")
            continue
        base = {"ref": ref, "url": FINLEX + it["href"], "date": it.get("date"), "keywords": it.get("keywords")}
        rec = _normalise(court, ccfg, cfg, resolver, base, parsed, finlex_page=True, href=it["href"])
        rec["url"] = FINLEX + it["href"]
        if not rec.get("date"):
            continue
        if rec["date"] < cutoff:
            if not it.get("date"):
                break  # supreme-court listings are newest first and dateless: everything below is older
            continue
        decisions[rid] = rec
        new += 1
    return len(listed), new


def main():
    cfg = load_config()
    keep_days = int(cfg.get("keep_days", 120))
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    resolver = StatuteResolver(cfg)
    old = load_json(OUT, {}) or {}
    decisions: dict[str, dict] = dict(old.get("decisions") or {})
    health: dict[str, dict] = dict(old.get("health") or {})
    budget = [int((cfg.get("finlex") or {}).get("max_pages_per_run", 40))]
    courts = {c: v for c, v in (cfg.get("courts") or {}).items() if v.get("enabled")}
    failed, dropped = [], []
    for court, ccfg in courts.items():
        prev = health.get(court) or {}
        t0 = time.time()
        try:
            if ccfg.get("source") == "finlex":
                n, new = run_finlex_court(court, ccfg, cfg, resolver, decisions, cutoff, budget)
            else:
                try:
                    n, new = run_site_court(court, ccfg, cfg, resolver, decisions, cutoff)
                except Exception as e:  # noqa: BLE001
                    if not (ccfg.get("fallback_finlex") and ccfg.get("finlex")):
                        raise
                    log(f"warn: {court}: oma sivusto ei vastaa ({e}); käytetään Finlexin vuosiluetteloa")
                    n, new = run_finlex_court(court, ccfg, cfg, resolver, decisions, cutoff, budget)
        except Exception as e:  # noqa: BLE001
            failed.append(court)
            health[court] = {**prev, "ok": False, "error": str(e)[:300], "checked": TODAY.isoformat()}
            log(f"warn: {court}: {e}")
            continue
        if n == 0 and int(prev.get("n") or 0) > 0:
            dropped.append(court)
            health[court] = {**prev, "ok": False, "error": "luettelo tyhjä (aiemmin %d riviä) – sivun rakenne on ehkä muuttunut" % prev["n"],
                             "checked": TODAY.isoformat()}
            log(f"warn: {court}: luettelo palautti 0 ratkaisua, aiemmin {prev['n']}")
            continue
        health[court] = {"ok": True, "error": None, "n": n, "new": new, "checked": TODAY.isoformat()}
        log(f"{court}: {n} ratkaisua luettelossa, {new} uutta haettu ({time.time() - t0:.0f} s)")
    for court in list(health):
        if court not in courts:
            health.pop(court)
    decisions = {k: v for k, v in decisions.items() if (v.get("date") or "9999") >= cutoff}
    save_json(OUT, {"fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "health": health, "decisions": decisions}, compact=True)
    per_court = {c: sum(1 for d in decisions.values() if d["court"] == c) for c in courts}
    log(f"oikeuskäytäntö: {len(decisions)} ratkaisua välimuistissa {per_court} -> {OUT}")
    if budget[0] <= 0:
        log("oikeuskäytäntö: Finlex-sivukiintiö täyttyi, loput haetaan seuraavalla ajolla")
    if courts and len(failed) == len(courts):
        raise RuntimeError(f"oikeuskäytäntö: kaikki lähteet epäonnistuivat: {failed}")
    if dropped:
        raise RuntimeError(f"oikeuskäytäntö: {dropped} palautti 0 ratkaisua vaikka aiemmin löytyi – rakenne muuttunut? (muut lähteet päivitetty)")


if __name__ == "__main__":
    main()
