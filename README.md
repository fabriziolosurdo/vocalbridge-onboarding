# VocalBridge — onboarding automatico dei clienti (v1)

Dato il sito di un cliente e/o la sua scheda Google, lo strumento recupera da solo i dati che servono
il primo giorno (telefono, indirizzo, orari, servizi, zone servite, urgenze 24 ore, P.IVA, email, social)
e per **ogni singolo valore** dice da dove l'ha preso: pagina, frammento di testo letterale, metodo e
confidenza. Un dato che non si trova resta vuoto: **nessun valore viene dedotto o inventato**.

Serve ai tre prodotti (assistente vocale, gestione scheda Google, assistente per studio).

## Installazione

Python 3.11 o successivo.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Chiavi facoltative, **solo come variabili d'ambiente** (mai nel repository, `.env` è ignorato da git):

| Variabile | Effetto se presente | Se manca |
|---|---|---|
| `GOOGLE_PLACES_API_KEY` | legge la scheda Google (1 sola chiamata `places.get` per esecuzione) | stadio saltato, con avviso |
| `DEEPSEEK_API_KEY` | usa l'LLM per servizi/zone/orari scritti in prosa (max 8 chiamate) | stadio saltato, con avviso |
| `DEEPSEEK_MODEL` | cambia il modello DeepSeek (default `deepseek-flash`, vedi Limiti) | — |

## Uso

```bash
python -m onboarding --sito https://www.artefermilano.com --mestiere fabbro --out ./out/artefer
```

Con la scheda Google (place_id, oppure un link Google Maps che contiene il place_id):

```bash
python -m onboarding --sito https://www.esempio.it --gbp ChIJxxxxxxxx --mestiere fabbro --out ./out/esempio
```

Nella cartella `--out` vengono scritti:

- `dati.json` — tutti i dati nello schema concordato (punto 3 del brief);
- `RAPPORTO.md` — la stessa cosa in una tabella leggibile in un minuto, più avvisi e campi vuoti.

Opzione `--senza-llm` per non usare l'LLM anche se la chiave è presente.

## Esempio di uscita (eseguito davvero il 27/09/2026 sul primo comando qui sopra)

`RAPPORTO.md` (estratto):

| Campo | Valore | Fonte | Confidenza |
|---|---|---|---|
| Ragione sociale | ARTEFER S.A.S. | www.artefermilano.com/dove-siamo — «ARTEFER S.A.S.» | alta (regex) |
| Partita IVA | 11184070156 | www.artefermilano.com/dove-siamo — «P.I. 11184070156 \|» | alta (regex) |
| Telefono | +390266202067 | www.artefermilano.com/dove-siamo — «Tel. 02 66 20 20 67» | alta (regex) |
| Indirizzo | Via Semplicità 4, 20161 Milano | www.artefermilano.com/ — «Via Semplicità 4 20161 Milano» | alta (regex) |
| Orari | lun–ven 08:00-12:00, 13:00-17:30; sab, dom chiuso | www.artefermilano.com/dove-siamo — «Lun - Ven 8:00 - 12:00 13:00 - 17:30 Sab - Dom Chiuso» | alta (regex) |
| Urgenze 24 ore | — | | |

`dati.json` (estratto): ogni campo ha sempre le quattro chiavi, anche quando è vuoto.

```json
"telefono": [
  { "valore": "+390266202067",
    "fonte": { "url": "https://www.artefermilano.com/dove-siamo", "frammento": "Tel. 02 66 20 20 67" },
    "metodo": "regex", "confidenza": "alta" }
],
"urgenza_h24": { "valore": null, "fonte": null, "metodo": null, "confidenza": null }
```

Oltre alle chiavi del brief, `dati.json` contiene `statistiche` (chiamate Places, chiamate LLM,
candidati LLM proposti e `llm_scartati`). I campi-lista vuoti (es. nessun social) sono `[]` e compaiono
in `campi_vuoti`.

## Come lavora

