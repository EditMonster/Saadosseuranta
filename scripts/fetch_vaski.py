"""Eduskunta committee feed (avoindata.eduskunta.fi, table VaskiData): what the committees
are doing with a bill between the lähetekeskustelu and the plenary readings.

The parliamentary stage data per HE (fetch_eduskunta.py) says *that* a bill is in a committee;
this source says *what happens there* – the part of the process where outside influence is
exercised and where the text actually changes:

* Esityslista (committee agenda, "<Vk>E n/yyyy vp") – published 2–4 days before the meeting.
  Each item carries the stage code (ATKUUL = asiantuntijakuuleminen, ESITML = mietintöluonnos,
  …) and the persons/organisations invited ("Asiantuntijat:" / "Kirjalliset lausunnot:").
  This is the only forward-looking signal of a hearing. Minutes (Pöytäkirja, "<Vk>P") have the
  same item structure and are used when no agenda was seen for that meeting.
* Asiantuntijalausunto – the written expert statements, PDF-only rows (tunnus = EDK id). The
  bill is in Vireilletulo/EduskuntaTunnus; the author exists only in the title string
  ("HE 100/2025 vp HaV 21.11.2025 lainsäädäntöneuvos Saara Rahko, valtiovarainministeriö
  Asiantuntijalausunto"), which is parsed into organisation and person.
* Valiokunnan mietintö / lausunto ("<Vk>M", "<Vk>L") – the committee's decision proposal.
  PaatosOsa says whether the bills are approved muuttamattomana / muutettuna / hylättäväksi;
  the committee's amendments are the Saados blocks whose sections contain MuutosTeksti or
  PoistoTeksti markup (unchanged laws are not reprinted). JasenMielipideOsa = vastalauseet
  (dissenting opinions) with the parties in their heading; JOHDANTO lists the experts heard.
* Kirjallinen kysymys, lakialoite, toimenpidealoite, kansalaisaloite – MPs' and citizens'
  own initiatives (early signals of political pressure on a topic). Parsed from the document
  when it is structured XML, otherwise from the käsittelytiedot row (KAA is PDF-only).

Mechanics: rows are read with the incremental Id scan (`batch?pkName=Id&pkStartValue=…`,
max 100 rows and up to several MB per page) starting after the last Id seen; on the first run
the newest `bootstrap_rows` rows are read (the max Id is found by probing). Only Finnish rows
are kept (tunnus ends with " vp", or kieliKoodi="fi" for EDK rows). Agendas are re-sent in
place (same Id) when updated, so upcoming agendas are re-read by tunnus on every run. Committee
reports of the current year are backfilled once by enumerating "<Vk>M n/yyyy vp" per committee
(and "<Vk>L"), because the Id scan only covers the last weeks.

Cache: data/cache/vaski.json – compact, no XML and no full texts. A row whose XML does not
parse is skipped with a warning; the run raises only when the API itself is unreachable, so
update.py keeps the previous cache.
"""
from __future__ import annotations

import datetime as dt
import re
import time
import xml.etree.ElementTree as ET

from common import CACHE_DIR, CONFIG_DIR, TODAY, get_json, load_json, load_yaml, log, save_json

API = "https://avoindata.eduskunta.fi/api/v1/tables/VaskiData"
OUT = CACHE_DIR / "vaski.json"
PDF = "https://www.eduskunta.fi/pdf/"
ASIA_URL = "https://www.eduskunta.fi/valtiopaivaasiat/"

