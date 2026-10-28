"""Lausunnonantajan ehdotusten kohtalo ministeriövaiheessa: HE:n Lausuntopalaute-luvusta (fetch_palaute.py).

Jokaisen hankkeen lausuntokierroksella lausuneet organisaatiot etsitään HE:n lausuntopalauteluvusta. Kohdistus
rajataan niihin, jotka todella lausuivat samassa hankkeessa, mikä pitää virheosumat vähäisinä. Nimi tunnistetaan
taivutettuna ("Poliisihallitus" → "Poliisihallituksen", "Suomen Kuntaliitto ry" → "Kuntaliiton"), myös
sulkeissa olevalla lyhenteellä.

Lauseelle, jossa organisaatio mainitaan, etsitään samasta kappaleesta seuraavista lauseista ministeriön vastaus:
  * h = huomioitiin: "palautteen johdosta / perusteella", "on lisätty / täsmennetty / tarkennettu / muutettu …",
    "on otettu huomioon";
  * e = ei huomioitu: "ei ole pidetty perusteltuna / tarkoituksenmukaisena", "ei ole muutettu", "on katsottu
    perustelluksi säilyttää";
  * m = mainittu: kanta kerrotaan, mutta vastausta ei ole samassa kappaleessa.
Vastaus kohdistetaan lähimpään sitä edeltävään mainintaan (yleensä sama tai edellinen lause). Ministeriön
vastaus on ministeriön oma kuvaus, ja lähdelauseet tallennetaan rinnalle tarkistettaviksi.

Tulos: docs/data/palaute/<kohteen id>.json {"he", "orgs": {nimi: {"r": h|e|m, "s": [[otsikko, maininta, vastaus], …]}}}
ja build() palauttaa {kohteen id: {nimi: r}} sidosryhmäprofiileja varten.
"""
from __future__ import annotations

import re
from pathlib import Path

from common import CACHE_DIR, HIDDEN_GIVERS, OUT_DIR, is_sole_trader, load_json, looks_like_person, save_json

YES = re.compile(r"\b(?:palautteen|lausuntopalautteen|lausuntojen|lausunnon|lausunnoissa esitetyn|huomautusten)\s+(?:johdosta|perusteella|vuoksi|pohjalta)"
                 r"|\bon\s+(?:\w+\s+){0,3}(?:lisätty|täsmennetty|tarkennettu|muutettu|korjattu|poistettu|selkeytetty|täydennetty|"
                 r"tarkistettu|laajennettu|rajattu|lievennetty|pidennetty|lyhennetty|kirjoitettu)\b"
                 r"|\b(?:lisättiin|täsmennettiin|tarkennettiin|muutettiin|korjattiin|poistettiin|täydennettiin|selkeytettiin|tarkistettiin|"
                 r"laajennettiin|rajattiin|lievennettiin|pidennettiin|lyhennettiin|selvennettiin)\b"
                 r"|\botettu\s+(?:\w+\s+){0,2}huomioon\b|\bhuomioitu\b|\bon\s+(?:päädytty|päätetty)\s+(?:\w+\s+){0,4}(?:muutta|lisät|poista|täsmentä)", re.I)
NO = re.compile(r"\bei\s+(?:ole\s+)?(?:\w+\s+){0,3}(?:katsottu|pidetty|nähty|arvioitu)\s+(?:\w+\s+){0,4}(?:tarpeelli|tarkoituksenmukai|perustel|"
                r"mahdolli|aiheelli|välttämätö|järkevä)\w*"
                r"|\bei\s+ole\s+(?:\w+\s+){0,2}(?:muutettu|tehty|lisätty|otettu\s+huomioon|ollut\s+mahdollista|lähdetty)"
                r"|\bon\s+(?:pidetty|katsottu)\s+(?:\w+\s+){0,2}(?:perusteltuna|perustelluksi|tarkoituksenmukaisena)\s+(?:säilyttää|pitää|pysyä)"
                r"|\b(?:esitystä|ehdotusta|esitysluonnosta)\s+ei\s+(?:ole\s+)?muutettu"
                r"|\bmutta\s+(?:\w+\s+){0,4}päädyttiin|\bpäädyttiin\s+(?:kuitenkin\s+)?(?:säilyttämään|pitämään|pysymään)", re.I)
