"""Annetut lausunnot sivulle: yksi tiedosto per säädös (docs/data/lausunnot/<id>.json), joka ladataan vasta
kun rivi avataan, ja rivin omiin tietoihin pieni yhteenveto (kantojen lukumäärät) merkkejä varten.

Lähteenä fetch_lausunnot-välimuisti (tiivistelmä ja kanta per asiakirja), johon yhdistetään
* Hankeikkunan lausuntokierroksen lausunnot (`lausunnot.docs`: järjestö, päivä, PDF) ja
* eduskunnan valiokuntien asiantuntijalausunnot – HE:t, U/E-kirjelmät (myös EU-ehdotuksen `kirjelmat`), lakialoitteet,
  kansalaisaloitteet ja muut asiat, joiden tunnus on rivin viite: eduskunta.fi:n asiasivuilta kaikki valiokunnat ja
  jaostot (fetch_asiat, data/cache/asiat/) yhdistettynä VaskiData-syötteeseen (fetch_vaski), sekä
* valiokuntien omat lausunnot ja mietinnöt (PeVL, YmVL … / …M): päätösosa tiivistelmänä, muutetut pykälät ja
  vastalauseet (VaskiData-jäsennys fetch_vaski.parse_report, puuttuvat haettu fetch_asiatissa).

Tiedoston rakenne:
{"id", "kierros": {"n", "kannat": {kanta: n}, "rivit": [{"org", "date", "stance", "gist", "url", "none"}]},
 "eduskunta": {"n", "kannat", "rivit": [{"org", "person", "committee", "date", "stance", "gist", "url", "kind"}]},
 "valiokunnat": [{"tunnus", "kind", "committee", "committeeName", "date", "decision", "gist" (ponsi), "view" (valiokunnan
                  oma kanta asiakirjasta), "yhtyy" (yhtyy valtioneuvoston kantaan), "changedSections", "dissent", "url"}],
 "tiivistetty": <luettujen määrä>, "odottaa": <vielä lukematta>}
Rivit järjestetään kannan mukaan (vastustavat ensin, sitten varaukselliset, muutosehdotukset, kannattavat,
muut kannanotot, virkamiesesittelyt, "ei lausuttavaa" viimeisenä) ja kunkin ryhmän sisällä uusin ensin.
"""
from __future__ import annotations

import re

from common import OUT_DIR, log, save_json
from fetch_lausunnot import load_docs

COMMITTEE_NAMES = {
    "PeV": "perustuslakivaliokunta", "UaV": "ulkoasiainvaliokunta", "VaV": "valtiovarainvaliokunta", "TrV": "tarkastusvaliokunta",
    "HaV": "hallintovaliokunta", "LaV": "lakivaliokunta", "LiV": "liikenne- ja viestintävaliokunta", "MmV": "maa- ja metsätalousvaliokunta",
    "PuV": "puolustusvaliokunta", "SiV": "sivistysvaliokunta", "StV": "sosiaali- ja terveysvaliokunta", "TaV": "talousvaliokunta",
    "TiV": "tiedusteluvalvontavaliokunta", "TuV": "tulevaisuusvaliokunta", "TyV": "työelämä- ja tasa-arvovaliokunta",
    "YmV": "ympäristövaliokunta", "SuV": "suuri valiokunta"}
DOC_URL = "https://www.eduskunta.fi/valtiopaivaasiakirjat/{}"

LAUSUNNOT_DIR = OUT_DIR / "lausunnot"
ORDER = {"vastustaa": 0, "osin": 1, "varauksin": 2, "muutoksia": 3, "kannattaa": 4, "kanta": 5, None: 6, "esittely": 7, "ei": 8}
PER_FILE = 1000


def _norm(ref: str) -> str:
    return re.sub(r"\s+vp$", "", (ref or "").strip())


