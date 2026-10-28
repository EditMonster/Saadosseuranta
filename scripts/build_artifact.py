"""Rakentaa yhden tiedoston tilannevedoksen sivusta (claude.ai-artifact): docs/index.html, johon aineisto ja
logot on upotettu. Artifact-näkymä ei päästä sivua hakemaan tiedostoja verkosta, joten vedos ei päivity
itsestään – ajantasainen sivu on GitHub Pagesissa, ja vedoksen yläpalkki kertoo rakennuspäivän ja linkin.

Aineisto (items, hankinnat, yrityskaupat, vaikuttaminen, ratkaisut, tilastot, annetut lausunnot, HE-diffit)
upotetaan yhtenä gzip-pakattuna base64-merkkijonona (~4 MB; purettuna ~25 MB) ja puretaan selaimen omalla
DecompressionStream-rajapinnalla – näin koko aineisto mahtuu artifactin 16 MB:n rajaan.

Käyttö:  python scripts/build_artifact.py [tulostiedosto]   (oletus: /tmp/saadosseuranta.html)
"""
from __future__ import annotations

import base64
import gzip
import json
import pathlib
import sys

R = pathlib.Path(__file__).resolve().parent.parent
SITE = "https://editmonster.github.io/Saadosseuranta/"
LS_ROWS = 12


def rd(p: str, default: str) -> str:
    f = R / "docs" / "data" / p
    return f.read_text(encoding="utf-8").strip() if f.exists() else default


def per_item(sub: str) -> dict:
    out = {}
    for f in sorted((R / "docs" / "data" / sub).glob("*.json")):
        out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return out


def main(out_path: str) -> None:
    src = (R / "docs" / "index.html").read_text(encoding="utf-8")
    items, meta, changes = rd("items.json", '{"items":[]}'), rd("meta.json", "{}"), rd("changes.json", '{"changes":[]}')
    hank, yk, kans = rd("hankinnat.json", '{"items":[]}'), rd("yrityskaupat.json", '{"items":[]}'), rd("kansiot.json", "{}")
    vaik, tilas, ratk = rd("vaikuttaminen.json", '{"items":{}}'), rd("tilastot.json", "{}"), rd("ratkaisut.json", '{"items":[]}')
    generated = (json.loads(meta).get("generated") or "")[:16].replace("T", " ")

    def b64(p: str) -> str:
        return "data:image/png;base64," + base64.b64encode((R / "docs" / p).read_bytes()).decode()

    html = src[src.index("<title>"):]
    html = html.replace("<title>Säädösseuranta</title>", '<title>Säädösseuranta</title>\n<meta name="claude:viewport-fit-sides" content="cover">', 1)
    html = html.replace("</head>\n<body>", "", 1).replace("</body>\n</html>", "", 1)
    html = html.replace('src="logo-icon.png"', 'src="' + b64("logo-icon.png") + '"')
    start = html.index("const v=Date.now();")
    end = html.index("</script>", start)
    blob = {"items": json.loads(items), "meta": json.loads(meta), "changes": json.loads(changes), "hank": json.loads(hank), "yk": json.loads(yk),
            "kans": json.loads(kans), "vaik": json.loads(vaik), "ratk": json.loads(ratk), "tilas": json.loads(tilas),
            "lausunnot": per_item("lausunnot"), "diffs": per_item("diff"), "palaute": per_item("palaute")}
    raw = json.dumps(blob, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    packed = base64.b64encode(gzip.compress(raw, 9)).decode("ascii")
    inline = f'''window.__SNAPSHOT={json.dumps(generated)};
(async function(){{
  const b64="{packed}";
  let D;
  try{{
    const bytes=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));
    const txt=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
    D=JSON.parse(txt);
  }}catch(e){{ document.getElementById("sys").innerHTML='<span class="warn">Aineiston purku ei onnistunut tässä selaimessa – avaa ajantasainen sivu: <a href="{SITE}">editmonster.github.io/Saadosseuranta</a></span>'; return; }}
  window.__INFLUENCE=(D.vaik||{{}}).items||{{}}; window.__RATKAISUT=D.ratk||{{items:[]}}; window.__TILASTOT=D.tilas||{{}}; window.__LAUSUNNOT=D.lausunnot||{{}}; window.__DIFFS=D.diffs||{{}}; window.__PALAUTE=D.palaute||{{}};
  const j=D.items, m=D.meta, ch=D.changes, __H=D.hank, __Y=D.yk, __K=D.kans;
  DATA=j.items||[]; META=Object.assign({{}},j.meta||{{}},m||{{}});
  CHANGES=(ch&&ch.changes)||[]; CHANGE_BY_ID={{}}; CHANGES.forEach(c=>{{ if(!CHANGE_BY_ID[c.id]||CHANGE_BY_ID[c.id].date<c.date) CHANGE_BY_ID[c.id]=c; }});
  DATA.forEach(it=>{{ it.events=(it.events||[]).slice().sort((a,b)=>a.date.localeCompare(b.date)); it.topics=it.topics||[]; }});
  buildTopicChips(META.topics||TOPICS); buildLajiChips(META.lajit||{{}}); buildPTopicChips(META.hankintaTopics||[]); buildYkTopicChips(META.yrityskauppaTopics||[]);
  TENDERS=(__H.items||[]).filter(t=>t.deadline||t.stage).map(t=>Object.assign({{topics:[],events:[]}},t)); TENDERS_LOADED=true;
  MERGERS=(__Y.items||[]).map(m=>Object.assign({{topics:[],events:[]}},m)); MERGERS.forEach(it=>{{ it.events=(it.events||[]).slice().sort((a,b)=>a.date.localeCompare(b.date)); }}); MERGERS_LOADED=true;
  KANSIOT={{repo:__K.repo||"",newUrl:__K.newUrl||"",issueUrl:__K.issueUrl||""}}; SHARED=(__K.folders||[]).map(f=>Object.assign({{}},f,{{id:"t:"+f.id,key:f.id,shared:true,items:(f.items||[]).slice(),ics:"{SITE}"+f.ics}})); SHARED_LOADED=true;
  buildCountrySelect(); loadRulings();
  renderStatus();
  render();
  if(pendingItem&&findItem(pendingItem)) openItem(pendingItem);
}})();
'''
    html = html[:start] + inline + html[end:]
    html = html.replace('<button class="follow-btn" data-fics="${esc(f.id)}" title="Lataa kansion määräajat kalenteritiedostona (.ics)">Kalenteri</button>', "")  # blob downloads do not work inside the artifact viewer
    html = html.replace('href="data/saadosseuranta.ics"', f'href="{SITE}data/saadosseuranta.ics"')
    html = html.replace('location.origin+location.pathname+"?s="+syncCode()+"#tilannekuva"', f'"{SITE}?s="+syncCode()+"#tilannekuva"')
    assert "function renderStatus" in html and "window.__SNAPSHOT" in html
    out = pathlib.Path(out_path)
    out.write_text(html, encoding="utf-8")
    print(f"{out} {len(html.encode('utf-8')) / 1e6:.1f} MB (aineisto {generated})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/saadosseuranta.html")
