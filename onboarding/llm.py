"""Stadio C: LLM (DeepSeek, endpoint OpenAI-compatibile) con verifica letterale.

Documentazione verificata il 2026-09-27 (https://api-docs.deepseek.com/):
- base_url https://api.deepseek.com, POST /chat/completions, header Authorization: Bearer
- il nome "deepseek-chat" indicato nel brief NON compare più fra i modelli correnti:
  il modello documentato è "deepseek-flash" (sovrascrivibile con DEEPSEEK_MODEL)
- "thinking" è attivo di default e in quella modalità temperature è ignorata:
  lo disattiviamo con {"thinking": {"type": "disabled"}} per avere temperatura 0
- JSON Output: response_format {"type": "json_object"}

Regola di grounding (non negoziabile): un candidato è accettato SOLO se il suo
frammento compare letteralmente (dopo normalizzazione di spazi/maiuscole) nel testo
della pagina, e il valore compare nel frammento. Altrimenti è scartato e contato.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Optional

from .candidati import Candidato, compare_in, normalizza_spazi
from .comuni import comune_plausibile
from .extract_text import REGIONI, parse_orari
from .fetch import Pagina

BASE_URL = "https://api.deepseek.com"
MODELLO_DEFAULT = "deepseek-flash"
MAX_CHIAMATE = 8
MAX_TOKEN_USCITA = 1500
MAX_CARATTERI_PAGINA = 12000

PROMPT_SISTEMA = """Sei un estrattore di dati. Leggi il testo di una pagina web di un'impresa italiana
(mestiere: {mestiere}) e restituisci SOLO un oggetto JSON con questa forma:
{{"candidati": [{{"campo": "servizi" | "zone_servite" | "orari", "valore": "...", "frammento": "..."}}]}}
Regole:
- "frammento" deve essere copiato PAROLA PER PAROLA dal testo (massimo 200 caratteri), senza correggere nulla.
- "valore" deve comparire identico dentro "frammento".
- servizi: nomi brevi di lavori/servizi offerti (massimo 6 parole), non slogan.
- zone_servite: solo nomi di comuni o regioni in cui l'impresa dichiara di lavorare.
- orari: il frammento che contiene giorni e ore di apertura; valore = lo stesso testo.
- Se un dato non c'è, non inserirlo. Non dedurre, non completare, non inventare.
- Se non trovi nulla restituisci {{"candidati": []}}."""


def verifica(c: dict, testo_pagina: str) -> Optional[tuple[str, object]]:
    """Applica la regola di grounding. Restituisce (campo, valore) accettato o None."""
    campo = c.get("campo")
    valore = c.get("valore")
    frammento = c.get("frammento")
    if campo not in ("servizi", "zone_servite", "orari") or not isinstance(frammento, str) or not isinstance(valore, str):
        return None
    frammento, valore = normalizza_spazi(frammento), normalizza_spazi(valore)
    if not frammento or not valore or not compare_in(frammento, testo_pagina):
        return None
    if campo == "orari":
        orari, _ = parse_orari(frammento)
        return ("orari", orari) if orari else None
    if not compare_in(valore, frammento):
        return None
    if campo == "servizi":
        return ("servizi", valore) if 1 <= len(valore.split()) <= 6 else None
    nome = comune_plausibile(valore)
    if nome or valore in REGIONI:
        return ("zone_servite", valore)
    return None


def _chiama_deepseek(messaggi: list[dict], chiave: str) -> str:
    import requests

    r = requests.post(
        f"{BASE_URL}/chat/completions", timeout=60,
        headers={"Authorization": f"Bearer {chiave}", "Content-Type": "application/json"},
        json={
            "model": os.environ.get("DEEPSEEK_MODEL", MODELLO_DEFAULT),
            "messages": messaggi,
            "temperature": 0,
            "max_tokens": MAX_TOKEN_USCITA,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "stream": False,
        },
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _pagine_da_leggere(pagine: list[Pagina]) -> list[Pagina]:
    ordine = {"contatti": 0, "servizi": 1, "home": 2, "menu": 3, "altra": 4, "zona": 5}
    return sorted(pagine, key=lambda p: ordine.get(p.tipo, 9))[:MAX_CHIAMATE]


def stadio_c(pagine: list[Pagina], mestiere: str, avvisi: list[str], stat,
             chiamata: Optional[Callable[[list[dict], str], str]] = None) -> list[Candidato]:
    chiave = os.environ.get("DEEPSEEK_API_KEY")
    if not chiave and chiamata is None:
        avvisi.append("stadio C saltato: DEEPSEEK_API_KEY non impostata")
        return []
    chiamata = chiamata or _chiama_deepseek
    out: list[Candidato] = []
    for p in _pagine_da_leggere(pagine):
        if stat.llm_chiamate >= MAX_CHIAMATE:
            break
        testo = p.testo[:MAX_CARATTERI_PAGINA]
        messaggi = [
            {"role": "system", "content": PROMPT_SISTEMA.format(mestiere=mestiere)},
            {"role": "user", "content": f"URL: {p.url}\n\nTESTO DELLA PAGINA:\n{testo}"},
        ]
        stat.llm_chiamate += 1
        try:
            risposta = chiamata(messaggi, chiave or "")
            dati = json.loads(re.sub(r"^```(?:json)?|```$", "", risposta.strip()))
        except Exception as e:
            avvisi.append(f"stadio C: chiamata fallita su {p.url} ({type(e).__name__})")
            continue
        for c in (dati.get("candidati") or []) if isinstance(dati, dict) else []:
            if not isinstance(c, dict):
                continue
            stat.llm_candidati += 1
            ok = verifica(c, testo)
            if ok is None:
                stat.llm_scartati += 1
                continue
            campo, valore = ok
            out.append(Candidato(campo, valore, p.url, normalizza_spazi(c["frammento"]),
                                 "llm_verificato", "media" if campo == "orari" else "bassa", p.tipo))
    return out
