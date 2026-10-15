# Säädösseuranta

Automaattisesti päivittyvä seurantasivu kansallisesta ja EU-lainsäädännöstä:
lausuntoajat, eduskuntakäsittely, hyväksyminen, vahvistus, voimaantulot ja EU-määräajat
vaakasuuntaisina aikajanoina, suodatettavissa aihealueittain – sekä omana segmenttinään
julkisten hankintojen avoimet kilpailutukset (Hilma) määräajan mukaan.

Sivu on staattinen (`docs/`), aineisto on kaksi JSON-tiedostoa (`docs/data/items.json` säädökset,
`docs/data/hankinnat.json` kilpailutukset), ja
GitHub Actions ajaa hakuskriptit arkisin kolmesti päivässä (viikonloppuisin kerran) ja committaa muuttuneen aineiston. Käyttökustannus
on nolla: julkisen repon Actions-minuutit ja GitHub Pages ovat ilmaisia.

## Sivun näkymät

* **Tyyppi-suodatin** – Lait (HE), Asetukset, EU-säädökset, EU-kuulemiset, U/E-kirjelmät; valinta muistetaan. Asetukset ovat oletuksena pois, muut päällä.
* **Tilannekuva** – seurannassa olevat säädökset, *Mitä on muuttunut* (ajojen välinen muutosloki: uudet säädökset, uudet vaiheet, siirtyneet päivämäärät, tilan vaihtumiset), avoimet lausuntokierrokset, seuraavien 60 päivän vaiheet ja viimeisten 14 päivän tapahtumat.
* **Oma seuranta** – tähti ☆ minkä tahansa säädöksen kohdalla lisää sen seurantaan; *Vain seuranta* -kytkin rajaa kaikki näkymät seurattuihin. Aihealuevalinta muistetaan selaimessa, joten se toimii kategoriaseurantana. Seurantalista tallentuu selaimeen; Tilannekuvan *Seurannassa*-paneelin "Siirrä toiselle koneelle" antaa siirtolinkin tai koodin (tuonti yhdistää tai korvaa). Sivu on suunniteltu työpöytäkäyttöön; kapealla näytöllä se toimii, mutta aikajana vaatii vaakavieritystä.
* **Kansallinen** ja **EU** – vaakasuuntaiset aikajanat (lausuntoaika, eduskunta-/lainsäädäntömenettely, voimaantulo, määräajat), lausuttavissa olevat kärjessä.
* **Valmiit** – vahvistetut ja voimassa olevat säädökset taulukkona.
* **Kilpailutukset** – kaikki Hilmassa avoinna olevat hankintailmoitukset (kansalliset ja EU-kynnysarvon ylittävät) määräajan mukaan: kuinka monta päivää on aikaa tarjota (tai jättää osallistumishakemus), mitä hankitaan (hankintayksikön omasta kuvauksesta poimittu tiivistelmä, CPV-nimike, hankintalaji, menettely, arvioitu arvo, osat) ja linkki alkuperäiseen ilmoitukseen Hilmassa sekä tarjouspyyntöasiakirjoihin ja TED:iin. Suodattimet: *Toimiala* (15 CPV-pohjaista luokkaa, `config/hankinnat.yaml`), EU-kynnysarvo / kansallinen, sulkeutuu 7/14/30 pv, haku. Dynaamiset hankintajärjestelmät (DPS, joihin voi hakea koko voimassaoloajan) ovat oletuksena piilossa *Myös DPS* -kytkimen takana. Tähditetty kilpailutus näkyy Tilannekuvan *Seurannassa*-paneelissa ja säilyy 14 päivää määräajan jälkeen tilassa *päättynyt* (tai *poistunut*, jos ilmoitus katosi Hilmasta ennen määräaikaa).
* Jokaisella säädöksellä on pysyvä linkki (`…/#fi-he-129-2026`), joka avaa sen aikajanan suoraan.
* `data/saadosseuranta.ics` – kaikki tulevat määräajat kalenteriin (Google/Outlook/Apple: "tilaa kalenteri osoitteesta").
* Ulkoasu valittavissa yläpalkista: *Vaalea* (oletus) tai *Tumma*; valinta muistetaan selaimessa.

## Mistä aineisto tulee