def parliament_keys(it: dict) -> set[str]:
    """Vaski asia ids this item answers to: its HE numbers, its own reference (E/U/LA/KAA … letters and
    motions) and the U/E-kirjelmät linked to an EU proposal."""
    keys = {f"HE {h}" for h in it.get("heNumerot") or []}
    ref = _norm(it.get("ref") or "")
    if re.match(r"^(HE|U|E|UTP|VNS|VNT|K|O|LA|KAA|TPA|TAA|LTA|M) \d+/\d{4}$", ref):
        keys.add(ref)
    keys.update(_norm(k) for k in it.get("kirjelmat") or [])
    return keys


def _row(doc: dict, summ: dict | None, extra: dict) -> dict:
    row = {"org": doc.get("org"), "date": doc.get("date"), "url": doc.get("url"), **extra}
    if doc.get("none"):
        row["stance"] = "ei"
    if not doc.get("url"):
        row["noFile"] = True   # metadata only (the ministry did not publish the file): nothing to summarise
        row["read"] = True
    if summ:
        if summ.get("ok") is True:
            row["stance"] = summ.get("stance") or row.get("stance")
            if summ.get("gist"):
                row["gist"] = summ["gist"]
            if summ.get("vaat") and summ.get("src") in ("ek", "hk"):
                from fetch_lausunnot import DEMAND_CUE, DESCRIPTIVE
                vaat = [v for v in summ["vaat"] if DEMAND_CUE.search(v.get("t") or "") and not DESCRIPTIVE.search(v.get("t") or "")]
                if vaat:
                    row["vaat"] = vaat[:6]  # section-specific demands: compared with the committee's changes
        elif summ.get("ok") == "noText":
            row["stance"] = summ.get("stance") or row.get("stance")
            row["noText"] = True
        elif summ.get("ok") in ("error", "notPdf"):
            row["fetchError"] = True   # the link does not lead to a readable file (retried on later runs)
        row["read"] = True
    return {k: v for k, v in row.items() if v not in (None, "", False)}


