"""Content in the reader's language: titles and summaries of laws, EU matters and tenders in FI, SV, EN, ET and LT.

Runs after build.py. For every item and every page language it picks, in order:
  1. the original, when the text already is in that language;
  2. an official translation (Projektfönstret's Swedish names of Finnish projects; the European Parliament's
     titles of EU procedures in English, Swedish, Estonian and Lithuanian);
  3. a machine translation with open OPUS-MT models (scripts/mt.py) – free, no API keys – marked as such.

Machine translations are cached by text (data/cache/kaannokset/<xx>.json, sharded so a run rewrites little), so each text is translated once; the first
fill is spread over several runs by a time budget (TRANSLATE_BUDGET_S, default 480 s): open matters and open
tenders first. Output: docs/data/tr/<lang>.json = {"items": {id: {"t": title, "f": full title, "s": summary,
"o": original language, "m": 1 if machine-translated}}}. The page loads only the file of the chosen language and
can always show the originals.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import time

from common import CACHE_DIR, OUT_DIR, load_json, log, save_json

LANGS = ("fi", "sv", "en", "et", "lt")
CACHE = CACHE_DIR / "kaannokset"  # 256 shards by hash prefix: a run rewrites only the shards it touched
TR_DIR = OUT_DIR / "tr"
COUNTRY_LANGS = {"FI": ("fi", "sv", "en"), "SE": ("sv", "en"), "NO": ("nb", "en"), "DK": ("da", "en"), "IS": ("en",),
                 "EE": ("et", "en"), "LV": ("lv", "en"), "LT": ("lt", "en")}
FIELDS = (("t", "title"), ("f", "fullTitle"), ("s", "summary"))
MAX_LEN = 700  # summaries are short; anything longer is cut at a sentence boundary before translating


def _key(src: str, text: str) -> str:
    return src + "|" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _shard(key: str) -> str:
    return key.split("|", 1)[1][:2]


def _clip(text: str) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= MAX_LEN:
        return text
    cut = text[:MAX_LEN]
    dot = cut.rfind(". ")
    return cut[: dot + 1] if dot > MAX_LEN // 2 else cut.rstrip() + " …"


def _official(it: dict, lang: str) -> dict:
    """Official translations carried by the item itself."""
    if it.get("scope") == "fi" and lang == "sv":
        return {"t": it.get("titleSv"), "f": it.get("fullTitleSv")}
    if it.get("scope") == "eu":
        t = it.get({"en": "titleEn", "sv": "titleSv", "et": "titleEt", "lt": "titleLt"}.get(lang, "-"))
        return {"t": (t or "")[:160] or None, "f": t} if t else {}
    return {}


def _allowed(it: dict) -> tuple[str, ...]:
    if it.get("scope") == "hankinta":
        return COUNTRY_LANGS.get(it.get("country") or "FI", ("fi", "sv", "en"))
    if it.get("scope") == "eu":
        return ("fi", "en", "sv")
    return ("fi", "sv")


def collect(items: list[dict], tenders: list[dict]):
    """(id, field, text, src) for every text shown on the page, open matters and open tenders first."""
    from mt import detect, english_half
    rows = []
    def prio(it):
        if it.get("scope") == "hankinta":
            return 1 if it.get("stage") in ("avoin", "tulossa") else 3
        return 0 if not it.get("done") else 2
    for it in sorted(items + tenders, key=prio):
        allowed = _allowed(it)
        for short, field in FIELDS:
            if it.get("scope") == "hankinta" and short == "f":
                continue
            text = _clip(it.get(field))
            if not text or (short == "f" and text == _clip(it.get("title"))):
                continue
            src = detect(text, allowed)
            mt_src, mt_text = src, text
            if it.get("scope") == "hankinta" and src != "en":
                half = english_half(text)
                if half:
                    mt_src, mt_text = "en", half
            rows.append({"id": it["id"], "f": short, "text": text, "src": src, "mt_src": mt_src, "mt_text": mt_text})
    return rows


def main(budget_s: float | None = None) -> None:
    from mt import Engine
    t0 = time.time()
    budget = float(os.environ.get("TRANSLATE_BUDGET_S", "480") if budget_s is None else budget_s)
    items = [i for i in (load_json(OUT_DIR / "items.json", {"items": []}).get("items") or []) if i.get("scope") in ("fi", "eu")]
    tenders = load_json(OUT_DIR / "hankinnat.json", {"items": []}).get("items") or []
    by_id = {i["id"]: i for i in items + tenders}
    rows = collect(items, tenders)
    cache: dict[str, dict] = {}
    for f in sorted(CACHE.glob("*.json")):
        cache.update((load_json(f, {}) or {}).get("t") or {})
    before = {k: dict(v) for k, v in cache.items()}
    eng = Engine()
    used: set[str] = set()

    # which machine translations are still missing (a text is translated to English once, then to each target)
    need = []
    for r in rows:
        k = _key(r["mt_src"], r["mt_text"])
        used.add(k)
        r["k"] = k
        targets = [l for l in LANGS if l != r["src"] and not (_official(by_id[r["id"]], l).get(r["f"]))]
        missing = [l for l in targets if l not in cache.get(k, {})]
        if missing:
            need.append((r, missing))
    done_n = 0
    if eng.available and need:
        CHUNK = 48
        for i in range(0, len(need), CHUNK):
            if time.time() - t0 > budget:
                break
            chunk = need[i:i + CHUNK]
            by_src: dict[str, list] = {}
            for r, missing in chunk:
                by_src.setdefault(r["mt_src"], []).append((r, missing))
            try:
                for src, group in by_src.items():
                    # English pivot (cached as "en" – also the English result)
                    piv_todo = [(r, m) for r, m in group if "en" not in cache.get(r["k"], {})]
                    if piv_todo:
                        out = eng.to_english([r["mt_text"] for r, _ in piv_todo], src)
                        for (r, _), en in zip(piv_todo, out):
                            cache.setdefault(r["k"], {})["en"] = en
                    for tgt in ("fi", "sv", "et", "lt"):
                        todo = [r for r, m in group if tgt in m and tgt not in cache.get(r["k"], {}) and tgt != src]
                        if not todo:
                            continue
                        out = eng.from_english([cache[r["k"]]["en"] for r in todo], tgt)
                        for r, t in zip(todo, out):
                            cache[r["k"]][tgt] = t
                done_n += len(chunk)
            except Exception as e:  # noqa: BLE001 – a missing model must not stop the run
                log(f"translate: konekäännös keskeytyi ({e})")
                break

    # page files: per language, only items whose text is not already in that language
    gen = dt.datetime.now().isoformat(timespec="seconds")
    stats = {}
    for lang in LANGS:
        out: dict[str, dict] = {}
        for r in rows:
            it = by_id[r["id"]]
            if r["src"] == lang:
                continue
            off = _official(it, lang).get(r["f"])
            val, machine = (off, False) if off else (cache.get(r["k"], {}).get(lang), True)
            if not val or val == r["text"]:
                continue
            e = out.setdefault(r["id"], {"o": r["src"]})
            e[r["f"]] = val
            if machine:
                e["m"] = 1
        save_json(TR_DIR / f"{lang}.json", {"generated": gen, "lang": lang, "items": out}, compact=True)
        stats[lang] = len(out)
    pending = sum(1 for r, m in need if any(l not in cache.get(r["k"], {}) for l in m))
    shards: dict[str, dict] = {}
    for k, v in cache.items():
        if k in used:
            shards.setdefault(_shard(k), {})[k] = v
    for sh in {_shard(k) for k in set(cache) | set(before)}:
        old = {k: v for k, v in before.items() if _shard(k) == sh}
        new = shards.get(sh, {})
        if new != old:
            if new:
                save_json(CACHE / f"{sh}.json", {"t": new}, compact=True)
            else:
                (CACHE / f"{sh}.json").unlink(missing_ok=True)
    log(f"translate: {len(rows)} tekstiä, konekäännetty tässä ajossa {done_n}, odottaa {pending}, "
        f"kohteita per kieli {stats} ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    import sys
    main(float(sys.argv[1]) if len(sys.argv) > 1 else None)