COMMITTEES = {
    "PeV": "perustuslakivaliokunta", "UaV": "ulkoasiainvaliokunta", "VaV": "valtiovarainvaliokunta",
    "TrV": "tarkastusvaliokunta", "HaV": "hallintovaliokunta", "LaV": "lakivaliokunta",
    "LiV": "liikenne- ja viestintävaliokunta", "MmV": "maa- ja metsätalousvaliokunta",
    "PuV": "puolustusvaliokunta", "SiV": "sivistysvaliokunta", "StV": "sosiaali- ja terveysvaliokunta",
    "TaV": "talousvaliokunta", "TiV": "tiedusteluvalvontavaliokunta", "TuV": "tulevaisuusvaliokunta",
    "TyV": "työelämä- ja tasa-arvovaliokunta", "YmV": "ympäristövaliokunta", "SuV": "suuri valiokunta",
    # valtiovarainvaliokunnan jaostot (they publish agendas and minutes, not reports); the tunnus prefixes
    # seen in VaskiData 2026 are VeJ, HtJ, SitJ, MaJ, LiJ, KhJ, TeJ, AyJ – older/alternative spellings kept as aliases
    "VeJ": "valtiovarainvaliokunnan verojaosto",
    "HtJ": "valtiovarainvaliokunnan hallinto- ja turvallisuusjaosto", "HaJ": "valtiovarainvaliokunnan hallinto- ja turvallisuusjaosto",
    "SitJ": "valtiovarainvaliokunnan sivistys- ja tiedejaosto", "SiJ": "valtiovarainvaliokunnan sivistys- ja tiedejaosto",
    "MaJ": "valtiovarainvaliokunnan maatalousjaosto", "LiJ": "valtiovarainvaliokunnan liikennejaosto",
    "KhJ": "valtiovarainvaliokunnan kunta- ja terveysjaosto", "KuJ": "valtiovarainvaliokunnan kunta- ja terveysjaosto",
    "TeJ": "valtiovarainvaliokunnan työ- ja elinkeinojaosto", "TyJ": "valtiovarainvaliokunnan työ- ja elinkeinojaosto",
    "AyJ": "valtiovarainvaliokunnan asunto- ja ympäristöjaosto", "AsJ": "valtiovarainvaliokunnan asunto- ja ympäristöjaosto",
    "TuJ": "valtiovarainvaliokunnan jaosto",
}
REPORTING = [c for c in COMMITTEES if c.endswith("V")]  # the 17 committees that issue mietinnöt/lausunnot
NAME_TO_ABBR = {v: k for k, v in COMMITTEES.items()}
STAGES = {  # kasittelyvaiheKoodi of a committee agenda item -> Finnish label (variants with an A/JT suffix map to the base code)
    "ATKUUL": "asiantuntijakuuleminen", "ATKUULJT": "asiantuntijakuuleminen jatkuu", "ATKUJT": "asiantuntijakuuleminen jatkuu",
    "ATKUULA": "asiantuntijakuulemisen lopettaminen ja valmistava keskustelu", "VALMK": "valmistava keskustelu",
    "KASVKP": "ennakkokäsittely", "ENNHYV": "asiantuntijasuunnitelman hyväksyminen", "YLKES": "yleiskeskustelu",
    "ESITML": "mietintöluonnoksen esittely", "ESITLL": "lausuntoluonnoksen esittely",
    "ESITMLJTA": "jaoston mietintöluonnoksen esittely", "KASJTP": "jaoston käsittely",
    "YKSKAS": "yksityiskohtainen käsittely", "RATKAS": "ratkaiseva käsittely", "JATKKAS": "jatkettu käsittely",
    "ILMVK": "asia saapunut valiokuntaan", "ILMYEU": "EU-asia saapunut", "ILMEEU": "EU-asia saapunut",
    "SAAEEU": "EU-jatkokirjelmä saapunut", "SAAEUL": "lausunto saapunut", "SAAPL": "lausunto saapunut",
    "SAAYEU": "erikoisvaliokunnan kannanotto saapunut", "SAAPAKA": "kannanotto", "KASYEU": "EU-asian käsittely",
    "VKPA": "käsittely päättyy", "YHDVK": "asioiden yhdistäminen",
}


def stage_name(code: str) -> str | None:
    for c in (code, code[:-1] if code.endswith("A") else "", code[:-2] if code.endswith("JT") else "",
              code[:-3] if code.endswith("JTA") else ""):
        if c and c in STAGES:
            return STAGES[c]
    return None
TUNNUS = re.compile(r"^([A-Z][a-zA-Z]{1,2}[VJ])([EPML]) (\d+)/(\d{4}) vp$")
ASIA = re.compile(r"^[A-Z]{1,4} \d+/\d{4} vp$")
STATEMENT_TITLE = re.compile(r"^(?P<asia>[A-Z]{1,4} \d+/\d{4} vp) (?P<vk>\w+) (?P<pvm>\d{2}\.\d{2}\.\d{4}) (?P<who>.+?)"
                             r"(?: [Aa]siantuntijalausunto\b.*| / .*)?$")  # suffix may be missing, 'PowerPoint', '/ täydentävä …'
MOTION_TYPES = {"Kirjallinen kysymys": "KK", "Lakialoite": "LA", "Toimenpidealoite": "TPA", "Kansalaisaloite": "KAA"}
HEADER = re.compile(r"<[\w.-]*:?JulkaisuMetatieto\b([^>]*)>")


# ----------------------------------------------------------------------------- XML helpers
def strip_ns(xml: str) -> ET.Element:
    """The documents use ~30 namespace prefixes; local names are unique enough, so drop them."""
    xml = re.sub(r'\sxmlns(:\w+)?="[^"]*"', "", xml)
    xml = re.sub(r"<(/?)[\w.-]+:", r"<\1", xml)
    xml = re.sub(r"\s[\w.-]+:(\w+=)", r" \1", xml)
    return ET.fromstring(xml)


def text_of(el: ET.Element | None, limit: int | None = None) -> str:
    if el is None:
        return ""
    t = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
    return t[:limit] if limit else t


def header(xml: str) -> tuple[str, str]:
    """(AsiakirjatyyppiNimi, kieliKoodi) from the JulkaisuMetatieto start tag, without parsing the body."""
    m = HEADER.search(xml[:12000])
    if not m:
        return "", ""
    attrs = m.group(1)
    typ = re.search(r'asiakirjatyyppiNimi="([^"]*)"', attrs)
    lang = re.search(r'kieliKoodi="([^"]*)"', attrs)
    return (typ.group(1) if typ else ""), (lang.group(1) if lang else "")


def split_tunnus(tunnus: str | None) -> tuple[str, str, int, int] | None:
    """'HaVM 15/2026 vp' -> ('HaV', 'M', 15, 2026)."""
    m = TUNNUS.match(tunnus or "")
    return (m.group(1), m.group(2), int(m.group(3)), int(m.group(4))) if m else None


def committee_of(tunnus: str | None, name_hint: str | None = None) -> tuple[str | None, str | None]:
    parts = split_tunnus(tunnus)
    if parts and parts[0] in COMMITTEES:
        return parts[0], COMMITTEES[parts[0]]
    hint = (name_hint or "").strip().lower()
    if hint in NAME_TO_ABBR:
        return NAME_TO_ABBR[hint], hint
    if parts:
        return parts[0], hint or None
    return None, hint or None


