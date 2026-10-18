"""HE-diff: what a government proposal changes in the law text, section by section, in two steps –
voimassa oleva laki → HE:n ehdotus (the ministry's rinnakkaistekstit) and HE:n ehdotus →
valiokunnan mietintö (the committee's marked amendments). This script only collects the texts
into data/cache/hediff.json; build_hediff.py computes the word diffs for the page.

What the sources really look like (probed 2026-10-18 against 17 amending HEs of 2025–2026):

* avoindata.eduskunta.fi VaskiData, `rows?columnName=Eduskuntatunnus&columnValue=HE n/yyyy vp`
  (filtered lookups only – the unfiltered listings are refused from GitHub's network). The HE
  has two rows: the käsittelytiedot row and the document row (`SanomatyyppiNimi` =
  `VASKI_JULKVP_GovernmentProposal_fi`, body `he:HallituksenEsitys`). The document row carries
  the lakiehdotukset as `asi:SaadosOsa/saa:Saados` (per law: `SaadosNimeke`, `Johtolause`,
  `Pykalisto` with `Pykala@identifiointiTunnus="5 §"`, `SaadosOtsikkoKooste`, momentit as
  `MomenttiKooste`/`KohdatMomentti`, `Katkoviiva` for omitted momentit, `Aukko` for the blank
  date in the voimaantulo clause). **The rinnakkaistekstit are NOT in the XML.** None of the 17
  HEs had a parallel-text appendix: `asi:LiiteOsa` occurs in 4 of them and holds asetusluonnokset
  (`saa:Saados` with `SaadostyyppiKooste` "Valtioneuvoston asetus"), a treaty text (`LiiteNimi`
  "Sopimusteksti") or a `tau:table` ("Taulukko"); the Finlex HE page (finlex.fi/fi/hallituksen-
  esitykset/yyyy/n, Next.js payload) has no appendix either. The parallel texts exist only in the
  official PDF, as the appendix "Liite / Rinnakkaistekstit" after the lakiehdotukset (and before
  any asetusluonnos appendix).
* The PDF: `Attachment` table by the row's `AttachmentGroupId` (column 6) → `Url` on S3
  (`…/vaski%2FHE-100%2B2026-vp.pdf`, 2–13 MB; eduskunta.fi/pdf/HE+n/yyyy answered 503 here).
  Layout (pdfplumber words; the same Word template in every HE seen): A4 595×842 pt, body 11 pt
  Times. The appendix starts with right-aligned "Liite" + "Rinnakkaistekstit", then per law a
  bold "N." (x≈89, the lakiehdotus number – new laws have no parallel text, so numbers may skip),
  a centred bold "Laki" title + name line(s), the Johtolause as full-width prose, and the
  two-column table whose header line "Voimassa oleva laki | Ehdotus" (italic) repeats at the
  top of every following page. Columns: left x 94–296, right x 306–508 (gap 10 pt around the page
  centre; no word straddles it except page numbers, which are centred at the bottom). Inside a
  cell: "5 §" centred, the heading centred and italic on the next line(s), momentit as justified
  paragraphs with an 8.5 pt first-line indent, "— — — — —" katkoviiva rows (14 dash words per
  column, often spanning both columns), "N luku" + heading rows for chapters. Row pairing is by
  vertical position: both cells of a row start at the same `top`, so "22 § | 22 §" pairs, a new
  section is "(uusi) | 27 a §" (left cell holds only the marker) and a repealed one "10 § |
  (kumotaan)". The right column prints proposed changes in italics – not used, the word diff is
  computed instead. The voimaantulo clause follows a short "———" rule in the right column. No
  automatic hyphenation (line-end hyphens are real: "yritys- ja", "Senaatti-kiinteistöt").
  Validation: the right column re-joined from the PDF equals the XML `SaadosOsa` text of the
  same pykälä (difflib ratio 1.00 for 36 of 48 sections of three HEs; the rest differ only by
  katkoviiva markers and headings).
* The mietintö row (`columnValue = "HaVM n/yyyy vp"`, `SanomatyyppiNimi` =
  `VASKI_JULKVP_CommitteeReport_fi`, body `vml:Mietinto`) reprints the amended lakiehdotukset
  (often all of them) as `SaadosOsa/Saados`; the committee's text is marked inline with
  `saa1:MuutosTeksti` (inserted/changed) and `saa1:PoistoTeksti` (deleted). Replaced words are
  marked as MuutosTeksti only (VaVM 22/2026: "on <MuutosTeksti>20</MuutosTeksti>." where the HE
  said "on 18."), so the HE side of that diff is taken from the HE XML section, and the
  marker-stripped report text is used only when the HE XML lacks the section (a committee-added
  pykälä). Only sections that carry markers are kept; "(Uusi)" in the tunnus flags a new one.

Cache (data/cache/hediff.json, ≤ ~60 kB per HE):
  {"fetched", "he": {"118/2026": {"fetched", "created", "pdf": ok|none|error|…, "laws": [{"n", "name",
   "kind": muutos|uusi|kumoaminen, "parallel": bool, "sections": [{"id": "22 §", "heading", "old"|null,
   "new"|null, "headingOld"?}]}], "report": {"tunnus", "date", "laws": [{"name", "sections": [{"id",
   "heading", "he", "committee", "added"?, "heFrom"?}]}]} | null}}}
Texts are plain, paragraphs joined with "\n"; only sections whose texts differ are stored; a
section longer than 6 000 characters is cut with a "[…]" marker.

Selection: HEs of data/cache/eduskunta.json that are not final (or were confirmed less than 60
days ago) and were given within 540 days. Each HE is fetched once (the HE text does not change);
the PDF is retried after a failure; the report is (re)fetched when the mietintö known to
data/cache/vaski.json (asia == the HE, kind mietintö) is new or re-published with another date.
At most 120 HE document fetches per run, ≤ 1 request/s, 25 minutes; per-HE failures are logged
and the run raises only when the API itself does not answer.
"""
from __future__ import annotations

import datetime as dt
import difflib
import io
import json
import re
import time
import xml.etree.ElementTree as ET

from common import CACHE_DIR, TODAY, days_ago, http, load_json, log, save_json
from fetch_vaski import strip_ns

