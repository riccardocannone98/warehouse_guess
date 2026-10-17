"""Adapter per negozi Shopify (la maggior parte delle boutique sneaker).

Fonti usate, in ordine:
1. ``/search/suggest.json`` per trovare i prodotti dal codice; se non dà
   risultati si scorre il catalogo pubblico ``/products.json``.
2. ``/products/<handle>.js`` per taglie e disponibilità (sì/no) di ogni variante.
3. ``inventory_quantity`` quando il negozio lo espone ancora (``.json`` del
   prodotto o variabili del tema nella pagina HTML).
4. Facoltativo, per sito: "probe carrello" — aggiunge 1 pezzo a un carrello
   anonimo, chiede 9999 pezzi e legge quanti ne accetta il negozio (= stock),
   poi svuota il carrello.
"""
from __future__ import annotations

import re

import httpx

from ..http import ClientFactory, SiteError, fetch, get_json, get_text
from ..models import ProductHit, Site, VariantStock
from ..sku import matches, normalize

MAX_PRODUCTS = 8
PROBE_QUANTITY = 9999
SIZE_OPTION_HINTS = ("size", "tagl", "misur", "talla", "taille", "größe", "grosse", "eu", "us", "uk")


async def search(client: httpx.AsyncClient, site: Site, code: str, client_factory: ClientFactory) -> list[ProductHit]:
    query = normalize(code)
    products = await _candidate_products(client, site, code, query)
    if products and not site.config.get("currency"):
        site.config["currency"] = await _currency(client, site.base_url)
    return [await _build_hit(client, site, product, client_factory) for product in products]


async def _currency(client, base: str) -> str:
    for path in ("/meta.json", "/cart.js"):
        try:
            data = await get_json(client, base + path)
        except SiteError:
            return ""
        if isinstance(data, dict) and data.get("currency"):
            return str(data["currency"])
    return ""


async def _candidate_products(client, site: Site, code: str, query: str) -> list[dict]:
    base = site.base_url
    suggest = await get_json(
        client,
        f"{base}/search/suggest.json",
        params={"q": code, "resources[type]": "product", "resources[limit]": 10},
    )
    handles: list[str] = []
    for item in ((suggest or {}).get("resources") or {}).get("results", {}).get("products", []):
        handle = item.get("handle") or _handle_from_url(item.get("url", ""))
        if handle and handle not in handles:
            handles.append(handle)

    products: list[dict] = []
    for handle in handles[:MAX_PRODUCTS]:
        product = await get_json(client, f"{base}/products/{handle}.js")
        if product and _product_matches(product, query):
            products.append(product)
    if products:
        return products

    # La ricerca interna spesso non indicizza gli SKU: si scorre il catalogo.
    max_pages = int(site.config.get("max_pages") or 3)
    for page in range(1, max_pages + 1):
        data = await get_json(client, f"{base}/products.json", params={"limit": 250, "page": page})
        items = (data or {}).get("products") or []
        for item in items:
            if _product_matches(item, query):
                product = await get_json(client, f"{base}/products/{item['handle']}.js")
                products.append(product or item)
        if len(items) < 250 or len(products) >= MAX_PRODUCTS:
            break
    return products[:MAX_PRODUCTS]


def _handle_from_url(url: str) -> str:
    match = re.search(r"/products/([^/?#]+)", url)
    return match.group(1) if match else ""


def _product_matches(product: dict, query: str) -> bool:
    variant_skus = [v.get("sku") for v in product.get("variants", [])]
    return matches(
        query,
        product.get("title"),
        product.get("handle"),
        product.get("tags"),
        product.get("body_html") or product.get("description"),
        variant_skus,
    )


def _size_option_index(options) -> int:
    names = [(o.get("name") if isinstance(o, dict) else o) or "" for o in (options or [])]
    for i, name in enumerate(names):
        lowered = name.lower()
        if any(hint in lowered for hint in SIZE_OPTION_HINTS):
            return i
    return 0


