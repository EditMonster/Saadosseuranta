# Säädösseuranta

Automaattisesti päivittyvä seurantasivu kansallisesta ja EU-lainsäädännöstä:
lausuntoajat, eduskuntakäsittely, hyväksyminen, vahvistus, voimaantulot ja EU-määräajat
vaakasuuntaisina aikajanoina, suodatettavissa aihealueittain – sekä omina segmentteinään
julkisten hankintojen kilpailutukset (Hilma) koko elinkaarellaan ja yrityskauppavalvonnan
tapaukset (KKV ja Euroopan komissio) lakisääteisine määräaikoineen.

Sivu on staattinen (`docs/`), aineisto on kolme JSON-tiedostoa (`docs/data/items.json` säädökset,
`docs/data/hankinnat.json` kilpailutukset, `docs/data/yrityskaupat.json` yrityskaupat), ja
GitHub Actions ajaa hakuskriptit arkisin kolmesti päivässä (viikonloppuisin kerran) ja committaa muuttuneen aineiston. Käyttökustannus
on nolla: julkisen repon Actions-minuutit ja GitHub Pages ovat ilmaisia.

## Sivun näkymät

* **Tyyppi-suodatin** – Lait (HE), Asetukset, EU-säädökset, EU-delegoidut, EU-kuulemiset, U/E-kirjelmät; valinta muistetaan. Asetukset ovat oletuksena pois, muut päällä.
* **EU-säädösten neuvostovaiheet** – EU-aikajanalla näkyvät parlamentin vaiheiden lisäksi neuvoston yleisnäkemys, Coreperin neuvotteluvaltuudet, trilogit, Coreperin vahvistama alustava sopu, neuvoston ensimmäisen käsittelyn kanta ja säädöksen antaminen neuvostossa sekä viimeisin käsittely neuvoston työryhmässä, Coreperissa tai neuvostossa (lähde: julkaisutoimiston Cellarin menettelytapahtumat, entinen PreLex). Neuvoston kanta tai valtuudet vievät menettelyn tilaan *neuvotteluissa*.
* **EU-delegoidut** – komission hyväksymät delegoidut säädökset vastustamisaikana: koska komissio antoi säädöksen, kuinka pitkä parlamentin ja neuvoston vastustamisaika on (perussäädöksen mukaan 2 + 2 kk, finanssialan teknisissä standardeissa 1 tai 3 kk), pidennykset, ennakkoilmoitukset ettei vastusteta, vastustus, julkaisu EUVL:ssä ja voimaantulo. Tila *vastustamisaika* on EU-tason viimeinen vaikuttamisikkuna; *odottaa julkaisua* tarkoittaa, että aika on kulunut umpeen ilman vastustusta. Suomenkielinen nimi tulee EUVL-julkaisun myötä (Cellar); sitä ennen nimi on englanniksi. Vastustamisaika lasketaan hyväksymispäivästä (tai erikseen kirjatusta toimittamispäivästä) kuukausina.
* **Tilannekuva** – seurannassa olevat säädökset, *Mitä on muuttunut* (ajojen välinen muutosloki: uudet säädökset, uudet vaiheet, siirtyneet päivämäärät, tilan vaihtumiset), avoimet lausuntokierrokset, seuraavien 60 päivän vaiheet ja viimeisten 14 päivän tapahtumat.
* **Oma seuranta** – tähti ☆ minkä tahansa säädöksen kohdalla lisää sen seurantaan; *Vain seuranta* -kytkin rajaa kaikki näkymät seurattuihin. Aihealuevalinta muistetaan selaimessa, joten se toimii kategoriaseurantana. Seurantalista tallentuu selaimeen; Tilannekuvan *Seurannassa*-paneelin "Siirrä toiselle koneelle" antaa siirtolinkin tai koodin (tuonti yhdistää tai korvaa). Mitään käyttäjän tietoa ei lähetetä minnekään: sivu on pelkkiä staattisia tiedostoja, eikä toinen linkin saaja näe toisen tähtiä, kansioita tai piilotuksia. Sivu on suunniteltu työpöytäkäyttöön; kapealla näytöllä se toimii, mutta aikajana vaatii vaakavieritystä.
* **Kansiot ja piilotus** – *Hallitse*-painikkeesta (tai kohteen tiedoista) voi luoda nimettyjä kansioita (esim. asiakas, toimeksianto, "Lausuttavat") ja viedä niihin säädöksiä, EU-menettelyjä ja kilpailutuksia; sama kohde voi olla useassa kansiossa. Yläpalkin *Kansio*-valinta rajaa kaikki näkymät – myös Tilannekuvan laskurit ja paneelit – kansion kohteisiin, ja Tilannekuvan *Kansiot*-paneeli näyttää joka kansion seuraavan määräajan. Rivin × (näkyy hiirellä) tai tietojen *Piilota näkymistä* poistaa kohteen kaikista näkymistä ja laskureista; piilotetut löytyvät Kansio-valikon kohdasta *Piilotetut*, josta ne voi palauttaa (ja piilotuksen voi kumota heti ilmoituksesta). Kansiot, piilotukset ja tähdet tallentuvat selaimeen ja siirtyvät toiselle koneelle samalla siirtolinkillä kuin tähdet.
* **Kansallinen** ja **EU** – vaakasuuntaiset aikajanat (lausuntoaika, eduskunta-/lainsäädäntömenettely, voimaantulo, määräajat), lausuttavissa olevat kärjessä.
* **Valmiit** – vahvistetut ja voimassa olevat säädökset taulukkona.
* **Kilpailutukset** – Hilman hankintailmoitukset koko elinkaarellaan, vaihe valitaan välilehden yläreunasta:
  * *Avoinna* (oletus) – kaikki avoinna olevat hankintailmoitukset (kansalliset ja EU-kynnysarvon ylittävät) määräajan mukaan: kuinka monta päivää on aikaa tarjota (tai jättää osallistumishakemus), mitä hankitaan (hankintayksikön omasta kuvauksesta poimittu tiivistelmä, CPV-nimike, hankintalaji, menettely, arvioitu arvo, osat) ja linkki alkuperäiseen ilmoitukseen Hilmassa sekä tarjouspyyntöasiakirjoihin ja TED:iin. Dynaamiset hankintajärjestelmät (DPS, joihin voi hakea koko voimassaoloajan) ovat oletuksena piilossa *Myös DPS* -kytkimen takana.
  * *Tulossa* – ennakkoilmoitukset ja markkinakartoitukset eli hankinnat, joista ei vielä voi tarjota mutta joihin voi vaikuttaa (vastausaika markkinakartoitukseen näkyy lausuntoaikana).
  * *Ratkaistu* – viimeisten 30 päivän jälki-ilmoitukset: voittaja ja sopimuksen arvo. Hankintapäätöksestä voi valittaa 14 päivän kuluessa päätöksen tiedoksisaannista; koska tiedoksisaantipäivä ei ole julkinen, se näytetään huomautuksena eikä laskettuna päivänä.
  * *Suorahankinnat* – suorahankinnan avoimuusilmoitukset ja kansalliset suorahankintailmoitukset, joille lasketaan 14 päivän valitusajan päättyminen julkaisusta (hankintalaki 147 § 3 mom.; sopimuksen saa tehdä aikaisintaan 14 päivän kuluttua julkaisusta, 131 §).
  * *Markkinaoikeus* – markkinaoikeudessa vireillä olevat hankintavalitukset (markkinaoikeuden hankintalain 148 §:n 3 momentin nojalla julkaisema luettelo: vireilletulopäivä, hankintayksikkö, valituksenalainen hankintapäätös) ja viimeisten 90 päivän ratkaisut (valittaja, hankintayksikkö, asiasanat, diaarinumero, lopputulos luokiteltuna: valitus hylätty, hankintapäätös kumottu, hyvitysmaksu, tehottomuusseuraamus, jätetty tutkimatta, välipäätös …). Vireillä oleva asia yhdistetään ratkaisuunsa hankintayksikön ja hankintapäätöksen päivän perusteella, ja ratkaisu Hilma-ilmoitukseen hankintayksikön ja ratkaisussa mainitun ilmoituspäivän perusteella – silloin valitus näkyy myös Hilma-ilmoituksen tiedoissa. Ratkaisun jälkeen aikajanalle merkitään valitusajan KHO:een päättyminen arviona (30 pv antopäivästä; valituslupa, hankintalaki 165 §), koska tiedoksisaantipäivä ei ole julkinen.

  Saman hankintamenettelyn ilmoitukset (ennakkoilmoitus → hankintailmoitus → korjausilmoitus → jälki-ilmoitus) on linkitetty toisiinsa: kohteen tiedoissa on *Saman hankinnan muut ilmoitukset* ja sen aikajanalla näkyvät kaikki vaiheet. Suodattimet: *Toimiala* (15 CPV-pohjaista luokkaa, `config/hankinnat.yaml`), EU-kynnysarvo / kansallinen, sulkeutuu (tai ratkaistu) 7/14/30 pv, haku. Tähditetty kilpailutus näkyy Tilannekuvan *Seurannassa*-paneelissa ja säilyy 14 päivää määräajan jälkeen tilassa *päättynyt* (tai *poistunut*, jos ilmoitus katosi Hilmasta ennen määräaikaa).
