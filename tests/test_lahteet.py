"""Uudet lähteet: Hankeikkunan valmisteluasiakirjat, HE:n sisältö ja säätämisjärjestys, täysistunto (äänestykset,
puheenvuorot, lausumat), KKO:n valitusluvat, lautakuntien syötteet, OEIL:n asiakirjat ja direktiivien NIM."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_lausunnot as bl  # noqa: E402
import fetch_arviointineuvosto as fa  # noqa: E402
import fetch_nim as fn  # noqa: E402
import fetch_oeil as fo  # noqa: E402
import fetch_taysistunto as ft  # noqa: E402
import fetch_toimiala as fti  # noqa: E402

S = ROOT / "tests" / "samples"


def _d(t, n, d, u="https://api.hankeikkuna.fi/asiakirjat/x/y/z.pdf"):
    return {"t": t, "n": n, "d": d, "u": u + n.replace(" ", "")}


def test_prep_section_key_and_routine_documents():
    docs = [_d("ASETTAMISPAATOS", "Asettamispäätös 22.1.2021", "2021-01-22"),
            *[_d("POYTAKIRJA", f"Työryhmän pöytäkirja {i}_2021", f"2021-0{i}-10") for i in range(1, 8)],
            _d("KUTSU", "Kokouskutsu 5.5.2021", "2021-05-01"),
            _d("KUTSU", "Styrgruppen 5.5.2021 Möteskallelse", "2021-05-01"),
            _d("RAPORTTI", "Työryhmän mietintö OM 2023 32", "2023-12-12"),
            _d("LAUSUNTOPYYNTO", "Lausuntopyyntö - Työryhmän mietintö", "2023-12-12"),
            _d("LAUSUNTOPYYNTO", "Begäran om utlåtande - Arbetsgruppens betänkande", "2023-12-12"),
            _d("KIRJE", "Luonnos HE laiksi opioidiyliannostusten vastalääkkeistä", "2024-03-01"),
            _d("LAUSUNTOPYYNTO", "Lausuntopyyntö luonnoksesta", "2024-03-01"),
            _d("LIITE", "Eriävä mielipide - SAK ja STTK", "2024-05-02"),
            _d("YHTEENVETO", "Lausuntoyhteenveto", "2024-06-01")]
    sec = bl.prep_section(docs)
    labels = [(e["date"], e["label"]) for e in sec["keskeiset"]]
    assert ("2021-01-22", "Hanke asetettu") in labels
    assert ("2023-12-12", "Työryhmän mietintö tai selvitys") in labels
    assert ("2024-03-01", "Luonnos hallituksen esitykseksi lausunnolle") in labels  # draft + request merged
    assert ("2024-05-02", "Eriävä mielipide") in labels and ("2024-06-01", "Lausuntoyhteenveto") in labels
    names = [d["n"] for e in sec["keskeiset"] for d in e["docs"]]
    assert not any("Begäran" in n for n in names)  # Swedish versions left out
    muut = sec["muut"]
    assert muut["n"] == 8 and muut["first"] == "2021-01-10" and muut["last"] == "2021-07-10"
    assert [g["label"] for g in muut["groups"]] == ["Pöytäkirjat ja muistiot", "Kokouskutsut"]
    assert muut["groups"][0]["rivit"][0]["d"] == "2021-07-10"  # newest first


def test_he_content_summary_and_enactment_order():
    xml = ("<he:HallituksenEsitys><asi:SisaltoKuvaus><sis:KappaleKooste>Esityksessä ehdotetaan muutettavaksi lakia x."
           "</sis:KappaleKooste></asi:SisaltoKuvaus><asi:PerusteluOsa><sis1:OtsikkoTeksti>12 Suhde perustuslakiin ja "
           "säätämisjärjestys</sis1:OtsikkoTeksti> Ehdotus on arvioitava perustuslain 6 §:n kannalta. Edellä mainituilla perusteilla "
           "lakiehdotukset voidaan käsitellä tavallisessa lainsäätämisjärjestyksessä. Hallitus pitää kuitenkin suotavana, että "
           "perustuslakivaliokunta antaisi asiasta lausunnon.</asi:PerusteluOsa> Ponsi Edellä esitetyn perusteella annetaan "
           "eduskunnan hyväksyttäviksi seuraavat lakiehdotukset: 1. Laki x</he:HallituksenEsitys>")
    c = fa.he_content(xml)
    assert c["sisalto"] == "Esityksessä ehdotetaan muutettavaksi lakia x."
    assert c["sj"]["order"] == "tavallinen" and c["sj"]["pev"] is True
    assert "suotavana" in c["sj"]["text"] and "Laki x" not in c["sj"]["text"]
    c2 = fa.he_content("<x>10 Säätämisjärjestys Lakiehdotus on käsiteltävä perustuslain säätämisjärjestyksessä. Ponsi y</x>")
    assert c2["sj"]["order"] == "perustuslaki" and "pev" not in c2["sj"]


def test_plenary_helpers():
    assert ft.local_date("2026-06-10 21:00:00") == "2026-06-11"
    assert ft.local_date("2026-01-14 22:00:00") == "2026-01-15"
    assert ft.party("Kansallisen kokoomuksen eduskuntaryhmä") == "kok" and ft.party("Vasemmistoliiton eduskuntaryhmä") == "vas"
    xml = ("<x><ns:LausumaKannanotto><sis:KappaleKooste>Eduskunta edellyttää, että hallitus seuraa uudistusta.</sis:KappaleKooste>"
           "</ns:LausumaKannanotto><ns:LausumaKannanotto>Eduskunta edellyttää, että hallitus seuraa uudistusta.</ns:LausumaKannanotto></x>")
    assert ft.lausumat(xml) == ["Eduskunta edellyttää, että hallitus seuraa uudistusta."]
    a = {"AanestysId": "56738", "IstuntoPvm": "2026-06-16 21:00:00", "KohtaKasittelyVaihe": "Toinen käsittely ",
         "AanestysOtsikko": "Lakiehdotusten hyväksyminen JAA / hylkääminen EI", "AanestysTulosJaa": "102  ", "AanestysTulosEi": "85 ",
         "AanestysTulosTyhjia": "0", "AanestysTulosPoissa": "12", "AanestysPoytakirjaUrl": "/valtiopaivaasiakirjat/PTK+69/2026"}
    j = [{"Ryhma": "Kansallisen kokoomuksen eduskuntaryhmä", "Jaa": "44 ", "Ei": "0", "Tyhjia": "0", "Poissa": "3", "Tyyppi": "eduskuntaryhma"},
         {"Ryhma": "Sosialidemokraattinen eduskuntaryhmä", "Jaa": "0", "Ei": "40", "Tyhjia": "0", "Poissa": "3", "Tyyppi": "eduskuntaryhma"},
         {"Ryhma": "Hallitusryhmät", "Jaa": "100", "Ei": "0", "Tyhjia": "0", "Poissa": "6", "Tyyppi": "hallitusoppositio"},
         {"Ryhma": "Oppositioryhmät", "Jaa": "2", "Ei": "85", "Tyhjia": "0", "Poissa": "6", "Tyyppi": "hallitusoppositio"},
         {"Ryhma": "Helsingin vaalipiiri", "Jaa": "9", "Ei": "11", "Tyhjia": "0", "Poissa": "2", "Tyyppi": "vaalipiiri"}]
    v = ft.vote_row(a, j)
    assert v["date"] == "2026-06-17" and v["tulos"] == [102, 85, 0, 12] and v["vaihe"] == "Toinen käsittely"
    assert v["ryhmat"] == [["kok", 44, 0, 0, 3], ["sd", 0, 40, 0, 3]] and v["hallitus"] == [100, 0, 0, 6] and v["oppositio"] == [2, 85, 0, 6]
    assert v["url"] == "https://www.eduskunta.fi/valtiopaivaasiakirjat/PTK+69/2026"


def test_kko_valitusluvat_listing_and_card():
    entries = fti.parse_kko_valitusluvat((S / "toimiala" / "finlex_kko_valitusluvat.html").read_text())
    assert len(entries) >= 50
    e = next(x for x in entries if x["n"] == 253)
    assert e["ref"] == "KKO VL:2026-253" and e["keywords"] == ["Tapon yritys", "Todistelu – Hyödyntämiskielto"]
    assert e["path"].endswith("/valitusluvat/2026/253")
    multi = next(x for x in entries if x["n"] == 252)
    assert multi["keywords"] == ["Yrityssaneeraus – Konkurssi, Konkurssivalvonta"]
    card = fti.parse_kko_valituslupa((S / "toimiala" / "finlex_kko_valituslupa.html").read_text())
    assert card["date"] == "2026-10-22"
    assert card["summary"].startswith("Kysymys poliisin tapahtumapaikalla") and "\\" not in card["summary"]


def test_board_feeds():
    k = fti.parse_rss_items((S / "toimiala" / "kril_paatokset.xml").read_text())
    assert len(k) == 30 and k[0]["date"] == "2026-10-26" and k[0]["pid"] == "10333"
    assert k[0]["title"].startswith("Kaupan purku uuden auton") and k[0]["url"].startswith("https://www.kuluttajariita.fi/paatokset/")
    y = fti.parse_rss_items((S / "toimiala" / "yvtltk_tapausselosteet.xml").read_text())
    assert y and y[0]["url"].startswith("https://www.yvtltk.fi/tapausselosteet/")


def test_oeil_documentation_gateway():
    g = fo.parse_gateway((S / "eu" / "oeil_2023_0205.html").read_text())
    by_ref = {d.get("ref"): d for d in g["docs"]}
    assert by_ref["A9-0183/2024"]["label"] == "Parlamentin valiokunnan mietintö" and by_ref["A9-0183/2024"]["date"] == "2024-04-30"
    assert by_ref["SWD(2023)0224"]["url"].startswith("https://eur-lex.europa.eu/")
    assert by_ref["SEC(2023)0255"]["label"].startswith("Sääntelyntarkastelulautakunnan")
    assert by_ref["N9-0090/2023"]["label"] == "Euroopan tietosuojavaltuutetun lausunto (EDPS)"
    assert "PE757.355" not in by_ref  # committee drafts and amendments are left out
    assert g["np"] == 1 and not any(d["label"].startswith("Institution") for d in g["docs"])


def test_nim_rows():
    r = fn.measure_row({"title": "Kirjanpitolaki / Bokföringslag (1336/1997) 30.12.1997, viimeksi muutettuna / ändrad senast genom (1249/2023) 2",
                        "oj": "1336/1997", "notif": "2024-10-01", "type": "Laki", "date": "2024-10-01"})
    assert r == {"title": "Kirjanpitolaki", "sk": "1336/1997", "type": "Laki", "date": "2024-10-01", "notif": "2024-10-01"}
    a = fn.measure_row({"title": "LANDSKAPSLAG (2025:57) om cybersäkerhet", "oj": "2025:57", "type": "Landskapslag"})
    assert "sk" not in a and a["oj"] == "2025:57"
