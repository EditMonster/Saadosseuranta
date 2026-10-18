"""Rows for the enforcement side of procurement and competition – pure functions over the caches
written by fetch_paatokset, fetch_toimittajat and fetch_kkv_valvonta (no network):

* decision_rows()      – municipal procurement decisions (stage "paatos"): the appeal window is
                         14 days from service of the decision (hankintalaki 147 §); the date of
                         service is not public, so the window is shown as an estimate of
                         decision date + 7 + 14 days. Rows link to the Hilma notice (HEL/Cloudia
                         number, notice date or title match within the same buyer) and to a pending
                         Market Court appeal of the same buyer against a decision of the same date.
* attach_incumbents()  – the buyer's largest suppliers of the last 12 months (Tutkihankintoja) on
                         state-sector tender rows, preferring the category group of the tender.
* kkv_valvonta_rows()  – KKV's procurement supervision and Market Court proposals as stage "mao"
                         rows of hankinnat.json, and its restriction / commitment / neutrality
                         decisions as segment "kilpailunrajoitus" rows of yrityskaupat.json.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re

from common import CACHE_DIR, CONFIG_DIR, TODAY, load_json, load_yaml
from build_mao import classify_subject
from fetch_mao import norm
from fetch_toimittajat import match_buyer

SERVICE_DAYS = 7      # estimated days from decision to service by electronic means / letter
APPEAL_DAYS = 14      # hankintalaki 147 § 1 mom.
APPEAL_LABEL = "Hankintaoikaisu / valitus markkinaoikeuteen 14 pv tiedoksisaannista (arvio: tiedoksianto 7 pv)"
CITY = {"Helsinki": "Helsingin kaupunki", "Oulu": "Oulun kaupunki"}
STOP = {"hankinta", "hankinnan", "palvelut", "palvelujen", "palveluiden", "kaupunki", "kaupungin", "helsingin", "helsinki", "toimiala",
        "toimialan", "puitejärjestely", "puitejärjestelyyn", "kokonaisurakka", "urakka", "sekä", "siihen", "liittyvät", "kaupunginkanslia",
        "lisätyötilaus", "muutostyötilaus", "euroa", "päätös", "hankinnasta", "hankintaan", "osallistumishakemus", "osallistumishakemukset",
        "kilpailutus", "minikilpailutus", "optio", "option", "käyttöönotto", "vuosille", "ajalle", "dynaamiseen", "hankintajärjestelmään",
        "kaupunkiympäristön", "rakennukset", "yleiset", "alueet", "palvelu", "tavara", "hankkiminen", "hankintasopimus",
        "kulttuurin", "vapaa", "ajan", "toimialalle", "toimialalla", "sosiaali", "terveys", "pelastustoimiala", "pelastustoimialan", "kasvatuksen",
        "koulutuksen", "liikelaitos", "liikelaitoksen", "kaupunginkanslian", "kolmen", "kahden", "neljän", "viiden"}
GENERIC_SHARE = 0.015  # a token found in at least 3 (or this share of) the city's notices does not identify a procurement
# the state's own service providers bill agencies too; they are not competitors in a tender
INTERNAL = ("senaatti-kiinteistöt", "puolustuskiinteistöt", "valtion tieto- ja viestintätekniikk", "valtion talous- ja", "hansel oy",
            "haus kehittämiskeskus", "valtiokonttori", "palkeet", "kansaneläkelaitos", "valtori")
KIND_HANKINTA = {"hankintojen-valvonta": "KKV:n hankintojen valvonta", "esitykset-markkinaoikeudelle": "KKV:n esitys markkinaoikeudelle"}
KIND_KILPAILU = {"esitykset-markkinaoikeudelle": "Seuraamusmaksuesitys markkinaoikeudelle",
                 "kielto-sitoumus-tai-toimitusvelvoiteratkaisut": "Sitoumuspäätös",
                 "kilpailuneutraliteetti": "Kilpailuneutraliteetti"}
PROCUREMENT = re.compile(r"\bsuorahankin|\bhankintalai|\bhankintayksik|\bjulkis\w*\s+hankin|\bhankintamenettely|\btarjouskilpail|\bkilpailutta|14\.00\.60", re.I)


def is_city(name: str | None, city: str = "Helsinki") -> bool:
    low = (name or "").lower()
    if city == "Helsinki":
        return bool(re.search(r"helsingin kaupun|^helsinki\b|^helsingfors stad", low)) and not re.search(r"yliopisto|seudun|asunnot|asumisoikeus", low)
    if city == "Oulu":
        return bool(re.search(r"oulun kaupun|^oulu\b", low)) and "yliopisto" not in low
    return False


def tokens(text: str) -> set[str]:
    out = set()
    for w in re.sub(r"[^a-zåäö0-9]+", " ", (text or "").lower()).split():
        if len(w) >= 4 and w not in STOP and not w.isdigit():
            out.add(w[:6])
    return out


def overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _plus(iso: str, days: int) -> str:
    return (dt.date.fromisoformat(iso) + dt.timedelta(days=days)).isoformat()


def _related(row: dict, kind: str | None = None) -> dict:
    return {k: v for k, v in {"id": row["id"], "stage": row.get("stage", "avoin"), "kind": kind or row.get("kind"), "published": row.get("published")}.items() if v}


def decision_rows(settings: dict, tenders: list[dict], hcfg: dict, mao_rows: list[dict]) -> list[dict]:
    """Stage "paatos" rows from data/cache/paatokset.json; links are added to the matching tender and
    Market Court rows in place (as build_mao does)."""
    cache = load_json(CACHE_DIR / "paatokset.json", {}) or {}
    decisions = cache.get("decisions") or {}
    pcfg = settings.get("paatokset", {}) or {}
    keep_days = int(pcfg.get("keep_days", 60))
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    today = TODAY.isoformat()
    rows: list[dict] = []
    if not decisions:
        return rows

    city_tenders: dict[str, list[dict]] = {}
    city_mao: dict[str, list[dict]] = {}
    for city in CITY:
        city_tenders[city] = [t for t in tenders if t.get("stage") != "mao" and is_city(t.get("buyer"), city)]
        city_mao[city] = [m for m in mao_rows if str(m.get("id", "")).startswith("mao-v-") and is_city(m.get("buyer"), city)]
    tender_tokens = {t["id"]: tokens((t.get("title") or "") + " " + " ".join(t.get("lotTitles") or [])) for c in city_tenders.values() for t in c}
    generic: dict[str, set[str]] = {}
    for city, cands in city_tenders.items():
        df: dict[str, int] = {}
        for t in cands:
            for tok in tender_tokens.get(t["id"], ()):
                df[tok] = df.get(tok, 0) + 1
        generic[city] = {tok for tok, n in df.items() if n >= max(3, GENERIC_SHARE * len(cands))}
    per_day: dict[tuple[str, str], int] = {}
    for d in decisions.values():
        if d.get("date"):
            per_day[(d.get("city") or "Helsinki", d["date"])] = per_day.get((d.get("city") or "Helsinki", d["date"]), 0) + 1

    for did, d in decisions.items():
        date = d.get("date")
        if not date or date < cutoff:
            continue
        city = d.get("city") or "Helsinki"
        maker = d.get("maker") or ""
        buyer = f"{CITY.get(city, city)} – {maker}" if maker else CITY.get(city, city)
        served = d.get("served")
        appeal_end = _plus(served, APPEAL_DAYS) if served else _plus(date, SERVICE_DAYS + APPEAL_DAYS)
        # a page that carries MUUTOKSENHAKUKIELTO without the Market Court instructions leaves only the
        # hankintaoikaisu (if its instructions are there) – or nothing to appeal at all
        no_appeal = bool(d.get("muutoksenhakukielto")) and not d.get("valitusosoitus")
        if no_appeal and not d.get("oikaisuohje"):
            appeal_end = None
        status = "valitusaika" if appeal_end and appeal_end >= today else "päättynyt"
        winners = [w["name"] for w in d.get("winners") or []]
        losers = [w["name"] for w in d.get("losers") or []]
        title = d.get("title") or d.get("issueSubject") or did
        row = {
            "id": f"hk-pt-{did}", "scope": "hankinta", "laji": "kilpailutus", "stage": "paatos", "kind": "Hankintapäätös",
            "title": title[:220], "buyer": buyer[:160], "city": city, "decisionMaker": maker or None, "decisionUnit": d.get("makerUnit"),
            "decisionDate": date, "published": date, "section": f"§ {d['section']}" if d.get("section") else None,
            "issueId": d.get("issueId"), "issueSubject": d.get("issueSubject"), "decisionType": d.get("type"),
            "winner": "; ".join(winners)[:300] or None, "winners": winners[:12] or None, "losers": losers[:12] or None,
            "value": d.get("value"), "currency": "EUR" if d.get("value") else None,
            "status": status, "appealEnd": appeal_end, "served": served, "visible": d.get("visible"),
            "valitusosoitus": d.get("valitusosoitus"), "oikaisuohje": d.get("oikaisuohje"), "muutoksenhakukielto": d.get("muutoksenhakukielto"),
            "hilmaNo": d.get("hilmaNo"), "helRefs": d.get("helRefs"), "noticeDate": d.get("noticeDate"),
            "dps": d.get("dps"), "framework": d.get("framework"), "direct": d.get("category") == "Hankinta ilman kilpailutusta" or d.get("type") == "suorahankinta" or None,
            "summary": (d.get("summary") or "")[:500], "url": d.get("url"), "pdf": d.get("pdf"),
        }
        ev = []
        if d.get("noticeDate") and d["noticeDate"] <= date:
            ev.append({"date": d["noticeDate"], "label": "Hankintailmoitus julkaistu", "kind": "he"})
        ev.append({"date": date, "label": "Hankintapäätös", "kind": "muu"})
        if d.get("visible") and d["visible"] != date:
            ev.append({"date": d["visible"], "label": "Päätös tullut nähtäväksi", "kind": "julkaistu"})
        if appeal_end:
            label = APPEAL_LABEL
            if no_appeal:
                label = "Hankintaoikaisu 14 pv tiedoksisaannista (arvio: tiedoksianto 7 pv; ei valitusoikeutta markkinaoikeuteen)"
            if served:
                label = label.replace("(arvio: tiedoksianto 7 pv", f"(tiedoksianto alkaen {served}")
            ev.append({"date": appeal_end, "label": label, "kind": "maaraaika", "confirmed": False})

        # --- Hilma notice: number, notice date or title match within the same buyer ---
        cands = city_tenders.get(city) or []
        refs = {r for r in (d.get("helRefs") or [])} | ({d["issueId"]} if d.get("issueId") else set())
        refs_norm = {r.replace(" ", "").lower() for r in refs} | {f"hel{r[4:]}".replace(" ", "").lower() for r in refs if r.startswith("HEL ")}
        num = d.get("hilmaNo")
        mine = tokens(title + " " + (d.get("issueSubject") or ""))
        scored: list[tuple[int, float, dict]] = []
        for t in cands:
            text = ((t.get("title") or "") + " " + (t.get("summary") or "") + " " + (t.get("noticeNumber") or "")).lower()
            flat = text.replace(" ", "")
            if (refs_norm and any(r in flat for r in refs_norm)) or (num and num in text):
                scored.append((3, 1.0, t))
                continue
            theirs = tender_tokens.get(t["id"], set())
            ov = overlap(mine, theirs)
            distinctive = (mine & theirs) - generic.get(city, set())
            if ov >= 0.6 and len(mine & theirs) >= 2 and distinctive:
                scored.append((2, ov, t))
            elif d.get("noticeDate") and (t.get("published") or "")[:10] == d["noticeDate"] and ov >= 0.3 and distinctive:
                scored.append((1, ov, t))
        scored.sort(key=lambda x: (-x[0], -x[1], x[2].get("published") or ""))
        related = []
        linked_topics: list[str] = []
        for _, _, t in scored[:3]:
            related.append(_related(t))
            t.setdefault("related", []).append(_related(row, "Hankintapäätös"))
            for tp in t.get("topics") or []:
                if tp not in linked_topics:
                    linked_topics.append(tp)

        # --- Market Court: a pending appeal of the same buyer against a decision of this date; a city makes
        # several procurement decisions a day, so the appeal's description must also name the subject or the
        # section number unless this is the only decision of the day ---
        for m in city_mao.get(city) or []:
            m_dates = {m.get("decisionDate")} | {e["date"] for e in m.get("events") or [] if e.get("label") == "Hankintapäätös"}
            if date not in m_dates:
                continue
            m_text = (m.get("decisionText") or "") + " " + (m.get("title") or "")
            same_section = bool(d.get("section")) and re.search(rf"(?<!\d){d['section']}\s*§", m_text) is not None
            if same_section or overlap(mine, tokens(m_text)) >= 0.3 or per_day.get((city, date), 1) == 1:
                related.append(_related(m))
                m.setdefault("related", []).append(_related(row, "Hankintapäätös"))
                row["appealed"] = True
                if m.get("filed"):
                    ev.append({"date": m["filed"], "label": "Valitus vireille markkinaoikeudessa", "kind": "julkaistu"})
        ev.sort(key=lambda e: (e["date"], e["label"]))
        row["events"] = ev
        if related:
            row["related"] = related
        own = classify_subject(" ".join(x for x in (d.get("issueSubject"), title, d.get("summary")) if x), hcfg)
        row["topics"] = linked_topics[:3] if linked_topics and linked_topics != ["Muut"] else own
        rows.append({k: v for k, v in row.items() if v not in (None, "", [], {}, False)})
    rows.sort(key=lambda r: (r["decisionDate"], r["id"]), reverse=True)
    return rows


def _groups_for(topics: list[str], group_map: dict[str, list[str]]) -> list[str]:
    out = []
    for tp in topics or []:
        for g in group_map.get(tp) or []:
            if g not in out:
                out.append(g)
    return out


def attach_incumbents(tenders: list[dict], settings: dict | None = None) -> None:
    """Set `incumbents` [{name, sum, year, category}] on tender rows whose buyer is in the Tutkihankintoja
    cache: the top vendors of the tender's category group when fetched, else the overall top 5."""
    cache = load_json(CACHE_DIR / "toimittajat.json", {}) or {}
    buyers = cache.get("buyers") or {}
    if not buyers:
        return
    agencies = {n.lower() for n in (cache.get("index") or {}).get("names") or []}

    def external(v: dict) -> bool:
        low = (v.get("name") or "").lower()
        return low not in agencies and not low.startswith(INTERNAL)
    settings = settings if settings is not None else (load_yaml(CONFIG_DIR / "settings.yaml") or {})
    group_map = (settings.get("toimittajat", {}) or {}).get("kategoriat") or {}
    # match by the Hilma spelling the fetcher saw (cache key) or by the backend's own name
    index: dict[str, dict] = {}
    for k, v in buyers.items():
        entry = {"id": v.get("id"), "name": v.get("name"), "branch": v.get("branch") or "sub", "key": k}
        index.setdefault(k, entry)
        for name in [v.get("name")] + list(v.get("hilmaNames") or []):
            if name:
                index.setdefault(norm(name), entry)
    memo: dict[str, dict | None] = {}
    for t in tenders:
        if t.get("stage") not in ("avoin", "ratkaistu", "tulossa", "suorahankinta") or not t.get("buyer"):
            continue
        key = norm(t["buyer"])
        if key not in memo:
            hit = buyers.get(key)
            if hit is None:
                m = match_buyer(t["buyer"], index)
                hit = buyers.get(m["key"]) if m else None
            memo[key] = hit
        b = memo[key]
        if not b or not b.get("top"):
            continue
        period = b.get("period") or {}
        year = f"{(period.get('from') or '')[:4]}–{(period.get('to') or '')[:4]}".strip("–") or (b.get("fetched") or "")[:4]
        picked: list[dict] = []
        for g in _groups_for(t.get("topics") or [], group_map):
            picked = [v for v in b["top"] if v.get("category") == g and external(v)]
            if picked:
                break
        if not picked:
            picked = [v for v in b["top"] if not v.get("category") and external(v)][:5]
        if picked:
            t["incumbents"] = [{k: v for k, v in {"name": v["name"], "sum": v.get("sum"), "year": year, "category": v.get("category"), "yTunnus": v.get("yTunnus")}.items() if v is not None} for v in picked]
            t["incumbentsBuyer"] = b.get("name")


