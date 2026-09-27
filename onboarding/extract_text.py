"""Stadio A, parte 2: regex ed euristiche sul testo visibile e sui link.

Ogni candidato porta con sé il frammento letterale da cui è tratto.
Regola generale: nel dubbio si scarta (campo vuoto + avviso), mai si indovina.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional
from urllib.parse import urlparse

from .candidati import Candidato, normalizza_spazi, taglia
from .comuni import cerca_comune, comune_plausibile, e_sigla, sigla_di_provincia
from .fetch import Pagina, dominio, slug

# ---------------------------------------------------------------------------
# Telefoni
# ---------------------------------------------------------------------------

_SEP = r"[ .\-/]"
TEL_RE = re.compile(
    rf"(?<![\w+])((?:\+|00)[ ]?39[ .\-]?)?"
    rf"(\(?0\d{{1,3}}\)?(?:{_SEP}?\d){{4,9}}|3\d{{2}}(?:{_SEP}?\d){{6,7}}|80[0-3](?:{_SEP}?\d){{3,7}})"
    rf"(?![\w/])"
)
_CONTESTO_NON_TEL = re.compile(r"(iva|c\.?\s?f\.?|fiscale|rea|fax|\bf\.|cap\b|codice|cod\.|n\.\s?reg|matricola|iban)\W*$", re.I)

# Dati di contatto (telefono, email, indirizzo, P.IVA, ragione sociale) si leggono solo
# dalle pagine dell'azienda stessa: in un articolo di blog possono comparire fornitori o clienti.
PAGINE_CONTATTO = ("home", "contatti", "chi_siamo")
_ETICHETTA_TEL = re.compile(r"(tel|telefono|cell|cellulare|chiama|mobile|numero|whatsapp|uffici|fisso|📞|☎)", re.I)


def e164(testo: str) -> Optional[str]:
    """Normalizza un numero italiano in E.164 (+39...). None se non plausibile."""
    t = testo.strip()
    cifre = re.sub(r"\D", "", t)
    if t.startswith("+") or t.startswith("00"):
        cifre = cifre[2:] if t.startswith("00") else cifre
        if not cifre.startswith("39"):
            return None
        cifre = cifre[2:]
    elif cifre.startswith("39") and len(cifre) >= 11 and cifre[2] in "03":
        cifre = cifre[2:]
    if cifre.startswith("3") and 9 <= len(cifre) <= 10:
        return "+39" + cifre
    if cifre.startswith("0") and 6 <= len(cifre) <= 11:
        return "+39" + cifre
    if re.match(r"80[0-3]", cifre) and 6 <= len(cifre) <= 10:
        return "+39" + cifre
    return None


def estrai_telefoni(p: Pagina, piva: set[str]) -> list[Candidato]:
    out = []
    if p.tipo not in PAGINE_CONTATTO:
        return out
    for riga in p.testo.split("\n"):
        for m in TEL_RE.finditer(riga):
            prima = riga[max(0, m.start() - 25):m.start()]
            if _CONTESTO_NON_TEL.search(prima):
                continue
            grezzo = m.group(0)
            if re.sub(r"\D", "", grezzo) in piva:
                continue
            n = e164(grezzo)
            if not n:
                continue
            conf = "alta" if _ETICHETTA_TEL.search(riga[max(0, m.start() - 40):m.start()]) else "media"
            out.append(Candidato("telefono", n, p.url, taglia(riga, m.start(), m.end()),
                                 "regex", conf, p.tipo))
    for a in p.soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("tel:"):
            n = e164(re.sub(r"^tel:", "", href, flags=re.I).replace("%20", " "))
            if n:
                out.append(Candidato("telefono", n, p.url, href, "regex", "alta", p.tipo,
                                     extra={"tel_link": True}))
    return out


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"(?<![\w.\-+])[A-Za-z0-9][A-Za-z0-9._%+\-]*@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}(?![\w@])")
_EMAIL_SCARTA = re.compile(
    r"\.(png|jpe?g|gif|webp|svg|css|js)$|@(\dx|example\.|sentry|wixpress|domain\.|dominio\.|email\.it$|tuaemail|yourdomain)",
    re.I,
)


def estrai_email(p: Pagina) -> list[Candidato]:
    out = []
    if p.tipo not in PAGINE_CONTATTO:
        return out
    for riga in p.testo.split("\n"):
        for m in EMAIL_RE.finditer(riga):
            e = m.group(0).rstrip(".")
            if _EMAIL_SCARTA.search(e):
                continue
            out.append(Candidato("email", e.lower(), p.url, taglia(riga, m.start(), m.end()),
                                 "regex", "alta", p.tipo))
    for a in p.soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            e = href[7:].split("?")[0].strip()
            if EMAIL_RE.fullmatch(e) and not _EMAIL_SCARTA.search(e):
                out.append(Candidato("email", e.lower(), p.url, href.split("?")[0], "regex", "alta", p.tipo))
    return out


# ---------------------------------------------------------------------------
# Partita IVA e ragione sociale
# ---------------------------------------------------------------------------

PIVA_RE = re.compile(
    r"(?:P\.?\s?IVA|P\.\s?I\.|Partita\s+I\.?V\.?A\.?|VAT(?:\s+(?:number|n\.?|no\.?))?)\s*(?:n\.|nr\.|n°|numero)?\s*[:.\-]?\s*(?:IT\s?)?(\d{11})(?!\d)",
    re.I,
)


def piva_valida(n: str) -> bool:
    """Cifra di controllo della partita IVA italiana."""
    if not re.fullmatch(r"\d{11}", n):
        return False
    s = 0
    for i, c in enumerate(n[:10]):
        d = int(c)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        s += d
    return (10 - s % 10) % 10 == int(n[10])


def estrai_piva(p: Pagina) -> list[Candidato]:
    out = []
    if p.tipo not in PAGINE_CONTATTO:
        return out
    for riga in p.testo.split("\n"):
        for m in PIVA_RE.finditer(riga):
            n = m.group(1)
            ok = piva_valida(n)
            out.append(Candidato("partita_iva", n, p.url, taglia(riga, m.start(), m.end()),
                                 "regex", "alta" if ok else "bassa", p.tipo, extra={"checksum_ok": ok}))
    return out


_FORMA = r"(?:s\.?\s?r\.?\s?l\.?\s?s\.?|s\.?\s?r\.?\s?l\.?(?:\s?u\.?)?|s\.?\s?n\.?\s?c\.?|s\.?\s?a\.?\s?s\.?|s\.?\s?p\.?\s?a\.?|soc\.?\s?coop\.?)"
RAGIONE_RIGA_RE = re.compile(rf"^((?:[A-Z0-9ÀÈÉÌÒÙ][\w'’&.\-]*\s+){{0,5}}{_FORMA})$", re.I)
COPYRIGHT_RE = re.compile(r"©\s*(?:\d{4}\s*[-–]?\s*)?(?:\d{4}\s+)?([A-Z][\w'’&. ]{2,60}?)\s*[-–|,]\s*(?:P\.?\s?IVA|Partita\s+IVA)", re.I)


def estrai_ragione_sociale(p: Pagina) -> list[Candidato]:
    out = []
    if p.tipo not in PAGINE_CONTATTO:
        return out
    for riga in p.testo.split("\n"):
        r = riga.strip(" -–|•")
        m = RAGIONE_RIGA_RE.match(r)
        if m and len(r.split()) >= 2 and r[0].isupper() and not re.search(r"@|\d{5}", r):
            out.append(Candidato("ragione_sociale", r, p.url, riga, "regex", "alta", p.tipo))
            continue
        m = COPYRIGHT_RE.search(riga)
        if m:
            nome = m.group(1).strip()
            if not re.search(r"tutti i diritti|all rights|copyright", nome, re.I):
                out.append(Candidato("ragione_sociale", nome, p.url, taglia(riga, m.start(), m.end()),
                                     "heuristica", "media", p.tipo))
    return out


# ---------------------------------------------------------------------------
# Indirizzo
# ---------------------------------------------------------------------------

_TIPI_VIA = (r"Via\s+privata|Viale|V\.le|Via|Piazzale|P\.le|Piazza|P\.zza|P\.za|Corso|C\.so|Largo|Vicolo|"
             r"Strada\s+(?:Provinciale|Statale|Comunale|Vicinale)|Strada|S\.P\.|S\.S\.|Alzaia|Ripa|Bastioni|"
             r"Galleria|Contrada|Località|Loc\.|Frazione|Fraz\.|Borgo|Lungolago|Traversa")
VIA_RE = re.compile(
    rf"(?<![\w])((?:{_TIPI_VIA})\s+(?:[A-Za-zÀ-ÿ'’.]+\s+){{0,5}}?[A-Za-zÀ-ÿ'’.]+),?\s+(\d{{1,4}}(?:\s?/\s?\d{{1,4}}|\s?/?[A-Za-z](?![\w]))?)(?![\d])",
    re.I,
)
CAP_RE = re.compile(r"(?<!\d)(\d{5})(?!\d)")
_SEP_IND = r"[\s,\-–•|]*"


def _comune_dopo(testo: str) -> Optional[tuple[str, str, int]]:
    """Cerca un comune ISTAT all'inizio di ``testo``: (testo letterale, nome ufficiale, fine)."""
    parole = list(re.finditer(r"[A-Za-zÀ-ÿ'’]+", testo[:80]))
    if not parole or parole[0].start() > 3:
        return None
    for k in range(min(6, len(parole)), 0, -1):
        letterale = testo[parole[0].start():parole[k - 1].end()]
        if not letterale[0].isupper() and not letterale.islower():
            continue
        uff = comune_plausibile(letterale)
        if uff:
            return letterale, uff, parole[k - 1].end()
    return None


