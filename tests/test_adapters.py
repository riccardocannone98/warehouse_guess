import asyncio

from app.adapters import detect_platform
from app.adapters.generic import parse_product_page
from app.adapters.shopify import leaked_quantity
from app.models import Site
from app.search import run_search
from app.sku import normalize

from .fakes import BLOCKED, GENERIC, SHOP, WOO, FakeInternet


def sizes(hit):
    return {v.size: (v.quantity, v.available, v.method) for v in hit.variants}


def search(site, code):
    net = FakeInternet()
    return asyncio.run(run_search([site], [code], net.client_factory))[0], net


def test_shopify_uses_exposed_inventory_and_availability():
    outcome, _ = search(Site(id=1, name="Shop", base_url=SHOP, platform="shopify"), "dd1391 100")
    assert outcome.status == "ok"
    hit = outcome.hits[0]
    assert hit.title == "Nike Dunk Low Retro White Black"
    assert hit.price == 119.99 and hit.currency == "EUR"
    assert hit.image == "https://cdn.shop.example/dunk.jpg"
    assert sizes(hit) == {
        "40": (4, True, "inventario esposto"),
        "42.5": (None, True, "solo disponibilità"),
        "44": (0, False, "esaurito"),
    }


def test_shopify_cart_probe_reads_stock_and_empties_cart():
    outcome, net = search(Site(id=1, name="Shop", base_url=SHOP, platform="shopify", cart_probe=True), "DD1391-100")
    assert sizes(outcome.hits[0])["42.5"] == (2, True, "probe carrello")
    # La sola variante senza numero viene sondata, in una sessione separata poi svuotata.
    assert len(net.carts) == 2 and net.carts[1] == {}


def test_woocommerce_store_api_quantities():
    outcome, _ = search(Site(id=2, name="Woo", base_url=WOO, platform="woocommerce"), "B75806")
    hit = outcome.hits[0]
    assert hit.currency == "EUR" and hit.price == 100.0
    assert sizes(hit) == {
        "41.5": (1, True, "store api"),
        "43": (7, True, "store api"),
        "45": (0, False, "esaurito"),
    }


def test_generic_jsonld_product_group():
    outcome, _ = search(Site(id=3, name="Atelier", base_url=GENERIC, platform="generic"), "U9060AAA")
    hit = outcome.hits[0]
    assert hit.title == "New Balance 9060 Sea Salt"
    assert hit.url == f"{GENERIC}/it/scarpe/new-balance-9060-u9060aaa"
    assert hit.image == f"{GENERIC}/img/9060.jpg"
    assert hit.currency == "EUR"
    assert sizes(hit) == {
        "42": (3, True, "dati strutturati"),
        "43": (None, True, "solo disponibilità"),
        "44": (0, False, "esaurito"),
    }


def test_generic_custom_selectors():
    html = """<h1>Air Jordan 1 FD1437-612</h1>
    <ul><li class="size" data-size="42" data-stock="5">42</li>
        <li class="size disabled" data-size="43">43</li>
        <li class="size" data-size="44" title="Solo 1 rimasto">44</li></ul>"""
    cfg = {"variant_selector": "li.size", "size_attr": "data-size", "qty_attr": "data-stock"}
    hit = parse_product_page(html, "https://x.example/p", cfg, normalize("FD1437-612"))
    assert sizes(hit) == {
        "42": (5, True, "selettore personalizzato"),
        "43": (0, False, "esaurito"),
        "44": (1, True, "selettore personalizzato"),
    }


def test_generic_woocommerce_variations_form():
    html = """<p>SKU: IE3438</p><form class="variations_form" data-product_variations='[
      {"attributes":{"attribute_pa_taglia":"42-5"},"max_qty":3,"is_in_stock":true,"display_price":120,"variation_id":5},
      {"attributes":{"attribute_pa_taglia":"44"},"max_qty":"","is_in_stock":true,"availability_html":"<p>Solo 2 disponibili</p>","display_price":120},
      {"attributes":{"attribute_pa_taglia":"45"},"max_qty":"","is_in_stock":false,"display_price":120}]'></form>"""
    hit = parse_product_page(html, "https://x.example/p", {}, normalize("IE3438"))
    assert sizes(hit) == {
        "42.5": (3, True, "pagina prodotto"),
        "44": (2, True, "pagina prodotto"),
        "45": (0, False, "esaurito"),
    }


def test_page_without_code_is_ignored():
    html = '<script type="application/ld+json">{"@type":"Product","name":"Altro","offers":{"availability":"InStock"}}</script>'
    assert parse_product_page(html, "https://x.example/p", {}, normalize("DD1391-100")) is None


def test_leaked_quantity_both_orders():
    assert leaked_quantity('{"id": 555, "inventory_quantity": 7}', "555") == 7
    assert leaked_quantity("{inventory_quantity: -2, id: 555}", "555") == 0
    assert leaked_quantity('{"id": 5550, "inventory_quantity": 7}', "555") is None


def test_blocked_site_reports_error_and_others_continue():
    net = FakeInternet()
    sites = [
        Site(id=1, name="Shop", base_url=SHOP, platform="shopify"),
        Site(id=9, name="Bloccato", base_url=BLOCKED, platform="shopify"),
    ]
    outcomes = asyncio.run(run_search(sites, ["DD1391-100"], net.client_factory))
    by_site = {o.site.name: o for o in outcomes}
    assert by_site["Shop"].status == "ok"
    assert by_site["Bloccato"].status == "errore" and "403" in by_site["Bloccato"].error


def test_not_found_is_empty_not_error():
    outcome, _ = search(Site(id=2, name="Woo", base_url=WOO, platform="woocommerce"), "ZZ0000-000")
    assert outcome.status == "vuoto"


def test_detect_platform():
    net = FakeInternet()

    async def detect(url):
        async with net.client_factory() as client:
            return await detect_platform(client, url)

    assert asyncio.run(detect(SHOP)) == "shopify"
    assert asyncio.run(detect(WOO)) == "woocommerce"
    assert asyncio.run(detect(GENERIC)) == "generic"


def test_blocked_site_keeps_auto_platform():
    net = FakeInternet()
    site = Site(id=9, name="Bloccato", base_url=BLOCKED)
    outcome = asyncio.run(run_search([site], ["DD1391-100"], net.client_factory))[0]
    assert outcome.status == "errore" and site.platform == "auto"
