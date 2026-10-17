"""Adapter per negozi WooCommerce tramite la Store API pubblica
(``/wp-json/wc/store/v1/products``).

Per ogni variante (taglia) la quantità viene da ``low_stock_remaining`` o, se
il negozio gestisce lo stock, dal massimo acquistabile ``add_to_cart.maximum``.
Se la Store API è disattivata si ripiega sull'adapter generico, che legge il
JSON delle varianti nella pagina prodotto.
"""
from __future__ import annotations

import httpx

from . import generic
from ..http import ClientFactory, SiteError, get_json
from ..models import ProductHit, Site, VariantStock
from ..sku import matches, normalize

API = "/wp-json/wc/store/v1/products"
MAX_PRODUCTS = 8
UNLIMITED = 9999
SIZE_ATTR_HINTS = generic.SIZE_ATTR_HINTS


async def search(client: httpx.AsyncClient, site: Site, code: str, client_factory: ClientFactory) -> list[ProductHit]:
    base = site.base_url
    query = normalize(code)
    found = await get_json(client, base + API, params={"search": code, "per_page": 20})
    if found is None:
        fallback = Site(**{**site.__dict__, "config": {"search_url": f"{base}/?s={{code}}&post_type=product", **site.config}})
        return await generic.search(client, fallback, code, client_factory)

    products = [p for p in found if _product_matches(p, query)]
    if not products:
        by_sku = await get_json(client, base + API, params={"sku": code, "per_page": 20}) or []
        products = [p for p in by_sku if _product_matches(p, query)]

    hits = []
    for product in products[:MAX_PRODUCTS]:
        variants: list[VariantStock] = []
        if product.get("variations"):
            for variation in product["variations"]:
                detail = await get_json(client, f"{base}{API}/{variation['id']}") or {}
                variants.append(_variant(detail, _size(variation.get("attributes") or []), variation["id"]))
        else:
            variants.append(_variant(product, "Unica", product.get("id")))
        prices = [v.price for v in variants if v.price is not None]
        images = product.get("images") or [{}]
        hits.append(
            ProductHit(
                title=product.get("name", ""),
                url=product.get("permalink", ""),
                image=images[0].get("src", "") if images else "",
                price=min(prices) if prices else _price(product.get("prices")),
                currency=(product.get("prices") or {}).get("currency_code", ""),
                variants=variants,
            )
        )
    return hits


def _product_matches(product: dict, query: str) -> bool:
    return matches(
        query,
        product.get("sku"),
        product.get("name"),
        product.get("permalink"),
        product.get("short_description"),
        product.get("description"),
    )


def _size(attributes: list[dict]) -> str:
    for attr in attributes:
        if any(h in str(attr.get("name", "")).lower() for h in SIZE_ATTR_HINTS):
            return generic._slug_size(attr.get("value"))
    return generic._slug_size(attributes[0].get("value")) if attributes else "?"


def _price(prices: dict | None) -> float | None:
    if not prices or prices.get("price") in (None, ""):
        return None
    return int(prices["price"]) / 10 ** int(prices.get("currency_minor_unit", 2))


def _variant(data: dict, size: str, ref) -> VariantStock:
    available = data.get("is_in_stock")
    qty = data.get("low_stock_remaining")
    maximum = (data.get("add_to_cart") or {}).get("maximum")
    if not isinstance(qty, int) and isinstance(maximum, int) and 0 < maximum < UNLIMITED and not data.get("sold_individually"):
        qty = maximum
    if isinstance(qty, int):
        method = "store api"
    elif available is False:
        qty, method = 0, "esaurito"
    else:
        qty, method = None, "solo disponibilità"
    return VariantStock(
        size=size,
        quantity=qty,
        available=available,
        sku=data.get("sku") or "",
        price=_price(data.get("prices")),
        method=method,
        ref=str(ref or ""),
    )


async def looks_like_woocommerce(client, base: str) -> bool:
    try:
        data = await get_json(client, base + API, params={"per_page": 1})
    except SiteError:
        return False
    return isinstance(data, list)
