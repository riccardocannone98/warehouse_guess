#!/bin/bash
# Avvio di Warehouse Guess su macOS / Linux (doppio clic o collegamento sul desktop).
cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/python ]; then
    echo "Prima installazione: preparo l'ambiente Python, attendi..."
    if ! python3 -m venv .venv; then
        echo
        echo "Python 3 non trovato. Installalo da https://www.python.org/downloads/ e riprova."
        read -r -p "Premi Invio per chiudere."
        exit 1
    fi
fi

if ! .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt; then
    echo
    echo "Installazione delle librerie non riuscita: controlla la connessione internet."
    read -r -p "Premi Invio per chiudere."
    exit 1
fi

exec .venv/bin/python run.py
