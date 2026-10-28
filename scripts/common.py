"""Shared helpers: HTTP with retries, JSON cache files, date utilities."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache"
OUT_DIR = ROOT / "docs" / "data"
CONFIG_DIR = ROOT / "config"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

UA = "saadosseuranta/1.0 (+https://github.com/; open-data monitoring bot)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept": "application/json, text/html;q=0.8, */*;q=0.5"})

TODAY = dt.date.today()


def log(*args):
    print(dt.datetime.now().strftime("%H:%M:%S"), *args, flush=True)


class SourceOutage(RuntimeError):
    """The source itself is temporarily unavailable (maintenance page, 5xx, timeouts) – not a parser problem.
    update.py records it as a katko: the page says so, the source is retried sooner and no structural alarm is raised."""


# Maintenance redirects seen in practice: oikeushallinto sends every court site to vara.<domain> and Helsinki
# sends hel.fi / paatokset.hel.fi / its APIs to kopio.hel.fi (static backup copy) during an outage.
MAINTENANCE_HOST = re.compile(r"^(vara|kopio|backup|maintenance|huolto)\.|helfi-backup", re.I)
OUTAGE_STATUS = {408, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 530}


def maintenance_redirect(requested: str, final: str) -> str | None:
    """Host of a maintenance/backup site the request was redirected to, or None."""
    from urllib.parse import urlparse
    a, b = urlparse(requested).hostname or "", urlparse(final).hostname or ""
    if a and b and a != b and MAINTENANCE_HOST.search(b) and not MAINTENANCE_HOST.search(a):
        return b
    return None


def http(method: str, url: str, *, retries: int = 3, timeout: int = 60, **kw) -> requests.Response:
    last = None
    for attempt in range(retries):
        try:
            r = SESSION.request(method, url, timeout=timeout, **kw)
            if r.status_code == 429:
                wait = min(int(r.headers.get("Retry-After", "20") or 20), 120)
                time.sleep(wait + 1)
                raise requests.HTTPError(f"429 for {url}", response=r)
            if r.status_code in OUTAGE_STATUS:
                raise requests.HTTPError(f"{r.status_code} for {url}", response=r)
            host = maintenance_redirect(url, r.url) or next((maintenance_redirect(url, h.headers.get("Location") or "")
                                                             for h in r.history if maintenance_redirect(url, h.headers.get("Location") or "")), None)
            if host:
                raise SourceOutage(f"huoltokatko: {url} ohjautuu varasivulle {host}")
            return r
        except (requests.RequestException, requests.HTTPError) as e:  # noqa: PERF203
            last = e
            if attempt + 1 < retries:
                time.sleep(2 * (attempt + 1) ** 2)
    status = getattr(getattr(last, "response", None), "status_code", None)
    if status == 429:
        raise RuntimeError(f"request failed after {retries} attempts: {url}: {last}")
    raise SourceOutage(f"lähde ei vastaa ({status or type(last).__name__}) {retries} yrityksen jälkeen: {url}: {last}")


def get_json(url: str, **kw):
    r = http("GET", url, **kw)
    r.raise_for_status()
    return r.json()


def post_json(url: str, body, **kw):
    r = http("POST", url, json=body, **kw)
    r.raise_for_status()
    return r.json()


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ---------- tietosuoja: julkaistavan aineiston minimointi ----------
# Lähteet (Hilma, Hankeikkuna, eduskunta) julkaisevat toisinaan henkilökohtaisia yhteystietoja ja nimiä, joita
# sivu ei tarvitse. Ne poistetaan kaikesta, mitä kirjoitetaan docs/data-hakemistoon (julkinen sivu):
# * henkilökohtaiset sähköpostiosoitteet (etunimi.sukunimi@…) vapaatekstistä → "[sähköposti]";
#   yleiset osoitteet (kirjaamo@, toimisto@, hankinnat@ …) säilyvät, koska niihin lähetetään asiakirjoja
# * suomalaiset puhelinnumerot vapaatekstistä → "[puhelin]"
# * valiokuntien kuulemien asiantuntijoiden nimet (sivu näyttää vain organisaatiot ja määrät) – myös välimuistista
import re as _re

_EMAIL = _re.compile(r"(?<![\w.%+-])([A-Za-z0-9._%+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
_ROLE = _re.compile(r"^(kirjaamo|toimisto|info|hankinn\w*|hankinta\w*|registry|registrar|office|asiakaspalvelu|"
                    r"palaute|tietosuoja|neuvonta|vaihde|posti|mail|contact|tarjoukset|tenders?|procurement|purchase\d*|"
                    r"ostot|kirjaamot|edustaja|valiokunta\w*|\w*valiokunta|eduskunta|lausunnot|lausuntopalvelu|kilpailutus\w*|kirjasto|tietopalvelu|tiimi|hva)$", _re.I)
_PHONE = _re.compile(r"(?:(?<=puh\. )|(?<=puh )|(?<=puh: )|(?<=puh\.: )|(?<=puhelin )|(?<=puhelin: )|(?<=tel\. )|(?<=tel: )|(?<=p\. )|(?<=gsm )|(?<=mob\. ))\+?\d[\d\s-]{5,16}\d"
                    r"|(?<![\w/.:-])(?:\+358[\s-]?|0)(?:4\d|50)[\s-]?\d{3}[\s-]?\d{3,4}(?![\w/.:-])"
                    r"|(?<![\w/.:-])\+358[\s-]?\(?0?\)?\d{1,3}[\s-]?\d{3,4}[\s-]?\d{3,4}(?![\w/.:-])", _re.I)


def _is_role(local: str) -> bool:
    """kirjaamo@, kirjaamo.hva@, helsinki.kirjaamo@, kilpailutus.tiimi@ – any segment naming a function, not a person."""
    return bool(_ROLE.match(local)) or any(_ROLE.match(seg) for seg in _re.split(r"[._-]", local) if seg)


def _scrub_text(t: str) -> str:
    if "@" in t:
        def em(m):
            local = m.group(1)
            return m.group(0) if _is_role(local) else "[sähköposti]"
        t = _EMAIL.sub(em, t)
        t = _re.sub(r"https?://\[sähköposti\]", "[sähköposti]", t)
    if any(c.isdigit() for c in t):
        t = _PHONE.sub("[puhelin]", t)
    return t


# * yksityishenkilöiden lausuntojen antajan nimi → "Yksityishenkilö" (Hankeikkuna merkitsee ne otsikolla
#   "Yksityishenkilön lausunto"); lausunnon sisältö säilyy
# * välimuisteissa (data/cache, julkinen repo) myös eduskunnalle annettujen lausuntojen allekirjoittajan nimi
#   peitetään, kun organisaatio on tiedossa – sivu ei käytä nimeä, vain tiedon siitä, että allekirjoittaja on
PRIVATE_LABEL = "Yksityishenkilö"
_PRIVATE_TITLE = _re.compile(r"yksityishenkil|privatperson|private individual", _re.I)
# * toiminimellä toimivan yksityisen elinkeinonharjoittajan nimi on käytännössä henkilön nimi ("Etu Suku Tmi",
#   "Toiminimi X") → "Yksityinen elinkeinonharjoittaja"; kommandiitti- ja avoimet yhtiöt ovat yhtiöitä ja säilyvät
SOLE_LABEL = "Yksityinen elinkeinonharjoittaja"
_SOLE = _re.compile(r"(?<![\w-])(?:tmi|t:mi|toiminimi|enskild\s+(?:firma|näringsidkare))(?![\w-])", _re.I)
HIDDEN_GIVERS = (PRIVATE_LABEL, SOLE_LABEL)


def is_sole_trader(name) -> bool:
    return isinstance(name, str) and bool(_SOLE.search(name))


def mask_private_givers(tree):
    """A private individual who once filed a statement marked "Yksityishenkilön lausunto" may file another under
    their own name ("Sukunimi Etunimi, lausunto"): collect every such name in the tree, then show all of their
    statements (and the per-project giver lists) as PRIVATE_LABEL. Returns (tree, number of names)."""
    names: set[str] = set()

    def collect(o):
        if isinstance(o, dict):
            if isinstance(o.get("org"), str) and o["org"] != PRIVATE_LABEL and _PRIVATE_TITLE.search(str(o.get("title") or "")):
                names.add(o["org"])
            for v in o.values():
                collect(v)
        elif isinstance(o, list):
            for v in o:
                collect(v)

    def mask(o):
        if isinstance(o, dict):
            out = {}
            hidden = o.get("org") if o.get("org") in names else None
            for k, v in o.items():
                if k == "org" and v in names:
                    out[k] = PRIVATE_LABEL
                elif hidden and k == "title" and isinstance(v, str):
                    out[k] = v.replace(hidden, PRIVATE_LABEL)
                elif k == "orgs" and isinstance(v, list):
                    seen: list = []
                    for x in v:
                        x = PRIVATE_LABEL if x in names else x
                        if x not in seen:
                            seen.append(x)
                    out[k] = seen
                else:
                    out[k] = mask(v)
            return out
        if isinstance(o, list):
            return [mask(v) for v in o]
        return o

    collect(tree)
    return (mask(tree) if names else tree), len(names)


def scrub_personal(o, *, text: bool = True, cache: bool = False):
    """Minimise personal data in a JSON tree (returns a new tree). text=False only drops hearing names
    and private individuals' names; cache=True also masks signer names where the organisation is known."""
    if isinstance(o, dict):
        out = {}
        private = isinstance(o.get("org"), str) and bool(_PRIVATE_TITLE.search(str(o.get("title") or "")))
        sole = not private and is_sole_trader(o.get("org"))
        for k, v in o.items():
            if private and k == "org":
                out[k] = PRIVATE_LABEL
                continue
            if sole and k == "org":
                out[k] = SOLE_LABEL
                continue
            if sole and k == "title" and isinstance(v, str):
                out[k] = v.replace(o["org"], SOLE_LABEL)
                continue
            if k in ("orgs", "givers") and isinstance(v, list) and any(is_sole_trader(x) for x in v):
                seen: list = []
                for x in v:
                    x = SOLE_LABEL if is_sole_trader(x) else x
                    if x not in seen:
                        seen.append(x)
                v = seen
            if cache and k == "person" and isinstance(v, str) and v and v != "[nimi]" and (o.get("org") or "").strip():
                out[k] = "[nimi]"
                continue
            if k == "heard" and isinstance(v, list):
                v = [{kk: vv for kk, vv in h.items() if kk != "name"} if isinstance(h, dict) else h for h in v]
            if text and isinstance(v, str) and k.lower().endswith("url") and ("@" in v or "[sähköposti]" in v):
                if "[sähköposti]" in _scrub_text(v):  # a mailto disguised as a link ("https://etu.suku@kunta.fi"): no usable link
                    continue
            out[k] = scrub_personal(v, text=text, cache=cache)
        return out
    if isinstance(o, list):
        return [scrub_personal(v, text=text, cache=cache) for v in o]
    if text and isinstance(o, str) and len(o) > 6:
        return _scrub_text(o)
    return o