def person_name(h: ET.Element | None) -> str | None:
    if h is None:
        return None
    n = f"{h.findtext('EtuNimi') or ''} {h.findtext('SukuNimi') or ''}".strip()
    return n or None


def pdf_url(tunnus: str) -> str:
    return PDF + tunnus.replace(" vp", "").replace(" ", "+")


# ----------------------------------------------------------------------------- parsers
def parse_agenda(root: ET.Element, created: str | None = None) -> dict | None:
    """Esityslista or Pöytäkirja -> {tunnus, committee, committeeName, start, created, items}."""
    el = root.find(".//Esityslista")
    if el is None:
        el = root.find(".//KokousPoytakirja")
    if el is None:
        return None
    tunnus = el.get("eduskuntaTunnus")
    abbr, name = committee_of(tunnus, root.findtext(".//JulkaisuMetatieto//Toimija[@rooliKoodi='Laatija']/YhteisoTeksti")
                              or el.findtext("./IdentifiointiOsa/Toimija[@rooliKoodi='Laatija']/YhteisoTeksti"))
    if abbr not in COMMITTEES:  # puhemiesneuvosto (PmNP), suuren valiokunnan työjaosto (SuVtJE) etc. are not committees
        return None
    items = []
    for k in el.findall("./Asiakohta"):
        asia = (k.get("eduskuntaTunnus") or k.findtext("KohtaAsia/EduskuntaTunnus") or "").strip()
        if not ASIA.match(asia):
            continue
        experts, written = [], []
        for block in k.findall("AsiantuntijatToimenpide"):
            mode = "experts"
            for c in block:
                if c.tag == "KappaleKooste":
                    low = (c.text or "").lower()
                    mode = "written" if "kirjallis" in low else "skip" if "ei lausu" in low or "ilmoitus" in low else "experts"
                elif c.tag == "Asiantuntija":
                    org = (c.findtext("YhteisoTeksti") or "").strip() or None
                    person = person_name(c.find("Henkilo"))
                    if mode == "written":
                        written.append(org or person)
                    elif mode == "experts":
                        experts.append({"name": person, "org": org} if person else {"org": org})
        stage = k.get("kasittelyvaiheKoodi") or ""
        items.append({"asia": asia, "stage": stage, "stageName": stage_name(stage),
                      "title": text_of(k.find("KohtaNimeke/NimekeTeksti"), 300) or None,
                      "experts": experts, "written": [w for w in written if w]})
    return {"tunnus": tunnus, "committee": abbr, "committeeName": name, "start": el.get("kokousAloitusHetki"),
            "created": created, "items": items}


def split_author(who: str) -> tuple[str | None, str | None]:
    """'lainsäädäntöneuvos Saara Rahko, valtiovarainministeriö' -> ('Saara Rahko', 'valtiovarainministeriö').

    Eduskunta writes the author as '[titteli Etunimi Sukunimi, ]Organisaatio[, yksikkö]'. The
    person is the first comma-separated segment that ends in 2–4 name-like tokens (capitalised
    with lowercase letters: 'Saara', 'Keto-Huovinen', but not the degree 'OTK') preceded by at
    least one title token ('lainsäädäntöneuvos', 'OTK', 'Kouluterveyskyselyn kehittämispäällikkö');
    the organisation is what follows it (or an earlier segment that names one, as in
    'Pohjanmaan käräjäoikeus, laamanni X Y'). A lone 'professori Kaarlo Tuori' has no
    organisation; a segment with no title ('Suomen Kuntaliitto') is an organisation."""
    segments = [s.strip() for s in who.split(", ") if s.strip()]
    for i, seg in enumerate(segments):
        tokens = seg.split()
        tail = 0
        while tail < len(tokens) and (_namelike(tokens[-1 - tail]) or (
                tail and tokens[-1 - tail] in _NAME_PARTICLES and tail + 1 < len(tokens) and _namelike(tokens[-2 - tail]))):
            tail += 1
        if 2 <= tail <= 5 and any(_titlelike(t) for t in tokens[:-tail]):
            after = segments[i + 1:]
            before = [s for s in segments[:i] if any(_namelike(t) for t in s.split())]
            return " ".join(tokens[-tail:]), (", ".join(after or before) or None)
    return None, (", ".join(segments) or None)


_CONNECTORS = {"ja", "och", "för", "vid", "i", "av", "de", "von", "af", "van", "der", "-", "&"}
_NAME_PARTICLES = {"von", "af", "de", "van", "der", "da", "di", "du", "la", "le"}  # 'Anna von Fieandt-Lehtonen'


def _namelike(token: str) -> bool:
    return token[:1].isupper() and any(ch.islower() for ch in token[1:])


def _titlelike(token: str) -> bool:
    """'lainsäädäntöneuvos', 'kehittämispäällikkö', 'OTK' – but not 'Stiftelsen' or the Swedish 'för'."""
    if token.lower() in _CONNECTORS or token in ("(", ")"):
        return False
    return token[:1].islower() or not any(ch.islower() for ch in token)


