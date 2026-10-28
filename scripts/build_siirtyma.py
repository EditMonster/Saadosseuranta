"""Velvoitekalenteri: siirtymäsäännökset ja porrastettu voimaantulo pykälätasolla.

Uutiskirjeet kertovat lain voimaantulopäivän; juristi tarvitsee myös sen, mitä säännöstä sovelletaan vasta myöhemmin,
mikä säännös on määräaikainen, mihin mennessä yhtiöjärjestys tai rekisteröinti on saatettava uuden lain mukaiseksi ja
mihin vanhoihin sopimuksiin ja asioihin sovelletaan yhä vanhaa lakia. Ne ovat lain voimaantulosäännöksessä.

Lähteet (puhtaat funktiot – ei verkkoa):
  * vahvistettu laki: Finlexin säädöskokoelman voimaantulosäännös (fetch_finlex `vtText`), oikeat päivämäärät;
  * eduskunnassa oleva HE: HE-diffin lakiehdotusten voimaantulo- ja siirtymäpykälät (valiokunnan mietintö, kun se
    on annettu, muuten HE) – merkitään ehdotukseksi, koska eduskunta voi muuttaa niitä.

Jokainen virke luokitellaan: porrastettu voimaantulo, soveltaminen alkaa, määräaikainen säännös päättyy, siirtymäajan
määräaika (velvoite), vanhaa lakia sovelletaan (aiemmat sopimukset/asiat) ja kumottua säännöstä sovelletaan asti.
Päivämäärä luetaan suoraan ("1 päivänä tammikuuta 2028", "vuoden 2030 loppuun") tai lasketaan lain voimaantulosta
("kolmen vuoden kuluttua tämän lain voimaantulosta"), kun voimaantulopäivä tiedetään. Kohteeseen tulee lista
`siirtymat` ja päivätyistä säännöistä tapahtumat (kind "siirtyma"), jotka näkyvät aikajanalla, kalenterissa ja
raporteissa.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from common import FI_MONTHS

KIND_LABEL = {"voimaan": "Porrastettu voimaantulo", "soveltaminen": "Soveltaminen alkaa", "voimassa": "Määräaikainen säännös päättyy",
              "velvoite": "Siirtymäajan määräaika", "vanha": "Aiempiin sovelletaan vanhaa lakia", "kumottu": "Kumottua säännöstä sovelletaan asti"}
_DATE = re.compile(r"(\d{1,2})\s+päiv(?:änä|ästä|ään|än)\s+(\w+kuuta)\s+(\d{4})", re.I)
_YEAR_END = re.compile(r"vuoden\s+(\d{4})\s+(?:loppuun|lopussa|päättyessä)", re.I)
_REL = re.compile(r"(?:\b(\w+)\s+)?(vuoden|kuukauden|vuotta|kuukautta)\s+(?:kuluttua|kuluessa)\s+(?:tämän\s+)?(?:lain|asetuksen)\s+voimaantulosta", re.I)
_NUM = {"yhden": 1, "kahden": 2, "kolmen": 3, "neljän": 4, "viiden": 5, "kuuden": 6, "seitsemän": 7, "kahdeksan": 8, "yhdeksän": 9,
        "kymmenen": 10, "yhdentoista": 11, "kahdentoista": 12, "kahdeksantoista": 18, "kahdenkymmenenneljän": 24, "kolmenkymmenenkuuden": 36}
_NUMREF = r"\d+(?:\s?[a-z](?![a-zäö]))?"
_SECTION = re.compile(r"(?:\d+\s+(?:[a-z]\s+)?luvun\s+)?" + _NUMREF + r"(?:(?:\s?[–,]\s?|\s+ja\s+)" + _NUMREF + r")*\s?§(?::[nää]+)?"
                      r"(?:\s+\d+(?:\s+ja\s+\d+)?\s+momentti(?:a)?)?")
_GENERIC = re.compile(r"^Tämä\s+(?:laki|asetus)\s+tulee\s+voimaan\s+(?:päivänä\s+kuuta\s+20\s*\.*|\d{1,2}\s+päivänä\s+\w+kuuta\s+\d{4}\.?)\s*$", re.I)
_OBLIGATION = re.compile(r"\b(?:viimeistään|mennessä|on\s+(?:saatettava|muutettava|tehtävä|ilmoitettava|haettava|toimitettava|järjestettävä|laadittava|päivitettävä)|tulee\s+(?:hakea|ilmoittaa|saattaa))\b", re.I)
MAX_RULES = 14


def _iso(d: int, month: str, y: int) -> str | None:
    m = FI_MONTHS.get(month.lower())
    try:
        return dt.date(y, m, d).isoformat() if m else None
    except ValueError:
        return None


def _add_months(base: str, months: int) -> str:
    d = dt.date.fromisoformat(base)
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    import calendar
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1])).isoformat()


def sentences(text: str) -> list[str]:
    """Split a provision into sentences and list items ("1) ... ;")."""
    text = re.sub(r"[ \s]+", " ", (text or "").replace("\n", " ¶ ")).strip()
    parts = re.split(r"(?<=[.;:])\s+(?=(?:\d+\)\s)|[A-ZÄÖÅ])|\s*¶\s*", text)
    out = []
    for p in parts:
        p = p.strip(" ¶")
        if len(p) > 6 and not p.startswith("— —"):
            out.append(p)
    return out


_TAX_YEAR = re.compile(r"(?:kalenteri|vero|tili)?vuodelta\s+(\d{4})|vuoden\s+(\d{4})\s+verotu", re.I)


def _dates(s: str) -> list[str]:
    ds = [_iso(int(d), mo, int(y)) for d, mo, y in _DATE.findall(s)]
    ds += [f"{y}-12-31" for y in _YEAR_END.findall(s)]
    if not ds and "sovelletaan" in s.lower():  # "sovelletaan ensimmäisen kerran vuodelta 2027 toimitettavassa verotuksessa"
        ds += [f"{a or b}-01-01" for a, b in _TAX_YEAR.findall(s)]
    return [d for d in dict.fromkeys(ds) if d]


def _relative(s: str) -> tuple[int, str] | None:
    """('kolmen vuoden kuluttua tämän lain voimaantulosta') -> (36, '3 v')"""
    m = _REL.search(s)
    if not m:
        return None
    word, unit = (m.group(1) or "").lower(), m.group(2).lower()
    n = _NUM.get(word) or (int(word) if word.isdigit() else 1)
    months = n * 12 if unit.startswith("vuo") else n
    return months, (f"{n} v" if unit.startswith("vuo") else f"{n} kk")


def classify(s: str) -> str | None:
    low = s.lower()
    if _GENERIC.match(s):
        return None
    if low.startswith("kumottu") or re.search(r"\bkumottu\w*\s+[\d\s§a-z,–-]*\s*sovelletaan", low):
        return "kumottu"
    if re.search(r"\b(?:on|ovat)\s+voimassa\b", low) and (_DATE.search(s) or _YEAR_END.search(s)):
        return "voimassa"
    if _OBLIGATION.search(s) and (_DATE.search(s) or _YEAR_END.search(s) or _REL.search(s)):
        return "velvoite"
    if re.search(r"\btule(?:e|vat)\s+(?:kuitenkin\s+)?(?:vasta\s+)?voimaan\b", low) and not low.startswith("tämä laki tulee voimaan päivänä") \
            and (_DATE.search(s) or _REL.search(s)) and not re.match(r"^tämä\s+(?:laki|asetus)\s+tulee\s+voimaan\s+\d", low):
        return "voimaan"
    if "sovelletaan" in low and re.search(r"ennen\s+(?:tämän\s+)?(?:lain|asetuksen)\s+voimaantuloa|(?:lain|asetuksen)\s+voimaan\s+tullessa", low) \
            and re.search(r"voimassa\s*ollei|aiemp|vanh", low):
        return "vanha"
    if re.search(r"\btule(?:e|vat)\s+voimaan\s+valtioneuvoston\s+asetuksella\s+säädettävänä\s+ajankohtana", low):
        return "voimaan"
    if "sovelletaan" in low and (_DATE.search(s) or _REL.search(s) or "ensimmäisen kerran" in low):
        return "soveltaminen"
    return None


def scope(s: str) -> str:
    secs = [re.sub(r"\s+", " ", x).strip() for x in _SECTION.findall(s)]
    secs = [x for x in dict.fromkeys(secs) if x]
    if secs:
        return ", ".join(secs[:3]) + (" …" if len(secs) > 3 else "")
    for kw, label in (("yhtiöjärjestys", "yhtiöjärjestykset"), ("sääntö", "säännöt"), ("sopimu", "sopimukset"), ("tilikau", "tilikaudet"),
                      ("rekisteröin", "rekisteröinnit"), ("lup", "luvat"), ("hakemu", "hakemukset"), ("kirjanpi", "kirjanpito")):
        if kw in s.lower():
            return label
    return ""


def rules_from_text(text: str, base: str | None, law: str, src: str) -> list[dict]:
    out = []
    for s in sentences(text):
        k = classify(s)
        if not k:
            continue
        ds = _dates(s)
        rel = _relative(s)
        r = {"k": k, "t": s[:420], "law": law[:160], "src": src}
        sc = scope(s)
        if sc:
            r["s"] = sc
        if ds:
            r["d"] = ds[0]
            if len(ds) > 1:
                r["d2"] = ds[1:3]
        elif k == "voimaan" and "asetuksella säädettävänä" in s:
            r["r"] = "asetuksella"
        elif rel:
            r["r"] = rel[1]
            if base:
                r["d"] = _add_months(base, rel[0])
                r["calc"] = 1  # computed from the entry-into-force date
        out.append(r)
    return out


def finlex_vt_text(page_text: str) -> str:
    """The entry-into-force provision of a statute page (Finlex RSC payload): from "Tämä laki/asetus tulee voimaan" to
    the signatures. Used by fetch_finlex."""
    spans = [m.group(1) for m in re.finditer(r'"className":"highlightable","children":"((?:[^"\\]|\\.)*)"', page_text)]
    def unesc(x: str) -> str:  # JSON string escapes (\\u00a0, \\") inside the payload; keeps ä/ö as they are
        try:
            return json.loads('"' + x + '"') if "\\" in x else x
        except ValueError:
            return x
    spans = [unesc(s) for s in spans]
    start = next((i for i, s in enumerate(spans) if re.match(r"\s*Tämä\s+(?:laki|asetus)\s+tulee\s+voimaan", s)), None)
    if start is None:
        return ""
    out = []
    for s in spans[start:start + 40]:
        if re.match(r"\s*(?:Helsingissä|Annettu\s+Helsingissä|Tasavallan\s+Presidentti|Pääministeri)\b", s) or re.search(r"ministeri\s*$", s.strip()) \
                or "\\n" in s or "\n" in s or re.search(r"\b(?:träder\s+i\s+kraft|sådan\s+den\s+lyder|Denna\s+(?:lag|förordning))\b", s):
            break  # the signatures, or the Swedish version that follows on the same page
        out.append(s.replace("\xa0", " ").strip())
    return "\n".join(out)[:6000]


def _he_texts(diff: dict) -> list[tuple[str, str, str]]:
    """(law name, provision text, source) from the latest step of an HE-diff: the committee report if any, else the HE."""
    steps = diff.get("steps") or []
    if not steps:
        return []
    st = steps[-1]
    src = "mietintö" if st.get("kind") == "mietinto" else "HE"
    out = []
    for law in st.get("laws") or []:
        for sec in law.get("sections") or []:
            head = f"{sec.get('id') or ''} {sec.get('heading') or ''}"
            if not re.search(r"voimaantulo|siirtymä", head, re.I):
                continue
            txt = " ".join(o[1] for o in sec.get("ops") or [] if isinstance(o, list) and len(o) > 1 and o[0] in ("=", "+"))
            if txt:
                out.append((law.get("name") or "", txt, src))
    return out


def attach(items: list[dict], diffs: dict[str, dict], finlex: dict[str, dict], today: str | None = None) -> int:
    """Add `siirtymat` and "siirtyma" events to items. diffs: item id -> HE-diff; finlex: sk -> cache record."""
    today = today or dt.date.today().isoformat()
    n = 0
    for it in items:
        if it.get("scope") != "fi":
            continue
        base = next((e["date"] for e in it.get("events") or [] if e.get("kind") == "voimaan" and e.get("date")), None)
        rules: list[dict] = []
        for sk in it.get("sk") or []:
            rec = finlex.get(sk) or {}
            if rec.get("vtText"):
                rules += rules_from_text(rec["vtText"], rec.get("voimaan") or base, f"{rec.get('title') or ''} ({sk})".strip(), "sk")
        if not rules and it["id"] in diffs:
            for law, txt, src in _he_texts(diffs[it["id"]]):
                rules += rules_from_text(txt, base, law, src)
        if not rules:
            it.pop("siirtymat", None)
            continue
        seen, uniq = set(), []
        for r in rules:
            key = (r["k"], r.get("d"), r.get("s"), r["t"][:80])
            if key not in seen:
                seen.add(key)
                uniq.append(r)
        uniq.sort(key=lambda r: (r.get("d") or "9999", r["k"]))
        it["siirtymat"] = uniq[:MAX_RULES]
        n += 1
        evs = it.setdefault("events", [])
        have = {(e.get("kind"), e.get("date"), e.get("label")) for e in evs}
        for r in it["siirtymat"]:
            for d in [r.get("d")] + list(r.get("d2") or []):
                if not d or r["k"] == "vanha":
                    continue
                label = f"{KIND_LABEL[r['k']]}{': ' + r['s'] if r.get('s') else ''}"
                if (("siirtyma", d, label)) in have:
                    continue
                have.add(("siirtyma", d, label))
                evs.append({"date": d, "end": d, "kind": "siirtyma", "label": label, "confirmed": r["src"] == "sk" and not r.get("calc")})
    return n
