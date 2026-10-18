"""Run the whole pipeline: fetch sources (each tolerant of the others failing),
then build docs/data/items.json + hankinnat.json + yrityskaupat.json.

Every source's outcome is recorded in data/cache/health.json (consecutive failure streak,
last success, last error). build.py copies the summary into meta.json so the page can show
"Lähde ei päivity", and scripts/health_report.py turns a long streak into a GitHub issue."""
from __future__ import annotations

import datetime as dt
import sys
import traceback

import build
import fetch_avoimuus
import fetch_caselaw
import fetch_curia
import fetch_eduskunta
import fetch_eu
import fetch_eu_mergers
import fetch_finlex
import fetch_hankeikkuna
import fetch_hankinnat
import fetch_hys
import fetch_kkv
import fetch_kkv_valvonta
import fetch_mao
import fetch_paatokset
import fetch_regdel
import fetch_sopimuskaudet
import fetch_suunnitelmat
import fetch_ted
import fetch_toimiala
import fetch_toimittajat
import fetch_ue
import fetch_vaski
from common import CACHE_DIR, load_json, log, save_json

HEALTH = CACHE_DIR / "health.json"
STEPS = [
    ("hankeikkuna", fetch_hankeikkuna.main),
    ("eduskunta", fetch_eduskunta.main),
    ("vaski", fetch_vaski.main),
    ("finlex", fetch_finlex.main),
    ("eu", fetch_eu.main),
    ("ue", fetch_ue.main),
    ("hys", fetch_hys.main),
    ("hankinnat", fetch_hankinnat.main),
    ("sopimuskaudet", fetch_sopimuskaudet.main),
    ("suunnitelmat", fetch_suunnitelmat.main),
    ("ted", fetch_ted.main),
    ("paatokset", fetch_paatokset.main),
    ("toimittajat", fetch_toimittajat.main),
    ("kkv_valvonta", fetch_kkv_valvonta.main),
    ("kkv", fetch_kkv.main),
    ("eu_mergers", fetch_eu_mergers.main),
    ("regdel", fetch_regdel.main),
    ("mao", fetch_mao.main),
    ("avoimuus", fetch_avoimuus.main),
    ("caselaw", fetch_caselaw.main),
    ("curia", fetch_curia.main),
    ("toimiala", fetch_toimiala.main),
]


def main(only: list[str] | None = None) -> int:
    health = load_json(HEALTH, {})
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    failures = []
    for name, fn in STEPS:
        if only and name not in only:
            continue
        h = health.setdefault(name, {"streak": 0})
        try:
            fn()
            h.update({"ok": True, "streak": 0, "last_ok": now, "last_error": None})
        except Exception:  # noqa: BLE001
            failures.append(name)
            tb = traceback.format_exc()
            h.update({"ok": False, "streak": int(h.get("streak", 0)) + 1, "last_fail": now,
                      "last_error": (tb.strip().splitlines() or ["?"])[-1][:300]})
            log(f"ERROR in {name} (peräkkäisiä epäonnistumisia {h['streak']}):\n{tb}")
    save_json(HEALTH, health)
    build.main()
    if failures:
        log(f"valmis, mutta epäonnistuneet vaiheet: {failures} (vanha välimuisti käytössä)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
