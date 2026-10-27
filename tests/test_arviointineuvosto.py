"""Lainsäädännön arviointineuvosto (HE-tekstin jakso) ja Hankeikkunan muiden hankkeiden lausuntokierrokset."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_arviointineuvosto as fa  # noqa: E402
import fetch_hankeikkuna as fh  # noqa: E402

# HE 204/2024 vp (abridged): the table of contents names the section first, the section itself has subsections
HE_204 = ("Sisällys 6 Lausuntopalaute 6.2 Lainsäädännön arviointineuvoston lausunto 7 Säännöskohtaiset perustelut … "
          "6 Lausuntopalaute Siinä selostetaan myös lainsäädännön arviointineuvoston 25.10.2024 antamaa lausuntoa. "
          "6.2 Lainsäädännön arviointineuvoston lausunto 6.2.1 Lausunnon sisältö Lainsäädännön arviointineuvosto antoi lausunnon "
          "hallituksen esityksen luonnoksesta 25.10.2024. Lausunnossaan arviointineuvosto katsoi, että hallituksen esitysluonnos "
          "noudattaa välttävästi lainvalmistelun vaikutusarviointiohjetta. Arviointineuvoston mukaan esitysluonnosta tulee korjata "
          "neuvoston lausunnon mukaisesti ennen hallituksen esityksen antamista. 6.2.2 Lausunnon huomioon ottaminen Esitystä on "
          "täydennetty kotitalousvaikutusten osalta. 7 Säännöskohtaiset perustelut 7.1 Laki x 1 §. Pykälä.")


def test_section_with_subsections_and_grade():
    rec = fa.extract(HE_204)
    assert rec["found"] and rec["date"] == "2024-10-25" and rec["verdict"] == "välttävästi" and rec["fixFirst"] is True
    assert rec["text"].startswith("Lainsäädännön arviointineuvosto antoi lausunnon") and "kotitalousvaikutusten" in rec["text"]
    assert "Säännöskohtaiset" not in rec["text"] and "6.2.1" not in rec["text"]
    assert fa.VERDICT_LABEL[rec["verdict"]] == "täyttää välttävästi"


def test_grade_scale_and_hyperlink_label():
    # HE 190/2025 vp: Word's hyperlink label is left in the sentence
    text = ("6.3 Lainsäädännön arviointineuvoston lausunto Lainsäädännön arviointineuvosto antoi lausuntonsa Lainsäädännön "
            "arviointineuvoston lausunto (13.10.2025) esitysluonnoksesta 13.10.2025. Lausunnossaan arviointineuvosto totesi "
            "esitysluonnoksen täyttävän hyvin lainvalmistelun vaikutusarviointiohjeen vaatimukset. 7 Säännöskohtaiset perustelut x")
    rec = fa.extract(text)
    assert rec["verdict"] == "hyvin" and "fixFirst" not in rec and "(13.10.2025)" not in rec["text"]
    assert fa.grade("hallituksen esitysluonnos täyttää tyydyttävästi vaatimukset")[0] == "tyydyttävästi"
    assert fa.grade("esitysluonnos noudattaa osittain arviointiohjetta")[0] == "osittain"
    assert fa.grade("esitysluonnos ei täytä vaatimuksia")[0] == "ei täytä"


def test_mention_without_section_and_no_mention():
    text = ("1.2 Valmistelu Esitysluonnos oli lausunnolla. Hallituksen esitys oli lainsäädännön arviointineuvoston arvioitavana "
            "ajalla 5.–18.6.2026. 2 Nykytila ja sen arviointi 2.1 Eläintenpitokielto Sääntelystä säädetään rikoslaissa.")
    rec = fa.extract(text)
    assert rec["found"] and rec["text"].startswith("Hallituksen esitys oli lainsäädännön arviointineuvoston") and "Nykytila" not in rec["text"]
    assert fa.extract("1 Asian tausta Esitys koskee passilakia. 2 Nykytila Passeista säädetään laissa.") == {"found": False}
    assert fa.extract("Esitys ei ole ollut lainsäädännön arviointineuvoston arvioitavana.")["found"] is False


def test_hankeikkuna_other_consultations():
    r = {"kohde": {"uuid": "abcdef12-0000", "tunnus": "MMM012:00/2026", "nimi": {"fi": "Susikannan hoitosuunnitelman päivitys"},
                   "asettajaUuid": "mmm", "tyyppi": "HANKE"},
         "etapit": [{"tyyppi": "LAUSUNTOKIERROS", "alku": "2026-10-09", "loppu": "2026-12-05", "uuid": "e1e1e1e1"},
                    {"tyyppi": "LAUSUNTOKIERROS", "alku": "2025-01-01", "loppu": "2025-02-01", "uuid": "old00000"},
                    {"tyyppi": "KOKOUS", "alku": "2026-10-01"}],
         "linkit": [{"url": {"fi": "https://www.lausuntopalvelu.fi/FI/Proposal/Participation?proposalId=x"}}],
         "asiakirjat": [{"tyyppi": "LAUSUNTOPYYNTO", "url": "https://api.hankeikkuna.fi/asiakirjat/a/b/LP.PDF"}]}
    rows = fh.consultation_rows(r, {"mmm": "maa- ja metsätalousministeriö"})
    assert len(rows) == 1
    row = rows[0]
    assert row["laji"] == "kuuleminen" and row["deadline"] == "2026-12-05" and row["authority"] == "maa- ja metsätalousministeriö"
    assert row["url"] == "https://valtioneuvosto.fi/hanke?tunnus=MMM012:00/2026" and row["lausuntopalvelu"].startswith("https://www.lausuntopalvelu.fi/")


def test_hankeikkuna_council_flag():
    r = {"kohde": {"uuid": "u1", "nimi": {"fi": "x"}}, "lainsaadanto": {"tehtavaluokka": "HALLITUKSEN_ESITYKSEN_VALMISTELU",
                                                                     "lainsaadannonArviointineuvosto": True}}
    assert fh.normalise(r, {}, {})["arviointineuvosto"] is True
