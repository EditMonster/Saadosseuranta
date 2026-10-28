"""Sidosryhmien kannat organisaatioittain: kuka on lausunut mistäkin ja mitä mieltä, kenen kanssa samaa mieltä.

Lähde: sivun annetut lausunnot (docs/data/lausunnot/<id>.json – Hankeikkunan lausuntokierrokset ja eduskunnalle
annetut asiantuntijalausunnot, kanta luokiteltu fetch_lausunnot.py:ssä). Puhdas funktio – ei verkkoa.

  * Nimet yhdistetään: kirjainkoko, "ry/Oy", sulkeissa oleva lyhenne, "täydentävä lausunto", "X edustaen Y:tä"
    (edustettu järjestö) ja pari tunnettua rinnakkaisnimeä (EK, SAK, STTK, Kuntaliitto ...). Yksityishenkilöt
    (tietosuoja) ja tunnistamattomat jätetään pois.
  * Kanta ryhmitellään: kannattaa (S), varauksin tai muutosehdotuksin (R), vastustaa kokonaan tai osin (O) ja
    neutraali (kannanotto, virkamiesesittely, ei lausuttavaa).
  * Samanmieliset ja vastapuoli: vähintään viidessä samassa hankkeessa kantansa ilmaisseiden organisaatioiden
    yhtäpitävyys (sama ryhmä = 1, viereinen = ½, vastakkainen = 0).
  * Yhtäpitävyys painotetaan otoskoolla (kolmen hankkeen "neutraali" ennakko), jottei viiden hankkeen sattuma nouse
    kärkeen; näytetään prosentti ja yhteisten hankkeiden määrä.
  * Vastustus ja valiokunnan muutokset (bins): tarkistettu aineistosta – valiokunta muuttaa noin kaksi kolmasosaa
    esityksistä riippumatta lausuntokierroksen vastustuksen määrästä, joten sitä ei esitetä ennusteena sivulla.

Tulos: docs/data/sidosryhmat.json, ladataan sivulla vasta kun profiili tai haku avataan. Tiivis muoto: "ids" listaa
kohteet, ja kannanotto on [kohteen indeksi, kanta-koodi (STANCE_CODE), päivä, k=kierros/e=eduskunta].
"""
from __future__ import annotations

import collections
import re
from pathlib import Path

from common import PRIVATE_LABEL

GROUP = {"kannattaa": "S", "varauksin": "R", "muutoksia": "R", "vastustaa": "O", "osin": "O", "kanta": "N", "esittely": "N", "ei": "N"}
ALIAS = {"elinkeinoelämän keskusliitto": "elinkeinoelämän keskusliitto ek", "ek": "elinkeinoelämän keskusliitto ek",
         "sak": "suomen ammattiliittojen keskusjärjestö sak", "toimihenkilökeskusjärjestö sttk": "sttk",
         "kuntaliitto": "suomen kuntaliitto", "kilpailu- ja kuluttajavirasto kkv": "kilpailu- ja kuluttajavirasto",
         "kkv": "kilpailu- ja kuluttajavirasto", "tietosuojavaltuutettu": "tietosuojavaltuutetun toimisto",
         "kela": "kansaneläkelaitos", "mtk": "maa- ja metsätaloustuottajain keskusliitto mtk", "keskuskauppakamari": "keskuskauppakamari"}
_TAIL = re.compile(r"\s+(?:täydentävä(?:\s+lausunto)?|lisäselvitys|lisälausunto|lausuntopyynnöt|lausunto(?:\s+ei\s+lausuttavaa)?|ei\s+lausuttavaa|"
                   r"kirjallinen\s+lausunto|liite\s*\d*)$", re.I)
BINS = ((0, 10), (10, 25), (25, 50), (50, 101))
STANCE_CODE = {"kannattaa": "a", "varauksin": "b", "muutoksia": "c", "vastustaa": "d", "osin": "e", "kanta": "f", "esittely": "g", "ei": "h"}
PRIOR_N, PRIOR = 5, 0.55


def key_of(name: str) -> str:
    s = " ".join(str(name or "").split())
    m = re.search(r"\sedustaen\s+(myös\s+)?(.+)$", s, re.I)
    if m:  # "Yhtiö Oy edustaen myös Liitto ry:tä" → the company itself; "Henkilö, yhtiö edustaen Liitto ry:tä" → the association
        s = s[:m.start()] if m.group(1) else re.split(r"\s*:tä\b|\s+ja\s+", m.group(2))[0]
    s = s.casefold()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[\"'”“.,]", " ", s)
    s = re.sub(r"\b(?:ry|r\s?y|rf|r\s?f|oy|oyj|ab|abp|ltd|plc)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -")
    for _ in range(2):
        s = _TAIL.sub("", s).strip()
    return ALIAS.get(s, s)


def _display(variants: collections.Counter) -> str:
    best = sorted(variants.items(), key=lambda kv: (-kv[1], not kv[0][:1].isupper(), len(kv[0])))[0][0]
    return re.sub(r"\s+(?:täydentävä(?:\s+lausunto)?|lisäselvitys)$", "", best, flags=re.I)


