"""EU-lainsäädäntömenettelyjen asiakirjat Euroopan parlamentin Legislative Observatorysta (OEIL).

OEIL:n menettelysivun "Documentation gateway" kokoaa menettelyn asiakirjat kaikilta toimielimiltä:
* parlamentti: valiokunnan mietintö täysistunnolle (A10-…/2025), hyväksytyt tekstit
* komissio: vaikutustenarviointi ja sen tiivistelmä (SWD), sääntelyntarkastelulautakunnan lausunto (SEC),
  muutettu ehdotus, komission vastaus parlamentin kantaan
* neuvosto: kanta ensimmäisessä käsittelyssä, lausumat
* muut: Euroopan tietosuojavaltuutettu (EDPS), Euroopan talous- ja sosiaalikomitea, alueiden komitea, EKP
* kansalliset parlamentit: perustellut lausunnot ja kannanotot (määrä)

Välimuisti data/cache/oeil.json {"proc": {"2023/0205(COD)": {checked, docs: [{group, type, ref, date, url}], np}}}.
Keskeneräinen menettely luetaan uudelleen REFRESH_DAYS välein; valmis (säädös julkaistu) kerran valmistumisen jälkeen.
Ajossa luetaan enintään MAX_PER_RUN sivua ja BUDGET_S sekuntia.
"""
from __future__ import annotations

import datetime as dt
import html as htmlmod
import os
import re
import time

from common import CACHE_DIR, OUT_DIR, SourceOutage, http, load_json, log, save_json

URL = "https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference={}"
OUT = CACHE_DIR / "oeil.json"
MAX_PER_RUN = int(os.environ.get("OEIL_MAX", "60"))
BUDGET_S = int(os.environ.get("OEIL_BUDGET_S", "240"))
REFRESH_DAYS = 7
DONE_KEEP_DAYS = 730  # finished procedures are read for this long after the act (their documents stay useful)

SECTION = re.compile(r'aria-labelledby="es_accordion-item-doc-gateway-([A-Za-z]+)-title"(.*?)</table>', re.S)
ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL = re.compile(r"<(th|td)\b[^>]*>(.*?)</\1>", re.S)
HREF = re.compile(r'href="([^"]+)"')
DMY = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")

# which document types are worth a line on the page; the rest (drafts, amendments, debates) are left out
KEEP = [
    ("EP", re.compile(r"Committee report tabled", re.I), "Parlamentin valiokunnan mietintö"),
    ("EP", re.compile(r"Text adopted by Parliament", re.I), "Parlamentin hyväksymä teksti"),
    ("EC", re.compile(r"Amended legislative proposal|Modified legislative proposal", re.I), "Komission muutettu ehdotus"),
    ("EC", re.compile(r"Commission response to text adopted", re.I), "Komission vastaus parlamentin kantaan"),
    ("EC", re.compile(r"Document attached to the procedure", re.I), None),  # SWD / SEC: label from the reference
    ("OTHER", re.compile(r".", re.I), None),
]
OTHER_LABEL = {"EDPS": "Euroopan tietosuojavaltuutetun lausunto (EDPS)", "EESC": "Euroopan talous- ja sosiaalikomitean lausunto",
               "CofR": "Alueiden komitean lausunto", "CoR": "Alueiden komitean lausunto", "ECB": "Euroopan keskuspankin lausunto"}


def _text(cell: str) -> str:
    t = re.sub(r"<[^>]+>", " ", cell)
    return re.sub(r"\s+", " ", htmlmod.unescape(t)).strip()


def doc_label(group: str, dtype: str, ref: str, body: str = "") -> str | None:
    if group == "EC" and re.match(r"SWD", ref or ""):
        return "Komission valmisteluasiakirja (SWD), esim. vaikutustenarviointi"
    if group == "EC" and re.match(r"SEC", ref or ""):
        return "Sääntelyntarkastelulautakunnan lausunto (SEC)"
    if group == "OTHER":
        return OTHER_LABEL.get(body) or (f"{body}: {dtype}" if body else dtype)
    if group in ("CSL", "COUNCIL", "CONS", "CS", "CN"):
        return {"Council position": "Neuvoston kanta", "Council statement": "Neuvoston lausuma",
                "Coreper letter confirming interinstitutional agreement": "Coreperin kirje: alustava sopu vahvistettu",
                "Draft final act": "Säädöksen lopullinen teksti (neuvosto)",
                "Council position on draft budget": "Neuvoston kanta talousarvioesitykseen"}.get(dtype, f"Neuvosto: {dtype}")
    for g, rx, label in KEEP:
        if g == group and rx.search(dtype or "") and label:
            return label
    return None


