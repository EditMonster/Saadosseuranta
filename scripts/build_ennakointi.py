"""Forward-looking rows of the Kilpailutukset segment, built from the caches of fetch_sopimuskaudet.py,
fetch_suunnitelmat.py and fetch_ted.py. Pure functions – no network – that return rows in the shape
build_hankinnat.py produces (scope "hankinta", laji "kilpailutus", events, related, topics by the same
CPV → toimiala classification), so docs/index.html renders them unchanged:

* ``forecast_rows`` – stage "ennuste": a re-tender forecast per award notice whose contract ends within
  the next 0–18 months. The forecast window is contractEnd − 9 months … contractEnd − 3 months (the
  usual lead time between a contract notice and the start of the next contract); events are the start of
  that window ("Uusi kilpailutus odotettavissa (arvio)", kind ennuste) and the contract end(s) (kind
  maaraaika, never confirmed). ``related`` points at the award row when it is still on the page.
* ``plan_rows`` – stage "kalenteri": Hilma kilpailutussuunnitelmat and the buyers' own calendars, one row
  per planned procurement with ``plannedText`` as the buyer wrote it and ``plannedDate`` as our ISO
  estimate. When the same buyer has since published a notice with a matching title (token overlap ≥ 0.6)
  the row's status becomes "julkaistu Hilmassa" and ``related`` links to that notice.
* ``ted_rows`` – TED notices from the configured neighbouring countries: stage "avoin" (contract
  notices) or "tulossa" (prior information notices), with ``country`` set so the page can filter by
  country (FI = Hilma rows, which have no country field).

``link_back`` adds the reciprocal ``related`` entries to the Hilma rows so that lifecycle links stay
mutual, and ``ennakointi_rows`` runs all three builders tolerant of one of them failing.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re

from common import CACHE_DIR, CONFIG_DIR, TODAY, load_json, load_yaml, log
from build_hankinnat import _cfg, category, clean, notice_url
from build_mao import classify_subject
from fetch_sopimuskaudet import add_months

SOPIMUSKAUDET = CACHE_DIR / "sopimuskaudet.json"
SUUNNITELMAT = CACHE_DIR / "suunnitelmat.json"
TED_CACHE = CACHE_DIR / "ted.json"
CPV_LABELS = CACHE_DIR / "cpv.json"
STOPWORDS = {"ja", "sekä", "tai", "hankinta", "hankinnan", "kilpailutus", "kilpailutuksen", "puitejärjestely", "puitesopimus",
             "dps", "dynaaminen", "hankintajärjestelmä", "jälki-ilmoitus", "jälki", "ilmoitus", "osa", "osa-alue", "palvelut",
             "palvelujen", "palveluiden", "palvelu", "the", "of", "and", "för", "och", "av", "oy", "ab", "kaupunki", "kaupungin"}
TED_KINDS = {"cn-standard": "Hankintailmoitus", "cn-social": "SOTE- ja muut erityiset palvelut",
             "pin-cfc-standard": "Tarjouskilpailukutsuna käytettävä ennakkoilmoitus", "pin-only": "Ennakkoilmoitus",
             "pin-buyer": "Ennakkoilmoitus"}
COUNTRY_FI = {"SE": "Ruotsi", "EE": "Viro", "DK": "Tanska", "NO": "Norja", "LV": "Latvia", "LT": "Liettua", "DE": "Saksa",
              "PL": "Puola", "IS": "Islanti", "NL": "Alankomaat"}


# ---------- shared helpers ----------

def _prefixes(hcfg):
    """CPV prefix table from the hankinnat.yaml dict (as build_hankinnat passes it), loading the file when absent."""
    cfg = hcfg if isinstance(hcfg, dict) and hcfg.get("toimialat") else _cfg()[0]
    prefixes = sorted(((str(p), name) for name, codes in (cfg.get("toimialat") or {}).items() for p in codes), key=lambda x: -len(x[0]))
    return cfg, prefixes


def topics_for(codes, prefixes) -> list[str]:
    cats = []
    for code in codes or []:
        c = category(str(code), prefixes)
        if c and c not in cats:
            cats.append(c)
    return cats[:3] or ["Muut"]


def _codes(cpv) -> list[str]:
    if isinstance(cpv, list):
        return [str(c) for c in cpv if c]
    return [c for c in re.split(r"[\s,;]+", str(cpv or "")) if c]


def _labels() -> dict:
    return load_json(CPV_LABELS, {}).get("labels", {})


def _base(stage: str, kind: str) -> dict:
    return {"scope": "hankinta", "laji": "kilpailutus", "stage": stage, "kind": kind}


def _compact(row: dict) -> dict:
    return {k: v for k, v in row.items() if v not in (None, "", [], False)}


def tokens(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[\wäöå]+", (text or "").lower()):
        if len(w) >= 3 and w not in STOPWORDS and not w.isdigit():
            out.add(w[:12])  # crude stemming: 'siivouspalvelut' ~ 'siivouspalvelun' (12 keeps Finnish compounds apart)
    return out


def title_overlap(a: str, b: str, drop: set[str] | None = None) -> float:
    """Share of the shorter title's tokens found in the other one. At least two tokens must be shared unless both
    titles are single-token, so that 'Sairaalakalusteet' alone never claims every title mentioning a hospital.
    `drop` removes tokens that carry no meaning here (the buyer's own name inside titles such as 'HUS 463-2025 …')."""
    ta, tb = tokens(a) - (drop or set()), tokens(b) - (drop or set())
    if not ta or not tb:
        return 0.0
    shared = ta & tb
    if min(len(ta), len(tb)) == 1:
        return 1.0 if (len(ta) == len(tb) == 1 and shared) else 0.0
    if len(shared) < 2:
        return 0.0
    return len(shared) / min(len(ta), len(tb))


def norm_buyer(name: str) -> str:
    return re.sub(r"[^a-zäöå0-9]+", " ", (name or "").lower()).strip()


def fmt_date(iso: str | None) -> str:
    if not iso:
        return "?"
    y, m, d = iso[:10].split("-")
    return f"{int(d)}.{int(m)}.{y}"


def fmt_money(v, cur: str | None = "EUR") -> str | None:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    cur = cur or "EUR"
    if v >= 1e6:
        return f"{v / 1e6:.1f} M{'€' if cur == 'EUR' else ' ' + cur}".replace(".", ",")
    return f"{v:,.0f} {'€' if cur == 'EUR' else cur}".replace(",", " ")


def _rel(t: dict) -> dict:
    return {"id": t["id"], "stage": t.get("stage", "avoin"), "kind": t.get("kind"), "published": t.get("published")}


# ---------- stage "ennuste" ----------

def forecast_rows(settings, tenders: list[dict], hcfg=None, cache: dict | None = None) -> list[dict]:
    """Re-tender forecasts from the contract periods behind recent award notices (see module docstring)."""
    ecfg = (settings or {}).get("ennusteet") or {}
    max_months = int(ecfg.get("max_months", 18))
    lead_from, lead_to = int(ecfg.get("lead_from_months", 9)), int(ecfg.get("lead_to_months", 3))
    min_duration = int(ecfg.get("min_duration_months", 6))  # one-off deliveries and DPS mini-competitions of a few weeks are noise
    cache = cache if cache is not None else load_json(SOPIMUSKAUDET, {})
    notices = (cache or {}).get("notices") or {}
    if not notices:
        return []
    _, prefixes = _prefixes(hcfg)
    labels = _labels()
    by_id = {t["id"]: t for t in tenders or [] if t.get("id")}
    horizon = add_months(TODAY, max_months).isoformat()
    rows = []
    for rec in notices.values():
        end = rec.get("contractEnd")
        if rec.get("skip") or not end or end < TODAY.isoformat() or end > horizon:
            continue
        months = rec.get("durationMonths")
        if not months and rec.get("contractStart"):  # a 0-month record means a span of days: measure it
            months = (dt.date.fromisoformat(end) - dt.date.fromisoformat(rec["contractStart"])).days / 30.44
        if months is not None and months < min_duration:
            continue
        end_d = dt.date.fromisoformat(end)
        window = {"from": add_months(end_d, -lead_from).isoformat(), "to": add_months(end_d, -lead_to).isoformat()}
        codes = _codes(rec.get("cpv"))
        winners = rec.get("winners") or []
        incumbent = "; ".join(w.get("name") for w in winners if w.get("name"))[:200] or None
        value = rec.get("value")
        with_opt = rec.get("contractEndWithOptions")
        options = rec.get("optionsText") or rec.get("renewalText")
        bits = [f"Sopimuskausi {fmt_date(rec.get('contractStart'))}–{fmt_date(end)}" + (f" ({rec['durationMonths']} kk)" if rec.get("durationMonths") else "")]
        if rec.get("framework"):
            bits[0] += ", puitejärjestely"
        if rec.get("dps"):
            bits[0] += ", dynaaminen hankintajärjestelmä"
        if incumbent:
            bits.append(f"Nykyinen toimittaja: {incumbent}")
        if value:
            bits.append(f"Arvo {fmt_money(value, rec.get('currency'))}")
        if with_opt:
            bits.append(f"Optiot käytettynä {fmt_date(with_opt)} asti")
        bits.append(f"Uusi kilpailutus odotettavissa arviolta {fmt_date(window['from'])}–{fmt_date(window['to'])} (arvio sopimuskauden päättymisestä)")
        events = [{"date": window["from"], "label": "Uusi kilpailutus odotettavissa (arvio)", "kind": "ennuste", "confirmed": False},
                  {"date": end, "label": "Sopimuskausi päättyy", "kind": "maaraaika", "confirmed": False}]
        if with_opt and with_opt != end:
            events.append({"date": with_opt, "label": "Sopimuskausi päättyy optiot käytettynä", "kind": "maaraaika", "confirmed": False})
        if rec.get("published"):
            events.insert(0, {"date": rec["published"], "label": "Jälki-ilmoitus julkaistu" + (f" – {incumbent[:60]}" if incumbent else ""), "kind": "hyvaksytty"})
        events.sort(key=lambda e: e["date"])
        award = by_id.get(f"hk-{rec.get('id')}")
        n = {"isEForms": rec.get("isEForms"), "procedureId": rec.get("procedureId"), "noticeId": rec.get("noticeId"),
             "oldProcurementProjectId": rec.get("oldProcurementProjectId")}
        row = _base("ennuste", "Uudelleenkilpailutuksen ennuste") | {
            "id": f"hk-enn-{rec.get('id')}", "title": (rec.get("title") or "(nimetön)")[:220], "buyer": rec.get("buyer"), "buyerId": rec.get("buyerId"),
            "incumbent": incumbent, "incumbents": [{"name": w.get("name"), "id": w.get("id")} for w in winners[:5]] or None,
            "lastValue": value, "currency": rec.get("currency") if value else None,
            "contractStart": rec.get("contractStart"), "contractEnd": end, "contractEndWithOptions": with_opt,
            "durationMonths": rec.get("durationMonths"), "optionsText": options, "framework": bool(rec.get("framework")), "dps": bool(rec.get("dps")),
            "forecastWindow": window, "published": rec.get("published"), "awardDate": rec.get("awardDate"), "contractDate": rec.get("contractDate"),
            "eu": bool(rec.get("eu")), "cpv": codes[0] if codes else None, "cpvLabel": labels.get(codes[0]) if codes else None,
            "topics": topics_for(codes, prefixes), "summary": ". ".join(bits)[:500], "url": (award or {}).get("url") or notice_url(n),
            "status": "ennuste", "events": events, "related": [_rel(award)] if award else None}
        rows.append(_compact(row))
    rows.sort(key=lambda r: (r["contractEnd"], r["id"]))
    return rows


# ---------- stage "kalenteri" ----------

def _match_notice(buyer_names: list[str], buyer_id: str | None, title: str, open_tenders: list[dict], threshold: float = 0.6,
                  not_before: str | None = None) -> dict | None:
    """The open or upcoming Hilma notice that a plan has become: same buyer (Y-tunnus, or a configured name), published
    on or after `not_before` (a notice older than the plan is its predecessor, not its outcome) and a title whose
    tokens overlap the plan title by at least `threshold`."""
    names = {norm_buyer(b) for b in buyer_names if b}
    drop = set().union(*(tokens(b) for b in buyer_names if b)) if buyer_names else set()
    best, best_score = None, 0.0
    for t in open_tenders:
        same = (buyer_id and t.get("buyerId") == buyer_id) or (norm_buyer(t.get("buyer") or "") in names)
        if not same or (not_before and (t.get("published") or "") < not_before):
            continue
        score = title_overlap(title, t.get("title") or "", drop | tokens(t.get("buyer") or ""))
        if score >= threshold and (score > best_score or (score == best_score and (t.get("published") or "") > (best.get("published") or ""))):
            best, best_score = t, score
    return best


def _plan_id(source: str, buyer: str, title: str) -> str:
    """Stable id: sha1 of source + normalised buyer + normalised title (whitespace collapsed, lower case)."""
    t = re.sub(r"\s+", " ", (title or "").strip().lower())
    key = f"{source}|{norm_buyer(buyer)}|{t}"
    return "hk-kal-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def plan_rows(settings, tenders: list[dict], hcfg=None, cache: dict | None = None, kcal: dict | None = None) -> list[dict]:
    """Hilma kilpailutussuunnitelmat + buyers' calendars as stage "kalenteri" rows (see module docstring)."""
    kcfg = (settings or {}).get("kalenterit") or {}
    max_months = int(kcfg.get("max_months", 24))
    past_days = int(kcfg.get("past_days", 30))
    threshold = float(kcfg.get("title_overlap", 0.6))
    match_months = int(kcfg.get("match_months", 12))  # calendar rows: only notices of the last 12 months can be "the" notice
    cache = cache if cache is not None else load_json(SUUNNITELMAT, {})
    if not cache:
        return []
    kcal = kcal if kcal is not None else (load_yaml(CONFIG_DIR / "kalenterit.yaml") or {}).get("kalenterit") or {}
    cfg, prefixes = _prefixes(hcfg)
    labels = _labels()
    open_tenders = [t for t in tenders or [] if t.get("stage") in ("avoin", "tulossa") and t.get("status") in ("avoin", "tulossa")
                    and not t.get("country") and str(t.get("id", "")).startswith("hk-") and not str(t.get("id", "")).startswith("hk-ted-")]
    lo = (TODAY - dt.timedelta(days=past_days)).isoformat()
    hi = add_months(TODAY, max_months).isoformat()
    rows, seen = [], set()

    def add(source: str, src_names: list[str], kind: str, p: dict, hilma: bool):
        planned = p.get("plannedDate")
        if not planned:
            return
        title, buyer = (p.get("title") or "").strip(), (p.get("buyer") or "").strip()
        if not title:
            return
        not_before = (add_months(dt.date.fromisoformat(p["published"]), -1).isoformat() if hilma and p.get("published")
                      else add_months(TODAY, -match_months).isoformat())
        match = _match_notice([buyer] + src_names, p.get("buyerId"), title, open_tenders, threshold, not_before)
        if not match and (planned < lo or planned > hi):
            return
        rid = _plan_id(source, buyer, title)
        n = 2
        while rid in seen:  # identical title twice in one calendar (e.g. yearly repeats): keep both, stable order
            rid = _plan_id(source, buyer, f"{title} #{n}")
            n += 1
        seen.add(rid)
        codes = _codes(p.get("cpv"))
        topics = topics_for(codes, prefixes) if codes else classify_subject(" ".join([title, p.get("category") or "", p.get("description") or ""]), cfg)
        events = [{"date": planned, "label": "Hankintailmoitus suunniteltu (arvio)", "kind": "ennuste", "confirmed": False}]
        if hilma and p.get("published"):
            events.append({"date": p["published"], "label": "Kilpailutussuunnitelma julkaistu Hilmassa", "kind": "julkaistu"})
        if p.get("dialogueDate"):
            events.append({"date": p["dialogueDate"], "label": "Markkinavuoropuhelu (suunnitelma)", "kind": "ennuste", "confirmed": False})
        if p.get("contractStart"):
            events.append({"date": p["contractStart"], "label": "Sopimuskausi alkaa (suunnitelma)", "kind": "ennuste", "confirmed": False})
        if match:
            events.append({"date": match.get("published") or TODAY.isoformat(), "label": f"{match.get('kind') or 'Hankintailmoitus'} julkaistu Hilmassa", "kind": "he"})
        events.sort(key=lambda e: e["date"])
        desc = clean(p.get("description") or p.get("summary") or "")
        extra = []
        if p.get("phase"):
            extra.append(f"Vaihe: {p['phase']}")
        if p.get("contractStart") and not hilma:
            extra.append(f"Sopimuskausi alkaa {fmt_date(p['contractStart'])}" + (f"–{fmt_date(p['contractEnd'])}" if p.get("contractEnd") else ""))
        if p.get("value"):
            extra.append(f"Ennakoitu arvo {fmt_money(p['value'], p.get('currency'))}")
        summary = (desc[:300] + ("…" if len(desc) > 300 else "")) if desc else ". ".join(extra)
        row = _base("kalenteri", kind) | {
            "id": rid, "source": source, "title": title[:220], "buyer": buyer or None, "buyerId": p.get("buyerId"),
            "plannedText": p.get("plannedText") or fmt_date(planned), "plannedDate": planned, "phase": p.get("phase"), "category": p.get("category"),
            "contractStart": p.get("contractStart"), "contractEnd": p.get("contractEnd"), "published": p.get("published") if hilma else None,
            "expires": p.get("expires") if hilma else None, "value": p.get("value"), "currency": p.get("currency") if p.get("value") else None,
            "eu": p.get("eu") if p.get("eu") is not None else (p.get("type") == "EU" if hilma else None), "nature": p.get("nature"),
            "cpv": codes[0] if codes else None, "cpvLabel": labels.get(codes[0]) if codes else None, "topics": topics,
            "summary": summary[:500], "url": p.get("url"), "likes": p.get("likes"), "reference": p.get("reference") or p.get("agreement"),
            "status": "julkaistu Hilmassa" if match else "suunniteltu", "events": events, "related": [_rel(match)] if match else None}
        rows.append(_compact(row))

    for p in (cache.get("hilma") or {}).values():
        add("hilma", [], "Kilpailutussuunnitelma (Hilma)", p, True)
    for key, plist in (cache.get("kalenterit") or {}).items():
        src = kcal.get(key) or {}
        names = list(src.get("hilma_nimet") or []) + [src.get("nimi") or ""]
        for p in plist or []:
            add(key, names, f"Hankintakalenteri ({(p.get('buyer') or src.get('nimi') or key)})", p, False)
    rows.sort(key=lambda r: (r["plannedDate"], r["id"]))
    return rows


# ---------- TED rows ----------

def ted_rows(settings, hcfg=None, cache: dict | None = None) -> list[dict]:
    """TED notices of the configured countries as "avoin"/"tulossa" rows with a `country` field."""
    tcfg = (settings or {}).get("ted") or {}
    if not tcfg.get("enabled", True):
        return []
    keep_days = int(((settings or {}).get("hankinnat") or {}).get("keep_closed_days", 14))
    cache = cache if cache is not None else load_json(TED_CACHE, {})
    notices = (cache or {}).get("notices") or {}
    if not notices:
        return []
    _, prefixes = _prefixes(hcfg)
    labels = _labels()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    wanted = {str(c).upper() for c in (tcfg.get("maat") or [])}
    rows = []
    for rec in notices.values():
        ntype = rec.get("noticeType") or ""
        stage = "tulossa" if ntype.startswith("pin") else "avoin"
        deadline = rec.get("deadline")
        if deadline and deadline[:10] < cutoff:
            continue
        if wanted and rec.get("country") not in wanted:
            continue
        if stage == "avoin" and not deadline:
            continue
        codes = _codes(rec.get("cpv"))
        country = rec.get("country")
        if stage == "avoin":
            status = "avoin" if deadline >= now else "päättynyt"
        else:
            status = "tulossa" if (not deadline or deadline >= now) else "päättynyt"
        events = []
        if rec.get("published"):
            events.append({"date": rec["published"], "label": ("Hankintailmoitus" if stage == "avoin" else "Ennakkoilmoitus") + " julkaistu (TED)",
                           "kind": "he" if stage == "avoin" else "ehdotus"})
        if deadline:
            events.append({"date": deadline[:10], "label": ("Osallistumishakemukset" if rec.get("deadlineKind") == "osallistumishakemus" else "Tarjoukset") + " viimeistään",
                           "kind": "maaraaika"})
        kind = TED_KINDS.get(ntype, "Hankintailmoitus")
        summary = f"{COUNTRY_FI.get(country, country)}: {kind.lower()} TED:ssä" + (f" – {rec['cpvText']}" if rec.get("cpvText") else "") \
            + (f". Ennakoitu arvo {fmt_money(rec.get('value'), rec.get('currency'))}" if rec.get("value") else "")
        row = _base(stage, kind) | {
            "id": f"hk-ted-{rec.get('pn')}", "title": (rec.get("title") or "(nimetön ilmoitus)")[:220], "buyer": rec.get("buyer"), "country": country,
            "deadline": deadline, "deadlineKind": (rec.get("deadlineKind") or ("tarjous" if stage == "avoin" else "vastaus")) if deadline else None,
            "published": rec.get("published"), "cpv": codes[0] if codes else None, "cpvLabel": labels.get(codes[0]) if codes else None,
            "topics": topics_for(codes, prefixes), "value": rec.get("value"), "currency": rec.get("currency") if rec.get("value") else None,
            "eu": True, "ted": True, "tedNumber": rec.get("pn"), "procedureUuid": rec.get("procedureId"),
            "summary": summary[:500], "url": rec.get("url"), "tedUrl": rec.get("url"), "status": status, "events": events}
        rows.append(_compact(row))
    rows.sort(key=lambda r: (r.get("deadline") or "~" + (r.get("published") or ""), r["id"]))
    return rows


# ---------- glue ----------

def link_back(tenders: list[dict], rows: list[dict]) -> int:
    """Add the reciprocal `related` entry to every Hilma row a new row points at; returns how many were added."""
    by_id = {t["id"]: t for t in tenders or [] if t.get("id")}
    added = 0
    for r in rows:
        for rel in r.get("related") or []:
            t = by_id.get(rel["id"])
            if not t:
                continue
            back = t.setdefault("related", [])
            if not any(x.get("id") == r["id"] for x in back):
                back.append(_rel(r))
                added += 1
    return added


def ennakointi_rows(settings, tenders: list[dict], hcfg=None) -> list[dict]:
    """All forward-looking rows; a failing builder is logged and skipped so the rest of the page still builds."""
    out = []
    for name, fn in (("ennusteet", lambda: forecast_rows(settings, tenders, hcfg)),
                     ("kalenterit", lambda: plan_rows(settings, tenders, hcfg)),
                     ("ted", lambda: ted_rows(settings, hcfg))):
        try:
            rows = fn()
        except Exception as e:  # noqa: BLE001
            log(f"warn: ennakointi: {name} ohitettu: {e}")
            continue
        log(f"ennakointi: {name}: {len(rows)} riviä")
        out.extend(rows)
    return out


if __name__ == "__main__":
    from common import OUT_DIR
    _settings = load_yaml(CONFIG_DIR / "settings.yaml")
    _tenders = load_json(OUT_DIR / "hankinnat.json", {}).get("items", [])
    for _r in ennakointi_rows(_settings, _tenders)[:3]:
        print(_r)
