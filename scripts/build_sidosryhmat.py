"""Sidosryhmien kannat organisaatioittain: kuka on lausunut mistäkin ja mitä mieltä, kenen kanssa samaa mieltä.

Lähde: sivun annetut lausunnot (docs/data/lausunnot/<id>.json – Hankeikkunan lausuntokierrokset ja eduskunnalle
annetut asiantuntijalausunnot, kanta luokiteltu fetch_lausunnot.py:ssä). Puhdas funktio – ei verkkoa.

  * Yksityishenkilöt, toiminimet ja yksittäiset asiantuntijat (henkilönimet, common.looks_like_person) eivät saa profiilia.
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

  * Lopputulos ja record: jokaiselle hankkeelle päätellään, mitä esitykselle tapahtui (säädetty / kesken, ja
    muuttiko eduskunnan valiokunta sitä mietinnössään). Lausunnonantajan kanta hankkeessa (viimeisin ei-neutraali)
    verrataan siihen: kannatti → säädettiin; varauksin tai muutosehdotuksin → valiokunta muutti esitystä;
    vastusti → hyväksyttiin muutettuna (puoliksi kannan mukainen) tai sellaisenaan. Osuutta verrataan kaikkien
    lausunnonantajien keskiarvoon samalla kannalla, koska valiokunta muuttaa suurinta osaa esityksistä joka
    tapauksessa. Luonnoksen muutoksia ministeriössä lausuntokierroksen jälkeen aineisto ei näe, eikä sitä, liittyikö
    valiokunnan muutos juuri tämän lausunnonantajan ehdotukseen – record kuvaa yhteyttä, ei vaikutusta.
  * Tyyppi (kunta, viranomainen, järjestö, yritys, tutkimus) ja tunnusmerkit (aktiivisuus, areena, kantatyyli,
    record) päätellään säännöillä nimestä ja luvuista – ei tekoälyä.

Tulos: docs/data/sidosryhmat.json, ladataan sivulla vasta kun profiili tai haku avataan. Tiivis muoto: "ids" listaa
kohteet, ja kannanotto on [kohteen indeksi, kanta-koodi (STANCE_CODE), päivä, k=kierros/e=eduskunta].
"""
from __future__ import annotations

import collections
import re
from pathlib import Path

from common import HIDDEN_GIVERS, is_sole_trader, looks_like_person

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


ENACTED = {"voimassa", "vahvistettu", "hyväksytty"}
_TYPES = (("kunta", r"\b(?:kunta|kaupunki|hyvinvointialue|kuntayhtymä|maakunnan liitto|liitto - förbund|seutukunta|kommun|stad|välfärdsområde)\b|hyvinvointialue"),
          ("viranomainen", r"ministeriö|virasto|laitos\b|valtuutet|kansleri|oikeusasiamies|opetushallitus|ympäristökeskus|"
                           r"luonnonvarakeskus|käräjä|oikeusrekisteri|huoltovarmuus|eläketurvakeskus|fimea|keha-keskus|"
                           r"turvallisuuskeskus|patentti- ja rekisteri|pääesikunta|vakuutusoikeus|markkinaoikeus|kansallisarkisto|"
                           r"\bkeva\b|riistakeskus|ihmisoikeuskeskus|metsäkeskus|tapaturmavakuutuskeskus|hätäkeskus|arviointikeskus|"
                           r"onnettomuustutkinta|valtori|elinvoimakeskus|presidentin kanslia|landskapsregering|maakunnan hallitus|"
                           r"hus-yhtymä|tuomioistuin|\boikeus\b|hovioikeus|hallinto-oikeus|"
                           r"poliisi|tulli|rajavartio|puolustusvoimat|verohallinto|kela\b|kansaneläkelaitos|ely-keskus|aluehallintovirasto|"
                           r"lautakunta|valtiokonttori|syyttäjä|ulosotto|traficom|fiva|finanssivalvonta|tilastokeskus|metsähallitus|"
                           r"pelastus|keskusrikospoliisi|\bthl\b|terveyden ja hyvinvoinnin laitos|eduskunnan|valtioneuvoston|"
                           r"kilpailu- ja kuluttajavirasto|suomen pankki|myndighet|ämbetsverk|departement"),
          ("tutkimus", r"yliopisto|korkeakoulu|ammattikorkeakoulu|instituutti|tutkimus|akatemia|akademi|universit|högskola|research"),
          ("yritys", r"\b(?:oy|oyj|ab|abp|ltd|plc|inc|gmbh|ky|osakeyhtiö|keskinäinen|vakuutusyhtiö)\b|pankki\b|bank\b"),
          ("järjestö", r"\b(?:ry|rf|r\.y\.)\b|liitto|yhdistys|järjestö|säätiö|seura\b|seurakunta|kirkko|keskusjärjestö|förbund|förening|"
                       r"stiftelse|kamari|federation|association|foundation|union|neuvottelukunta|osuuskunta|asianajajat|wwf|"
                       r"amnesty|punainen risti|folkting|paneeli|verkosto|rikosuhripäivystys|liikenneturva|valtuuskunta|klusteri|"
                       r"saamelaiskäräjät"))