def build(statements: dict[str, dict], items: dict[str, dict]) -> dict:
    """statements: item id -> docs/data/lausunnot/<id>.json payload; items: id -> item (title, topics)."""
    variants: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    pos: dict[str, list] = collections.defaultdict(list)
    bins = [[lo, hi, 0, 0] for lo, hi in BINS]
    for iid, d in statements.items():
        for sec, code in (("kierros", "k"), ("eduskunta", "e")):
            for r in (d.get(sec) or {}).get("rivit") or []:
                org = (r.get("org") or "").strip()
                st = r.get("stance") or ""
                if not org or org == PRIVATE_LABEL or len(org) < 2 or st not in GROUP:
                    continue
                k = key_of(org)
                if not k or len(k) < 2:
                    continue
                variants[k][org] += 1
                pos[k].append([iid, st, r.get("date") or "", code])
        # opposition on the consultation round vs. what the committee did
        kier = (d.get("kierros") or {}).get("kannat") or {}
        s_r_o = sum(v for s, v in kier.items() if GROUP.get(s) in ("S", "R", "O"))
        decisions = [v.get("decision") for v in d.get("valiokunnat") or [] if v.get("kind") == "mietintö" and v.get("decision")]
        if s_r_o >= 5 and decisions:
            share = 100 * sum(v for s, v in kier.items() if GROUP.get(s) == "O") / s_r_o
            changed = any(x == "muutettuna" for x in decisions) or any(v.get("changedSections") for v in d.get("valiokunnat") or [])
            for b in bins:
                if b[0] <= share < b[1]:
                    b[2] += int(changed)
                    b[3] += 1
    # "X" and "X ABBR" are the same body when both occur ("terveyden ja hyvinvoinnin laitos" / "... thl")
    for k in list(variants):
        if k in variants:
            longer = [o for o in variants if o.startswith(k + " ") and len(o.split()) == len(k.split()) + 1 and len(o.split()[-1]) <= 6]
            if len(longer) == 1:
                o = longer[0]
                variants[o].update(variants.pop(k))
                pos[o].extend(pos.pop(k))
    # one position per organisation and item for agreement: the latest non-neutral one
    latest: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for k, ps in pos.items():
        for iid, st, date, _ in sorted(ps, key=lambda p: p[2]):
            g = GROUP[st]
            if g != "N":
                latest[k][iid] = g
    cand = {k for k, m in latest.items() if len(m) >= 8}
    by_item: dict[str, list] = collections.defaultdict(list)
    for k in cand:
        for iid, g in latest[k].items():
            by_item[iid].append((k, g))
    VAL = {"S": 2, "R": 1, "O": 0}
    agree: dict[tuple, list] = collections.defaultdict(lambda: [0.0, 0])
    for iid, lst in by_item.items():
        lst.sort()
        for i in range(len(lst)):
            ki, gi = lst[i]
            for j in range(i + 1, len(lst)):
                kj, gj = lst[j]
                a = agree[(ki, kj)]
                a[0] += 1 - abs(VAL[gi] - VAL[gj]) / 2
                a[1] += 1
    rel: dict[str, list] = collections.defaultdict(list)
    for (a, b), (score, n) in agree.items():
        if n >= 5:
            r, adj = round(100 * score / n), (score + PRIOR_N * PRIOR) / (n + PRIOR_N)
            rel[a].append((b, r, n, adj))
            rel[b].append((a, r, n, adj))
    orgs = {}
    alias = {}
    ids = sorted({p[0] for ps in pos.values() for p in ps})
    idx = {iid: i for i, iid in enumerate(ids)}
    for k, ps in pos.items():
        st = collections.Counter(p[1] for p in ps)
        topics = collections.Counter(t for p in ps for t in (items.get(p[0]) or {}).get("topics") or [])
        o = {"n": _display(variants[k]), "c": len(ps), "st": dict(st),
             "p": [[idx[p[0]], STANCE_CODE[p[1]], p[2], p[3]] for p in sorted(ps, key=lambda p: p[2], reverse=True)]}
        if topics:
            o["t"] = dict(topics.most_common(6))
        rs = rel.get(k, [])
        al = [[b, r, n] for b, r, n, adj in sorted(rs, key=lambda x: -x[3]) if adj >= 0.7][:6]
        op = [[b, r, n] for b, r, n, adj in sorted(rs, key=lambda x: x[3]) if adj <= 0.45][:6]
        if al:
            o["al"] = al
        if op:
            o["op"] = op
        orgs[k] = o
        for v in variants[k]:
            alias[v] = k
    return {"ids": ids, "orgs": orgs, "alias": alias, "bins": bins}


def main(out_dir: Path, items: list[dict]) -> int:
    from common import load_json, save_json
    statements = {}
    for f in sorted((out_dir / "lausunnot").glob("*.json")):
        d = load_json(f, {}) or {}
        statements[d.get("id") or f.stem] = d
    res = build(statements, {i["id"]: i for i in items})
    save_json(out_dir / "sidosryhmat.json", res, compact=True)
    return len(res["orgs"])
