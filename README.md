# Säädösseuranta

Automaattisesti päivittyvä seurantasivu kansallisesta ja EU-lainsäädännöstä:
lausuntoajat, eduskuntakäsittely, hyväksyminen, vahvistus, voimaantulot ja EU-määräajat
vaakasuuntaisina aikajanoina, suodatettavissa aihealueittain – sekä omina segmentteinään
julkisten hankintojen kilpailutukset (Hilma) koko elinkaarellaan ja yrityskauppavalvonnan
tapaukset (KKV ja Euroopan komissio) lakisääteisine määräaikoineen.

Sivu on staattinen (`docs/`), aineisto on kolme JSON-tiedostoa (`docs/data/items.json` säädökset,
`docs/data/hankinnat.json` kilpailutukset, `docs/data/yrityskaupat.json` yrityskaupat), ja
GitHub Actions ajaa hakuskriptit arkisin klo 7, 12 ja 16 ja viikonloppuisin klo 9 (Suomen aikaa) ja committaa muuttuneen aineiston; epäonnistuneet lähteet yritetään uudelleen tunnin välein. Käyttökustannus
on nolla: julkisen repon Actions-minuutit ja GitHub Pages ovat ilmaisia.

## Sivun näkymät

* **Tyyppi-suodatin** – Lait (HE), Asetukset, EU-säädökset, EU-delegoidut, EU-täytäntöönpano (komitologia), EU-pakotteet, Kuulemiset (komissio, Fiva, ESMA/EBA/EIOPA, EDPB), Viranomaisohjeet (Verohallinto, Fiva, Traficom, EDPB), U/E-kirjelmät, Signaalit (lainsäädäntösuunnitelma, kirjalliset kysymykset ja aloitteet, komission suunnitelmat, rikkomusmenettelyt, neuvoston kokousmuistiot); valinta muistetaan. Asetukset, EU-täytäntöönpano ja EU-pakotteet ovat oletuksena pois, muut päällä.
* **EU-säädösten neuvostovaiheet** – EU-aikajanalla näkyvät parlamentin vaiheiden lisäksi neuvoston yleisnäkemys, Coreperin neuvotteluvaltuudet, trilogit, Coreperin vahvistama alustava sopu, neuvoston ensimmäisen käsittelyn kanta ja säädöksen antaminen neuvostossa sekä viimeisin käsittely neuvoston työryhmässä, Coreperissa tai neuvostossa (lähde: julkaisutoimiston Cellarin menettelytapahtumat, entinen PreLex). Neuvoston kanta tai valtuudet vievät menettelyn tilaan *neuvotteluissa*.
* **EU-delegoidut** – komission hyväksymät delegoidut säädökset vastustamisaikana: koska komissio antoi säädöksen, kuinka pitkä parlamentin ja neuvoston vastustamisaika on (perussäädöksen mukaan 2 + 2 kk, finanssialan teknisissä standardeissa 1 tai 3 kk), pidennykset, ennakkoilmoitukset ettei vastusteta, vastustus, julkaisu EUVL:ssä ja voimaantulo. Tila *vastustamisaika* on EU-tason viimeinen vaikuttamisikkuna; *odottaa julkaisua* tarkoittaa, että aika on kulunut umpeen ilman vastustusta. Suomenkielinen nimi tulee EUVL-julkaisun myötä (Cellar); sitä ennen nimi on englanniksi. Vastustamisaika lasketaan hyväksymispäivästä (tai erikseen kirjatusta toimittamispäivästä) kuukausina.
* **Vaikuttaminen** – jokaisen HE:n tiedoissa: ketkä vastasivat lausuntokierrokseen (Hankeikkunan lausunnot: määrä, organisaatiot, "ei lausuttavaa", linkki lausuntopalveluun), keitä valiokunta kuuli ja ketkä toimittivat kirjallisen lausunnon (eduskunnan käsittelytiedot, samana päivänä), valiokunnan tulevat esityslistat kuultavineen (2–4 päivää etukäteen – ikkuna pyytää kuulemista), mietinnön päätös (muuttamattomana/muutettuna, muutetut pykälät, vastalauseet ja puolueet), eduskunnalle annetut asiantuntijalausunnot sekä avoimuusrekisterin lobbaus (kuka, kenen asiakkaan puolesta, kehen yhteydessä, miten). Rivillä näkyy tiivistelmäpilli; yksityiskohdat ladataan vasta riviä avattaessa (`data/vaikuttaminen.json`).
* **Lainsäädäntösuunnitelma** – Hankeikkunaan kirjattu suunniteltu antoviikko näkyy ennusteena ("Suunniteltu antaminen eduskunnalle vko 45/2026", arvio), samoin siirtyminen aiemmasta viikosta, kesken istuntokauden lisätyt ja luettelosta poistetut, kiireellisyys ja perustuslakivaliokunnan lausunnon tarve. Sama tieto kuin VNK:n julkaisema suunnitelma-PDF, mutta päivittyvänä.
* **Ratkaisut** – oikeuskäytäntö omana välilehtenään: KKO:n ennakkopäätökset, KHO:n vuosikirjapäätökset, hovi- ja hallinto-oikeuksien julkaistut ratkaisut (Finlex), työtuomioistuin, markkinaoikeuden IPR- ja markkinaoikeudelliset asiat, keskusverolautakunnan ennakkoratkaisut (lainvoima/valitus KHO:een), tietosuojavaltuutetun päätökset sekä EU-tuomioistuimen tuomiot ja julkisasiamiehen ratkaisuehdotukset – ja **vireillä olevat suomalaisten tuomioistuinten ennakkoratkaisupyynnöt** (ennakkoratkaisukysymykset suomeksi EUVL C:stä). Säädösviittaukset ratkaistaan säädösnumeroiksi ja linkitetään säädösriveihin: säädöksen tiedoissa on *Oikeuskäytäntö*-osio ja ratkaisun tiedoista pääsee säädökseen. Suodattimet: tuomioistuin, aihealue, vain Suomea koskevat EUT-ratkaisut, vain vireillä olevat ennakkoratkaisupyynnöt.
* **Määräaikojen laskenta** – kun määräaika lasketaan itse eikä lueta lähteestä, se lasketaan yhdessä paikassa (`scripts/maaraajat.py`): suomalaiset määräajat lain säädettyjen määräaikain laskemisesta (150/1930) mukaan – alkamispäivää ei lueta (2 §), kuukausimääräaika päättyy samannumeroisena päivänä tai kuun viimeisenä (3 §), ja jos viimeinen päivä on lauantai, sunnuntai, muu pyhäpäivä, itsenäisyyspäivä, vappu, jouluaatto tai juhannusaatto, määräaika siirtyy seuraavaan arkipäivään (5 §; pääsiäinen ja liikkuvat pyhät lasketaan vuosittain). EU-määräajat asetuksen 1182/71 3 artiklan mukaan (lauantai, sunnuntai ja toimielinten yhteiset vapaapäivät → seuraava työpäivä). Sovelletaan suorahankintojen valitusaikaan (147 § 3 mom.), kuntien hankintapäätösten hankintaoikaisu- ja valitusaikaan (vaihteluväli, koska tiedoksisaantipäivä ei ole julkinen), markkinaoikeuden ratkaisujen KHO-valitusaikaan (aikaisin mahdollinen, laskettu antopäivästä), EUVL:n yrityskauppailmoitusten huomautusaikaan ja delegoitujen säädösten vastustamisaikaan. Siirtynyt päivä näkyy perusteineen määräajan tekstissä. Viranomaisen itse ilmoittamat määräajat (Hilma, lausuntopalvelut, KKV, komissio) näytetään sellaisinaan.
* **Annetut lausunnot – kuka sanoi mitä** – jokainen jo annettu lausunto tiivistetään automaattisesti ja lisätään asian
  tietoihin (*Annetut lausunnot*): ensin tiivistelmä (lausunnon oma, sanatarkka virke, jossa kanta ilmaistaan) ja
  suuntaa-antava kanta (kannattaa / kannattaa varauksin / vastustaa / vastustaa osin / muutosehdotuksia / kannanotto /
  virkamiesesittely / ei lausuttavaa), sitten lausunnon antaja (järjestö, henkilö, päivä, valiokunta) ja lopuksi linkki
  lausuntoon. Lähteinä ministeriöiden lausuntokierrosten lausunnot (Hankeikkunan LAUSUNTO-asiakirjat, CC BY 4.0) ja
  eduskunnan valiokuntien asiantuntijalausunnot (eduskunta.fi/pdf) – HE:t, U/E-kirjelmät (myös EU-ehdotuksiin liitetyt
  kirjelmät), lakialoitteet ja muut asiat, joiden tunnus on rivin viite. Jokainen päivitysajo hakee uudet lausunnot
  ensin (käynnissä olevat kierrokset ja uusimmat), lukee PDF:t neljällä rinnakkaisella haulla (aikabudjetti 15 min) ja
  tallentaa tuloksen asiakirjan tunnisteella, joten sama lausunto luetaan vain kerran. Skannatut lausunnot luetaan
  tekstintunnistuksella (tesseract, suomi ja ruotsi). Lausunto, jota ministeriö ei ole julkaissut tiedostona, näytetään
  antajan ja päivän kera. `scripts/build_lausunnot.py` kirjoittaa säädöskohtaisen tiedoston `docs/data/lausunnot/<id>.json`
  (ladataan vasta kun rivi avataan; vastustavat ensin) ja rivin merkkiin kantojen lukumäärät ("32 lausuntoa (6 vastustaa)").
  Kannat voi suodattaa napeista. Tiivistelmä on ote eikä tulkinta lausunnon kokonaissisällöstä – tarkista lausunnosta
  ennen kuin vetoat siihen.