def parse_statement(root: ET.Element) -> dict | None:
    """Asiantuntijalausunto metadata -> {asia, edk, date, committee, org, person, title, url}."""
    meta = root.find(".//JulkaisuMetatieto")
    if meta is None:
        return None
    asia = (root.findtext(".//Vireilletulo/EduskuntaTunnus") or "").strip()
    title = text_of(root.find(".//JulkaisuMetatieto//Nimeke/NimekeTeksti"), 300)
    m = STATEMENT_TITLE.match(title)
    person, org = split_author(m.group("who") if m else title)
    kokous = root.find(".//KokousViite")
    abbr = None
    if kokous is not None and kokous.get("kokousTunnus"):
        abbr = kokous.get("kokousTunnus").split(" ")[0]
    if not abbr and m:
        abbr = m.group("vk")
    if abbr not in COMMITTEES:
        abbr = committee_of(None, root.findtext(".//JulkaisuMetatieto//Toimija[@rooliKoodi='Laatija']/YhteisoTeksti"))[0] or abbr
    edk = meta.get("muuTunnus")
    if not asia or not edk:
        return None
    return {"asia": asia, "edk": edk, "date": meta.get("laadintaPvm"), "committee": abbr, "org": org,
            "person": person, "title": title, "url": PDF + edk}


def classify_decision(text: str) -> str:
    """PaatosOsa sentences -> muutettuna | muuttamattomana | hylättäväksi | muu. A report that amends
    any bill counts as 'muutettuna'; rejection only when the government's bills themselves are
    rejected (rejecting an attached lakialoite/toimenpidealoite is routine and does not count)."""
    low = text.lower()
    if "muutettuna" in low or "muutettui" in low or re.search(r"(?:hyväksyy uuden|valiokunnan uusi lakiehdotus)", low):
        return "muutettuna"  # a new bill drafted by the committee is also a change to the proposal
    if "muuttamattomana" in low or "muuttamattomina" in low:
        return "muuttamattomana"
    if re.search(r"hylkää\w*[\s\d.,—–]*(?:ja\s+)?[\d.,—–\s]*(?:hallituksen esityk|lakiehdotu|esityk)", low) or "hylättäväksi" in low:
        return "hylättäväksi"
    return "muu"


def parse_report(root: ET.Element) -> dict | None:
    """Valiokunnan mietintö / lausunto -> report row (decision, amended sections, dissents, experts)."""
    doc = root.find(".//Mietinto")
    kind = "mietintö"
    if doc is None:
        doc = root.find(".//Lausunto")
        kind = "lausunto"
    if doc is None:
        return None
    tunnus = doc.get("eduskuntaTunnus")
    if not split_tunnus(tunnus):
        return None
    meta = root.find(".//JulkaisuMetatieto")
    abbr, name = committee_of(tunnus, doc.findtext("./IdentifiointiOsa/Toimija[@rooliKoodi='Laatija']/YhteisoTeksti"))
    sign = doc.find("./OsallistujaOsa/PaivaysKooste")
    date = (sign.get("allekirjoitusPvm") if sign is not None else None) or (meta.get("laadintaPvm") if meta is not None else None) \
        or doc.get("laadintaPvm")
    sentences = [text_of(k) for k in doc.findall("./PaatosOsa//SisennettyKappaleKooste")]
    sentences = [s for s in sentences if s]
    decision_text = " ".join(sentences)
    sections: list[str] = []
    laws: list[str] = []
    for s in doc.findall("./SaadosOsa/Saados"):  # the committee's own text, not the vastalause versions
        changed = []
        for p in s.findall(".//Pykala"):
            if p.find(".//MuutosTeksti") is not None or p.find(".//PoistoTeksti") is not None:
                sec = re.sub(r"\s+", " ", p.get("identifiointiTunnus") or text_of(p.find("PykalaTunnusKooste"))).strip()
                if sec and sec not in changed:
                    changed.append(sec)
        if not changed and (s.find(".//MuutosTeksti") is not None or s.find(".//PoistoTeksti") is not None):
            changed.append("johtolause")  # e.g. a new amending reference added to the enacting clause only
        if changed:
            sections.extend(c for c in changed if c not in sections)
            sn = s.find("SaadosNimeke")
            law = " ".join(text_of(c) for c in sn).strip() if sn is not None else ""
            if law and law not in laws:
                laws.append(law)
    dissents = doc.findall("./JasenMielipideOsa")
    parties: list[str] = []
    for v in dissents:
        head = text_of(v.find("OtsikkoTeksti"))
        if "/" in head:  # "Vastalause 1 /sd, vihr, vas"
            found = head.split("/", 1)[1].split(",")
        else:  # plain "Vastalause 1" / "Eriävä mielipide 1.": the parties are those of its signatories
            found = [text_of(t) for t in v.findall(".//Allekirjoittaja//LisatietoTeksti")]
        for p in found:
            p = re.sub(r"[^a-zåäö]", "", p.lower())  # "/Vas." -> "vas", "sdp." -> "sdp"
            p = {"sdp": "sd", "rkp": "r"}.get(p, p)
            if p and len(p) <= 5 and p not in parties:
                parties.append(p)
    return {"tunnus": tunnus, "asia": (doc.findtext("./IdentifiointiOsa/Vireilletulo/EduskuntaTunnus") or "").strip() or None,
            "committee": abbr, "committeeName": name, "kind": kind, "date": date,
            "decision": classify_decision(decision_text),
            "decisionText": decision_text[:300], "changedSections": sections[:40], "changedLaws": laws[:10],
            "dissent": len(dissents), "dissentParties": parties, "experts": count_experts(doc.find("./AsiaKuvaus")),
            "url": pdf_url(tunnus)}


