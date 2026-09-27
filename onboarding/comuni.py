"""Elenco ufficiale dei comuni italiani (ISTAT), usato solo per VALIDARE nomi
trovati nel testo: un nome che non è un comune non diventa mai un comune."""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional

_FILE = Path(__file__).parent / "data" / "comuni_istat.json"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("’", "'")
    return re.sub(r"[^a-z0-9']+", " ", s).strip()


@lru_cache(maxsize=1)
def _dati() -> tuple[dict, dict, set]:
    raw = json.loads(_FILE.read_text("utf-8"))["comuni"]
    per_nome = {_norm(k): (k, v) for k, v in raw.items()}
    sigle = {v["sigla"] for v in raw.values()}
    # Nomi delle province / città metropolitane (es. "Milano", "Monza e della Brianza").
    province = {_norm(v["provincia"]): v["sigla"] for v in raw.values()}
    return per_nome, province, sigle


def cerca_comune(nome: str) -> Optional[tuple[str, dict]]:
    """Restituisce (nome ufficiale, {sigla, provincia, capoluogo}) o None."""
    return _dati()[0].get(_norm(nome))


def e_sigla(s: str) -> bool:
    return s in _dati()[2]


def sigla_di_provincia(nome: str) -> Optional[str]:
    return _dati()[1].get(_norm(nome))


# Parole comuni che sono anche nomi di comuni: mai accettate da sole come zona.
FALSI_COMUNI = {
    "porte", "cancello", "ferro", "vetrine", "scale", "tetti", "serravalle", "centro", "villa",
    "piano", "pace", "valle", "monte", "porto", "ponte", "castello", "chiesa", "cassano",
    "pieve", "rocca", "torre", "casa", "sala", "orta", "lu", "re", "bosco", "fontana", "ne",
    "ro", "pietra", "grate", "cassa", "tre", "mercato", "arena", "urbe", "zone",
    "nave", "bella", "zona", "sale", "vale", "lago", "isola", "lavoro", "campo", "fiume",
}


def comune_plausibile(nome: str) -> Optional[str]:
    if _norm(nome) in FALSI_COMUNI or len(nome) < 3:
        return None
    c = cerca_comune(nome)
    return c[0] if c else None
