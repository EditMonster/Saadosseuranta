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


def http(method: str, url: str, *, retries: int = 3, timeout: int = 60, **kw) -> requests.Response:
    last = None
    for attempt in range(retries):
        try:
            r = SESSION.request(method, url, timeout=timeout, **kw)
            if r.status_code == 429:
                wait = min(int(r.headers.get("Retry-After", "20") or 20), 120)
                time.sleep(wait + 1)
                raise requests.HTTPError(f"429 for {url}", response=r)
            if r.status_code in (500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} for {url}", response=r)
            return r
        except (requests.RequestException, requests.HTTPError) as e:  # noqa: PERF203
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"request failed after {retries} attempts: {url}: {last}")


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


def save_json(path: Path, data, *, compact: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
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
