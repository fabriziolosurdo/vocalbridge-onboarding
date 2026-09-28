"""Stadio A, parte 1: dati strutturati schema.org (JSON-LD). Fonte a confidenza più alta.

Il frammento riportato è sempre un pezzo letterale del blocco <script> JSON-LD.
Se un valore JSON-LD non trova riscontro nel testo visibile del sito, la confidenza
scende a "media" (capita che i temi lascino dati di esempio nel JSON-LD).
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional

from .candidati import Candidato, normalizza_spazi
from .comuni import cerca_comune, e_sigla, sigla_di_provincia
from .extract_text import EMAIL_RE, GIORNI, SOCIAL_DOMINI, e164
from .fetch import Pagina, dominio

TIPI_AZIENDA = re.compile(
    r"(LocalBusiness|Organization|Corporation|Locksmith|Plumber|Electrician|HomeAndConstructionBusiness|"
    r"GeneralContractor|RoofingContractor|HVACBusiness|Store|ProfessionalService|AutomotiveBusiness|"
    r"HousePainter|MovingCompany|Dentist|MedicalBusiness|LegalService|Attorney|AccountingService|"
    r"FinancialService|RealEstateAgent|TravelAgency|EmploymentAgency|Place)$"
)
GIORNI_EN = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
             "mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6}


def _blocchi(p: Pagina) -> list[tuple[str, Any]]:
    out = []
    for sc in p.soup.find_all("script", type=re.compile(r"ld\+json", re.I)):
        raw = sc.string or sc.get_text() or ""
        try:
            dati = json.loads(raw)
        except json.JSONDecodeError:
            try:
                dati = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))  # virgole finali, errore frequente
            except json.JSONDecodeError:
                continue
        out.append((raw, dati))
    return out


def _nodi(dati: Any) -> Iterable[dict]:
    if isinstance(dati, list):
        for x in dati:
            yield from _nodi(x)
    elif isinstance(dati, dict):
        yield dati
        for k, v in dati.items():
            if k in ("@graph", "location", "publisher", "provider", "author", "mainEntity", "about", "brand"):
                yield from _nodi(v)


def _tipi(n: dict) -> list[str]:
    t = n.get("@type", [])
    return [t] if isinstance(t, str) else [x for x in t if isinstance(x, str)]


def _frammento(raw: str, chiave: str, valore: str) -> Optional[str]:
    """Pezzo letterale del JSON grezzo che contiene chiave e valore."""
    varianti = {valore, json.dumps(valore)[1:-1], json.dumps(valore, ensure_ascii=False)[1:-1],
                json.dumps(valore)[1:-1].replace("/", "\\/")}
    for v in varianti:
        m = re.search(rf'"{re.escape(chiave)}"\s*:\s*\[?\s*"{re.escape(v)}"', raw)
        if m:
            return normalizza_spazi(m.group(0))
    for v in varianti:
        i = raw.find(v)
        if i >= 0:
            return normalizza_spazi(raw[max(0, i - 30):i + len(v) + 1])
    return None


def _finestra(raw: str, valori: list[str], ancora: str) -> Optional[str]:
    """Pezzo letterale che contiene tutti i valori (es. i campi di un PostalAddress)."""
    for m in re.finditer(re.escape(ancora), raw):
        pezzo = raw[m.start():m.start() + 600]
        pos = []
        for v in valori:
            for var in (v, json.dumps(v)[1:-1], json.dumps(v, ensure_ascii=False)[1:-1]):
                i = pezzo.find(var)
                if i >= 0:
                    pos.append(i + len(var))
                    break
            else:
                break
        else:
            return normalizza_spazi(pezzo[:max(pos) + 1])
    return None


def _testo(v: Any) -> Optional[str]:
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, dict):
        return _testo(v.get("name"))
    return None


def _lista(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _orari_spec(specs: list[dict]) -> dict:
    out: dict[str, list[str]] = {}
    for s in specs:
        if not isinstance(s, dict):
            continue
        giorni = []
        for d in _lista(s.get("dayOfWeek")):
            d = str(d).rsplit("/", 1)[-1].lower()
            if d in GIORNI_EN:
                giorni.append(GIORNI_EN[d])
        a, c = s.get("opens"), s.get("closes")
        if not giorni or not a or not c:
            continue
        a, c = str(a)[:5], str(c)[:5]
        if not re.fullmatch(r"\d{2}:\d{2}", a) or not re.fullmatch(r"\d{2}:\d{2}", c):
            continue
        for g in giorni:
            out.setdefault(GIORNI[g], []).append(f"{a}-{c}")
    return {k: ", ".join(v) for k, v in out.items()}


def _orari_stringa(righe: list[str]) -> dict:
    """Formato schema.org openingHours: "Mo-Fr 08:00-18:00" o "Monday,Tuesday 00:00-24:00"."""
    out: dict[str, list[str]] = {}
    for r in righe:
        m = re.match(r"\s*([A-Za-z,\- ]+?)\s+(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})\s*$", str(r))
        if not m:
            continue
        giorni: list[int] = []
        for parte in m.group(1).split(","):
            parte = parte.strip().lower()
            if "-" in parte:
                x, y = [t.strip() for t in parte.split("-", 1)]
                if x in GIORNI_EN and y in GIORNI_EN and GIORNI_EN[y] >= GIORNI_EN[x]:
                    giorni += list(range(GIORNI_EN[x], GIORNI_EN[y] + 1))
            elif parte in GIORNI_EN:
                giorni.append(GIORNI_EN[parte])
        for g in giorni:
            out.setdefault(GIORNI[g], []).append(f"{m.group(2)}-{m.group(3)}")
    return {k: ", ".join(v) for k, v in out.items()}


def estrai_jsonld(p: Pagina, avvisi: list[str]) -> list[Candidato]:
    out: list[Candidato] = []

    def add(campo, valore, raw, chiave, testo_val=None, conf="alta"):
        fr = _frammento(raw, chiave, testo_val if testo_val is not None else str(valore))
        if fr:
            out.append(Candidato(campo, valore, p.url, fr, "jsonld", conf, p.tipo))

    for raw, dati in _blocchi(p):
        for n in _nodi(dati):
            tipi = _tipi(n)
            if not any(TIPI_AZIENDA.search(t) for t in tipi):
                continue
            nome_legale = _testo(n.get("legalName"))
            nome = nome_legale or (_testo(n.get("name")) if "Place" not in tipi else None)
            if nome:
                add("ragione_sociale", nome, raw, "legalName" if nome_legale else "name")
            vat = _testo(n.get("vatID")) or _testo(n.get("taxID"))
            if vat:
                cifre = re.sub(r"\D", "", vat)
                if len(cifre) == 11:
                    add("partita_iva", cifre, raw, "vatID" if n.get("vatID") else "taxID", vat)
            tels = [_testo(t) for t in _lista(n.get("telephone"))]
            for cp in _lista(n.get("contactPoint")):
                if isinstance(cp, dict):
                    tels += [_testo(t) for t in _lista(cp.get("telephone"))]
            for t in tels:
                if t and e164(t):
                    add("telefono", e164(t), raw, "telephone", t)
            emails = [_testo(e) for e in _lista(n.get("email"))]
            for cp in _lista(n.get("contactPoint")):
                if isinstance(cp, dict):
                    emails += [_testo(e) for e in _lista(cp.get("email"))]
            for e in emails:
                if e:
                    e2 = e.removeprefix("mailto:")
                    if EMAIL_RE.fullmatch(e2):
                        add("email", e2.lower(), raw, "email", e)
            for a in _lista(n.get("address")):
                if not isinstance(a, dict):
                    continue
                via, cap = _testo(a.get("streetAddress")), _testo(a.get("postalCode"))
                comune, regione = _testo(a.get("addressLocality")), _testo(a.get("addressRegion"))
                if not comune and not via:
                    continue
                if cap and not re.fullmatch(r"\d{5}", cap):
                    avvisi.append(f"CAP \"{cap}\" nel JSON-LD di {p.url} non valido: ignorato")
                    cap = None
                prov = None
                if regione and (e_sigla(regione) or sigla_di_provincia(regione)):
                    prov = regione
                elif comune and (c := cerca_comune(comune)) and c[1]["capoluogo"]:
                    prov = comune
                val = {"via": via, "cap": cap, "comune": comune, "provincia": prov}
                valori = [x for x in (via, cap, comune, prov) if x]
                fr = _finestra(raw, valori, '"address"') or _finestra(raw, valori, "PostalAddress")
                if fr:
                    out.append(Candidato("indirizzo", val, p.url, fr, "jsonld", "alta", p.tipo))
            i_area = raw.find('"areaServed"')
            for area in _lista(n.get("areaServed")):
                nome_area = _testo(area)
                if nome_area and not re.fullmatch(r"[A-Z]{2}", nome_area) and i_area >= 0:
                    fr = _frammento(raw[i_area:], "name", nome_area) or _frammento(raw[i_area:], "areaServed", nome_area)
                    if fr:
                        out.append(Candidato("zone_servite", nome_area, p.url, fr, "jsonld", "alta", p.tipo))
            orari = _orari_spec(_lista(n.get("openingHoursSpecification")))
            chiave_or = "openingHoursSpecification"
            if not orari:
                orari = _orari_stringa([str(x) for x in _lista(n.get("openingHours"))])
                chiave_or = "openingHours"
            if orari:
                m = re.search(rf'"{chiave_or}"\s*:\s*(\[[^\]]*\]|\{{[^}}]*\}}|"[^"]*")', raw, re.S)
                if m:
                    out.append(Candidato("orari", orari, p.url, normalizza_spazi(m.group(0)), "jsonld", "alta", p.tipo))
            for s in _lista(n.get("sameAs")):
                if isinstance(s, str) and s.startswith("http") and any(
                        dominio(s) == d or dominio(s).endswith("." + d) for d in SOCIAL_DOMINI):
                    add("social", s.rstrip("/"), raw, "sameAs", s)
    return out


def _norm_testo_confronto(t: str) -> str:
    from .merge import norm_via
    return norm_via(t)


def conferma_jsonld(cands: list[Candidato], pagine: list[Pagina], avvisi: list[str]) -> None:
    """Un dato che compare SOLO nel JSON-LD (non nel testo visibile) scende a confidenza media."""
    testo = "\n".join(p.testo for p in pagine)
    cifre = re.sub(r"\D", "", testo)
    testo_min = testo.lower()
    testo_via = _norm_testo_confronto(testo)
    segnalati = set()
    for c in cands:
        if c.metodo != "jsonld" or c.campo not in ("telefono", "email", "indirizzo", "partita_iva"):
            continue
        if c.campo == "telefono":
            ok = c.valore[3:] in cifre
        elif c.campo == "email":
            ok = c.valore.lower() in testo_min
        elif c.campo == "partita_iva":
            ok = c.valore in cifre
        else:
            via = c.valore.get("via")
            ok = bool(via) and _norm_testo_confronto(via) in testo_via
        if not ok:
            if c.confidenza == "alta":
                c.confidenza = "media"
            chiave = (c.campo, str(c.valore))
            if chiave not in segnalati:
                segnalati.add(chiave)
                v = c.valore if not isinstance(c.valore, dict) else ", ".join(x for x in c.valore.values() if x)
                avvisi.append(f"{c.campo} \"{v}\" presente solo nei dati strutturati (JSON-LD), non nel testo visibile del sito: confidenza ridotta")