def _slug_id(prefix: str, c: dict, key: str) -> str:
    slug = c.get("slug") or re.sub(r"[^a-z0-9]+", "-", (c.get("diaari") or key).lower()).strip("-")
    if len(slug) > 80:
        slug = slug[:72].rstrip("-") + "-" + hashlib.sha1(slug.encode()).hexdigest()[:6]
    return f"{prefix}-{slug}"


def kkv_valvonta_rows(settings: dict, hcfg: dict | None = None) -> dict:
    """{"hankinta": [stage "mao" rows], "kilpailu": [segment "kilpailunrajoitus" rows]} from data/cache/kkv_valvonta.json."""
    cache = load_json(CACHE_DIR / "kkv_valvonta.json", {}) or {}
    cases = cache.get("cases") or {}
    kcfg = settings.get("kkv_valvonta", {}) or {}
    keep_days = int(kcfg.get("keep_days", 180))
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    hcfg = hcfg if hcfg is not None else (load_yaml(CONFIG_DIR / "hankinnat.yaml") or {})
    out = {"hankinta": [], "kilpailu": []}
    for key, c in cases.items():
        date = c.get("date") or c.get("listDate")
        if not date or date < cutoff:
            continue
        cat = c.get("category")
        outcome = c.get("outcome") or "päätös"
        text = " ".join(x for x in (c.get("title"), c.get("summary"), c.get("parties"), c.get("diaari")) if x)
        esitys = outcome == "esitys markkinaoikeudelle" or cat == "esitykset-markkinaoikeudelle"
        # a proposal concerns procurement when KKV filed it under the procurement-supervision task code or the
        # text speaks of the procurement act (party names such as "Marjahankinta Oy" must not count)
        procurement = cat == "hankintojen-valvonta" or (cat == "esitykset-markkinaoikeudelle" and bool(
            PROCUREMENT.search(" ".join(x for x in (c.get("title"), c.get("summary"), c.get("diaari")) if x))))
        if procurement:
            kind = KIND_HANKINTA["esitykset-markkinaoikeudelle"] if esitys else KIND_HANKINTA["hankintojen-valvonta"]
            status = "esitys markkinaoikeudessa" if esitys else "päätetty"
            label = ("KKV:n esitys markkinaoikeudelle – " + ("seuraamusmaksu" if "seuraamusmaksu" in text.lower() else "seuraamus")) if esitys else f"KKV:n päätös – {outcome}"
            ev = [{"date": date, "label": label, "kind": "vahvistettu" if esitys else "muu"}]
            row = {
                "id": _slug_id("hk-kkv", c, key), "scope": "hankinta", "laji": "kilpailutus", "stage": "mao", "kind": kind,
                "title": (c.get("title") or key)[:200], "buyer": c.get("buyer") or c.get("parties"), "parties": c.get("parties"),
                "diaari": c.get("diaari"), "published": date, "decided": date, "status": status, "outcome": outcome,
                "nextStep": "Markkinaoikeuden ratkaisu (ei määräaikaa laissa)" if esitys else None,
                "topics": classify_subject(text, hcfg), "summary": (c.get("summary") or "")[:600], "url": c.get("url"), "eu": None, "events": ev,
            }
            out["hankinta"].append({k: v for k, v in row.items() if v not in (None, "", [], {})})
            continue
        if cat not in KIND_KILPAILU:
            continue
        kind = KIND_KILPAILU[cat]
        if cat == "kielto-sitoumus-tai-toimitusvelvoiteratkaisut" and outcome in ("kielto", "toimitusvelvoite"):
            kind = "Kilpailunrajoitus – päätös"
        if esitys:
            status = "esitys markkinaoikeudessa"
        elif outcome == "sitoumukset":
            status = "sitoumukset"
        else:
            status = "päätetty"
        label = "KKV:n seuraamusmaksuesitys markkinaoikeudelle" if esitys else f"KKV:n päätös – {outcome}"
        ev = [{"date": date, "label": label, "kind": "vahvistettu" if esitys else "muu"}]
        row = {
            "id": _slug_id("kr-kkv", c, key), "scope": "yrityskauppa", "laji": "kilpailunrajoitus", "segment": "kilpailunrajoitus", "authority": "KKV",
            "kind": kind, "title": (c.get("title") or key)[:200], "fullTitle": c.get("title"), "parties": c.get("parties"), "ref": c.get("diaari") or c.get("slug"),
            "status": status, "done": status != "esitys markkinaoikeudessa", "published": date, "decided": date, "outcome": outcome,
            "nextStep": "Markkinaoikeuden ratkaisu (ei määräaikaa laissa)" if esitys else None,
            "topics": ["Kansallinen (KKV)"], "summary": (c.get("summary") or "")[:600], "fiParty": True,
            "ministry": "Kilpailu- ja kuluttajavirasto · " + ("kilpailulaki 12 § – seuraamusmaksuesitys" if esitys else ("kilpailulaki 10 § – sitoumukset" if outcome == "sitoumukset"
                        else ("kilpailulaki 30 a § – kilpailuneutraliteetti" if cat == "kilpailuneutraliteetti" else "kilpailulaki 9 §"))),
            "source": c.get("url"), "url": c.get("url"), "links": {"kkv": c.get("url")}, "events": ev, "updated": c.get("seen"),
        }
        out["kilpailu"].append({k: v for k, v in row.items() if v not in (None, "", [], {})})
    for rows in out.values():
        rows.sort(key=lambda r: (r.get("published") or "", r["id"]), reverse=True)
    return out


if __name__ == "__main__":
    settings = load_yaml(CONFIG_DIR / "settings.yaml")
    hcfg = load_yaml(CONFIG_DIR / "hankinnat.yaml") or {}
    rows = decision_rows(settings, [], hcfg, [])
    print(len(rows), "hankintapäätöstä")
    for r in rows[:3]:
        print(r["id"], r["status"], r["title"][:60], "|", r.get("winner"), r.get("value"), r["topics"])
    kv = kkv_valvonta_rows(settings, hcfg)
    print(len(kv["hankinta"]), "KKV hankinta,", len(kv["kilpailu"]), "KKV kilpailu")
