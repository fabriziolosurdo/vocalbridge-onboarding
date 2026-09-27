"""Stadio D: fusione dei candidati nello schema di uscita.

Precedenza a parità di campo: jsonld > google_places > regex > heuristica > llm_verificato.
Valori diversi fra fonti: si riportano tutti (lista) e si aggiunge un avviso.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Callable, Optional
from urllib.parse import urlparse

from .candidati import Candidato, normalizza_confronto, valore_confronto
from .comuni import cerca_comune
from .schema import CAMPI, CAMPI_LISTA, PRECEDENZA, Azienda, Campo

CONF = {"alta": 0, "media": 1, "bassa": 2}
MAX_VOCI = {"servizi": 30, "zone_servite": 60, "social": 15, "email": 10, "telefono": 10}


def _prec(c: Candidato) -> int:
    return PRECEDENZA.index(c.metodo)


def _chiave_lista(c: Candidato) -> str:
    if c.campo == "social":
        u = urlparse(c.valore)
        return u.netloc.lower().removeprefix("www.").removeprefix("m.") + u.path.rstrip("/").lower()
    if c.campo == "zone_servite":
        info = cerca_comune(c.valore)
        return normalizza_confronto(info[0] if info else c.valore)
    return valore_confronto(c.valore) or ""


def _orari_confronto(v: dict) -> str:
    def n(x: str) -> str:
        return x.replace("23:59", "24:00").replace("00:01-", "00:00-")
    return "|".join(f"{k}={n(v[k])}" for k in sorted(v))


def _breve(v) -> str:
    if isinstance(v, dict):
        return ", ".join(f"{x}" for x in v.values() if x) if "via" in v or "comune" in v else \
            "; ".join(f"{k} {x}" for k, x in v.items())
    return str(v)


ABBREVIAZIONI = [(r"\bc\.\s?so\b", "corso"), (r"\bv\.\s?le\b", "viale"), (r"\bp\.\s?z?za\b", "piazza"),
                 (r"\bp\.\s?le\b", "piazzale"), (r"\bl\.\s?go\b", "largo"), (r"\bs\.\s?", "san ")]


def norm_via(t: str) -> str:
    """Normalizza una via solo per CONFRONTARLA (il valore riportato resta quello letterale)."""
    t = normalizza_confronto(t)
    for a, b in ABBREVIAZIONI:
        t = re.sub(a, b, t)
    return re.sub(r"\s+", " ", re.sub(r"[^\w/]+", " ", t)).strip()


_FORMA_LEGALE = re.compile(r"\b(s\.?\s?r\.?\s?l\.?\s?s?\.?|s\.?\s?n\.?\s?c\.?|s\.?\s?a\.?\s?s\.?|s\.?\s?p\.?\s?a\.?)\s*$", re.I)


def _nome_base(t: str) -> str:
    return re.sub(r"[^\w]+", " ", _FORMA_LEGALE.sub("", normalizza_confronto(t))).strip()


def _rappresentante(gruppo: list[Candidato], campo: str) -> Candidato:
    if campo == "telefono":
        # Punto 5: fonte = prima occorrenza in una pagina contatti, se esiste.
        # A parità di pagina, meglio il testo visibile ("02 897 618 51") del link tel:.
        chiave = lambda c: (c.tipo_pagina != "contatti", c.metodo == "jsonld", bool(c.extra.get("tel_link")),
                            CONF[c.confidenza])
    else:
        chiave = lambda c: (_prec(c), CONF[c.confidenza], c.tipo_pagina != "contatti")
    rep = min(gruppo, key=chiave)
    metodi = {c.metodo for c in gruppo}
    conf = min((c.confidenza for c in gruppo), key=CONF.get)
    # Il JSON-LD ripetuto su più pagine è lo stesso blocco del tema: non è una conferma indipendente.
    if (len(metodi) >= 2 or (len({c.url for c in gruppo}) >= 2 and metodi != {"jsonld"})) and metodi != {"llm_verificato"}:
        conf = "alta"  # confermato da due metodi o da due pagine diverse
    if rep.metodo == "llm_verificato" and conf == "alta":
        conf = "media"
    return Candidato(rep.campo, rep.valore, rep.url, rep.frammento, rep.metodo, conf, rep.tipo_pagina, rep.extra)


def _fondi_lista(campo: str, cands: list[Candidato], avvisi: list[str]) -> list[Campo]:
    gruppi: dict[str, list[Candidato]] = {}
    for c in cands:
        gruppi.setdefault(_chiave_lista(c), []).append(c)
    reps = []
    for k, g in gruppi.items():
        rep = _rappresentante(g, campo)
        pagine = {c.url for c in g}
        punteggio = len(pagine) + 3 * any(c.extra.get("tel_link") for c in g) + 2 * any(c.metodo in ("jsonld", "google_places") for c in g)
        reps.append((-punteggio if campo == "telefono" else _prec(rep), -len(pagine), rep))
    reps.sort(key=lambda x: (x[0], x[1]))
    limite = MAX_VOCI.get(campo, 50)
    if len(reps) > limite:
        avvisi.append(f"{campo}: trovate {len(reps)} voci, riportate le prime {limite}")
    return [r[2].a_campo() for r in reps[:limite]]


def _compatibili(a: dict, b: dict) -> bool:
    va, vb = norm_via(a.get("via") or ""), norm_via(b.get("via") or "")
    if va and vb and va == vb and a.get("cap") and a.get("cap") == b.get("cap"):
        return True
    for k in ("via", "cap", "comune"):
        x, y = a.get(k), b.get(k)
        if x and y:
            if k == "comune":
                cx, cy = cerca_comune(x), cerca_comune(y)
                x, y = (cx[0] if cx else x), (cy[0] if cy else y)
            if (norm_via(x) if k == "via" else normalizza_confronto(x)) != (norm_via(y) if k == "via" else normalizza_confronto(y)):
                return False
    return True


def _fondi_singolo(campo: str, cands: list[Candidato], avvisi: list[str]) -> Campo | list[Campo]:
    if not cands:
        return Campo.vuoto()
    gruppi: list[list[Candidato]] = []
    if campo == "indirizzo":
        for c in sorted(cands, key=lambda c: (_prec(c), -sum(1 for v in c.valore.values() if v))):
            for g in gruppi:
                if all(_compatibili(c.valore, x.valore) for x in g):
                    g.append(c)
                    break
            else:
                gruppi.append([c])
        reps = []
        for g in gruppi:
            completo = max(g, key=lambda c: (sum(1 for v in c.valore.values() if v), -_prec(c)))
            rep = _rappresentante(g, campo)
            rep = Candidato(completo.campo, completo.valore, completo.url, completo.frammento, completo.metodo,
                            rep.confidenza if completo.metodo != "llm_verificato" else "media", completo.tipo_pagina)
            reps.append(rep)
    elif campo == "ragione_sociale":
        # "L'arte nel ferro" e "L'arte nel ferro Srls" sono lo stesso nome: si tiene quello con la forma legale.
        for c in sorted(cands, key=lambda c: (_prec(c), CONF[c.confidenza])):
            for g in gruppi:
                a, b = _nome_base(c.valore), _nome_base(g[0].valore)
                if a == b or a.startswith(b + " ") or b.startswith(a + " "):
                    g.append(c)
                    break
            else:
                gruppi.append([c])
        reps = []
        for g in gruppi:
            con_forma = [c for c in g if _FORMA_LEGALE.search(c.valore)]
            scelto = min(con_forma or g, key=lambda c: (len(c.valore) if not con_forma else 0, _prec(c)))
            conf = _rappresentante(g, campo).confidenza
            reps.append(Candidato(scelto.campo, scelto.valore, scelto.url, scelto.frammento, scelto.metodo,
                                  conf if scelto.metodo != "llm_verificato" else "bassa", scelto.tipo_pagina))
    else:
        per_val: dict[str, list[Candidato]] = {}
        for c in cands:
            k = _orari_confronto(c.valore) if campo == "orari" else (valore_confronto(c.valore) or "")
            per_val.setdefault(k, []).append(c)
        reps = [_rappresentante(g, campo) for g in per_val.values()]
    # Fra versioni in conflitto: prima la più confermata, poi la precedenza delle fonti.
    reps.sort(key=lambda c: (CONF[c.confidenza], _prec(c)))
    if len(reps) == 1:
        return reps[0].a_campo()
    elenco = "; ".join(f"\"{_breve(r.valore)}\" ({r.url})" for r in reps[:6])
    avvisi.append(f"{campo} trovato in {len(reps)} versioni diverse: {elenco}")
    return [r.a_campo() for r in reps]


def fondi(cands: list[Candidato], avvisi: list[str]) -> tuple[Azienda, list[str]]:
    per_campo: dict[str, list[Candidato]] = defaultdict(list)
    for c in cands:
        per_campo[c.campo].append(c)
    dati = {}
    for campo in CAMPI:
        if campo in CAMPI_LISTA:
            dati[campo] = _fondi_lista(campo, per_campo[campo], avvisi)
        else:
            dati[campo] = _fondi_singolo(campo, per_campo[campo], avvisi)
    azienda = Azienda(**dati)
    vuoti = [c for c in CAMPI if _vuoto(getattr(azienda, c))]
    return azienda, vuoti


def _vuoto(v) -> bool:
    if isinstance(v, list):
        return len(v) == 0
    return v.valore is None