def _provincia_dopo(testo: str) -> tuple[Optional[str], int]:
    m = re.match(r"\s*[\-–,]?\s*\(?\s*([A-Z]{2})\s*\)?(?![A-Za-z])", testo)
    if m and e_sigla(m.group(1)):
        return m.group(1), m.end()
    m = re.match(r"\s*[\-–,(]\s*(?:provincia di\s+)?([A-Z][a-zà-ù]+(?:\s[a-z]+\s[A-Z][a-zà-ù]+)?)\)?", testo)
    if m and sigla_di_provincia(m.group(1)):
        return m.group(1), m.end()
    return None, 0


def _indirizzo(via: Optional[str], cap: Optional[str], com: Optional[tuple], resto: str) -> tuple[dict, int]:
    lett, uff, _ = com
    prov, fine = _provincia_dopo(resto)
    info = cerca_comune(uff)[1]
    if prov is None and info["capoluogo"]:
        # "Milano" è anche il nome della sua provincia: il testo letterale lo contiene già.
        prov = lett
    return {"via": via, "cap": cap, "comune": lett, "provincia": prov}, fine


def estrai_indirizzi(p: Pagina) -> list[Candidato]:
    if p.tipo not in PAGINE_CONTATTO:
        return []
    out = []
    righe = p.testo.split("\n")
    for i, riga in enumerate(righe):
        usate = False
        for m in VIA_RE.finditer(riga):
            via = normalizza_spazi(m.group(1) + (", " if "," in riga[m.end(1):m.start(2)] else " ") + m.group(2))
            dopo = riga[m.end():]
            testo_frammento = riga
            if not dopo.strip() and i + 1 < len(righe) and CAP_RE.match(righe[i + 1].strip()):
                dopo = " " + righe[i + 1]
                testo_frammento = riga + " " + righe[i + 1]
            ms = re.match(_SEP_IND, dopo)
            j = ms.end()
            cap = None
            mc = CAP_RE.match(dopo[j:])
            if mc:
                cap = mc.group(1)
                j += mc.end()
                j += re.match(_SEP_IND, dopo[j:]).end()
            elif dopo[:j].strip(" ") == "":
                continue  # senza virgola né CAP, un nome dopo il civico è ambiguo
            com = _comune_dopo(dopo[j:])
            if not com:
                continue
            val, fine = _indirizzo(via, cap, com, dopo[j + com[2]:])
            conf = "alta" if cap and val["provincia"] else "media"
            out.append(Candidato("indirizzo", val, p.url, normalizza_spazi(testo_frammento[:m.start()][-30:] + testo_frammento[m.start():m.end() + j + com[2] + fine]),
                                 "regex", conf, p.tipo))
            usate = True
        if usate:
            continue
        # CAP + comune a inizio riga, eventualmente seguiti dalla via ("20123 milano corso magenta 56")
        mc = re.match(r"\s*(\d{5})" + _SEP_IND, riga)
        if mc and not (i > 0 and VIA_RE.search(righe[i - 1])):
            com = _comune_dopo(riga[mc.end():])
            if com:
                resto = riga[mc.end() + com[2]:]
                val, fine = _indirizzo(None, mc.group(1), com, resto)
                mv = VIA_RE.match(resto[fine:].strip())
                if mv:
                    val["via"] = normalizza_spazi(mv.group(1) + " " + mv.group(2))
                out.append(Candidato("indirizzo", val, p.url, normalizza_spazi(riga[:120]), "regex",
                                     "media", p.tipo))
    return out