TYPE_RX = [(t, re.compile(rx, re.I)) for t, rx in _TYPES]


_TYPE_FIX = re.compile(r"diakonissalaitos|diakonia|invalidiliitto|näkövammaisten|kuurojen", re.I)  # säätiöt ja järjestöt, joiden nimi muistuttaa virastoa


def org_type(name: str) -> str:
    if _TYPE_FIX.search(name or ""):
        return "järjestö"
    for t, rx in TYPE_RX:
        if rx.search(name or ""):
            return t
    return "muu"


def outcomes(statements: dict[str, dict], items: dict[str, dict]) -> dict[str, str]:
    """Item id -> outcome code: a = säädetty, valiokunta muutti; b = säädetty muuttamattomana; c = säädetty
    (valiokunnan ratkaisu ei tiedossa); d = kesken, valiokunta muutti; e = kesken, muuttamattomana; "" = kesken."""
    out = {}
    for iid, d in statements.items():
        decs = [v.get("decision") for v in d.get("valiokunnat") or [] if v.get("kind") == "mietintö" and v.get("decision")]
        changed = "muutettuna" in decs or any(v.get("changedSections") for v in d.get("valiokunnat") or [] if v.get("kind") == "mietintö")
        com = "m" if changed else ("u" if decs else "")
        enacted = (items.get(iid) or {}).get("status") in ENACTED
        out[iid] = {("m", True): "a", ("u", True): "b", ("", True): "c", ("m", False): "d", ("u", False): "e"}.get((com, enacted), "")
    return out


def _score(g: str, oc: str):
    """How far the outcome went the giver's way (1, ½ or 0), or None when the outcome is not known yet."""
    if g == "S":
        return 1.0 if oc in ("a", "b", "c") else None
    committee = "m" if oc in ("a", "d") else ("u" if oc in ("b", "e") else "")
    if not committee:
        return None
    if g == "R":
        return 1.0 if committee == "m" else 0.0
    return 0.5 if committee == "m" else 0.0  # O: adopted with changes = half its way; as such = not its way


