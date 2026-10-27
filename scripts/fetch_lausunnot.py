"""Annetut lausunnot: napakka tiivistelmä jokaisesta jo annetusta lausunnosta ja sen antajasta.

Lähteet (molemmat jo pipeline-välimuistissa, tämä vaihe vain lukee lausuntojen PDF:t):
* Hankeikkuna – ministeriöiden lausuntokierrosten LAUSUNTO-asiakirjat (fetch_hankeikkuna tallentaa
  järjestön, päivän ja PDF-osoitteen: `lausunnot.docs`). PDF:t ovat api.hankeikkuna.fi/asiakirjat/…
  (CC BY 4.0).
* Eduskunta – valiokuntien ja jaostojen asiantuntijalausunnot ja lisäselvitykset: eduskunta.fi:n asiasivuilta
  kaikki (fetch_asiat: data/cache/asiat/) ja VaskiData-syötteestä (fetch_vaski: `statements`); PDF eduskunta.fi/pdf/EDK-….
  Virkamiesten esittelyt (ministeriö esittelee omaa esitystään) tiivistetään myös, kannaksi merkitään "virkamiesesittely".
  Skannatut lausunnot luetaan tekstintunnistuksella (pdftoppm + tesseract, suomi ja ruotsi), kun työkalut ovat asennettuina.

Tiivistelmä on **sanatarkka ote** lausunnosta, ei tulkinta: lausunnosta valitaan virke (tai kaksi), jossa
lausunnonantaja ilmaisee kantansa (kannattaa, vastustaa, esittää, pitää …), ja kiitokset, osoitteet ja
viitetiedot ohitetaan. Lisäksi sanastoon perustuva suuntaa-antava kanta: kannattaa / kannattaa varauksin /
vastustaa / muutosehdotuksia / ei lausuttavaa / kannanotto. Kumpikin näkyy sivulla linkin kera, jotta
lukija voi tarkistaa otteen alkuperäisestä.

Kerran luettu lausunto ei muutu, joten tulos tallennetaan asiakirjan tunnisteella (data/cache/lausunnot/<lähde>-<vuosi>.json)
ja PDF luetaan vain kerran. Jokainen ajo käsittelee aikabudjetin verran uusia lausuntoja (LAUSUNNOT_BUDGET_S,
oletus 15 min, 4 rinnakkaista hakua), tuoreimmat ja käynnissä olevien kierrosten lausunnot ensin.
"""
from __future__ import annotations

import datetime as dt
import io
import os
import re
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from common import CACHE_DIR, TODAY, SourceOutage, http, load_json, log, save_json

