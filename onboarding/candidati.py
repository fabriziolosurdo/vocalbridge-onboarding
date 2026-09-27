"""Strutture comuni agli estrattori: un Candidato è un valore con la sua prova."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

from .schema import Campo, Fonte


@dataclass
class Candidato:
    campo: str  # nome del campo dello schema
    valore: Any
    url: str
    frammento: str
    metodo: str
    confidenza: str
    tipo_pagina: str = "altra"
    extra: dict = field(default_factory=dict)

    def a_campo(self) -> Campo:
        return Campo(valore=self.valore, fonte=Fonte(url=self.url, frammento=self.frammento),
                     metodo=self.metodo, confidenza=self.confidenza)


def normalizza_spazi(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace(" ", " ")).strip()


def normalizza_confronto(s: str) -> str:
    """Normalizzazione per la regola di grounding: spazi, maiuscole, apostrofi, trattini."""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-")
    return normalizza_spazi(s).lower()


def compare_in(frammento: str, testo: str) -> bool:
    return normalizza_confronto(frammento) in normalizza_confronto(testo)


def taglia(testo: str, inizio: int, fine: int, margine: int = 40) -> str:
    """Estrae un frammento letterale con un po' di contesto, senza spezzare parole."""
    a = max(0, inizio - margine)
    b = min(len(testo), fine + margine)
    while a > 0 and not testo[a - 1].isspace() and a > inizio - margine - 15:
        a -= 1
    while b < len(testo) and not testo[b].isspace() and b < fine + margine + 15:
        b += 1
    return normalizza_spazi(testo[a:b])


def valore_confronto(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, dict):
        return "|".join(f"{k}={normalizza_confronto(str(x))}" for k, x in sorted(v.items()) if x)
    return normalizza_confronto(str(v))
