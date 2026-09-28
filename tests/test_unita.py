"""Test unitari: estrattori, stadi B e C con mock (zero chiamate a pagamento), schema, rapporto, CLI."""
import json

import pytest

from onboarding import llm, places
from onboarding.candidati import Candidato
from onboarding.extract_jsonld import estrai_jsonld
from onboarding.extract_text import (
    e164, estrai_indirizzi, estrai_telefoni, estrai_urgenza, parse_orari, piva_valida, estrai_servizi,
)
from onboarding.fetch import FixtureFetcher, crea_pagina
from onboarding.merge import fondi
from onboarding.pipeline import esegui
from onboarding.report import genera
from onboarding.schema import Campo, Statistiche

from .conftest import FIXTURE


def pagina(html, tipo="contatti", url="https://www.esempio.it/contatti/"):
    p = crea_pagina(url, 200, f"<html><head><title>t</title></head><body>{html}</body></html>")
    p.tipo = tipo
    return p


# --- telefoni ---------------------------------------------------------------

@pytest.mark.parametrize("testo,atteso", [
    ("02 897 618 51", "+390289761851"),
    ("+39 02.1234.5678", "+390212345678"),
    ("0039 347 1234567", "+393471234567"),
    ("347-123-4567", "+393471234567"),
    ("800 123 456", "+39800123456"),
    ("+39-3492866321", "+393492866321"),
    ("12345", None),
    ("+44 20 7946 0958", None),
])
def test_e164(testo, atteso):
    assert e164(testo) == atteso


def test_telefoni_non_confonde_partita_iva_fax_e_segnaposto():
    p = pagina("<p>P.IVA 01234567890</p><p>Fax 02 1234567</p><p>Tel. 02 [numero di telefono]</p>"
               "<p>Chiamaci: 333 123 4567</p><a href='tel:+390298765432'>chiama</a>")
    valori = {c.valore for c in estrai_telefoni(p, {"01234567890"})}
    assert valori == {"+393331234567", "+390298765432"}


def test_partita_iva_checksum():
    assert piva_valida("08864490969")
    assert not piva_valida("08864490968")


# --- indirizzi ----------------------------------------------------------------

def test_indirizzo_su_due_righe_con_sigla():
    p = pagina("<p>Via Edmondo de Amicis, 7</p><p>20020 • Solaro MI</p>")
    (c,) = estrai_indirizzi(p)
    assert c.valore == {"via": "Via Edmondo de Amicis, 7", "cap": "20020", "comune": "Solaro", "provincia": "MI"}


def test_indirizzo_segnaposto_scartato():
    p = pagina("<p>Address</p><p>Mainstreet 1234</p><p>12346 Anytown, UK</p>"
               "<p>Via [Inserisci indirizzo o zona operativa principale] – Milano</p>")
    assert estrai_indirizzi(p) == []


def test_comune_non_attribuito_se_ambiguo():
    # "COMO" sulla riga dopo la via è l'etichetta della sede successiva, non il comune della via.
    p = pagina("<p>Via Brera 2</p><p>COMO</p><p>Via Monti 69</p>")
    assert estrai_indirizzi(p) == []


# --- orari --------------------------------------------------------------------

def test_orari_strutturati():
    o, _ = parse_orari("Lun – Ven 8:00 – 13:00 14:00 – 18:00 Sabato 8:00 – 13:00 Domenica Chiuso")
    assert o == {"lun": "08:00-13:00, 14:00-18:00", "mar": "08:00-13:00, 14:00-18:00",
                 "mer": "08:00-13:00, 14:00-18:00", "gio": "08:00-13:00, 14:00-18:00",
                 "ven": "08:00-13:00, 14:00-18:00", "sab": "08:00-13:00", "dom": "chiuso"}


def test_orari_dal_al_dalle_alle():
    o, _ = parse_orari("Siamo aperti dal lunedì al venerdì dalle 8 alle 18")
    assert o == {g: "08:00-18:00" for g in ("lun", "mar", "mer", "gio", "ven")}