OUT = CACHE_DIR / "lausunnot.json"          # legacy single file (read once, then replaced by the shards)
SHARD_DIR = CACHE_DIR / "lausunnot"          # one file per source and year: a run only rewrites the shards it touched
BUDGET_S = int(os.environ.get("LAUSUNNOT_BUDGET_S", 15 * 60))
WORKERS = int(os.environ.get("LAUSUNNOT_WORKERS", 4))
PER_HOST = int(os.environ.get("LAUSUNNOT_PER_HOST", 2))
COMMITTEE_VERSION = 2  # 2: the members' dissent/opinion after the signature is no longer read as the committee's view
FORMAT_VERSION = 2   # 2: Outlook .msg, Word .doc, pptx/odt, plain text/e-mail/RTF and images are read too
STRIKES = 5
MAX_PAGES = 4
GIST_MAX = 280
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) saadosseuranta/1.0 (+https://github.com/EditMonster/Saadosseuranta)"}

# --- text clean-up ---------------------------------------------------------------------------------------
BOILER = re.compile(
    r"kiit(t)?ä\w* (mahdollisuud|lausuntopyyn|pyynnö|kutsu)|kiitos (mahdollisuudesta|kutsusta)|mahdollisuudesta (lausua|antaa)|lausuntopyyntö\w*\s|lausuntopyyntönne|"
    r"pyydettynä lausuntona|lausunto asiassa|^asia\s*:|viite\s*:|@|\bpuh\.|puhelin|www\.|https?://|lausuntopalvelu\.fi|"
    r"y-tunnus|postiosoite|käyntiosoite|^\s*(liite|liitteet|jakelu|tiedoksi)\b|allekirjoit|sähköisesti hyväksytty|"
    r"ystävällisin terveisin|kunnioittavasti|^\s*lausunto\s*\d|^\s*\d+\s*\(\d+\)\s*$|lausunnonantajan lausunto|"
    r"vastaa(?:ja|jan) (?:nimi|tiedot)|lausunnon antajan (?:nimi|yhteystiedot)|"
    # document headers and slide furniture that the PDF text puts in front of the first paragraph
    r"^\s*(HE|U|E|K|VNS|VNT|TAE|LAUSUNTO|ASIANTUNTIJALAUSUNTO|MUISTIO|Asiantuntijalausunto|Lausunto)\b\s*\d|^\s*(HE|U|E|K|VNS) \d+/\d{4} vp|"
    r"hallituksen esitys eduskunnalle|valtioneuvoston (selvitys|kirjelmä)|^\s*\d{1,2}\.\d{1,2}\.\d{4}|\d{1,2}\.\d{1,2}\.\d{4}\s+\d+\s*$|"
    r"^\s*lähde:|\(cid:\d+\)|julkinen kuuleminen|valiokunnan kuuleminen|kuuleminen \d{1,2}\.\d{1,2}\.|^\s*[A-ZÄÖÅ][a-zäöå]+ [A-ZÄÖÅ][a-zäöå]+\s*$", re.I)
# reservations strong enough to turn "kannattaa" into "kannattaa varauksin"
RESERVE_RE = re.compile(r"\b(kuitenkin|ongelmallis\w*|huolestun\w*|huolissa\w*|puutteellis\w*|riittämät\w*|epäselv\w*|kohtuuton\w*|"
                        r"(esittä\w*|esitämme|ehdotta\w*|ehdotamme) [a-zäö ,]{0,40}(muutos|muutett|tarkennu|täsmennys|täsmennet|lisäy|poist)\w*|"
                        r"ei (voida|voi) pitää|ei ole (riittäv|perustel|tarkoituksenmukai)\w*|tulee (muuttaa|täsmentää|tarkentaa|poistaa|korjata)|poistamista|"
                        r"tulisi (muuttaa|täsmentää|tarkentaa|poistaa|korjata|harkita|selvittää|arvioida))\b", re.I)
STANCE_VERB = re.compile(
    r"\b(kannatta\w*|puolta\w*|vastusta\w*|yhtyy|yhdy\w*|ei kannata|ei puolla|esittää|esitämme|ehdotta\w*|ehdotamme|"
    r"edellyttä\w*|katso\w*|pitää [a-zäöå\- ]{0,60}(tärkeä|hyvä|perustel|kannatettav|ongelmallis|välttämätön|tarpeellis|"
    r"myönteis|tervetullee|kiirehdittäv|riittämätön|puutteellis|haitallis)\w*|pidämme|suhtautu\w*|huolestun\w*|huolissa\w*|"
    r"korosta\w*|tukee|tuemme|ei ole huomautettavaa|ei ole lausuttavaa|toivo\w*|vaati\w*|tulisi|pitäisi|on syytä)\b", re.I)
NONE_RE = re.compile(r"\bei (ole )?(lausuttavaa|lausuntoa|huomautettavaa|kommentoitavaa)\b|ingenting att yttra|inget utlåtande|"
                     r"inga kommentarer|ei näe tarvetta lausua", re.I)
OPPOSE_RE = re.compile(r"\b(vastusta(a|vat|mme|isi\w*|a jyrkästi)|ei kannata|emme kannata|ei puolla|emme puolla|(ei|emme) voi(da)? (hyväksyä|kannattaa|puoltaa)|"
                       r"tulee hylätä|on hylättävä|ei tule (toteuttaa|hyväksyä|säätää)|ei pidä [a-zäö ]{0,40}perusteltuna|torju(u|vat|mme|isi\w*|taan)|"
                       r"esittä\w* [a-zäö ,]{0,50}(luopumista|hylkäämistä)|ei (ole )?(hyväksyttäv|kannatettav)\w*)\b", re.I)
SUPPORT_RE = re.compile(r"\b(kannatta(a|vat|mme)(?! (huomata|todeta|harkita|selvittää|ottaa|pohtia|miettiä))|kannatamme|puolta(a|vat|mme)|"
                        r"yhtyy|yhdymme|(pitää|pidämme|pitävät) [a-zäöå\- ]{0,60}(hyv|kannatettav|perusteltu|myönteis|tervetullee|"
                        r"oikeansuuntais|tarpeellis)(änä|ana|enä|ena|inä|ina|nä|na|ä|a)\b|suhtautu\w* myönteisesti|tuke(e|vat|mme) (esitystä|ehdotusta|"
                        r"esitettyä|tavoitetta|ehdotettua|uudistusta|valtioneuvoston kantaa|kantaa|linjau\w*)|(ei ole|ei) huomautettavaa)\b", re.I)
CONCERN_RE = re.compile(r"\b(kuitenkin|huolestun\w*|huolissa\w*|ongelmallis\w*|riski\w*|puutteellis\w*|riittämät\w*|"
                        r"esittä\w* [a-zäö ,]{0,40}(muutos|tarkennu|täsmennys|lisäy|selvity)\w*|ehdotta\w*|ehdotamme|"
                        r"tulisi|pitäisi|edellyttä\w*|on syytä|on tarpeen)\b", re.I)
STANCE_LABEL = {"esittely": "virkamiesesittely", "kannattaa": "kannattaa", "varauksin": "kannattaa varauksin", "vastustaa": "vastustaa",
                "muutoksia": "muutosehdotuksia", "osin": "vastustaa osin", "ei": "ei lausuttavaa", "kanta": "kannanotto"}


def clean_text(raw: str) -> str:
    """PDF text -> running text: hyphenation joined, line breaks inside paragraphs removed."""
    t = raw.replace("­", "").replace("\r", "")
    t = re.sub(r"(\w)[-‐]\n(?=[a-zäöå])", r"\1", t)          # tavoit-\nteena -> tavoitteena
    t = re.sub(r"[ \t]+", " ", t)
    lines = [ln.strip() for ln in t.split("\n")]
    out, buf = [], []
    for i, ln in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if ln and not buf and len(ln) < 70 and not re.search(r"[.!?:,;]$", ln) and nxt[:1].isupper():
            out.append(ln)  # a heading on its own line: never glue it to the paragraph below
            continue
        if not ln:
            if buf:
                out.append(" ".join(buf))
                buf = []
            continue
        buf.append(ln)
        if re.search(r"[.!?:]$", ln) and len(ln) < 60:
            out.append(" ".join(buf))
            buf = []
    if buf:
        out.append(" ".join(buf))
    return "\n".join(out)


SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÅ0-9\"”(])")


