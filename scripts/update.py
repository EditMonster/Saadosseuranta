"""Run the whole pipeline: fetch sources (each tolerant of the others failing),
then build docs/data/items.json."""
from __future__ import annotations

import sys
import traceback

import build
import fetch_eduskunta
import fetch_eu
import fetch_finlex
import fetch_hankeikkuna
import fetch_hys
import fetch_ue
from common import log

STEPS = [
    ("hankeikkuna", fetch_hankeikkuna.main),
    ("eduskunta", fetch_eduskunta.main),
    ("finlex", fetch_finlex.main),
    ("eu", fetch_eu.main),
    ("ue", fetch_ue.main),
    ("hys", fetch_hys.main),
]


def main(only: list[str] | None = None) -> int:
    failures = []
    for name, fn in STEPS:
        if only and name not in only:
            continue
        try:
            fn()
        except Exception:  # noqa: BLE001
            failures.append(name)
            log(f"ERROR in {name}:\n{traceback.format_exc()}")
    build.main()
    if failures:
        log(f"valmis, mutta epäonnistuneet vaiheet: {failures} (vanha välimuisti käytössä)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
