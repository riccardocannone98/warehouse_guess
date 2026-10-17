"""Avvio locale: python run.py  →  http://127.0.0.1:8000"""
import argparse
import threading
import webbrowser

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Warehouse Guess — disponibilità sneaker per taglia")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="non aprire il browser all'avvio")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    print(f"Warehouse Guess in esecuzione su {url} (Ctrl+C per fermare)")
    uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=args.port)
