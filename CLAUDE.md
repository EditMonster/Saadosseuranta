# Säädösseuranta – ohjeet Claudelle

Kallen oma projekti: julkinen, ilmainen säädös-, hankinta- ja yrityskauppaseuranta suomalaisille juristeille.
Fondia saa testata sitä, mutta se ei ole firman työkalu. Sivu: https://editmonster.github.io/Saadosseuranta/
Käyttäjälle vastataan suomeksi. Hän on ohjelmoinnissa aloittelija: selitä muutokset lopputuloksina, ei koodina.

## Ehdottomat säännöt

- **Ei maksullista tekoälyä eikä maksullisia rajapintoja.** Ei LLM-kutsuja ajossa eikä selaimessa. Kaiken pitää
  pysyä ilmaisena, vaikka käyttäjiä olisi paljon. Konekäännös = avoimet OPUS-MT-mallit (`scripts/mt.py`), poiminta =
  sääntöpohjainen Python.
- **Repo pysyy julkisena.** Älä ehdota yksityiseksi muuttamista. Sivulla on `noindex`.
- **Tietosuoja:** yksityishenkilöt ja toiminimet (yksityiset elinkeinonharjoittajat) eivät näy nimellä missään
  (`common.scrub_personal`, `mask_private_givers`, `PRIVATE_LABEL`, `SOLE_LABEL`). Kaikki `docs/data`- ja
  `data/cache`-tiedostot kirjoitetaan `common.save_json`illa, joka minimoi henkilötiedot. Tiimikansioihin ei asiakastietoja.
- **Älä koskaan kirjoita git-historiaa uudelleen** (ei force pushia, ei rebasea julkaistulle historialle), ellei Kalle pyydä.
- Ei analytiikkaa, ei kolmannen osapuolen fontteja tai skriptejä (fontit ja kirjastot ovat `docs/`-hakemistossa).

## Rakenne

- `docs/index.html` – koko sivu yhdessä tiedostossa (vanilla JS, lasiteema). Raportit: `docs/js/raportit.js`
  (ladataan vasta tarvittaessa) ja `docs/vendor/`.
- `scripts/update.py` – ajo: haut (`fetch_*.py`) → `build.py` (`build_*.py`) → `translate.py`.
- `docs/data/` – julkaistava aineisto, **rakentuu Actionsissa**. Älä commitoi paikallisesti rakennettua dataa:
  ennen committia `git checkout -- docs/data && git clean -fdq docs/data`.
- `data/cache/` – välimuistit (julkinen repo).
- `config/i18n/{sv,en,et,lt}.json` – käyttöliittymän käännökset; uuden tekstin jälkeen lisää avain kaikkiin ja aja
  `python3 scripts/build_i18n.py`.
- `.github/workflows/update.yml` (tunneittain, aineisto) ja `deploy.yml` (testit → Pages). `kansiopyynto.yml`
  toteuttaa sivulta tehdyt tiimikansiomuutokset issueina.

## Työtapa

- Testit ennen pushia: `python3 -m pytest -q` (n. 2–3 min; Playwright-testit `tests/test_smoke.py`). Uusi
  ominaisuus = uusi testi. Testipalvelin käyttää porttia 8765; jos se on varattu: `kill $(lsof -ti:8765)`
  (älä käytä `pkill -f`-kuviota, joka voi osua omaan komentotulkkiin).
- Commitit Kallen nimissä: `Kalle Jurkkala <66671917+EditMonster@users.noreply.github.com>`. Viestit suomeksi.
- Ennen pushia `git pull --rebase` – Actions-botti commitoi aineistoa tunneittain.
- Aineiston uudelleenrakennus: `gh api -X POST repos/EditMonster/Saadosseuranta/actions/workflows/update.yml/dispatches -f ref=main`
  (GraphQL ei ole käytettävissä; käytä REST-rajapintaa). Ajo kestää noin 40–45 min.
- Rehellisyys datasta: jos jokin tilastollinen havainto ei kestä tarkistusta (esim. lausuntokierroksen vastustus
  ei ennusta valiokunnan muutoksia), sitä ei esitetä sivulla ennusteena.
