# Säädösseuranta

Automaattisesti päivittyvä seurantasivu kansallisesta ja EU-lainsäädännöstä:
lausuntoajat, eduskuntakäsittely, hyväksyminen, vahvistus, voimaantulot ja EU-määräajat
vaakasuuntaisina aikajanoina, suodatettavissa aihealueittain.

Sivu on staattinen (`docs/`), aineisto on yksi JSON-tiedosto (`docs/data/items.json`), ja
GitHub Actions ajaa hakuskriptit joka aamu ja committaa muuttuneen aineiston. Käyttökustannus
on nolla: julkisen repon Actions-minuutit ja GitHub Pages ovat ilmaisia.

## Sivun näkymät

* **Tilannekuva** – avoimet lausuntokierrokset, seuraavien 60 päivän vaiheet ja viimeisten 14 päivän tapahtumat; neljä avainlukua.
* **Kansallinen** ja **EU** – vaakasuuntaiset aikajanat (lausuntoaika, eduskunta-/lainsäädäntömenettely, voimaantulo, määräajat), lausuttavissa olevat kärjessä.
* **Valmiit** – vahvistetut ja voimassa olevat säädökset taulukkona.
* Jokaisella säädöksellä on pysyvä linkki (`…/#fi-he-129-2026`), joka avaa sen aikajanan suoraan.
* `data/saadosseuranta.ics` – kaikki tulevat määräajat kalenteriin (Google/Outlook/Apple: "tilaa kalenteri osoitteesta").
* Valkea teema oletuksena, tumma *Teema*-napista; valinta muistetaan selaimessa.

## Mistä aineisto tulee

| Lähde | Mitä haetaan | Rajapinta |
|---|---|---|
| Valtioneuvoston Hankeikkuna | Kaikki hallituksen esitysten valmisteluhankkeet (käynnissä + 18 kk:n sisällä päättyneet): lausuntokierrokset, kuulemiset, HE-numerot, säädöskokoelman numerot, lausuntopyynnöt, vastuuministeriö, teemat | `POST https://api.hankeikkuna.fi/api/v2/kohteet/haku` (avoin, ei avainta) |
| Eduskunnan avoin data | Jokaisen HE:n käsittelytiedot: annettu, lähetekeskustelu, valiokunnan mietintö, 1. ja 2. käsittely, eduskunnan vastaus, vahvistuspäivä, säädöskokoelman numero, HE-tekstistä ehdotettu voimaantulo | `https://avoindata.eduskunta.fi/api/v1/tables/VaskiData/rows` |
| Finlex | Vireillä olevien HE:iden luettelo ministeriöittäin (varmistus, ettei mikään HE jää Hankeikkunan ulkopuolelle) sekä vahvistettujen lakien voimaantulopäivät säädöskokoelmasta | `finlex.fi` (HTML, rajoitettu nopeus) |
| Euroopan parlamentin avoin data | Tavallisen lainsäätämisjärjestyksen menettelyt (2021–): suomenkieliset nimet, valiokunta- ja täysistuntovaiheet, alustava sopu, allekirjoitus, EUVL-julkaisu | `https://data.europarl.europa.eu/api/v2/procedures` |
| EU:n julkaisutoimiston Cellar | Komission ehdotuksen päivä, hyväksytyn säädöksen CELEX-numero, voimaantulo, vaiheittaiset soveltamispäivät, täytäntöönpanon määräajat, voimassaolo | SPARQL `https://publications.europa.eu/webapi/rdf/sparql` |

Mitä **ei** seurata (lisättävissä): valtioneuvoston ja ministeriöiden asetukset, EU:n delegoidut
ja täytäntöönpanosäädökset, tuomioistuinratkaisut, kansalaisaloitteet, valtiosopimukset
muuten kuin HE-muodossa. `lausuntopalvelu.fi` ja `valtioneuvosto.fi` estävät ohjelmalliset
haut (Cloudflare), joten lausuntokierrokset tulevat Hankeikkunasta, joka on sama tieto.

