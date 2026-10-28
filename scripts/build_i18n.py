"""Upottaa käyttöliittymän englanninkielisen sanakirjan (config/i18n/en.json) sivuun docs/index.html.

Sanakirja on sivun sisällä (<script id="i18n-en" type="application/json">), jotta kielivalinta toimii myös
yhden tiedoston tilannevedoksessa, joka ei hae tiedostoja verkosta. Avaimet ovat sivun suomenkielisiä
tekstejä tai niiden osia; luvut ja päivämäärät on korvattu paikkamerkeillä {n} ja {d} (ks. index.html:n i18n-js).

Käyttö: python scripts/build_i18n.py   (tarkistus: --check palauttaa virheen, jos sivun kopio on vanha)
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

R = pathlib.Path(__file__).resolve().parent.parent
SRC = R / "config" / "i18n" / "en.json"
PAGE = R / "docs" / "index.html"
BLOCK = re.compile(r'(<script id="i18n-en" type="application/json">)(.*?)(</script>)', re.S)


def payload() -> str:
    d = json.loads(SRC.read_text(encoding="utf-8"))
    # "</" must not appear inside the script element
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")


def main(check: bool = False) -> int:
    html = PAGE.read_text(encoding="utf-8")
    m = BLOCK.search(html)
    if not m:
        print("i18n: sivulta puuttuu <script id=\"i18n-en\">", file=sys.stderr)
        return 1
    new = payload()
    if m.group(2) == new:
        print("i18n: ajan tasalla")
        return 0
    if check:
        print("i18n: sivun sanakirja on vanha – aja python scripts/build_i18n.py", file=sys.stderr)
        return 1
    PAGE.write_text(html[:m.start(2)] + new + html[m.end(2):], encoding="utf-8")
    print(f"i18n: {len(json.loads(SRC.read_text(encoding='utf-8')))} käännöstä upotettu -> {PAGE}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