* **Eduskuntakäsittely kokonaisuudessaan** – `scripts/fetch_asiat.py` lukee jokaisen sivulla näkyvän eduskunta-asian
  (HE, U/E-kirjelmä, EU-ehdotukseen liitetyt kirjelmät, VNS, LA, KAA …) eduskunta.fi:n asiasivulta: asian **kaikki
  asiantuntijalausunnot ja lisäselvitykset kaikista valiokunnista ja jaostoista** (myös perustuslakivaliokunnan ja muiden
  lausuntovaliokuntien kuulemiset, ei vain VaskiData-syötteen viime viikkoja) sekä **valiokuntien lausunnot ja mietinnöt**
  (PeVL, YmVL, …M). Valiokunnan asiakirjasta näytetään päätösosa tiivistelmänä (esim. "että lakiehdotus voidaan käsitellä
  tavallisen lain säätämisjärjestyksessä, jos …"), mietinnön ratkaisu (hyväksytään muutettuna / muuttamattomana /
  hylätään), muutetut pykälät ja vastalauseet puolueineen sekä linkki asiakirjaan; puuttuvat asiakirjat haetaan
  VaskiDatasta tunnuksella. Käsittelyssä olevat asiat päivitetään joka ajossa, käsitellyt viikoittain.
* **Lainsäädännön arviointineuvosto** – `scripts/fetch_arviointineuvosto.py` lukee jokaisen HE:n XML-tekstistä (eduskunnan avoin data) jakson *Lainsäädännön arviointineuvoston lausunto*: neuvoston kokonaisarvio (täyttää hyvin / tyydyttävästi / välttävästi / ei täytä vaikutusarviointiohjeen vaatimuksia), suositus korjata ennen antamista ja miten lausunto on otettu huomioon. Neuvoston omat sivut (valtioneuvosto.fi) vastaavat koneellisille hauille Cloudflaren haasteella, eikä estoa kierretä. Hankkeet, jotka Hankeikkunassa on merkitty neuvoston arvioitavaksi, näytetään ennen HE:tä merkinnällä.
* **Valmisteluasiakirjat (Hankeikkuna)** – hankkeen kaikki julkiset asiakirjat asian aikajanalle: asettamispäätös, HE-luonnos (lausunnolle), työryhmän mietintö tai selvitys, vaikutusarviot, lausuntoyhteenveto ja eriävät mielipiteet omina kohtinaan; rutiiniasiakirjat (pöytäkirjat, kutsut, toimikausipäätökset, kirjeet) yhtenä taitettuna "Valmisteluasiakirjat (N)" -kohtana. Ruotsinkieliset rinnakkaisversiot jätetään pois.
* **HE:n pääasiallinen sisältö ja säätämisjärjestys** – samasta HE-tekstistä kuin arviointineuvoston jakso: esityksen oma tiivistelmä ja hallituksen kanta säätämisjärjestykseen (tavallinen / perustuslain / supistettu perustuslain säätämisjärjestys, pidetäänkö perustuslakivaliokunnan lausuntoa suotavana).
* **Täysistunto** – `scripts/fetch_taysistunto.py`: HE:n käsittelyvaiheet täysistunnossa puheenvuorojen määrineen eduskuntaryhmittäin, äänestykset tuloksineen eduskuntaryhmittäin sekä hallitus- ja oppositioryhmät yhteensä (SaliDB-taulut), ja eduskunnan vastauksen hyväksymät lausumat ("Eduskunta edellyttää, että …", EV:n XML).
* **KKO:n valitusluvat ja lautakunnat** – KKO:n myöntämät valitusluvat oikeuskysymyksineen (Finlex; tulevat ennakkopäätökset, omana valintanaan Ratkaisut-näkymässä), kuluttajariitalautakunnan ratkaisusuositukset ja yhdenvertaisuus- ja tasa-arvolautakunnan tapausselosteet ja lausunnot (syötteet). Työneuvoston ja tekijänoikeusneuvoston lausunnot ovat valtioneuvoston palvelimella Cloudflaren takana, joten niitä ei haeta.
* **EU-menettelyjen asiakirjat ja kansallinen täytäntöönpano** – `scripts/fetch_oeil.py` lukee Legislative Observatoryn asiakirjaportista parlamentin mietinnöt ja hyväksytyt tekstit, komission vaikutustenarvioinnit (SWD) ja sääntelyntarkastelulautakunnan lausunnot (SEC), neuvoston asiakirjat sekä EDPS:n, ETSK:n, alueiden komitean ja EKP:n lausunnot; `scripts/fetch_nim.py` hakee Cellarista Suomen komissiolle ilmoittamat direktiivien täytäntöönpanosäädökset ja direktiivin määräajan – direktiivin tiedoissa näkyy myös, jos Suomi ei ole ilmoittanut yhtään toimea määräajan umpeuduttua.
* **Laillisuusvalvonta, yleissitovat TES:t ja virastojen määräykset Finlexistä** – oikeusasiamiehen ja oikeuskanslerin ratkaisut ja lausunnot, työehtosopimuksen yleissitovuuden vahvistamislautakunnan päätökset (yleissitovat työehtosopimukset, vuoden ajalta) sekä 27 viraston ja ministeriön määräyskokoelmat (mm. Energiavirasto, KKV, PRH, Verohallinto, Valvira, Fimea, Tukes, STUK). Lähteiden omat sivustot ovat Cloudflare-estettyjä; Finlex julkaisee samat asiakirjat.
* **Muiden hankkeiden lausuntokierrokset** – Hankeikkunasta myös selvitys-, strategia-, työryhmä- ja talousarviohankkeiden lausuntokierrokset määräaikoineen (lausuntopalvelu.fi itse on Cloudflare-estetty). Lakien vahvistuspäivä otetaan Hankeikkunan vaiheesta *Laki on vahvistettu*, jos eduskunnan tiedoista se vielä puuttuu.
* **Alilähteiden vahti** – `health_report.py` hälyttää myös toimialakerroksen yksittäisestä lähteestä, joka ei ole päivittynyt 72 tuntiin, vaikka kerros kokonaisuutena toimisi.
* **Toimi – luonnokset riviltä** – jokaisen rivin tiedoissa on *Toimi*-painikkeet, jotka kokoavat rivin omista tiedoista valmiin luonnoksen muokattavaan ikkunaan (Kopioi / Avaa Outlookissa / Jaa Teamsiin – sivulta ei lähde mitään): lausuntoluonnos lausuntokierrokselle (viite, määräaika, muut lausunnonantajat, rakenne pykälittäin), palaute kuulemiseen, pyyntö tulla kuulluksi valiokunnassa (valiokunnan osoite tunnuksen mukaan), viesti delegoidun säädöksen vastustamisajasta, huomautus komissiolle yrityskeskittymästä (COMP-MERGER-REGISTRY, EUVL-viite ja määräaika), lausunto KKV:lle, kysymykset tarjouspyynnöstä, vastaus markkinakartoitukseen (hankintalaki 65 §), asiakirjapyyntö hankintapäätöksestä ja voittaneesta tarjouksesta (julkisuuslaki 621/1999: 11 §, 11 § 2 mom. 6 k., 24 § 1 mom. 20 k., 14 § 4 mom.; hankintalaki 138 §), hankintaoikaisuvaatimuksen ja markkinaoikeusvalituksen runko (hankintalaki 132–135 §, 146–148 §, 150–151 §, 154 §), yhteydenotto markkinavuoropuheluun ennustetusta kilpailutuksesta, muistion runko ratkaisusta ja tiivistelmä tiimille. Luonnokset ovat rakenteita ja viitteitä, eivät oikeudellista neuvontaa: määräajat ja pykälät tarkistetaan ennen lähettämistä.
* **Lakianalyysi ja johtoryhmäraportti (Word ja PowerPoint)** – säädöksen tai EU-asian tiedoissa *⤓ Word* ja *⤓ Diat* lataavat analyysin: avaintiedot, aikajana kuvana tai diana, vaiheet päivämäärineen, HE:n pääasiallinen sisältö ja säätämisjärjestys, arviointineuvosto, lausuntokierroksen kannat ja poimintoja, valiokunnan mietintö, täysistunnon äänestykset ja lausumat, lakitekstin muutokset (HE-diff), vaikuttaminen, liittyvä oikeuskäytäntö ja lähteet. Yläpalkin *Raportti* kokoaa johtoryhmäraportin valitulta jaksolta (7/30/90 pv taaksepäin, 30/90/180 pv eteenpäin) ja rajauksella (kaikki, sivun valinnat, seuratut tai kansio; oletuksena vain lait, asetukset ja EU-säädökset): luvut, nostot (seuratut ensin), tulevat voimaantulot, avoimet lausuntokierrokset, jakson tapahtumat, EU-määräajat ja oikeuskäytäntö. Tiedostot syntyvät kokonaan selaimessa sivulla olevasta aineistosta valitulla kielellä – ei palvelinta, ei tekoälyä eikä käyttökuluja. Kirjastot (`docs/vendor/`: docx 9.10.0 ja PptxGenJS 4.0.1, MIT) ja `docs/js/raportit.js` ladataan vasta latausnapin painalluksella, joten sivun avautuminen ei hidastu.
* **Mikä muuttuu (HE-diff)** – hallituksen esityksen tiedoissa sanatason muutosnäkymä kahdessa vaiheessa: *voimassa oleva → HE* (HE:n rinnakkaistekstit, pykälittäin) ja *HE → valiokunnan mietintö* (mietinnön muutosmerkinnät). Lisätty teksti vihreällä, poistettu yliviivattuna; rivillä pilli "n § muuttuu". Lähde: eduskunnan avoin data (HE:n ja mietinnön asiakirjat, PDF-liitteiden rinnakkaistekstit); yksi tiedosto per HE (`data/diff/<id>.json`), ladataan vasta riviä avattaessa. Päivitysajo hakee uudet HE:t 8 minuutin aikarajalla (`HEDIFF_BUDGET_S`).
* **Tilastot** – kertyvästä historiasta (`data/history/`: markkinaoikeuden hankintaratkaisut 2025–, KKV:n yrityskauppapäätökset 2024–, sopimuskaudet, vireillä-luettelo) ja nykyisistä välimuisteista lasketut mediaanit ja osuudet (`data/tilastot.json`): HE:n läpimenoajat valiokunnittain ja ministeriöittäin, mietintöjen muutosaste, lainsäädäntösuunnitelman osuvuus, markkinaoikeuden lopputulosjakaumat toimialoittain ja hankintayksiköittäin, valitukset hankintayksiköittäin, KKV:n jatkoselvitysosuus ja käsittelyajat, sopimuskausien ja tarjousaikojen pituudet CPV-jaoittain, delegoitujen säädösten vastustus. Tilannekuvan *Tilastot*-paneeli ja rivin tiedoissa asiayhteyteen sopivat luvut. Jokaisella luvulla on n; alle kolmen tapauksen lukuja ei näytetä. Markkinaoikeuden luvut perustuvat Finlexissä julkaistuihin ratkaisuihin (valikoima), joten osuuksissa on valikoitumisharhaa.
* **Ennakoivat signaalit** (Tilannekuva) – mitä on tulossa ennen virallista vaihetta: suunnitellut antoviikot, valiokuntien esityslistat, komission suunnitellut hyväksynnät (viikkolista ja työohjelma), EP:n täysistuntoennusteet ja Coreperin/neuvoston esityslistat (Cellarin PROJECTED-tapahtumat, merkitty "esityslistalla"), uudelleenkilpailutusten ennusteet ja hankintakalenterit. **Vaikuta nyt** -paneeli kokoaa avoimet vaikutusikkunat: lausuntokierrokset, kuulemiset, valiokuntakuulemiset, vastustamisajat, EUVL:n huomautusajat, markkinakartoitukset ja valitusajat – kullakin mitä voi tehdä.
* **Tilannekuva** – seurannassa olevat säädökset, *Mitä on muuttunut* (ajojen välinen muutosloki: uudet säädökset, uudet vaiheet, siirtyneet päivämäärät, tilan vaihtumiset), avoimet lausuntokierrokset, seuraavien 60 päivän vaiheet ja viimeisten 14 päivän tapahtumat.
* **Oma seuranta** – tähti ☆ minkä tahansa säädöksen kohdalla lisää sen seurantaan; *Vain seuranta* -kytkin rajaa kaikki näkymät seurattuihin. Aihealuevalinta muistetaan selaimessa, joten se toimii kategoriaseurantana. Seurantalista tallentuu selaimeen; Tilannekuvan *Seurannassa*-paneelin "Siirrä toiselle koneelle" antaa siirtolinkin tai koodin (tuonti yhdistää tai korvaa). Mitään käyttäjän tietoa ei lähetetä minnekään: sivu on pelkkiä staattisia tiedostoja, eikä toinen linkin saaja näe toisen tähtiä, kansioita tai piilotuksia. Sivu on suunniteltu työpöytäkäyttöön; kapealla näytöllä se toimii, mutta aikajana vaatii vaakavieritystä.
* **Tiimikansiot (jaetut kansiot) ja tiimin kalenterisyöte** – `config/kansiot/<tunnus>.yaml` määrittelee kansion, jonka kaikki näkevät: kiinteitä kohteita tunnisteilla ja/tai sääntöjä (aihealueet, lajit, kilpailutusten toimialat, hankintayksiköt ja vaiheet, hakusanat, yrityskauppojen osapuolet tai suomalaisuus, vain keskeneräiset), jotka ratkaistaan joka päivitysajossa – kansio on siis tiimin seurantaprofiili, johon uudet kohteet ilmestyvät itsestään. Jokaisella tiimikansiolla on oma, automaattisesti päivittyvä kalenterisyöte `docs/data/kansiot/<tunnus>.ics` (tulevat lausunto-, tarjous-, valitus-, huomautus- ja vastustamisajat, voimaantulot ja määräajat) ja Atom-syöte `docs/data/kansiot/<tunnus>.xml` (yksi merkintä per tuleva määräaika 60 päivän sisällä). Tiimikansiot näkyvät Kansio-valikossa omana ryhmänään, Tilannekuvan Kansiot-paneelissa katkoviivaisina valintoina ja kohteen tiedoissa; ne rajaavat näkymät samoin kuin omat kansiot; `?k=<tunnus>` avaa sivun kansio valittuna. Tiimikansiot ovat julkisia siinä missä repokin – ei asiakastietoa. Formaatti: `config/kansiot/README.md`; mukana kaksi esimerkkikansiota (`esimerkki: true`), jotka voi poistaa.
* **Jakaminen sivun sisällä – ilman GitHub-käyntiä** – kaikki tiimikansioiden muutokset tehdään sivulta: Kansiot › Hallitse › *Uusi tiimikansio* (nimi, kuvaus, sääntöeditori, jossa aihealueet, toimialat, hankintayksiköt, hakusanat ja yrityskauppojen rajaukset valitaan listoista), tiimikansion *Muokkaa* ja *Poista*, oman kansion *Jaa tiimikansioksi* sekä kohteen tiedoissa tiimikansion nimi (lisää/poista kohde). Sivu tarvitsee siihen **tiimin avaimen**, joka syötetään kerran *Jakamisen asetukset* -ikkunassa (oma nimi + avain; avain tallentuu vain selaimeen, *Unohda avain* poistaa sen). Avain on GitHubin fine-grained personal access token, jolla on tässä repossa vain *Issues: Read and write* -oikeus: sivu avaa sillä muutospyynnön (`[kansio] …` -issue, rakenne `scripts/kansiopyynto.py`), `kansiopyynto.yml` toteuttaa sen, kommentoi ja sulkee, ja sivu seuraa pyyntöä (näyttää muutoksen heti ennakoivasti, vahvistaa noin minuutissa ja lataa kansiot uudelleen julkaisun jälkeen). Ylläpitäjä tekee avaimen kerran (ohje *Jakamisen asetukset* -ikkunassa: Only select repositories → tämä repo → Issues: Read and write → voimassaolo enintään vuosi) ja jakaa sen tiimille Teamsissä; avaimen voi mitätöidä GitHubista milloin vain. Rajoitukset rehellisesti: avain on jaettu salaisuus (vuotaessaan sillä voi vain avata turhia muutospyyntöjä, jotka näkyvät issueissa), muutospyynnöt toteutuvat avaimen omistajan nimissä ilman erillistä hyväksyntää, ja kansiot ovat julkisia. Yksityiset kansiot ja henkilökohtainen kirjautuminen vaatisivat oikean taustapalvelun (ks. *Pitkän ajan ylläpito*).
* **Teams ja Outlook** – kansion *Jaa Teamsiin* avaa Teamsin jakoikkunan kansion linkillä; *Outlook* tilaa kalenterisyötteen Microsoft 365 -kalenteriin, *Google* Google-kalenteriin, *webcal* Appleen tai muuhun kalenterisovellukseen; *Teams-ilmoitukset (syöte)* on Atom-osoite Power Automate -työnkulkuun *"When a feed item is published" → "Post message in a chat or channel"*, jolloin tiimin kanava saa jokaisen uuden määräajan viestinä (resepti `config/kansiot/README.md`). Kohteen tiedoissa *Jaa Teamsiin* jakaa yksittäisen säädöksen, kilpailutuksen tai yrityskaupan pysyvän linkin.
* **Kansiot ja piilotus** – *Hallitse*-painikkeesta (tai kohteen tiedoista) voi luoda nimettyjä kansioita (esim. asiakas, toimeksianto, "Lausuttavat") ja viedä niihin säädöksiä, EU-menettelyjä, kilpailutuksia ja yrityskauppoja; sama kohde voi olla useassa kansiossa. Oman kansion määräajat saa ladattua kalenteritiedostona (*Kalenteri*-painike Hallitse-ikkunassa; tiedosto rakennetaan selaimessa). Yläpalkin *Kansio*-valinta rajaa kaikki näkymät – myös Tilannekuvan laskurit ja paneelit – kansion kohteisiin, ja Tilannekuvan *Kansiot*-paneeli näyttää joka kansion seuraavan määräajan. Rivin × (näkyy hiirellä) tai tietojen *Piilota näkymistä* poistaa kohteen kaikista näkymistä ja laskureista; piilotetut löytyvät Kansio-valikon kohdasta *Piilotetut*, josta ne voi palauttaa (ja piilotuksen voi kumota heti ilmoituksesta). Kansiot, piilotukset ja tähdet tallentuvat selaimeen ja siirtyvät toiselle koneelle samalla siirtolinkillä kuin tähdet.
* **Kansallinen** ja **EU** – vaakasuuntaiset aikajanat (lausuntoaika, eduskunta-/lainsäädäntömenettely, voimaantulo, määräajat), lausuttavissa olevat kärjessä.
* **Valmiit** – vahvistetut ja voimassa olevat säädökset taulukkona.
* **Kilpailutukset** – Hilman hankintailmoitukset koko elinkaarellaan, vaihe valitaan välilehden yläreunasta:
  * *Avoinna* (oletus) – kaikki avoinna olevat hankintailmoitukset (kansalliset ja EU-kynnysarvon ylittävät) määräajan mukaan: kuinka monta päivää on aikaa tarjota (tai jättää osallistumishakemus), mitä hankitaan (hankintayksikön omasta kuvauksesta poimittu tiivistelmä, CPV-nimike, hankintalaji, menettely, arvioitu arvo, osat) ja linkki alkuperäiseen ilmoitukseen Hilmassa sekä tarjouspyyntöasiakirjoihin ja TED:iin. Dynaamiset hankintajärjestelmät (DPS, joihin voi hakea koko voimassaoloajan) ovat oletuksena piilossa *Myös DPS* -kytkimen takana.
  * *Tulossa* – ennakkoilmoitukset ja markkinakartoitukset eli hankinnat, joista ei vielä voi tarjota mutta joihin voi vaikuttaa (vastausaika markkinakartoitukseen näkyy lausuntoaikana).
  * *Ratkaistu* – viimeisten 30 päivän jälki-ilmoitukset: voittaja ja sopimuksen arvo. Hankintapäätöksestä voi valittaa 14 päivän kuluessa päätöksen tiedoksisaannista; koska tiedoksisaantipäivä ei ole julkinen, se näytetään huomautuksena eikä laskettuna päivänä.
  * *Suorahankinnat* – suorahankinnan avoimuusilmoitukset ja kansalliset suorahankintailmoitukset, joille lasketaan 14 päivän valitusajan päättyminen julkaisusta (hankintalaki 147 § 3 mom.; sopimuksen saa tehdä aikaisintaan 14 päivän kuluttua julkaisusta, 131 §).
  * *Markkinaoikeus* – markkinaoikeudessa vireillä olevat hankintavalitukset (markkinaoikeuden hankintalain 148 §:n 3 momentin nojalla julkaisema luettelo: vireilletulopäivä, hankintayksikkö, valituksenalainen hankintapäätös) ja viimeisten 90 päivän ratkaisut (valittaja, hankintayksikkö, asiasanat, diaarinumero, lopputulos luokiteltuna: valitus hylätty, hankintapäätös kumottu, hyvitysmaksu, tehottomuusseuraamus, jätetty tutkimatta, välipäätös …). Vireillä oleva asia yhdistetään ratkaisuunsa hankintayksikön ja hankintapäätöksen päivän perusteella, ja ratkaisu Hilma-ilmoitukseen hankintayksikön ja ratkaisussa mainitun ilmoituspäivän perusteella – silloin valitus näkyy myös Hilma-ilmoituksen tiedoissa. Ratkaisun jälkeen aikajanalle merkitään valitusajan KHO:een päättyminen arviona (30 pv antopäivästä; valituslupa, hankintalaki 165 §), koska tiedoksisaantipäivä ei ole julkinen.
  * *Päätökset* – Helsingin kaupungin hankintapäätökset päätöspalvelusta (voittaja, hävinneet, arvonlisäveroton arvo, päätöstyyppi, valitusosoitus/muutoksenhakukielto): hankintaoikaisu ja valitus markkinaoikeuteen 14 päivän kuluessa tiedoksisaannista; koska tiedoksisaantipäivä ei ole julkinen, määräaika näytetään vaihteluvälinä: aikaisintaan päätös + 14 pv (sähköinen tiedoksianto päätöspäivänä, hankintalaki 128 §), viimeistään päätös + 7 + 14 pv (kirje). Linkittyy Hilma-ilmoitukseen ja markkinaoikeuden vireillä-riviin. Muut kunnat eivät tarjoa rajapintaa (Oulun RSS asetuksella).
  * *Ennusteet* – uudelleenkilpailutuksen ennuste: jälki-ilmoitusten sopimuskaudet (alku, loppu, kesto, optiot, puitejärjestely) Hilman julkisesta detaljirajapinnasta; kun sopimus päättyy 0–18 kuukauden sisällä, näytetään nykyinen toimittaja, edellinen arvo, optioiden vaikutus ja arvioitu ikkuna uudelle kilpailutukselle (9–3 kk ennen sopimuskauden päättymistä). Alle kuuden kuukauden sopimukset (DPS-minikilpailutukset) jätetään pois.
  * *Kalenterit* – Hilman kilpailutussuunnitelmat (hankintayksikön oma suunniteltu ilmoituspäivä) sekä hankintayksiköiden julkaisemat hankintakalenterit (`config/kalenterit.yaml`: Hansel, HUS, Espoo, Senaatti, Tampere, Tuomi Logistiikka, Länsi-Uudenmaan hyvinvointialue); kvartaalit ja vuodenajat muunnetaan arviopäiviksi. Kun ilmoitus julkaistaan Hilmassa, suunnitelma linkittyy siihen ("julkaistu Hilmassa").
  * *Maa-valinta* – Hilma kattaa Suomen; TED:stä haetaan Ruotsin, Viron, Tanskan ja Norjan ilmoitukset toimialojen CPV-jaoilla (`settings.yaml` → `ted`). Toisen maan rivit näkyvät vain, kun maa on valittu.
  * *Nykyiset toimittajat* – valtion hankintayksiköiden riveillä näkyvät saman luokan suurimmat toimittajat viimeisen 12 kuukauden ostolaskuista (Tutkihankintoja.fi, valtion sektori); kunnista vastaavaa avointa rajapintaa ei ole.
  * *KKV:n hankintojen valvonta* – laittomia suorahankintoja koskevat päätökset ja esitykset markkinaoikeudelle näkyvät *Markkinaoikeus*-vaiheessa.

  Saman hankintamenettelyn ilmoitukset (ennakkoilmoitus → hankintailmoitus → korjausilmoitus → jälki-ilmoitus) on linkitetty toisiinsa: kohteen tiedoissa on *Saman hankinnan muut ilmoitukset* ja sen aikajanalla näkyvät kaikki vaiheet. Suodattimet: *Toimiala* (15 CPV-pohjaista luokkaa, `config/hankinnat.yaml`), EU-kynnysarvo / kansallinen, sulkeutuu (tai ratkaistu) 7/14/30 pv, haku. Tähditetty kilpailutus näkyy Tilannekuvan *Seurannassa*-paneelissa ja säilyy 14 päivää määräajan jälkeen tilassa *päättynyt* (tai *poistunut*, jos ilmoitus katosi Hilmasta ennen määräaikaa).
