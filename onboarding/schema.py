"""Schema di uscita (punto 3 del brief).

Ogni campo ha sempre le quattro chiavi: valore, fonte, metodo, confidenza.
Un campo assente ha valore null (e compare in ``campi_vuoti``).
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

Metodo = Literal["jsonld", "regex", "heuristica", "llm_verificato", "google_places"]
Confidenza = Literal["alta", "media", "bassa"]

# Precedenza dello stadio D: indice più basso = fonte più affidabile.
PRECEDENZA: list[str] = ["jsonld", "google_places", "regex", "heuristica", "llm_verificato"]


class Fonte(BaseModel):
    url: str
    frammento: str


class Campo(BaseModel):
    valore: Any = None
    fonte: Optional[Fonte] = None
    metodo: Optional[Metodo] = None
    confidenza: Optional[Confidenza] = None

    @model_validator(mode="after")
    def _coerenza(self) -> "Campo":
        if self.valore is not None:
            if self.fonte is None or self.metodo is None or self.confidenza is None:
                raise ValueError("un valore non nullo richiede fonte, metodo e confidenza")
            if self.metodo == "llm_verificato" and self.confidenza == "alta":
                raise ValueError("un valore llm_verificato non può avere confidenza alta")
        return self

    @classmethod
    def vuoto(cls) -> "Campo":
        return cls()


# Un campo "singolo" diventa una lista quando due fonti si contraddicono.
CampoSingolo = Union[Campo, list[Campo]]


class Input(BaseModel):
    sito: Optional[str] = None
    gbp: Optional[str] = None
    mestiere: str
    data_estrazione: str


class Azienda(BaseModel):
    ragione_sociale: CampoSingolo = Field(default_factory=Campo.vuoto)
    partita_iva: CampoSingolo = Field(default_factory=Campo.vuoto)
    telefono: list[Campo] = Field(default_factory=list)
    email: list[Campo] = Field(default_factory=list)
    indirizzo: CampoSingolo = Field(default_factory=Campo.vuoto)
    zone_servite: list[Campo] = Field(default_factory=list)
    orari: CampoSingolo = Field(default_factory=Campo.vuoto)
    urgenza_h24: CampoSingolo = Field(default_factory=Campo.vuoto)
    servizi: list[Campo] = Field(default_factory=list)
    social: list[Campo] = Field(default_factory=list)


CAMPI_SINGOLI = ["ragione_sociale", "partita_iva", "indirizzo", "orari", "urgenza_h24"]
CAMPI_LISTA = ["telefono", "email", "zone_servite", "servizi", "social"]
CAMPI = ["ragione_sociale", "partita_iva", "telefono", "email", "indirizzo",
         "zone_servite", "orari", "urgenza_h24", "servizi", "social"]


class PaginaLetta(BaseModel):
    url: str
    stato: int
    titolo: str = ""
    chars: int = 0


class Statistiche(BaseModel):
    places_chiamate: int = 0
    llm_chiamate: int = 0
    llm_candidati: int = 0
    llm_scartati: int = 0


class Risultato(BaseModel):
    input: Input
    azienda: Azienda
    pagine_lette: list[PaginaLetta] = Field(default_factory=list)
    avvisi: list[str] = Field(default_factory=list)
    campi_vuoti: list[str] = Field(default_factory=list)
    statistiche: Statistiche = Field(default_factory=Statistiche)