def sentences(text: str) -> list[str]:
    out = []
    for para in text.split("\n"):
        for s in SENT_SPLIT.split(para):
            s = s.strip(" •–-*·\t")
            if s:
                out.append(s)
    return out


def _org_tokens(org: str) -> list[str]:
    org = org or ""
    toks = [w for w in re.findall(r"[A-ZÄÖÅ][\wäöåÄÖÅ\-]{2,}", org) if w.lower() not in {"suomen", "ry", "oyj", "oy"}]
    abbr = re.findall(r"\(([A-ZÄÖÅ]{2,8})\)", org) + re.findall(r"\b([A-ZÄÖÅ]{2,8})\b", org)
    return list(dict.fromkeys(abbr + toks[:2]))


def pick_gist(text: str, org: str = "", prefer: str | None = None) -> str:
    """The sentence(s) where the respondent states its position, verbatim, at most GIST_MAX characters.
    `prefer`: a regex; when some candidate sentences match it, only those are considered (a committee's own
    view: sentences that name the committee, not the government's position it quotes)."""
    sents = sentences(text)
    toks = [t.lower() for t in _org_tokens(org)]
    scored = []
    for i, s in enumerate(sents):
        words = len(s.split())
        if words < 7 or BOILER.search(s) or not re.search(r"[a-zäöå]{3}", s):
            continue
        if sum(c.isdigit() for c in s) > len(s) * 0.12 or s.count("•") or re.search(r"\d+\s*\(\d+\)|\bvp\b", s):
            continue
        if sum(1 for ch in s if ch.isupper()) > len(s) * 0.3:  # headings in capitals glued to a paragraph
            continue
        low = s.lower()
        score = 0.0
        score += 3 * len(STANCE_VERB.findall(s))
        score += 2 if any(t and t in low for t in toks) or re.search(r"\b(me|meidän|emme|esitämme|pidämme|katsomme|kannatamme)\b", low) else 0
        score += 2 if (OPPOSE_RE.search(s) or SUPPORT_RE.search(s)) else 0
        score += max(0.0, 2.0 - i * 0.12)                       # earlier sentences tend to carry the main position
        score -= 1.5 if words > 50 else 0
        score -= 2 if s.endswith(":") else 0
        scored.append((score, i, s))
    if not scored:
        # no sentence passed the filters (slides, tables, very short texts): the first readable sentence(s)
        plain = [s for s in sents if len(s.split()) >= 5 and not BOILER.search(s) and re.search(r"[a-zäöå]{3}", s)]
        if not plain:
            return ""
        gist = " ".join(plain[:2]) if len(plain[0]) < 120 and len(plain) > 1 else plain[0]
        return gist if len(gist) <= GIST_MAX else gist[:GIST_MAX].rsplit(" ", 1)[0].rstrip(",;:–-") + " …"
    if prefer:
        own = [x for x in scored if re.search(prefer, x[2], re.I)]
        scored = own or scored
    best = max(scored, key=lambda x: (x[0], -x[1]))
    gist = best[2]
    if len(gist) < 140:                                         # a short main sentence: add the next one when it qualifies it
        nxt = next((s for sc, i, s in scored if i == best[1] + 1), None)
        if nxt and (CONCERN_RE.search(nxt) or STANCE_VERB.search(nxt)):
            gist = f"{gist} {nxt}"
    if len(gist) > GIST_MAX:
        cut = gist[:GIST_MAX].rsplit(" ", 1)[0].rstrip(",;:–-")
        gist = cut + " …"
    return gist


