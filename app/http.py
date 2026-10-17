"""Client HTTP comune a tutti gli adapter."""
from __future__ import annotations

from typing import Callable

import httpx

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

ClientFactory = Callable[[], httpx.AsyncClient]


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=20.0, follow_redirects=True)


class SiteError(Exception):
    """Il sito non risponde o blocca le richieste (bot protection, rate limit)."""


async def fetch(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response | None:
    """GET che restituisce None per le pagine inesistenti e solleva SiteError
    quando il problema riguarda il sito nel suo insieme."""
    try:
        response = await client.get(url, **kwargs)
    except httpx.HTTPError as exc:
        raise SiteError(f"connessione fallita verso {url}: {exc.__class__.__name__}") from exc
    if response.status_code in (401, 403, 429) or response.status_code >= 500:
        raise SiteError(f"HTTP {response.status_code} da {url} (sito protetto o sovraccarico)")
    if response.status_code != 200:
        return None
    return response


async def get_json(client: httpx.AsyncClient, url: str, **kwargs):
    response = await fetch(client, url, **kwargs)
    if response is None:
        return None
    try:
        return response.json()
    except ValueError:
        return None


async def get_text(client: httpx.AsyncClient, url: str, **kwargs) -> str | None:
    response = await fetch(client, url, **kwargs)
    return None if response is None else response.text
