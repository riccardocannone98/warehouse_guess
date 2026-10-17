"""Negozi finti serviti tramite httpx.MockTransport (nessun accesso a internet)."""
from __future__ import annotations

import json

import httpx

SHOP = "https://shop.example"
WOO = "https://woo.example"
GENERIC = "https://atelier.example"
BLOCKED = "https://blocked.example"

SHOPIFY_PRODUCT_JS = {
    "id": 1,
    "title": "Nike Dunk Low Retro White Black",
    "handle": "nike-dunk-low-retro-white-black",
    "description": "Style code: DD1391-100",
    "tags": ["nike", "dunk"],
    "featured_image": "//cdn.shop.example/dunk.jpg",
    "options": [{"name": "Taglia", "position": 1, "values": ["40", "42.5", "44"]}],
    "variants": [
        {"id": 101, "title": "40", "option1": "40", "sku": "DD1391-100-40", "available": True, "price": 11999},
        {"id": 102, "title": "42.5", "option1": "42.5", "sku": "DD1391-100-425", "available": True, "price": 11999},
        {"id": 103, "title": "44", "option1": "44", "sku": "DD1391-100-44", "available": False, "price": 11999},
    ],
}
# Il tema espone inventory_quantity solo per la variante 101.
SHOPIFY_HTML = """<html><script>var meta = {"variants":[{"id":101,"inventory_quantity":4,"name":"40"}]};</script></html>"""
CART_STOCK = {"102": 2}


def shopify_handler(request: httpx.Request, cart: dict) -> httpx.Response:
    path = request.url.path
    if path == "/search/suggest.json":
        products = []
        if "DD1391" in request.url.params.get("q", "").upper():
            products = [{"handle": SHOPIFY_PRODUCT_JS["handle"], "url": "/products/" + SHOPIFY_PRODUCT_JS["handle"]}]
        return httpx.Response(200, json={"resources": {"results": {"products": products}}})
    if path == f"/products/{SHOPIFY_PRODUCT_JS['handle']}.js":
        return httpx.Response(200, json=SHOPIFY_PRODUCT_JS)
    if path == f"/products/{SHOPIFY_PRODUCT_JS['handle']}.json":
        return httpx.Response(200, json={"product": {"variants": [{"id": v["id"]} for v in SHOPIFY_PRODUCT_JS["variants"]]}})
    if path == f"/products/{SHOPIFY_PRODUCT_JS['handle']}":
        return httpx.Response(200, text=SHOPIFY_HTML)
    if path == "/meta.json":
        return httpx.Response(200, json={"name": "Shop", "currency": "EUR"})
    if path == "/products.json":
        return httpx.Response(200, json={"products": []})
    if path == "/cart/add.js":
        body = json.loads(request.content)
        cart[str(body["id"])] = 1
        return httpx.Response(200, json={"id": body["id"]})
    if path == "/cart/change.js":
        body = json.loads(request.content)
        vid = str(body["id"])
        cart[vid] = min(body["quantity"], CART_STOCK.get(vid, 9999))
        return httpx.Response(200, json={"items": [{"variant_id": int(k), "quantity": q} for k, q in cart.items()]})
    if path == "/cart/clear.js":
        cart.clear()
        return httpx.Response(200, json={"items": []})
    return httpx.Response(404)


WOO_PRODUCT = {
    "id": 10,
    "name": "adidas Samba OG Cloud White",
    "sku": "B75806",
    "permalink": f"{WOO}/prodotto/samba-og/",
    "images": [{"src": f"{WOO}/samba.jpg"}],
    "prices": {"price": "10000", "currency_code": "EUR", "currency_minor_unit": 2},
    "variations": [
        {"id": 11, "attributes": [{"name": "Taglia", "value": "41-5"}]},
        {"id": 12, "attributes": [{"name": "Taglia", "value": "43"}]},
        {"id": 13, "attributes": [{"name": "Taglia", "value": "45"}]},
    ],
}
WOO_VARIATIONS = {
    11: {"id": 11, "is_in_stock": True, "low_stock_remaining": 1, "add_to_cart": {"maximum": 1}, "prices": WOO_PRODUCT["prices"]},
    12: {"id": 12, "is_in_stock": True, "low_stock_remaining": None, "add_to_cart": {"maximum": 7}, "prices": WOO_PRODUCT["prices"]},
    13: {"id": 13, "is_in_stock": False, "low_stock_remaining": None, "add_to_cart": {"maximum": 9999}, "prices": WOO_PRODUCT["prices"]},
}


def woo_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    api = "/wp-json/wc/store/v1/products"
    if path == api:
        term = request.url.params.get("search") or request.url.params.get("sku") or ""
        return httpx.Response(200, json=[WOO_PRODUCT] if "B75806" in term or request.url.params.get("per_page") == "1" else [])
    if path.startswith(api + "/"):
        vid = int(path.rsplit("/", 1)[1])
        return httpx.Response(200, json=WOO_VARIATIONS[vid]) if vid in WOO_VARIATIONS else httpx.Response(404)
    return httpx.Response(404)


GENERIC_SEARCH = """<html><body>
<a href="/it/scarpe/new-balance-9060-u9060aaa">New Balance 9060 U9060AAA</a>
<a href="/it/chi-siamo">Chi siamo</a>
</body></html>"""
GENERIC_PRODUCT = """<html><head>
<meta property="og:title" content="New Balance 9060 Sea Salt">
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":"BreadcrumbList"},{"@type":"ProductGroup","name":"New Balance 9060",
"productGroupID":"U9060AAA","image":"/img/9060.jpg","hasVariant":[
 {"@type":"Product","sku":"U9060AAA-42","size":"42","offers":{"@type":"Offer","price":"170.00","priceCurrency":"EUR","availability":"https://schema.org/InStock","inventoryLevel":{"@type":"QuantitativeValue","value":3}}},
 {"@type":"Product","sku":"U9060AAA-43","size":"43","offers":{"@type":"Offer","price":"170.00","priceCurrency":"EUR","availability":"https://schema.org/InStock"}},
 {"@type":"Product","sku":"U9060AAA-44","size":"44","offers":{"@type":"Offer","price":"170.00","priceCurrency":"EUR","availability":"https://schema.org/OutOfStock"}}
]}]}
</script></head><body><h1>New Balance 9060</h1></body></html>"""


def generic_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/search":
        return httpx.Response(200, text=GENERIC_SEARCH if "U9060AAA" in request.url.params.get("q", "") else "<html></html>")
    if path == "/it/scarpe/new-balance-9060-u9060aaa":
        return httpx.Response(200, text=GENERIC_PRODUCT)
    if path == "/it/chi-siamo":
        return httpx.Response(200, text="<html>Chi siamo</html>")
    return httpx.Response(404)


class FakeInternet:
    """Instrada le richieste verso il negozio finto giusto in base all'host."""

    def __init__(self):
        self.carts: list[dict] = []
        self.requests: list[httpx.Request] = []

    def handler(self, cart: dict):
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            origin = f"{request.url.scheme}://{request.url.host}"
            if origin == SHOP:
                return shopify_handler(request, cart)
            if origin == WOO:
                return woo_handler(request)
            if origin == GENERIC:
                return generic_handler(request)
            if origin == BLOCKED:
                return httpx.Response(403, text="Access denied")
            raise httpx.ConnectError("host sconosciuto", request=request)

        return handle

    def client_factory(self) -> httpx.AsyncClient:
        cart: dict = {}  # ogni client ha il suo carrello, come una sessione con cookie propri
        self.carts.append(cart)
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler(cart)), follow_redirects=True)