LISTING = re.compile(r"lausun\w* (?:antoivat|antoi|saapui|saatiin|pyydettiin)|vastaanottaj|lausuntopyyntö (?:lähetettiin|osoitettiin)|"
                     r"lausunnon (?:jättivät|toimittivat)|lausuntonsa antoivat|lausuntoja (?:saatiin|annettiin)", re.I)
REPORTING = re.compile(r"\b(?:totea[av]?|totesi|totesivat|toteavat|katsoo|katsoi|katsoivat|katsovat|esittää|esitti|esittivät|esittävät|"
                       r"ehdottaa|ehdotti|ehdottivat|ehdottavat|piti|pitivät|pitää|pitävät|mukaan|vaatii|vaati|vaativat|edellyttää|edellytti|"
                       r"edellyttivät|korostaa|korosti|korostivat|kannattaa|kannatti|kannattivat|vastustaa|vastusti|vastustivat|huomauttaa|"
                       r"huomautti|huomauttivat|toivoo|toivoi|toivoivat|kiinnitti|kiinnittivät|lausuu|lausui|lausuivat|lausunnossaan|"
                       r"lausunnoissaan|arvioi|arvioivat|muistutti|muistuttaa|painotti|painottaa|suhtautui|suhtautuivat)\b"
                       r"|\b(?:tuo|toi|toivat|tuovat|nosti|nostivat|nostaa)\s+(?:\w+\s+){0,2}esi(?:in|lle)\b", re.I)
OTHER = re.compile(r"\b[A-ZÅÄÖ][\wåäö-]+(?:n|in|en)\s+(?:kommentti|kommentit|lausunto|lausunnon|ehdotus|ehdotuksen|huomio|huomiot|huomautus)\b")
GENERIC = {"lausunto", "lausunnot", "kommentti", "kommentit", "muistio", "liite", "vastaus", "palaute", "lausuntoyhteenveto", "yhteenveto"}
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÅÄÖ0-9])")
_DROP = re.compile(r"\b(?:ry|rf|r\.y\.|oy|oyj|ab|abp|ltd|plc)\b\.?", re.I)
QUOTE_MAX = 320


def _stem(word: str) -> str:
    """A prefix that survives Finnish case endings: Poliisihallitus → Poliisihallitu(s|ksen), Kuntaliitto → Kuntaliit."""
    w = word.lower()
    if len(w) <= 4:
        return re.escape(w)
    cut = 2 if len(w) <= 7 else 3
    return re.escape(w[:-cut]) + r"\w*"


def name_pattern(name: str) -> re.Pattern | None:
    """Regex for an organisation's name as it appears in running Finnish text, or None for a too generic name."""
    parts = re.split(r",\s+(?=[A-ZÅÄÖ])|\s+/\s+", name)
    n = parts[0] if len(parts[0].split()) >= 2 or len(parts[0]) >= 8 else name
    abbr = re.findall(r"\(([A-ZÅÄÖ][\w-]{1,10})\)", n)
    n = re.sub(r"\([^)]*\)", " ", n)
    n = _DROP.sub(" ", n)
    words = [w for w in re.findall(r"[\wÅÄÖåäö][\wÅÄÖåäö-]*", n) if w]
    while len(words) >= 2 and re.fullmatch(r"[A-ZÅÄÖ]{2,6}", words[-1]):  # "Keskusrikospoliisi KRP", "… keskusliitto EK"
        abbr.append(words.pop())
    if not words or len("".join(words)) < 3:
        return None
    alts = []
    if len(words) == 1 and len(words[0]) < 7:  # "Kela", "Tulli": the word itself with a case ending
        alts.append(re.escape(words[0].lower()) + r"(?::\w+|\w{0,4}\b)")
    else:
        alts.append(r"\s+".join([re.escape(w.lower()) for w in words[:-1]] + [_stem(words[-1])]))
    if len(words) >= 2 and words[0].lower() in ("suomen", "finlands", "suomi"):  # "Suomen Kuntaliitto" → "Kuntaliitto"
        rest = words[1:]
        if len(" ".join(rest)) >= 8:
            alts.append(r"\s+".join([re.escape(w.lower()) for w in rest[:-1]] + [_stem(rest[-1])]))
    for a in abbr:
        if len(a) >= 2:
            alts.append(r"(?-i:" + re.escape(a) + r")(?::\w+|\b)")
    return re.compile(r"(?<![\w-])(?:" + "|".join(alts) + r")", re.I)


