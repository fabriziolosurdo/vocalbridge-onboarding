# Onboarding automatico dei clienti — v1 (27/09/2026)

**In sintesi.** Dato il sito di un cliente (e, se c'è la chiave, la sua scheda Google) lo strumento raccoglie da solo telefono, indirizzo, orari, servizi, zone, urgenze 24 ore, P.IVA, email e social, e per ogni dato indica la pagina e la frase esatta da cui l'ha copiato. Sui 5 siti di prova ha trovato il telefono giusto 5 volte su 5, comune e provincia 5 su 5, e nessun servizio che non sia scritto nel sito. Quando un dato manca o due fonti si contraddicono lo dice, invece di scegliere o indovinare.

## Risultati sui 5 siti di prova (fabbri di Milano e provincia)

| Sito | Telefono principale | Comune e provincia | Servizi corretti | Urgenza 24 ore |
|---|---|---|---|---|
| lartenelferro.it (Solaro) | giusto | giusto | 5 su 5 | giusto (non dichiarata) |
| coscoservice.it (Milano) | giusto | giusto | 22 su 30 (gli altri 8 sono comunque scritti nel sito) | giusto (sì) |
| fabbromilano.it (Milano) | giusto | giusto | 10 su 10 | giusto (sì) |
| brescianifabbro.it (Milano) | giusto | giusto | 10 su 10 | giusto (sì) |
| cdscasasicura.com (Trezzano s/N) | giusto | giusto | 25 su 30 (gli altri 5 sono comunque scritti nel sito) | giusto (non dichiarata) |

"Servizi corretti" = voci che coincidono con quelle che ho annotato a mano leggendo il sito. Le voci restanti sono varianti presenti nel sito (es. "Serrature cilindro europeo", "Aperture Giudiziarie") che non avevo elencato; nessuna è inventata. Tutti i 68 controlli automatici passano, senza internet né chiavi, in circa 7 secondi.

## Sesto sito, mai visto prima: artefermilano.com (eseguito online)

Ragione sociale, P.IVA, fisso e cellulare, due email, indirizzo (Via Semplicità 4, 20161 Milano), orari (lun–ven 8–12 e 13–17:30, sabato e domenica chiuso), 26 servizi e 2 social. Ho confrontato ogni dato con le pagine: tutto corrisponde, e un controllo automatico ha ritrovato alla lettera sul sito tutte le 36 frasi citate come fonte. Zone servite e urgenze restano vuote perché il sito non le indica. Prima di consegnare ho tolto dai servizi due didascalie di foto ("Cilindro europeo (foto dal web)", "Porta materassi").

## Cosa ha evitato sui siti veri

Indirizzi e numeri "di esempio" lasciati dai temi grafici ("Mainstreet 1234 Anytown", "02 [numero di telefono]"), un CAP sbagliato ("0068") nei dati nascosti di un sito, una pagina servizi copiata da un'altra attività (assistenza Sanitrit), i contatti di un fornitore citato in un articolo del blog, e i link social del tema grafico. Nei casi dubbi il dato è segnalato negli avvisi.

## Limiti onesti

- Scheda Google e intelligenza artificiale sono pronte ma **non provate con chiavi vere** (non ne avevo): provate con risposte simulate. Il modello "deepseek-chat" del brief non compare più nella documentazione di DeepSeek: uso "deepseek-flash", modificabile.
- Orari scritti in forma discorsiva o senza giorni ("dalle 8 alle 17") restano vuoti, con avviso.
- Siti che mostrano i testi solo con JavaScript, o il telefono solo in immagine, danno risultati parziali.
- Il filtro dei servizi oggi conosce solo il mestiere "fabbro"; per altri mestieri le voci escono con confidenza bassa.
- Su siti con molte pagine-città (es. coscoservice: 338 comuni) il rapporto riporta le prime 60 zone.

Scelte prudenti prese da solo sui punti ambigui: "pronto intervento" senza "24 ore" esplicito non vale come urgenza 24 ore (campo vuoto + avviso); la provincia si riporta solo se scritta (per Milano città il nome coincide); un dato presente solo nei dati nascosti del sito, e non nel testo visibile, esce con confidenza ridotta e avviso.

## Cosa manca per la v2

Vocabolario dei servizi per gli altri mestieri e per gli studi; prova reale con chiavi Google e DeepSeek su 10–20 clienti; lettura dei siti che richiedono JavaScript; formato di uscita adattato al primo prodotto che userà lo strumento.