def count_experts(johdanto: ET.Element | None) -> int:
    """Experts heard or giving a written statement; 'ilmoitus, ei lausuttavaa' entries do not count."""
    n = 0
    for block in (johdanto.findall("./AsiantuntijatToimenpide") if johdanto is not None else []):
        counting = True
        for c in block:
            if c.tag == "KappaleKooste":
                counting = "ei lausu" not in (c.text or "").lower()
            elif c.tag == "Asiantuntija" and counting:
                n += 1
    return n


def motion_url(tunnus: str) -> str:
    return ASIA_URL + tunnus.replace(" vp", "").replace(" ", "+")


def parse_motion(root: ET.Element) -> dict | None:
    """KK / LA / TPA document -> motion row with first signer, signer count and the opening paragraph."""
    doc = None
    for tag in ("Kysymys", "Lakialoite", "EduskuntaAloite"):
        doc = root.find(f".//{tag}")
        if doc is not None:
            break
    if doc is None:
        return None
    tunnus = (doc.get("eduskuntaTunnus") or "").strip()
    typ = tunnus.split(" ")[0]
    if typ not in MOTION_TYPES.values():
        return None
    first = doc.find("./IdentifiointiOsa/Toimija[@rooliKoodi='Laatija']/Henkilo")
    signers = doc.findall("./AllekirjoitusOsa/Allekirjoittaja")
    party = (first.findtext("LisatietoTeksti") if first is not None else None) or None
    para = doc.find("./SisaltoKuvaus/KappaleKooste")
    if para is None:
        para = doc.find("./PerusteluOsa//KappaleKooste")
    sign = doc.find("./AllekirjoitusOsa/PaivaysKooste")
    meta = root.find(".//JulkaisuMetatieto")
    keywords = [text_of(a) for a in (meta.findall("./Aihe/AiheTeksti") if meta is not None else [])]
    return {"tunnus": tunnus, "type": typ, "date": (sign.get("allekirjoitusPvm") if sign is not None else None) or doc.get("laadintaPvm"),
            "title": text_of(doc.find("./IdentifiointiOsa/Nimeke/NimekeTeksti"), 300) or None,
            "firstSigner": person_name(first), "party": party.lower() if party and party != "ym." else None,
            "signers": len(signers) or 1, "text": text_of(para, 400) or None, "keywords": [k for k in keywords if k][:8],
            "url": motion_url(tunnus)}


def parse_motion_stages(root: ET.Element) -> dict | None:
    """Käsittelytiedot of a KK/LA/TPA/KAA (used when the document itself is PDF-only, e.g. kansalaisaloite)."""
    doc = root.find(".//KasittelytiedotValtiopaivaasia")
    if doc is None:
        return None
    tunnus = (doc.get("eduskuntaTunnus") or "").strip()
    typ = tunnus.split(" ")[0]
    if typ not in MOTION_TYPES.values():
        return None
    first = doc.find("./IdentifiointiOsa/Toimija/Henkilo")
    jatto = doc.find(".//ToimenpideJulkaisu[@kasittelyvaiheKoodi='JATTO']")
    others = jatto.findtext("MuuAllekirjoittajaLkm") if jatto is not None else None
    party = (first.findtext("LisatietoTeksti") if first is not None else None) or None
    return {"tunnus": tunnus, "type": typ, "date": (jatto.get("tapahtumaPvm") if jatto is not None else None) or doc.get("laadintaPvm"),
            "title": text_of(doc.find("./IdentifiointiOsa/Nimeke/NimekeTeksti"), 300) or None,
            "firstSigner": person_name(first), "party": party.lower() if party else None,
            "signers": (1 + int(others)) if others and others.isdigit() else (1 if first is not None else None),
            "text": None, "keywords": [text_of(a) for a in doc.findall("./Asiasanat/Aihe/AiheTeksti")][:8],
            "url": motion_url(tunnus)}


# ----------------------------------------------------------------------------- cache assembly
def empty_cache() -> dict:
    return {"fetched": None, "lastId": 0, "agendas": {}, "statements": {}, "reports": {}, "motions": []}


def absorb(cache: dict, xml: str, tunnus_col: str | None, created: str | None, stats: dict) -> None:
    """Classify one VaskiData row by its header and merge what it tells into the cache."""
    tunnus_col = (tunnus_col or "").strip()
    typ, lang = header(xml)
    if tunnus_col.endswith(" rd") or (not tunnus_col.endswith(" vp") and lang and lang != "fi"):
        return
    is_stages = "KasittelytiedotValtiopaivaasia" in xml
    if typ == "Esityslista" or (typ == "Pöytäkirja" and "KokousPoytakirja" in xml):  # not plenary minutes (PTK)
        kind = "agenda"
    elif typ == "Asiantuntijalausunto":
        kind = "statement"
    elif typ in ("Valiokunnan mietintö", "Valiokunnan lausunto"):
        kind = "report"
    elif typ in MOTION_TYPES:
        kind = "motion"
    else:
        return
    try:
        root = strip_ns(xml)
    except ET.ParseError as e:
        stats["bad"] += 1
        log(f"warn: vaski {tunnus_col or '?'} ({typ}): XML ei jäsenny: {e}")
        return
    if kind == "agenda":
        a = parse_agenda(root, created)
        if a and a.get("tunnus") and a.get("start"):
            key = upsert_agenda(cache, a, minutes=typ == "Pöytäkirja")
            if key:
                stats["agendas"] += 1
                stats.setdefault("touched", set()).add(key)
    elif kind == "statement":
        s = parse_statement(root)
        if s:
            lst = cache["statements"].setdefault(s.pop("asia"), [])
            lst[:] = [x for x in lst if x.get("edk") != s["edk"]] + [s]
            stats["statements"] += 1
    elif kind == "report":
        r = parse_report(root)
        if r:
            cache["reports"][r.pop("tunnus")] = r
            stats["reports"] += 1
    elif kind == "motion":
        m = parse_motion_stages(root) if is_stages else parse_motion(root)
        if m:
            upsert_motion(cache, m, from_stages=is_stages)
            stats["motions"] += 1


