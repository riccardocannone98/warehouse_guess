# Warehouse Guess

Applicazione locale per controllare la **disponibilità per taglia** (in pezzi, quando il sito la espone) di uno o più modelli di sneaker su una lista di rivenditori che gestisci tu.

Cerchi per **style code**, il codice modello + colorway che è lo stesso su tutti i negozi:

| Brand | Esempio | Dove si trova |
|---|---|---|
| Nike / Jordan | `DD1391-100` | etichetta interna della scarpa, scatola, "Codice stile" sul sito Nike |
| adidas | `IE3438` | linguetta interna, URL del prodotto su adidas.com |
| New Balance | `U9060AAA` | etichetta interna, nome del prodotto |

Il confronto ignora maiuscole, spazi e trattini: `dd1391 100`, `DD1391-100` e lo SKU di variante `DD1391-100-42` vengono riconosciuti tutti.

## Avvio

Richiede Python 3.10 o successivo.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py                    # apre http://127.0.0.1:8000
```

I dati (siti e storico ricerche) stanno in `data/warehouse.db`, un file SQLite locale escluso da git. Per usare un altro file: variabile d'ambiente `WAREHOUSE_DB`.

## Come si usa

1. **Siti**: aggiungi i rivenditori uno alla volta (`+ Nuovo sito`) o incolla una lista in *Importazione rapida* (`URL` oppure `Nome;URL`, uno per riga). La lista si esporta in CSV.
2. **Ricerca**: incolla uno o più style code e premi *Cerca*. Di default interroga tutti i siti attivi; dal riquadro "Siti in cui cercare" puoi limitarla ad alcuni.
3. **Risultati**: per ogni codice c'è una matrice sito × taglia con i pezzi disponibili, il totale per riga e per taglia, il log per sito (trovato / nessun risultato / errore) e l'export Excel.

Significato delle celle:

- **numero**: pezzi a magazzino
- **✓**: disponibile, ma il sito non espone la quantità
- **0**: esaurito
- **?**: disponibilità non nota

## Da dove arrivano i numeri

La piattaforma di ogni sito viene rilevata automaticamente alla prima ricerca. Puoi anche impostarla a mano o usare *Rileva piattaforma*.

| Piattaforma | Ricerca prodotto | Quantità per taglia |
|---|---|---|
| **Shopify** (la maggior parte delle boutique sneaker) | `/search/suggest.json`, poi scansione di `/products.json` | `inventory_quantity` se il negozio lo espone (JSON o variabili del tema); altrimenti, se abiliti il **probe carrello**, il limite che il carrello accetta. Senza nessuna delle due: solo disponibile/esaurito. |
| **WooCommerce** | Store API `/wp-json/wc/store/v1/products` | `low_stock_remaining` oppure il massimo acquistabile (`add_to_cart.maximum`) quando il negozio gestisce lo stock |
| **Generico** | pagina di ricerca del sito, poi i link ai prodotti | dati strutturati schema.org (`inventoryLevel`), JSON delle varianti WooCommerce nella pagina, oppure **selettori CSS personalizzati** |

### Probe carrello (Shopify, facoltativo)

Si attiva per singolo sito. Aggiunge 1 pezzo a un carrello anonimo e isolato, chiede 9999 pezzi e legge quanti il negozio ne accetta, cioè lo stock; poi svuota il carrello. Costa una richiesta in più per taglia, quindi è più lento. Non funziona sui negozi che limitano la quantità per ordine (es. "max 1 paio").

### Siti generici: configurazione avanzata

Se un sito non è Shopify/WooCommerce e non pubblica dati strutturati, dalla scheda del sito puoi indicare:

- **URL di ricerca** con `{code}`, es. `https://negozio.it/catalogsearch/result/?q={code}`
- **Selettore link prodotto**, es. `a.product-item-link`
- **Selettore taglie**: un elemento per taglia, es. `.size-selector li`
- **Attributo taglia** / **attributo quantità** (es. `data-size`, `data-stock`) oppure una **regex quantità** con un gruppo, applicata all'HTML dell'elemento

Gli elementi con classe `disabled` o con attributo `disabled` sono considerati esauriti. Testi come "Solo 2 rimasti" o "3 disponibili" vengono letti automaticamente.

## Limiti da conoscere

- Molti negozi **non pubblicano la quantità esatta**: in quel caso l'app mostra solo disponibile/esaurito (✓ / 0). Il numero è affidabile quanto la fonte indicata nel tooltip della cella e nella colonna "Metodo rilevazione" dell'export.
- I siti con protezione anti-bot (Cloudflare, Akamai, DataDome) possono rispondere 403/429: compaiono come *errore* nel log e la ricerca prosegue sugli altri siti.
- Le richieste sono contenute (massimo 4 siti in parallelo, codici in sequenza sullo stesso sito). Usa l'app per consultazioni puntuali e rispetta i termini d'uso dei siti.

## Struttura

```
run.py                  avvio locale (uvicorn + apertura browser)
app/
  main.py               route web: ricerca, risultati, anagrafica siti
  db.py                 SQLite: siti, ricerche, risultati, log
  search.py             esecuzione parallela per sito
  sku.py                normalizzazione codici, ordinamento taglie, lettura quantità da testo
  report.py             matrice taglie ed export Excel
  http.py               client HTTP e gestione errori dei siti
  adapters/
    shopify.py          Shopify (+ probe carrello)
    woocommerce.py      WooCommerce Store API
    generic.py          JSON-LD, form varianti WooCommerce, selettori CSS
  templates/, static/   interfaccia
tests/                  test con negozi simulati (nessun accesso a internet)
```

Per eseguire i test:

```bash
pip install -r requirements-dev.txt
python -m pytest
```
