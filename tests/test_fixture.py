"""Criteri passa/fallisce del brief (punto 7) sui 5 siti reali salvati come fixture.

1. telefono principale trovato in 5/5 con fonte corretta
2. indirizzo (almeno comune + provincia) in almeno 4/5
3. almeno 3 servizi corretti in almeno 4/5, e zero servizi che non compaiono nella pagina
4. urgenza sì/no corretta in 5/5
5. fonte mai nulla quando il valore non è nullo (e frammento sempre letterale nella pagina)
"""
import re
from functools import lru_cache
from urllib.parse import unquote

import pytest

from onboarding.candidati import compare_in, normalizza_confronto
from onboarding.comuni import cerca_comune, sigla_di_provincia
from onboarding.fetch import crea_pagina
from onboarding.schema import CAMPI

from .conftest import SLUG, atteso, pagine_salvate, risultato


@lru_cache(maxsize=None)
def _testo(slug, url):
    return crea_pagina(url, 200, pagine_salvate(slug)[url]).testo


def test_ci_sono_cinque_fixture():
    assert len(SLUG) == 5


def _voci(v):
    return v if isinstance(v, list) else [v]


def _tutti_i_campi(r):
    for campo in CAMPI:
        for c in _voci(getattr(r.azienda, campo)):
            yield campo, c


# --- criterio 1 -------------------------------------------------------------

def _telefono_ok(slug):
    r, a = risultato(slug), atteso(slug)["telefono_principale"]
    if not r.azienda.telefono:
        return False
    t = r.azienda.telefono[0]
    cifre_fr = re.sub(r"\D", "", unquote(t.fonte.frammento))
    return t.valore == a["valore"] and t.fonte.url in a["pagine"] and a["valore"][3:] in cifre_fr


@pytest.mark.parametrize("slug", SLUG)
def test_telefono_principale(slug):
    assert _telefono_ok(slug), [(t.valore, t.fonte.url, t.fonte.frammento) for t in risultato(slug).azienda.telefono]


# --- criterio 2 -------------------------------------------------------------

def _sigla(p):
    if not p:
        return None
    return p.upper() if len(p) == 2 else sigla_di_provincia(p)


def _indirizzo_ok(slug):
    r, a = risultato(slug), atteso(slug)["indirizzo"]
    primo = _voci(r.azienda.indirizzo)[0].valore
    if not primo:
        return False
    com = cerca_comune(primo["comune"] or "")
    return bool(com) and com[0] == a["comune"] and _sigla(primo["provincia"]) == a["provincia"]


def test_indirizzo_almeno_4_su_5():
    esiti = {s: _indirizzo_ok(s) for s in SLUG}
    assert sum(esiti.values()) >= 4, esiti


# --- criterio 3 -------------------------------------------------------------

def _servizio_corretto(v, attesi):
    n = normalizza_confronto(v)
    return any(n in normalizza_confronto(x) or normalizza_confronto(x) in n for x in attesi)


def test_servizi_almeno_3_corretti_in_4_su_5():
    esiti = {}
    for s in SLUG:
        attesi = atteso(s)["servizi"]
        esiti[s] = sum(_servizio_corretto(c.valore, attesi) for c in risultato(s).azienda.servizi)
    assert sum(n >= 3 for n in esiti.values()) >= 4, esiti


@pytest.mark.parametrize("slug", SLUG)
def test_zero_servizi_non_presenti_nella_pagina(slug):
    pagine = pagine_salvate(slug)
    for c in risultato(slug).azienda.servizi:
        testo = _testo(slug, c.fonte.url)
        assert compare_in(c.valore, testo), (c.valore, c.fonte.url)


# --- criterio 4 -------------------------------------------------------------

@pytest.mark.parametrize("slug", SLUG)
def test_urgenza(slug):
    u = _voci(risultato(slug).azienda.urgenza_h24)[0].valore
    assert u == atteso(slug)["urgenza_h24"]


# --- criterio 5 (+ grounding su tutto l'output) -----------------------------

@pytest.mark.parametrize("slug", SLUG)
def test_fonte_mai_nulla_se_valore_presente(slug):
    for campo, c in _tutti_i_campi(risultato(slug)):
        if c.valore is not None:
            assert c.fonte is not None and c.fonte.url and c.fonte.frammento, campo
            assert c.metodo and c.confidenza, campo


@pytest.mark.parametrize("slug", SLUG)
def test_frammento_letterale_nella_pagina_e_valore_nel_frammento(slug):
    pagine = pagine_salvate(slug)
    for campo, c in _tutti_i_campi(risultato(slug)):
        if c.valore is None:
            continue
        html = pagine[c.fonte.url]
        testo = _testo(slug, c.fonte.url)
        fr = c.fonte.frammento
        assert compare_in(fr, testo) or compare_in(fr, html), (campo, fr)
        n_fr = normalizza_confronto(fr)
        if campo == "telefono":
            assert c.valore[3:] in re.sub(r"\D", "", unquote(fr)), (c.valore, fr)
        elif campo == "indirizzo":
            for k, x in c.valore.items():
                if x:
                    assert normalizza_confronto(x) in n_fr, (k, x, fr)
        elif campo in ("orari",):
            pass  # valore strutturato: la corrispondenza giorni/ore è verificata nei test unitari
        elif isinstance(c.valore, str) and campo != "social":
            assert normalizza_confronto(c.valore) in n_fr, (campo, c.valore, fr)


@pytest.mark.parametrize("slug", SLUG)
def test_campi_vuoti_coerenti(slug):
    r = risultato(slug)
    for campo in CAMPI:
        v = getattr(r.azienda, campo)
        vuoto = (len(v) == 0) if isinstance(v, list) else v.valore is None
        assert (campo in r.campi_vuoti) == vuoto, campo


@pytest.mark.parametrize("slug", SLUG)
def test_nessun_segnaposto_del_tema(slug):
    """I dati di esempio dei temi non devono mai diventare dati del cliente."""
    s = risultato(slug).model_dump_json()
    for vietato in ("Anytown", "Mainstreet", "[Inserisci", "[numero"):
        assert vietato not in s