def signals(text: str, title: str = "") -> dict:
    """The vocabulary hits the stance rests on – stored with the summary so a narrowed vocabulary can be
    re-applied without re-reading the PDF (`reclassify`)."""
    hits = lambda rx: [m.group(0).lower() for m in rx.finditer(text)][:12]  # noqa: E731
    return {"none": bool(NONE_RE.search(title) or (NONE_RE.search(text) and len(text) < 1800)),
            "opp": hits(OPPOSE_RE), "sup": hits(SUPPORT_RE), "res": hits(RESERVE_RE), "con": len(CONCERN_RE.findall(text))}


def decide(sig: dict) -> str:
    """Suuntaa-antava kanta sanastosta. Key into STANCE_LABEL."""
    if sig.get("none"):
        return "ei"
    opp, sup, strong, weak = len(sig.get("opp") or []), len(sig.get("sup") or []), len(sig.get("res") or []), int(sig.get("con") or 0)
    if opp and not sup:
        return "vastustaa"
    if opp:
        return "osin"
    if sup and strong >= 2:
        return "varauksin"
    if sup:
        return "kannattaa"
    if strong >= 1 or weak >= 4:
        return "muutoksia"
    return "kanta"


def classify(text: str, title: str = "") -> str:
    return decide(signals(text, title))


def reclassify(rec: dict) -> bool:
    """Re-check a cached record's stored hits against the current vocabulary (drops hits the regexes no longer
    accept) and recompute the stance. Returns True when the stance changed."""
    sig = rec.get("sig")
    if not sig or rec.get("ok") is not True or rec.get("stance") == "esittely":
        return False
    for key, rx in (("opp", OPPOSE_RE), ("sup", SUPPORT_RE), ("res", RESERVE_RE)):
        sig[key] = [h for h in sig.get(key) or [] if rx.fullmatch(h) or rx.search(h)]
    new = decide(sig)
    changed = new != rec.get("stance")
    rec["stance"] = new
    return changed


def pdf_text(data: bytes, max_pages: int) -> tuple[str, int | None]:
    """Text of the first pages: poppler's pdftotext when installed (10–30× faster than pdfplumber, the same
    reading order for these documents), pdfplumber otherwise."""
    import shutil
    import subprocess
    if shutil.which("pdftotext"):
        try:
            r = subprocess.run(["pdftotext", "-l", str(max_pages), "-enc", "UTF-8", "-", "-"], input=data, capture_output=True, timeout=120)
            if r.returncode == 0:
                return r.stdout.decode("utf-8", "ignore").replace("\f", "\n"), None
        except Exception:  # noqa: BLE001
            pass
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages[:max_pages]), len(pdf.pages)


def summarise_pdf(data: bytes, org: str = "", title: str = "") -> dict:
    raw, pages = pdf_text(data, MAX_PAGES)
    text = clean_text(raw)
    ocr = False
    if len(re.sub(r"\s", "", text)) < 80:
        text = clean_text(ocr_pdf(data))  # a scanned statement: read the first pages with Tesseract (Finnish)
        ocr = True
        if len(re.sub(r"\s", "", text)) < 80:
            return {"ok": "noText", "pages": pages, "stance": "ei" if NONE_RE.search(title) else None, "ocrTried": OCR_READY}
    sig = signals(text, title)
    out = {"ok": True, "pages": pages, "stance": decide(sig), "sig": sig, "gist": pick_gist(text, org)}
    if ocr:
        out["ocr"] = True
    return out


def _ocr_ready() -> bool:
    import shutil
    return bool(shutil.which("pdftoppm") and shutil.which("tesseract"))


OCR_READY = _ocr_ready()


def ocr_pdf(data: bytes, pages: int = 2) -> str:
    """Text of the first pages of a scanned PDF via pdftoppm + tesseract (fin+swe); '' when the tools are missing."""
    import shutil
    import subprocess
    import tempfile
    if not (shutil.which("pdftoppm") and shutil.which("tesseract")):
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.pdf")
        with open(src, "wb") as f:
            f.write(data)
        try:
            subprocess.run(["pdftoppm", "-r", "200", "-f", "1", "-l", str(pages), "-png", src, os.path.join(tmp, "p")], check=True, timeout=90,
                           capture_output=True)
        except Exception:  # noqa: BLE001
            return ""
        langs = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout.split()
        lang = "+".join(x for x in ("fin", "swe") if x in langs) or "eng"
        out = []
        for img in sorted(f for f in os.listdir(tmp) if f.endswith(".png")):
            try:
                r = subprocess.run(["tesseract", os.path.join(tmp, img), "-", "-l", lang], capture_output=True, text=True, timeout=90)
                out.append(r.stdout)
            except Exception:  # noqa: BLE001
                continue
        return "\n".join(out)