def match_item(secs: list[dict], orgs: list[str]) -> dict[str, dict]:
    """{org: {"r": h|e|m, "s": [[heading, mention, response], …]}} for the organisations named in the chapter."""
    pats = {o: p for o in orgs if o.strip().lower() not in GENERIC and (p := name_pattern(o))}
    out: dict[str, dict] = {}
    for sec in secs:
        last_mention: list[tuple[int, str]] = []  # (sentence index, org) of the latest mention group in this subsection
        base = 0
        for para in sec.get("p") or []:
            sents = SENT.split(para)
            if last_mention and base - last_mention[0][0] > 1:
                last_mention = []  # a new paragraph answers the previous one only when it follows right after it
            for j, s in enumerate(sents):
                i = base + j
                named = [o for o, p in pats.items() if p.search(s)]
                if named and (LISTING.search(s) or len(named) >= 5):
                    named = []  # "Lausunnon antoivat A, B, C …": a list of givers, not a position
                if named:
                    last_mention = [(i, o) for o in named]
                    for o in named:
                        rec = out.setdefault(o, {"r": "m", "s": []})
                        rec.setdefault("_m", []).append((sec.get("h") or "", s))
                own_words = bool(named) and bool(REPORTING.search(s))  # the giver's own claim, not the ministry's answer
                verdict = None if own_words else ("e" if NO.search(s) else ("h" if YES.search(s) else None))
                if verdict and not named and OTHER.search(s):
                    verdict = None  # "Ympäristöministeriön kommentti on huomioitu": the answer names someone else
                if verdict and last_mention and i - last_mention[0][0] <= 3:
                    for _, o in last_mention:
                        rec = out[o]
                        mention = next((m for h, m in reversed(rec.get("_m", [])) if m), "")
                        if verdict == "h" or rec["r"] == "m":
                            rec["r"] = verdict if rec["r"] != "h" else "h"
                        quote = [sec.get("h") or "", mention[:QUOTE_MAX], s[:QUOTE_MAX] if s != mention else ""]
                        if quote not in rec["s"] and len(rec["s"]) < 4:
                            rec["s"].append(quote)
            base += len(sents)
    for o, rec in out.items():
        if not rec["s"]:
            h, m = rec["_m"][0]
            rec["s"].append([h, m[:QUOTE_MAX], ""])
        rec.pop("_m", None)
    return out


def _he_nums(it: dict) -> list[str]:
    out = []
    for h in it.get("heNumerot") or []:
        m = re.search(r"(\d+)/(\d{4})", str(h))
        if m:
            out.append(f"{int(m.group(1))}/{m.group(2)}")
    return out


def build(statements: dict[str, dict], items: dict[str, dict], palaute: dict[str, dict], out_dir: Path | None = None) -> dict[str, dict]:
    """Writes docs/data/palaute/<id>.json (when out_dir is given) and returns {item id: {org: verdict}}."""
    res: dict[str, dict] = {}
    keep = set()
    for iid, d in statements.items():
        rows = (d.get("kierros") or {}).get("rivit") or []
        orgs = sorted({r.get("org") for r in rows if r.get("org") and r.get("org") not in HIDDEN_GIVERS
                       and not is_sole_trader(r.get("org")) and not looks_like_person(r.get("org"))})
        if not orgs:
            continue
        for num in _he_nums(items.get(iid) or {}):
            secs = (palaute.get(num) or {}).get("secs")
            if not secs:
                continue
            m = match_item(secs, orgs)
            if not m:
                continue
            res[iid] = {o: v["r"] for o, v in m.items()}
            if out_dir is not None:
                save_json(out_dir / f"{iid}.json", {"id": iid, "he": num, "orgs": m}, compact=True)
                keep.add(f"{iid}.json")
            break
    if out_dir is not None:
        for f in out_dir.glob("*.json"):
            if f.name not in keep:
                f.unlink()
    return res


def main(items: list[dict]) -> dict[str, dict]:
    from fetch_palaute import load_all
    statements = {}
    for f in sorted((OUT_DIR / "lausunnot").glob("*.json")):
        d = load_json(f, {}) or {}
        statements[d.get("id") or f.stem] = d
    out = OUT_DIR / "palaute"
    out.mkdir(parents=True, exist_ok=True)
    return build(statements, {i["id"]: i for i in items}, load_all(), out)


__all__ = ["build", "main", "match_item", "name_pattern", "CACHE_DIR"]
