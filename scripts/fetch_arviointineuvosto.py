"""Lainsäädännön arviointineuvoston lausunnot hallitusten esitysten omasta tekstistä.

Arviointineuvosto arvioi HE-luonnosten vaikutusarvioinnit ennen kuin esitys annetaan. Neuvoston omat lausunnot
ovat valtioneuvosto.fi:ssä, joka vastaa sekä tästä ympäristöstä että GitHubin verkosta Cloudflaren haasteella
(403) – estoa ei kierretä. Hallituksen esityksen laatimisohjeiden mukaan esitykseen kirjoitetaan kuitenkin oma
jakso "Lainsäädännön arviointineuvoston lausunto" (yleensä 6.3 tai 6.x Lausuntopalaute-luvussa): neuvoston
keskeiset havainnot, sen kokonaisarvio ja miten lausunto on otettu huomioon. Tämä vaihe lukee jakson HE:n
XML-tekstistä eduskunnan avoimesta datasta (VaskiData, sama haku kuin fetch_hediff.py).

Välimuisti data/cache/arviointineuvosto.json {"he": {"n/yyyy": {checked, found, date, verdict, text}}}. Annetun
HE:n teksti ei enää muutu, joten kukin HE luetaan kerran; HE, jonka XML ei vielä ole avoimessa datassa, yritetään
seuraavassa ajossa. Ajossa luetaan enintään MAX_PER_RUN uutta HE:tä (uusimmat ensin).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import time

from common import CACHE_DIR, SourceOutage, load_json, log, save_json

OUT = CACHE_DIR / "arviointineuvosto.json"
MAX_PER_RUN = int(os.environ.get("ARVIOINTINEUVOSTO_MAX", "80"))
BUDGET_S = int(os.environ.get("ARVIOINTINEUVOSTO_BUDGET_S", "300"))
TEXT_MAX = 900
VERSION = 2  # 2: subsections, the noudattaa/täyttää grade scale and the "korjattava ennen antamista" recommendation

HEAD = re.compile(r"(?:^|\s)(\d{1,2}(?:\.\d{1,2}){0,3})\s+(?=[A-ZÄÖ][a-zäöå]+[\s,])")  # "6.3 Lainsäädännön …", "7 Säännöskohtaiset …"
TITLE = re.compile(r"Lainsäädännön arviointineuvoston lausunto\b")
NOT_REVIEWED = re.compile(r"\bei (?:ole )?ollut\b[^.]{0,80}arviointineuvos|arviointineuvos[^.]{0,80}\bei (?:ole )?(?:arvioinut|käsitellyt)", re.I)
DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d\d)\b")
# the council's overall grade as the HE reports it. Since 2024: noudattaa/täyttää hyvin, tyydyttävästi, välttävästi,
# ei täytä (heikosti); earlier: (pääosin) ohjeen mukainen, osittain, puutteellinen. First match wins.
GRADE_WORD = r"(hyvin|tyydyttävästi|välttävästi|kohtuullisesti|osittain|pääosin|heikosti|puutteellisesti)"
VERB = r"(?:täyttä|täyttäv|noudatta|noudattav|noudatt)\w*"
GRADES = [
    ("ei täytä", re.compile(r"\bei (?:täytä|noudata)\b|ei ole (?:\w+\s+){0,3}ohjeen mukainen|olennaisesti puutteelli", re.I)),
    ("grade", re.compile(VERB + r"\s+(?:\w+\s+){0,2}" + GRADE_WORD + r"|" + GRADE_WORD + r"\s+" + VERB, re.I)),
    ("pääosin", re.compile(r"pääosin (?:\w+\s+){0,3}ohjeen mukainen", re.I)),
    ("hyvin", re.compile(r"\bon (?:\w+\s+){0,3}ohjeen mukainen|olevan ohjeen mukainen", re.I)),
]
FIX_FIRST = re.compile(r"korjat\w*\s+(?:\w+\s+){0,8}ennen\b|ennen (?:hallituksen )?esityksen antamista", re.I)
VERDICT_LABEL = {"ei täytä": "ei täytä vaatimuksia", "hyvin": "täyttää hyvin", "tyydyttävästi": "täyttää tyydyttävästi",
                 "välttävästi": "täyttää välttävästi", "kohtuullisesti": "täyttää kohtuullisesti", "osittain": "täyttää osittain",
                 "pääosin": "pääosin ohjeen mukainen", "heikosti": "täyttää heikosti", "puutteellisesti": "puutteellinen"}


def flat(xml: str) -> str:
    t = re.sub(r"<[^>]+>", " ", xml)
    t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    t = t.replace("\u200b", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def _sentences(t: str) -> list[str]:
    t = HEAD.sub(lambda m: "\n", t)  # a numbered heading ends the sentence before it
    return [s.strip() for line in t.split("\n") for s in re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖ])", line) if s.strip()]


def _trim(t: str, n: int = TEXT_MAX) -> str:
    if len(t) <= n:
        return t
    cut = t[:n]
    i = cut.rfind(". ")
    return cut[: i + 1] if i > n * 0.5 else cut.rsplit(" ", 1)[0] + " …"


def section_bodies(text: str) -> list[str]:
    """The text under each "N.N Lainsäädännön arviointineuvoston lausunto" heading, its own subsections included
    ("6.2.1 Lausunnon sisältö"), up to the next heading of the same or a higher level."""
    heads = [(m.start(1), m.group(1), m.end()) for m in HEAD.finditer(text)]
    out = []
    for i, (pos, num, end) in enumerate(heads):
        if not TITLE.match(text, end):
            continue
        stop = len(text)
        for pos2, num2, _ in heads[i + 1:]:
            if not num2.startswith(num + "."):
                stop = pos2
                break
        body = text[end + len("Lainsäädännön arviointineuvoston lausunto"):stop]
        body = HEAD.sub(" ", body)  # subsection numbers and their titles stay as plain words
        body = re.sub(r"\b(Lausunnon sisältö|Lausunnon huomioon ottaminen|Lausunnon johdosta tehdyt muutokset)\b\s*", "", body)
        out.append(re.sub(r"\s+", " ", body).strip())
    return out


def grade(body: str) -> tuple[str | None, bool]:
    for key, rx in GRADES:
        m = rx.search(body)
        if m:
            if key == "grade":
                word = next(g for g in m.groups() if g).lower()
                return word, bool(FIX_FIRST.search(body))
            return key, bool(FIX_FIRST.search(body))
    return None, bool(FIX_FIRST.search(body))


def extract(text: str) -> dict:
    """{found, date, verdict, fixFirst, text} from an HE's flattened text. `found` is False when the HE says the
    draft was not reviewed or does not mention the council at all."""
    bodies = section_bodies(text)
    body = max(bodies, key=len) if bodies else ""
    if len(body) < 60:  # only the table of contents line: fall back to the sentences that name the council
        sents = [s for s in _sentences(text) if re.search(r"arviointineuvos", s, re.I) and len(s) < 600]
        body = " ".join(dict.fromkeys(sents[:3]))
    if not body:
        return {"found": False}
    if NOT_REVIEWED.search(body) and not re.search(r"antoi\b|antanut\b|lausunnossaan", body, re.I):
        return {"found": False, "note": "ei arviointineuvoston arvioitavana"}
    # drop the hyperlink label Word leaves in the text ("… antoi lausuntonsa Lainsäädännön arviointineuvoston lausunto (13.10.2025) esitysluonnoksesta …")
    body = re.sub(r"\s*Lainsäädännön arviointineuvoston lausunto \(\d{1,2}\.\d{1,2}\.\d{4}\)", "", body)
    body = re.sub(r"^Lainsäädännön arviointineuvoston lausunto\s+", "", body)
    d = DATE.search(body)
    date = f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d else None
    verdict, fix_first = grade(body)
    rec = {"found": True, "date": date, "verdict": verdict, "text": _trim(body)}
    if fix_first:
        rec["fixFirst"] = True
    return rec


def wanted() -> list[str]:
    """Every HE known to the pipeline (eduskunta cache + Hankeikkuna HE numbers), newest first."""
    ek = (load_json(CACHE_DIR / "eduskunta.json", {}) or {}).get("items") or {}
    hk = (load_json(CACHE_DIR / "hankeikkuna.json", {}) or {}).get("items") or []
    nums = set(ek)
    for p in hk:
        for h in p.get("heNumerot") or []:
            m = re.search(r"(\d+)/(\d{4})", h)
            if m:
                nums.add(f"{int(m.group(1))}/{m.group(2)}")
    return sorted(nums, key=lambda s: (int(s.split("/")[1]), int(s.split("/")[0])), reverse=True)


def main() -> None:
    from fetch_vaski import fetch_by_tunnus
    cache = load_json(OUT, {}) or {}
    he = cache.setdefault("he", {})
    todo = [n for n in wanted() if n not in he or int(he[n].get("v") or 1) < VERSION]
    log(f"arviointineuvosto: {len(he)} HE:tä luettu, {len(todo)} odottaa")
    t0, done, found, outage = time.time(), 0, 0, None
    for num in todo[:MAX_PER_RUN]:
        if time.time() - t0 > BUDGET_S:
            break
        try:
            rows = fetch_by_tunnus(f"HE {num} vp")
        except SourceOutage as e:
            outage = e
            break
        except Exception as e:  # noqa: BLE001
            log(f"warn: arviointineuvosto HE {num}: {e}")
            continue
        doc = max(rows, key=lambda r: len(r[1] or ""), default=None)
        if not doc or len(doc[1] or "") < 20000:  # not yet in the open data (only the käsittelytiedot row): next run
            continue
        rec = extract(flat(doc[1]))
        rec["checked"] = dt.date.today().isoformat()
        rec["v"] = VERSION
        he[num] = rec
        done += 1
        found += bool(rec.get("found"))
    cache["fetched"] = dt.datetime.now().isoformat(timespec="seconds")
    save_json(OUT, cache)
    total = sum(1 for v in he.values() if v.get("found"))
    log(f"arviointineuvosto: {done} HE:tä luettu ({found} arvioitu), yhteensä {total} lausuntoa -> {OUT}")
    if outage and not done:
        raise SourceOutage(f"eduskunnan avoin data ei vastaa: {outage}")


if __name__ == "__main__":
    main()
