# Tiimikansiot (jaetut kansiot)

Jokainen tämän hakemiston `*.yaml`-tiedosto on yksi jaettu kansio, jonka kaikki sivun käyttäjät näkevät
(yläpalkin Kansio-valikko › Tiimikansiot, Tilannekuvan Kansiot-paneeli) ja jolla on oma kalenterisyöte
`docs/data/kansiot/<tiedostonimi>.ics`. Tiedostonimi on kansion tunnus (pienet kirjaimet, numerot, viiva).

Kansion sisältö on kahdenlaista:

* **kohteet** – kiinteät kohteet tunnisteilla (tunniste näkyy kohteen pysyvässä linkissä: `…/#fi-he-129-2026`).
* **saannot** – automaattiset säännöt, joilla täsmäävät kohteet lisätään kansioon joka päivitysajossa.
  Näin kansio toimii tiimin seurantaprofiilina: uudet kilpailutukset, lausuntokierrokset ja yrityskaupat
  ilmestyvät siihen itsestään.

```yaml
nimi: Hankintatiimi
kuvaus: Hankintaryhmän seurannassa olevat kilpailutukset ja hankintalain muutokset
omistaja: Hankintatiimi            # vapaamuotoinen: nimi tai tiimi, jolta voi kysyä kansiosta
kohteet:
  - fi-he-129-2026
  - hk-EF-28755
saannot:
  aihealueet: [Hallinto ja hankinnat]              # säädökset ja EU-asiat (config/topics.yaml)
  lajit: [laki, eu, delegoitu]                     # rajaa säädökset lajeihin (laki, asetus, eu, delegoitu, taytantoonpano, pakote, kuuleminen, ohje, kirjelma, signaali)
  toimialat: [Lakipalvelut, ICT ja ohjelmistot]    # kilpailutukset (config/hankinnat.yaml)
  hankintayksikot: [Hansel Oy, Helsingin kaupunki] # kilpailutukset, osuma hankintayksikön nimen alusta
  kilpailutusvaiheet: [avoin, tulossa, mao]        # tulossa, avoin, ratkaistu, suorahankinta, mao, paatos, ennuste, kalenteri (oletus: kaikki)
  tuomioistuimet: [KKO, KHO, EUT]                  # oikeuskäytäntö: KKO, KHO, HO, HaO, TT, MAO, KVL, TSV, EUT (aihealueet/hakusanat rajaavat)
  hakusanat: [hankintalaki, kilpailutus]           # otsikko tai tiivistelmä sisältää sanan (ei kirjainkokoa)
  yrityskaupat:
    vain_suomalaiset: true                         # KKV:n tapaukset ja komission tapaukset, joissa suomalainen osapuoli
    osapuolet: [UPM, Kesko]                        # osapuolen nimen osa
    toimialat: [Teollisuus]                        # yrityskauppojen toimialaluokat (config/yrityskaupat.yaml)
  vain_avoimet: true                               # vain keskeneräiset: avoimet kilpailutukset, vireillä olevat yrityskaupat, voimaan tulemattomat säädökset
  enintaan: 300                                    # enimmäismäärä sääntöjen tuomia kohteita (uusimmat ensin)
```

Kaikki kentät ovat valinnaisia paitsi `nimi`.

## Muokkaus sivulta (ilman GitHubia)

Tiimi ei normaalisti koske näihin tiedostoihin: kansiot luodaan, muokataan ja poistetaan sivulta (Kansiot › Hallitse ›
*Uusi tiimikansio*, tiimikansion *Muokkaa* / *Poista*, oman kansion *Jaa tiimikansioksi*, kohteen tiedoissa tiimikansion
nimi lisää tai poistaa kohteen). Sivu tarvitsee **tiimin avaimen** (*Jakamisen asetukset*): sillä se avaa repoon
`[kansio] …` -issuen, jonka `kansiopyynto.yml` toteuttaa, kommentoi ja sulkee noin minuutissa; sivu näyttää muutoksen heti
ja vahvistaa sen, kun pyyntö on käsitelty. Issuen runko on konekielinen (`kansio:`, `toiminto: lisaa|poista|uusi|muokkaa|poista_kansio`,
`nimi:`, `kuvaus:`, `saannot:` JSON, `ehdottaja:`, `kohteet:`), ja `scripts/kansiopyynto.py` tarkistaa tunnisteet aineistoa
vasten ja suodattaa säännöt sallittuihin avaimiin ennen kuin kirjoittaa YAMLin. Ilman avainta tehty issue jää odottamaan
ylläpitäjän kommenttia `/hyvaksy`.

**Ylläpitäjä: tiimin avain (kerran).** GitHub → Settings → Developer settings → Personal access tokens → Fine-grained →
*Generate new token*: Repository access *Only select repositories* → tämä repo; Permissions → Repository permissions →
*Issues: Read and write* (Metadata: Read tulee mukana); voimassaolo enintään vuosi. Kopioi `github_pat_…` ja jaa se
tiimille Teamsissä (yksityisviesti tai kanavan kiinnitetty viesti). Avain ei pääse koodiin, aineistoon eikä asetuksiin; jos
se vuotaa, poista se GitHubista – pahin seuraus on turhia issueita. Uusi avain ennen voimassaolon päättymistä, vanha pois.

## Teams ja Outlook

* **Jaa Teamsiin** (kansion rivillä ja kohteen tiedoissa) avaa Teamsin jakoikkunan valmiilla linkillä (`?k=<tunnus>` avaa
  sivun kansio valittuna).
* **Kalenteri**: *Outlook* lisää syötteen Microsoft 365 -kalenteriin "Internet-kalenterina" (päivittyy itsestään), *Google*
  Google-kalenteriin, *webcal* Appleen tai muuhun sovellukseen; *.ics* on raaka osoite.
* **Teams-ilmoitukset** Power Automatella (ei vaadi ylläpitäjää, Teamsin vakiokäyttäjä riittää): Power Automate →
  *Create* → *Automated cloud flow* → trigger **"When a feed item is published" (RSS)**, *The RSS feed URL* = kansion
  Atom-osoite (`https://editmonster.github.io/Saadosseuranta/data/kansiot/<tunnus>.xml`, sivulla *Teams-ilmoitukset
  (syöte)*) → action **"Post message in a chat or channel"** (Teams), *Post as* Flow bot, *Post in* Channel, viestiin
  dynaamiset kentät *Feed title* ja *Primary feed link*. Syötteessä on yksi merkintä per kohde ja määräaika (60 päivän
  sisällä), tunnisteena `urn:saadosseuranta:<tunnus>:<kohde>:<laji>:<pvm>`, joten sama määräaika postataan vain kerran.

Jaetut kansiot ovat julkisia siinä missä repokin: älä kirjoita niihin asiakas- tai toimeksiantotietoa.