* **Yrityskaupat** – yrityskauppavalvonnan vireillä olevat tapaukset KKV:ssa ja Euroopan komissiossa (DG COMP) aikajanana, jossa näkyvät viranomaisen omat lakisääteiset määräajat: KKV:n tapauksista ilmoituksen saapuminen, kuulemisen määräaika (jolloin kilpailija tai asiakas voi lausua), ensimmäisen vaiheen määräaika (23 työpäivää), jatkokäsittelyyn siirrettyjen jatkokäsittelyn määräaika (69 työpäivää) sekä KKV:n kieltoesitys markkinaoikeudelle ja markkinaoikeuden ratkaisun määräaika (3 kk esityksestä, kilpailulaki 29 §) ja ratkaisu (tila *kieltoesitys markkinaoikeudessa*, kunnes markkinaoikeus ratkaisee asian); komission tapauksista ilmoituspäivä, EUVL:n ennakkoilmoitus ja sen avaama kolmansien huomautusaika (yleensä 10 päivää julkaisusta – EU-tason "milloin voi lausua"), komission julkaisema alustava määräaika (vaihe 1: 25 työpäivää; vaihe 2 pidempi), kellon keskeytykset tietopyynnön vuoksi (11 art. 3 kohta), määräajan pidennykset (10 art. 3 kohta), sitoumusten toimittaminen, väitetiedoksianto ja päätökset oikeusperustoineen (6(1)(b), 6(1)(c), 8(2) …). EUVL:n ennakkoilmoituksesta luetaan myös **osapuolet kotimaineen**, joten komission tapauksista tunnistetaan ne, joissa on suomalainen osapuoli (merkintä *FI-osapuoli*, suodatin *Suomalainen osapuoli*; myös suomalaisen emoyhtiön määräysvallassa oleva osapuoli lasketaan). Suodattimet: *Toimiala* (KKV-tapaukset omana luokkanaan, komission tapaukset NACE-pääluokan mukaan), KKV / komissio, *Vain vireillä* (oletus; pois päältä näkyvät myös viimeisten 90 päivän päätökset: hyväksytty sellaisenaan, ehdollisena, kielletty, peruutettu), *Suomalainen osapuoli*; haku löytää myös osapuolen nimellä. Kohteen tiedoissa on tapauksen tiivistelmä (KKV:n oma tiivistelmä tai ilmoittajan kuvaus kaupasta; komission tapauksista EUVL-ilmoituksen kuvaus kaupasta ja osapuolten liiketoiminnasta), osapuolet, huomautusajan päättyminen ja linkit KKV:n tapaussivulle ja päätökseen tai komission tapaussivulle ja EUVL-ilmoitukseen. Määräaikoja ei lasketa itse – ne luetaan viranomaisen sivulta, jotta kellon pysäytykset ja pidennykset tulevat oikein. Tilannekuvan *Yrityskauppoja vireillä* -laskuri vie välilehdelle; KKV:n kuulemiset ja suomalaisosapuolisten komission tapausten huomautusajat näkyvät *Lausuntokierrokset käynnissä* -paneelissa ja niiden määräajat *Seuraavat 60 päivää* -listassa. Välilehden *Kilpailunrajoitukset*-segmentissä ovat KKV:n kilpailunrajoitusasiat: seuraamusmaksuesitykset markkinaoikeudelle, kielto-, sitoumus- ja toimitusvelvoiteratkaisut sekä kilpailuneutraliteettiasiat (markkinaoikeuden ratkaisulle ei ole laissa määräaikaa).
* Jokaisella säädöksellä on pysyvä linkki (`…/#fi-he-129-2026`), joka avaa sen aikajanan suoraan.
* `data/saadosseuranta.ics` – kaikki tulevat säädösmääräajat kalenteriin (Google/Outlook/Apple: "tilaa kalenteri osoitteesta"); tiimikohtaiset syötteet `data/kansiot/<tunnus>.ics` ja Teams/Power Automate -ilmoituksiin Atom-syöte `data/kansiot/<tunnus>.xml`.
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

