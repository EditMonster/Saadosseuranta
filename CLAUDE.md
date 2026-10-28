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

## Avoimet tehtävät (tilanne 28.10.2026)

1. **Välimuistien kertasiivous:** toiminimien maskaus (`SOLE_LABEL`) tuli koodiin 28.10. Ne `data/cache`-tiedostot, joita
   ajo ei kirjoita uudelleen (esim. `data/cache/lausunnot/hk-2025.json`, `data/cache/hankeikkuna.json`), sisältävät vielä
   toiminimiä: lataa ja tallenna ne kerran `common.save_json`illa ja commitoi. Historiaa ei muuteta.
2. **Tietoturvakorjaukset** (katselmus 28.10.):
   - sivu hyväksyy vain `github_pat_`-alkuiset tiimiavaimet;
   - tiimiavaimen riskikuvaus oikeaksi (avain = omistajan nimissä toimiminen issueissa);
   - `kansiopyynto`: hyväksyntä tarkistaa, ettei pyynnön tekstiä ole muokattu hyväksynnän jälkeen (tiiviste);
   - `?s=`-siirtolinkki kysyy vahvistuksen ennen tuontia, erityisesti piilotusten osalta;
   - linkkien skeemaksi vain `https?://` (`safeUrl`);
   - `.ics`: poista myös `\r`;
   - työnkulkujen oikeudet: `permissions: {}` ylätasolle ja oikeudet työkohtaisesti.
   Bottitiliä ei tehdä niin kauan kuin tiimiavain on vain Kallella ja muutamalla luotetulla.
3. **Saavutettavuus:**
   - apu- ja päivämäärätekstien kontrasti vähintään 4,5:1 (vaalea: harmaa noin `#6b5f55`, korostus noin `#8a4a06`;
     tumma: harmaa noin `#a39890`);
   - ikkunoiden kohdistusloukku ja Escape dokumenttitasolla;
   - ilmoituksiin `role="status"` ja `aria-live`.
4. **Otostarkistukset, kun aineisto on rakentunut:**
   - siirtymäsäännökset: 30 säädöstä verrattuna Finlexiin;
   - sidosryhmänimet: 100 suurinta organisaatiota.
5. **claude.ai-tilannevedos** (päivitetty 28.10. klo 15:27 aineistolla, versio 59; päivitä tarvittaessa): `python3 scripts/build_artifact.py`. Sidosryhmät ladataan suhteellisesta polusta
   `data/sidosryhmat.json`, joten vedoksen mukana julkaistaan tämä tiedosto sekä `data/tr/*.json`, `js/`, `vendor/` ja `fonts/`.
