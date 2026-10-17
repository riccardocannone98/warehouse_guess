"""Applicazione web locale (FastAPI): dashboard, ricerca, risultati, catalogo codici, anagrafica siti."""
from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .adapters import detect_platform
from .db import Database, clean_url
from .http import ClientFactory, SiteError, make_client
from .models import PLATFORMS, Site
from .dashboard import build_dashboard
from .report import build_matrix, export_xlsx
from .search import run_search
from .sku import normalize, parse_codes

APP_DIR = Path(__file__).parent
DEFAULT_DB = APP_DIR.parent / "data" / "warehouse.db"
CONFIG_FIELDS = ("search_url", "product_link_selector", "variant_selector", "size_attr", "qty_attr", "qty_regex", "currency", "max_pages")
PLATFORM_LABELS = {
    "auto": "Rilevamento automatico",
    "shopify": "Shopify",
    "woocommerce": "WooCommerce",
    "generic": "Generico (JSON-LD / selettori)",
}


def asset_version() -> str:
    return str(max(int(f.stat().st_mtime) for f in (APP_DIR / "static").iterdir()))


def create_app(db_path: str | Path | None = None, client_factory: ClientFactory = make_client) -> FastAPI:
    db = Database(db_path or os.environ.get("WAREHOUSE_DB", DEFAULT_DB))
    app = FastAPI(title="Warehouse Guess")
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=APP_DIR / "templates")
    templates.env.globals["PLATFORM_LABELS"] = PLATFORM_LABELS
    templates.env.globals["normalize"] = normalize
    # Versione dei file statici nei link: a ogni aggiornamento il browser scarica il CSS nuovo
    # invece di usare quello vecchio in cache.
    templates.env.globals["asset_version"] = asset_version()

    def redirect(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    def search_page(request: Request, codes: str = "", error: str = "", status_code: int = 200):
        catalog = db.list_catalog()
        return templates.TemplateResponse(
            request,
            "search.html",
            {
                "sites": db.list_sites(only_active=True),
                "catalog": catalog,
                "brands": sorted({c["brand"] for c in catalog}, key=str.lower),
                "recent": db.recent_searches(6),
                "codes": codes,
                "error": error,
            },
            status_code=status_code,
        )

    # --- dashboard e ricerca ------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        return templates.TemplateResponse(request, "dashboard.html", build_dashboard(db))

    @app.get("/search", response_class=HTMLResponse)
    def search_form(request: Request):
        return search_page(request, "\n".join(parse_codes("\n".join(request.query_params.getlist("codes")))))

    @app.post("/search")
    async def search(request: Request):
        form = await request.form()
        raw = "\n".join(str(v) for v in form.getlist("codes"))
        codes = parse_codes(raw)
        chosen = {int(i) for i in form.getlist("site_ids")}
        sites = [s for s in db.list_sites(only_active=True) if not chosen or s.id in chosen]
        if not codes or not sites:
            error = "Inserisci o seleziona almeno un codice prodotto." if not codes else "Nessun sito attivo selezionato."
            return search_page(request, raw, error, status_code=400)
        outcomes = await run_search(sites, codes, client_factory)
        for site in sites:
            errors = [o.error for o in outcomes if o.site is site and o.error]
            db.set_site_status(site.id, site.platform, errors[0] if errors else "ok")
        return redirect(f"/results/{db.save_search(codes, outcomes)}")

    @app.get("/results/{search_id}", response_class=HTMLResponse)
    def results(request: Request, search_id: int):
        search_row, log, rows = db.get_search(search_id)
        if not search_row:
            raise HTTPException(404, "Ricerca non trovata")
        return templates.TemplateResponse(
            request,
            "results.html",
            {
                "search": search_row,
                "log": log,
                "blocks": build_matrix(rows),
                "codes": search_row["codes"].split("\n"),
                "catalog": db.catalog_by_code(),
            },
        )

    @app.get("/results/{search_id}/export.xlsx")
    def results_xlsx(search_id: int):
        search_row, log, rows = db.get_search(search_id)
        if not search_row:
            raise HTTPException(404, "Ricerca non trovata")
        return Response(
            export_xlsx(search_row, log, rows),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="disponibilita_{search_id}.xlsx"'},
        )

    @app.post("/results/{search_id}/delete")
    def results_delete(search_id: int):
        db.delete_search(search_id)
        return redirect("/")

    # --- catalogo codici ---------------------------------------------------

    @app.get("/catalog", response_class=HTMLResponse)
    def catalog(request: Request, msg: str = ""):
        items = db.list_catalog()
        return templates.TemplateResponse(
            request,
            "catalog.html",
            {"items": items, "brands": sorted({c["brand"] for c in items}, key=str.lower), "msg": msg},
        )

    @app.post("/catalog")
    def catalog_add(brand: str = Form(""), model: str = Form(""), colorway: str = Form(""), code: str = Form("")):
        return redirect("/catalog?" + urlencode({"msg": db.save_catalog_item(brand, model, colorway, code)}))

    @app.post("/catalog/import")
    def catalog_import(text: str = Form("")):
        items = []
        for line in filter(str.strip, text.splitlines()):
            parts = [p.strip() for p in line.replace("\t", ";").split(";")]
            if len(parts) >= 4:
                items.append({"brand": parts[0], "model": parts[1], "colorway": parts[2], "code": parts[3]})
            else:
                # Righe con meno di 3 campi arrivano incomplete e vengono contate come scartate.
                items.append({"brand": parts[0], "model": parts[1] if len(parts) > 1 else "", "code": parts[-1] if len(parts) == 3 else ""})
        added, skipped = db.import_catalog(items)
        return redirect("/catalog?" + urlencode({"msg": f"Importati {added} codici ({skipped} già presenti o incompleti)"}))

    @app.get("/catalog/export.csv")
    def catalog_export():
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";")
        writer.writerow(["marca", "modello", "colorway", "codice"])
        for c in db.list_catalog():
            writer.writerow([c["brand"], c["model"], c["colorway"], c["code"]])
        return Response(
            out.getvalue().encode("utf-8-sig"),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="catalogo.csv"'},
        )

    @app.post("/catalog/{item_id}")
    def catalog_update(item_id: int, brand: str = Form(""), model: str = Form(""), colorway: str = Form(""), code: str = Form("")):
        return redirect("/catalog?" + urlencode({"msg": db.save_catalog_item(brand, model, colorway, code, item_id)}))

    @app.post("/catalog/{item_id}/delete")
    def catalog_delete(item_id: int):
        db.delete_catalog_item(item_id)
        return redirect("/catalog?msg=Codice+eliminato")

    # --- anagrafica siti --------------------------------------------------

    @app.get("/sites", response_class=HTMLResponse)
    def sites(request: Request, msg: str = ""):
        return templates.TemplateResponse(
            request, "sites.html", {"sites": db.list_sites(), "platforms": PLATFORMS, "msg": msg}
        )

    @app.get("/sites/new", response_class=HTMLResponse)
    def site_new(request: Request):
        return templates.TemplateResponse(request, "site_form.html", {"site": Site(name="", base_url=""), "platforms": PLATFORMS})

    @app.get("/sites/{site_id}/edit", response_class=HTMLResponse)
    def site_edit(request: Request, site_id: int):
        site = db.get_site(site_id)
        if not site:
            raise HTTPException(404, "Sito non trovato")
        return templates.TemplateResponse(request, "site_form.html", {"site": site, "platforms": PLATFORMS})

    async def site_from_form(request: Request, site_id: int | None) -> Site:
        form = await request.form()
        platform = str(form.get("platform", "auto"))
        if platform not in PLATFORMS:
            raise HTTPException(400, "Piattaforma non valida")
        base_url = clean_url(str(form.get("base_url", "")))
        if not base_url.startswith(("http://", "https://")) or "." not in base_url:
            raise HTTPException(400, "URL del sito non valido")
        return Site(
            id=site_id,
            name=str(form.get("name", "")),
            base_url=base_url,
            platform=platform,
            active=form.get("active") == "on",
            cart_probe=form.get("cart_probe") == "on",
            notes=str(form.get("notes", "")),
            config={f: str(form.get(f, "")).strip() for f in CONFIG_FIELDS},
        )

    @app.post("/sites")
    async def site_create(request: Request):
        site = await site_from_form(request, None)
        if any(s.base_url == site.base_url for s in db.list_sites()):
            return redirect("/sites?msg=Sito già presente in elenco")
        db.save_site(site)
        return redirect(f"/sites?msg=Aggiunto {site.name}")

    @app.post("/sites/import")
    def sites_import(text: str = Form("")):
        added, skipped = db.import_sites(text)
        return redirect(f"/sites?msg=Importati {added} siti ({skipped} già presenti)")

    @app.post("/sites/{site_id}")
    async def site_update(request: Request, site_id: int):
        if not db.get_site(site_id):
            raise HTTPException(404, "Sito non trovato")
        site = db.save_site(await site_from_form(request, site_id))
        return redirect(f"/sites?msg=Aggiornato {site.name}")

    @app.post("/sites/{site_id}/delete")
    def site_delete(site_id: int):
        db.delete_site(site_id)
        return redirect("/sites?msg=Sito eliminato")

    @app.post("/sites/{site_id}/toggle")
    def site_toggle(site_id: int):
        site = db.get_site(site_id)
        if not site:
            raise HTTPException(404, "Sito non trovato")
        site.active = not site.active
        db.save_site(site)
        return redirect("/sites")

    @app.post("/sites/{site_id}/detect")
    async def site_detect(site_id: int):
        site = db.get_site(site_id)
        if not site:
            raise HTTPException(404, "Sito non trovato")
        async with client_factory() as client:
            try:
                platform = await detect_platform(client, site.base_url)
                status = "ok"
            except SiteError as exc:
                platform, status = site.platform, str(exc)
        db.set_site_status(site_id, platform, status)
        return redirect(f"/sites?msg={site.name}: piattaforma {PLATFORM_LABELS[platform]}")

    @app.get("/sites/export.csv")
    def sites_export():
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";")
        writer.writerow(["nome", "url", "piattaforma", "attivo", "probe_carrello", "note"])
        for s in db.list_sites():
            writer.writerow([s.name, s.base_url, s.platform, int(s.active), int(s.cart_probe), s.notes])
        return Response(
            out.getvalue().encode("utf-8-sig"),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="siti.csv"'},
        )

    return app