## Rakenne

```
config/
  settings.yaml      EU-vuodet, menettelytyypit, Valmiit-sivun aikaraja
  topics.yaml        aihealueiden avainsanat (muokkaa vapaasti)
  eu_watchlist.yaml  EU-menettelyt, jotka haetaan aina
  overrides.json     käsin lisätyt tapahtumat, korjaukset ja lyhyet näyttönimet (id:n mukaan)
scripts/
  fetch_hankeikkuna.py  fetch_eduskunta.py  fetch_finlex.py  fetch_eu.py
  build.py           yhdistää välimuistit -> docs/data/items.json
  update.py          ajaa kaiken; yhden lähteen virhe ei kaada muita
data/cache/          lähdekohtaiset välimuistit (committataan, jotta päivitys on nopea)
docs/                GitHub Pages -sivu: index.html, logot, data/items.json + meta.json + saadosseuranta.ics
.github/workflows/update.yml   päivittäinen ajo
```

## Käyttöönotto

1. Luo GitHub-repo ja työnnä tämä sisältö sinne.
2. **Settings → Pages → Source: Deploy from a branch → `main` / `/docs`.** Sivu tulee osoitteeseen
   `https://<käyttäjä>.github.io/<repo>/`.
3. **Settings → Actions → General → Workflow permissions: Read and write permissions** (jotta
   workflow voi committata aineiston).
4. Aja workflow kerran käsin: **Actions → Päivitä säädösaineisto → Run workflow.** Sen jälkeen se
   ajaa itsensä joka aamu klo 06:40 UTC.

Paikallisesti:

```bash
pip install -r requirements.txt
python scripts/update.py            # kaikki lähteet (ensimmäinen ajo ~10 min)
python scripts/update.py eduskunta  # vain yksi lähde + build
python -m http.server -d docs 8000  # http://localhost:8000
```

## Ylläpito

* **Aihealueet**: lisää avainsana `config/topics.yaml`-tiedostoon; luokittelu lasketaan joka ajossa
  uudelleen. Säädös, johon mikään avainsana ei osu, saa aihealueen *Muut* (EU-puolella sellaiset
  jätetään pois, ellei menettely ole watchlistillä).
* **Uusi EU-säädös seurantaan**: lisää menettelytunnus `config/eu_watchlist.yaml`-tiedostoon.
* **Käsin tunnettu päivämäärä** (esim. omnibus-asetuksen siirtämä soveltamispäivä): `config/overrides.json`.
  Käsin lisätyt päivät näkyvät katkoviivalla ja merkinnällä "tarkistamaton", ellei `confirmed: true`.
* Finlex rajoittaa pyyntöjä: voimaantulot haetaan enintään 200 säädökselle per ajo, loput seuraavana
  päivänä. Jo haetut säilyvät välimuistissa.
* Jos jokin lähde on alhaalla, ajo käyttää sen edellistä välimuistia ja kirjaa virheen lokiin.

## Kustannus

| Erä | Hinta |
|---|---|
| GitHub Actions, julkinen repo | 0 € (yksityisessä repossa 2 000 min/kk ilmaiseksi; ajo kestää 3–8 min/pv ≈ 150–250 min/kk) |
| GitHub Pages | 0 € |
| Rajapinnat (Hankeikkuna, eduskunta, Finlex, EP, Cellar) | 0 €, avointa dataa |
| Oma verkkotunnus (valinnainen) | ~10–15 €/v |
| Tekoälytiivistelmät (valinnainen, ei vielä kytketty) | muutama euro/kk Haiku-luokan mallilla |

## Lisenssi ja attribuutio

Lähdeaineistot ovat avointa dataa (valtioneuvosto, eduskunta, Finlex, EU). Mainitse lähde,
jos julkaiset aineistoa eteenpäin. Koodi: MIT.