def _section(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    rows.sort(key=lambda r: (ORDER.get(r.get("stance"), 6), "".join(chr(0x10FFFF - ord(c)) for c in (r.get("date") or ""))))
    kannat: dict[str, int] = {}
    for r in rows:
        if r.get("stance"):
            kannat[r["stance"]] = kannat.get(r["stance"], 0) + 1
    return {"n": len(rows), "kannat": kannat, "luettu": sum(1 for r in rows if r.get("read")), "rivit": rows[:PER_FILE]}


GENERIC_PONSI = re.compile(r"^(että )?\w+valiokunta ottaa (edellä (olevan|esitetyn|todetun)|lausunnossa esitetyn) huomioon\.?$|"
                           r"^(että )?(se|valiokunta) yhtyy (asiassa )?valtioneuvoston kantaan\.?$|^ottaa edellä olevan huomioon", re.I)


def committee_row(d: dict, rep: dict | None, summ: dict | None = None) -> dict:
    """A committee opinion/report: its decision part (ponsi) and the sentence stating the committee's own view
    (read from the document by fetch_lausunnot). A boilerplate ponsi ("ottaa edellä olevan huomioon") is dropped."""
    rep = rep or {}
    abbr = d.get("committee") or rep.get("committee")
    ponsi = re.sub(r"\s+", " ", rep.get("decisionText") or "").strip()
    if ponsi and len(ponsi) > 420:
        ponsi = ponsi[:420].rsplit(" ", 1)[0].rstrip(",;:") + " …"
    view = (summ or {}).get("gist") if (summ or {}).get("ok") is True else None
    if view and re.search(r"\b(esitämme|ehdotamme)\b", view, re.I):
        view = None  # read before COMMITTEE_VERSION 2: the members' dissent, not the committee's view
    gist = ponsi if ponsi and not GENERIC_PONSI.search(ponsi) else None
    if gist and gist.startswith("että "):  # the ponsi is stored without its subject: "että se yhtyy …"
        name = COMMITTEE_NAMES.get(abbr or "") or rep.get("committeeName") or "Valiokunta"
        gist = f"{name[:1].upper()}{name[1:]} esittää, {gist}"
    row = {"tunnus": d["tunnus"], "kind": d.get("kind") or rep.get("kind"), "committee": abbr,
           "committeeName": COMMITTEE_NAMES.get(abbr or "") or rep.get("committeeName"), "date": d.get("date") or rep.get("date"),
           "decision": rep.get("decision") if rep.get("decision") not in (None, "muu") else None, "gist": gist or None,
           "view": view if view and view != gist else None, "yhtyy": True if ponsi and re.search(r"yhtyy .*valtioneuvoston kantaan", ponsi) else None,
           "changedSections": (rep.get("changedSections") or [])[:12] or None, "dissent": rep.get("dissent") or None,
           "dissentParties": rep.get("dissentParties") or None, "url": DOC_URL.format(d["tunnus"].replace(" vp", "").replace(" ", "+"))}
    return {k: v for k, v in row.items() if v not in (None, "", [], 0)}


# ---- valmisteluasiakirjat (Hankeikkuna): the few documents that mark a step get their own timeline entry, the routine
# rest (pöytäkirjat, kutsut, toimikausipäätökset …) is folded into one "Valmisteluasiakirjat (N)" entry ----
SWEDISH = re.compile(r"\b(Begäran om utlåtande|Begäran|Översättning|betänkande|Möteskallelse|Styrgruppen|Promemoria|Regeringens proposition|"
                     r"utkast|Sammandrag|Sammanfattning|remiss|Arbetsgrupp\w*|Lag om|Förordning)\b|\bpå svenska\b|_sv\b|\(sv\)|\bSV\b(?!_)|"
                     r"ruotsinkieli|ruotsiksi|ruotsinnos|käännös", re.I)
DISSENT = re.compile(r"eriävä|eriäv\w+ mielipi|erimielisyy", re.I)
DRAFT = re.compile(r"\bHE[-_ ]?luonno|esitysluonno|luonnos\w*[^.]{0,50}(?:hallituksen esity|\bHE\b|laiksi|lai(?:n|en) muuttami|asetukse|asetus)|"
                   r"(?:hallituksen esity\w*|asetu\w*)[^.]{0,30}luonno|\bluonnos(?:\s+\d|$)", re.I)
REPORT = re.compile(r"mietint|selvity|raportti|arviointi|loppuraportti|julkaisu \d|työryhmän ehdotu|esiselvity", re.I)
IMPACT = re.compile(r"vaikutusarvi|vaikutusten arvi|yritysvaikutu|vaikutusarvio", re.I)
SETUP = re.compile(r"asettamispäätö|asettaminen|säädöshankepäätö|hankepäätö", re.I)
ROUTINE_GROUP = {"POYTAKIRJA": "Pöytäkirjat ja muistiot", "MUISTIO": "Pöytäkirjat ja muistiot", "KUTSU": "Kokouskutsut",
                 "PAATOS": "Päätökset ja kirjeet", "KIRJE": "Päätökset ja kirjeet", "LIITE": "Esitykset, liitteet ja julkaisut",
                 "ESITYS": "Esitykset, liitteet ja julkaisut", "JULKAISU": "Esitykset, liitteet ja julkaisut",
                 "LAUSUNTOPYYNTO": "Lausuntopyynnöt ja kyselyt"}
KEY_LIMIT = {"asettaminen": 2, "luonnos": 3, "mietinto": 3, "yhteenveto": 2, "eriava": 6, "vaikutus": 2, "lausuntopyynto": 3}
KEY_LABEL = {"asettaminen": "Hanke asetettu", "luonnos": "Luonnos hallituksen esitykseksi", "mietinto": "Työryhmän mietintö tai selvitys",
             "yhteenveto": "Lausuntoyhteenveto", "eriava": "Eriävä mielipide", "vaikutus": "Vaikutusarvio", "lausuntopyynto": "Lausuntopyyntö"}


def prep_category(d: dict) -> str | None:
    t, n = d.get("t") or "", d.get("n") or ""
    if DISSENT.search(n):
        return "eriava"
    if t == "ASETTAMISPAATOS" or (t in ("SUUNNITELMA", "PAATOS") and SETUP.search(n)):
        return "asettaminen"
    if t == "YHTEENVETO" and re.search(r"lausun|palaute|kuulemi", n, re.I):
        return "yhteenveto"
    if DRAFT.search(n) and t not in ("KUTSU", "POYTAKIRJA"):
        return "luonnos"
    if IMPACT.search(n):
        return "vaikutus"
    if t in ("MIETINTO", "RAPORTTI") and not re.search(r"ei lausuttavaa|arviointineuvoston lausunto", n, re.I):
        return "mietinto"
    if t == "JULKAISU" and REPORT.search(n):
        return "mietinto"
    if t == "LAUSUNTOPYYNTO":
        return "lausuntopyynto"
    return None


def prep_section(docs: list[dict]) -> dict | None:
    """{"keskeiset": [{"date", "cat", "label", "docs": [{"n", "u"}]}], "muut": {"n", "first", "last", "groups": [{"label",
    "rivit": [{"d", "n", "u"}]}]}} from a project's documents (fetch_hankeikkuna `valmistelu`). Swedish versions of the
    same document are left out; key documents of one kind on one day are one entry."""
    seen, key, routine = set(), {}, {}
    for d in docs or []:
        n = re.sub(r"\s+", " ", (d.get("n") or "").replace("_", " ")).strip()
        n = re.sub(r"\.(pdf|docx?|xlsx?|pptx?)$", "", n, flags=re.I)
        if not d.get("u") or not n or SWEDISH.search(d.get("n") or ""):
            continue
        sig = (d.get("t"), n.lower(), d.get("d"))
        if sig in seen:
            continue
        seen.add(sig)
        cat = prep_category(d)
        row = {"n": n, "u": d["u"]}
        if cat and d.get("d"):
            key.setdefault((cat, d["d"]), []).append(row)
        else:
            routine.setdefault(ROUTINE_GROUP.get(d.get("t") or "", "Muut asiakirjat"), []).append({"d": d.get("d"), **row})
    # a draft sent out for comments the same day is one step: "Luonnos hallituksen esitykseksi lausunnolle"
    to_comment = set()
    for (cat, date) in [k for k in key if k[0] == "lausuntopyynto"]:
        if ("luonnos", date) in key:
            key[("luonnos", date)] += key.pop((cat, date))
            to_comment.add(date)
    entries = []
    by_cat: dict[str, list] = {}
    for (cat, date), rows in key.items():
        label = KEY_LABEL[cat] + (" lausunnolle" if cat == "luonnos" and date in to_comment else "")
        by_cat.setdefault(cat, []).append({"date": date, "cat": cat, "label": label, "docs": rows[:6]})
    for cat, lst in by_cat.items():
        lst.sort(key=lambda e: e["date"])
        lim = KEY_LIMIT.get(cat)
        if lim and len(lst) > lim:  # older ones of a frequent kind go with the routine documents
            for e in lst[:-lim] if cat != "asettaminen" else lst[lim:]:
                for r in e["docs"]:
                    routine.setdefault("Muut asiakirjat" if cat != "lausuntopyynto" else ROUTINE_GROUP["LAUSUNTOPYYNTO"], []).append({"d": e["date"], **r})
            lst = lst[-lim:] if cat != "asettaminen" else lst[:lim]
        entries += lst
    out: dict = {}
    if entries:
        out["keskeiset"] = sorted(entries, key=lambda e: e["date"])
    rows_all = [r for rows in routine.values() for r in rows]
    if rows_all:
        ds = sorted(r["d"] for r in rows_all if r.get("d"))
        order = list(ROUTINE_GROUP.values()) + ["Muut asiakirjat"]
        groups = [{"label": g, "rivit": sorted(rows, key=lambda r: r.get("d") or "", reverse=True)}
                  for g, rows in sorted(routine.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)]
        out["muut"] = {"n": len(rows_all), "first": ds[0] if ds else None, "last": ds[-1] if ds else None, "groups": groups}
    return out or None


def _extra_caches() -> tuple[dict, dict, dict, dict]:
    """HE texts (summary, enactment order), plenary records, directives' national measures, OEIL documents."""
    from common import CACHE_DIR, load_json
    return ((load_json(CACHE_DIR / "arviointineuvosto.json", {}) or {}).get("he") or {},
            (load_json(CACHE_DIR / "taysistunto.json", {}) or {}).get("he") or {},
            (load_json(CACHE_DIR / "nim.json", {}) or {}).get("celex") or {},
            (load_json(CACHE_DIR / "oeil.json", {}) or {}).get("proc") or {})


def build_lausunnot(items: list[dict], hk_by_uuid: dict, vaski: dict, asiat: dict | None = None) -> dict[str, dict]:
    """Writes docs/data/lausunnot/<id>.json for every item that has statements or committee documents; returns
    {item_id: summary} where summary = {"n", "luettu", "kannat", "valiokunnat"} for the item's own record."""
    cache = load_docs()
    if asiat is None:
        from fetch_asiat import load_cache
        asiat = load_cache()
    statements: dict[str, list] = {}
    for k, lst in (vaski.get("statements") or {}).items():
        statements.setdefault(_norm(k), []).extend(lst)
    for k, a in (asiat.get("asiat") or {}).items():
        statements.setdefault(_norm(k), []).extend(a.get("statements") or [])
    reports = {**(vaski.get("reports") or {}), **(asiat.get("reports") or {})}
    committee_docs: dict[str, list] = {}
    for k, a in (asiat.get("asiat") or {}).items():
        committee_docs[_norm(k)] = a.get("committeeDocs") or []
    for t, r in (vaski.get("reports") or {}).items():  # reports VaskiData saw for a matter the asia pages have not listed yet
        if r.get("asia") and not any(d["tunnus"] == t for d in committee_docs.get(_norm(r["asia"]), [])):
            committee_docs.setdefault(_norm(r["asia"]), []).append({"tunnus": t, "kind": r.get("kind"), "date": r.get("date"), "committee": r.get("committee")})
    he_text, plenary, nim, oeil = _extra_caches()
    LAUSUNNOT_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict] = {}
    keep: set[str] = set()
    for it in items:
        doc: dict = {"id": it["id"]}
        p = hk_by_uuid.get(it.get("hankeUuid") or "")
        if p and (p.get("lausunnot") or {}).get("docs"):
            rows = [_row(d, cache.get(d["id"]), {}) for d in p["lausunnot"]["docs"]]
            sec = _section(rows)
            if sec:
                sec["url"] = (p["lausunnot"] or {}).get("url")
                doc["kierros"] = sec
        rows, seen = [], set()
        for key in sorted(parliament_keys(it)):
            for s in statements.get(key) or []:
                sid = s.get("edk") or s.get("url")
                if sid in seen:
                    continue
                seen.add(sid)
                rows.append(_row({"org": s.get("org") or s.get("person"), "date": s.get("date"), "url": s.get("url")}, cache.get(sid),
                                 {"committee": s.get("committee"), "kind": s.get("kind"),
                                  "asia": key if key != _norm(it.get("ref") or "") and not key.startswith("HE ") else None}))
        sec = _section(rows)
        if sec:
            doc["eduskunta"] = sec
        vk, seen_vk = [], set()
        for key in sorted(parliament_keys(it)):
            for d in committee_docs.get(key) or []:
                if d["tunnus"] in seen_vk:
                    continue
                seen_vk.add(d["tunnus"])
                vk.append(committee_row(d, reports.get(d["tunnus"]), cache.get(d["tunnus"])))
        if vk:
            # opinions first (they come before the lead committee's report), then by date
            doc["valiokunnat"] = sorted(vk, key=lambda r: (r.get("kind") == "mietintö", r.get("date") or "", r["tunnus"]))
        if p and p.get("valmistelu"):
            prep = prep_section(p["valmistelu"])
            if prep:
                doc["valmistelu"] = prep
        hes = [k[3:] for k in sorted(parliament_keys(it)) if k.startswith("HE ")]
        for h in hes[:1]:  # the item's own HE (a project with several HEs is rare; the first is the main one)
            t = he_text.get(h) or {}
            if t.get("sisalto") or t.get("sj"):
                doc["he"] = {k: v for k, v in {"tunnus": f"HE {h} vp", "sisalto": t.get("sisalto"), "sj": t.get("sj")}.items() if v}
            pl = plenary.get(h) or {}
            if pl.get("kasittelyt") or pl.get("aanestykset") or pl.get("lausumat"):
                doc["taysistunto"] = {k: pl.get(k) for k in ("ev", "lausumat", "kasittelyt", "aanestykset") if pl.get(k)}
        n_rec = nim.get(it.get("celex") or "") if it.get("scope") == "eu" else None
        if n_rec and (n_rec.get("measures") or n_rec.get("deadline")):
            doc["nim"] = {k: v for k, v in {"deadline": n_rec.get("deadline"), "measures": n_rec.get("measures")[:60]}.items() if v}
        o_rec = oeil.get(it.get("procedure") or "") if it.get("scope") == "eu" else None
        if o_rec and (o_rec.get("docs") or o_rec.get("np")):
            doc["eu_asiakirjat"] = {k: v for k, v in {"docs": o_rec.get("docs"), "np": o_rec.get("np"),
                                                      "url": f"https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference={it['procedure']}"}.items() if v}
        if not any(k in doc for k in ("kierros", "eduskunta", "valiokunnat", "valmistelu", "he", "taysistunto", "nim", "eu_asiakirjat")):
            continue
        n = sum(doc[k]["n"] for k in ("kierros", "eduskunta") if k in doc)
        read = sum(doc[k]["luettu"] for k in ("kierros", "eduskunta") if k in doc)
        kannat: dict[str, int] = {}
        for k in ("kierros", "eduskunta"):
            for st, c in (doc.get(k) or {}).get("kannat", {}).items():
                kannat[st] = kannat.get(st, 0) + c
        doc["tiivistetty"], doc["odottaa"] = read, n - read
        save_json(LAUSUNNOT_DIR / f"{it['id']}.json", doc, compact=True)
        keep.add(f"{it['id']}.json")
        out[it["id"]] = {"n": n, "luettu": read, "kannat": kannat, "valiokunnat": len(doc.get("valiokunnat") or [])}
        extra = [k for k in ("valmistelu", "he", "taysistunto", "nim", "eu_asiakirjat") if k in doc]
        if extra:
            out[it["id"]]["x"] = extra  # the drawer loads the file for these too
    for f in LAUSUNNOT_DIR.glob("*.json"):
        if f.name not in keep:
            f.unlink()
    total = sum(f.stat().st_size for f in LAUSUNNOT_DIR.glob("*.json"))
    read_all = sum(v["luettu"] for v in out.values())
    n_all = sum(v["n"] for v in out.values())
    n_vk = sum(v["valiokunnat"] for v in out.values())
    log(f"lausunnot: {len(out)} säädöstä, {n_all} lausuntoa, {read_all} tiivistetty, {n_vk} valiokunnan lausuntoa/mietintöä "
        f"({total / 1e6:.1f} MB) -> {LAUSUNNOT_DIR}")
    return out