def _price(value) -> float | None:
    """``.js`` usa i centesimi (int), ``.json`` una stringa in unità."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value / 100
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _image(product: dict) -> str:
    src = product.get("featured_image") or ((product.get("images") or [{}])[0] or {})
    if isinstance(src, dict):
        src = src.get("src", "")
    src = src or ""
    return "https:" + src if src.startswith("//") else src


async def _build_hit(client, site: Site, product: dict, client_factory: ClientFactory) -> ProductHit:
    base = site.base_url
    handle = product.get("handle", "")
    url = f"{base}/products/{handle}"
    size_index = _size_option_index(product.get("options"))

    variants: list[VariantStock] = []
    for v in product.get("variants", []):
        qty = v.get("inventory_quantity")
        has_qty = isinstance(qty, int)
        variants.append(
            VariantStock(
                size=str(v.get(f"option{size_index + 1}") or v.get("title") or "?"),
                quantity=max(qty, 0) if has_qty else None,
                available=v.get("available"),
                sku=v.get("sku") or "",
                price=_price(v.get("price")),
                method="inventario esposto" if has_qty else "",
                ref=str(v.get("id", "")),
            )
        )

    if _missing(variants):
        await _fill_from_product_json(client, base, handle, variants)
    if _missing(variants):
        await _fill_from_html(client, url, variants)
    if site.cart_probe:
        for v in _missing(variants):
            if v.available is not False:
                qty = await _cart_probe(client_factory, base, v.ref)
                if qty is not None:
                    v.quantity, v.method = qty, "probe carrello"

    for v in variants:
        if v.quantity is None and v.available is False:
            v.quantity, v.method = 0, "esaurito"
        elif v.quantity is None:
            v.method = "solo disponibilità"

    prices = [v.price for v in variants if v.price is not None]
    return ProductHit(
        title=product.get("title", ""),
        url=url,
        image=_image(product),
        price=min(prices) if prices else _price(product.get("price")),
        currency=site.config.get("currency", ""),
        variants=variants,
    )


def _missing(variants: list[VariantStock]) -> list[VariantStock]:
    return [v for v in variants if v.quantity is None]


async def _fill_from_product_json(client, base: str, handle: str, variants: list[VariantStock]) -> None:
    try:
        data = await get_json(client, f"{base}/products/{handle}.json")
    except SiteError:
        return
    by_id = {str(v.get("id")): v for v in ((data or {}).get("product") or {}).get("variants", [])}
    for v in _missing(variants):
        qty = (by_id.get(v.ref) or {}).get("inventory_quantity")
        if isinstance(qty, int):
            v.quantity, v.method = max(qty, 0), "inventario esposto"


def leaked_quantity(html: str, variant_id: str) -> int | None:
    """Cerca ``inventory_quantity`` associato all'id variante nelle variabili del tema."""
    if not variant_id:
        return None
    vid = re.escape(variant_id)
    qty = r"[\"']?inventory_?quantity[\"']?\s*[:=]\s*[\"']?(-?\d+)"
    for pattern in (
        rf"\b{vid}\b[\"']?[^{{}}]{{0,400}}?{qty}",
        rf"{qty}[^{{}}]{{0,400}}?[\"']?id[\"']?\s*[:=]\s*[\"']?{vid}\b",
    ):
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return max(int(match.group(1)), 0)
    return None


async def _fill_from_html(client, url: str, variants: list[VariantStock]) -> None:
    try:
        html = await get_text(client, url)
    except SiteError:
        return
    if not html:
        return
    for v in _missing(variants):
        qty = leaked_quantity(html, v.ref)
        if qty is not None:
            v.quantity, v.method = qty, "inventario esposto"


async def _cart_probe(client_factory: ClientFactory, base: str, variant_id: str) -> int | None:
    """Stock di una variante letto dal limite del carrello (sessione anonima e isolata)."""
    if not variant_id:
        return None
    try:
        async with client_factory() as cart:
            added = await cart.post(f"{base}/cart/add.js", json={"id": int(variant_id), "quantity": 1})
            if added.status_code != 200:
                return None
            changed = await cart.post(
                f"{base}/cart/change.js", json={"id": variant_id, "quantity": PROBE_QUANTITY}
            )
            await cart.post(f"{base}/cart/clear.js")
            if changed.status_code != 200:
                return None
            for item in changed.json().get("items", []):
                if str(item.get("variant_id") or item.get("id")) == variant_id:
                    qty = int(item.get("quantity", 0))
                    # 9999 accettati = stock non tracciato: il numero non è significativo.
                    return qty if qty < PROBE_QUANTITY else None
    except (httpx.HTTPError, ValueError):
        return None
    return None


async def looks_like_shopify(client, base: str) -> bool:
    try:
        response = await fetch(client, f"{base}/products.json", params={"limit": 1})
    except SiteError:
        return False
    if response is None:
        return False
    try:
        return "products" in response.json()
    except ValueError:
        return False