| Eduskunnan avoin data (Vaski, valiokunnat) | Valiokuntien esityslistat ja kuultavat (2–4 pv etukäteen), asiantuntijalausunnot, mietintöjen ja lausuntojen päätökset (muuttamattomana/muutettuna, muutetut pykälät, vastalauseet), kirjalliset kysymykset, laki- ja toimenpidealoitteet, kansalaisaloitteet eduskunnassa, EUN-muistiot neuvoston kokouksista | `VaskiData/batch` (Id-skannaus) + tunnushaut; CC BY 4.0 |
| Valtioneuvoston Hankeikkuna (lausunnot ja suunnitelma) | Lausuntokierrosten annetut lausunnot (organisaatio, päivä, PDF, lausuntopalvelu-linkki) sekä HE-suunnitelman tila: suunniteltu antoviikko, siirtymät, lisätyt/poistetut, kiireellisyys, PeV | sama rajapinta (`asiakirjat` LAUSUNTO, `heTiedot.tilatiedot`) |
| Avoimuusrekisteri (VTV) | Lobbauksen toimintailmoitukset hankkeittain (Hankeikkunan tunnus) ja HE-numeroittain: organisaatiot, asiakkaat, yhteydenottojen kohteet ja tavat, kausi | `https://public.api.avoimuusrekisteri.fi` (JSON, CC BY 4.0; kevyt käyttö – kerran päivässä) |
| Tuomioistuimet | KKO, työtuomioistuin, (vakuutusoikeus) RSS + ratkaisusivut; KHO:n ennakkopäätösarkisto; markkinaoikeuden IPR- ja markkinaoikeudelliset ratkaisut; hovi- ja hallinto-oikeudet Finlexin vuosiluetteloista; säädösviittaukset lyhenteistä säädösnumeroiksi (`config/tuomioistuimet.yaml`) | `korkeinoikeus.fi`, `kho.fi`, `tyotuomioistuin.fi`, `markkinaoikeus.fi`, `finlex.fi` (HTML/RSS, hidastettu) |
| EU-tuomioistuin (Cellar) | Tuomiot ja julkisasiamiehen ratkaisuehdotukset (Suomesta lähtöisin tai valituilla oikeudenaloilla), vireillä olevat suomalaisten tuomioistuinten ennakkoratkaisupyynnöt EUVL C:n ilmoituksista kysymyksineen | SPARQL + `publications.europa.eu/resource/celex|oj` (Accept-Language fi) |
| Toimialakerros (`config/toimiala.yaml`) | Finanssivalvonnan valvottavatiedotteet, lausuntopyynnöt ja MOK-muutokset; EBA- ja EIOPA-kuulemiset määräaikoineen (ESMA pois päältä: esma.europa.eu vastaa 403 palvelinverkoista 21.10.2026 alkaen); EDPB:n kuulemiset ja ohjeet; Verohallinnon syventävät ohjeet ja KVL:n ennakkoratkaisut; Traficomin määräykset ja määräyshankepäätökset; tietosuojavaltuutetun, oikeusasiamiehen ja oikeuskanslerin ratkaisut, yleissitovat TES:t ja virastojen määräyskokoelmat (Finlex) | HTML/RSS/JSON (vero.fi:n ja traficom.fi:n hakurajapinnat) |
| Komission asiakirjarekisteri | Viikoittainen lista komission kokousten suunnitelluista hyväksynnöistä (SEC) ja työohjelman liite (suunnitellut aloitteet, viitteellinen vuosineljännes, FI+EN) | `ec.europa.eu/transparency/documents-register/api` + PDF (pdfplumber) |
| EU:n neuvosto (Cellar) | Coreperin, erityiskomiteoiden ja neuvoston esityslistat (AGENDA_DRAFT_CONSIL) ja suunnitellut PROJECTED-tapahtumat menettelyittäin; peruutetut pudotetaan | SPARQL (neuvoston oma avoin data lopetettu) |
| Euroopan parlamentti (OEIL + API) | Menettelyjen ennusteet: viitteellinen täysistuntopäivä, valiokunta-äänestys, tulevien istuntojen esityslistat | `oeil.secure.europarl.europa.eu` (FORECAST-PDF) ja `data.europarl.europa.eu/api/v2/meetings` (≤1 pyyntö / 3 s) |
| Komission rikkomusmenettelyt | Suomea koskevat päätökset: virallinen ilmoitus, perusteltu lausunto, kanne, lopettaminen; politiikka-ala, säädös | `ec.europa.eu/implementing-eu-law/search-infringement-decisions/api` |
| Komitologiarekisteri | Täytäntöönpanosäädösluonnokset ja komiteoiden äänestykset (lausunto, päivä, antaminen), perussäädöksen CELEX, Have your say -palauteaika kun täsmää | `comitology-register/core/api` + päivittäinen CSV |
| EU-pakotteet (Cellar) | Rajoittavia toimenpiteitä koskevat EUVL L:n säädökset: suomenkielinen nimi, julkaisu, voimaantulo, perussäädös/pakotejärjestelmä | SPARQL |
| Hilma (detaljit ja suunnitelmat) | Jälki-ilmoitusten sopimuskaudet, optiot ja voittajat (uudelleenkilpailutuksen ennuste); kilpailutussuunnitelmat (suunniteltu ilmoituspäivä, sopimuskausi, arvo) | `/web/api/public/procedure/{id}/enotice/{id}`, `/web/api/public/procurementplan/{id}`, hakuindeksi `isPlan eq true` |
| Hankintakalenterit (`config/kalenterit.yaml`) | Hansel (tulevat yhteishankinnat vaiheineen), HUS (xlsx), Espoo, Senaatti, Tampere (JSON), Tuomi Logistiikka, Länsi-Uudenmaan hyvinvointialue | HTML/xlsx/JSON |
| TED | Ruotsin, Viron, Tanskan ja Norjan hankinta- ja ennakkoilmoitukset toimialojen CPV-jaoilla (otsikko suomeksi) | `api.ted.europa.eu/v3/notices/search` |
| Helsingin päätöspalvelu | Hankintapäätökset (voittaja, arvo, hävinneet, valitusosoitus, nähtävilläolo) | `paatokset-elastic-proxy.api.hel.ninja` (haku) + päätössivut |
| Tutkihankintoja.fi (Valtiokonttori) | Valtion hankintayksiköiden suurimmat toimittajat luokittain (12 kk) | sivuston oma taustapalvelu (julkinen avain) |
| KKV – kilpailu- ja hankintavalvonta | Hankintojen valvonnan päätökset ja esitykset markkinaoikeudelle, kilpailunrajoitusasiat (seuraamusmaksuesitykset, kielto/sitoumus/toimitusvelvoite, neutraliteetti) | `kkv.fi/paatokset/…` (HTML + RSS) |
Mitä **ei** seurata, ja miksi: `valtioneuvosto.fi` (valtioneuvoston istuntojen esityslistat, EU-ministerivaliokunnan asialistat, lainsäädäntösuunnitelma-PDF), `lausuntopalvelu.fi`, `kansalaisaloite.fi`, `consilium.europa.eu`, Väylä, Valtori ja Puolustusvoimat estävät ohjelmalliset haut palvelinverkoista (Cloudflare-tarkistus); sama tieto tulee Hankeikkunasta (lausunnot, HE-suunnitelma, antaminen), eduskunnan avoimesta datasta (EUN-muistiot neuvoston kokouksista, KAA-aloitteet) ja Cellarista (neuvoston esityslistat). Kuntien hankintapäätöksistä vain Helsingillä on rajapinta (Oulun RSS asetuksella); muiden kaupunkien päätökset eivät ole koneluettavia. Tutkihankintoja kattaa vain valtion. `curia.europa.eu`:n omat syötteet on lopetettu – EU-tuomioistuin tulee Cellarista. Finlexin avoin data ei vielä sisällä tuomioistuinten ratkaisuja (vain laillisuusvalvojat), joten oikeuskäytäntö haetaan tuomioistuinten sivuilta ja Finlexin HTML:stä hidastetusti. Kilpailutusten ja ratkaisujen tiivistelmät ovat poimivia (ei kielimallia). Komission tapausten suomalaisuutta ei tunnisteta ennen EUVL-ilmoituksen julkaisua. Ennusteet (antoviikot, täysistunnot, esityslistat, sopimuskausien päättymiset, suunnitellut ilmoitukset) ovat aina merkitty arvioiksi eivätkä mene kalenterisyötteisiin.

