"""Download in sola lettura: robots.txt, rate limit, sitemap, crawl limitato.

Due "fetcher" con la stessa interfaccia ``get(url) -> Risposta | None``:
- ``HttpFetcher``: rete vera (requests), User-Agent dichiarato, timeout 15 s,
  massimo 2 richieste/secondo per dominio;
- ``FixtureFetcher``: legge le pagine salvate sotto ``tests/fixtures/<slug>/``
  (usato dai test, zero rete).
``RegistraFetcher`` avvolge un fetcher e salva ciò che scarica come fixture.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

USER_AGENT = "VocalBridgeOnboarding/1.0 (+https://vocalbridge.co.uk)"
UA_TOKEN = "VocalBridgeOnboarding"
TIMEOUT_S = 15
MAX_PAGINE = 25
MAX_RICHIESTE_AL_SECONDO = 2

# Parole chiave del brief (punto 4.A.2), in ordine di priorità.
PAROLE_CHIAVE = [
    "contatt", "dove-siamo", "chi-siamo", "orari", "servizi", "pronto-intervento",
    "emergenz", "h24", "zone", "azienda", "lavori", "prodotti", "realizzazioni",
]
ESTENSIONI_NON_HTML = re.compile(
    r"\.(jpe?g|png|gif|webp|svg|ico|pdf|zip|rar|docx?|xlsx?|pptx?|mp4|mp3|avi|mov|css|js|xml|txt|json|woff2?|ttf|eot)$",
    re.I,
)
SALTA_PERCORSI = re.compile(
    r"/(wp-admin|wp-login|wp-json|feed|cart|carrello|checkout|my-account|login|tag|author|category|page/\d+)(/|$)|[?&](replytocom|share|s)=",
    re.I,
)


@dataclass
class Risposta:
    url: str  # URL finale dopo i redirect
    stato: int
    testo: str
    content_type: str = ""


class Fetcher(Protocol):
    def get(self, url: str) -> Optional[Risposta]: ...


def _decodifica(resp) -> str:
    """Charset dal header, poi dal meta, poi apparent_encoding (punto 5)."""
    ct = resp.headers.get("content-type", "")
    m = re.search(r"charset=([\w\-]+)", ct, re.I)
    if m:
        enc = m.group(1)
    else:
        testa = resp.content[:4096].decode("ascii", "ignore")
        m = re.search(r"<meta[^>]+charset=[\"']?([\w\-]+)", testa, re.I)
        enc = m.group(1) if m else (resp.apparent_encoding or "utf-8")
    try:
        return resp.content.decode(enc, errors="replace")
    except LookupError:
        return resp.content.decode("utf-8", errors="replace")


class HttpFetcher:
    def __init__(self, timeout: float = TIMEOUT_S, max_rps: float = MAX_RICHIESTE_AL_SECONDO):
        import requests

        self.sessione = requests.Session()
        self.sessione.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.9",
        })
        self.timeout = timeout
        self.intervallo = 1.0 / max_rps
        self._ultima: dict[str, float] = {}
        self.richieste = 0

    def _attendi(self, url: str) -> None:
        host = urlparse(url).netloc
        attesa = self._ultima.get(host, 0) + self.intervallo - time.monotonic()
        if attesa > 0:
            time.sleep(attesa)
        self._ultima[host] = time.monotonic()

    def get(self, url: str) -> Optional[Risposta]:
        import requests

        self._attendi(url)
        self.richieste += 1
        try:
            r = self.sessione.get(url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException:
            return None
        return Risposta(url=r.url, stato=r.status_code, testo=_decodifica(r),
                        content_type=r.headers.get("content-type", ""))


def _nome_file(url: str) -> str:
    p = urlparse(url)
    base = (p.path.strip("/") or "home").replace("/", "__")
    base = re.sub(r"[^\w.\-]+", "_", base)[:80]
    if p.query:
        base += "_q" + hashlib.md5(p.query.encode()).hexdigest()[:6]
    return base


class FixtureFetcher:
    """Legge ``manifest.json`` + file salvati. Un URL assente equivale a 404."""

    def __init__(self, cartella: Path | str):
        self.cartella = Path(cartella)
        self.manifest: dict = json.loads((self.cartella / "manifest.json").read_text("utf-8"))

    def get(self, url: str) -> Optional[Risposta]:
        voce = self.manifest["risposte"].get(url)
        if voce is None:
            return Risposta(url=url, stato=404, testo="", content_type="text/html")
        testo = (self.cartella / voce["file"]).read_text("utf-8") if voce.get("file") else ""
        return Risposta(url=voce.get("url_finale", url), stato=voce["stato"], testo=testo,
                        content_type=voce.get("content_type", ""))


class RegistraFetcher:
    """Scarica con un fetcher reale e salva ogni risposta come fixture."""

    def __init__(self, interno: Fetcher, cartella: Path | str):
        self.interno = interno
        self.cartella = Path(cartella)
        (self.cartella / "pagine").mkdir(parents=True, exist_ok=True)
        self.manifest: dict = {"risposte": {}}

    def get(self, url: str) -> Optional[Risposta]:
        r = self.interno.get(url)
        if r is None:
            return None
        voce = {"stato": r.stato, "url_finale": r.url, "content_type": r.content_type}
        if r.stato == 200 and r.testo:
            nome = _nome_file(url)
            est = ".xml" if "xml" in r.content_type or url.endswith(".xml") else (
                ".txt" if url.endswith("robots.txt") else ".html")
            file = f"pagine/{nome}{est}"
            (self.cartella / file).write_text(r.testo, "utf-8")
            voce["file"] = file
        self.manifest["risposte"][url] = voce
        return r

    def salva_manifest(self, extra: dict | None = None) -> None:
        dati = dict(self.manifest)
        if extra:
            dati.update(extra)
        (self.cartella / "manifest.json").write_text(
            json.dumps(dati, ensure_ascii=False, indent=1), "utf-8")


# ---------------------------------------------------------------------------
# Pagine e testo visibile
# ---------------------------------------------------------------------------

@dataclass
class Pagina:
    url: str
    stato: int
    html: str
    titolo: str = ""
    testo: str = ""  # testo visibile, una riga per blocco
    tipo: str = "altra"  # home | contatti | servizi | zona | altra
    extra_avvisi: list = field(default_factory=list)
    _soup: Optional[BeautifulSoup] = field(default=None, repr=False)

    @property
    def soup(self) -> BeautifulSoup:
        if self._soup is None:
            self._soup = BeautifulSoup(self.html, "lxml")
        return self._soup


_NON_VISIBILI = {"script", "style", "noscript", "template", "svg", "iframe", "head"}


def testo_visibile(html: str) -> str:
    """Testo visibile, un pezzo per riga (come get_text("\\n") di BeautifulSoup, ma con lxml: più veloce)."""
    from lxml import etree, html as lh

    try:
        doc = lh.document_fromstring(html)
    except (ValueError, etree.ParserError):
        try:
            doc = lh.document_fromstring(html.encode("utf-8"))
        except Exception:
            return ""
    pezzi: list[str] = []

    def visita(el) -> None:
        tag = el.tag if isinstance(el.tag, str) else ""
        nome = tag.split("}")[-1].lower()
        if tag and nome not in _NON_VISIBILI and el.text:
            pezzi.append(el.text)
        if not tag or nome not in _NON_VISIBILI:
            for figlio in el:
                visita(figlio)
        if el.tail:
            pezzi.append(el.tail)

    import sys
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 5000))
    visita(doc)
    righe = []
    for pezzo in pezzi:
        for riga in pezzo.split("\n"):
            riga = re.sub(r"[ \t\u00a0\u200b\r]+", " ", riga).strip()
            if riga:
                righe.append(riga)
    return "\n".join(righe)


def crea_pagina(url: str, stato: int, html: str) -> Pagina:
    p = Pagina(url=url, stato=stato, html=html)
    t = p.soup.find("title")
    p.titolo = re.sub(r"\s+", " ", t.get_text()).strip() if t else ""
    p.testo = testo_visibile(html)
    return p


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------

def normalizza_sito(sito: str) -> str:
    sito = sito.strip()
    if not re.match(r"^https?://", sito, re.I):
        sito = "https://" + sito
    return sito


def dominio(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def stesso_dominio(url: str, base: str) -> bool:
    return dominio(url) == dominio(base)


def _pulisci_link(href: str, base: str) -> Optional[str]:
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#", "whatsapp:", "sms:")):
        return None
    u = urldefrag(urljoin(base, href.strip()))[0]
    if not u.startswith(("http://", "https://")):
        return None
    if ESTENSIONI_NON_HTML.search(urlparse(u).path) or SALTA_PERCORSI.search(u):
        return None
    return u


def _chiave(u: str) -> str:
    p = urlparse(u)
    return dominio(u) + (p.path.rstrip("/") or "/") + ("?" + p.query if p.query else "")


def slug(testo: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def classifica_url(url: str, mestiere: str) -> tuple[int, str]:
    """Priorità (più bassa = prima) e tipo di pagina, dal solo percorso."""
    pu = urlparse(url)
    percorso = pu.path.lower()
    if percorso.strip("/") == "":
        return (0, "home") if not pu.query else (100, "altra")
    for i, k in enumerate(PAROLE_CHIAVE):
        if k in percorso:
            tipo = "contatti" if k in ("contatt", "dove-siamo") else (
                "servizi" if k in ("servizi", "lavori", "prodotti", "realizzazioni") else
                "zona" if k == "zone" else "altra")
            return 1 + i, tipo
    m = slug(mestiere)
    if m and re.search(rf"(^|/){m}[a-z]*-(a-|in-|di-)?[a-z]", percorso):
        return 50, "zona"
    return 100, "altra"


class _Robots:
    def __init__(self, fetcher: Fetcher, base: str, avvisi: list[str]):
        self.rp = urllib.robotparser.RobotFileParser()
        self.sitemaps: list[str] = []
        url = urljoin(base, "/robots.txt")
        r = fetcher.get(url)
        if r is None or r.stato >= 500:
            # Errore di rete o del server su robots.txt: per prudenza non si legge nulla.
            self.rp.parse(["User-agent: *", "Disallow: /"])
            self.irraggiungibile = True
            return
        self.irraggiungibile = False
        righe = r.testo.splitlines() if r.stato == 200 else []
        self.rp.parse(righe)
        for riga in righe:
            if riga.lower().startswith("sitemap:"):
                self.sitemaps.append(riga.split(":", 1)[1].strip())

    def consentito(self, url: str) -> bool:
        return self.rp.can_fetch(UA_TOKEN, url)


def _leggi_sitemap(fetcher: Fetcher, url: str, base: str, profondita: int = 0) -> list[str]:
    r = fetcher.get(url)
    if r is None or r.stato != 200 or "<" not in r.testo[:200]:
        return []
    try:
        radice = ET.fromstring(r.testo.strip().encode("utf-8"))
    except ET.ParseError:
        return []
    locs = [e.text.strip() for e in radice.iter() if e.tag.endswith("loc") and e.text]
    if radice.tag.endswith("sitemapindex"):
        if profondita > 0:
            return []
        figli = [u for u in locs if stesso_dominio(u, base)
                 and not re.search(r"attachment|media|image|author|tag|categor|product_cat|video", u, re.I)]
        # Prima le sitemap delle pagine, poi il resto; massimo 5 sitemap.
        figli.sort(key=lambda u: (0 if re.search(r"page|pagin", u) else 1, u))
        tutti: list[str] = []
        for f in figli[:5]:
            tutti += _leggi_sitemap(fetcher, f, base, profondita + 1)
        return tutti
    return [u for u in locs if stesso_dominio(u, base)]


MAX_PAGINE_ZONA = 8
# Pagine-allegato di WordPress (una foto per pagina): nessun dato utile.
ALLEGATO_WP = re.compile(r"/[^/]+/(dsc|img|err|dcim|foto|image|photo|p)[-_]?\d{3,}(-\d+)?/?$", re.I)


def crawl(sito: str, fetcher: Fetcher, mestiere: str, avvisi: list[str],
          max_pagine: int = MAX_PAGINE) -> list[Pagina]:
    sito = normalizza_sito(sito)
    robots = _Robots(fetcher, sito, avvisi)
    if robots.irraggiungibile:
        avvisi.append("robots.txt non raggiungibile (errore di rete o del server): per prudenza nessuna pagina letta")
        return []
    if not robots.consentito(sito):
        avvisi.append("robots.txt vieta la lettura del sito: nessuna pagina letta")
        return []
    r = fetcher.get(sito)
    if r is None or r.stato != 200:
        avvisi.append(f"home non raggiungibile ({'errore di rete' if r is None else r.stato})")
        return []
    base = r.url
    home = crea_pagina(base, r.stato, r.testo)
    home.tipo = "home"
    pagine = [home]

    candidati: dict[str, str] = {}
    sitemap_urls = robots.sitemaps or [urljoin(base, "/sitemap.xml")]
    da_sitemap: list[str] = []
    for sm in sitemap_urls[:3]:
        if stesso_dominio(sm, base):
            da_sitemap += _leggi_sitemap(fetcher, sm, base)
    if not da_sitemap:
        avvisi.append("sitemap.xml assente o vuota: pagine trovate dai link interni")
    for u in da_sitemap:
        u2 = _pulisci_link(u, base)
        if u2:
            candidati.setdefault(_chiave(u2), u2)
    menu: set[str] = set()
    for a in home.soup.find_all("a", href=True):
        u = _pulisci_link(a["href"], base)
        if u and stesso_dominio(u, base):
            candidati.setdefault(_chiave(u), u)
            if a.find_parent(["nav", "header"]) or a.find_parent(class_=re.compile("menu|nav", re.I)):
                menu.add(_chiave(u))
    candidati.pop(_chiave(base), None)

    ordinati = []
    for k, u in candidati.items():
        prio, tipo = classifica_url(u, mestiere)
        if prio == 100 and k in menu:
            prio, tipo = 60, "menu"
        if prio < 100:
            if ALLEGATO_WP.search(urlparse(u).path):
                continue
            ordinati.append((prio, urlparse(u).path.rstrip("/").count("/"), len(u), u, tipo))
    ordinati.sort()

    n_zona = 0
    for prio, _, _, u, tipo in ordinati:
        if len(pagine) >= max_pagine:
            break
        if tipo == "zona":
            if n_zona >= MAX_PAGINE_ZONA:
                continue
            n_zona += 1
        if not robots.consentito(u):
            continue
        r = fetcher.get(u)
        if r is None or r.stato != 200 or "html" not in (r.content_type or "text/html"):
            continue
        if not stesso_dominio(r.url, base) or any(_chiave(p.url) == _chiave(r.url) for p in pagine):
            continue
        p = crea_pagina(r.url, r.stato, r.testo)
        corpo = p.soup.find("body")
        if corpo is not None and "attachment" in (corpo.get("class") or []):
            continue  # pagina-allegato di WordPress (una sola immagine)
        # Link con sola query (es. Joomla ?Itemid=): il tipo si ricava dall'URL finale.
        prio2, tipo2 = classifica_url(r.url, mestiere)
        p.tipo = tipo2 if prio2 < 100 and tipo2 != "home" else tipo
        # Tipo usato solo dall'estrazione (non cambia l'ordine di lettura).
        if re.search(r"/(blog|news|notizie|articoli)(/|$)|/\d{4}/\d{2}/", urlparse(r.url).path, re.I):
            p.tipo = "blog"
        elif re.search(r"chi-siamo|about|la-nostra-storia|azienda/?$", urlparse(r.url).path, re.I):
            p.tipo = "chi_siamo"
        pagine.append(p)
    if not any(p.tipo == "contatti" for p in pagine):
        avvisi.append("sito senza pagina contatti")
    return pagine