# ---------------------------------------------------------------------------
# Orari
# ---------------------------------------------------------------------------

GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
_GIORNO = (r"(lun(?:edì|edi|\.)?|mar(?:tedì|tedi|\.)?|mer(?:coledì|coledi|\.)?|gio(?:vedì|vedi|\.)?|"
           r"ven(?:erdì|erdi|\.)?|sab(?:ato|\.)?|dom(?:enica|\.)?)(?![a-zà-ù])")
_ORA = r"(\d{1,2})(?:[:.](\d{2}))?"
_INTERVALLO = rf"(?:dalle\s+(?:ore\s+)?)?{_ORA}\s*(?:-|–|alle(?:\s+ore)?|a)\s*{_ORA}"
ORARI_RE = re.compile(
    rf"(?:dal\s+)?{_GIORNO}(?:\s*(?:-|–|al|a|/)\s*{_GIORNO}|((?:\s*(?:,|e)\s*(?:lun|mar|mer|gio|ven|sab|dom)[a-zà-ù.]*)+))?\s*[:\-–]?\s*"
    rf"((?:(?:{_INTERVALLO})(?:\s*(?:,|/|e|;|-|–)?\s*)){{1,3}}|chius[oia]|closed)",
    re.I,
)
_INTERVALLO_RE = re.compile(_INTERVALLO, re.I)
_TUTTI_RE = re.compile(rf"(tutti i giorni|7 giorni su 7|lun(?:edì)?\s*(?:-|–|al)\s*dom(?:enica)?)\s*[:\-–]?\s*((?:{_INTERVALLO}\s*(?:,|/|e)?\s*){{1,3}})", re.I)


