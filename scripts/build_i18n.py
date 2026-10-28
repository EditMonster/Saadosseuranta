"""Upottaa käyttöliittymän sanakirjat (config/i18n/<kieli>.json: sv, en) sivuun docs/index.html.

Sanakirjat ovat sivun sisällä (<script id="i18n-<kieli>" type="application/json">), jotta kielivalinta toimii myös
yhden tiedoston tilannevedoksessa, joka ei hae tiedostoja verkosta. Avaimet ovat sivun suomenkielisiä tekstejä tai
niiden osia; luvut ja päivämäärät on korvattu paikkamerkeillä {n} ja {d} (ks. index.html:n i18n-js).

Käyttö: python scripts/build_i18n.py   (tarkistus: --check palauttaa virheen, jos sivun kopio on vanha)
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

R = pathlib.Path(__file__).resolve().parent.parent
DIR = R / "config" / "i18n"
PAGE = R / "docs" / "index.html"
LANGS = ("sv", "en")


def payload(lang: str) -> str:
    d = json.loads((DIR / f"{lang}.json").read_text(encoding="utf-8"))
    # "</" must not appear inside the script element
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")


def main(check: bool = False) -> int:
    html = PAGE.read_text(encoding="utf-8")
    changed = []
    for lang in LANGS:
        block = re.compile(rf'(<script id="i18n-{lang}" type="application/json">)(.*?)(</script>)', re.S)
        m = block.search(html)
        if not m:
            print(f"i18n: sivulta puuttuu <script id=\"i18n-{lang}\">", file=sys.stderr)
            return 1
        new = payload(lang)
        if m.group(2) != new:
            changed.append(lang)
            html = html[:m.start(2)] + new + html[m.end(2):]
    if not changed:
        print("i18n: ajan tasalla")
        return 0
    if check:
        print(f"i18n: sivun sanakirja on vanha ({', '.join(changed)}) – aja python scripts/build_i18n.py", file=sys.stderr)
        return 1
    PAGE.write_text(html, encoding="utf-8")
    print(f"i18n: upotettu {', '.join(changed)} -> {PAGE}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
