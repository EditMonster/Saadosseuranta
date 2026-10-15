"""European Commission "Have your say": public consultations and feedback periods on
initiatives (calls for evidence, consultations, feedback on adopted proposals and on
draft delegated/implementing acts). Newest first; a few pages cover everything that is
open or recently closed."""
from __future__ import annotations

import datetime as dt

from common import CACHE_DIR, CONFIG_DIR, TODAY, get_json, load_yaml, log, save_json

API = "https://ec.europa.eu/info/law/better-regulation/brpapi/searchInitiatives"
OUT = CACHE_DIR / "hys.json"
ACT_TYPES = {
    "PROP_REG": "Asetusehdotus", "PROP_DIR": "Direktiiviehdotus", "PROP_DEC": "Päätösehdotus", "REG": "Asetus",
    "DIR": "Direktiivi", "DEC": "Päätös", "REG_DEL": "Delegoitu asetus", "REG_IMPL": "Täytäntöönpanoasetus",
    "DIR_DEL": "Delegoitu direktiivi", "DIR_IMPL": "Täytäntöönpanodirektiivi", "DEC_IMPL": "Täytäntöönpanopäätös",
    "DEC_DEL": "Delegoitu päätös", "COMMUNIC": "Tiedonanto", "REPORT": "Kertomus", "RECOMM": "Suositus",
    "GUIDELINES": "Suuntaviivat", "STRATEGY": "Strategia", "ACTION_PLAN": "Toimintasuunnitelma",
}
STAGES = {
    "CALL_FOR_EVIDENCE": "Kannanottopyyntö (call for evidence)", "PUBLIC_CONSULTATION": "Julkinen kuuleminen",
    "ADOPTION_WORKFLOW": "Palaute hyväksytystä ehdotuksesta", "DRAFT_ACT": "Palaute säädösluonnoksesta",
    "ISC_WORKFLOW": "Palaute säädösluonnoksesta", "DELEGATED_ACT": "Palaute delegoidusta säädöksestä",
}


def _d(s: str | None) -> str | None:
    return s[:10].replace("/", "-") if s else None


def main():
    settings = load_yaml(CONFIG_DIR / "settings.yaml")
    pages = settings.get("hys", {}).get("pages", 6)
    keep_closed_days = settings.get("hys", {}).get("keep_closed_days", 60)
    cutoff = (TODAY - dt.timedelta(days=keep_closed_days)).isoformat()
    items, seen = [], set()
    for page in range(pages):
        try:
            data = get_json(API, params={"size": 100, "page": page}, timeout=90)
        except Exception as e:  # noqa: BLE001
            log(f"warn: have your say page {page}: {e}")
            break
        content = (data.get("initiativeResultDtoPage") or {}).get("content") or []
        if not content:
            break
        for c in content:
            iid = int(c.get("id") or 0)
            if not iid or iid in seen:
                continue
            seen.add(iid)
            periods = []
            for s in c.get("currentStatuses") or []:
                st, en = _d(s.get("feedbackStartDate")), _d(s.get("feedbackEndDate"))
                if st and en:
                    periods.append({"stage": s.get("frontEndStage"), "start": st, "end": en,
                                    "open": s.get("receivingFeedbackStatus") == "OPEN"})
            if not periods:
                continue
            if not any(p["open"] or p["end"] >= cutoff or p["start"] >= TODAY.isoformat() for p in periods):
                continue
            title_fi = next((t["value"] for t in c.get("initiativeTranslations") or [] if t.get("language") == "FI" and t.get("field") == "SHORT_TITLE"), None)
            items.append({
                "id": iid, "title_fi": title_fi, "title_en": c.get("shortTitle"), "reference": c.get("reference"),
                "actType": c.get("foreseenActType"), "actTypeLabel": ACT_TYPES.get(c.get("foreseenActType"), c.get("foreseenActType") or ""),
                "status": c.get("initiativeStatus"), "periods": sorted(periods, key=lambda p: p["start"]),
                "url": f"https://ec.europa.eu/info/law/better-regulation/have-your-say/initiatives/{iid}_en",
            })
    save_json(OUT, {"fetched": dt.datetime.now().isoformat(timespec="seconds"), "items": items})
    log(f"have your say: {len(items)} aloitetta (avoin tai päättynyt ≤ {keep_closed_days} pv) -> {OUT}")


if __name__ == "__main__":
    main()