def parse_gateway(h: str) -> dict:
    """{"docs": [{group, type, label, ref, date, url}], "np": number of national parliaments' documents}."""
    docs, np_n = [], 0
    for group, body in SECTION.findall(h):
        group = group.upper()
        for tr in ROW.findall(body):
            if 'scope="col"' in tr:  # the table header
                continue
            cells = CELL.findall(tr)
            if not cells or cells[0][0] != "th" and group != "NP":
                continue
            texts = [_text(c[1]) for c in cells]
            if not any(texts):
                continue
            if group == "NP":
                np_n += 1
                continue
            m = DMY.search(" ".join(texts))
            date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None
            inst = texts[0] if group == "OTHER" else ""
            dtype = texts[1] if group == "OTHER" else texts[0]
            ref_cell = next((c[1] for c in cells if "w-25" in c[1] or HREF.search(c[1])), "")
            ref_i = next((i for i, c in enumerate(cells) if HREF.search(c[1])), None)
            ref = texts[ref_i].split(" OJ ")[0].strip() if ref_i is not None else ""
            if not ref:  # the reference column (w-25) without a link
                ref = next((t for t in texts[1:] if re.match(r"[A-Z]{1,4}[\d(]", t)), "")
            href = HREF.search(cells[ref_i][1]).group(1) if ref_i is not None else None
            label = doc_label(group, dtype, ref, inst)
            if not label:
                continue
            docs.append({k: v for k, v in {"group": group, "type": dtype, "label": label, "ref": ref.split(" ")[0] or None,
                                           "date": date, "url": htmlmod.unescape(href) if href else None}.items() if v})
            _ = ref_cell
    return {"docs": docs, "np": np_n}


def wanted() -> list[tuple[str, bool]]:
    """(procedure, finished) for the EU items on the page (previous build) that have a procedure reference."""
    data = load_json(OUT_DIR / "items.json", {}) or {}
    items = data.get("items") if isinstance(data, dict) else data
    out = {}
    cut = (dt.date.today() - dt.timedelta(days=DONE_KEEP_DAYS)).isoformat()
    for it in items or []:
        p = it.get("procedure") or ""
        if it.get("scope") != "eu" or not re.match(r"^\d{4}/\d{4}[A-Z]?\((COD|CNS|APP|NLE|BUD|SYN|AVC|CNS)\)$", p):
            continue
        last = max((e.get("date") or "" for e in it.get("events") or []), default="")
        if it.get("done") and last and last < cut:
            continue
        out[p] = bool(it.get("done"))
    return sorted(out.items())


def main() -> None:
    cache = load_json(OUT, {}) or {}
    procs = cache.setdefault("proc", {})
    today = dt.date.today()

    def due(p: str, done: bool) -> bool:
        c = procs.get(p)
        if not c:
            return True
        if done and c.get("done"):
            return False
        return (today - dt.date.fromisoformat(c.get("checked") or "2000-01-01")).days >= REFRESH_DAYS

    todo = [(p, d) for p, d in wanted() if due(p, d)]
    todo.sort(key=lambda pd: (pd[0] in procs, pd[1], pd[0]), reverse=False)
    log(f"oeil: {len(procs)} menettelyä välimuistissa, {len(todo)} luettavana")
    t0, done_n, fails = time.time(), 0, 0
    for p, done in todo[:MAX_PER_RUN]:
        if time.time() - t0 > BUDGET_S:
            break
        try:
            h = http("GET", URL.format(p), timeout=60).text
        except Exception as e:  # noqa: BLE001
            fails += 1
            log(f"warn: oeil {p}: {e}")
            if fails >= 5 and not done_n:
                raise SourceOutage(f"OEIL ei vastaa: {e}") from e
            continue
        rec = parse_gateway(h)
        rec.update({"checked": today.isoformat(), "done": done})
        procs[p] = rec
        done_n += 1
        time.sleep(0.5)
        if done_n % 25 == 0:
            save_json(OUT, cache)
    cache["fetched"] = dt.datetime.now().isoformat(timespec="seconds")
    save_json(OUT, cache)
    n_docs = sum(len(v.get("docs") or []) for v in procs.values())
    log(f"oeil: {done_n} sivua luettu; yhteensä {len(procs)} menettelyä, {n_docs} asiakirjaa -> {OUT}")


if __name__ == "__main__":
    main()