def save_json(path: Path, data, *, compact: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        rel = path.resolve().relative_to(ROOT)
    except ValueError:
        rel = None
    if rel is not None and rel.parts[:2] == ("docs", "data"):
        data = scrub_personal(data)
    elif rel is not None and rel.parts[:2] == ("data", "cache"):
        data = scrub_personal(data, cache=True)  # the repo is public: caches get the same minimisation
    if compact:
        txt = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    else:
        txt = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    path.write_text(txt + "\n", encoding="utf-8")


def load_yaml(path: Path):
    import yaml  # lazy: only the build needs it

    return yaml.safe_load(path.read_text(encoding="utf-8"))


FI_MONTHS = {
    "tammikuuta": 1, "helmikuuta": 2, "maaliskuuta": 3, "huhtikuuta": 4, "toukokuuta": 5, "kesäkuuta": 6,
    "heinäkuuta": 7, "elokuuta": 8, "syyskuuta": 9, "lokakuuta": 10, "marraskuuta": 11, "joulukuuta": 12,
}
_FI_DATE_RE = re.compile(r"(\d{1,2})\s+päivänä\s+(\w+kuuta)\s+(\d{4})")
_DMY_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")


def parse_fi_date(text: str) -> str | None:
    """'1 päivänä tammikuuta 2027' -> '2027-01-01'."""
    m = _FI_DATE_RE.search(text)
    if not m:
        return None
    month = FI_MONTHS.get(m.group(2).lower())
    if not month:
        return None
    try:
        return dt.date(int(m.group(3)), month, int(m.group(1))).isoformat()
    except ValueError:
        return None


def parse_dmy(text: str) -> str | None:
    m = _DMY_RE.search(text or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def days_ago(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return (TODAY - dt.date.fromisoformat(iso[:10])).days
    except ValueError:
        return None


def is_future(iso: str | None) -> bool:
    try:
        return dt.date.fromisoformat(iso[:10]) > TODAY
    except (TypeError, ValueError):
        return False
