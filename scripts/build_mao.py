"""Market Court procurement appeals and rulings as rows of the Kilpailutukset segment (stage "mao").

One row per pending appeal (from the court's statutory list) and per ruling of the last keep_days; a
ruling matched to a pending entry merges into that entry's row. Rulings are linked to the Hilma notice
they concern when the contracting entity matches and the notice date quoted in the ruling equals the
Hilma publication date; pending entries only when the list quotes a Hilma/Cloudia competition number
found in the notice text.

Appeal to the Supreme Administrative Court needs leave to appeal and must be lodged within 30 days of
service of the ruling (hankintalaki 165 §, laki oikeudenkäynnistä hallintoasioissa 13 §). The date of
service is not public, so the end of that period is shown as an estimate from the ruling date.
"""
from __future__ import annotations

import datetime as dt
import re

from common import CACHE_DIR, CONFIG_DIR, TODAY, load_json, load_yaml
from maaraajat import fi_deadline, shifted_note_fi
from fetch_mao import PENDING, norm

OUTCOME_KIND = {"valitus hylätty": "hyvaksytty", "jätetty tutkimatta": "hyvaksytty", "rauennut": "muu", "poistettu käsittelystä": "muu"}


def subject(text: str, buyer: str) -> str:
    """'Lahden kaupungin tietohallintojohtajan päätös 2.10.2026, 24/2026, kameravalvonta…' -> 'kameravalvonta…'."""
    t = text or ""
    m = re.search(r"\d{1,2}\.\d{1,2}\.\d{4,5}\s*,?\s*", t)
    if m:
        rest = t[m.end():]
        rest = re.sub(r"^(?:§\s*\d+[^,]*,\s*|\d+\s*/\s*\d{4}\s*,\s*|[A-ZÄÖ]+/\d+[^,]*,\s*|\d{3,6}\s*,\s*|nro\s*\d+[^,]*,\s*)+", "", rest).strip(" ,;")
        if len(rest) >= 12:
            t = rest
    t = re.sub(r"\s+", " ", t).strip()
    return (t[:1].upper() + t[1:]) if t else (text or buyer)


def classify_subject(text: str, cfg: dict) -> list[str]:
    low = (text or "").lower()
    out = [name for name, kws in (cfg.get("mao_toimialat") or {}).items() if any(k in low for k in kws)]
    return out[:3] or ["Muut"]