## Rakenne

```
config/
  settings.yaml      EU-vuodet, menettelytyypit, Valmiit-sivun aikaraja, Hilma- ja yrityskauppa-asetukset sekä uusien lähteiden lohkot
                     (vaikuttaminen, vaski, ratkaisut/eut, ted, ennusteet, kalenterit, paatokset, toimittajat, kkv_valvonta)
  tuomioistuimet.yaml tuomioistuimet (käytössä/pois), säilytysaika, lyhenne -> säädösnumero -taulukko, EU-tuomioistuimen oikeudenalat
  eut_aiheet.yaml    EU-tuomioistuimen oikeudenalakoodien suomenkieliset nimet
  toimiala.yaml      toimialakerroksen lähteet (Fiva, ESMA, EBA, EIOPA, EDPB, Vero, KVL, Traficom, TSV) ja niiden oletusaihealueet
  eu_signaalit.yaml  EU-ennakoinnin asetukset: neuvoston kokoonpanot, rikkomusvaiheet, komitologian suodattimet, pakotejärjestelmät
  kalenterit.yaml    hankintayksiköiden hankintakalenterit (osoite, jäsennin, Hilma-nimet)
  topics.yaml        aihealueiden avainsanat (muokkaa vapaasti)
  hankinnat.yaml     kilpailutusten toimialat (CPV-etuliitteet), ilmoitustyyppien ja menettelyjen nimet, suorahankintatyypit ja valitusaika, tiivistelmäsäännöt
  yrityskaupat.yaml  komission päätöstyyppien ja KKV:n ratkaisujen suomennokset ja tilat, NACE-pääluokat, kieltoesityksen määräaika
  neuvosto.yaml      neuvoston käsittelyvaiheiden tapahtumakoodit (Cellar) ja niiden nimet aikajanalla
  delegoidut.yaml    delegoitujen säädösten tilat, toimielimet ja pääosasto -> aihealue -varasääntö
  eu_watchlist.yaml  EU-menettelyt, jotka haetaan aina
  overrides.json     käsin lisätyt tapahtumat, korjaukset ja lyhyet näyttönimet (id:n mukaan)
  kansiot/           tiimikansiot: yksi yaml per kansio (kohteet + säännöt), README.md kuvaa formaatin
scripts/
  fetch_hankeikkuna.py  fetch_eduskunta.py  fetch_finlex.py  fetch_eu.py  fetch_ue.py  fetch_hys.py
  fetch_hankinnat.py  fetch_kkv.py  fetch_eu_mergers.py  eu_notice.py (EUVL:n ennakkoilmoitusten jäsennys)
  fetch_regdel.py (delegoitujen säädösten rekisteri)  fetch_mao.py (markkinaoikeus)  build_mao.py
  fetch_vaski.py (eduskunnan valiokunnat)  fetch_avoimuus.py (avoimuusrekisteri)
  fetch_caselaw.py (tuomioistuimet)  fetch_curia.py (EU-tuomioistuin)  build_ratkaisut.py -> ratkaisut.json
  fetch_toimiala.py  build_toimiala.py (toimialakerros)
  fetch_eu_signals.py  build_eu_signals.py (komission suunnitelmat, neuvoston esityslistat, EP:n ennusteet, rikkomukset, komitologia, pakotteet)
  fetch_sopimuskaudet.py  fetch_suunnitelmat.py  fetch_ted.py  build_ennakointi.py (hankintojen ennakointi)
  fetch_paatokset.py  fetch_toimittajat.py  fetch_kkv_valvonta.py  build_valvonta.py (hankintapäätökset, toimittajat, KKV:n valvonta)
  fetch_hediff.py  build_hediff.py (HE-diff -> docs/data/diff/)  fetch_history.py  build_tilastot.py (historia -> tilastot.json)
  build.py           yhdistää välimuistit -> docs/data/items.json (+ build_hankinnat.py -> hankinnat.json, build_yrityskaupat.py -> yrityskaupat.json,
                     build_kansiot.py -> kansiot.json + kansiot/<tunnus>.ics + .xml)
  kansiopyynto.py    toteuttaa sivulta tulleen tiimikansion muutospyynnön (GitHub-issue: lisaa/poista/uusi/muokkaa/poista_kansio) – kansiopyynto.yml
  update.py          ajaa kaiken; yhden lähteen virhe ei kaada muita; kirjaa lähteiden tilan health.json-tiedostoon
  health_report.py   lähdevahti: avaa/sulkee GitHub-issuen lähteen epäonnistuessa toistuvasti
tests/               eheystestit (test_data.py), selaimen savutesti (test_smoke.py) ja lähdekohtaiset jäsennintestit tallennetuilla näytteillä (tests/samples/)
data/cache/          lähdekohtaiset välimuistit (committataan, jotta päivitys on nopea; Hilma-välimuisti haetaan joka ajossa eikä sitä versioida)
docs/                GitHub Pages -sivu: index.html, logot, data/items.json + hankinnat.json + yrityskaupat.json + ratkaisut.json + vaikuttaminen.json
                     + meta.json + changes.json + saadosseuranta.ics + kansiot/
.github/workflows/update.yml   tunnin välein herättävä ajastin (scripts/ajastus.py) -> ajo -> eheystestit -> commit -> lähdevahti -> julkaisu
.github/workflows/deploy.yml   testit joka pushille ja Pages-julkaisu testien takana
.github/workflows/vahti.yml    päivitysvahti: aineiston ikä julkaistulla sivulla, työnkulun käytössäolo, uudelleenkäynnistys, issue
.github/workflows/kansiopyynto.yml  tiimikansion muutospyyntö issuesta konfiguraatioon ja julkaisuun (tiimin avaimella heti, muuten /hyvaksy)
```