* **Yrityskaupat** – yrityskauppavalvonnan vireillä olevat tapaukset KKV:ssa ja Euroopan komissiossa (DG COMP) aikajanana, jossa näkyvät viranomaisen omat lakisääteiset määräajat: KKV:n tapauksista ilmoituksen saapuminen, kuulemisen määräaika (jolloin kilpailija tai asiakas voi lausua), ensimmäisen vaiheen määräaika (23 työpäivää), jatkokäsittelyyn siirrettyjen jatkokäsittelyn määräaika (69 työpäivää) sekä KKV:n kieltoesitys markkinaoikeudelle ja markkinaoikeuden ratkaisun määräaika (3 kk esityksestä, kilpailulaki 29 §) ja ratkaisu (tila *kieltoesitys markkinaoikeudessa*, kunnes markkinaoikeus ratkaisee asian); komission tapauksista ilmoituspäivä, EUVL:n ennakkoilmoitus ja sen avaama kolmansien huomautusaika (yleensä 10 päivää julkaisusta – EU-tason "milloin voi lausua"), komission julkaisema alustava määräaika (vaihe 1: 25 työpäivää; vaihe 2 pidempi), kellon keskeytykset tietopyynnön vuoksi (11 art. 3 kohta), määräajan pidennykset (10 art. 3 kohta), sitoumusten toimittaminen, väitetiedoksianto ja päätökset oikeusperustoineen (6(1)(b), 6(1)(c), 8(2) …). EUVL:n ennakkoilmoituksesta luetaan myös **osapuolet kotimaineen**, joten komission tapauksista tunnistetaan ne, joissa on suomalainen osapuoli (merkintä *FI-osapuoli*, suodatin *Suomalainen osapuoli*; myös suomalaisen emoyhtiön määräysvallassa oleva osapuoli lasketaan). Suodattimet: *Toimiala* (KKV-tapaukset omana luokkanaan, komission tapaukset NACE-pääluokan mukaan), KKV / komissio, *Vain vireillä* (oletus; pois päältä näkyvät myös viimeisten 90 päivän päätökset: hyväksytty sellaisenaan, ehdollisena, kielletty, peruutettu), *Suomalainen osapuoli*; haku löytää myös osapuolen nimellä. Kohteen tiedoissa on tapauksen tiivistelmä (KKV:n oma tiivistelmä tai ilmoittajan kuvaus kaupasta; komission tapauksista EUVL-ilmoituksen kuvaus kaupasta ja osapuolten liiketoiminnasta), osapuolet, huomautusajan päättyminen ja linkit KKV:n tapaussivulle ja päätökseen tai komission tapaussivulle ja EUVL-ilmoitukseen. Määräaikoja ei lasketa itse – ne luetaan viranomaisen sivulta, jotta kellon pysäytykset ja pidennykset tulevat oikein. Tilannekuvan *Yrityskauppoja vireillä* -laskuri vie välilehdelle; KKV:n kuulemiset ja suomalaisosapuolisten komission tapausten huomautusajat näkyvät *Lausuntokierrokset käynnissä* -paneelissa ja niiden määräajat *Seuraavat 60 päivää* -listassa.
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
| Hilma (hankintailmoitukset.fi) | Kaikki avoimet hankintailmoitukset, voimassa olevat ennakkoilmoitukset ja markkinakartoitukset, viimeisten 30 päivän jälki-ilmoitukset (voittaja, arvo) sekä suorahankintailmoitukset: määräaika, kuvaus, hankintayksikkö, CPV, menettely, arvioitu arvo, osat, linkit ilmoitukseen ja tarjouspyyntöön; saman menettelyn ilmoitukset linkitetään `procedureId`-tunnuksella; CPV-nimikkeistö suomeksi. Suomalaiset EU-kynnysarvon ylittävät ilmoitukset julkaistaan Hilman kautta myös TED:issä, joten TED:iä ei tarvita erikseen | `https://www.hankintailmoitukset.fi/search/eformnotices` – sama julkinen hakuindeksi, jota Hilman oma hakusivu käyttää (ei avainta). Varalla dokumentoitu *Hilma avoin rajapinta* (`api.hankintailmoitukset.fi/avp`), joka vaatii maksuttoman API-avaimen |
| KKV – yrityskauppavalvonta | Vireillä olevat yrityskaupat (diaarinumero, osapuolet, ilmoituksen saapuminen, kuulemisen määräaika, 1. vaiheen määräaika, jatkokäsittelyn siirto ja määräaika, ilmoittajan kuvaus kaupasta) sekä viimeisten 90 päivän päätökset | `kkv.fi/paatokset/vireilla-olevat-yrityskaupat/` ja `…/kilpailuasiat/yrityskauppavalvonta/` (HTML; sivuston oma REST-rajapinta ei julkaise näitä sisältötyyppejä) |
| Euroopan komissio, DG COMP | Komissiolle viimeisten 120 päivän aikana ilmoitetut yrityskaupat ja kaikki vaiheen 2 tutkinnat: ilmoituspäivä, alustava määräaika, vaihe, yksinkertaistettu menettely, NACE-toimiala, komission määräaikatapahtumat (keskeytykset, pidennykset, sitoumukset), päätökset oikeusperustoineen | `webgate.ec.europa.eu/es/search-api` – sama julkinen hakurajapinta, jota `competition-cases.ec.europa.eu` käyttää (ei kirjautumista) |
| EU:n virallinen lehti (Cellar) | Yrityskeskittymien ennakkoilmoitukset suomeksi: osapuolet kotimaineen, kaupan kuvaus, osapuolten liiketoiminta, huomautusaika | `publications.europa.eu/resource/oj/C_<vuosi><numero>` (XHTML, `Accept-Language: fi`); EUR-Lex itse on botti­suojan takana, joten se on vain linkkinä |
| EU:n julkaisutoimiston Cellar (menettelytapahtumat) | Neuvoston käsittelyvaiheet EU-menettelyissä: yleisnäkemys, Coreperin neuvotteluvaltuudet, trilogit, alustavan sovun vahvistaminen, neuvoston kanta, säädöksen antaminen, viimeisin käsittely valmisteluelimissä | SPARQL `cdm:event_legal_part_of_dossier` + `cdm:event_legal_type` (entinen PreLex); tapahtumatyyppien koodit ja suomennokset `config/neuvosto.yaml` |
| Komission delegoitujen säädösten rekisteri | Hyväksytyt delegoidut säädökset vastustamisaikana ja viimeisten 90 päivän aikana julkaistut: hyväksymispäivä, vastustamisajat toimielimittäin, pidennykset, ennakkoilmoitukset, vastustus, julkaisu; perussäädös ja pääosasto | `webgate.ec.europa.eu/regdel/web/` – rekisterin oman selainsovelluksen JSON-rajapinta (CSRF-eväste yhdellä GET-pyynnöllä, ei kirjautumista) |
| Markkinaoikeus | Vireillä olevat hankinta-asiat (hankintalaki 148 § 3 mom.) ja ratkaisut hankinta- sekä kilpailuasioissa (osapuolet, asiasanat, tausta, lopputulos) | `markkinaoikeus.fi/vireilla-olevat-hankinta-asiat/` ja `…/ratkaisut/…` (HTML + RSS; ei REST-rajapintaa) |

