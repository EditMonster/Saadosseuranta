"""Incumbent suppliers of state-sector contracting entities from Tutkihankintoja.fi (Hansel /
Valtiokonttori: the central government's purchase invoices, CC BY 4.0).

The site is a React app on a Spring backend, https://hns-th-spring-prod-api.azurewebsites.net.
Its requests carry ``subscription-key=<key>`` as a query parameter; the key is the site's own public
key baked into the browser bundle (assets/index-*.js) and is kept in config/settings.yaml
(``toimittajat.key``) because the site may rotate it – if the backend answers 401/403 the run
fails loudly so the key can be updated. Only the state sector (``sector=Valtio``) is loaded in the
current version; municipal data is not available there.

Endpoints used (dates dd.MM.yyyy, the date range must stay within one calendar year):

* ``GET /index/vendors?startDate&endDate&sector=Valtio`` – top vendors; its ``filters.subBranches``
  (agencies) and ``filters.mainBranches`` (ministries' administrative branches) are the buyer index
  we match Hilma buyer names against; ``subBranches=<id>`` / ``mainBranches=<id>`` and
  ``categories=<id>`` narrow the same table to one buyer and one procurement-category group.

For every distinct state-sector buyer with open or awarded tenders in data/cache/hankinnat.json
(at most ``max_buyers`` per run, each refreshed after ``refresh_days``) the last 12 months are
fetched as two same-year windows and merged: the overall top 8 vendors and the top 8 in up to two
category groups implied by the buyer's tenders (``toimittajat.kategoriat`` maps Hilma CPV topics to
Tutkihankintoja category groups). Polite: ≤1 request/s.

Cache: data/cache/toimittajat.json {fetched, index: {...}, buyers: {normBuyer: {fetched, name, hilmaNames,
id, branch, period, top: [{name, yTunnus?, sum, category}]}}}; normBuyer is the normalised backend name
(fetch_mao.norm) and ``category`` null = all purchases.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from collections import Counter
from urllib.parse import unquote

from common import CACHE_DIR, CONFIG_DIR, TODAY, http, load_json, load_yaml, log, save_json
from fetch_mao import norm

API = "https://hns-th-spring-prod-api.azurewebsites.net"
OUT = CACHE_DIR / "toimittajat.json"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) saadosseuranta/1.0 (+https://github.com/EditMonster/Saadosseuranta)",
      "Accept": "application/json", "Origin": "https://tutkihankintoja.fi", "Referer": "https://tutkihankintoja.fi/"}
TOP_N = 8
MAX_GROUPS = 2
STAGES = ("avoin", "ratkaistu")
YT = re.compile(r"(\d{7}-\d)")


def dmy(d: dt.date) -> str:
    return d.strftime("%d.%m.%Y")


def windows(today: dt.date) -> list[tuple[dt.date, dt.date]]:
    """The last 12 months (data lags ~5 days) split at New Year – the backend rejects ranges spanning two years."""
    end = today - dt.timedelta(days=5)
    try:
        start = end.replace(year=end.year - 1) + dt.timedelta(days=1)
    except ValueError:  # 29 Feb
        start = end.replace(year=end.year - 1, day=28) + dt.timedelta(days=1)
    if start.year < end.year:
        return [(start, dt.date(start.year, 12, 31)), (dt.date(end.year, 1, 1), end)]
    return [(start, end)]


def match_buyer(name: str, index: dict[str, dict]) -> dict | None:
    """Hilma buyer name -> backend buyer {id, name, branch}; exact normalised match first, then a prefix
    match (the backend truncates long names: 'Valtion tieto- ja viestintätekniikk')."""
    n = norm(name)
    if not n or len(n) < 4:
        return None
    if n in index:
        return index[n]
    for branch in ("sub", "main"):
        for key, b in index.items():
            if b["branch"] != branch or len(key) < 12:
                continue
            if n.startswith(key + " ") or n.startswith(key) and len(key) >= 20 or key.startswith(n + " "):
                return b
    return None


def buyer_index(resp: dict) -> dict[str, dict]:
    f = resp.get("filters") or {}
    out: dict[str, dict] = {}
    for branch, key in (("sub", "subBranches"), ("main", "mainBranches")):
        for b in f.get(key) or []:
            if b.get("name"):
                # ids come percent-encoded ("Valtioneuvoston%20kanslia"); requests encodes query values itself
                out.setdefault(norm(b["name"]), {"id": unquote(b.get("id") or b["name"]), "name": b["name"], "branch": branch})
    return out


def vendors_table(resp: dict) -> list[dict]:
    """The response table -> [{name, yTunnus?, sum}] (confidential/unknown vendors dropped)."""
    out = []
    for row in ((resp.get("table") or {}).get("data") or []):
        if not row:
            continue
        first = row[0] or {}
        name = (first.get("value") or "").strip()
        if not name or name.lower().startswith(("salassa", "tuntematon", "ei tiedossa")):
            continue
        yt = YT.search(first.get("extra") or "")
        amount = next((c.get("value") for c in row[1:] if c.get("type") == "number"), None)
        if amount is None:
            continue
        out.append({"name": name, "yTunnus": yt.group(1) if yt else None, "sum": float(amount)})
    return out


def merge(tables: list[list[dict]], category: str | None, top_n: int = TOP_N) -> list[dict]:
    acc: dict[str, dict] = {}
    for t in tables:
        for v in t:
            k = v["name"].lower()
            e = acc.setdefault(k, {"name": v["name"], "yTunnus": v.get("yTunnus"), "sum": 0.0})
            e["sum"] += v["sum"]
            e["yTunnus"] = e["yTunnus"] or v.get("yTunnus")
    rows = sorted((e for e in acc.values() if e["sum"] > 0), key=lambda e: -e["sum"])[:top_n]
    return [{k: v for k, v in {"name": e["name"], "yTunnus": e["yTunnus"], "sum": round(e["sum"]), "category": category}.items() if v is not None or k == "category"}
            for e in rows]


class Client:
    def __init__(self, key: str):
        self.key = key
        self.requests = 0
        self.last = 0.0

    def get(self, path: str, params: dict) -> dict:
        wait = 1.0 - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        q = {**params, "sector": "Valtio", "lang": "fi"}
        if self.key:
            q["subscription-key"] = self.key
        r = http("GET", API + path, params=q, headers=UA, timeout=90)
        self.last = time.monotonic()
        self.requests += 1
        if r.status_code in (401, 403):
            raise RuntimeError(f"Tutkihankintoja: avain hylättiin (HTTP {r.status_code}) – päivitä toimittajat.key config/settings.yaml:iin "
                               "sivuston selainpaketista (assets/index-*.js, 'subscription-key=')")
        r.raise_for_status()
        return r.json()


def top_for(client: Client, buyer: dict, category_id: str | None, wins: list[tuple[dt.date, dt.date]]) -> list[dict]:
    tables = []
    for a, b in wins:
        params = {"startDate": dmy(a), "endDate": dmy(b), ("subBranches" if buyer["branch"] == "sub" else "mainBranches"): buyer["id"]}
        if category_id:
            params["categories"] = category_id
        try:
            tables.append(vendors_table(client.get("/index/vendors", params)))
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001
            log(f"warn: toimittajat {buyer['name']} {dmy(a)}–{dmy(b)}: {e}")
    return tables


def main():
    cfg = (load_yaml(CONFIG_DIR / "settings.yaml") or {}).get("toimittajat", {}) or {}
    if not cfg.get("enabled", True):
        log("toimittajat: pois käytöstä (toimittajat.enabled=false)")
        return
    key = str(cfg.get("key") or "")
    max_buyers = int(cfg.get("max_buyers", 40))
    refresh_days = int(cfg.get("refresh_days", 30))
    group_map: dict[str, list[str]] = cfg.get("kategoriat") or {}
    old = load_json(OUT, {}) or {}
    buyers: dict[str, dict] = dict(old.get("buyers") or {})
    stale = (TODAY - dt.timedelta(days=refresh_days)).isoformat()

    hank = load_json(CACHE_DIR / "hankinnat.json", {}) or {}
    tenders = hank.get("items") or []
    names: Counter[str] = Counter()
    topics_by: dict[str, Counter] = {}
    cpv_prefixes = []
    hcfg = load_yaml(CONFIG_DIR / "hankinnat.yaml") or {}
    for cat, codes in (hcfg.get("toimialat") or {}).items():
        cpv_prefixes += [(str(c), cat) for c in codes]
    cpv_prefixes.sort(key=lambda x: -len(x[0]))

    def topic(cpv: str) -> str | None:
        for p, c in cpv_prefixes:
            if (cpv or "").startswith(p):
                return c
        return None

    for n in tenders:
        buyer = (n.get("organisationNameFi") or n.get("organisationNameSv") or n.get("organisationNameEn") or "").strip()
        if not buyer or n.get("isCancelled"):
            continue
        mt = n.get("mainType") or ""
        if mt not in ("ContractNotices", "ContractAwardNotices"):
            continue
        names[buyer] += 1
        codes = [c for c in re.split(r"[\s,;]+", n.get("cpvCodes") or "") if c]
        t = topic(codes[0]) if codes else None
        if t:
            topics_by.setdefault(buyer, Counter())[t] += 1

    client = Client(key)
    wins = windows(TODAY)
    first = client.get("/index/vendors", {"startDate": dmy(wins[-1][0]), "endDate": dmy(wins[-1][1])})
    index = buyer_index(first)
    if len(index) < 20:
        raise RuntimeError(f"Tutkihankintoja: hankintayksikköindeksissä vain {len(index)} nimeä – rajapinta on ehkä muuttunut")

    # one cache entry per backend buyer, however Hilma spells it ("Liikenne- ja viestintävirasto Traficom")
    matched: dict[str, tuple[dict, list[str], Counter]] = {}
    for buyer, _cnt in names.most_common():
        b = match_buyer(buyer, index)
        if b:
            entry = matched.setdefault(norm(b["name"]), (b, [], Counter()))
            entry[1].append(buyer)
            entry[2].update(topics_by.get(buyer, Counter()))
    todo = [(k, v) for k, v in matched.items() if (buyers.get(k) or {}).get("fetched", "") < stale][:max_buyers]
    log(f"toimittajat: {len(names)} hankintayksikköä Hilmassa, {len(matched)} valtion yksikköä tunnistettu, {len(todo)} haetaan nyt")
    done = 0
    for key_norm, (b, hilma_names, tcount) in todo:
        groups: list[str] = []
        for t, _ in tcount.most_common():
            for g in group_map.get(t) or []:
                if g not in groups:
                    groups.append(g)
            if len(groups) >= MAX_GROUPS:
                break
        groups = groups[:MAX_GROUPS]
        top = merge(top_for(client, b, None, wins), None)
        for g in groups:
            top += merge(top_for(client, b, g, wins), g)
        if not top:
            log(f"warn: toimittajat {b['name']}: ei laskurivejä")
        buyers[key_norm] = {"fetched": TODAY.isoformat(), "name": b["name"], "hilmaNames": hilma_names[:5], "id": b["id"], "branch": b["branch"],
                            "period": {"from": wins[0][0].isoformat(), "to": wins[-1][1].isoformat()}, "top": top}
        done += 1
    # forget buyers that no longer appear in Hilma and are older than two refresh periods
    drop_before = (TODAY - dt.timedelta(days=2 * refresh_days)).isoformat()
    buyers = {k: v for k, v in buyers.items() if k in matched or v.get("fetched", "") >= drop_before}
    save_json(OUT, {"fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "index": {"subBranches": sum(1 for b in index.values() if b["branch"] == "sub"), "mainBranches": sum(1 for b in index.values() if b["branch"] == "main"),
                              "currentDate": (first.get("currentDate") or "")[:10], "names": sorted(b["name"] for b in index.values())},
                    "buyers": buyers}, compact=True)
    log(f"toimittajat: {done} hankintayksikköä päivitetty ({client.requests} pyyntöä), {len(buyers)} välimuistissa -> {OUT}")


if __name__ == "__main__":
    main()
