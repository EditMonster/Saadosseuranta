"""Prior-notification notices of concentrations in the Official Journal (C series), read from the
Publications Office's Cellar in Finnish.

The notice ("Ennakkoilmoitus yrityskeskittymästä") is the one public document that names the
undertakings with their countries, describes the transaction and each party's business, and opens
the window for third-party observations (normally 10 days from publication). It is published in all
EU languages a few days after notification, so new cases get their notice on a later run.

Cellar: https://publications.europa.eu/resource/oj/C_202601921 with Accept: application/xhtml+xml
and Accept-Language: fi returns the Finnish XHTML directly (EUR-Lex itself sits behind a bot wall).
"""
from __future__ import annotations

import datetime as dt
import html
import re

from common import http

UA = {"User-Agent": "Mozilla/5.0 saadosseuranta/1.0 (+https://github.com/EditMonster/Saadosseuranta)",
      "Accept": "application/xhtml+xml, text/html;q=0.9", "Accept-Language": "fi"}
TITLE = re.compile(r"Ennakkoilmoitus yrityskeskittymästä", re.I)
DMY = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
PAREN = re.compile(r"\(([^()]*)\)")
CONTROLLER = re.compile(r"yrityks(?:en|ten)\s+(.+?)\s*\(([^()]*)\)", re.I)


def oj_id(reference: str) -> str | None:
    """'C:2026:1921:' -> 'C_202601921' (the Cellar / ELI document id)."""
    m = re.match(r"\s*([A-Z])\s*:\s*(\d{4})\s*:\s*(\d+)", reference or "")
    return f"{m.group(1)}_{m.group(2)}{int(m.group(3)):05d}" if m else None


def eli_url(reference: str) -> str | None:
    m = re.match(r"\s*([A-Z])\s*:\s*(\d{4})\s*:\s*(\d+)", reference or "")
    return f"https://eur-lex.europa.eu/eli/{m.group(1)}/{m.group(2)}/{int(m.group(3))}/oj/fin" if m else None


def text_of(xhtml: str) -> str:
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", xhtml, flags=re.S)
    t = re.sub(r"<(p|/p|br|div|/div|tr|/tr|li|/li|h\d|/h\d|table|/table)[^>]*>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def iso(dmy: str) -> str | None:
    m = DMY.search(dmy or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def _country_group(line: str) -> tuple[str | None, str | None, str]:
    """Find the '(Short, Country)' group of a party line; returns (short, country, text after it)."""
    for m in PAREN.finditer(line):
        parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
        if not parts:
            continue
        last = parts[-1]
        if len(parts) == 1 and (last.isupper() and len(last) <= 6 or last[:1].islower() or any(ch.isdigit() for ch in last)):
            continue  # an abbreviation such as (CF) or a note, not a country
        if not last[:1].isupper() or len(last.split()) > 5:
            continue
        return (parts[0] if len(parts) > 1 else None), last, line[m.end():]
    return None, None, ""


def parse_party(line: str) -> dict:
    line = re.sub(r"[”“\"’‘']", "", line).strip().rstrip(".,;").strip()
    short, country, rest = _country_group(line)
    name = line
    if country:
        name = line[: line.rfind("(" + (short + ", " if short else "") + country)].strip().rstrip(",") or line
    controllers = []
    for m in CONTROLLER.finditer(rest):
        parts = [p.strip() for p in m.group(2).split(",") if p.strip()]
        if parts:
            controllers.append({"name": m.group(1).strip().rstrip(","), "country": parts[-1]})
    if not country:
        m = re.search(r"([A-ZÄÖÅ][\wäöå-]+n)\s+kansalainen", line)  # a natural person: "Robert X, Puolan kansalainen"
        if m:
            country = m.group(0)
            name = line[: m.start()].strip().rstrip(",")
    fi = country in ("Suomi", "Suomen kansalainen") or any(c["country"] == "Suomi" for c in controllers)
    out = {"name": re.sub(r"\s+", " ", name)[:120], "country": country, "fi": fi}
    if short and short != name:
        out["short"] = short
    if controllers:
        out["controllers"] = controllers
    return out


def _items(block: str) -> tuple[list[str], list[str]]:
    """Split a '—'-bulleted block into the bullet items and the paragraphs after them."""
    lines = [l.strip() for l in block.split("\n") if l.strip()]
    items, rest, expect = [], [], False
    for l in lines:
        if l in ("—", "–", "-"):
            expect = True
            continue
        if expect and not rest:
            items.append(l)
            expect = False
        else:
            rest.append(l)
    return items, rest


def parse_notice(text: str) -> dict | None:
    if not TITLE.search(text[:1500]):
        return None
    d: dict = {"simplified": "yksinkertaistettuun menettelyyn" in text[:1500].lower()}
    head = text[:800]
    m = re.search(r"\n(\d{1,2}\.\d{1,2}\.\d{4})\n", head)
    d["published"] = iso(m.group(1)) if m else None
    m = re.search(r"\n\(?(C/\d{4}/\d+)\)?\n", head)
    d["reference"] = m.group(1) if m else None
    m = re.search(r"vastaanotti\s+(\d{1,2}\.\s*\w+\s+\d{4})", text)
    # parties + transaction: from the list heading to the next numbered section
    m = re.search(r"Ilmoitus koskee seuraavi[a-z]* yrityksi[äa]:?\s*\n(.*?)\n\s*\d{1,2}\.\s*\n", text, re.S)
    parties, transaction = [], ""
    if m:
        items, rest = _items(m.group(1))
        parties = [parse_party(i) for i in items]
        transaction = " ".join(rest)
    d["parties"] = parties
    d["transaction"] = re.sub(r"\s+", " ", transaction).strip()
    # business activities
    m = re.search(r"liiketoiminnan sisältö on seuraava:?\s*\n(.*?)\n\s*\d{1,2}\.\s*\n", text, re.S)
    acts, extra = _items(m.group(1)) if m else ([], [])
    d["activities"] = [re.sub(r"\s+", " ", a).strip() for a in acts]
    # a joint-venture paragraph sits between the activities and "Komissio katsoo alustavan tarkastelun"
    m = re.search(r"\n\s*\d{1,2}\.\s*\n((?:(?!\n\s*\d{1,2}\.\s*\n).)*?)\n\s*\d{1,2}\.\s*\n\s*Komissio katsoo alustavan", text, re.S)
    jv = re.sub(r"\s+", " ", m.group(1)).strip() if m and "liiketoiminnan sisältö" not in m.group(1) else ""
    if jv:
        d["jv"] = jv
    m = re.search(r"(\d+)\s+päivän kuluessa tämän ilmoituksen julkaisupäivästä", text)
    d["observationDays"] = int(m.group(1)) if m else 10
    if d["published"]:
        d["observationsEnd"] = (dt.date.fromisoformat(d["published"]) + dt.timedelta(days=d["observationDays"])).isoformat()
    d["fi"] = any(p["fi"] for p in parties)
    return d


def fetch_notice(reference: str) -> dict | None:
    """Fetch and parse the Finnish notice for an OJ reference such as 'C:2026:1921:'."""
    oid = oj_id(reference)
    if not oid:
        return None
    r = http("GET", f"https://publications.europa.eu/resource/oj/{oid}", headers=UA, timeout=60)
    if r.status_code != 200:
        return None
    n = parse_notice(text_of(r.text))
    if n:
        n["url"] = eli_url(reference)
    return n
