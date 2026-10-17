"""Avvio locale: python run.py  →  http://127.0.0.1:8000"""
import argparse
import socket
import threading
import webbrowser

import uvicorn


def already_running(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Warehouse Guess — disponibilità sneaker per taglia")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="non aprire il browser all'avvio")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    # Doppio clic sul collegamento con l'app già aperta: si riapre solo il browser.
    if already_running(args.port):
        print(f"Warehouse Guess è già in esecuzione su {url}")
        if not args.no_browser:
            webbrowser.open(url)
        raise SystemExit(0)
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    print(f"Warehouse Guess in esecuzione su {url}")
    print("Chiudi questa finestra (o premi Ctrl+C) per fermare l'app.")
    uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=args.port)
