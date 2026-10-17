"""Dati della dashboard: ultima rilevazione per codice, andamento, taglie, stato siti."""
from __future__ import annotations

from .db import Database
from .sku import normalize, size_key

TREND_POINTS = 8
SPARK_W, SPARK_H = 96, 26


def sparkline(values: list[int]) -> dict | None:
    """Coordinate SVG di una sparkline (una sola serie: pezzi per rilevazione)."""
    if len(values) < 2:
        return None
    top = max(values) or 1
    step = SPARK_W / (len(values) - 1)
    points = [(round(i * step, 1), round(SPARK_H - 3 - (v / top) * (SPARK_H - 6), 1)) for i, v in enumerate(values)]
    return {"points": " ".join(f"{x},{y}" for x, y in points), "last": points[-1]}


def build_dashboard(db: Database) -> dict:
    catalog = db.catalog_by_code()
    sites = db.list_sites()

    # Rilevazioni raggruppate per codice normalizzato ("DD1391 100" = "DD1391-100").
    by_code: dict[str, list] = {}
    for snap in db.snapshots():
        by_code.setdefault(normalize(snap["code"]), []).append(snap)

    codes = []
    for norm, snaps in by_code.items():
        latest = snaps[-1]
        trend = [s["pieces"] for s in snaps[-TREND_POINTS:]]
        item = catalog.get(norm)
        codes.append(
            {
                "code": latest["code"],
                "label": f"{item['brand']} {item['model']}" if item else "",
                "colorway": item["colorway"] if item else "",
                "pieces": latest["pieces"],
                "sites_in_stock": latest["sites_in_stock"],
                "sizes_in_stock": latest["sizes_in_stock"],
                "best_price": latest["best_price"],
                "currency": latest["currency"] or "",
                "checked_at": latest["created_at"],
                "search_id": latest["search_id"],
                "trend": trend,
                "trend_dates": [s["created_at"][:16].replace("T", " ") for s in snaps[-TREND_POINTS:]],
                "spark": sparkline(trend),
                "delta": trend[-1] - trend[-2] if len(trend) > 1 else None,
            }
        )
    codes.sort(key=lambda c: (-c["pieces"], c["code"]))
    max_pieces = max((c["pieces"] for c in codes), default=0) or 1
    for c in codes:
        c["bar"] = round(100 * c["pieces"] / max_pieces, 1)

    # Taglie: somma dei pezzi nell'ultima rilevazione di ogni codice.
    latest_pairs = [(c["search_id"], c["code"]) for c in codes]
    size_totals: dict[str, int] = {}
    for r in db.results_for(latest_pairs):
        if r["quantity"]:
            size_totals[r["size"]] = size_totals.get(r["size"], 0) + r["quantity"]
    max_size = max(size_totals.values(), default=0) or 1
    sizes = [
        {"size": s, "pieces": size_totals[s], "bar": round(100 * size_totals[s] / max_size, 1)}
        for s in sorted(size_totals, key=size_key)
    ]

    health = db.site_health()
    site_rows = []
    for site in sites:
        h = health.get(site.name)
        total = h["total"] if h else 0
        site_rows.append(
            {
                "site": site,
                "ok": h["ok"] if h else 0,
                "empty": h["empty"] if h else 0,
                "errors": h["errors"] if h else 0,
                "total": total,
                "error_rate": round(100 * h["errors"] / total) if total else None,
            }
        )
    site_rows.sort(key=lambda r: (not r["site"].active, -(r["errors"] or 0), r["site"].name.lower()))

    return {
        "kpi": {
            "sites_active": sum(1 for s in sites if s.active),
            "sites_total": len(sites),
            "catalog": len(catalog),
            "searches": db.search_count(),
            "codes_tracked": len(codes),
            "pieces": sum(c["pieces"] for c in codes),
            "codes_in_stock": sum(1 for c in codes if c["pieces"] or c["sites_in_stock"]),
        },
        "codes": codes,
        "sizes": sizes,
        "sites": site_rows,
        "recent": db.recent_searches(8),
    }
