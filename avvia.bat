@echo off
rem Avvio di Warehouse Guess su Windows (doppio clic o collegamento sul desktop).
title Warehouse Guess
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Prima installazione: preparo l'ambiente Python, attendi...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo Python non trovato. Installalo da https://www.python.org/downloads/
        echo spuntando "Add python.exe to PATH", poi riprova.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo.
    echo Installazione delle librerie non riuscita: controlla la connessione internet.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" run.py
if errorlevel 1 pause
