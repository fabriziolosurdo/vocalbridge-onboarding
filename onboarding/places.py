"""Stadio B: scheda Google via Places API (New), una sola chiamata places.get.

Documentazione verificata il 2026-09-27:
https://developers.google.com/maps/documentation/places/web-service/place-details
- GET https://places.googleapis.com/v1/places/{PLACE_ID}
- header X-Goog-Api-Key (chiave) e X-Goog-FieldMask (campi separati da virgola)
- regularOpeningHours.periods[].open/close = {day (0=domenica), hour, minute}
Niente recensioni, niente foto, nessun'altra chiamata Places.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Optional
from urllib.parse import unquote

from .candidati import Candidato
from .extract_text import GIORNI, e164

ENDPOINT = "https://places.googleapis.com/v1/places/{}"
FIELD_MASK = ",".join([
    "displayName", "formattedAddress", "addressComponents", "nationalPhoneNumber",
    "internationalPhoneNumber", "websiteUri", "regularOpeningHours", "businessStatus", "types",
])
MAX_CHIAMATE = 1
PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{16,}$")


def ricava_place_id(gbp: str) -> Optional[str]:
    """Da place_id o da link Google Maps che contiene esplicitamente il place_id."""
    g = unquote(gbp.strip())
    if not g.startswith("http") and PLACE_ID_RE.match(g):
        return g
    for pat in (r"place_id[:=]([A-Za-z0-9_\-]{16,})", r"query_place_id=([A-Za-z0-9_\-]{16,})",
                r"!1s(ChIJ[A-Za-z0-9_\-]{10,})", r"(ChIJ[A-Za-z0-9_\-]{10,})"):
        m = re.search(pat, g)
        if m:
            return m.group(1)
    return None


def url_scheda(place_id: str) -> str:
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"


def _frammento(dati: dict, chiave: str) -> str:
    return json.dumps({chiave: dati[chiave]}, ensure_ascii=False)[:500]


def candidati_da_places(dati: dict, place_id: str, avvisi: list[str]) -> list[Candidato]:
    url = url_scheda(place_id)
    out: list[Candidato] = []

    def add(campo, valore, chiave, conf="alta"):
        out.append(Candidato(campo, valore, url, _frammento(dati, chiave), "google_places", conf, "scheda_google"))

    nome = (dati.get("displayName") or {}).get("text")
    if nome:
        add("ragione_sociale", nome, "displayName", "media")  # nome della scheda, non per forza quello legale
    for k in ("internationalPhoneNumber", "nationalPhoneNumber"):
        if dati.get(k) and e164(dati[k]):
            add("telefono", e164(dati[k]), k)
            break
    comp = {t: c for c in dati.get("addressComponents", []) for t in c.get("types", [])}
    if comp:
        via = None
        if "route" in comp:
            via = comp["route"].get("longText")
            if "street_number" in comp:
                via = f"{via}, {comp['street_number'].get('longText')}"
        val = {
            "via": via,
            "cap": (comp.get("postal_code") or {}).get("longText"),
            "comune": (comp.get("locality") or comp.get("administrative_area_level_3") or {}).get("longText"),
            "provincia": (comp.get("administrative_area_level_2") or {}).get("shortText"),
        }
        if any(val.values()):
            add("indirizzo", val, "addressComponents")
    periodi = (dati.get("regularOpeningHours") or {}).get("periods") or []
    orari: dict[str, list[str]] = {}
    for p in periodi:
        a, c = p.get("open"), p.get("close")
        if not a:
            continue
        g = GIORNI[(a["day"] + 6) % 7]  # Google: 0 = domenica
        if c is None:  # aperto sempre (unico periodo senza chiusura)
            for x in GIORNI:
                orari.setdefault(x, []).append("00:00-24:00")
            continue
        orari.setdefault(g, []).append(f"{a.get('hour', 0):02d}:{a.get('minute', 0):02d}-{c.get('hour', 0):02d}:{c.get('minute', 0):02d}")
    if orari:
        add("orari", {k: ", ".join(v) for k, v in sorted(orari.items(), key=lambda kv: GIORNI.index(kv[0]))},
            "regularOpeningHours")
    stato = dati.get("businessStatus")
    if stato and stato != "OPERATIONAL":
        avvisi.append(f"scheda Google: stato attività {stato}")
    return out


def stadio_b(gbp: Optional[str], avvisi: list[str], stat, chiamata: Optional[Callable] = None) -> list[Candidato]:
    if not gbp:
        return []
    chiave = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not chiave and chiamata is None:
        avvisi.append("stadio B saltato: GOOGLE_PLACES_API_KEY non impostata")
        return []
    place_id = ricava_place_id(gbp)
    if not place_id:
        avvisi.append("stadio B saltato: dal riferimento alla scheda Google non si ricava un place_id (serve il place_id o un link che lo contenga)")
        return []
    if stat.places_chiamate >= MAX_CHIAMATE:
        return []
    stat.places_chiamate += 1
    try:
        dati = (chiamata or _chiama)(place_id, chiave)
    except Exception as e:  # rete, 4xx/5xx: lo stadio si ferma, il resto continua
        avvisi.append(f"stadio B: chiamata Places fallita ({type(e).__name__}: {str(e)[:120]})")
        return []
    return candidati_da_places(dati, place_id, avvisi)


def _chiama(place_id: str, chiave: str) -> dict:
    import requests

    r = requests.get(ENDPOINT.format(place_id), timeout=15, params={"languageCode": "it", "regionCode": "IT"},
                     headers={"X-Goog-Api-Key": chiave, "X-Goog-FieldMask": FIELD_MASK})
    r.raise_for_status()
    return r.json()