def _giorno_idx(t: str) -> Optional[int]:
    t = t.lower()[:3]
    return GIORNI.index(t) if t in GIORNI else None


def _fmt(h: str, m: Optional[str]) -> Optional[str]:
    h_i, m_i = int(h), int(m or 0)
    if h_i > 24 or m_i > 59:
        return None
    return f"{h_i:02d}:{m_i:02d}"


def _intervalli(testo: str) -> Optional[str]:
    if re.fullmatch(r"\s*(chius[oia]|closed)\s*", testo, re.I):
        return "chiuso"
    parti = []
    for m in _INTERVALLO_RE.finditer(testo):
        a, b = _fmt(m.group(1), m.group(2)), _fmt(m.group(3), m.group(4))
        if not a or not b or a >= b and b != "00:00":
            return None
        parti.append(f"{a}-{b}")
    return ", ".join(parti) or None


def parse_orari(testo: str) -> tuple[dict, list[tuple[int, int]]]:
    """Orari scritti in forma strutturata. Restituisce (dict giorno->orario, spans usati)."""
    risultato: dict[str, str] = {}
    spans = []
    for m in _TUTTI_RE.finditer(testo):
        v = _intervalli(m.group(2))
        if v:
            for g in GIORNI:
                risultato.setdefault(g, v)
            spans.append(m.span())
    for m in ORARI_RE.finditer(testo):
        g1 = _giorno_idx(m.group(1))
        g2 = _giorno_idx(m.group(2)) if m.group(2) else None
        v = _intervalli(m.group(4))
        if g1 is None or v is None:
            continue
        giorni = [g1]
        if g2 is not None:
            giorni = list(range(g1, g2 + 1)) if g2 >= g1 else []
        elif m.group(3):
            giorni += [i for i in (_giorno_idx(x) for x in re.findall(r"[a-zà-ù]+", m.group(3), re.I)) if i is not None]
        for g in giorni:
            risultato[GIORNI[g]] = v
        spans.append(m.span())
    return risultato, spans