## Käyttöönotto

1. Luo GitHub-repo ja työnnä tämä sisältö sinne.
2. **Settings → Pages → Source: GitHub Actions.** `deploy.yml` julkaisee `docs/`-hakemiston testien mentyä läpi; sivu
   tulee osoitteeseen `https://<käyttäjä>.github.io/<repo>/`. (Vaihtoehto *Deploy from a branch → main /docs* toimii
   myös, mutta silloin testit eivät portita julkaisua.)
3. **Settings → Actions → General → Workflow permissions: Read and write permissions** (jotta
   workflow voi committata aineiston).
4. Aja workflow kerran käsin: **Actions → Päivitä säädösaineisto → Run workflow.** Sen jälkeen se
   ajaa itsensä arkisin klo 7, 12 ja 16 ja viikonloppuisin klo 9 Suomen aikaa (ks. *Ajastin* alla).

Paikallisesti:

```bash
pip install -r requirements.txt
python scripts/update.py            # kaikki lähteet (ensimmäinen ajo ~10 min)
python scripts/update.py eduskunta  # vain yksi lähde + build
python -m http.server -d docs 8000  # http://localhost:8000
```

## Ylläpito

* **Kielivalinta (FI/SV/EN)**: yläpalkin FI | SV | EN vaihtaa käyttöliittymän kielen lennosta (valinta muistetaan
  selaimessa; linkkiin `?lang=sv` tai `?lang=en`). Käännökset ovat sanakirjoissa `config/i18n/sv.json` ja
  `config/i18n/en.json`: avain on sivun suomenkielinen
  teksti tai sen osa (erottimet ·, –, :, sulut), luvut ja päivämäärät paikkamerkkeinä `{n}` ja `{d}`. Lisää puuttuva
  käännös tiedostoon ja aja `python scripts/build_i18n.py`, joka upottaa sanakirjan sivuun (testi tarkistaa, että kopio on
  ajan tasalla). Otsikot vaihtuvat virallisiin käännöksiin, kun sellainen on: ruotsiksi HE:t ja lausuntohankkeet
  Hankeikkunan ruotsinkielisellä nimellä ja EU-asiat Euroopan parlamentin ruotsinkielisellä otsikolla, englanniksi
  EU-asiat EU:n englanninkielisellä otsikolla. Muu aineisto – tiivistelmät, lausunnot, ratkaisut, kilpailutukset –
  näytetään alkuperäiskielellään, ja toimenpideluonnokset (viranomaisille lähetettävät kirjeet ja muistiot) pysyvät
  suomeksi.
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
* **Tiimikansiot**: tiimi muokkaa kansioita sivulta tiimin avaimella (ks. *Jakaminen sivun sisällä*); ylläpitäjän tehtäväksi jää
  avaimen luonti kerran (ja uusiminen ennen voimassaolon päättymistä – sivu näyttää päivämäärän *Tarkista ja tallenna* -painikkeen
  yhteydessä) sekä harvinaiset tapaukset, joissa pyynnön tekijällä ei ole avainta: silloin issue jää odottamaan kommenttia `/hyvaksy`.
  Suoraan tiedostoon voi edelleen kirjoittaa: `config/kansiot/<tunnus>.yaml` (formaatti `config/kansiot/README.md`); kansiot ja
  syötteet rakennetaan seuraavassa päivitysajossa tai heti, kun `kansiopyynto.yml` toteuttaa issuen. Kansion poisto sivulta poistaa
  tiedoston (syöte katoaa samalla).
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
* **Ajastin** (`update.yml` herää joka tunti minuutilla 11, `scripts/ajastus.py` päättää): täysi ajo, kun viimeisin
  aikataulun mukainen ajohetki (arkisin 7, 12, 16; viikonloppuisin 9; kesä- ja talviaika huomioiden) on ohitettu eikä
  sen jälkeen ole ajettu – GitHubin pudottama tai viivästämä herätys korjaantuu siis seuraavalla tunnilla. Lisäksi
  epäonnistuneet lähteet yritetään uudelleen tunnin välein klo 7–22 (vain ne lähteet, `update.py <lähteet>`).
  Muut herätykset päättyvät ~15 sekunnissa. Käsin: *Run workflow* (valinnaisesti vain tietyt lähteet).
  GitHubin omat ajastukset ovat tässä repossa harvoja ja tunteja myöhässä, joten luotettavin herättäjä on ulkoinen
  cron (esim. cron-job.org) tunnin välein: `POST https://api.github.com/repos/EditMonster/Saadosseuranta/actions/workflows/update.yml/dispatches`,
  otsakkeet `Authorization: Bearer <fine-grained PAT, vain tämä repo, Actions: Read and write>` ja
  `Accept: application/vnd.github+json`, runko `{"ref":"main","inputs":{"ajastin":"true"}}` – ajastin päättää silloin itse, ajetaanko.