def upsert_agenda(cache: dict, a: dict, *, minutes: bool) -> str | None:
    """Store by tunnus; minutes only stand in for an agenda that was never published for that meeting."""
    tunnus = a.pop("tunnus")
    if minutes:
        day = (a.get("start") or "")[:10]
        for key, old in cache["agendas"].items():
            if key != tunnus and old.get("committee") == a.get("committee") and (old.get("start") or "")[:10] == day:
                return None
    cache["agendas"][tunnus] = a
    return tunnus


def upsert_motion(cache: dict, m: dict, *, from_stages: bool) -> None:
    """The document row is richer than the käsittelytiedot row: the latter only fills gaps."""
    motions = cache["motions"]
    for i, old in enumerate(motions):
        if old.get("tunnus") == m["tunnus"]:
            if from_stages:
                for k, v in m.items():
                    if v not in (None, [], 0) and old.get(k) in (None, [], 0):
                        old[k] = v
            else:
                motions[i] = {**old, **{k: v for k, v in m.items() if v not in (None, [])}}
            return
    motions.append(m)


def prune(cache: dict, cfg: dict) -> None:
    def cutoff(days: int) -> str:
        return (TODAY - dt.timedelta(days=days)).isoformat()

    c = cutoff(int(cfg.get("agenda_keep_days", 7)))
    cache["agendas"] = {k: v for k, v in cache["agendas"].items() if (v.get("start") or "")[:10] >= c}
    c = cutoff(int(cfg.get("statement_keep_days", 400)))
    cache["statements"] = {k: sorted(v, key=lambda s: (s.get("date") or "", s.get("edk") or ""))
                           for k, v in cache["statements"].items() if any((s.get("date") or "") >= c for s in v)}
    c = cutoff(int(cfg.get("report_keep_days", 400)))
    cache["reports"] = {k: v for k, v in cache["reports"].items() if (v.get("date") or "9999") >= c}
    c = cutoff(int(cfg.get("motion_keep_days", 120)))
    cache["motions"] = sorted((m for m in cache["motions"] if (m.get("date") or "9999") >= c),
                              key=lambda m: (m.get("date") or "", m.get("tunnus") or ""), reverse=True)


# ----------------------------------------------------------------------------- API access
_ROWS_ONLY = False  # set when the batch endpoint refuses us (seen: HTTP 403 from GitHub Actions' network) → page the rows endpoint instead
_PAGE_FIRST: dict[int, int | None] = {}  # rows-endpoint page → first Id on it (None = empty page)


def _rows_page(page: int, per_page: int = 100) -> dict:
    return get_json(f"{API}/rows", params={"perPage": per_page, "page": page}, timeout=180)


def _page_first_id(page: int, per_page: int) -> int | None:
    if page not in _PAGE_FIRST:
        rows = _rows_page(page, per_page).get("rowData") or []
        _PAGE_FIRST[page] = int(rows[0][0]) if rows else None
    return _PAGE_FIRST[page]


def _batch_via_rows(start: int, per_page: int = 100) -> dict:
    """Emulate `batch?pkStartValue=start` with the plain rows listing, which is ordered by Id: binary-search the page
    whose Ids straddle `start`, then return that page's rows from `start` on (topped up from the next page)."""
    lo, hi = 0, 4096
    while _page_first_id(hi, per_page) is not None:  # find an empty page beyond the end
        lo, hi = hi, hi * 2
    while hi - lo > 1:  # invariant: page lo has rows with first Id <= start-or-exists, page hi is beyond
        mid = (lo + hi) // 2
        first = _page_first_id(mid, per_page)
        if first is not None and first <= start:
            lo = mid
        else:
            hi = mid
    data = _rows_page(lo, per_page)
    rows = [r for r in (data.get("rowData") or []) if int(r[0]) >= start]
    more = len(rows) >= per_page  # a full page: the scan loop asks again from the last Id + 1
    if not more:
        nxt = (_rows_page(lo + 1, per_page).get("rowData") or [])
        extra = [r for r in nxt if int(r[0]) >= start]
        rows += extra[: per_page - len(rows)]
        more = len(extra) > per_page - (len(rows) - len(extra[: per_page - len(rows)])) or len(nxt) >= per_page
    return {"rowData": rows, "rowCount": len(rows), "hasMore": more, "pkLastValue": int(rows[-1][0]) if rows else None, "pkStartValue": start}


def fetch_batch(start: int, per_page: int = 100) -> dict:
    global _ROWS_ONLY
    if not _ROWS_ONLY:
        try:
            return get_json(f"{API}/batch", params={"pkName": "Id", "pkStartValue": start, "perPage": per_page}, timeout=180)
        except Exception as e:  # noqa: BLE001
            if "403" not in str(e) and "404" not in str(e):
                raise
            log(f"warn: vaski batch-rajapinta kieltäytyi ({str(e)[:80]}) – käytetään rows-sivutusta")
            _ROWS_ONLY = True
    return _batch_via_rows(start, per_page)