def estrai_orari(p: Pagina) -> tuple[list[Candidato], bool]:
    """(candidati, orari_in_prosa): il secondo segnala orari non strutturati."""
    piatto = normalizza_spazi(p.testo)
    orari, spans = parse_orari(piatto)
    out = []
    if orari:
        a = min(s[0] for s in spans)
        b = max(s[1] for s in spans)
        if b - a > 400:  # blocchi lontani: tengo il primo blocco contiguo
            orari, spans = parse_orari(piatto[spans[0][0]:spans[0][0] + 400])
            b = a + max(s[1] for s in spans)
        out.append(Candidato("orari", orari, p.url, piatto[a:b], "regex", "alta" if p.tipo == "contatti" else "media", p.tipo))
    prosa = bool(re.search(r"\borari[oa]?\b", piatto, re.I)) and not orari
    if not orari:
        # Orari con le ore ma senza i giorni ("Orari: dalle 8:00 alle 17:00"): non si attribuiscono ai giorni.
        m = re.search(rf"\borari\w*\s*:?\s*({_INTERVALLO})", piatto, re.I)
        if m:
            p.extra_avvisi.append(f"orari senza giorni della settimana su {p.url}: «{normalizza_spazi(m.group(0))}» (non attribuiti ai giorni)")
    return out, prosa


# ---------------------------------------------------------------------------
# Urgenza h24
# ---------------------------------------------------------------------------

H24_RE = re.compile(
    r"\b(h\s?24|24\s?h\b|24\s?/\s?24|24\s?/\s?7|24\s?ore\s?su\s?24|24\s?ore\s?(?:al giorno|7 giorni|e 7|,? ?7 giorni)|"
    r"7\s?giorni\s?su\s?7|giorno e notte|notte e giorno|24 ore)",
    re.I,
)
URGENZA_RE = re.compile(r"pronto intervento|urgenz|emergenz|notturn|festivi", re.I)


def estrai_urgenza(p: Pagina) -> tuple[list[Candidato], bool]:
    out = []
    piatto = normalizza_spazi(p.testo)
    for m in H24_RE.finditer(piatto):
        prima = piatto[max(0, m.start() - 25):m.start()].lower()
        if re.search(r"(entro|in|nelle|risposta|preventivo|rispondiamo)\s*(le\s*)?$", prima):
            continue  # "entro 24 ore", "preventivo in 24h": non è reperibilità
        if m.group(1).lower().replace(" ", "") == "24ore":
            dopo = piatto[m.end():m.end() + 25].lower()
            if not re.match(r"\s*(su 24|al giorno|,? ?7|e 7|tutti|sempre|/)", dopo) and not re.search(r"(attiv|operativ|disponibil|reperibil|aperti)\w*\s*$", prima):
                continue
        out.append(Candidato("urgenza_h24", True, p.url, taglia(piatto, m.start(), m.end(), 50),
                             "regex", "alta", p.tipo))
        break
    solo_urgenza = not out and bool(URGENZA_RE.search(piatto))
    return out, solo_urgenza


# ---------------------------------------------------------------------------
# Servizi
# ---------------------------------------------------------------------------

LESSICO = {
    "fabbro": [
        r"apertur", r"serratur", r"cilindr", r"blindat", r"\bport[ae]\b", r"portoncin", r"porton",
        r"cancell", r"inferriat", r"\bgrat[ae]\b", r"serrand", r"basculant", r"ringhier", r"recinzion",
        r"tapparell", r"avvolgibil", r"cassafort", r"casseforti", r"chiav", r"\bscal[ae]\b", r"soppalc",
        r"pensilin", r"tettoi", r"carpenteri", r"saldatur", r"zanzarier", r"persian", r"infiss",
        r"serrament", r"\bbox\b", r"maniglion", r"antipanico", r"\bcler\b", r"saracinesc", r"lattoner",
        r"parapett", r"corrimano", r"vetrin", r"verand", r"dehor", r"fiorier", r"linee vita",
        r"struttur\w* (?:in )?metallic", r"ferro battuto", r"lavorazion\w* (?:del )?ferro", r"duplicazion",
        r"motorizzazion", r"automazion", r"soppalch", r"arredo urbano", r"costruzioni metalliche",
        r"opere in ferro", r"isole ecologiche", r"porte rei", r"tagliafuoco", r"defender",
    ],
}
_SCARTA_SERVIZIO = re.compile(
    r"prezz|offert|costo|bonus|detrazion|news|blog|privacy|cookie|contatt|chi siamo|home\b|galler|"
    r"preventiv|scopri|leggi|clicca|chiama|richied|\?|!|@|https?:|www\.|\d{4,}|€",
    re.I,
)
TAG_SERVIZIO = ["h2", "h3", "h4", "h5", "li", "dt"]
# "Card" dei page builder (Elementor, Oxygen, Wix...): blocchi di testo brevi senza figli a blocchi.
TAG_CARD = ["p", "div", "span", "a", "strong", "b"]
_BLOCCHI = ["div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table", "br"]
_INIZIO_NON_SERVIZIO = re.compile(
    r"^(come|perch[eé]|vantaggi|cosa|quando|quanto|quali|il nostro|la nostra|i nostri|le nostre|scegli|"
    r"tipi|tipologi|domande|faq|guida|consigli|dove|chi|distributor|rivenditor|scopri|leggi|vedi|marchi|"
    r"brand|partner|certificaz|ultimi|ultime|articol|caratteristich|esperti|specialisti|professionisti|"
    r"servizio di|servizi di|serratura giusta|blocco)\w*\b", re.I)