def test_orari_in_prosa_restano_vuoti():
    assert parse_orari("Aperti tutti i giorni, anche la domenica")[0] == {}


# --- urgenza ------------------------------------------------------------------

def test_urgenza_h24_e_falsi_positivi():
    assert estrai_urgenza(pagina("<p>Reperibile 24 ore su 24, 7 giorni su 7</p>"))[0][0].valore is True
    assert estrai_urgenza(pagina("<p>Ti risponderemo entro 24 ore.</p>"))[0] == []
    c, solo = estrai_urgenza(pagina("<p>Pronto intervento urgente</p>"))
    assert c == [] and solo is True


# --- servizi ------------------------------------------------------------------

def test_servizi_solo_voci_brevi_del_mestiere():
    p = pagina("<ul><li>Apertura porte blindate</li><li>Chi siamo</li><li>Contatti</li>"
               "<li>Siamo la migliore azienda di fabbri di tutta la Lombardia da sempre</li>"
               "<li>Sostituzione serrature Milano</li></ul>"
               "<p>Realizziamo <strong>cancelli</strong> e molto altro per voi.</p>", tipo="servizi")
    assert [c.valore for c in estrai_servizi(p, "fabbro")] == ["Apertura porte blindate", "Sostituzione serrature"]


# --- JSON-LD ------------------------------------------------------------------

def test_jsonld_locksmith_e_cap_non_valido():
    ld = {"@context": "https://schema.org", "@type": "Locksmith", "name": "Fabbro Rossi",
          "telephone": "+39 02 1234567",
          "address": {"@type": "PostalAddress", "streetAddress": "Via Roma 1", "postalCode": "0068",
                      "addressLocality": "Milano", "addressRegion": "Lombardia"},
          "openingHoursSpecification": [{"@type": "OpeningHoursSpecification", "dayOfWeek": ["Monday", "Tuesday"],
                                         "opens": "08:00", "closes": "18:00"}]}
    p = pagina(f'<script type="application/ld+json">{json.dumps(ld)}</script>')
    avvisi = []
    cands = {c.campo: c for c in estrai_jsonld(p, avvisi)}
    assert cands["telefono"].valore == "+39021234567"
    assert cands["indirizzo"].valore == {"via": "Via Roma 1", "cap": None, "comune": "Milano", "provincia": "Milano"}
    assert cands["orari"].valore == {"lun": "08:00-18:00", "mar": "08:00-18:00"}
    assert any("0068" in a for a in avvisi)


# --- fusione ------------------------------------------------------------------

def test_valori_contraddittori_riportati_entrambi_con_avviso():
    c1 = Candidato("partita_iva", "08864490969", "u1", "P.IVA 08864490969", "regex", "alta")
    c2 = Candidato("partita_iva", "13556570961", "u2", "P.IVA 13556570961", "jsonld", "alta")
    avvisi = []
    az, vuoti = fondi([c1, c2], avvisi)
    assert isinstance(az.partita_iva, list) and len(az.partita_iva) == 2
    assert any("partita_iva" in a for a in avvisi)
    assert "partita_iva" not in vuoti and "telefono" in vuoti


def test_schema_rifiuta_valore_senza_fonte_e_llm_alta():
    with pytest.raises(ValueError):
        Campo(valore="x")
    with pytest.raises(ValueError):
        Campo(valore="x", fonte={"url": "u", "frammento": "x"}, metodo="llm_verificato", confidenza="alta")


# --- stadio C (LLM) con mock ----------------------------------------------------

