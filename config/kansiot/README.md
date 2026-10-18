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
  lajit: [laki, eu, delegoitu]                     # rajaa säädökset lajeihin (laki, asetus, eu, delegoitu, kuuleminen, kirjelma)
  toimialat: [Lakipalvelut, ICT ja ohjelmistot]    # kilpailutukset (config/hankinnat.yaml)
  hankintayksikot: [Hansel Oy, Helsingin kaupunki] # kilpailutukset, osuma hankintayksikön nimen alusta
  kilpailutusvaiheet: [avoin, tulossa, mao]        # tulossa, avoin, ratkaistu, suorahankinta, mao (oletus: kaikki)
  hakusanat: [hankintalaki, kilpailutus]           # otsikko tai tiivistelmä sisältää sanan (ei kirjainkokoa)
  yrityskaupat:
    vain_suomalaiset: true                         # KKV:n tapaukset ja komission tapaukset, joissa suomalainen osapuoli
    osapuolet: [UPM, Kesko]                        # osapuolen nimen osa
    toimialat: [Teollisuus]                        # yrityskauppojen toimialaluokat (config/yrityskaupat.yaml)
  vain_avoimet: true                               # vain keskeneräiset: avoimet kilpailutukset, vireillä olevat yrityskaupat, voimaan tulemattomat säädökset
  enintaan: 300                                    # enimmäismäärä sääntöjen tuomia kohteita (uusimmat ensin)
```

Kaikki kentät ovat valinnaisia paitsi `nimi`. Kansion voi luoda myös sivulta: Kansiot › Hallitse › oman kansion
kohdalla *Jaa tiimikansioksi* avaa GitHubiin valmiiksi täytetyn tiedoston. Muutosehdotukset (kohteen lisäys tai
poisto) tehdään sivulta *Ehdota*-painikkeella: se avaa GitHub-issuen, jonka `kansiopyynto.yml`-työnkulku toteuttaa
automaattisesti, jos ehdottajalla on kirjoitusoikeus repoon – muuten ylläpitäjä hyväksyy sen kommentilla `/hyvaksy`.

Jaetut kansiot ovat julkisia siinä missä repokin: älä kirjoita niihin asiakas- tai toimeksiantotietoa.
