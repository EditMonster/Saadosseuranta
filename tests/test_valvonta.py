"""Yksikkötestit valvontalähteille tallennetuilla näytteillä (tests/samples/valvonta): Helsingin
hankintapäätösten jäsennys (Elasticsearch-osuma + päätössivu), 21 päivän valitusaika-arvio ja
linkitys ostajan ja päätöspäivän perusteella, Tutkihankintoja-vastausten jäsennys ja ostajien
täsmäytys, KKV:n valvontalistausten ja tapaussivujen jäsennys sekä rakentajien rivimuodot.
Ei verkkoa: HTTP korvataan näytteillä monkeypatchilla."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
S = ROOT / "tests" / "samples" / "valvonta"

import build_valvonta  # noqa: E402
import fetch_kkv  # noqa: E402
import fetch_kkv_valvonta  # noqa: E402
import fetch_paatokset  # noqa: E402
import fetch_toimittajat  # noqa: E402
from common import TODAY  # noqa: E402


class Resp:
    def __init__(self, text: str, status: int = 200, content: bytes | None = None):
        self.text, self.status_code = text, status
        self.content = content if content is not None else text.encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return json.loads(self.text)


@pytest.fixture
def hit():
    return json.loads((S / "es_hit.json").read_text(encoding="utf-8"))


@pytest.fixture
def hcfg():
    import yaml
    return yaml.safe_load((ROOT / "config" / "hankinnat.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def settings():
    import yaml
    return yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))


# ---------- Helsinki: Elasticsearch hit + decision page ----------

def test_es_hit_parsing(hit):
    d = fetch_paatokset.from_hit(hit)
    assert d["id"] == "acaebb52-992c-487d-a321-9b20e04e956e"
    assert d["date"] == "2026-10-15" and d["maker"] == "Hankintajohtaja"
    assert d["title"] == "Henkilöturvajärjestelmä ja siihen liittyvät palvelut"
    assert d["issueId"] == "HEL 2026-000013" and d["url"].startswith("https://paatokset.hel.fi/fi/asia/hel-2026-000013?paatos=")
    assert d["value"] == 7000000
    assert [w["name"] for w in d["winners"]] == ["Loihde Trust Oy", "Tunstall Oy", "Everon Oy", "Vivago Oy"]
    assert d["winners"][0]["yTunnus"] == "0863729-2"
    assert [w["name"] for w in d["losers"]] == ["Ascom Oy"]           # excluded tenderer; the 5 tenders -> no extra losers
    assert d["tenderers"] == 5
    assert d["noticeDate"] == "2026-06-18" and d["rfqDate"] == "2026-06-17"
    assert d["helRefs"] == ["HEL 2026-000013"]
    assert d["framework"] is True and d["type"] == "valinta"
    assert d["summary"].startswith("Hankintajohtaja päätti hyväksyä") and len(d["summary"]) <= 425


def test_es_hit_filters():
    base = {"_source": {"id": ["{AAA}"], "field_is_decision": [True], "subject": ["Jotain"], "issue_subject": ["Toimipaikat 2027"],
                        "meeting_date": [1792022400], "organization_name": ["Johtaja"], "decision_url": ["/fi/asia/x"], "category_name": ["Muu"]}}
    assert fetch_paatokset.from_hit(base) is None
    ok = json.loads(json.dumps(base))
    ok["_source"]["issue_subject"] = ["Hankinta, jotain, kaupunginkanslia"]
    assert fetch_paatokset.from_hit(ok)["id"] == "aaa"
    card = json.loads(json.dumps(ok))
    card["_source"]["category_name"] = ["Pankkipalveluiden hallinta"]
    assert fetch_paatokset.from_hit(card) is None
    agenda = json.loads(json.dumps(ok))
    agenda["_source"]["field_is_decision"] = [False]
    assert fetch_paatokset.from_hit(agenda) is None


def test_epoch_to_helsinki_date():
    assert fetch_paatokset.epoch_date(1792022400) == "2026-10-15"   # 00:00 UTC
    assert fetch_paatokset.epoch_date(1792069200) == "2026-10-15"   # 13:00 UTC = 16:00 Helsinki
    assert fetch_paatokset.epoch_date("x") is None


def test_amount_and_type_parsing():
    assert fetch_paatokset.parse_amount("tilata muutostyöt GRK Suomi Oy:ltä 12 841,95 euron arvonlisäverottomaan hintaan") == 12841.95
    assert fetch_paatokset.parse_amount("Hankinnan arvo on 193 000 euroa (alv 0 %).") == 193000
    assert fetch_paatokset.parse_amount("yhteensä enintään 1.842,65 euron arvonlisäverottomaan hintaan") == 1842.65
    assert fetch_paatokset.parse_amount("maksetaan 500 euroa kuukaudessa") is None
    assert fetch_paatokset.decision_type("Telakkaranta, kokonaisurakka, lisätyötilaus, 12 841,95 euroa", "", "Kilpailutus") == "lisätyö"
    assert fetch_paatokset.decision_type("Hankinnan keskeyttäminen, maastomalli", "päätti keskeyttää", "Kilpailutus") == "keskeytys"
    assert fetch_paatokset.decision_type("Sofokus Oy:n hyväksyminen", "hyväksyä osallistumishakemuksen dynaamiseen hankintajärjestelmään", None) == "dps"
    assert fetch_paatokset.decision_type("Asiantuntijatyön hankkiminen", "päätti jatkaa", "Hankinta ilman kilpailutusta") == "suorahankinta"


def test_winner_list_cleanup():
    paatos = "Johtaja päätti valita puitejärjestelyyn seuraavat palveluntuottajat etusijajärjestyksessä:\n1. Freetax Company Oy\n2. NAL Palvelut Oy\n" \
             "3. Suur-Helsingin Valkonauha ry\nJohtaja päätti sulkea Testi Oy:n tarjouskilpailusta.\n" \
             "Hankinnan kohteena on pitkä kuvaus osa-alueista (osa-alue 1: Business Finland Oy ja osa-alue 2: Helsingin kaupunki), jota ei pidä lukea voittajaksi koska lause on pitkä."
    w, l = fetch_paatokset.winners_losers(paatos)
    assert [x["name"] for x in w] == ["Freetax Company Oy", "NAL Palvelut Oy", "Suur-Helsingin Valkonauha ry"]
    assert [x["name"] for x in l] == ["Testi Oy"]


def test_decision_page_parsing():
    p = fetch_paatokset.parse_page((S / "decision_page.html").read_text(encoding="utf-8"))
    assert p["valitusosoitus"] is True and p["oikaisuohje"] is True and p["muutoksenhakukielto"] is False
    assert p["visible"] == "2026-10-16"
    assert p["pdf"] == "https://ahjojulkaisu.hel.fi/D4C2DF91-072B-CB0C-9619-A13E01D00001.pdf"


def test_oulu_rss(monkeypatch):
    raw = (S / "oulu_rss.xml").read_bytes()
    monkeypatch.setattr(fetch_paatokset, "http", lambda *a, **k: Resp(raw.decode("latin-1"), content=raw))
    items = fetch_paatokset.fetch_oulu()
    assert items and all(i["id"].startswith("oulu-") and i["city"] == "Oulu" for i in items)
    urak = next(i for i in items if i["title"].startswith("Urakoitsijavalinta"))
    assert urak["date"] == "2026-10-15" and urak["served"] == "2026-10-15" and urak["servedUntil"] == "2026-11-05"
    assert urak["maker"] == "Rakennuttamispäällikkö"
    assert not any("luokanopettajan" in i["title"] for i in items)  # staffing decisions are not procurement


# ---------- build_valvonta.decision_rows: 21-day estimate, linking by buyer + date ----------

def _decision(did="acaebb52-992c-487d-a321-9b20e04e956e", date="2026-10-15", **over):
    d = {"id": did, "city": "Helsinki", "issueId": "HEL 2026-000013", "issueSubject": "Hankinta, yhteishankinta, henkilöturvajärjestelmä ja siihen liittyvät palvelut, kaupunginkanslia",
         "title": "Henkilöturvajärjestelmä ja siihen liittyvät palvelut", "maker": "Hankintajohtaja", "date": date, "section": 57,
         "category": "Kilpailutus", "url": "https://paatokset.hel.fi/fi/asia/hel-2026-000013?paatos=" + did,
         "winners": [{"name": "Loihde Trust Oy", "yTunnus": "0863729-2"}, {"name": "Tunstall Oy"}], "losers": [{"name": "Ascom Oy"}],
         "value": 7000000, "helRefs": ["HEL 2026-000013"], "noticeDate": "2026-06-18", "framework": True, "type": "valinta",
         "summary": "Hankintajohtaja päätti hyväksyä…", "valitusosoitus": True, "oikaisuohje": True, "visible": "2026-10-16"}
    d.update(over)
    return d


def _cache(monkeypatch, decisions: dict):
    monkeypatch.setattr(build_valvonta, "load_json", lambda path, default: {"decisions": decisions} if "paatokset" in str(path) else default)


def test_decision_row_shape_and_appeal_estimate(monkeypatch, settings, hcfg):
    today = TODAY.isoformat()
    _cache(monkeypatch, {"a": _decision("a", today)})
    rows = build_valvonta.decision_rows(settings, [], hcfg, [])
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == "hk-pt-a" and r["stage"] == "paatos" and r["kind"] == "Hankintapäätös"
    assert r["scope"] == "hankinta" and r["laji"] == "kilpailutus"
    assert r["buyer"] == "Helsingin kaupunki – Hankintajohtaja" and r["decisionMaker"] == "Hankintajohtaja"
    assert r["decisionDate"] == today and r["published"] == today
    assert r["winner"] == "Loihde Trust Oy; Tunstall Oy" and r["losers"] == ["Ascom Oy"]
    assert r["value"] == 7000000 and r["currency"] == "EUR"
    assert r["status"] == "valitusaika"
    assert r["appealEnd"] == (TODAY + dt.timedelta(days=21)).isoformat()
    assert r["url"].startswith("https://paatokset.hel.fi/")
    assert r["topics"] and "ICT ja ohjelmistot" in r["topics"] or r["topics"] == ["Muut"] or r["topics"]
    labels = [e["label"] for e in r["events"]]
    assert "Hankintapäätös" in labels and "Hankintailmoitus julkaistu" in labels
    dl = [e for e in r["events"] if e["kind"] == "maaraaika"]
    assert len(dl) == 1 and dl[0]["confirmed"] is False and dl[0]["date"] == r["appealEnd"]
    assert dl[0]["label"].startswith("Hankintaoikaisu / valitus markkinaoikeuteen 14 pv tiedoksisaannista (arvio")
    dates = [e["date"] for e in r["events"]]
    assert dates == sorted(dates)
    assert "related" not in r


def test_decision_row_expired(monkeypatch, settings, hcfg):
    old = (TODAY - dt.timedelta(days=30)).isoformat()
    _cache(monkeypatch, {"b": _decision("b", old)})
    r = build_valvonta.decision_rows(settings, [], hcfg, [])[0]
    assert r["status"] == "päättynyt" and r["appealEnd"] == (TODAY - dt.timedelta(days=9)).isoformat()
    older = (TODAY - dt.timedelta(days=int(settings["paatokset"]["keep_days"]) + 1)).isoformat()
    _cache(monkeypatch, {"c": _decision("c", older)})
    assert build_valvonta.decision_rows(settings, [], hcfg, []) == []


def test_decision_no_appeal_right(monkeypatch, settings, hcfg):
    today = TODAY.isoformat()
    _cache(monkeypatch, {"k": _decision("k", today, muutoksenhakukielto=True, valitusosoitus=False, oikaisuohje=True),
                         "n": _decision("n", today, muutoksenhakukielto=True, valitusosoitus=False, oikaisuohje=False)})
    rows = {r["id"]: r for r in build_valvonta.decision_rows(settings, [], hcfg, [])}
    k, n = rows["hk-pt-k"], rows["hk-pt-n"]
    assert k["status"] == "valitusaika" and [e for e in k["events"] if e["kind"] == "maaraaika"][0]["label"].startswith("Hankintaoikaisu 14 pv")
    assert n["status"] == "päättynyt" and "appealEnd" not in n and not any(e["kind"] == "maaraaika" for e in n["events"])


def test_decision_links_to_hilma_and_market_court(monkeypatch, settings, hcfg):
    today = TODAY.isoformat()
    _cache(monkeypatch, {"a": _decision("a", today)})
    tenders = [
        {"id": "hk-EF-1", "stage": "avoin", "kind": "Hankintailmoitus", "buyer": "Helsingin kaupunki", "title": "Henkilöturvajärjestelmä ja siihen liittyvät palvelut",
         "summary": "Kaupunginkanslia pyytää tarjouksia", "published": "2026-06-18", "topics": ["ICT ja ohjelmistot"]},
        {"id": "hk-EF-2", "stage": "avoin", "kind": "Hankintailmoitus", "buyer": "Espoon kaupunki", "title": "Henkilöturvajärjestelmä ja siihen liittyvät palvelut",
         "summary": "", "published": "2026-06-18", "topics": ["ICT ja ohjelmistot"]},          # other buyer: never linked
        {"id": "hk-EF-3", "stage": "ratkaistu", "kind": "Jälki-ilmoitus", "buyer": "Helsingin kaupunki, kaupunkiympäristön toimiala", "title": "Katujen talvihoito",
         "summary": "Dnro HEL 2026-000013", "published": "2026-09-01", "topics": ["Kiinteistö- ja huoltopalvelut"]},  # number match
        {"id": "hk-EF-4", "stage": "avoin", "kind": "Hankintailmoitus", "buyer": "Helsingin kaupunki", "title": "Leikkipuiston kalusteet",
         "summary": "", "published": "2026-06-18", "topics": ["Koneet, laitteet ja tarvikkeet"]},   # same notice date, no title overlap
    ]
    mao = [
        {"id": "mao-v-abc", "stage": "mao", "kind": "Valitus markkinaoikeudessa", "buyer": "Helsingin kaupunki", "filed": (TODAY + dt.timedelta(days=3)).isoformat(),
         "decisionDate": today, "published": today, "events": [{"date": today, "label": "Hankintapäätös", "kind": "muu"}]},
        {"id": "mao-v-def", "stage": "mao", "kind": "Valitus markkinaoikeudessa", "buyer": "Helsingin kaupunki", "filed": today, "decisionDate": "2026-01-01", "published": today, "events": []},
        {"id": "mao-r-1-2026", "stage": "mao", "kind": "Markkinaoikeuden ratkaisu", "buyer": "Helsingin kaupunki", "decisionDate": today, "published": today, "events": []},
        {"id": "mao-v-ghi", "stage": "mao", "kind": "Valitus markkinaoikeudessa", "buyer": "Vantaan kaupunki", "filed": today, "decisionDate": today, "published": today, "events": []},
    ]
    r = build_valvonta.decision_rows(settings, tenders, hcfg, mao)[0]
    rel = {x["id"] for x in r["related"]}
    assert rel == {"hk-EF-1", "hk-EF-3", "mao-v-abc"}
    assert r["appealed"] is True
    assert set(r["topics"]) == {"ICT ja ohjelmistot", "Kiinteistö- ja huoltopalvelut"}   # CPV topics of the linked notices
    assert any(e["label"] == "Valitus vireille markkinaoikeudessa" for e in r["events"])
    # reverse links were added in place
    assert any(x["id"] == "hk-pt-a" and x["stage"] == "paatos" for x in tenders[0]["related"])
    assert any(x["id"] == "hk-pt-a" for x in mao[0]["related"])
    assert "related" not in tenders[1] and "related" not in mao[1] and "related" not in mao[3]


def test_market_court_link_on_a_busy_day(monkeypatch, settings, hcfg):
    today = TODAY.isoformat()
    _cache(monkeypatch, {"a": _decision("a", today), "b": _decision("b", today, title="Katujen talvihoito 2026–2028", issueSubject="Hankinta, katujen talvihoito", section=12, helRefs=[], noticeDate=None)})
    mao = [{"id": "mao-v-1", "stage": "mao", "kind": "Valitus markkinaoikeudessa", "buyer": "Helsingin kaupunki", "filed": today, "decisionDate": today, "published": today,
            "decisionText": f"Helsingin kaupungin hankintajohtajan päätös {TODAY.day}.{TODAY.month}.{TODAY.year}, 57 §, henkilöturvajärjestelmä ja siihen liittyvät palvelut", "events": []},
           {"id": "mao-v-2", "stage": "mao", "kind": "Valitus markkinaoikeudessa", "buyer": "Helsingin kaupunki", "filed": today, "decisionDate": today, "published": today,
            "decisionText": "Helsingin kaupungin päätös, 12 §", "events": []}]
    rows = {r["id"]: r for r in build_valvonta.decision_rows(settings, [], hcfg, mao)}
    assert [x["id"] for x in rows["hk-pt-a"]["related"]] == ["mao-v-1"]
    assert [x["id"] for x in rows["hk-pt-b"]["related"]] == ["mao-v-2"]


def test_city_matching_and_overlap():
    assert build_valvonta.is_city("Helsingin kaupunki, kaupunkiympäristön toimiala")
    assert build_valvonta.is_city("Kulttuurin ja vapaa-ajan toimiala, Helsingin kaupunki")
    assert not build_valvonta.is_city("Helsingin yliopisto") and not build_valvonta.is_city("HSY Helsingin seudun ympäristöpalvelut -kuntayhtymä")
    a = build_valvonta.tokens("Henkilöturvajärjestelmä ja siihen liittyvät palvelut")
    b = build_valvonta.tokens("Henkilöturvajärjestelmän hankinta puitejärjestelynä")
    assert build_valvonta.overlap(a, b) >= 0.6


# ---------- Tutkihankintoja ----------

def test_tutkihankintoja_index_and_tables():
    idx = json.loads((S / "th_index_vendors.json").read_text(encoding="utf-8"))
    index = fetch_toimittajat.buyer_index(idx)
    assert len(index) >= 50 and index["maanmittauslaitos"]["branch"] == "sub"
    assert index["valtioneuvoston kanslia"]["id"] == "Valtioneuvoston kanslia"       # decoded once
    assert fetch_toimittajat.match_buyer("Maanmittauslaitos", index)["name"] == "Maanmittauslaitos"
    assert fetch_toimittajat.match_buyer("Liikenne- ja viestintävirasto Traficom", index)["name"] == "Liikenne- ja viestintävirasto"
    assert fetch_toimittajat.match_buyer("Valtion tieto- ja viestintätekniikkakeskus Valtori", index)["name"].startswith("Valtion tieto- ja viestint")
    assert fetch_toimittajat.match_buyer("Työ- ja elinkeinoministeriön hallinnonala", index)["branch"] == "main"
    assert fetch_toimittajat.match_buyer("Hansel Oy", index) is None
    assert fetch_toimittajat.match_buyer("Helsingin kaupunki", index) is None
    cat = json.loads((S / "th_vendors_buyer_category.json").read_text(encoding="utf-8"))
    table = fetch_toimittajat.vendors_table(cat)
    assert len(table) == 30 and table[0]["name"].startswith("Valtion tieto- ja viestint") and table[1] == {"name": "Solita Oy", "yTunnus": "2905040-7", "sum": 2183797.4}
    top = fetch_toimittajat.merge([table, table], "ICT-hankinnat (tavarat, palvelut ja ohjelmistot)")
    assert len(top) == 8 and top[1]["sum"] == 2 * 2183797 + 1 and top[1]["category"].startswith("ICT") and top[1]["yTunnus"] == "2905040-7"
    assert all(t["category"] for t in top) and "yTunnus" not in top[0]


def test_tutkihankintoja_windows():
    w = fetch_toimittajat.windows(dt.date(2026, 10, 18))
    assert w == [(dt.date(2025, 10, 14), dt.date(2025, 12, 31)), (dt.date(2026, 1, 1), dt.date(2026, 10, 13))]
    assert all(a.year == b.year for a, b in w)


def test_tutkihankintoja_key_rejected(monkeypatch):
    monkeypatch.setattr(fetch_toimittajat, "http", lambda *a, **k: Resp("", 401))
    with pytest.raises(RuntimeError, match="avain"):
        fetch_toimittajat.Client("x").get("/index/vendors", {})


def test_attach_incumbents(monkeypatch, settings):
    cache = {"buyers": {"maanmittauslaitos": {"fetched": TODAY.isoformat(), "name": "Maanmittauslaitos", "id": "Maanmittauslaitos", "branch": "sub",
                                              "period": {"from": "2025-10-14", "to": "2026-10-13"},
                                              "top": [{"name": "Senaatti-kiinteistöt", "sum": 6464776, "category": None}, {"name": "Solita Oy", "sum": 3012392, "category": None},
                                                      {"name": "Konekorhonen Oy", "sum": 987079, "category": None}, {"name": "Valtiokonttori", "sum": 900000, "category": None},
                                                      {"name": "Solita Oy", "yTunnus": "2905040-7", "sum": 3012392, "category": "ICT-hankinnat (tavarat, palvelut ja ohjelmistot)"}]}},
             "index": {"names": ["Maanmittauslaitos", "Valtiokonttori"]}}
    monkeypatch.setattr(build_valvonta, "load_json", lambda path, default: cache if "toimittajat" in str(path) else default)
    tenders = [{"id": "hk-1", "stage": "avoin", "buyer": "Maanmittauslaitos", "topics": ["ICT ja ohjelmistot"]},
               {"id": "hk-2", "stage": "avoin", "buyer": "Maanmittauslaitos", "topics": ["Rakentaminen ja infra"]},
               {"id": "hk-3", "stage": "avoin", "buyer": "Espoon kaupunki", "topics": ["ICT ja ohjelmistot"]},
               {"id": "hk-4", "stage": "mao", "buyer": "Maanmittauslaitos", "topics": ["Muut"]}]
    build_valvonta.attach_incumbents(tenders, settings)
    assert tenders[0]["incumbents"] == [{"name": "Solita Oy", "sum": 3012392, "year": "2025–2026", "category": "ICT-hankinnat (tavarat, palvelut ja ohjelmistot)", "yTunnus": "2905040-7"}]
    # no fetched group -> overall top; the state's own providers (Senaatti, Valtiokonttori) are not competitors
    assert [i["name"] for i in tenders[1]["incumbents"]] == ["Solita Oy", "Konekorhonen Oy"]
    assert tenders[1]["incumbents"][0]["year"] == "2025–2026" and "category" not in tenders[1]["incumbents"][0]
    assert "incumbents" not in tenders[2] and "incumbents" not in tenders[3]


# ---------- KKV enforcement ----------

def _kkv_http(url, **kw):
    for cat in fetch_kkv_valvonta.CATEGORIES:
        if url.rstrip("/").endswith("/kilpailuasiat/" + cat):
            return Resp((S / f"kkv_list_{cat if cat != 'kielto-sitoumus-tai-toimitusvelvoiteratkaisut' else 'kielto-sitoumus'}.html").read_text(encoding="utf-8"))
    if url == fetch_kkv_valvonta.FEED:
        return Resp((S / "kkv_feed.xml").read_text(encoding="utf-8"))
    name = {"hankintojen-valvonta": "kkv_case_hankintojen-valvonta.html", "esitykset-markkinaoikeudelle": "kkv_case_esitys-markkinaoikeudelle.html",
            "kielto-sitoumus-tai-toimitusvelvoiteratkaisut": "kkv_case_kielto-sitoumus.html", "kilpailuneutraliteetti": "kkv_case_kilpailuneutraliteetti.html"}
    for cat, f in name.items():
        if f"/kilpailuasiat/{cat}/" in url:
            return Resp((S / f).read_text(encoding="utf-8"))
    raise AssertionError(url)


def test_kkv_listings_and_feed(monkeypatch):
    monkeypatch.setattr(fetch_kkv_valvonta, "http", lambda method, url, **kw: _kkv_http(url))
    rows = fetch_kkv_valvonta.listing("hankintojen-valvonta", 3)
    assert len(rows) == 3 and rows[0]["date"] == "2026-10-15" and rows[0]["status"] == "Hankintojen valvonta"
    assert rows[0]["url"].startswith("https://www.kkv.fi/paatokset/kilpailuasiat/hankintojen-valvonta/oulun-kaupungin")
    assert fetch_kkv_valvonta.listing("kilpailuneutraliteetti", 3)[0]["status"] == "Kilpailuneutraliteettiratkaisu"
    feed = fetch_kkv_valvonta.feed_items()
    assert feed and all(i["category"] in fetch_kkv_valvonta.CATEGORIES for i in feed)
    assert any(i["category"] == "hankintojen-valvonta" and i["date"] for i in feed)
    assert not any("yrityskaup" in i["url"] for i in feed)


def test_kkv_case_pages(monkeypatch):
    monkeypatch.setattr(fetch_kkv, "http", lambda method, url, **kw: _kkv_http(url))
    c = fetch_kkv.parse_case("https://www.kkv.fi/paatokset/kilpailuasiat/hankintojen-valvonta/oulun-kaupungin-x/")
    assert c["diaari"] == "KKV/542/14.00.60/2025" and c["parties"] == "Oulun kaupunki" and c["decided"] == "2026-10-15"
    assert fetch_kkv_valvonta.classify_outcome(c["summary"]) == "huomautus"
    e = fetch_kkv.parse_case("https://www.kkv.fi/paatokset/kilpailuasiat/esitykset-markkinaoikeudelle/x/")
    assert e["diaari"] and e["decided"] and fetch_kkv_valvonta.classify_outcome(e["summary"]) == "esitys markkinaoikeudelle"
    s = fetch_kkv.parse_case("https://www.kkv.fi/paatokset/kilpailuasiat/kielto-sitoumus-tai-toimitusvelvoiteratkaisut/x/")
    assert s["diaari"] and fetch_kkv_valvonta.classify_outcome("Sitoumusten määrääminen. " + s["summary"]) == "sitoumukset"
    n = fetch_kkv.parse_case("https://www.kkv.fi/paatokset/kilpailuasiat/kilpailuneutraliteetti/x/")
    assert n["diaari"] and "14.00.40" in n["diaari"] and n["decided"]
    assert fetch_kkv_valvonta.classify_outcome("Kilpailu- ja kuluttajavirasto esittää markkinaoikeudelle seuraamusmaksun määräämistä") == "esitys markkinaoikeudelle"
    assert fetch_kkv_valvonta.classify_outcome("KKV ei ryhdy asiassa enempiin toimenpiteisiin") == "ei toimenpiteitä"


def test_kkv_valvonta_rows(monkeypatch, settings, hcfg):
    d = TODAY.isoformat()
    cache = {"cases": {
        "KKV/542/14.00.60/2025": {"category": "hankintojen-valvonta", "date": d, "title": "Oulun kaupungin työkonepalveluiden puitejärjestely", "parties": "Oulun kaupunki",
                                  "buyer": "Oulun kaupunki", "summary": "KKV antaa Oulun kaupungille huomautuksen hankintalain noudattamatta jättämisestä.", "outcome": "huomautus",
                                  "url": "https://www.kkv.fi/paatokset/kilpailuasiat/hankintojen-valvonta/oulun-kaupungin-tyokonepalveluiden-puitejarjestely/",
                                  "slug": "oulun-kaupungin-tyokonepalveluiden-puitejarjestely", "diaari": "KKV/542/14.00.60/2025", "seen": d},
        "KKV/1/14.00.60/2026": {"category": "esitykset-markkinaoikeudelle", "date": d, "title": "Esitys markkinaoikeudelle seuraamusmaksun määräämiseksi laittomasta suorahankinnasta",
                                "parties": "Testikunta", "summary": "KKV esittää markkinaoikeudelle, että Testikunnalle määrätään seuraamusmaksu laittomasta suorahankinnasta.",
                                "outcome": "esitys markkinaoikeudelle", "url": "https://www.kkv.fi/paatokset/kilpailuasiat/esitykset-markkinaoikeudelle/kkv-1-14-00-60-2026/",
                                "slug": "kkv-1-14-00-60-2026", "diaari": "KKV/1/14.00.60/2026", "seen": d},
        "KKV/1098/14.00.00/2022": {"category": "esitykset-markkinaoikeudelle", "date": d, "title": "Esitys markkinaoikeudelle seuraamusmaksun määräämiseksi",
                                   "parties": "Arctic International Oy, Polarica AB", "summary": "KKV esittää, että markkinaoikeus määrää yhtiöille seuraamusmaksun kartellista.",
                                   "outcome": "esitys markkinaoikeudelle", "url": "https://www.kkv.fi/paatokset/kilpailuasiat/esitykset-markkinaoikeudelle/esitys-x/", "slug": "esitys-x",
                                   "diaari": "KKV/1098/14.00.00/2022", "seen": d},
        "KKV/2/14.00.00/2025": {"category": "kielto-sitoumus-tai-toimitusvelvoiteratkaisut", "date": d, "title": "Sitoumusten määrääminen matkaviestinmarkkinoilla", "parties": "Operaattori Oy",
                                "summary": "KKV määrää sitoumukset noudatettaviksi.", "outcome": "sitoumukset", "url": "https://www.kkv.fi/paatokset/kilpailuasiat/kielto-sitoumus-tai-toimitusvelvoiteratkaisut/sitoumus-y/",
                                "slug": "sitoumus-y", "diaari": "KKV/2/14.00.00/2025", "seen": d},
        "KKV/3/14.00.40/2024": {"category": "kilpailuneutraliteetti", "date": d, "title": "Maanmittauslaitoksen menettelyt", "parties": "Maanmittauslaitos",
                                "summary": "KKV ei ryhdy enempiin toimenpiteisiin.", "outcome": "ei toimenpiteitä", "url": "https://www.kkv.fi/paatokset/kilpailuasiat/kilpailuneutraliteetti/mml/",
                                "slug": "mml", "diaari": "KKV/3/14.00.40/2024", "seen": d},
        "KKV/4/14.00.60/2020": {"category": "hankintojen-valvonta", "date": (TODAY - dt.timedelta(days=400)).isoformat(), "title": "Vanha", "parties": "X", "summary": "", "outcome": "huomautus",
                                "url": "https://www.kkv.fi/paatokset/kilpailuasiat/hankintojen-valvonta/vanha/", "slug": "vanha", "diaari": "KKV/4/14.00.60/2020", "seen": d},
    }}
    monkeypatch.setattr(build_valvonta, "load_json", lambda path, default: cache if "kkv_valvonta" in str(path) else default)
    out = build_valvonta.kkv_valvonta_rows(settings, hcfg)
    h = {r["id"]: r for r in out["hankinta"]}
    k = {r["id"]: r for r in out["kilpailu"]}
    assert set(h) == {"hk-kkv-oulun-kaupungin-tyokonepalveluiden-puitejarjestely", "hk-kkv-kkv-1-14-00-60-2026"}
    oulu = h["hk-kkv-oulun-kaupungin-tyokonepalveluiden-puitejarjestely"]
    assert oulu["stage"] == "mao" and oulu["kind"] == "KKV:n hankintojen valvonta" and oulu["buyer"] == "Oulun kaupunki" and oulu["status"] == "päätetty"
    assert oulu["scope"] == "hankinta" and oulu["laji"] == "kilpailutus" and oulu["url"].startswith("https://www.kkv.fi/")
    assert oulu["events"] == [{"date": d, "label": "KKV:n päätös – huomautus", "kind": "muu"}] and oulu["topics"]
    esitys = h["hk-kkv-kkv-1-14-00-60-2026"]
    assert esitys["kind"] == "KKV:n esitys markkinaoikeudelle" and esitys["status"] == "esitys markkinaoikeudessa"
    assert esitys["nextStep"] == "Markkinaoikeuden ratkaisu (ei määräaikaa laissa)" and esitys["events"][0]["kind"] == "vahvistettu"
    assert not any(e["kind"] == "maaraaika" for e in esitys["events"])
    assert set(k) == {"kr-kkv-esitys-x", "kr-kkv-sitoumus-y", "kr-kkv-mml"}
    cartel = k["kr-kkv-esitys-x"]
    assert cartel["segment"] == "kilpailunrajoitus" and cartel["authority"] == "KKV" and cartel["kind"] == "Seuraamusmaksuesitys markkinaoikeudelle"
    assert cartel["status"] == "esitys markkinaoikeudessa" and cartel["done"] is False and cartel["parties"].startswith("Arctic") and cartel["ref"] == "KKV/1098/14.00.00/2022"
    assert k["kr-kkv-sitoumus-y"]["kind"] == "Sitoumuspäätös" and k["kr-kkv-sitoumus-y"]["status"] == "sitoumukset"
    assert k["kr-kkv-mml"]["kind"] == "Kilpailuneutraliteetti" and k["kr-kkv-mml"]["status"] == "päätetty" and k["kr-kkv-mml"]["done"] is True
    for r in list(h.values()) + list(k.values()):
        assert r["published"] == d and r["summary"] and r["title"] and r["url"].startswith("https://www.kkv.fi/")
        for e in r["events"]:
            assert e["date"] and e["label"] and e["kind"] in ("muu", "vahvistettu")