def summarise_text(text: str, org: str = "", title: str = "", extra: dict | None = None) -> dict:
    text = clean_text(text or "")
    if len(re.sub(r"\s", "", text)) < 80:
        return {"ok": "noText", "pages": None, "stance": "ei" if NONE_RE.search(title) else None, "ocrTried": OCR_READY, **(extra or {})}
    sig = signals(text, title)
    return {"ok": True, "pages": None, "stance": decide(sig), "sig": sig, "gist": pick_gist(text, org), **(extra or {})}


def zip_text(data: bytes) -> str:
    """Text of an Office Open XML / OpenDocument file: Word, PowerPoint, OpenDocument text, Excel strings."""
    import zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        parts = (["word/document.xml"] if "word/document.xml" in names else []) or \
                sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1])) or \
                (["content.xml"] if "content.xml" in names else []) or (["xl/sharedStrings.xml"] if "xl/sharedStrings.xml" in names else [])
        out = []
        for n in parts:
            xml = z.read(n).decode("utf-8", "ignore")
            xml = re.sub(r"</(w:p|a:p|text:p|text:h|si)>", "\n", xml)
            out.append(html_unescape(re.sub(r"<[^>]+>", "", xml)))
    return "\n".join(out)


def html_unescape(t: str) -> str:
    import html
    return html.unescape(t)


def ole_text(data: bytes) -> str:
    """Readable text from an OLE file (Outlook .msg, Word 97 .doc): the longest runs of UTF-16LE text, and of
    single-byte text for .doc. Rough but enough to find the sentence that states the position."""
    runs = re.findall(r"(?:[\x20-\x7e\xa0-\xff\n\r\t]\x00){40,}", data.decode("latin-1"))
    texts = [r.encode("latin-1").decode("utf-16le", "ignore") for r in runs]
    if sum(len(t) for t in texts) < 400:  # Word 97 often stores the body as 8-bit text
        texts += re.findall(r"[\x20-\x7e\xa0-\xff\n\r\t]{60,}", data.decode("cp1252", "ignore"))
    junk = re.compile(r"\\[a-z]{3,}\d|xmlns|<\w+:|/O=|/OU=|/CN=|EXCHANGE|SMTP|IPM\.|@[\w.-]+\.(fi|com|net|org)|[A-F0-9]{16,}|"
                      r"endobj|endstream|H4sI|govauth|\.(pdf|docx?|xlsx?)\b|[A-Za-z0-9+/]{30,}|þÿ", re.I)

    def prose(t: str) -> bool:
        words = t.split()
        if len(words) < 8:
            return False
        lettery = sum(1 for w in words if re.fullmatch(r"[\wäöåÄÖÅ,.;:()\-–!?\"”']+", w))
        return lettery / len(words) > 0.85 and sum(len(w) for w in words) / len(words) < 11

    texts = [t for t in texts if len(re.findall(r"[a-zäöåA-ZÄÖÅ]{3,}", t)) >= 6 and not junk.search(t) and prose(t)]
    texts = sorted(set(texts), key=len, reverse=True)[:6]  # the message / document body is the longest run
    body = "\n".join(texts)
    if "<html" in body.lower() or "</p>" in body.lower():
        body = html_unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style|head).*?</\1>", "", body)))
    return body


def plain_text(data: bytes) -> str:
    """.txt / .eml / .rtf: decode, drop RTF control words and e-mail headers."""
    for enc in ("utf-8", "cp1252"):
        try:
            t = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if t.lstrip().startswith("{\\rtf"):
        t = re.sub(r"\\'([0-9a-f]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252"), t)
        t = re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", t)
    if re.match(r"^(Received|From|Return-Path|MIME-Version|Subject|Date|To|Content-Type|X-[\w-]+):", t):
        import email
        from email import policy
        msg = email.message_from_bytes(data, policy=policy.default)
        part = msg.get_body(preferencelist=("plain", "html"))
        t = part.get_content() if part else t.split("\n\n", 1)[-1]
    if "<html" in t.lower() or "</p>" in t.lower():
        t = html_unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style|head).*?</\1>", "", t)))
    return t