def find_max_id(lower: int) -> int:
    """Largest Id in the table: `batch?pkStartValue=N&perPage=1` is empty exactly when N > max Id,
    so step up from a known lower bound (the row count: Ids are unique and start at 0), then bisect."""
    lo, step = max(lower, 1), 10000
    while fetch_batch(lo + step, 1).get("rowCount"):
        lo, step = lo + step, step * 2
    hi = lo + step
    while hi - lo > 1:  # invariant: a row exists at Id >= lo, none at Id >= hi
        mid = (lo + hi) // 2
        if fetch_batch(mid, 1).get("rowCount"):
            lo = mid
        else:
            hi = mid
    last = fetch_batch(lo, 1)
    return int(last.get("pkLastValue") or lo)


def fetch_by_tunnus(tunnus: str) -> list[list]:
    data = get_json(f"{API}/rows", params={"perPage": 10, "page": 0, "columnName": "Eduskuntatunnus", "columnValue": tunnus},
                    timeout=120)
    return data.get("rowData") or []


def scan(cache: dict, start: int, stats: dict, max_pages: int = 400) -> int:
    """Incremental Id scan from `start`; returns the last Id seen. Parses and discards page by page."""
    last = start - 1
    for _ in range(max_pages):
        data = fetch_batch(start)
        rows = data.get("rowData") or []
        for row in rows:
            stats["rows"] += 1
            try:
                absorb(cache, row[1] or "", row[4], (row[3] or "")[:19].replace(" ", "T") or None, stats)
            except Exception as e:  # noqa: BLE001 – one odd document must not stop the feed
                stats["bad"] += 1
                log(f"warn: vaski rivi {row[0]} ({row[4]}): {e}")
        if rows:
            last = int(data.get("pkLastValue") or rows[-1][0])
        if not data.get("hasMore") or not rows:
            break
        start = last + 1
    return last


def scan_by_tunnus(cache: dict, stats: dict, miss_limit: int = 3, max_probes: int = 400) -> None:
    """Discover new documents without any table listing: committee agendas (<Vk>E n/yyyy vp), minutes (<Vk>P),
    reports/statements (<Vk>M, <Vk>L) and motions (KK, LA, TPA, KAA) are numbered sequentially per year, so probe
    the next numbers after the highest one seen until `miss_limit` consecutive misses. Expert statements (EDK ids)
    cannot be enumerated this way; the hearings themselves still arrive through the HE käsittelytiedot."""
    year = TODAY.year
    seen: dict[str, int] = cache.setdefault("lastNums", {})
    if not seen:  # seed from what the cache already holds
        for key in list(cache.get("agendas") or {}) + list(cache.get("reports") or {}):
            parts = split_tunnus(key)
            if parts and parts[3] == year:
                k = f"{parts[0]}{parts[1]}"
                seen[k] = max(seen.get(k, 0), parts[2])
        for m in cache.get("motions") or []:
            mm = re.match(r"^(KK|LA|TPA|KAA) (\d+)/(\d{4}) vp$", m.get("tunnus") or "")
            if mm and int(mm.group(3)) == year:
                seen[mm.group(1)] = max(seen.get(mm.group(1), 0), int(mm.group(2)))
    series = [f"{c}{s}" for c in COMMITTEES for s in ("E", "M", "L")] + ["KK", "LA", "TPA", "KAA"]  # minutes (P) add nothing the agendas lack
    probes = 0
    for key in series:
        n, misses = seen.get(key, 0) + 1, 0
        while misses < miss_limit and probes < max_probes:
            tunnus = f"{key} {n}/{year} vp"
            probes += 1
            try:
                rows = [r for r in fetch_by_tunnus(tunnus) if (r[4] or "").strip() == tunnus]
            except Exception as e:  # noqa: BLE001
                log(f"warn: vaski {tunnus}: {e}")
                break
            if rows:
                misses = 0
                seen[key] = n
                for row in rows:
                    stats["rows"] += 1
                    try:
                        absorb(cache, row[1] or "", row[4], (row[3] or "")[:19].replace(" ", "T") or None, stats)
                    except Exception as e:  # noqa: BLE001
                        stats["bad"] += 1
                        log(f"warn: vaski rivi {row[0]} ({row[4]}): {e}")
            else:
                misses += 1
            n += 1
            time.sleep(0.1)
    stats["probes"] = probes


def refresh_agendas(cache: dict, stats: dict, limit: int = 40) -> None:
    """Agendas are re-published in place (same Id) when experts are added: re-read the upcoming ones."""
    today = TODAY.isoformat()
    touched = stats.get("touched") or set()
    upcoming = sorted(k for k, v in cache["agendas"].items() if (v.get("start") or "")[:10] >= today and k not in touched
                      and split_tunnus(k) and split_tunnus(k)[1] == "E")
    for tunnus in upcoming[:limit]:
        try:
            for row in fetch_by_tunnus(tunnus):
                if (row[4] or "").strip() == tunnus:
                    absorb(cache, row[1] or "", row[4], (row[3] or "")[:19].replace(" ", "T") or None, stats)
                    stats["refreshed"] += 1
        except Exception as e:  # noqa: BLE001
            log(f"warn: vaski esityslista {tunnus}: {e}")
        time.sleep(0.1)