* **Huoltokatkon tunnistus** (`common.http`): kun lähde ohjaa varasivulle (esim. tuomioistuinten `vara.*`-sivut,
  Helsingin `kopio.hel.fi`) tai vastaa 5xx/aikakatkaisulla kolmen yrityksen jälkeen, virhe kirjataan *huoltokatkoksi*
  eikä "rakenne muuttunut" -virheeksi. Sivu kertoo silloin "Huoltokatko lähteessä" ja edellinen aineisto pysyy.
  Tuomioistuinten ratkaisuille on varalähde: kun KKO:n, KHO:n, TT:n tai markkinaoikeuden oma sivusto ei vastaa,
  ratkaisut haetaan Finlexin oikeuskäytäntöluetteloista (`fallback_finlex` tiedostossa `config/tuomioistuimet.yaml`).
* **Lähdevahti**: jokaisen lähteen onnistuminen kirjataan (`data/cache/health.json`). Jos lähde ei ole päivittynyt
  20 tuntiin (huoltokatkossa 48 tuntiin) uusintayrityksistä huolimatta, `scripts/health_report.py` avaa repoon issuen (GitHub lähettää siitä sähköpostin) ja sulkee sen
  itsestään, kun lähde toipuu. Sivun yläpalkki näyttää samalla varoituksen "Lähde ei päivity" – muut lähteet ja
  edellinen onnistunut aineisto pysyvät käytössä.
