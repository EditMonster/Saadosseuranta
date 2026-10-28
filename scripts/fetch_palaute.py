"""Hallitusten esitysten Lausuntopalaute-luku: mitä ministeriö kertoo lausunnonantajien ehdotuksista ja niiden
huomioon ottamisesta.

Hallituksen esityksen laatimisohjeiden mukaan esitykseen kirjoitetaan luku "Lausuntopalaute": keneltä lausuntoa
pyydettiin, mitä lausunnonantajat (usein nimeltä) esittivät ja miten palaute vaikutti esitykseen ("Palautteen
johdosta jaksoon 4.2.3 on lisätty …", "Ehdotusta ei ole pidetty perusteltuna …"). Tämä vaihe lukee luvun HE:n
XML-tekstistä eduskunnan avoimesta datasta (VaskiData, sama haku kuin fetch_arviointineuvosto.py) ja tallentaa sen
kappaleina alalukujen otsikoineen. Lausunnonantajiin kohdistus tehdään rakennusvaiheessa (build_palaute.py), joten
sitä voi parantaa ilman uutta hakua.

Välimuisti on jaettu vuosittain, jotta ajo kirjoittaa vain muuttuneen vuoden tiedoston (julkinen repo, pieni
historia): data/cache/palaute/<vuosi>.json {"he": {"n/yyyy": {checked, v, found, secs: [{h, p: [kappale, …]}]}}}.
Annetun HE:n teksti ei muutu, joten kukin luetaan kerran; HE, jonka XML ei vielä ole avoimessa datassa, yritetään
seuraavassa ajossa. Ajossa luetaan enintään MAX_PER_RUN HE:tä (uusimmat ensin).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import time
import xml.etree.ElementTree as ET

from common import CACHE_DIR, SourceOutage, load_json, log, save_json

DIR = CACHE_DIR / "palaute"
MAX_PER_RUN = int(os.environ.get("PALAUTE_MAX", "150"))
BUDGET_S = int(os.environ.get("PALAUTE_BUDGET_S", "420"))
VERSION = 1
PARA_MAX = 2500       # characters per paragraph
CHAPTER_MAX = 40_000  # characters per HE
TITLE = re.compile(r"^(?:lausuntopalaute|lausuntomenettely|lausunnot ja niiden huomioon ottaminen|lausuntokierros)\b", re.I)  # 2018– vaihtelevat otsikot


def _text(el: ET.Element) -> str:
    t = "".join(el.itertext()).replace("​", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def _heading(chapter: ET.Element) -> str:
    h = chapter.find("LukuOtsikko")
    if h is None:
        return ""
    nro, txt = h.find("OtsikkoNroTeksti"), h.find("OtsikkoTeksti")
    return " ".join(x for x in ((_text(nro) if nro is not None else ""), (_text(txt) if txt is not None else "")) if x)


def chapter(root: ET.Element) -> list[dict]:
    """The paragraphs of the HE's "Lausuntopalaute" chapter grouped by subsection: [{"h": "6.2 …", "p": [...]}]."""
    for ch in root.iter("PerusteluLuku"):
        head = ch.find("LukuOtsikko")
        title = head.find("OtsikkoTeksti") if head is not None else None
        if title is None or not TITLE.match(_text(title)):
            continue
        secs: list[dict] = []
        size = 0

        def walk(el: ET.Element, heading: str) -> None:
            nonlocal size
            for child in el:
                if child.tag == "PerusteluLuku":
                    walk(child, _heading(child) or heading)
                elif child.tag == "KappaleKooste":
                    t = _text(child)
                    if len(t) < 20 or size > CHAPTER_MAX:
                        continue
                    t = t[:PARA_MAX]
                    size += len(t)
                    if not secs or secs[-1]["h"] != heading:
                        secs.append({"h": heading, "p": []})
                    secs[-1]["p"].append(t)
                elif child.tag not in ("LukuOtsikko",):
                    walk(child, heading)

        walk(ch, _heading(ch))
        if secs:
            return secs
    return []


def _year(num: str) -> str:
    return num.split("/")[1]


def load_all() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted(DIR.glob("*.json")):
        out.update((load_json(f, {}) or {}).get("he") or {})
    return out


def main() -> None:
    from fetch_arviointineuvosto import wanted
    from fetch_vaski import fetch_by_tunnus, strip_ns
    he = load_all()
    todo = [n for n in wanted() if n not in he or int(he[n].get("v") or 0) < VERSION]
    log(f"palaute: {len(he)} HE:tä luettu, {len(todo)} odottaa")
    t0, done, found, outage, touched = time.time(), 0, 0, None, set()
    for num in todo[:MAX_PER_RUN]:
        if time.time() - t0 > BUDGET_S:
            break
        try:
            rows = fetch_by_tunnus(f"HE {num} vp")
        except SourceOutage as e:
            outage = e
            break
        except Exception as e:  # noqa: BLE001
            log(f"warn: palaute HE {num}: {e}")
            continue
        # the government proposal itself (not the committee report or the käsittelytiedot row of the same tunnus)
        rows = [r for r in rows if "GovernmentProposal_fi" in (r[1] or "")[:3000] and "KasittelytiedotValtiopaivaasia" not in (r[1] or "")]
        doc = max(rows, key=lambda r: len(r[1] or ""), default=None)
        if not doc or len(doc[1] or "") < 20000:  # not yet in the open data: next run
            continue
        try:
            secs = chapter(strip_ns(doc[1]))
        except ET.ParseError as e:
            log(f"warn: palaute HE {num}: XML {e}")
            secs = []
        he[num] = {"checked": dt.date.today().isoformat(), "v": VERSION, "found": bool(secs), **({"secs": secs} if secs else {})}
        touched.add(_year(num))
        done += 1
        found += bool(secs)
    for y in sorted(touched):
        save_json(DIR / f"{y}.json", {"he": {n: v for n, v in he.items() if _year(n) == y}})
    total = sum(1 for v in he.values() if v.get("found"))
    log(f"palaute: {done} HE:tä luettu ({found} lausuntopalautteella), yhteensä {total} -> {DIR}")
    if outage and not done:
        raise SourceOutage(f"eduskunnan avoin data ei vastaa: {outage}")


if __name__ == "__main__":
    main()
