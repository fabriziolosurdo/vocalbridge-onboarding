"""Orchestrazione degli stadi A-D. Usata dalla CLI e dai test."""
from __future__ import annotations

import datetime
from typing import Callable, Optional

from .extract_jsonld import conferma_jsonld, estrai_jsonld
from .extract_text import estrai_tutto, filtra_social
from .fetch import Fetcher, HttpFetcher, crawl, normalizza_sito
from .llm import stadio_c
from .merge import fondi
from .places import stadio_b
from .schema import Input, PaginaLetta, Risultato, Statistiche


def esegui(sito: Optional[str], gbp: Optional[str], mestiere: str,
           fetcher: Optional[Fetcher] = None,
           places_chiamata: Optional[Callable] = None,
           llm_chiamata: Optional[Callable] = None,
           usa_llm: bool = True,
           adesso: Optional[str] = None) -> Risultato:
    if not sito and not gbp:
        raise ValueError("serve almeno uno fra --sito e --gbp")
    avvisi: list[str] = []
    stat = Statistiche()
    cands = []
    pagine = []
    # Stadio A: sito
    if sito:
        pagine = crawl(normalizza_sito(sito), fetcher or HttpFetcher(), mestiere, avvisi)
        for p in pagine:
            cands += estrai_jsonld(p, avvisi)
        cands += estrai_tutto(pagine, mestiere, avvisi, gia=cands)
        if pagine:
            cands = filtra_social(cands, pagine[0].url, avvisi)
        conferma_jsonld(cands, pagine, avvisi)
    # Stadio B: scheda Google
    cands += stadio_b(gbp, avvisi, stat, chiamata=places_chiamata)
    # Stadio C: LLM con verifica letterale
    if usa_llm and pagine:
        cands += stadio_c(pagine, mestiere, avvisi, stat, chiamata=llm_chiamata)
    # Stadio D: fusione
    azienda, vuoti = fondi(cands, avvisi)
    avvisi = list(dict.fromkeys(avvisi))  # senza duplicati, ordine preservato
    return Risultato(
        input=Input(sito=sito, gbp=gbp, mestiere=mestiere,
                    data_estrazione=adesso or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")),
        azienda=azienda,
        pagine_lette=[PaginaLetta(url=p.url, stato=p.stato, titolo=p.titolo, chars=len(p.testo)) for p in pagine],
        avvisi=avvisi,
        campi_vuoti=vuoti,
        statistiche=stat,
    )