| Lähde | Mitä haetaan | Rajapinta |
|---|---|---|
| Valtioneuvoston Hankeikkuna | Kaikki hallituksen esitysten valmisteluhankkeet (käynnissä + 18 kk:n sisällä päättyneet): lausuntokierrokset, kuulemiset, HE-numerot, säädöskokoelman numerot, lausuntopyynnöt, vastuuministeriö, teemat | `POST https://api.hankeikkuna.fi/api/v2/kohteet/haku` (avoin, ei avainta) |
| Eduskunnan avoin data | Jokaisen HE:n käsittelytiedot: annettu, lähetekeskustelu, valiokunnan mietintö, 1. ja 2. käsittely, eduskunnan vastaus, vahvistuspäivä, säädöskokoelman numero, HE-tekstistä ehdotettu voimaantulo | `https://avoindata.eduskunta.fi/api/v1/tables/VaskiData/rows` |
| Finlex | Vireillä olevien HE:iden luettelo ministeriöittäin (varmistus, ettei mikään HE jää Hankeikkunan ulkopuolelle) sekä vahvistettujen lakien voimaantulopäivät säädöskokoelmasta | `finlex.fi` (HTML, rajoitettu nopeus) |
| Euroopan parlamentin avoin data | Tavallisen lainsäätämisjärjestyksen menettelyt (2021–): suomenkieliset nimet, valiokunta- ja täysistuntovaiheet, alustava sopu, allekirjoitus, EUVL-julkaisu | `https://data.europarl.europa.eu/api/v2/procedures` |
| EU:n julkaisutoimiston Cellar | Komission ehdotuksen päivä, hyväksytyn säädöksen CELEX-numero, voimaantulo, vaiheittaiset soveltamispäivät, täytäntöönpanon määräajat, voimassaolo | SPARQL `https://publications.europa.eu/webapi/rdf/sparql` |
| Valtioneuvoston Hankeikkuna (asetukset) | Valtioneuvoston ja ministeriöiden asetushankkeet: lausuntokierrokset, antaminen, säädöskokoelman numero (Tyyppi-suodatin *Asetukset*, oletuksena pois) | sama rajapinta, tehtäväluokka `ASETUKSEN_ANTAMINEN` |
| Eduskunnan avoin data (U/E) | Valtioneuvoston U-kirjelmät ja E-kirjeet eli Suomen kannat EU-ehdotuksiin: liitetään vaiheena seurattuun EU-menettelyyn COM-numeron perusteella, muuten omana rivinään | `VaskiData`, tunnukset `U n/vuosi vp`, `E n/vuosi vp` |
| Komission Have your say | Julkiset kuulemiset, kannanottopyynnöt ja palauteajat ehdotuksista sekä delegoiduista ja täytäntöönpanosäädöksistä (EU-tason "milloin voi lausua") | `https://ec.europa.eu/info/law/better-regulation/brpapi/searchInitiatives` |
| Hilma (hankintailmoitukset.fi) | Kaikki avoimet hankintailmoitukset: määräaika, kuvaus, hankintayksikkö, CPV, menettely, arvioitu arvo, osat, linkit ilmoitukseen ja tarjouspyyntöön; CPV-nimikkeistö suomeksi. Suomalaiset EU-kynnysarvon ylittävät ilmoitukset julkaistaan Hilman kautta myös TED:issä, joten TED:iä ei tarvita erikseen | `https://www.hankintailmoitukset.fi/search/eformnotices` – sama julkinen hakuindeksi, jota Hilman oma hakusivu käyttää (ei avainta). Varalla dokumentoitu *Hilma avoin rajapinta* (`api.hankintailmoitukset.fi/avp`), joka vaatii maksuttoman API-avaimen |

Mitä **ei** seurata (lisättävissä): neuvoston käsittelyvaiheet (yleisnäkemys, hyväksyntä – neuvostolla
ei ole yksinkertaista avointa rajapintaa), hyväksytyt delegoidut säädökset muuten kuin kuulemisvaiheessa,
tuomioistuinratkaisut, kansalaisaloitteet. Hankinnoista ei seurata ennakkoilmoituksia ja markkinakartoituksia,
jälki-ilmoituksia, muiden maiden TED-ilmoituksia eikä Hilman ulkopuolisia pienhankintoja; kilpailutusten
tiivistelmä on poimiva (ei kielimallia), joten se on aina hankintayksikön omaa tekstiä. `lausuntopalvelu.fi` ja `valtioneuvosto.fi` estävät ohjelmalliset
haut (Cloudflare), joten lausuntokierrokset tulevat Hankeikkunasta, joka on sama tieto.