def test_llm_grounding_accetta_solo_frammenti_letterali():
    p = pagina("<p>Interveniamo a Monza e Sesto San Giovanni per apertura porte e cambio cilindro.</p>"
               "<p>Aperti dal lunedì al sabato dalle 7:30 alle 19</p>", tipo="home", url="https://www.esempio.it/")
    risposta = {"candidati": [
        {"campo": "servizi", "valore": "apertura porte", "frammento": "per apertura porte e cambio cilindro"},
        {"campo": "zone_servite", "valore": "Monza", "frammento": "Interveniamo a Monza e Sesto San Giovanni"},
        {"campo": "orari", "valore": "lun-sab 7:30-19", "frammento": "dal lunedì al sabato dalle 7:30 alle 19"},
        {"campo": "servizi", "valore": "riparazione tapparelle", "frammento": "riparazione tapparelle"},  # inventato
        {"campo": "zone_servite", "valore": "Lodi", "frammento": "Interveniamo a Monza e Sesto San Giovanni"},  # valore non nel frammento
        {"campo": "servizi", "valore": "cambio cilindro", "frammento": "cambio del cilindro"},  # frammento non letterale
    ]}
    chiamate = []

    def finta(messaggi, chiave):
        chiamate.append(messaggi)
        return json.dumps(risposta)

    stat, avvisi = Statistiche(), []
    out = llm.stadio_c([p], "fabbro", avvisi, stat, chiamata=finta)
    assert {(c.campo, str(c.valore)) for c in out} == {
        ("servizi", "apertura porte"), ("zone_servite", "Monza"),
        ("orari", str({g: "07:30-19:00" for g in ("lun", "mar", "mer", "gio", "ven", "sab")})),
    }
    assert stat.llm_chiamate == 1 and stat.llm_candidati == 6 and stat.llm_scartati == 3
    assert all(c.metodo == "llm_verificato" and c.confidenza != "alta" for c in out)


def test_llm_massimo_8_chiamate():
    pagine = [pagina("<p>x</p>", tipo="servizi", url=f"https://www.esempio.it/p{i}/") for i in range(12)]
    stat = Statistiche()
    llm.stadio_c(pagine, "fabbro", [], stat, chiamata=lambda m, k: '{"candidati": []}')
    assert stat.llm_chiamate == 8


def test_llm_saltato_senza_chiave():
    avvisi = []
    assert llm.stadio_c([pagina("<p>x</p>")], "fabbro", avvisi, Statistiche()) == []
    assert any("DEEPSEEK_API_KEY" in a for a in avvisi)


# --- stadio B (Places) con mock -------------------------------------------------

RISPOSTA_PLACES = {
    "displayName": {"text": "Fabbro Rossi", "languageCode": "it"},
    "formattedAddress": "Via Roma, 1, 20121 Milano MI, Italia",
    "addressComponents": [
        {"longText": "1", "shortText": "1", "types": ["street_number"]},
        {"longText": "Via Roma", "shortText": "Via Roma", "types": ["route"]},
        {"longText": "Milano", "shortText": "Milano", "types": ["locality", "political"]},
        {"longText": "Città Metropolitana di Milano", "shortText": "MI", "types": ["administrative_area_level_2", "political"]},
        {"longText": "20121", "shortText": "20121", "types": ["postal_code"]},
    ],
    "internationalPhoneNumber": "+39 02 1234 5678",
    "regularOpeningHours": {"periods": [
        {"open": {"day": 1, "hour": 8, "minute": 0}, "close": {"day": 1, "hour": 18, "minute": 0}},
        {"open": {"day": 0, "hour": 9, "minute": 0}, "close": {"day": 0, "hour": 12, "minute": 0}},
    ]},
    "businessStatus": "OPERATIONAL",
}


def test_place_id_da_link():
    assert places.ricava_place_id("ChIJN1t_tDeuEmsRUsoyG83frY4") == "ChIJN1t_tDeuEmsRUsoyG83frY4"
    assert places.ricava_place_id(
        "https://www.google.com/maps/search/?api=1&query=x&query_place_id=ChIJN1t_tDeuEmsRUsoyG83frY4") == "ChIJN1t_tDeuEmsRUsoyG83frY4"
    assert places.ricava_place_id("https://maps.app.goo.gl/abc123") is None