_CONTENITORI_NO = re.compile(r"tag|cloud|categor|widget|breadcrumb|sidebar|comment|share|social|cookie|footer|related|recent", re.I)


def _pulisci_voce(t: str) -> str:
    t = normalizza_spazi(t)
    return re.sub(r"^[^\wÀ-ÿ]+|[^\wÀ-ÿ)]+$", "", t)  # simboli ed emoji in testa/coda


def _togli_localita(v: str) -> str:
    """"Apertura Porte Bloccate Milano" -> "Apertura Porte Bloccate" (sottostringa letterale)."""
    v = re.sub(r"\s+e\s+provincia$", "", v, flags=re.I)
    parole = v.split()
    for k in range(min(4, len(parole) - 1), 0, -1):
        coda = " ".join(parole[-k:])
        if comune_plausibile(coda):
            testa = parole[:-k]
            while testa and testa[-1].lower() in ("a", "in", "di", "per", "zona", "-", "–"):
                testa = testa[:-1]
            if testa:
                return " ".join(testa)
    return v


def estrai_servizi(p: Pagina, mestiere: str) -> list[Candidato]:
    if p.tipo not in ("home", "servizi", "menu"):
        return []
    lessico = LESSICO.get(slug(mestiere))
    out = []
    viste = set()
    for el in p.soup.find_all(TAG_SERVIZIO + TAG_CARD):
        testo_grezzo = el.get_text(" ")
        if len(testo_grezzo) > 120:
            continue
        testo = _pulisci_voce(testo_grezzo).rstrip(".;,")
        if not testo or len(testo) < 4 or len(testo.split()) > 6 or _SCARTA_SERVIZIO.search(testo):
            continue
        if _INIZIO_NON_SERVIZIO.search(testo) or re.search(r"\b(autorizzat|certificat|garantit|gratuit|dal \d)", testo, re.I):
            continue
        if re.match(rf"^{re.escape(mestiere)}i?\b", testo, re.I):
            continue  # "Fabbro Monza": è una zona, non un servizio
        if lessico is None:
            conf = "bassa"
        elif any(re.search(r, testo, re.I) for r in lessico):
            conf = "media"
        else:
            continue
        antenati = list(el.parents)[:12]
        if any(_CONTENITORI_NO.search(" ".join(a.get("class") or []) + " " + (a.get("id") or ""))
               for a in [el, *antenati] if hasattr(a, "get")):
            continue
        if el.name in TAG_CARD:
            if el.find(_BLOCCHI) or any(a.name in TAG_SERVIZIO or a.name in ("footer", "form", "button", "label")
                                        for a in list(el.parents)):
                continue
            # La voce deve essere l'intero blocco, non una parola evidenziata dentro un paragrafo.
            blocco = el if el.name in ("p", "div") else next((a for a in antenati if a.name in ("p", "div")), None)
            if blocco is not None and normalizza_spazi(blocco.get_text(" ")) != normalizza_spazi(testo_grezzo):
                continue
        elif el.find(TAG_SERVIZIO):  # solo foglie: evita di prendere interi menu
            continue
        valore = _togli_localita(testo)
        k = valore.lower()
        if k in viste or len(valore) < 4:
            continue
        viste.add(k)
        out.append(Candidato("servizi", valore, p.url, testo, "heuristica", conf, p.tipo,
                             extra={"tag": el.name}))
    return out