def ocr_image(data: bytes) -> str:
    import shutil
    import subprocess
    import tempfile
    if not shutil.which("tesseract"):
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "img")
        with open(src, "wb") as f:
            f.write(data)
        langs = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout.split()
        lang = "+".join(x for x in ("fin", "swe") if x in langs) or "eng"
        try:
            return subprocess.run(["tesseract", src, "-", "-l", lang], capture_output=True, text=True, timeout=120).stdout
        except Exception:  # noqa: BLE001
            return ""


def summarise_file(data: bytes, url: str, ctype: str, org: str = "", title: str = "") -> dict:
    """Any statement file: PDF, Office (docx/pptx/odt), Outlook .msg / Word .doc, plain text / e-mail / RTF, image."""
    ext = url.rsplit(".", 1)[-1].lower() if "." in url.rsplit("/", 1)[-1] else ""
    if data[:4] == b"%PDF" or "pdf" in ctype:
        return summarise_pdf(data, org, title)
    if data[:2] == b"PK":
        return summarise_text(zip_text(data), org, title)
    if data[:4] == b"\xd0\xcf\x11\xe0":
        if ext == "msg" or b"_\x00_\x00s\x00u\x00b\x00s\x00t\x00g\x001\x00" in data[:200000]:
            return summarise_msg(data, org, title)
        return summarise_text(ole_text(data), org, title)
    if data[:3] == b"\xff\xd8\xff" or data[:4] == b"\x89PNG" or data[:4] in (b"II*\x00", b"MM\x00*") or ext in ("jpg", "jpeg", "png", "tif", "tiff"):
        return summarise_text(ocr_image(data), org, title, {"ocr": True})
    if ext in ("txt", "eml", "rtf", "htm", "html") or ctype.startswith(("text/", "message/")):
        t = plain_text(data)
        if ext in ("htm", "html") or "html" in ctype:
            t = html_unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", "", t)))
        return summarise_text(t, org, title)
    return {"ok": "notPdf"}


def summarise_msg(data: bytes, org: str = "", title: str = "") -> dict:
    """An e-mailed statement: the attachment is usually the statement itself (PDF/Word); the message body is
    used when there is no readable attachment (or the body is the statement, e.g. "ei lausuttavaa")."""
    from cfb import msg_parts
    try:
        m = msg_parts(data)
    except Exception:  # noqa: BLE001 – a damaged file: fall back to the raw text runs
        return summarise_text(ole_text(data), org, title)
    best = None
    for name, blob in m["attachments"]:
        if len(blob) < 2000 and re.search(r"\.(png|jpe?g|gif)$", name, re.I):
            continue  # signature logos
        r = summarise_file(blob, name, "", org, title)
        if r.get("ok") is True and r.get("gist"):
            if not best or len(r["gist"]) > len(best["gist"]):
                best = {**r, "via": f"liite {name}"[:120]}
    if best:
        return best
    body = m["body"]
    if "<html" in body.lower() or "</p>" in body.lower():
        body = html_unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style|head).*?</\1>", "", body)))
    return summarise_text(body, org, title)


COMMITTEE_VIEW = r"\bvaliokun\w*|\bvaliokunnan\b"


SIGNATURE = re.compile(r"\bHelsingissä \d{1,2}\.\d{1,2}\.\d{4}")
DISSENT_VOICE = re.compile(r"\b(esitämme|ehdotamme|katsomme|edellytämme)\b", re.I)


def summarise_committee(data: bytes) -> dict:
    """A committee opinion/report (PeVL, YmVL, …M): the sentence where the committee states its own view,
    read from the first pages that hold the committee's considerations (no stance: it is not a respondent)."""
    raw, pages = pdf_text(data, 12)
    text = clean_text(raw)
    # the committee's own text ends at the signature ("Helsingissä 14.10.2026"); after it come the members'
    # dissenting opinions ("Edellä olevan perusteella esitämme …"), which are not the committee's view
    if (sig := SIGNATURE.search(text)):
        text = text[:sig.start()]
    # skip the summary of the government proposal: the committee's considerations start at "VALIOKUNNAN KANNANOTOT"/"Perustelut"
    m = re.search(r"\n(VALIOKUNNAN KANNANOTOT|Valiokunnan kannanotot|PERUSTELUT|Perustelut)\b", text)
    body = text[m.end():] if m else text
    gist = pick_gist(body, "Valiokunta", prefer=COMMITTEE_VIEW) or pick_gist(text, "Valiokunta", prefer=COMMITTEE_VIEW)
    if gist:
        gist = re.sub(r"^(?:[A-ZÄÖÅ]{3,}\s+){1,4}(?=[A-ZÄÖÅ][a-zäöå])", "", gist)  # a heading in capitals glued to the sentence
    if gist and DISSENT_VOICE.search(gist):
        gist = None
    return {"ok": True if gist else "noText", "pages": pages, "stance": None, "gist": gist or None}