VASKI_ROWS = "https://avoindata.eduskunta.fi/api/v1/tables/VaskiData/rows"
ATTACHMENT_ROWS = "https://avoindata.eduskunta.fi/api/v1/tables/Attachment/rows"
OUT = CACHE_DIR / "hediff.json"

MAX_HE = 120              # HE document fetches per run (the rest next run)
TIME_BUDGET = 25 * 60     # seconds; stop starting new HEs after this
WINDOW_DAYS = 540         # HE given within this many days
CONFIRMED_DAYS = 60       # final HEs stay this long after vahvistus
PACE = 1.0                # seconds between requests
SECTION_CAP = 6_000       # characters per section text
HE_CAP = 60_000           # bytes per HE in the cache
PDF_RETRY_DAYS = 14       # a failed PDF is tried again after this
PDF_MAX_BYTES = 60_000_000
PDF_SCAN_PAGES = 600      # pages scanned backwards for the appendix title

# momentti-level blocks of the Vaski law text: padded with spaces when flattened
BLOCKS = frozenset({"MomenttiKooste", "KohdatMomentti", "MomenttiJohdantoKooste", "MomenttiKohtaKooste",
                    "MomenttiAlakohtaKooste", "Katkoviiva", "Aukko", "SaadosKappaleKooste"})
MOM_TAGS = ("MomenttiKooste", "KohdatMomentti")
EDITORIAL = re.compile(r"\((?:Uusi|Poist\.?)(?: \d+ mom\.?)?\)")  # committee labels '(Uusi 3 mom.)', '(Poist.)'
HE_NUM = re.compile(r"^(\d+)/(\d{4})$")

# PDF layout
SECTION_RE = re.compile(r"^(\d+)\s?([a-zåäö]{1,2})?\s?§(?:\s*\((uusi|kumotaan|uusi \d+ mom\.?)\))?\s*$", re.IGNORECASE)
CHAPTER_RE = re.compile(r"^(\d+)\s?([a-zåäö])?\s?luku\s*$", re.IGNORECASE)
DASH_RE = re.compile(r"^[—–\-\s]+$")
LAWNUM_RE = re.compile(r"^\d+\.$")
PAGENUM_RE = re.compile(r"^\d{1,4}$")
RUNNING_HEADER_RE = re.compile(r"^(HE|RP) \d+/\d{4} (vp|rd)$")
JOHTOLAUSE_RE = re.compile(r"^((Eduskunnan|Valtioneuvoston|Tasavallan presidentin) päätöksen mukaisesti|kumotaan|muutetaan|lisätään|säädetään)\b", re.IGNORECASE)
UUSI_RE = re.compile(r"^\(?uusi(?: \d+ mom\.?)?\)?$", re.IGNORECASE)  # '(uusi)', 'Uusi', '(uusi 2 mom.)'
KUMOTAAN_RE = re.compile(r"^\(kumotaan\)$", re.IGNORECASE)
KEEP_HYPHEN_SPACE = {"ja", "tai", "sekä", "eli", "että", "taikka"}


# ----------------------------------------------------------------------------- text helpers
def tidy(s: str) -> str:
    """Collapse whitespace, normalise dashes, undo the spaces that element padding leaves around punctuation."""
    s = re.sub(r"[‒–—―]", "–", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:!?)\]])", r"\1", s)
    s = re.sub(r"([(\[])\s+", r"\1", s)
    return s


def sec_key(label: str) -> str:
    """'27 a § ', '27a§', '46 a § (Uusi)' -> '27a§' / '46a§' (the matching key); 'Voimaantulo' -> 'voimaantulo'."""
    s = re.sub(r"\(.*?\)", "", (label or "").lower())
    return re.sub(r"\s+", "", s)


def sec_label(label: str) -> str:
    """Canonical display form: '32 § ' -> '32 §', '6b §' -> '6 b §', '46 a § (Uusi)' -> '46 a §'."""
    m = re.match(r"^\s*(\d+)\s*([a-zåäö]{1,2})?\s*§", (label or "").lower())
    if m:
        return f"{m.group(1)} {m.group(2) + ' ' if m.group(2) else ''}§"
    return tidy(re.sub(r"\(.*?\)", "", label or "")) or "?"


def chap_key(label: str | None) -> str | None:
    m = re.match(r"^\s*(\d+)\s*([a-zåäö])?\s*luku|^\s*(\d+)\s*([a-zåäö])?\s*luvu", (label or "").lower())
    if m and m.group(3):
        return m.group(3) + (m.group(4) or "")
    return (m.group(1) + (m.group(2) or "")) if m else None