def mao_rows(settings: dict, tenders: list[dict], hcfg: dict) -> list[dict]:
    cache = load_json(CACHE_DIR / "mao.json", {}) or {}
    mcfg = settings.get("markkinaoikeus", {})
    keep_days = int(mcfg.get("keep_days", 90))
    kho_days = int(mcfg.get("kho_valitusaika_paivia", 30))
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    pending = cache.get("pending") or {}
    decisions = cache.get("decisions") or {}
    by_buyer: dict[str, list[dict]] = {}
    for t in tenders:
        if t.get("buyer"):
            by_buyer.setdefault(norm(t["buyer"]), []).append(t)

    def hilma_by_notice(buyer: str, notice_date: str | None) -> list[dict]:
        if not notice_date:
            return []
        return [t for t in by_buyer.get(norm(buyer), []) if (t.get("published") or "")[:10] == notice_date]

    def hilma_by_number(buyer: str, num: str | None) -> list[dict]:
        if not num:
            return []
        return [t for t in by_buyer.get(norm(buyer), []) if num in (t.get("title", "") + " " + t.get("summary", ""))]

    def ruling_events(d: dict) -> list[dict]:
        ev = []
        if d.get("noticeDate"):
            ev.append({"date": d["noticeDate"], "label": "Hankintailmoitus julkaistu", "kind": "he"})
        for cd in d.get("contestedDates") or []:
            ev.append({"date": cd, "label": "Hankintapäätös", "kind": "muu"})
        if d.get("date"):
            ev.append({"date": d["date"], "label": f"Markkinaoikeuden ratkaisu {d.get('number') or ''} – {d.get('outcome') or 'ratkaistu'}".strip(),
                       "kind": OUTCOME_KIND.get(d.get("outcome") or "", "vahvistettu")})
            # 30 days from service (hankintalaki 165 §, laki oikeudenkäynnistä hallintoasioissa 13 §); service is not public,
            # so count from the date of the ruling = the earliest possible end, shifted per 150/1930 5 §
            res = fi_deadline(d["date"], days=kho_days)
            ev.append({"date": res["date"],
                       "label": f"Valitusaika KHO:een päättyy aikaisintaan (arvio: {kho_days} pv tiedoksisaannista, laskettu antopäivästä; "
                                f"postitse tiedoksianto 7. päivänä lähettämisestä; valituslupa){shifted_note_fi(res)}",
                       "kind": "maaraaika", "confirmed": False})
        return ev

    def link(row: dict, matches: list[dict], kind: str):
        rel = []
        for t in matches[:3]:
            rel.append({"id": t["id"], "stage": t.get("stage", "avoin"), "kind": t.get("kind"), "published": t.get("published")})
            t.setdefault("related", []).append({"id": row["id"], "stage": "mao", "kind": kind, "published": row.get("published")})
        if rel:
            row["related"] = rel

    rows: list[dict] = []
    used = set()
    for key, p in pending.items():
        d = decisions.get(p.get("decision") or "")
        if d:
            used.add(d["number"])
        gone = p.get("missingSince")
        if not d and gone and gone < cutoff:
            continue
        status = "ratkaistu" if d else ("poistunut" if gone else "vireillä")
        title = subject(p.get("decisionText") or "", p["buyer"])
        row = {
            "id": f"mao-v-{key}", "scope": "hankinta", "laji": "kilpailutus", "stage": "mao",
            "kind": "Markkinaoikeuden ratkaisu" if d else "Valitus markkinaoikeudessa", "title": title[:200], "buyer": p["buyer"],
            "published": p["filed"], "filed": p["filed"], "decisionDate": p.get("decisionDate"), "decisionText": p.get("decisionText"),
            "status": status, "topics": classify_subject(p.get("decisionText") or "", hcfg),
            "summary": p.get("decisionText") or "", "url": PENDING, "eu": None,
        }
        ev = []
        if p.get("decisionDate"):
            ev.append({"date": p["decisionDate"], "label": "Hankintapäätös", "kind": "muu"})
        ev.append({"date": p["filed"], "label": "Valitus vireille markkinaoikeudessa", "kind": "julkaistu"})
        if d:
            row.update({"appellant": d.get("appellant"), "maoNumber": d.get("number"), "diaari": d.get("diaari"), "keywords": d.get("keywords"),
                        "outcome": d.get("outcome"), "outcomeText": d.get("outcomeText"), "ruled": d.get("date"), "maoUrl": d.get("url"),
                        "value": d.get("value"), "currency": "EUR" if d.get("value") else None, "noticeDate": d.get("noticeDate")})
            row["summary"] = (d.get("background") or row["summary"])[:600]
            ev += [e for e in ruling_events(d) if e["label"] != "Hankintapäätös" or not p.get("decisionDate")]
            if gone is None and d.get("date"):
                pass
        elif gone:
            ev.append({"date": gone, "label": "Poistunut vireillä olevien luettelosta (ratkaistu, peruttu tai siirretty)", "kind": "muu"})
        ev.sort(key=lambda e: (e["date"], e["label"]))
        row["events"] = ev
        link(row, hilma_by_number(p["buyer"], p.get("hilmaNo")) or (hilma_by_notice(p["buyer"], d.get("noticeDate")) if d else []), row["kind"])
        rows.append(row)

    for num, d in decisions.items():
        if num in used or d.get("category") != "hankinta" or (d.get("date") or "") < cutoff:
            continue
        row = {
            "id": f"mao-r-{num.replace('MAO:', '').replace('/', '-')}", "scope": "hankinta", "laji": "kilpailutus", "stage": "mao",
            "kind": "Markkinaoikeuden ratkaisu", "title": (d.get("appellant") or "Valittaja") + " ▸ " + (d.get("respondent") or ""),
            "buyer": d.get("respondent"), "appellant": d.get("appellant"), "published": d.get("date"), "ruled": d.get("date"),
            "maoNumber": num, "diaari": d.get("diaari"), "keywords": d.get("keywords"), "outcome": d.get("outcome"), "outcomeText": d.get("outcomeText"),
            "noticeDate": d.get("noticeDate"), "decisionDate": (d.get("contestedDates") or [None])[-1], "value": d.get("value"), "currency": "EUR" if d.get("value") else None,
            "status": "ratkaistu", "topics": classify_subject((d.get("keywords") or "") + " " + (d.get("background") or ""), hcfg),
            "summary": (d.get("background") or "")[:600], "url": d.get("url"), "maoUrl": d.get("url"), "eu": None,
        }
        row["events"] = sorted(ruling_events(d), key=lambda e: (e["date"], e["label"]))
        link(row, hilma_by_notice(d.get("respondent") or "", d.get("noticeDate")), row["kind"])
        rows.append(row)

    for r in rows:
        r = {k: v for k, v in r.items() if v not in (None, "", [], {})}
    return [{k: v for k, v in r.items() if v not in (None, "", [], {})} for r in rows]


if __name__ == "__main__":
    settings = load_yaml(CONFIG_DIR / "settings.yaml")
    hcfg = load_yaml(CONFIG_DIR / "hankinnat.yaml") or {}
    rows = mao_rows(settings, [], hcfg)
    print(len(rows), "rows;", sum(1 for r in rows if r["status"] == "vireillä"), "vireillä")
    for r in rows[:3]:
        print(r["id"], r["status"], r["title"][:70], r["buyer"], r["topics"], [e["label"][:30] for e in r["events"]])