def summarise_docx(data: bytes, org: str = "", title: str = "") -> dict:
    return summarise_text(zip_text(data), org, title)


# --- which statements -------------------------------------------------------------------------------------
def is_presentation(s: dict) -> bool:
    """A civil servant's slides in committee (the ministry presenting its own bill), not a position."""
    org = (s.get("org") or "").lower()
    return bool(s.get("person")) and ("ministeriö" in org or "valtioneuvoston kanslia" in org)


def candidates(hk: dict, vaski: dict, asiat: dict | None = None) -> list[dict]:
    """Every statement with a readable file – however old: a law shown on the page gets all of its statements
    summarised. Open/recent consultation rounds first, then newest first."""
    soon = (TODAY - dt.timedelta(days=60)).isoformat()
    out = []
    for p in (hk.get("items") or []):
        L = p.get("lausunnot") or {}
        open_round = any(e.get("kind") == "lausunto" and (e.get("end") or e.get("date") or "") >= soon for e in p.get("etapit") or [])
        for d in L.get("docs") or []:
            if not d.get("url"):
                continue
            out.append({"id": d["id"], "src": "hk", "url": d["url"], "org": d.get("org") or "", "date": d.get("date"),
                        "title": d.get("title") or "", "prio": 0 if open_round or (d.get("date") or "") >= soon else 1})
    lists = list((vaski.get("statements") or {}).values()) + [a.get("statements") or [] for a in ((asiat or {}).get("asiat") or {}).values()]
    seen: set[str] = set()
    for lst in lists:
        for s in lst:
            if not s.get("url") or (s.get("edk") or s["url"]) in seen:
                continue
            seen.add(s.get("edk") or s["url"])
            out.append({"id": s.get("edk") or s["url"], "src": "ek", "url": s["url"], "org": s.get("org") or s.get("person") or "",
                        "esittely": is_presentation(s),
                        "date": s.get("date"), "title": s.get("title") or "", "prio": 0 if (s.get("date") or "") >= soon else 1})
    for a in ((asiat or {}).get("asiat") or {}).values():
        for d in a.get("committeeDocs") or []:
            if d["tunnus"] in seen:
                continue
            seen.add(d["tunnus"])
            out.append({"id": d["tunnus"], "src": "vk", "url": "https://www.eduskunta.fi/pdf/" + d["tunnus"].replace(" vp", "").replace(" ", "+"),
                        "org": d.get("committee") or "", "date": d.get("date"), "title": "", "prio": 0 if (d.get("date") or "") >= soon else 1})
    out.sort(key=lambda c: c.get("date") or "", reverse=True)
    out.sort(key=lambda c: c["prio"])  # stable: open rounds first, newest first within each group
    return out


def _shard(rec: dict) -> str:
    return f"{rec.get('src') or 'x'}-{(rec.get('date') or '0000')[:4]}"


def load_docs() -> dict:
    """All cached summaries {doc id: record}: the shards plus the legacy single file, if it is still there."""
    docs = dict((load_json(OUT, {}) or {}).get("docs") or {})
    for f in sorted(SHARD_DIR.glob("*.json")):
        docs.update((load_json(f, {}) or {}).get("docs") or {})
    return docs


def _save(docs: dict, keep: set[str] | None = None) -> None:
    """Write the shards (deterministic, so an untouched shard is byte-identical and git sees no change).
    `keep` = ids still listed somewhere; records of statements no longer listed are dropped."""
    if keep is not None:
        docs = {k: v for k, v in docs.items() if k in keep}
    shards: dict[str, dict] = {}
    for k, v in docs.items():
        shards.setdefault(_shard(v), {})[k] = v
    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    for name, part in shards.items():
        save_json(SHARD_DIR / f"{name}.json", {"docs": part}, compact=True)
    for f in SHARD_DIR.glob("*.json"):
        if f.stem not in shards:
            f.unlink()
    if OUT.exists():
        OUT.unlink()