# ---------------------------------------------------------------------------
# Zone servite
# ---------------------------------------------------------------------------

REGIONI = {"Lombardia", "Piemonte", "Veneto", "Emilia-Romagna", "Liguria", "Toscana", "Lazio",
           "Trentino-Alto Adige", "Friuli-Venezia Giulia", "Valle d'Aosta", "Umbria", "Marche",
           "Abruzzo", "Molise", "Campania", "Puglia", "Basilicata", "Calabria", "Sicilia", "Sardegna"}
_CONTESTO_ZONA = re.compile(r"\b(zone|zona|interveniamo|interveniamo|operiamo|serviamo|copriamo|in tutta|dove operiamo|comuni|provincia di|hinterland)\b", re.I)


def _zona_da_titolo(titolo: str, mestiere: str) -> Optional[tuple[str, int, int]]:
    m = re.match(rf"\s*{re.escape(mestiere)}i?\s+(?:a\s+|in\s+|di\s+|per\s+|zona\s+)?([A-Z][\w'’]+(?:[ \-][A-Za-z][\w'’]+){{0,3}})", titolo, re.I)
    if not m:
        return None
    parole = m.group(1).split()
    for k in range(len(parole), 0, -1):
        nome = " ".join(parole[:k])
        if comune_plausibile(nome):
            return nome, m.start(1), m.start(1) + len(nome)
    return None


def estrai_zone(p: Pagina, mestiere: str) -> list[Candidato]:
    out = []
    # 1) pagine-zona generate in serie: title e h1, non il corpo (punto 5 del brief)
    if p.tipo == "zona":
        h1 = p.soup.find("h1")
        for t in [h1.get_text(" ") if h1 else "", p.titolo]:
            t = normalizza_spazi(t)
            z = _zona_da_titolo(t, mestiere)
            if z:
                out.append(Candidato("zone_servite", z[0], p.url, t, "heuristica", "media", p.tipo))
                break
    # 2) voci di elenco/link del tipo "Fabbro Sesto San Giovanni"
    for a in p.soup.find_all(["a", "li"]):
        if a.find(["a", "li"]):
            continue
        t = normalizza_spazi(a.get_text(" "))
        if len(t.split()) <= 6:
            z = _zona_da_titolo(t, mestiere)
            if z and (z[2] >= len(t) - 1 or t[z[2]:].strip().lower() in ("e provincia",)):
                out.append(Candidato("zone_servite", z[0], p.url, t, "heuristica", "media", p.tipo))
    # 3) frasi "interveniamo a Milano, Monza e ..." (solo nomi di comuni ISTAT o regioni).
    #    Serve un elenco (almeno 2 nomi) oppure la forma esplicita "in tutta X" / "X e provincia":
    #    un nome isolato può essere un quartiere omonimo di un comune (es. "Loreto" a Milano).
    for riga in p.testo.split("\n"):
        if not _CONTESTO_ZONA.search(riga) or len(riga) > 400:
            continue
        trovati = []
        for m in re.finditer(r"(?<![\w'])([A-Z][a-zà-ù'’]+(?:[ \-](?:[A-Z][a-zà-ù'’]+|d[ei]l?|sul|sull'|al|in|di|e)){0,4})", riga):
            parole = m.group(1).split()
            for k in range(len(parole), 0, -1):
                nome = " ".join(parole[:k])
                if nome in REGIONI or (comune_plausibile(nome) and nome[0].isupper()):
                    trovati.append((nome, m.start()))
                    break
        for nome, ini in trovati:
            esplicito = re.search(rf"(in tutta(?: la)?(?: provincia di)?\s+{re.escape(nome)}|{re.escape(nome)} e (?:provincia|hinterland))", riga, re.I)
            if len(trovati) >= 2 or esplicito:
                out.append(Candidato("zone_servite", nome, p.url, taglia(riga, ini, ini + len(nome)),
                                     "heuristica", "media" if esplicito or nome in REGIONI else "bassa", p.tipo))
    return out


# ---------------------------------------------------------------------------
# Social (link esterni: registrati, mai scaricati)
# ---------------------------------------------------------------------------

SOCIAL_DOMINI = ("facebook.com", "instagram.com", "linkedin.com", "youtube.com", "tiktok.com",
                 "twitter.com", "x.com", "pinterest.com", "pinterest.it", "paginegialle.it", "houzz.it")


