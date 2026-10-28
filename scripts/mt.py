"""Machine translation with open OPUS-MT models (Argos Translate packages, CC BY 4.0) – free, no API keys.

The models run on the CPU with CTranslate2. Argos ships one model per direction with English in the middle, so
"fi → lt" is translated fi → en → lt (the English pivot is cached and reused for every target language).

Packages are downloaded once into MT_MODELS (default ~/.cache/saadosseuranta-mt; the update workflow caches the
folder between runs) and only the parts needed for inference are kept (the stanza sentence splitter is dropped –
titles and summaries are translated whole).

    from mt import Engine
    eng = Engine()                       # None-safe: eng.available is False when the runtime is missing
    eng.translate(["Laki ..."], "fi", "lt")
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from pathlib import Path

from common import get_json, log

INDEX = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
MODELS = Path(os.environ.get("MT_MODELS") or Path.home() / ".cache" / "saadosseuranta-mt")
SOURCES = ("fi", "sv", "et", "lt", "lv", "nb", "da")  # → en
TARGETS = ("fi", "sv", "et", "lt")  # en →


def _fix_pivot(src_text: str, en: str, src: str) -> str:
    """Small glossary repairs on the English pivot, where Finnish legal wording is lost in the base models."""
    if src == "fi":
        if "§" in src_text and "artikla" not in src_text.lower():
            en = re.sub(r"\bArticles\s+(\d+[a-z]?)\s+and\s+(\d+[a-z]?)", r"sections \1 and \2", en)
            en = re.sub(r"\bArticle\s+(\d+[a-z]?)\b", r"section \1", en)
        if re.search(r"eduskun", src_text, re.I):
            en = re.sub(r"\b(?:the\s+)?(?:European\s+)?Parliament\b", "the Parliament of Finland", en)
            en = en.replace("the Parliament of Finland of Finland", "the Parliament of Finland")
    en = re.sub(r"(\d+)\s+/\s+(\d{4})", r"\1/\2", en)  # "HE 173 / 2026 vp" → "HE 173/2026 vp"
    return en


def _fix_target(text: str) -> str:
    text = re.sub(r"(\d+)\s+/\s+(\d{4})", r"\1/\2", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:1].upper() + text[1:] if text[:1].islower() else text  # titles start with a capital


class Engine:
    def __init__(self, models: Path = MODELS, threads: int | None = None):
        self.models = models
        self.threads = threads or max(1, os.cpu_count() or 2)
        self._pairs: dict[tuple[str, str], tuple] = {}
        self._index = None
        try:
            import ctranslate2  # noqa: F401
            import sacremoses  # noqa: F401
            import sentencepiece  # noqa: F401
            from argostranslate import tokenizer  # noqa: F401
            self.available = True
        except Exception as e:  # noqa: BLE001
            log(f"mt: käännösmoottori ei ole asennettu ({e.__class__.__name__}) – vain viralliset käännökset")
            self.available = False

    # ---------- packages ----------
    def _package_dir(self, a: str, b: str) -> Path | None:
        for d in sorted(self.models.glob(f"translate-{a}_{b}-*")) + sorted(self.models.glob(f"{a}_{b}")):
            if (d / "model" / "model.bin").exists():
                return d
        return None

    def _download(self, a: str, b: str) -> Path | None:
        if self._index is None:
            self._index = get_json(INDEX) or []
        pkg = next((p for p in self._index if p.get("from_code") == a and p.get("to_code") == b), None)
        if not pkg:
            return None
        import requests
        for url in pkg.get("links") or []:
            try:
                r = requests.get(url, timeout=600)
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001
                log(f"mt: {a}→{b} lataus epäonnistui ({url}): {e}")
                continue
            self.models.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                names = [n for n in z.namelist() if "/stanza/" not in n]
                root = names[0].split("/")[0]
                for n in names:
                    z.extract(n, self.models)
            log(f"mt: ladattu malli {a}→{b} ({len(r.content) / 1e6:.0f} MB)")
            return self.models / root
        return None

    def _pair(self, a: str, b: str):
        if (a, b) not in self._pairs:
            import ctranslate2
            from argostranslate.tokenizer import BPETokenizer, SentencePieceTokenizer
            d = self._package_dir(a, b) or self._download(a, b)
            if not d:
                raise RuntimeError(f"mallia {a}→{b} ei ole")
            tok = SentencePieceTokenizer(d / "sentencepiece.model") if (d / "sentencepiece.model").exists() else BPETokenizer(d / "bpe.model", a, b)
            self._pairs[(a, b)] = (ctranslate2.Translator(str(d / "model"), device="cpu", inter_threads=1, intra_threads=self.threads), tok)
        return self._pairs[(a, b)]

    # ---------- translation ----------
    def _run(self, texts: list[str], a: str, b: str) -> list[str]:
        if not texts:
            return []
        tr, tok = self._pair(a, b)
        res = tr.translate_batch([tok.encode(t) for t in texts], max_batch_size=32, beam_size=2, max_decoding_length=320)
        return [tok.decode(r.hypotheses[0]).strip() for r in res]

    def to_english(self, texts: list[str], src: str) -> list[str]:
        if src == "en":
            return list(texts)
        out = self._run(texts, src, "en")
        return [_fix_pivot(s, e, src) for s, e in zip(texts, out)]

    def from_english(self, texts: list[str], tgt: str) -> list[str]:
        if tgt == "en":
            return [_fix_target(t) for t in texts]
        return [_fix_target(t) for t in self._run(texts, "en", tgt)]

    def translate(self, texts: list[str], src: str, tgt: str) -> list[str]:
        return self.from_english(self.to_english(texts, src), tgt)


# ---------- language identification ----------
_LID = None


def detect(text: str, allowed: tuple[str, ...]) -> str:
    """Language of a short text, restricted to the languages the source can plausibly use."""
    global _LID
    if len(allowed) == 1:
        return allowed[0]
    try:
        if _LID is None:
            from py3langid.langid import MODEL_FILE, LanguageIdentifier
            _LID = LanguageIdentifier.from_pickled_model(MODEL_FILE, norm_probs=True)
        codes = ["no" if c == "nb" else c for c in allowed]
        _LID.set_languages(codes)
        code = _LID.classify(text)[0]
        return "nb" if code == "no" else code
    except Exception:  # noqa: BLE001
        return _guess(text, allowed)


_MARKERS = {"fi": r"\b(ja|tai|sekä|lain|laki|hankinta|palvelu\w*|annetun|muuttamisesta)\b|ä|ö",
            "sv": r"\b(och|av|för|om|avseende|upphandling|tjänster)\b|å",
            "en": r"\b(the|and|of|for|services|supply|framework)\b",
            "et": r"\b(ja|teenus\w*|hange|ning)\b|õ", "lt": r"\b(ir|paslaugos|pirkimas)\b|[ėįųū]",
            "lv": r"\b(un|pakalpojumi|iepirkums)\b|[āēīūņļķģ]", "nb": r"\b(og|av|for|tjenester|rammeavtale)\b|ø",
            "da": r"\b(og|af|for|levering|rammeaftale)\b|ø"}


def _guess(text: str, allowed: tuple[str, ...]) -> str:
    t = text.lower()
    scores = {c: len(re.findall(_MARKERS.get(c, r"$^"), t)) for c in allowed}
    return max(allowed, key=lambda c: (scores[c], -allowed.index(c)))


def english_half(text: str) -> str | None:
    """'Kravu pārvadājumu prognozes / Freight Traffic Demand Forecast' → the English half, a better MT source."""
    parts = [p.strip() for p in re.split(r"\s+[/|]\s+", text) if p.strip()]
    if len(parts) == 2:
        for p in parts:
            if detect(p, ("en", "fi", "sv", "et", "lt", "lv", "nb", "da")) == "en" and len(p) > 8:
                return p
    return None


if __name__ == "__main__":  # quick manual check: python scripts/mt.py fi lt "Laki ..."
    import sys
    a, b, *txt = sys.argv[1:]
    print(json.dumps(Engine().translate(txt, a, b), ensure_ascii=False, indent=1))