def norm_name(name: str | None) -> str:
    s = re.sub(r"[^a-z0-9åäö§ ]", " ", (name or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def truncate(text: str | None, cap: int) -> str | None:
    if text is None or len(text) <= cap:
        return text
    return text[:cap].rstrip() + " […]"


def doc_size(doc) -> int:
    return len(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


# ----------------------------------------------------------------------------- Vaski XML: law text
def node_text(el: ET.Element | None, drop: frozenset = frozenset()) -> str:
    """itertext() with the elements in `drop` omitted (their tails kept) and block elements padded."""
    if el is None:
        return ""
    buf = [el.text or ""]
    for c in el:
        if c.tag in drop:
            pass
        elif c.tag in BLOCKS:
            buf.append(" " + node_text(c, drop) + " ")
        else:
            buf.append(node_text(c, drop))
        buf.append(c.tail or "")
    return "".join(buf)


def block_text(el: ET.Element | None, drop: frozenset = frozenset()) -> str:
    return tidy(node_text(el, drop))


def spaced_text(el: ET.Element | None, drop: frozenset = frozenset()) -> str:
    """Every element boundary becomes a space ('Laki' + 'passilain muuttamisesta'); elements in `drop` are omitted."""
    if el is None:
        return ""
    parts = [el.text or ""]
    for c in el:
        if c.tag not in drop:
            parts.append(spaced_text(c, drop))
        parts.append(c.tail or "")
    return tidy(" ".join(parts))


def pykalat_of(container: ET.Element | None, chapter: str | None = None) -> list[tuple[ET.Element, str | None]]:
    """(Pykala, chapter label) in document order, descending into Luku/Osa/Pykalisto wrappers."""
    out: list[tuple[ET.Element, str | None]] = []
    if container is None:
        return out
    for c in container:
        if c.tag == "Pykala":
            out.append((c, chapter))
        elif c.tag in ("Luku", "Osa", "Pykalisto"):
            lbl = chapter
            if c.tag == "Luku":
                lbl = tidy(c.get("identifiointiTunnus") or c.findtext("LukuTunnusKooste") or "") or chapter
            out.extend(pykalat_of(c, lbl))
    return out


def pykala_ident(p: ET.Element) -> tuple[str, str, bool]:
    """-> (key, label, is_voimaantulo)."""
    ident = tidy(p.get("identifiointiTunnus") or p.findtext("PykalaTunnusKooste") or "")
    if p.get("pykalaLuokitusKoodi") == "VoimaantuloSaannos" or ident.lower().startswith("voimaantulo"):
        return "voimaantulo", "Voimaantulo", True
    return sec_key(ident), sec_label(ident), False


def paragraphs_of(p: ET.Element, drop: frozenset = frozenset()) -> list[str]:
    """The printed momentit of a Pykala, one string each (kohdat lists joined); Katkoviiva -> '— — —'."""
    out = []
    for c in p:
        if c.tag in MOM_TAGS:
            t = tidy(EDITORIAL.sub(" ", block_text(c, drop)))
            if t:
                out.append(t)
        elif c.tag == "Katkoviiva":
            out.append("— — —")
    return out


def law_kind(name: str, johtolause: str) -> str:
    low = (name or "").lower()
    if re.search(r"kumoamisesta\s*$", low):
        return "kumoaminen"
    if "muuttamisesta" in low or re.search(r"\b(muutetaan|lisätään|kumotaan)\b", (johtolause or "").lower()):
        return "muutos"
    return "uusi"


def law_number(s: ET.Element, i: int) -> str:
    return tidy(s.get("identifiointiTunnus") or "") or tidy(s.findtext("LakiehdotusNumeroKooste") or "").rstrip(".") or str(i)


def parse_he_xml(root: ET.Element) -> list[dict]:
    """HallituksenEsitys -> [{n, name, kind, johtolause, sections: [{key, id, chapter, heading, text, voimaantulo}]}]."""
    he = root.find(".//HallituksenEsitys")
    if he is None:
        return []
    laws = []
    for so in he.findall("SaadosOsa"):
        for i, s in enumerate(so.findall("Saados"), 1):
            name = spaced_text(s.find("SaadosNimeke")) or "Laki"
            jl = spaced_text(s.find("Johtolause"))
            secs = []
            for p, chapter in pykalat_of(s.find("Pykalisto") if s.find("Pykalisto") is not None else s):
                key, label, voimaantulo = pykala_ident(p)
                if not key:
                    continue
                secs.append({"key": key, "id": label, "chapter": chapter, "heading": block_text(p.find("SaadosOtsikkoKooste")) or None,
                             "text": "\n".join(paragraphs_of(p)), "voimaantulo": voimaantulo})
            laws.append({"n": law_number(s, i), "name": name, "kind": law_kind(name, jl), "johtolause": jl, "sections": secs})
    return laws


# ----------------------------------------------------------------------------- Vaski XML: committee report
def parse_report_xml(root: ET.Element) -> dict | None:
    """Mietinto -> {tunnus, date, asia, laws: [{n, name, johtolause: {base, clean}|None,
    sections: [{key, id, chapter, heading, headingBase, base, clean, new}]}]} – only sections with markers.
    `base` is the text without MuutosTeksti (the HE text as the committee reproduced it), `clean` the
    committee's text (without PoistoTeksti)."""
    doc = root.find(".//Mietinto")
    if doc is None:
        return None
    meta = root.find(".//JulkaisuMetatieto")
    sign = doc.find("./OsallistujaOsa/PaivaysKooste")
    date = (sign.get("allekirjoitusPvm") if sign is not None else None) or (meta.get("laadintaPvm") if meta is not None else None) \
        or doc.get("laadintaPvm")
    drop_m, drop_p = frozenset({"MuutosTeksti"}), frozenset({"PoistoTeksti"})
    laws = []
    for so in doc.findall("./SaadosOsa"):  # the committee's own text, not the vastalause versions
        for i, s in enumerate(so.findall("Saados"), 1):
            jl = s.find("Johtolause")
            jl_out = None
            if jl is not None and (jl.find(".//MuutosTeksti") is not None or jl.find(".//PoistoTeksti") is not None):
                jl_out = {"base": block_text(jl, drop_m), "clean": block_text(jl, drop_p)}
            secs = []
            for p, chapter in pykalat_of(s.find("Pykalisto") if s.find("Pykalisto") is not None else s):
                if p.find(".//MuutosTeksti") is None and p.find(".//PoistoTeksti") is None:
                    continue
                key, label, _ = pykala_ident(p)
                if not key:
                    continue
                h = p.find("SaadosOtsikkoKooste")
                secs.append({"key": key, "id": label, "chapter": chapter,
                             "heading": tidy(EDITORIAL.sub(" ", block_text(h, drop_p))) or None,
                             "headingBase": tidy(EDITORIAL.sub(" ", block_text(h, drop_m))) or None,
                             "base": "\n".join(paragraphs_of(p, drop_m)), "clean": "\n".join(paragraphs_of(p, drop_p)),
                             "new": "(uusi)" in ((p.get("identifiointiTunnus") or "") + " " + block_text(p.find("PykalaTunnusKooste"))).lower()})
            if secs or jl_out:
                laws.append({"n": law_number(s, i), "name": spaced_text(s.find("SaadosNimeke"), drop_p) or None, "johtolause": jl_out, "sections": secs})
    return {"tunnus": doc.get("eduskuntaTunnus"), "date": date,
            "asia": (doc.findtext("./IdentifiointiOsa/Vireilletulo/EduskuntaTunnus") or "").strip() or None, "laws": laws}


# ----------------------------------------------------------------------------- PDF: rinnakkaistekstit
def join_lines(lines: list[str]) -> str:
    """Join the lines of one paragraph. A line-end hyphen is a real hyphen in these PDFs (no automatic
    hyphenation): 'yritys-' + 'ja' -> 'yritys- ja', 'Senaatti-' + 'kiinteistöjen' -> 'Senaatti-kiinteistöjen'."""
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if not out:
            out = ln
        elif out.endswith("-") and len(out) > 1 and ln[:1].islower() and ln.split()[0].lower() not in KEEP_HYPHEN_SPACE:
            out += ln
        else:
            out += " " + ln
    return out


def words_to_lines(words: list[dict], tol: float = 2.5) -> list[list[dict]]:
    words = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
    lines: list[list[dict]] = []
    for w in words:
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    for ln in lines:
        ln.sort(key=lambda w: w["x0"])
    return lines


def is_italic(words: list[dict]) -> bool:
    return bool(words) and all(re.search(r"italic|oblique", w.get("fontname") or "", re.IGNORECASE) for w in words)


class Column:
    """One column (voimassa oleva / ehdotus) of a law's parallel-text table, fed line by line."""

    def __init__(self, base_x: float):
        self.base = base_x  # left edge of the column text
        self.sections: list[dict] = []
        self.cur: dict | None = None
        self.expect_heading = False
        self.heading_target: dict | None = None
        self.chapter: str | None = None
        self.para: list[str] | None = None

    def new_section(self, sid: str, page: int, top: float, kind: str = "section") -> None:
        self.flush()
        self.cur = {"id": sid, "key": sec_key(sid), "chapter": self.chapter, "heading": [], "paras": [], "page": page, "top": top,
                    "kind": kind, "mark": None}
        self.sections.append(self.cur)
        self.expect_heading = kind == "section"
        self.heading_target = self.cur

    def flush(self) -> None:
        if self.para and self.cur is not None:
            txt = tidy(join_lines(self.para))
            if txt and not UUSI_RE.match(txt):
                self.cur["paras"].append(txt)
        self.para = None

    def empty(self) -> bool:
        return self.cur is not None and not self.cur["paras"] and not self.para

    def feed(self, line: dict) -> None:
        """line: {words, page, top, edges, inject?} – edges = x1 of the column's words on that page (its right edge)."""
        words, page, top = line["words"], line["page"], line["top"]
        text = " ".join(w["text"] for w in words).strip()
        if not text:
            return
        edges = line.get("edges") or []
        right_edge = max(edges) if len(edges) >= 20 else self.base + 201.0
        if line.get("inject"):  # a section start that the other column has on this row ('10 § | (kumotaan)', '(uusi) | 27 a §')
            self.new_section(line["inject"], page, top)
            self.expect_heading = False
        x0, x1 = words[0]["x0"], words[-1]["x1"]
        if DASH_RE.match(text):
            if len(words) >= 4:  # '— — — — —' katkoviiva: omitted momentit
                self.flush()
                if self.cur is not None:
                    self.cur["paras"].append("— — —")
            elif not any(s["kind"] == "voimaantulo" for s in self.sections):  # '———' before the entry-into-force clause
                self.new_section("Voimaantulo", page, top, "voimaantulo")
                self.expect_heading = False
            else:  # the closing rule
                self.flush()
            return
        m = SECTION_RE.match(text)
        if m:
            self.new_section(sec_label(text), page, top)
            if m.group(3):
                self.cur["mark"] = m.group(3).lower().split()[0]
            return
        m = CHAPTER_RE.match(text)
        if m:
            self.flush()
            self.chapter = tidy(text)
            self.expect_heading = True
            self.heading_target = None  # chapter heading is context only
            return
        if UUSI_RE.match(text):  # '(uusi)' as the whole cell = new section; inside a cell = a new momentti (just a marker)
            if self.empty() and self.cur["kind"] == "section":
                self.cur["mark"] = "uusi"
            return
        if KUMOTAAN_RE.match(text) and self.empty():
            self.cur["mark"] = "kumotaan"
        lm, rm = x0 - self.base, right_edge - x1
        centered = abs(lm - rm) <= 3 and not text.endswith((".", ",", ";", ":")) and (lm >= 3 or is_italic(words))
        if self.expect_heading and centered:
            if self.heading_target is not None:
                self.heading_target["heading"].append(text)
            return
        self.expect_heading = False
        if self.cur is None:
            self.new_section("", page, top, "pre")
            self.expect_heading = False
        if lm >= 4 or self.para is None:  # first-line indent = new momentti
            self.flush()
            self.para = [text]
        else:
            self.para.append(text)

    def finish(self) -> list[dict]:
        self.flush()
        out = []
        for s in self.sections:
            if s["kind"] == "pre" and not s["paras"]:
                continue
            out.append({"id": s["id"], "key": s["key"], "chapter": s["chapter"], "heading": tidy(" ".join(s["heading"])) or None,
                        "text": "\n".join(s["paras"]), "page": s["page"], "top": s["top"], "kind": s["kind"], "mark": s["mark"]})
        return out


def section_start(line: dict) -> str | None:
    text = " ".join(w["text"] for w in line["words"])
    return sec_label(text) if SECTION_RE.match(text) else None


def same_row(a: dict, b: dict) -> bool:
    return a["page"] == b["page"] and abs(a["top"] - b["top"]) <= 3


def build_columns(law: dict) -> None:
    """Second pass over one law's collected lines: decide whether the two columns are a table (every
    row starts at the same height in both cells – then '10 § | (kumotaan)' and '(uusi) | 27 a §' rows are
    paired by position) or two free-flowing text columns (sections drift apart – pairing by number only),
    then run the column state machines."""
    lines = law.pop("lines")
    starts = [{} , {}]
    for side in (0, 1):
        for ln in lines[side]:
            sid = section_start(ln)
            if sid and sid not in starts[side]:
                starts[side][sid] = ln
    common = [k for k in starts[1] if k in starts[0]]
    aligned = sum(1 for k in common if same_row(starts[0][k], starts[1][k]))
    law["table"] = not common or aligned / len(common) >= 0.7
    if law["table"]:
        for side in (0, 1):
            other = 1 - side
            for sid, ln in starts[side].items():
                for oln in lines[other]:
                    otext = " ".join(w["text"] for w in oln["words"])
                    if same_row(ln, oln) and not section_start(oln) and (re.match(r"^\(.*\)$", otext) or DASH_RE.match(otext)):
                        oln["inject"] = sid  # the other cell of the row holds only a marker: '(kumotaan)', '(uusi)', a katkoviiva
                        break
    cols = (Column(law["base"][0]), Column(law["base"][1]))
    for side in (0, 1):
        for ln in lines[side]:
            cols[side].feed(ln)
    law["left"], law["right"] = cols[0].finish(), cols[1].finish()


def find_appendix_start(pdf) -> int | None:
    """Index of the page with the 'Rinnakkaistekstit' title, scanning backwards (the appendix is near the end)."""
    n = len(pdf.pages)
    for i in range(n - 1, max(-1, n - 1 - PDF_SCAN_PAGES), -1):
        page = pdf.pages[i]
        txt = page.extract_text() or ""
        page.flush_cache()
        if re.search(r"^\s*(?:Liite\s+)?Rinnakkaistekstit?\s*$", txt, re.MULTILINE | re.IGNORECASE):
            return i
    return None


def parse_parallel_pdf(pdf) -> dict:
    """pdfplumber PDF -> {"status": ok|none, "start": page no, "pages": n, "laws": [{n, name, table, left: [...], right: [...]}]}
    where left/right are the column sections (see Column.finish)."""
    start = find_appendix_start(pdf)
    if start is None:
        return {"status": "none", "laws": []}
    laws: list[dict] = []
    law: dict | None = None
    mode = "prose"
    title: list[str] = []
    collecting_title = False
    started = False  # lines before the appendix title on its page belong to the lakiehdotukset
    stop = False
    pages_used = 0
    empty_pages = 0

    def finish_law() -> None:
        nonlocal law
        if law is not None and law.get("lines") is not None:
            build_columns(law)
            laws.append(law)
        law = None

    for pi in range(start, len(pdf.pages)):
        page = pdf.pages[pi]
        mid = page.width / 2
        words = page.extract_words(x_tolerance=1.5, y_tolerance=2, extra_attrs=["fontname"])
        page.flush_cache()
        pages_used += 1
        page_has_table = False
        edges: list[list[float]] = [[], []]  # x1 of the table words per column on this page -> the columns' right edges
        for ln in words_to_lines(words):
            text = " ".join(w["text"] for w in ln)
            x0, top = ln[0]["x0"], ln[0]["top"]
            if (top > page.height - 170 and PAGENUM_RE.match(text)) or RUNNING_HEADER_RE.match(text):
                continue
            if not started:
                started = bool(re.match(r"^(Liite\s+)?Rinnakkaistekstit?$", text, re.IGNORECASE))
                continue
            strad = any(w["x0"] < mid - 1 and w["x1"] > mid + 1 and not DASH_RE.match(w["text"]) for w in ln)
            left = [w for w in ln if (w["x0"] + w["x1"]) / 2 < mid]
            right = [w for w in ln if (w["x0"] + w["x1"]) / 2 >= mid]
            ltext = " ".join(w["text"] for w in left)
            rtext = " ".join(w["text"] for w in right)
            if left and right and ltext.lower().startswith(("voimassa oleva", "nykyinen")) and rtext.lower().startswith("ehdot"):
                if law is None:
                    law = {"n": None, "name": None}
                if law.get("lines") is None:
                    law["lines"] = ([], [])
                    law["base"] = (left[0]["x0"], right[0]["x0"])
                mode = "table"
                collecting_title = False
                page_has_table = True
                continue
            if mode == "table":
                if LAWNUM_RE.match(text) and not right and x0 < law["base"][0] - 1:
                    finish_law()
                    mode = "prose"
                    law = {"n": int(text[:-1]), "name": None}
                    continue
                if text == "Liite" or re.match(r"^Liite \d+$", text):
                    finish_law()
                    stop = True
                    break
                if not strad:
                    page_has_table = True
                    for side, ws in ((0, left), (1, right)):
                        if ws:
                            law["lines"][side].append({"words": ws, "page": pi, "top": top, "edges": edges[side]})
                            edges[side].extend(w["x1"] for w in ws if not DASH_RE.match(w["text"]))
                    continue
                finish_law()  # a full-width line: the next law's title
                mode = "prose"
            # prose: titles and johtolause between tables
            if re.match(r"^Liite\b", text) and x0 > mid:
                if laws or (law is not None and law.get("name")):
                    stop = True
                    break
                continue
            if LAWNUM_RE.match(text) and x0 < mid - 100:
                law = {"n": int(text[:-1]), "name": None}
                page_has_table = True
                continue
            if re.match(r"^Laki\b", text) and strad and (law is None or law.get("name") is None):
                if law is None:
                    law = {"n": None, "name": None}
                title, collecting_title = [text], True
                page_has_table = True
                continue
            if collecting_title:
                if JOHTOLAUSE_RE.match(text):
                    law["name"], collecting_title = tidy(" ".join(title)), False
                else:
                    title.append(text)
                continue
            if strad and re.search(r"\basetus\b", text, re.IGNORECASE) and law is None:
                stop = True  # the asetusluonnokset appendix follows
                break
        if stop:
            break
        empty_pages = 0 if page_has_table or not started else empty_pages + 1
        if empty_pages >= 2 and mode == "prose":
            break  # two pages without table, title or law number: the appendix has ended
    finish_law()
    return {"status": "ok" if laws else "none", "start": start + 1, "pages": pages_used, "laws": laws}


def pair_columns(law: dict) -> list[dict]:
    """Left/right column sections of one law -> [{id, heading, headingOld?, old, new, mark}] in table order.
    Pairing: the same row (page and top), then the same section key; the rest are new (right only)
    or removed (left only)."""
    left, right = law["left"], law["right"]
    used_l: set[int] = set()
    pairs: dict[int, int] = {}
    if law.get("table", True):
        for j, r in enumerate(right):
            for i, l in enumerate(left):
                if i not in used_l and same_row(l, r) and l["kind"] == r["kind"]:
                    pairs[j] = i
                    used_l.add(i)
                    break
    for j, r in enumerate(right):
        if j in pairs or not r["key"]:
            continue
        cands = [i for i, l in enumerate(left) if i not in used_l and l["key"] == r["key"]
                 and (not l["chapter"] or not r["chapter"] or chap_key(l["chapter"]) == chap_key(r["chapter"]))]
        if len(cands) == 1:
            pairs[j] = cands[0]
            used_l.add(cands[0])
    order = [("l", l["page"], l["top"], i) for i, l in enumerate(left) if i not in used_l]
    order += [("r", r["page"], r["top"], j) for j, r in enumerate(right)]
    order.sort(key=lambda o: (o[1], o[2], o[0] == "l"))
    out = []
    for side, _, _, idx in order:
        if side == "l":
            l = left[idx]
            out.append({"id": l["id"], "heading": l["heading"], "old": l["text"], "new": None, "mark": l["mark"]})
            continue
        r = right[idx]
        if idx in pairs:
            l = left[pairs[idx]]
            old = l["text"] if (l["text"] or l["heading"]) and l["mark"] != "uusi" else None
            new = r["text"] if (r["text"] or r["heading"]) else None
            sec = {"id": r["id"] or l["id"], "heading": r["heading"] or l["heading"], "old": old, "new": new, "mark": r["mark"] or l["mark"]}
            if l["heading"] and r["heading"] and l["heading"] != r["heading"]:
                sec["headingOld"] = l["heading"]
            out.append(sec)
        else:
            out.append({"id": r["id"], "heading": r["heading"], "old": None, "new": r["text"], "mark": r["mark"]})
    return out


def parallel_texts(pdf_bytes: bytes) -> dict:
    """PDF bytes -> {"status", "start", "pages", "laws": [{n, name, sections: [...]}]} (differing sections only)."""
    import pdfplumber  # imported here: the XML parsers and the tests of them do not need it

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        res = parse_parallel_pdf(pdf)
    laws = []
    for law in res["laws"]:
        secs = [s for s in pair_columns(law) if (s["old"] or "") != (s["new"] or "") or s.get("headingOld")]
        laws.append({"n": str(law["n"]) if law.get("n") is not None else None, "name": law.get("name"), "sections": secs})
    return {"status": res["status"], "start": res.get("start"), "pages": res.get("pages"), "laws": laws}


# ----------------------------------------------------------------------------- assembling the cache entry
def match_law(target: dict, candidates: list[dict], used: set[int]) -> int | None:
    """Index of the candidate law with the same number, else the same (normalised) name."""
    for i, c in enumerate(candidates):
        if i not in used and target.get("n") is not None and c.get("n") is not None and str(target["n"]) == str(c["n"]):
            return i
    tn = norm_name(target.get("name"))
    for i, c in enumerate(candidates):
        if i not in used and tn and tn == norm_name(c.get("name")):
            return i
    return None


def assemble_laws(he_laws: list[dict], pdf: dict | None) -> list[dict]:
    """HE XML laws + parallel texts -> the cache's `laws` list."""
    pdf_laws = (pdf or {}).get("laws") or []
    used: set[int] = set()
    out = []
    for law in he_laws:
        rec = {"n": law["n"], "name": law["name"], "kind": law["kind"], "parallel": False, "sections": []}
        j = match_law(law, pdf_laws, used)
        if j is None and law["kind"] != "uusi" and len(pdf_laws) == 1 and sum(1 for l in he_laws if l["kind"] != "uusi") == 1:
            j = 0 if 0 not in used else None
        if j is not None:
            used.add(j)
            rec["parallel"] = True
            for s in pdf_laws[j]["sections"]:
                sec = {"id": s["id"], "heading": s["heading"], "old": s["old"], "new": s["new"]}
                if s.get("headingOld"):
                    sec["headingOld"] = s["headingOld"]
                rec["sections"].append(sec)
        else:
            if law["kind"] == "muutos" and pdf is not None:
                rec["note"] = "rinnakkaistekstiä ei löytynyt"
            for s in law["sections"]:
                if s["text"] or s["heading"]:
                    rec["sections"].append({"id": s["id"], "heading": s["heading"], "old": None, "new": s["text"]})
        out.append(rec)
    for j, pl in enumerate(pdf_laws):  # parallel texts of a law the XML does not list (should not happen)
        if j not in used and pl["sections"]:
            out.append({"n": pl.get("n"), "name": pl.get("name") or "Laki", "kind": "muutos", "parallel": True,
                        "sections": [{"id": s["id"], "heading": s["heading"], "old": s["old"], "new": s["new"]} for s in pl["sections"]]})
    return out


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").split(), (b or "").split(), autojunk=False).ratio()


def find_he_section(law: dict | None, key: str, chapter: str | None) -> dict | None:
    if not law:
        return None
    hits = [s for s in law["sections"] if s["key"] == key]
    want = chap_key(chapter)
    if want:
        for s in hits:
            if chap_key(s.get("chapter")) == want:
                return s
    return hits[0] if hits else None


def assemble_report(report: dict, he_laws: list[dict]) -> dict:
    """Parsed mietintö + HE XML laws -> the cache's `report` (changed sections with the HE text and the committee text)."""
    used: set[int] = set()
    laws = []
    for cl in report["laws"]:
        i = match_law(cl, he_laws, used)
        if i is None and len(he_laws) == 1 and len(report["laws"]) == 1:
            i = 0
        he_law = he_laws[i] if i is not None else None
        if i is not None:
            used.add(i)
        secs = []
        if cl.get("johtolause"):
            he_text = tidy(he_law["johtolause"]) if he_law and he_law.get("johtolause") else cl["johtolause"]["base"]
            if he_text != cl["johtolause"]["clean"]:
                secs.append({"id": "Johtolause", "heading": None, "he": he_text, "committee": cl["johtolause"]["clean"]})
        for s in cl["sections"]:
            hs = find_he_section(he_law, s["key"], s["chapter"])
            if hs is not None and s["base"] and similarity(hs["text"], s["base"]) < 0.6:
                hs = None  # the committee reprinted the pykälä differently (e.g. only some momentit): its own base text is safer
            he_text = hs["text"] if hs is not None else s["base"]
            heading = s["heading"] or (hs["heading"] if hs else None)
            heading_he = hs["heading"] if hs is not None else s["headingBase"]
            if he_text == s["clean"] and (heading_he or None) == (heading or None):
                continue
            sec = {"id": s["id"], "heading": heading, "he": he_text, "committee": s["clean"]}
            if hs is None:
                sec["heFrom"] = "mietintö"
            if s["new"] or (hs is None and not s["base"]):
                sec["added"] = True  # a pykälä the committee adds (its "HE text" is then the law in force or empty)
            if heading_he and heading and heading_he != heading:
                sec["headingHe"] = heading_he
            secs.append(sec)
        if secs:
            laws.append({"n": cl["n"], "name": (he_law or {}).get("name") or cl.get("name") or "Laki", "sections": secs})
    return {"tunnus": report["tunnus"], "date": report["date"], "laws": laws}


def shrink_entry(entry: dict) -> None:
    """Keep one HE's cache entry under HE_CAP bytes: cap every section text, then trim new-law sections, then the rest."""
    def texts(sec: dict) -> list[str]:
        return [k for k in ("old", "new", "he", "committee") if sec.get(k)]

    def all_sections():
        for law in entry.get("laws") or []:
            for s in law["sections"]:
                yield law, s
        for law in (entry.get("report") or {}).get("laws") or []:
            for s in law["sections"]:
                yield law, s

    for _, s in all_sections():
        for k in texts(s):
            s[k] = truncate(s[k], SECTION_CAP)
    if doc_size(entry) <= HE_CAP:
        return
    for law in entry.get("laws") or []:  # new laws first: their text is in the HE itself
        if law["kind"] == "uusi":
            for s in law["sections"]:
                s["new"] = truncate(s["new"], 800)
    while doc_size(entry) > HE_CAP:
        new_laws = [l for l in entry.get("laws") or [] if l["kind"] == "uusi" and l["sections"]]
        if not new_laws:
            break
        law = max(new_laws, key=lambda l: len(l["sections"]))
        law["sections"].pop()
        law["omitted"] = law.get("omitted", 0) + 1
    for cap in (3000, 1500, 700):
        if doc_size(entry) <= HE_CAP:
            return
        for _, s in all_sections():
            for k in texts(s):
                s[k] = truncate(s[k], cap)
    while doc_size(entry) > HE_CAP:  # last resort: drop the longest remaining section
        best = max(all_sections(), key=lambda ls: sum(len(ls[1].get(k) or "") for k in texts(ls[1])), default=None)
        if best is None:
            break
        law, s = best
        law["sections"].remove(s)
        law["omitted"] = law.get("omitted", 0) + 1


# ----------------------------------------------------------------------------- network
_last_request = 0.0


def pace() -> None:
    global _last_request
    wait = _last_request + PACE - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def fetch_rows(tunnus: str) -> list[list]:
    pace()
    r = http("GET", VASKI_ROWS, params={"perPage": 10, "page": 0, "columnName": "Eduskuntatunnus", "columnValue": tunnus}, timeout=180)
    r.raise_for_status()
    return r.json().get("rowData") or []


def he_document_row(num: str) -> list | None:
    """The HE document row [Id, XmlData, Status, Created, Eduskuntatunnus, AttachmentGroupId, Imported], newest first."""
    rows = [r for r in fetch_rows(f"HE {num} vp")
            if "VASKI_JULKVP_GovernmentProposal_fi" in (r[1] or "")[:3000] and "KasittelytiedotValtiopaivaasia" not in (r[1] or "")]
    if not rows:
        return None
    rows.sort(key=lambda r: r[3] or "", reverse=True)
    return rows[0]


def report_document_row(tunnus: str) -> list | None:
    rows = [r for r in fetch_rows(tunnus) if (r[4] or "").strip() == tunnus and "VASKI_JULKVP_CommitteeReport_fi" in (r[1] or "")[:3000]]
    if not rows:
        return None
    rows.sort(key=lambda r: r[3] or "", reverse=True)
    return rows[0]


def attachment_url(group_id: str | None) -> str | None:
    if not group_id:
        return None
    pace()
    r = http("GET", ATTACHMENT_ROWS, params={"perPage": 10, "page": 0, "columnName": "AttachmentGroupId", "columnValue": group_id}, timeout=120)
    r.raise_for_status()
    for row in r.json().get("rowData") or []:
        url = (row[2] or "").strip().strip('"')
        if url.lower().endswith(".pdf"):
            return url
    return None


def fetch_pdf(url: str) -> bytes | None:
    pace()
    r = http("GET", url, timeout=300, stream=True, headers={"Accept": "application/pdf, */*"})
    r.raise_for_status()
    size = int(r.headers.get("Content-Length") or 0)
    if size > PDF_MAX_BYTES:
        return None
    data = r.content
    return data if data[:5] == b"%PDF-" and len(data) <= PDF_MAX_BYTES else None


# ----------------------------------------------------------------------------- selection and main
def given_date(rec: dict) -> str | None:
    for s in rec.get("stages") or []:
        if s.get("code") == "ANTO" and s.get("date"):
            return s["date"]
    dates = [s.get("date") for s in rec.get("stages") or [] if s.get("date")]
    return min(dates) if dates else None


def select_hes(ek: dict) -> list[str]:
    """HE numbers in the window, those with a known mietintö first, then newest first."""
    out = []
    for num, rec in ek.items():
        if not HE_NUM.match(num) or rec.get("tila") == "Rauennut":
            continue
        given = given_date(rec)
        if (days_ago(given) or 10**6) > WINDOW_DAYS:
            continue
        if rec.get("final") and (days_ago(rec.get("vahvistettu")) or 10**6) >= CONFIRMED_DAYS:
            continue
        out.append(num)
    out.sort(key=lambda n: (bool(ek[n].get("reports")), given_date(ek[n]) or ""), reverse=True)
    return out


def report_for(num: str, vaski: dict) -> tuple[str, str | None] | None:
    """(tunnus, date) of the newest mietintö of the HE in the Vaski cache."""
    cands = [(r.get("date") or "", t) for t, r in (vaski.get("reports") or {}).items()
             if r.get("asia") == f"HE {num} vp" and r.get("kind") == "mietintö"]
    if not cands:
        return None
    date, tunnus = max(cands)
    return tunnus, date or None


def needs_fetch(entry: dict | None, wanted: tuple[str, str | None] | None) -> tuple[bool, bool]:
    """-> (fetch the HE document, fetch the report)."""
    if not entry or entry.get("status") == "error":
        return True, bool(wanted)
    stale = (days_ago(entry.get("fetched")) or 0) >= PDF_RETRY_DAYS
    he_again = stale and ((entry.get("pdf") in ("error", "nopdf") and entry.get("pdfTries", 0) < 4) or entry.get("status") == "nodoc")
    rep = entry.get("report")
    report_again = bool(wanted) and (rep is None or rep.get("tunnus") != wanted[0] or (wanted[1] and rep.get("date") != wanted[1]))
    return he_again or report_again, report_again


def process_he(num: str, entry: dict | None, wanted: tuple[str, str | None] | None, want_report: bool, stats: dict) -> dict:
    """Fetch and parse one HE (document + PDF + report as needed). Raises on transport errors."""
    row = he_document_row(num)
    stats["he"] += 1
    if row is None:
        return {"fetched": TODAY.isoformat(), "status": "nodoc", "pdf": "none", "laws": [], "report": None}
    root = strip_ns(row[1])
    he_laws = parse_he_xml(root)
    del root
    out = {"fetched": TODAY.isoformat(), "created": row[3], "status": "ok", "pdf": "none", "laws": [], "report": (entry or {}).get("report")}
    pdf = None
    reuse = entry and entry.get("created") == row[3] and entry.get("pdf") not in (None, "error", "nopdf") and entry.get("laws") is not None
    if reuse:
        out["pdf"] = entry["pdf"]
        out["laws"] = entry["laws"]
    else:
        tries = (entry or {}).get("pdfTries", 0) + 1
        try:
            url = attachment_url(row[5])
            data = fetch_pdf(url) if url else None
            if data is None:
                out["pdf"] = "nopdf" if url is None else "toolarge"
                out["pdfTries"] = tries
            else:
                stats["pdf"] += 1
                pdf = parallel_texts(data)
                del data
                out["pdf"] = pdf["status"]  # ok | none (no appendix)
                if pdf["status"] == "ok":
                    stats["parallel"] += 1
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001 – a broken PDF must not stop the run
            log(f"warn: hediff HE {num}: pdf: {str(e)[:160]}")
            out["pdf"] = "error"
            out["pdfTries"] = tries
        out["laws"] = assemble_laws(he_laws, pdf)
    if want_report and wanted:
        rrow = report_document_row(wanted[0])
        stats["reports"] += 1
        if rrow is None:
            log(f"warn: hediff {wanted[0]}: mietintöä ei löytynyt Vaskista")
        else:
            parsed = parse_report_xml(strip_ns(rrow[1]))
            if parsed:
                parsed["tunnus"] = parsed.get("tunnus") or wanted[0]
                parsed["date"] = parsed.get("date") or wanted[1]
                out["report"] = assemble_report(parsed, he_laws)
                stats["reportDiffs"] += 1 if out["report"]["laws"] else 0
    shrink_entry(out)
    return out


def main():
    ek = load_json(CACHE_DIR / "eduskunta.json", {"items": {}}).get("items") or {}
    vaski = load_json(CACHE_DIR / "vaski.json", {}) or {}
    cache = load_json(OUT, None) or {}
    he_cache: dict = dict(cache.get("he") or {})
    selected = select_hes(ek)
    todo = []
    for num in selected:
        wanted = report_for(num, vaski)
        fetch_he, fetch_rep = needs_fetch(he_cache.get(num), wanted)
        if fetch_he:
            todo.append((num, wanted, fetch_rep))
    stats = {"he": 0, "pdf": 0, "parallel": 0, "reports": 0, "reportDiffs": 0, "failed": 0}
    log(f"hediff: {len(selected)} HE:tä ikkunassa, {len(todo)} haettavaa (raja {MAX_HE} HE / {TIME_BUDGET // 60} min)")
    t0 = time.time()
    failures = 0
    for num, wanted, fetch_rep in todo:
        if stats["he"] >= MAX_HE or time.time() - t0 > TIME_BUDGET:
            break
        try:
            he_cache[num] = process_he(num, he_cache.get(num), wanted, fetch_rep, stats)
            failures = 0
            if stats["he"] % 10 == 0:  # progress survives a killed run
                save_json(OUT, {"fetched": cache.get("fetched"), "he": he_cache}, compact=True)
        except Exception as e:
            failures += 1
            stats["failed"] += 1
            log(f"warn: hediff HE {num}: {str(e)[:160]}")
            if failures >= 3 and (stats["he"] <= failures or isinstance(e, RuntimeError)):
                save_json(OUT, {"fetched": cache.get("fetched"), "he": he_cache}, compact=True)
                raise RuntimeError(f"vaski ei vastaa: {e}") from e
    keep = set(selected)
    he_cache = {k: v for k, v in he_cache.items() if k in keep}
    save_json(OUT, {"fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "he": he_cache}, compact=True)
    pending = sum(1 for num, wanted, _ in todo if needs_fetch(he_cache.get(num), wanted)[0])
    with_parallel = sum(1 for v in he_cache.values() if v.get("pdf") == "ok")
    with_report = sum(1 for v in he_cache.values() if (v.get("report") or {}).get("laws"))
    log(f"hediff: haettu {stats['he']} HE:tä, {stats['pdf']} PDF:ää ({stats['parallel']} rinnakkaistekstein), {stats['reports']} mietintöä "
        f"({stats['reportDiffs']} muutoksin); epäonnistui {stats['failed']}; välimuistissa {len(he_cache)} HE:tä, {with_parallel} rinnakkaistekstein, "
        f"{with_report} mietintödiffein, jonossa {pending}; {time.time() - t0:.0f} s -> {OUT}")


if __name__ == "__main__":
    main()