1. **Sito** (sempre): legge robots.txt e lo rispetta, User-Agent `VocalBridgeOnboarding/1.0`, timeout 15 s,
   massimo 25 pagine, solo lo stesso dominio, massimo 2 richieste al secondo. Trova le pagine da
   sitemap e link interni (contatti, chi siamo, servizi, orari, zone, pronto intervento…).
   Estrae prima i dati strutturati schema.org (JSON-LD), poi il testo visibile e i link `tel:`/`mailto:`.
2. **Scheda Google** (se c'è la chiave): una sola chiamata Places API (New) con i campi minimi;
   niente recensioni né foto.
3. **LLM** (se c'è la chiave): legge il testo delle pagine e propone candidati con il frammento da cui
   li ha presi. Un candidato è accettato **solo** se il frammento compare alla lettera nella pagina
   (spazi e maiuscole a parte) e il valore compare nel frammento; gli altri sono scartati e contati.
   Mai confidenza "alta".
4. **Fusione**: a parità di campo vale jsonld > google_places > regex > heuristica > llm_verificato.
   Se due fonti dicono cose diverse, si riportano **entrambe** con un avviso.

Accorgimenti contro i dati falsi (visti davvero sui siti di prova): indirizzi e numeri "segnaposto"
dei temi grafici ("Mainstreet 1234 Anytown", "02 [numero di telefono]"), CAP non validi nel JSON-LD,
partite IVA confuse con telefoni, numeri di fax, contatti di fornitori citati negli articoli del blog,
link social del tema grafico, dati presenti solo nel JSON-LD e non nel testo visibile (confidenza ridotta).
I nomi di comuni sono validati sull'elenco ufficiale ISTAT (`onboarding/data/comuni_istat.json`).

## Test

```bash
python -m pytest -q
```

La suite gira offline, senza chiavi, in circa 7 secondi: usa 5 siti reali di fabbri milanesi salvati
in `tests/fixtures/<sito>/` (pagine HTML, `FONTI.md` con URL e data di download, `atteso.json`
compilato a mano). Stadi Google e LLM sono provati con risposte finte: zero chiamate a pagamento
(ogni accesso alla rete durante i test fa fallire il test).

Per aggiungere un sito di prova: `python scripts/scarica_fixture.py <nome> <url> [mestiere]`, poi scrivere
a mano `atteso.json`.

## Limiti noti

- **Orari in prosa** ("aperti tutti i giorni, anche la domenica") o **senza giorni** ("dalle 8 alle 17")
  restano vuoti, con avviso; lo stadio LLM li recupera solo se il frammento contiene giorni e ore.
- **Siti costruiti interamente in JavaScript** (alcuni Wix/Jimdo) o con il telefono solo in immagine:
  si legge solo ciò che è nell'HTML (compresi JSON-LD e link `tel:`), non si esegue il JavaScript.
- **Email protette** da script anti-spam (es. Joomla, Cloudflare) non vengono lette: avviso.
- **Servizi**: solo voci brevi (≤ 6 parole) di elenchi, titoli e riquadri, filtrate con un vocabolario del
  mestiere. Oggi il vocabolario esiste solo per `fabbro`; per altri mestieri le voci sono prese con
  confidenza bassa. Le voci sono letterali ma possono includere varianti o categorie di galleria.
- **Zone servite**: nomi validati come comuni ISTAT o regioni; un quartiere omonimo di un comune
  (es. "Loreto" a Milano) può comparire, con confidenza bassa.
- **Link Google Maps abbreviati** (`maps.app.goo.gl/...`) o senza place_id: lo stadio Google si ferma
  con avviso (non si apre Google Maps).
- **DeepSeek**: il brief indicava il modello `deepseek-chat`; la documentazione ufficiale consultata il
  27/09/2026 non lo elenca più e indica `deepseek-flash` (impostabile con `DEEPSEEK_MODEL`).
  Stadi Google e LLM sono verificati con risposte simulate: nessuna chiave disponibile in sviluppo.
- La provincia è riportata solo se scritta (sigla o nome); per i capoluoghi il nome del comune coincide
  con quello della provincia (es. "Milano").
