import json
from functools import lru_cache
from pathlib import Path

import pytest

from onboarding.fetch import FixtureFetcher
from onboarding.pipeline import esegui

FIXTURE = Path(__file__).parent / "fixtures"
SLUG = sorted(p.name for p in FIXTURE.iterdir() if (p / "atteso.json").exists())


@pytest.fixture(autouse=True)
def senza_rete_e_senza_chiavi(monkeypatch):
    """Nessuna chiave e nessuna connessione: ogni tentativo di rete fa fallire il test."""
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    import requests
    import socket

    def vietato(*a, **k):
        raise AssertionError("rete usata durante i test")

    monkeypatch.setattr(requests.Session, "request", vietato)
    monkeypatch.setattr(socket, "create_connection", vietato)


@lru_cache(maxsize=None)
def risultato(slug: str):
    manifest = json.loads((FIXTURE / slug / "manifest.json").read_text("utf-8"))
    return esegui(manifest["sito"], None, "fabbro", fetcher=FixtureFetcher(FIXTURE / slug),
                  adesso="2026-09-27T00:00:00+00:00")


def atteso(slug: str) -> dict:
    return json.loads((FIXTURE / slug / "atteso.json").read_text("utf-8"))


@lru_cache(maxsize=None)
def pagine_salvate(slug: str) -> dict[str, str]:
    """url (anche finale dopo redirect) -> html salvato."""
    m = json.loads((FIXTURE / slug / "manifest.json").read_text("utf-8"))
    out = {}
    for url, v in m["risposte"].items():
        if v.get("file"):
            html = (FIXTURE / slug / v["file"]).read_text("utf-8")
            out[url] = html
            out[v.get("url_finale", url)] = html
    return out