def _norm_sec(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


def committee_changes(d: dict) -> set[str] | None:
    """Sections the committee changed in its report (normalised "4a§"), an empty set when it adopted the bill
    unamended, or None when the report or its changes are not known."""
    reps = [v for v in d.get("valiokunnat") or [] if v.get("kind") == "mietintö"]
    if not reps:
        return None
    secs = {_norm_sec(s) for v in reps for s in v.get("changedSections") or [] if "§" in str(s)}
    if secs:
        return secs
    if all(v.get("decision") == "muuttamattomana" for v in reps):
        return set()
    return None


def build(statements: dict[str, dict], items: dict[str, dict], palaute: dict[str, dict] | None = None) -> dict:
    """statements: item id -> docs/data/lausunnot/<id>.json payload; items: id -> item (title, topics);
    palaute: item id -> {giver name as in the rows: h|e|m} from build_palaute (the HE's Lausuntopalaute chapter)."""
    palaute = palaute or {}
    gists: dict[str, list] = collections.defaultdict(list)
    dem: dict[str, list] = collections.defaultdict(list)  # org -> [(date, item, section, changed?, sentence)]
    committee = {iid: committee_changes(d) for iid, d in statements.items()}
    variants: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    pos: dict[str, list] = collections.defaultdict(list)
    bins = [[lo, hi, 0, 0] for lo, hi in BINS]
    for iid, d in statements.items():
        for sec, code in (("kierros", "k"), ("eduskunta", "e")):
            for r in (d.get(sec) or {}).get("rivit") or []:
                org = (r.get("org") or "").strip()
                st = r.get("stance") or ""
                if not org or org in HIDDEN_GIVERS or is_sole_trader(org) or looks_like_person(org) or len(org) < 2 or st not in GROUP:
                    continue
                k = key_of(org)
                if not k or len(k) < 2:
                    continue
                variants[k][org] += 1
                pv = (palaute.get(iid) or {}).get(org, "") if code == "k" else ""
                pos[k].append([iid, st, r.get("date") or "", code] + ([pv] if pv else []))
                ch = committee.get(iid)
                if code == "e" and ch is not None and r.get("vaat"):
                    for v in r["vaat"]:
                        for sec in v.get("s") or []:
                            dem[k].append((r.get("date") or "", iid, sec, _norm_sec(sec) in ch, v.get("t") or ""))
                g = (r.get("gist") or "").strip()
                if g and GROUP[st] != "N" and len(g) > 40:
                    gists[k].append((r.get("date") or "", iid, g))
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
                if k in gists:
                    gists[o].extend(gists.pop(k))
                if k in dem:
                    dem[o].extend(dem.pop(k))
    # one position per organisation and item for agreement: the latest non-neutral one
    latest: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for k, ps in pos.items():
        for iid, st, date, *_ in sorted(ps, key=lambda p: p[2]):
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
    # outcome per item and each organisation's record against it (latest non-neutral stance per item)
    oc = outcomes(statements, items)
    base: dict[str, list] = {g: [0.0, 0] for g in "SRO"}
    per_org: dict[str, list] = {}
    for k, m in latest.items():
        rows = []
        for iid, g in m.items():
            sc = _score(g, oc.get(iid, ""))
            if sc is not None:
                rows.append((g, sc, oc[iid]))
                base[g][0] += sc
                base[g][1] += 1
        per_org[k] = rows
    base_rate = {g: (v[0] / v[1] if v[1] else 0.0) for g, v in base.items()}
    # stance shares across all positions, for the "more critical than average" tags
    allg = collections.Counter(GROUP[p[1]] for ps in pos.values() for p in ps)
    alln = sum(allg.values()) or 1
    avg = {g: allg[g] / alln for g in "SRON"}
    orgs = {}
    alias = {}
    ids = sorted({p[0] for ps in pos.values() for p in ps})
    idx = {iid: i for i, iid in enumerate(ids)}
    for k, ps in pos.items():
        st = collections.Counter(p[1] for p in ps)
        topics = collections.Counter(t for p in ps for t in (items.get(p[0]) or {}).get("topics") or [])
        o = {"n": _display(variants[k]), "c": len(ps), "st": dict(st),
             "p": [[idx[p[0]], STANCE_CODE[p[1]], p[2], p[3]] + p[4:] for p in sorted(ps, key=lambda p: p[2], reverse=True)]}
        if topics:
            o["t"] = dict(topics.most_common(6))
        rs = rel.get(k, [])
        al = [[b, r, n] for b, r, n, adj in sorted(rs, key=lambda x: -x[3]) if adj >= 0.7][:6]
        op = [[b, r, n] for b, r, n, adj in sorted(rs, key=lambda x: x[3]) if adj <= 0.45][:6]
        if al:
            o["al"] = al
        if op:
            o["op"] = op
        o["ty"] = org_type(o["n"])
        # ministry stage: what the HE's Lausuntopalaute chapter says of this giver's proposals, one verdict per item
        pv: dict[str, str] = {}
        for p in ps:
            if len(p) > 4 and p[4]:
                pv[p[0]] = "h" if "h" in (pv.get(p[0]), p[4]) else ("e" if "e" in (pv.get(p[0]), p[4]) else "m")
        if pv:
            o["pal"] = [sum(1 for v in pv.values() if v == x) for x in "hem"]
        # Parliament stage: each section it asked to be changed vs. the sections the committee changed
        dd = {}
        for d, iid, sec, changed, t in sorted(dem.get(k, []), reverse=True):
            dd.setdefault((iid, _norm_sec(sec)), (d, iid, sec, changed, t))
        if dd:
            rows = sorted(dd.values(), reverse=True)
            o["vq"] = [sum(1 for r in rows if r[3]), sum(1 for r in rows if not r[3])]
            o["vl"] = [[idx[r[1]], r[2], 1 if r[3] else 0, r[4][:200]] for r in rows[:8]]
        # agenda: its own key sentences, latest first, and the words that set its statements apart
        gl = sorted(gists.get(k, []), reverse=True)
        if len(ps) >= 3 and gl:
            seen_items: set = set()
            ag = []
            for d, iid, g in gl:
                if iid in seen_items:
                    continue
                seen_items.add(iid)
                ag.append([idx[iid], g[:180] + ("…" if len(g) > 180 else "")])
                if len(ag) >= 3:
                    break
            o["ag"] = ag
        rows = per_org.get(k, [])
        if rows:
            # rec: [n, score %, expected % for the same stance mix, per stance [n, met, half]]
            got = sum(r[1] for r in rows)
            exp = sum(base_rate[r[0]] for r in rows)
            by = {g: [sum(1 for r in rows if r[0] == g), sum(1 for r in rows if r[0] == g and r[1] == 1.0),
                      sum(1 for r in rows if r[0] == g and r[1] == 0.5)] for g in "SRO"}
            o["rec"] = [len(rows), round(100 * got / len(rows)), round(100 * exp / len(rows)), by]
        o["tg"] = tags(o, len(ps), avg)
        orgs[k] = o
        for v in variants[k]:
            alias[v] = k
    # agenda words: stems frequent in this giver's key sentences and rare elsewhere (simple tf-idf, no AI)
    themes = agenda_words({k: [g for _, _, g in v] for k, v in gists.items() if len(v) >= 4},
                          {k: orgs[k]["n"] for k in gists if k in orgs})
    for k, ws in themes.items():
        if k in orgs and ws:
            orgs[k]["aw"] = ws
    pal_all = [sum(o.get("pal", [0, 0, 0])[i] for o in orgs.values()) for i in range(3)]
    out_codes = "".join(oc.get(i, "") or "-" for i in ids)  # one character per item id
    return {"ids": ids, "orgs": orgs, "alias": alias, "bins": bins, "oc": out_codes,
            "base": {g: round(100 * base_rate[g]) for g in "SRO"}, "avg": {g: round(100 * avg[g]) for g in "SRON"},
            "palBase": round(100 * pal_all[0] / max(1, pal_all[0] + pal_all[1]))}


def tags(o: dict, n: int, avg: dict) -> list[str]:
    """Rule-based characterisation (codes; the page shows fixed, translatable labels)."""
    st = collections.Counter()
    for s, c in (o.get("st") or {}).items():
        st[GROUP.get(s, "N")] += c
    tot = sum(st.values()) or 1
    sh = {g: st[g] / tot for g in "SRON"}
    e = sum(1 for p in o["p"] if p[3] == "e") / max(1, len(o["p"]))
    t = []
    t.append("akt3" if n >= 200 else ("akt2" if n >= 50 else ("akt1" if n >= 10 else "akt0")))
    if e >= 0.4:
        t.append("edus")
    elif e <= 0.1 and n >= 10:
        t.append("kier")
    if n >= 10:
        if sh["O"] >= max(0.12, 1.5 * avg["O"]):
            t.append("krit")
        if sh["S"] >= max(0.25, 1.5 * avg["S"]):
            t.append("myot")
        if sh["R"] >= avg["R"] + 0.15:
            t.append("muut")
        if sh["N"] >= 0.4:
            t.append("neut")
    pal = o.get("pal")
    if pal and pal[0] + pal[1] >= 4:
        share = pal[0] / (pal[0] + pal[1])
        if share >= 0.75:
            t.append("pal+")
        elif share <= 0.35:
            t.append("pal-")
    vq = o.get("vq")
    if vq and sum(vq) >= 4:
        if vq[0] / sum(vq) >= 0.5:
            t.append("vq+")
        elif vq[0] / sum(vq) <= 0.15:
            t.append("vq-")
    rec = o.get("rec")
    if rec and rec[0] >= 10:
        if rec[1] >= rec[2] + 10:
            t.append("rec+")
        elif rec[1] <= rec[2] - 10:
            t.append("rec-")
    elif n >= 10:
        t.append("rec?")
    return t


_STOP = set("""
että joka jotka jonka joiden mikä mitä tämä tämän nämä näiden sekä myös tai sen ovat oli olisi ole ollut voi voisi
tulee tulisi pitää pidämme katsomme esitämme ehdotamme esitys esityksen esityksessä esitykseen ehdotus ehdotuksen
lakiehdotus lakiehdotuksen luonnos luonnoksessa luonnoksen hallituksen lain lakiin laissa pykälä pykälän momentti
osalta kannalta lisäksi kuitenkin erityisesti kanssa mukaan jälkeen ennen siten sitä niin kuin kun jos vaan mutta
lausunto lausunnossa lausuntonaan kannattaa kannatamme vastustaa nähden yhteydessä myös vielä hyvin olla ei eikä
toteaa totesi katsotaan katsoo yleisesti erityisen esitetty esitetään todetaan nähdään pidetään asiassa asian
""".split())


_GENERIC_STEMS = {"jatkova", "valiokun", "ministe", "säätämi", "perusteluj", "valmist", "hallitu", "lakiesi", "esityks", "ehdotet",
                  "sääntel", "säännök", "toteutt", "edellyt", "tarkoit", "huomioi", "vaikutu", "kokonai", "tärkeää", "tärkeän"}


def agenda_words(texts: dict[str, list[str]], names: dict[str, str] | None = None, top: int = 6) -> dict[str, list[str]]:
    """The giver's distinctive words: 7-letter stems ranked by share in its own sentences × rarity across givers;
    each shown in its most common written form."""
    import math
    df: collections.Counter = collections.Counter()
    tf: dict[str, collections.Counter] = {}
    form: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for k, ts in texts.items():
        c: collections.Counter = collections.Counter()
        for t in ts:
            for w in re.findall(r"[a-zåäö][a-zåäö-]{5,}", t.lower()):
                if w in _STOP:
                    continue
                st = w[:7]
                c[st] += 1
                form[st][w] += 1
        tf[k] = c
        df.update(set(c))
    n = len(texts) or 1
    out = {}
    for k, c in tf.items():
        tot = sum(c.values()) or 1
        own = {w[:5] for w in re.findall(r"[a-zåäö]{4,}", ((names or {}).get(k) or k).lower())}  # its own name is no theme
        scored = sorted(((cnt / tot) * math.log(n / (1 + df[st])), st) for st, cnt in c.items()
                        if cnt >= 2 and df[st] < n * 0.2 and st[:5] not in own and not st.endswith("-")
                        and not form[st].most_common(1)[0][0].endswith("-") and st not in _GENERIC_STEMS)
        out[k] = [form[st].most_common(1)[0][0] for _, st in reversed(scored[-top:])]
    return out


def main(out_dir: Path, items: list[dict], palaute: dict[str, dict] | None = None) -> int:
    from common import load_json, save_json
    statements = {}
    for f in sorted((out_dir / "lausunnot").glob("*.json")):
        d = load_json(f, {}) or {}
        statements[d.get("id") or f.stem] = d
    res = build(statements, {i["id"]: i for i in items}, palaute)
    save_json(out_dir / "sidosryhmat.json", res, compact=True)
    return len(res["orgs"])