def backfill_reports(cache: dict, year: int, budget: int, stats: dict) -> bool:
    """Enumerate '<Vk>M n/<year> vp' and '<Vk>L …' per committee until 4 consecutive misses.
    Progress per series is kept in cache['backfillDone'] so a run cut by the request budget resumes."""
    done: list[str] = list(cache.get("backfillDone") or [])
    requests, errors = 0, 0
    for abbr in REPORTING:
        for letter in ("M", "L"):
            series = f"{abbr}{letter}/{year}"
            if series in done:
                continue
            n, misses = 1, 0
            while misses < 4:
                if requests >= budget or errors >= 3:  # out of budget, or the API is failing: resume next run
                    cache["backfillDone"] = done
                    return False
                tunnus = f"{abbr}{letter} {n}/{year} vp"
                requests += 1
                stats["backfill"] += 1
                try:
                    rows = fetch_by_tunnus(tunnus)
                    errors = 0
                except Exception as e:  # noqa: BLE001 – retry the same number (bounded by the error counter above)
                    log(f"warn: vaski {tunnus}: {e}")
                    errors += 1
                    continue
                hit = False
                for row in rows:
                    if (row[4] or "").strip() == tunnus:
                        hit = True
                        if tunnus not in cache["reports"]:
                            absorb(cache, row[1] or "", row[4], None, stats)
                misses = 0 if hit else misses + 1
                n += 1
                time.sleep(0.1)
            done.append(series)
    cache.pop("backfillDone", None)
    return True


def main():
    cfg = (load_yaml(CONFIG_DIR / "settings.yaml") or {}).get("vaski") or {}
    old = load_json(OUT, None)
    cache = empty_cache()
    if isinstance(old, dict) and old.get("lastId"):
        for k in ("agendas", "statements", "reports"):
            cache[k] = dict(old.get(k) or {})
        cache["motions"] = list(old.get("motions") or [])
        cache["lastId"] = int(old["lastId"])
        for k in ("reportsBackfilled", "backfillDone"):
            if old.get(k) is not None:
                cache[k] = old[k]
    stats = {"rows": 0, "bad": 0, "agendas": 0, "statements": 0, "reports": 0, "motions": 0, "refreshed": 0, "backfill": 0}
    t0 = time.time()

    # 1) incremental Id scan (first run: the newest `bootstrap_rows` rows)
    if cache["lastId"]:
        start = cache["lastId"] + 1
    else:
        counts = get_json(f"{API.rsplit('/', 1)[0]}/counts", timeout=60)  # raises RuntimeError when the API is down
        row_count = next((int(c.get("rowCount") or 0) for c in counts if c.get("tableName") == "VaskiData"), 0)
        max_id = find_max_id(max(row_count, 1000))
        start = max(1, max_id - int(cfg.get("bootstrap_rows", 6000)))
        log(f"vaski: ensimmäinen ajo, suurin Id {max_id}, luetaan rivit {start}–")
    try:
        last = scan(cache, start, stats)
        cache["lastId"] = max(cache["lastId"], last)
        log(f"vaski: luettu {stats['rows']} riviä Id {start}–{cache['lastId']} ({time.time() - t0:.0f} s)")
    except Exception as e:  # noqa: BLE001
        # Both listing endpoints refused (seen: HTTP 403 for unfiltered listings from GitHub Actions' network, while
        # filtered `columnName=Eduskuntatunnus` lookups work). Fall back to enumerating the sequential tunnus numbers.
        if "403" not in str(e) and "404" not in str(e):
            raise
        log(f"warn: vaski listaus kieltäytyi ({str(e)[:90]}) – luetaan tunnuksittain")
        scan_by_tunnus(cache, stats)
        log(f"vaski: tunnuksittain luettu {stats['rows']} riviä ({stats.get('probes', 0)} hakua, {time.time() - t0:.0f} s)")

    # 2) upcoming agendas may have changed in place
    refresh_agendas(cache, stats)

    # 3) one-off backfill of this year's committee reports
    year = TODAY.year
    if cache.get("reportsBackfilled") != year:
        if cache.get("backfillDone") is None:
            cache["backfillDone"] = []
        if backfill_reports(cache, year, int(cfg.get("backfill_max_requests", 700)), stats):
            cache["reportsBackfilled"] = year
            log(f"vaski: mietintöjen täydennyshaku {year} valmis ({stats['backfill']} pyyntöä)")
        else:
            log(f"vaski: mietintöjen täydennyshaku {year} kesken ({stats['backfill']} pyyntöä, jatkuu seuraavalla ajolla)")

    prune(cache, cfg)
    cache["fetched"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_json(OUT, cache, compact=True)
    n_st = sum(len(v) for v in cache["statements"].values())
    log(f"vaski: {len(cache['agendas'])} esityslistaa, {n_st} asiantuntijalausuntoa ({len(cache['statements'])} asiaa), "
        f"{len(cache['reports'])} mietintöä/lausuntoa, {len(cache['motions'])} aloitetta/kysymystä; "
        f"uusia tällä ajolla {stats['agendas']}/{stats['statements']}/{stats['reports']}/{stats['motions']}, "
        f"ohitettu {stats['bad']} rikkinäistä, {time.time() - t0:.0f} s -> {OUT}")


if __name__ == "__main__":
    main()
