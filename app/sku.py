"""Codici prodotto (style code / SKU) e taglie.

Lo "style code" identifica la combinazione modello + colorway ed è lo stesso
su tutti i rivenditori (es. Nike ``DD1391-100``, adidas ``IE3438``,
New Balance ``U9060AAA``). I siti lo scrivono in modi diversi
("DD1391 100", "dd1391-100", "DD1391-100-42" come SKU di variante), quindi il
confronto avviene sulla forma normalizzata: maiuscolo, solo lettere e cifre.
"""
from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_CODE_SEPARATORS = re.compile(r"[\n,;\t]+")


def normalize(code: str | None) -> str:
    return _NON_ALNUM.sub("", (code or "").upper())


def matches(query_norm: str, *texts) -> bool:
    """True se il codice normalizzato compare in almeno uno dei testi."""
    if not query_norm:
        return False
    for text in texts:
        if isinstance(text, (list, tuple)):
            if matches(query_norm, *text):
                return True
        elif text and query_norm in normalize(str(text)):
            return True
    return False


def parse_codes(raw: str) -> list[str]:
    """Una lista di codici da testo libero (uno per riga, o separati da , ;)."""
    codes: list[str] = []
    seen: set[str] = set()
    for chunk in _CODE_SEPARATORS.split(raw or ""):
        code = chunk.strip().upper()
        if code and normalize(code) not in seen:
            seen.add(normalize(code))
            codes.append(code)
    return codes


_FRACTIONS = {"½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "1/2": 0.5, "1/3": 1 / 3, "2/3": 2 / 3}
_SIZE_NUMBER = re.compile(r"(\d+(?:[.,]\d+)?)\s*(½|⅓|⅔|1/2|1/3|2/3)?")


def size_key(size: str) -> tuple:
    """Chiave di ordinamento: taglie numeriche in ordine crescente, poi le altre."""
    m = _SIZE_NUMBER.search(size or "")
    if not m:
        return (1, 0.0, size or "")
    value = float(m.group(1).replace(",", ".")) + _FRACTIONS.get(m.group(2) or "", 0.0)
    return (0, value, size)


_QTY_PATTERNS = [
    re.compile(
        r"(\d+)\s*(?:pz|pezz\w*|disponibil\w*|in\s+stock|left|rimast\w*|available|"
        r"en\s+stock|auf\s+lager|verfügbar)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:solo|only|ultim\w*|nur\s+noch|plus\s+que)\s+(\d+)", re.IGNORECASE),
    re.compile(r"stock\s*[:=]\s*(\d+)", re.IGNORECASE),
]


def qty_from_text(text: str | None) -> int | None:
    """Estrae un numero di pezzi da testi come "Solo 3 rimasti" o "2 disponibili"."""
    if not text:
        return None
    for pattern in _QTY_PATTERNS:
        m = pattern.search(text)
        if m:
            return int(m.group(1))
    return None