def test_places_una_chiamata_e_mappatura():
    chiamate = []

    def finta(pid, chiave):
        chiamate.append(pid)
        return RISPOSTA_PLACES

    stat, avvisi = Statistiche(), []
    out = places.stadio_b("ChIJN1t_tDeuEmsRUsoyG83frY4", avvisi, stat, chiamata=finta)
    places.stadio_b("ChIJN1t_tDeuEmsRUsoyG83frY4", avvisi, stat, chiamata=finta)  # seconda: bloccata dal tetto
    assert len(chiamate) == 1 and stat.places_chiamate == 1
    per = {c.campo: c.valore for c in out}
    assert per["telefono"] == "+390212345678"
    assert per["indirizzo"] == {"via": "Via Roma, 1", "cap": "20121", "comune": "Milano", "provincia": "MI"}
    assert per["orari"] == {"lun": "08:00-18:00", "dom": "09:00-12:00"}
    assert all(c.metodo == "google_places" for c in out)


def test_places_saltato_senza_chiave():
    avvisi = []
    assert places.stadio_b("ChIJN1t_tDeuEmsRUsoyG83frY4", avvisi, Statistiche()) == []
    assert any("GOOGLE_PLACES_API_KEY" in a for a in avvisi)


# --- pipeline completa, rapporto, CLI -----------------------------------------

def test_pipeline_con_places_e_llm_finti():
    r = esegui("https://www.lartenelferro.it", "ChIJN1t_tDeuEmsRUsoyG83frY4", "fabbro",
               fetcher=FixtureFetcher(FIXTURE / "arte-nel-ferro"),
               places_chiamata=lambda pid, k: RISPOSTA_PLACES,
               llm_chiamata=lambda m, k: '{"candidati": [{"campo": "servizi", "valore": "x", "frammento": "non esiste"}]}')
    assert r.statistiche.places_chiamate == 1
    assert 1 <= r.statistiche.llm_chiamate <= 8 and r.statistiche.llm_scartati == r.statistiche.llm_chiamate
    # Telefono Google diverso da quello del sito: entrambi riportati
    assert {t.valore for t in r.azienda.telefono} == {"+390289761851", "+390212345678"}
    # Indirizzi diversi (sito: Solaro; scheda finta: Milano): lista + avviso
    assert isinstance(r.azienda.indirizzo, list) and any("indirizzo" in a for a in r.avvisi)
    md = genera(r)
    assert "llm_scartati" in md and "| Telefono |" in md


def test_cli_offline(tmp_path):
    from onboarding.cli import main

    out = tmp_path / "esempio"
    assert main(["--sito", "https://www.lartenelferro.it", "--mestiere", "fabbro", "--out", str(out),
                 "--fixture", str(FIXTURE / "arte-nel-ferro")]) == 0
    dati = json.loads((out / "dati.json").read_text("utf-8"))
    assert set(dati) >= {"input", "azienda", "pagine_lette", "avvisi", "campi_vuoti"}
    assert set(dati["azienda"]["partita_iva"]) == {"valore", "fonte", "metodo", "confidenza"}
    assert (out / "RAPPORTO.md").read_text("utf-8").startswith("# Onboarding")


def test_robots_rispettato():
    from onboarding.fetch import Risposta, crawl

    class Finto:
        def __init__(self, robots):
            self.robots, self.chieste = robots, []

        def get(self, url):
            self.chieste.append(url)
            if url.endswith("/robots.txt"):
                return self.robots
            return Risposta(url, 200, "<html><body><a href='/contatti/'>c</a></body></html>", "text/html")

    f = Finto(Risposta("https://www.x.it/robots.txt", 200, "User-agent: *\nDisallow: /", "text/plain"))
    avvisi = []
    assert crawl("https://www.x.it", f, "fabbro", avvisi) == [] and f.chieste == ["https://www.x.it/robots.txt"]
    f = Finto(None)
    assert crawl("https://www.x.it", f, "fabbro", avvisi) == [] and f.chieste == ["https://www.x.it/robots.txt"]
    f = Finto(Risposta("https://www.x.it/robots.txt", 200, "User-agent: *\nDisallow: /contatti/", "text/plain"))
    pagine = crawl("https://www.x.it", f, "fabbro", avvisi)
    assert [p.url for p in pagine] == ["https://www.x.it"] and "https://www.x.it/contatti/" not in f.chieste