Mitä **ei** seurata (lisättävissä): neuvoston työryhmien asialistat ja asiakirjat (vain Cellariin kirjatut
vaiheet), täytäntöönpanosäädökset komiteamenettelyssä, KHO:n ratkaisut hankinta-asioissa, unionin tuomioistuin,
kansalaisaloitteet. Hankinnoista ei seurata muiden maiden TED-ilmoituksia eikä Hilman
ulkopuolisia pienhankintoja; kilpailutusten tiivistelmä on poimiva (ei kielimallia), joten se on aina hankintayksikön
omaa tekstiä. Yrityskaupoista ei seurata markkinaoikeuden käsittelyä (KKV:n kieltoesitykset näkyvät päätöksenä), eikä
komission tapausten suomalaisuutta tunnisteta ennen EUVL-ilmoituksen julkaisua (muutama päivä ilmoituksesta) – siihen asti ne löytyvät haulla otsikon nimellä. `lausuntopalvelu.fi` ja `valtioneuvosto.fi` estävät ohjelmalliset
haut (Cloudflare), joten lausuntokierrokset tulevat Hankeikkunasta, joka on sama tieto.

## Rakenne

```
config/
  settings.yaml      EU-vuodet, menettelytyypit, Valmiit-sivun aikaraja, Hilma- ja yrityskauppa-asetukset
  topics.yaml        aihealueiden avainsanat (muokkaa vapaasti)
  hankinnat.yaml     kilpailutusten toimialat (CPV-etuliitteet), ilmoitustyyppien ja menettelyjen nimet, suorahankintatyypit ja valitusaika, tiivistelmäsäännöt
  yrityskaupat.yaml  komission päätöstyyppien ja KKV:n ratkaisujen suomennokset ja tilat, NACE-pääluokat, kieltoesityksen määräaika
  neuvosto.yaml      neuvoston käsittelyvaiheiden tapahtumakoodit (Cellar) ja niiden nimet aikajanalla
  delegoidut.yaml    delegoitujen säädösten tilat, toimielimet ja pääosasto -> aihealue -varasääntö
  eu_watchlist.yaml  EU-menettelyt, jotka haetaan aina
  overrides.json     käsin lisätyt tapahtumat, korjaukset ja lyhyet näyttönimet (id:n mukaan)
scripts/
  fetch_hankeikkuna.py  fetch_eduskunta.py  fetch_finlex.py  fetch_eu.py  fetch_ue.py  fetch_hys.py
  fetch_hankinnat.py  fetch_kkv.py  fetch_eu_mergers.py  eu_notice.py (EUVL:n ennakkoilmoitusten jäsennys)
  fetch_regdel.py (delegoitujen säädösten rekisteri)  fetch_mao.py (markkinaoikeus)  build_mao.py
  build.py           yhdistää välimuistit -> docs/data/items.json (+ build_hankinnat.py -> hankinnat.json, build_yrityskaupat.py -> yrityskaupat.json)
  update.py          ajaa kaiken; yhden lähteen virhe ei kaada muita; kirjaa lähteiden tilan health.json-tiedostoon
  health_report.py   lähdevahti: avaa/sulkee GitHub-issuen lähteen epäonnistuessa toistuvasti
tests/               eheystestit (test_data.py) ja selaimen savutesti (test_smoke.py)
data/cache/          lähdekohtaiset välimuistit (committataan, jotta päivitys on nopea; Hilma-välimuisti haetaan joka ajossa eikä sitä versioida)
docs/                GitHub Pages -sivu: index.html, logot, data/items.json + hankinnat.json + yrityskaupat.json + meta.json + changes.json + saadosseuranta.ics
.github/workflows/update.yml   ajastettu ajo (arkisin 3×, viikonloppuisin 1×) -> eheystestit -> commit -> lähdevahti -> julkaisu
.github/workflows/deploy.yml   testit joka pushille ja Pages-julkaisu testien takana
.github/workflows/vahti.yml    päivitysvahti: aineiston ikä julkaistulla sivulla, työnkulun käytössäolo, uudelleenkäynnistys, issue
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
  `hankinnat.min_items` ilmoitusta tai haku epäonnistuu, edellinen `hankinnat.json` jää voimaan. Jälki-ilmoituksia
  näytetään `hankinnat.award_days` päivää (30).
* **Neuvoston vaiheet**: `config/neuvosto.yaml` – lisää tapahtumakoodi (julkaisutoimiston `resource/authority/event`)
  ja sen nimi; `pida: last` näyttää toistuvasta vaiheesta vain viimeisimmän. Haku tehdään kaikille menettelyille
  muutamalla eräkyselyllä joka ajossa.
* **Delegoidut säädökset**: `config/settings.yaml` → `delegoidut.keep_days` (julkaistujen näkyvyys) ja `stale_days`;
  `config/delegoidut.yaml` → tilat ja pääosasto → aihealue -varasääntö, kun avainsanat eivät osu englanninkieliseen nimeen.
* **Markkinaoikeus**: `config/settings.yaml` → `markkinaoikeus.keep_days` ja `kho_valitusaika_paivia`;
  `config/hankinnat.yaml` → `mao_toimialat` (avainsanat, joilla hankintapäätöksen kuvaus luokitellaan toimialaan).
* **Yrityskaupat**: `config/settings.yaml` → `yrityskaupat.keep_decided_days` (kuinka kauan päätetyt näkyvät, 90) ja
  `eu_notified_days` (kuinka vanhoja komission ilmoituksia haetaan, 120; vaiheen 2 tapaukset haetaan aina). EUVL-ilmoitus
  haetaan kerran per tapaus (enintään 60 uutta per ajo) ja säilytetään välimuistissa; jäsennyksen epäonnistuminen ei kaada
  ajoa, tapaus näkyy silloin ilman osapuolia. KKV:n sivuston rakenteen muutos näkyy lähdevahdissa (`kkv`), komission
  rajapinnan muutos lähteenä `eu_mergers`.
* **Uusi EU-säädös seurantaan**: lisää menettelytunnus `config/eu_watchlist.yaml`-tiedostoon.
* **Käsin tunnettu päivämäärä** (esim. omnibus-asetuksen siirtämä soveltamispäivä): `config/overrides.json`.
  Käsin lisätyt päivät näkyvät katkoviivalla ja merkinnällä "tarkistamaton", ellei `confirmed: true`.
* Finlex rajoittaa pyyntöjä: voimaantulot haetaan enintään 200 säädökselle per ajo, loput seuraavana
  päivänä. Jo haetut säilyvät välimuistissa.
* Jos jokin lähde on alhaalla, ajo käyttää sen edellistä välimuistia ja kirjaa virheen lokiin.

## Laadunvarmistus

* **Testit** (`tests/`): `test_data.py` tarkistaa rakennetun aineiston rakenteen ja määrät (tunnisteet, päivämäärät,
  linkit, laskurit, kalenteritiedosto) alle sekunnissa; `test_smoke.py` ajaa sivun oikeassa selaimessa (Playwright +
  Chromium) ja käy läpi välilehdet, kohteen avaamisen, tähden, kansioon lisäämisen, piilotuksen, suodattimet,
  siirtokoodin, teeman ja pysyvän linkin – myös sen, että valinnat säilyvät uudelleenlatauksen yli. Paikallisesti:
  `pip install -r requirements-dev.txt && python -m playwright install chromium && pytest`.
* **Jokainen push** ajaa testit (`deploy.yml`). Kun Pagesin lähteeksi on valittu **Settings → Pages → Source:
  GitHub Actions**, sivu julkaistaan vasta testien mentyä läpi, eli rikkinäinen versio ei korvaa toimivaa. Jos lähde
  on vielä *Deploy from a branch*, testit ajetaan silti ja epäonnistuminen näkyy commitin punaisena ruksina.
* **Päivitysajo** ajaa eheystestit ennen aineiston committia; `build.py`:n raja-arvot estävät lisäksi tyhjän tai
  epäilyttävän pienen aineiston julkaisun.
* **Lähdevahti**: jokaisen lähteen onnistuminen kirjataan (`data/cache/health.json`). Jos lähde epäonnistuu kolme
  ajoa peräkkäin, `scripts/health_report.py` avaa repoon issuen (GitHub lähettää siitä sähköpostin) ja sulkee sen
  itsestään, kun lähde toipuu. Sivun yläpalkki näyttää samalla varoituksen "Lähde ei päivity" – muut lähteet ja
  edellinen onnistunut aineisto pysyvät käytössä.
* **Päivitysvahti** (`vahti.yml`, päivittäin 07:20 UTC, `scripts/vahti.py`): lukee julkaistun sivun `meta.json`-tiedoston
  ja laskee aineiston iän. Jos aineisto on yli 30 tuntia vanhaa, vahti käynnistää päivitysajon uudelleen ja avaa issuen
  *Päivitys on pysähtynyt* (sulkeutuu itsestään, kun aineisto on taas tuoretta). Samalla se varmistaa, että `update.yml`
  on käytössä, ja kutsuu GitHubin enable-rajapintaa – GitHub poistaa ajastetut työnkulut käytöstä 60 päivän hiljaiselon
  jälkeen, ja kutsu nollaa laskurin. Päivitysajo itse raportoi tuloksensa: epäonnistunut ajo avaa issuen *Päivitysajo
  epäonnistui* (linkki lokiin), seuraava onnistunut sulkee sen. Sivun yläpalkki varoittaa, jos aineisto on yli 36 tuntia
  vanhaa. GitHubin ajastus on parhaan kyvyn mukainen: ajot alkavat tyypillisesti 5–30 minuuttia myöhässä, hiljaisessa
  repossa joskus tunteja, ja yksittäinen ajo voi jäädä väliin – siksi raja on 30 tuntia eikä esimerkiksi 8.
* **Botin push ei kaadu käsin tehtyyn pushiin**: jos main on liikkunut ajon aikana, aineistocommit rebasetaan ja push
  yritetään uudelleen (kolmesti).

### Mitä tehdä, jos sähköpostiin tulee issue

| Issue | Mitä se tarkoittaa | Mitä tehdä |
|---|---|---|
| *Lähde ei päivity* (`lahdevahti`) | Yksi lähde on epäonnistunut ≥ 3 ajoa; sivu näyttää sen osalta edellistä aineistoa | Avaa ajon loki (Actions → Päivitä säädösaineisto): usein lähteen rakenne tai osoite on muuttunut → korjaa `scripts/fetch_*.py`. Issue sulkeutuu itsestään, kun lähde toipuu. |
| *Päivitysajo epäonnistui* (`ajovirhe`) | Koko ajo kaatui (esim. build-raja-arvo, testi, GitHubin verkko) | Katso loki; yksittäinen kerta korjaantuu yleensä seuraavassa ajossa. Jos `Aineiston eheys` -testi kaatuu, lähde on muuttanut tietosisältöä – korjaa jäsennys tai testin oletus. |
| *Päivitys on pysähtynyt* (`paivitysvahti`) | Julkaistu aineisto on yli 30 h vanhaa – ajo ei käynnisty tai ei julkaise | Vahti on jo käynnistänyt ajon uudelleen. Jos issue ei sulkeudu vuorokaudessa: Actions-välilehdellä tarkista, että *Päivitä säädösaineisto* on käytössä (Enable workflow) ja aja se käsin; tarkista Settings → Pages. |

### Pitkän ajan ylläpito

* **Repon koko kasvaa** noin 0,5–1 MB per aineistocommit (pakattuna), eli suuruusluokkaa 0,3–0,5 GB vuodessa. GitHub
  suosittelee alle 1 GB:n repoja; ennen sitä aineistohistoria kannattaa tiivistää (`git filter-repo` `docs/data`- ja
  `data/cache`-poluille, pakotettu push) tai siirtää julkaisu Pages-artefaktiksi (Settings → Pages → Source: GitHub
  Actions), jolloin `docs/data` voidaan jättää versioimatta. Actions käyttää matalaa kloonia, joten CI ei hidastu sitä ennen.
* **Dependabot** tekee kuukausittain PR:t toimintojen ja kirjastojen päivityksistä; testit ajetaan PR:lle ennen yhdistämistä.
* **Pages-lähteen vaihto** `GitHub Actions` -tilaan on edelleen suositeltava käsin tehtävä asetus: silloin myös käsin tehty
  rikkinäinen push ei pääse julkaistuun sivuun ennen testejä.

## Kustannus

| Erä | Hinta |
|---|---|
| GitHub Actions, julkinen repo | 0 € (yksityisessä repossa 2 000 min/kk ilmaiseksi; 3 ajoa/arkipäivä × ~8 min ≈ 550 min/kk) |
| GitHub Pages | 0 € |
| Rajapinnat (Hankeikkuna, eduskunta, Finlex, EP, Cellar, Have your say, Hilma, KKV, komissio, EUVL, delegoitujen säädösten rekisteri, markkinaoikeus) | 0 €, avointa dataa |
| Oma verkkotunnus (valinnainen) | ~10–15 €/v |
| Tekoälytiivistelmät (valinnainen, ei vielä kytketty) | muutama euro/kk Haiku-luokan mallilla |

## Lisenssi ja attribuutio

Lähdeaineistot ovat avointa dataa (valtioneuvosto, eduskunta, Finlex, EU, Hilma, KKV, Euroopan komissio, markkinaoikeus). Mainitse lähde,
jos julkaiset aineistoa eteenpäin. Koodi: MIT.
