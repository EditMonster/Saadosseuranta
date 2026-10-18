"""HE-diff page data: word-level diffs of the law text per HE, from data/cache/hediff.json
(collected by fetch_hediff.py) into docs/data/diff/<item id>.json. Pure: no network.

One file per HE (≤ 150 kB):
  {"id": "fi-he-118-2026", "he": "118/2026", "generated": "2026-10-18",
   "steps": [
     {"kind": "he", "label": "Voimassa oleva → HE", "laws": [{"name", "kind": muutos|uusi|kumoaminen, "note"?,
        "sections": [{"id": "22 §", "heading", "headingOld"?, "ops": [["=", "…"], ["-", "…"], ["+", "…"], ["…", "n sanaa"]],
                      "new": bool, "removed": bool}]}]},
     {"kind": "mietinto", "label": "HE → valiokunnan mietintö (TyVM 6/2026 vp)", "tunnus", "date", "laws": [… same …]}],
   "summary": {"he": {"laws", "sections", "new", "removed"}, "mietinto": {"laws", "sections"} | null}}

Ops are word tokens: the consumer joins the texts of consecutive ops with one space and renders "\\n"
as a paragraph break; joining the "=" and "-" ops gives the old text, "=" and "+" the new one. A long
unchanged run is collapsed to its first and last words with an ellipsis op ["…", "<n> sanaa"].
`build_hediff(items)` writes the files, deletes the ones that no longer belong to a cached HE and
returns {item id: summary} for build.py (a compact `diffN` per item).
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

from common import CACHE_DIR, OUT_DIR, TODAY, load_json, log, save_json

CACHE = CACHE_DIR / "hediff.json"
DIFF_DIR = OUT_DIR / "diff"
FILE_CAP = 150_000     # bytes per diff file
CONTEXT = 12           # words kept at both ends of a collapsed unchanged run
COLLAPSE_OVER = 40     # unchanged runs longer than this are collapsed
TEXT_CAP = 6_000       # characters per side before diffing (the cache already cuts at this)

TOKEN_RE = re.compile(r"\n|\S+")
HE_NUM = re.compile(r"^(\d+)/(\d{4})$")


# ----------------------------------------------------------------------------- word diff
def normalize(text: str | None) -> str:
    """Single spaces, paragraphs separated by exactly one '\\n', no blank lines."""
    paras = [re.sub(r"\s+", " ", p).strip() for p in (text or "").split("\n")]
    return "\n".join(p for p in paras if p)


def tokenize(text: str | None) -> list[str]:
    return TOKEN_RE.findall(normalize(text))


def detok(tokens: list[str]) -> str:
    return re.sub(r" ?\n ?", "\n", " ".join(tokens))


def word_diff(old: str | None, new: str | None) -> list[list[str]]:
    """[["=", text], ["-", text], ["+", text], …] over word tokens (punctuation attached, whitespace runs = one space)."""
    a, b = tokenize(old), tokenize(new)
    ops: list[list[str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            ops.append(["=", detok(a[i1:i2])])
        elif tag == "delete":
            ops.append(["-", detok(a[i1:i2])])
        elif tag == "insert":
            ops.append(["+", detok(b[j1:j2])])
        else:
            ops.append(["-", detok(a[i1:i2])])
            ops.append(["+", detok(b[j1:j2])])
    return ops


def join_ops(ops: list[list[str]], kinds: str = "=+") -> str:
    """Rebuild a side from ops: kinds "=+" gives the new text, "=-" the old one (ellipsis ops are skipped)."""
    toks: list[str] = []
    for kind, text in ops or []:
        if kind in kinds:
            toks.extend(TOKEN_RE.findall(text))
    return detok(toks)


def collapse(ops: list[list[str]], context: int = CONTEXT, over: int = COLLAPSE_OVER) -> list[list[str]]:
    """Replace the middle of long "=" runs by ["…", "<n> sanaa"], keeping `context` words at both ends."""
    out: list[list[str]] = []
    for kind, text in ops:
        toks = TOKEN_RE.findall(text) if kind == "=" else []
        words = [t for t in toks if t != "\n"]
        if kind != "=" or len(words) <= max(over, 2 * context + 1):
            out.append([kind, text])
            continue
        head: list[str] = []
        n = 0
        for t in toks:
            head.append(t)
            if t != "\n":
                n += 1
                if n == context:
                    break
        tail: list[str] = []
        n = 0
        for t in reversed(toks):
            tail.append(t)
            if t != "\n":
                n += 1
                if n == context:
                    break
        tail.reverse()
        hidden = len(words) - 2 * context
        out.append(["=", detok(head)])
        out.append(["…", f"{hidden} sanaa"])
        out.append(["=", detok(tail)])
    return out


def doc_size(doc) -> int:
    import json

    return len(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


# ----------------------------------------------------------------------------- sections
def removed_text(new: str | None) -> bool:
    return new is None or bool(re.match(r"^\(kumotaan\)\.?$", normalize(new)))


def he_section(sec: dict, law: dict) -> dict:
    old, new = sec.get("old"), sec.get("new")
    voimaantulo = (sec.get("id") or "").lower().startswith("voimaantulo")
    out = {"id": sec.get("id") or "?", "heading": sec.get("heading"), "new": False, "removed": False}
    if sec.get("headingOld"):
        out["headingOld"] = sec["headingOld"]
    if old is None:
        out["ops"] = [["+", normalize(new)]] if new else []
        out["new"] = bool(law.get("parallel")) and not voimaantulo or law.get("kind") == "uusi"
    elif removed_text(new):
        out["ops"] = [["-", normalize(old)]] + ([["+", normalize(new)]] if new else [])
        out["removed"] = True
    else:
        out["ops"] = word_diff(old, new)
    return out


def report_section(sec: dict) -> dict:
    he, com = sec.get("he") or "", sec.get("committee") or ""
    out = {"id": sec.get("id") or "?", "heading": sec.get("heading"), "new": bool(sec.get("added")) or not he, "removed": not com and bool(he)}
    if sec.get("headingHe"):
        out["headingOld"] = sec["headingHe"]
    if sec.get("heFrom"):
        out["heFrom"] = sec["heFrom"]
    out["ops"] = word_diff(he, com)
    return out


def law_label(name: str | None) -> str:
    return re.sub(r"\s+", " ", name or "Laki").strip()


def make_doc(item_id: str, num: str, rec: dict) -> dict | None:
    steps = []
    he_laws = []
    for law in rec.get("laws") or []:
        secs = [he_section(s, law) for s in law.get("sections") or []]
        secs = [s for s in secs if s["ops"]]
        if not secs:
            continue
        out = {"name": law_label(law.get("name")), "kind": law.get("kind") or "muutos", "sections": secs}
        if law.get("note"):
            out["note"] = law["note"]
        if law.get("omitted"):
            out["omitted"] = law["omitted"]
        he_laws.append(out)
    summary: dict = {"he": None, "mietinto": None}
    if he_laws:
        steps.append({"kind": "he", "label": "Voimassa oleva → HE", "laws": he_laws})
        summary["he"] = {"laws": len(he_laws), "sections": sum(len(l["sections"]) for l in he_laws),
                         "new": sum(1 for l in he_laws for s in l["sections"] if s["new"]),
                         "removed": sum(1 for l in he_laws for s in l["sections"] if s["removed"])}
    rep = rec.get("report") or {}
    rep_laws = []
    for law in rep.get("laws") or []:
        secs = [report_section(s) for s in law.get("sections") or []]
        secs = [s for s in secs if s["ops"]]
        if secs:
            rep_laws.append({"name": law_label(law.get("name")), "sections": secs})
    if rep_laws:
        steps.append({"kind": "mietinto", "label": f"HE → valiokunnan mietintö ({rep.get('tunnus')})", "tunnus": rep.get("tunnus"),
                      "date": rep.get("date"), "laws": rep_laws})
        summary["mietinto"] = {"laws": len(rep_laws), "sections": sum(len(l["sections"]) for l in rep_laws), "tunnus": rep.get("tunnus")}
    elif rep.get("tunnus"):
        summary["mietinto"] = {"laws": 0, "sections": 0, "tunnus": rep.get("tunnus")}
    if not steps:
        return None
    doc = {"id": item_id, "he": num, "generated": TODAY.isoformat(), "steps": steps, "summary": summary}
    shrink_doc(doc)
    return doc


def shrink_doc(doc: dict) -> None:
    """Collapse long unchanged runs always; tighten further only when the file would exceed FILE_CAP."""
    def sections():
        for step in doc["steps"]:
            for law in step["laws"]:
                yield from law["sections"]

    for s in sections():
        s["ops"] = collapse(s["ops"])
    if doc_size(doc) <= FILE_CAP:
        return
    for s in sections():
        s["ops"] = collapse(s["ops"], context=6, over=12)
    if doc_size(doc) <= FILE_CAP:
        return
    for cap in (3000, 1500, 600):  # cut the texts of whole-section insertions/deletions
        for s in sections():
            if len(s["ops"]) == 1 and s["ops"][0][0] in "+-" and len(s["ops"][0][1]) > cap:
                s["ops"] = [[s["ops"][0][0], s["ops"][0][1][:cap].rstrip() + " […]"]]
                s["truncated"] = True
        if doc_size(doc) <= FILE_CAP:
            return
    for s in sections():  # last resort: changed text only, cut
        total = sum(len(t) for _, t in s["ops"])
        if total > 2000:
            s["ops"] = [[k, t[:300] + (" […]" if len(t) > 300 else "")] for k, t in s["ops"] if k != "="][:40]
            s["truncated"] = True
        if doc_size(doc) <= FILE_CAP:
            return


# ----------------------------------------------------------------------------- entry point
def item_ids_by_he(items: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for it in items or []:
        for num in it.get("heNumerot") or []:
            out.setdefault(num, it.get("id"))
    return out


def build_hediff(items: list[dict], cache: dict | None = None, out_dir: Path | None = None) -> dict:
    """Write docs/data/diff/<item id>.json for every cached HE that has an item; return {item id: summary}."""
    cache = cache if cache is not None else (load_json(CACHE, {}) or {})
    out_dir = out_dir or DIFF_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    by_he = item_ids_by_he(items)
    result: dict[str, dict] = {}
    skipped = 0
    for num, rec in sorted((cache.get("he") or {}).items()):
        item_id = by_he.get(num)
        if not item_id:
            skipped += 1
            continue
        doc = make_doc(item_id, num, rec)
        if doc is None:
            continue
        save_json(out_dir / f"{item_id}.json", doc, compact=True)
        result[item_id] = doc["summary"]
    removed = 0
    for f in out_dir.glob("*.json"):
        if f.stem not in result:
            f.unlink()
            removed += 1
    total = sum(f.stat().st_size for f in out_dir.glob("*.json"))
    log(f"hediff: {len(result)} diff-tiedostoa ({total // 1024} kB), {skipped} HE:tä ilman kohdetta, poistettu {removed} -> {out_dir}")
    return result


if __name__ == "__main__":
    build_hediff((load_json(OUT_DIR / "items.json", {}) or {}).get("items") or [])
