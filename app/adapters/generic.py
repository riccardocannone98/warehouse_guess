"""Adapter generico per siti non Shopify / WooCommerce.

1. Apre la pagina di ricerca del sito (``search_url`` con ``{code}``).
2. Segue i link ai prodotti che contengono il codice (o quelli indicati da
   ``product_link_selector``).
3. Sulla pagina prodotto legge, in ordine di priorità:
   - selettori personalizzati (``variant_selector`` + ``size_attr`` / ``qty_attr`` / ``qty_regex``);
   - il JSON delle varianti WooCommerce (``data-product_variations``);
   - i dati strutturati schema.org (JSON-LD ``Product`` / ``ProductGroup``).
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ..http import ClientFactory, SiteError, fetch, get_text
from ..models import ProductHit, Site, VariantStock
from ..sku import matches, normalize, qty_from_text

MAX_PRODUCTS = 5
PRODUCT_URL_HINTS = ("/product", "/prodott", "/p/", "/item", "/shop/", "/sneaker")
SIZE_ATTR_HINTS = ("size", "tagl", "misur", "talla", "taille")
OUT_OF_STOCK = ("outofstock", "soldout", "discontinued")


async def search(client: httpx.AsyncClient, site: Site, code: str, client_factory: ClientFactory) -> list[ProductHit]:
    cfg = site.config
    query = normalize(code)
    template = cfg.get("search_url") or f"{site.base_url}/search?q={{code}}"
    if "{code}" not in template:
        raise SiteError("l'URL di ricerca deve contenere {code}")
    response = await fetch(client, template.replace("{code}", quote_plus(code)))
    if response is None:
        raise SiteError("pagina di ricerca non trovata: controlla l'URL di ricerca del sito")

    # Alcuni siti, cercando un codice esatto, rimandano direttamente al prodotto.
    direct = parse_product_page(response.text, str(response.url), cfg, query)
    if direct:
        return [direct]

    hits: list[ProductHit] = []
    for link in product_links(response.text, str(response.url), cfg.get("product_link_selector"), query):
        try:
            html = await get_text(client, link)
        except SiteError:
            continue
        hit = parse_product_page(html or "", link, cfg, query)
        if hit:
            hits.append(hit)
    return hits


def product_links(html: str, page_url: str, selector: str | None, query: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.select(selector) if selector else soup.find_all("a", href=True)
    own_host = urlparse(page_url).netloc
    with_code: list[str] = []
    product_like: list[str] = []
    for a in anchors:
        href = a.get("href")
        if not href:
            continue
        url = urljoin(page_url, href).split("#")[0]
        if urlparse(url).netloc != own_host or url == page_url:
            continue
        if selector or matches(query, href, a.get_text(" ")):
            with_code.append(url)
        elif any(hint in url.lower() for hint in PRODUCT_URL_HINTS):
            product_like.append(url)
    links = with_code or product_like
    return list(dict.fromkeys(links))[:MAX_PRODUCTS]


def parse_product_page(html: str, url: str, cfg: dict, query: str) -> ProductHit | None:
    if not html or query not in normalize(html):
        return None
    soup = BeautifulSoup(html, "html.parser")
    ld_products = _jsonld_products(soup)

    variants = _custom_variants(soup, cfg) or _woo_variants(soup) or _jsonld_variants(ld_products)
    if not variants:
        return None

    ld = ld_products[0] if ld_products else {}
    title = _meta(soup, "og:title") or ld.get("name") or (soup.h1.get_text(strip=True) if soup.h1 else "")
    image = _meta(soup, "og:image") or _first(ld.get("image"))
    if isinstance(image, dict):
        image = image.get("url", "")
    prices = [v.price for v in variants if v.price is not None]
    return ProductHit(
        title=title,
        url=url,
        image=urljoin(url, image) if image else "",
        price=min(prices) if prices else None,
        currency=cfg.get("currency", "") or _ld_currency(ld),
        variants=variants,
    )


def _meta(soup: BeautifulSoup, prop: str) -> str:
    tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    return (tag.get("content") or "").strip() if tag else ""


def _first(value):
    return value[0] if isinstance(value, list) and value else value or ""


def _to_float(value) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


# --- selettori personalizzati -------------------------------------------------

def _custom_variants(soup: BeautifulSoup, cfg: dict) -> list[VariantStock]:
    selector = cfg.get("variant_selector")
    if not selector:
        return []
    size_attr, qty_attr, qty_regex = cfg.get("size_attr"), cfg.get("qty_attr"), cfg.get("qty_regex")
    variants = []
    for el in soup.select(selector):
        size = (el.get(size_attr) if size_attr else el.get_text(" ", strip=True)) or "?"
        qty = None
        if qty_attr and el.get(qty_attr) not in (None, ""):
            qty = _to_int(el.get(qty_attr))
        elif qty_regex:
            m = re.search(qty_regex, str(el), re.IGNORECASE)
            qty = _to_int(m.group(1)) if m else None
        if qty is None:
            qty = qty_from_text(el.get("title") or el.get("aria-label") or "")
        disabled = el.has_attr("disabled") or "disabled" in " ".join(el.get("class", [])).lower()
        available = (qty > 0) if qty is not None else (not disabled)
        variants.append(
            VariantStock(
                size=str(size).strip(),
                quantity=qty if qty is not None else (0 if disabled else None),
                available=available,
                method="selettore personalizzato" if qty is not None else ("esaurito" if disabled else "solo disponibilità"),
            )
        )
    return variants


def _to_int(value) -> int | None:
    try:
        return max(int(float(str(value).strip())), 0)
    except (TypeError, ValueError):
        return None


# --- WooCommerce (form varianti nella pagina) ----------------------------------

def _woo_variants(soup: BeautifulSoup) -> list[VariantStock]:
    form = soup.select_one("[data-product_variations]")
    if not form:
        return []
    try:
        data = json.loads(form["data-product_variations"])
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    variants = []
    for v in data:
        attrs = v.get("attributes") or {}
        size_key = next((k for k in attrs if any(h in k.lower() for h in SIZE_ATTR_HINTS)), None)
        size = attrs.get(size_key) if size_key else next(iter(attrs.values()), "?")
        in_stock = bool(v.get("is_in_stock"))
        qty = _to_int(v.get("max_qty")) if v.get("max_qty") not in (None, "") else None
        if qty is None:
            qty = qty_from_text(BeautifulSoup(v.get("availability_html") or "", "html.parser").get_text(" "))
        if qty is None and not in_stock:
            qty, method = 0, "esaurito"
        else:
            method = "pagina prodotto" if qty is not None else "solo disponibilità"
        variants.append(
            VariantStock(
                size=_slug_size(size),
                quantity=qty,
                available=in_stock,
                sku=v.get("sku") or "",
                price=_to_float(v.get("display_price")),
                method=method,
                ref=str(v.get("variation_id", "")),
            )
        )
    return variants


def _slug_size(size) -> str:
    """Gli slug WooCommerce scrivono "42-5" per la taglia 42.5."""
    text = str(size or "?")
    return text.replace("-", ".") if re.fullmatch(r"\d+-\d", text) else text


# --- schema.org JSON-LD ------------------------------------------------------

def _jsonld_products(soup: BeautifulSoup) -> list[dict]:
    found: list[dict] = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Product" in types or "ProductGroup" in types:
                found.append(node)
            elif "@graph" in node:
                walk(node["@graph"])

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            walk(json.loads(script.string or script.get_text() or ""))
        except ValueError:
            continue
    return found


def _availability(value) -> bool | None:
    if not value:
        return None
    text = str(value).lower().replace(" ", "")
    return not any(flag in text for flag in OUT_OF_STOCK)


def _inventory(offer: dict) -> int | None:
    level = offer.get("inventoryLevel")
    if isinstance(level, dict):
        level = level.get("value")
    return _to_int(level) if level not in (None, "") else None


def _offer_variant(offer: dict, size: str, sku: str = "") -> VariantStock:
    available = _availability(offer.get("availability"))
    qty = _inventory(offer)
    if qty is None and available is False:
        qty, method = 0, "esaurito"
    else:
        method = "dati strutturati" if qty is not None else "solo disponibilità"
    return VariantStock(
        size=size or "Unica",
        quantity=qty,
        available=available,
        sku=offer.get("sku") or sku,
        price=_to_float(offer.get("price") or offer.get("lowPrice")),
        method=method,
    )


def _size_of(node: dict) -> str:
    size = node.get("size")
    if isinstance(size, dict):
        size = size.get("name") or size.get("value")
    if size:
        return str(size)
    for prop in node.get("additionalProperty") or []:
        if isinstance(prop, dict) and any(h in str(prop.get("name", "")).lower() for h in SIZE_ATTR_HINTS):
            return str(prop.get("value", ""))
    return ""


def _jsonld_variants(products: list[dict]) -> list[VariantStock]:
    for product in products:
        variants: list[VariantStock] = []
        for child in product.get("hasVariant") or []:
            offers = child.get("offers") or {}
            offer = _first(offers) if isinstance(offers, list) else offers
            variants.append(_offer_variant(offer or {}, _size_of(child) or child.get("name", ""), child.get("sku", "")))
        if variants:
            return variants

        offers = product.get("offers") or []
        if isinstance(offers, dict):
            offers = offers.get("offers") or [offers]
        for offer in offers:
            item = offer.get("itemOffered") if isinstance(offer.get("itemOffered"), dict) else {}
            size = _size_of(offer) or _size_of(item) or (offer.get("name", "") if len(offers) > 1 else "")
            variants.append(_offer_variant(offer, size))
        if variants:
            return variants
    return []


def _ld_currency(ld: dict) -> str:
    nodes = [ld] + [v for v in ld.get("hasVariant") or [] if isinstance(v, dict)]
    for node in nodes:
        offers = node.get("offers") or {}
        offer = _first(offers) if isinstance(offers, list) else offers
        if isinstance(offer, dict) and offer.get("priceCurrency"):
            return offer["priceCurrency"]
    return ""