def main():
    docs: dict = load_docs()
    hk = load_json(CACHE_DIR / "hankeikkuna.json", {}) or {}
    vaski = load_json(CACHE_DIR / "vaski.json", {}) or {}
    from fetch_asiat import load_cache
    asiat = load_cache()
    cands = candidates(hk, vaski, asiat)
    listed = {c["id"] for c in cands}
    changed = sum(reclassify(v) for v in docs.values())
    if changed:
        log(f"lausunnot: sanasto muuttunut – {changed} kantaa luokiteltu uudelleen tallennetuista osumista")
    def needs(c: dict) -> bool:
        v = docs.get(c["id"])
        if not v:
            return True
        if v.get("ok") == "error":
            return int(v.get("tries", 0)) < 3
        if v.get("ok") == "noText":
            return OCR_READY and not v.get("ocrTried")  # scanned before OCR was available: read again
        if v.get("ok") == "notPdf" or (v.get("ok") == "error" and "document.xml" in (v.get("error") or "")):
            return int(v.get("fmt") or 1) < FORMAT_VERSION  # a format the reader learned since: read again
        if c["src"] == "vk" and int(v.get("vk") or 1) < COMMITTEE_VERSION:
            return True  # the committee reader improved since: read again
        if c.get("esittely") and v.get("ok") is True and v.get("stance") != "esittely":
            v["stance"] = "esittely"
        return False

    todo = [c for c in cands if needs(c)]
    log(f"lausunnot: {len(docs)} tiivistetty, {len(todo)} odottaa (budjetti {BUDGET_S} s)")
    t0, done, outage, errors = time.time(), 0, None, 0
    down: set[str] = set()
    lock = threading.Lock()

    strikes: dict[str, int] = {}
    gates: dict[str, threading.Semaphore] = {}

    def host_of(url: str) -> str:
        return re.sub(r"^https?://([^/]+).*", r"\1", url)

    def read_one(c: dict) -> tuple[dict, dict | None, Exception | None]:
        rec = {k: c[k] for k in ("src", "org", "date", "url")}
        with lock:
            gate = gates.setdefault(host_of(c["url"]), threading.Semaphore(PER_HOST))
        try:
            with gate:  # at most PER_HOST requests at a time to one server (eduskunta.fi answers 503 when pushed)
                r = http("GET", c["url"], headers=UA, timeout=60, retries=3)
            r.raise_for_status()
            ctype = (r.headers.get("content-type") or "").lower()
            if c["src"] == "vk" and r.content[:4] == b"%PDF":
                rec.update(summarise_committee(r.content))
                rec["vk"] = COMMITTEE_VERSION
            else:
                rec.update(summarise_file(r.content, c["url"], ctype, c["org"], c["title"]))
            rec["fmt"] = FORMAT_VERSION
            if c.get("esittely") and rec.get("ok") is True:
                rec["stance"] = "esittely"  # the ministry presenting its own proposal: a summary, not a position
            return c, rec, None
        except SourceOutage as e:
            return c, None, e
        except Exception as e:  # noqa: BLE001
            rec.update({"ok": "error", "error": str(e)[:160], "tries": int((docs.get(c["id"]) or {}).get("tries", 0)) + 1})
            return c, rec, None

    # one queue per server, served in turn: a slow or failing server never holds every worker
    queues: dict[str, deque] = {}
    for c in todo:
        queues.setdefault(host_of(c["url"]), deque()).append(c)
    inflight: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        running = {}

        def submit_next() -> bool:
            for host in sorted(queues, key=lambda h: inflight.get(h, 0)):
                if host in down or not queues[host] or inflight.get(host, 0) >= PER_HOST:
                    continue
                c = queues[host].popleft()
                inflight[host] = inflight.get(host, 0) + 1
                running[pool.submit(read_one, c)] = host
                return True
            return False

        while len(running) < WORKERS and submit_next():
            pass
        while running:
            finished, _ = wait(list(running), return_when=FIRST_COMPLETED)
            for fut in finished:
                host = running.pop(fut)
                inflight[host] -= 1
                c, rec, err = fut.result()
                if err is not None:
                    # one 503 or timeout is not an outage: give up on a server only after STRIKES failures in a row;
                    # the statement itself is simply tried again on the next run
                    with lock:
                        strikes[host] = strikes.get(host, 0) + 1
                        if strikes[host] >= STRIKES and host not in down:
                            log(f"warn: lausunnot: {host} ei vastaa {STRIKES} kertaa peräkkäin – jatketaan muilla ({err})")
                            down.add(host)
                            outage = err
                    time.sleep(2)
                else:
                    strikes[host] = 0
                    rec["read"] = TODAY.isoformat()
                    docs[c["id"]] = rec
                    done += 1
                    errors += rec.get("ok") == "error"
                    if done % 200 == 0:
                        _save(docs, listed)  # a run cut short by the job timeout keeps what it read
            while time.time() - t0 <= BUDGET_S and len(running) < WORKERS and submit_next():
                pass
    # the cache only shrinks when the listings answered (an outage must not wipe what was read)
    _save(docs, listed if hk.get("items") and vaski.get("statements") else None)
    ok = sum(1 for v in docs.values() if v.get("ok") is True)
    log(f"lausunnot: {done} uutta luettu ({errors} virhettä), yhteensä {ok} tiivistelmää, {len(todo) - done} jäi seuraavaan ajoon -> {OUT}")
    if outage and not done:
        raise SourceOutage(f"lausunnot: lähteet eivät vastaa: {sorted(down)}") from outage


if __name__ == "__main__":
    main()