def _somiglia(a: str, b: str, n: int = 5) -> bool:
    a, b = re.sub(r"[^a-z0-9]", "", a.lower()), re.sub(r"[^a-z0-9]", "", b.lower())
    return any(a[i:i + n] in b for i in range(max(0, len(a) - n + 1)))


def social_dell_azienda(url_social: str, sito: str) -> bool:
    """Il profilo deve richiamare il nome del dominio: evita i link del tema grafico (es. yootheme)."""
    percorso = urlparse(url_social).path
    base = dominio(sito).split(".")[0]
    return _somiglia(base, percorso)


def estrai_social(p: Pagina) -> list[Candidato]:
    out = []
    for a in p.soup.find_all("a", href=True):
        href = a["href"].strip()
        d = dominio(href)
        if not any(d == s or d.endswith("." + s) for s in SOCIAL_DOMINI):
            continue
        if re.search(r"sharer|/share|intent/|/dialog/|plugins/|/p/|/reel/|/tv/|/explore/|/watch|/status/|/posts?/", href, re.I):
            continue
        u = urlparse(href)
        if not u.path.strip("/"):
            continue
        valore = f"https://{u.netloc.lower()}{u.path.rstrip('/')}"
        out.append(Candidato("social", valore, p.url, href, "regex", "alta", p.tipo))
    return out


# ---------------------------------------------------------------------------

def estrai_tutto(pagine: list[Pagina], mestiere: str, avvisi: list[str],
                 gia: Optional[list[Candidato]] = None) -> list[Candidato]:
    """``gia``: candidati già trovati (JSON-LD), usati solo per decidere gli avvisi."""
    gia = gia or []
    cands: list[Candidato] = []
    for p in pagine:
        cands += estrai_piva(p)
    piva = {c.valore for c in cands}
    prosa_orari, solo_urgenza = False, False
    for p in pagine:
        cands += estrai_telefoni(p, piva)
        cands += estrai_email(p)
        cands += estrai_ragione_sociale(p)
        cands += estrai_indirizzi(p)
        o, pr = estrai_orari(p)
        cands += o
        prosa_orari |= pr
        avvisi += p.extra_avvisi
        u, su = estrai_urgenza(p)
        cands += u
        solo_urgenza |= su
        cands += estrai_servizi(p, mestiere)
        cands += estrai_zone(p, mestiere)
        cands += estrai_social(p)
    if prosa_orari and not any(c.campo == "orari" for c in cands + gia):
        avvisi.append("orari citati nel sito ma non in forma strutturata (giorni + ore): lasciati vuoti")
    if solo_urgenza and not any(c.campo == "urgenza_h24" for c in cands + gia):
        avvisi.append("il sito parla di pronto intervento/urgenze ma non dichiara esplicitamente il servizio 24 ore: urgenza_h24 lasciato vuoto")
    for n in sorted({c.valore for c in cands if c.campo == "telefono" and c.valore.startswith("+393") and len(c.valore) == 12}):
        avvisi.append(f"cellulare {n} ha 9 cifre invece di 10: riportato come scritto, da verificare")
    for c in cands:
        if c.campo == "partita_iva" and not c.extra.get("checksum_ok"):
            avvisi.append(f"partita IVA {c.valore} con cifra di controllo non valida (riportata come scritta, confidenza bassa)")
    if any(re.search(r"protett\w* dagli spambot|\[email[^\]]*protected\]", p.testo, re.I) for p in pagine):
        avvisi.append("almeno un indirizzo email è nascosto da una protezione anti-spam: non letto")
    return cands


def filtra_social(cands: list[Candidato], sito: str, avvisi: list[str]) -> list[Candidato]:
    scartati = sorted({c.valore for c in cands if c.campo == "social" and not social_dell_azienda(c.valore, sito)})
    if scartati:
        avvisi.append("link social scartati perché non richiamano il nome del sito (spesso sono del tema grafico): "
                      + ", ".join(scartati))
    return [c for c in cands if c.campo != "social" or social_dell_azienda(c.valore, sito)]


def conta_pagine(cands: list[Candidato]) -> dict:
    per_valore: dict = defaultdict(set)
    for c in cands:
        per_valore[(c.campo, str(c.valore))].add(c.url)
    return per_valore