* **Päivitysvahti** (`vahti.yml`, päivittäin 07:20 UTC, `scripts/vahti.py`): lukee julkaistun sivun `meta.json`-tiedoston
  ja laskee aineiston iän (varmistus ajastimen lisäksi). Jos aineisto on yli 30 tuntia vanhaa, vahti käynnistää päivitysajon uudelleen ja avaa issuen
  *Päivitys on pysähtynyt* (sulkeutuu itsestään, kun aineisto on taas tuoretta). Samalla se varmistaa, että `update.yml`
  on käytössä, ja kutsuu GitHubin enable-rajapintaa – GitHub poistaa ajastetut työnkulut käytöstä 60 päivän hiljaiselon
  jälkeen, ja kutsu nollaa laskurin. Päivitysajo itse raportoi tuloksensa: epäonnistunut ajo avaa issuen *Päivitysajo
  epäonnistui* (linkki lokiin), seuraava onnistunut sulkee sen. Sivun yläpalkki varoittaa, jos aineisto on yli 36 tuntia
  vanhaa. GitHubin ajastus on parhaan kyvyn mukainen: ajot alkavat tyypillisesti 5–30 minuuttia myöhässä, joskus tunteja,
  ja yksittäinen herätys voi jäädä väliin – siksi ajastin herää joka tunti ja tarkistaa itse, onko ajo tehty.
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
* **Pages julkaistaan Actionsista** (Settings → Pages → Source: GitHub Actions): jokainen julkaisu kulkee `deploy.yml`:n
  testien läpi, myös käsin tehty push. Siksi jokaisen aineistoa committaavan työnkulun (`update.yml`, `kansiopyynto.yml`)
  on kutsuttava `deploy.yml`:ää – pelkkä push main-haaraan ei enää julkaise.
* **Tiimin avain vanhenee** viimeistään vuodessa (GitHub ei salli pidempää fine-grained-tokenia): tee uusi avain samoilla
  oikeuksilla, jaa se tiimille Teamsissä ja poista vanha. Sivu näyttää avaimen voimassaolon tarkistettaessa. Jos tiimi kasvaa
  tai kansioihin halutaan ei-julkista sisältöä, seuraava askel on pieni taustapalvelu (esim. Cloudflare Worker + Microsoft
  Entra -kirjautuminen), joka ottaa muutospyynnöt vastaan käyttäjän omalla tunnuksella ja pitää kansiot organisaation sisällä;
  sivun pyyntömuoto (`scripts/kansiopyynto.py`) on suunniteltu niin, että vastaanottaja voi vaihtua ilman sivun uudelleenkirjoitusta.

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
