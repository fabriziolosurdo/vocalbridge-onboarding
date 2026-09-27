"""Stadio E: rapporto Markdown leggibile in un minuto da chi deve chiamare il cliente."""
from __future__ import annotations

from .schema import CAMPI, Campo, Risultato

ETICHETTE = {
    "ragione_sociale": "Ragione sociale", "partita_iva": "Partita IVA", "telefono": "Telefono",
    "email": "Email", "indirizzo": "Indirizzo", "zone_servite": "Zone servite", "orari": "Orari",
    "urgenza_h24": "Urgenze 24 ore", "servizi": "Servizi", "social": "Social",
}
MAX_RIGHE_PER_CAMPO = 8


def _cella(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _valore(c: Campo) -> str:
    v = c.valore
    if isinstance(v, bool):
        return "sì" if v else "no"
    if isinstance(v, dict):
        if "comune" in v or "via" in v:
            parti = [v.get("via"), " ".join(x for x in (v.get("cap"), v.get("comune")) if x)]
            s = ", ".join(p for p in parti if p)
            return s + (f" ({v['provincia']})" if v.get("provincia") and v.get("provincia") != v.get("comune") else "")
        return "; ".join(f"{k} {x}" for k, x in v.items())
    return str(v)


def _fonte(c: Campo) -> str:
    if not c.fonte:
        return ""
    url = c.fonte.url
    corto = url.split("//", 1)[-1][:50]
    fr = c.fonte.frammento
    fr = fr if len(fr) <= 70 else fr[:67] + "…"
    return f"[{_cella(corto)}]({url}) — «{_cella(fr)}»"


def genera(r: Risultato) -> str:
    a = r.azienda
    nome = a.ragione_sociale
    titolo = (nome[0] if isinstance(nome, list) else nome).valore or r.input.sito or r.input.gbp
    righe = [
        f"# Onboarding — {titolo}",
        "",
        f"Mestiere: **{r.input.mestiere}** · Sito: {r.input.sito or '—'} · Scheda Google: {r.input.gbp or '—'} · "
        f"Estratto il {r.input.data_estrazione[:16].replace('T', ' ')} UTC",
        "",
        "Ogni valore è copiato dalla fonte indicata; nessun dato è dedotto. Un campo vuoto significa: non trovato.",
        "",
        "| Campo | Valore | Fonte | Confidenza |",
        "|---|---|---|---|",
    ]
    for campo in CAMPI:
        v = getattr(a, campo)
        voci = v if isinstance(v, list) else [v]
        voci = [x for x in voci if x.valore is not None]
        if not voci:
            righe.append(f"| {ETICHETTE[campo]} | — | | |")
            continue
        for i, c in enumerate(voci[:MAX_RIGHE_PER_CAMPO]):
            et = ETICHETTE[campo] if i == 0 else ""
            righe.append(f"| {et} | {_cella(_valore(c))} | {_fonte(c)} | {c.confidenza} ({c.metodo}) |")
        if len(voci) > MAX_RIGHE_PER_CAMPO:
            altre = ", ".join(_valore(c) for c in voci[MAX_RIGHE_PER_CAMPO:])
            righe.append(f"| | …e altre {len(voci) - MAX_RIGHE_PER_CAMPO}: {_cella(altre[:400])} | vedi JSON | |")
    righe += ["", "## Avvisi", ""]
    righe += [f"- {x}" for x in r.avvisi] or ["- nessuno"]
    righe += ["", "## Campi vuoti", ""]
    righe += [", ".join(ETICHETTE[c] for c in r.campi_vuoti) or "nessuno"]
    s = r.statistiche
    righe += [
        "", "## Contatori", "",
        f"- Pagine lette: {len(r.pagine_lette)}",
        f"- Chiamate Google Places: {s.places_chiamate} (massimo 1)",
        f"- Chiamate LLM: {s.llm_chiamate} (massimo 8) · candidati proposti: {s.llm_candidati} · "
        f"llm_scartati (non trovati alla lettera nella pagina): {s.llm_scartati}",
        "",
    ]
    return "\n".join(righe)