## Rakenne

```
config/
  settings.yaml      EU-vuodet, menettelytyypit, Valmiit-sivun aikaraja, Hilma-asetukset
  topics.yaml        aihealueiden avainsanat (muokkaa vapaasti)
  hankinnat.yaml     kilpailutusten toimialat (CPV-etuliitteet), ilmoitustyyppien ja menettelyjen nimet, tiivistelmäsäännöt
  eu_watchlist.yaml  EU-menettelyt, jotka haetaan aina
  overrides.json     käsin lisätyt tapahtumat, korjaukset ja lyhyet näyttönimet (id:n mukaan)
scripts/
  fetch_hankeikkuna.py  fetch_eduskunta.py  fetch_finlex.py  fetch_eu.py  fetch_ue.py  fetch_hys.py  fetch_hankinnat.py
  build.py           yhdistää välimuistit -> docs/data/items.json (+ kutsuu build_hankinnat.py -> docs/data/hankinnat.json)
  update.py          ajaa kaiken; yhden lähteen virhe ei kaada muita
data/cache/          lähdekohtaiset välimuistit (committataan, jotta päivitys on nopea; Hilma-välimuisti haetaan joka ajossa eikä sitä versioida)
docs/                GitHub Pages -sivu: index.html, logot, data/items.json + hankinnat.json + meta.json + changes.json + saadosseuranta.ics
.github/workflows/update.yml   ajastettu ajo (arkisin 3×, viikonloppuisin 1×)
```

## Käyttöönotto

1. Luo GitHub-repo ja työnnä tämä sisältö sinne.
2. **Settings → Pages → Source: Deploy from a branch → `main` / `/docs`.** Sivu tulee osoitteeseen
   `https://<käyttäjä>.github.io/<repo>/`.
3. **Settings → Actions → General → Workflow permissions: Read and write permissions** (jotta
   workflow voi committata aineiston).
4. Aja workflow kerran käsin: **Actions → Päivitä säädösaineisto → Run workflow.** Sen jälkeen se
   ajaa itsensä arkisin kolmesti (7:40, 12:40 ja 16:40 Suomen talviaikaa) ja viikonloppuisin kerran aamulla.

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
* **Kilpailutusten toimialat**: `config/hankinnat.yaml` – lisää tai siirrä CPV-etuliitteitä (pisin täsmäävä
  etuliite voittaa; esim. `791` = lakipalvelut erotettuna muusta 79-luokasta). Jos Hilma palauttaa alle
  `hankinnat.min_items` ilmoitusta tai haku epäonnistuu, edellinen `hankinnat.json` jää voimaan.
* **Uusi EU-säädös seurantaan**: lisää menettelytunnus `config/eu_watchlist.yaml`-tiedostoon.
* **Käsin tunnettu päivämäärä** (esim. omnibus-asetuksen siirtämä soveltamispäivä): `config/overrides.json`.
  Käsin lisätyt päivät näkyvät katkoviivalla ja merkinnällä "tarkistamaton", ellei `confirmed: true`.
* Finlex rajoittaa pyyntöjä: voimaantulot haetaan enintään 200 säädökselle per ajo, loput seuraavana
  päivänä. Jo haetut säilyvät välimuistissa.
* Jos jokin lähde on alhaalla, ajo käyttää sen edellistä välimuistia ja kirjaa virheen lokiin.

## Kustannus

| Erä | Hinta |
|---|---|
| GitHub Actions, julkinen repo | 0 € (yksityisessä repossa 2 000 min/kk ilmaiseksi; 3 ajoa/arkipäivä × ~8 min ≈ 550 min/kk) |
| GitHub Pages | 0 € |
| Rajapinnat (Hankeikkuna, eduskunta, Finlex, EP, Cellar, Have your say, Hilma) | 0 €, avointa dataa |
| Oma verkkotunnus (valinnainen) | ~10–15 €/v |
| Tekoälytiivistelmät (valinnainen, ei vielä kytketty) | muutama euro/kk Haiku-luokan mallilla |

## Lisenssi ja attribuutio

Lähdeaineistot ovat avointa dataa (valtioneuvosto, eduskunta, Finlex, EU, Hilma). Mainitse lähde,
jos julkaiset aineistoa eteenpäin. Koodi: MIT.
