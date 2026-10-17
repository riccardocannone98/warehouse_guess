"""Adapter per piattaforma e riconoscimento automatico della piattaforma di un sito."""
from __future__ import annotations

import httpx

from . import generic, shopify, woocommerce
from ..http import SiteError, get_text

ADAPTERS = {
    "shopify": shopify.search,
    "woocommerce": woocommerce.search,
    "generic": generic.search,
}


async def detect_platform(client: httpx.AsyncClient, base_url: str) -> str:
    if await shopify.looks_like_shopify(client, base_url):
        return "shopify"
    if await woocommerce.looks_like_woocommerce(client, base_url):
        return "woocommerce"
    # Se anche la home è bloccata la piattaforma resta da rilevare (SiteError risale).
    html = (await get_text(client, base_url) or "").lower()
    if "cdn.shopify.com" in html or "shopify.theme" in html:
        return "shopify"
    if "woocommerce" in html:
        return "woocommerce"
    return "generic"
