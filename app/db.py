"""Archivio SQLite locale: anagrafica siti, storico ricerche e risultati."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .models import Site, SiteOutcome

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL UNIQUE,
    platform TEXT NOT NULL DEFAULT 'auto',
    active INTEGER NOT NULL DEFAULT 1,
    cart_probe INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    config TEXT NOT NULL DEFAULT '{}',
    last_checked TEXT,
    last_status TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    codes TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS search_log (
    id INTEGER PRIMARY KEY,
    search_id INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    site_name TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY,
    search_id INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    site_id INTEGER,
    site_name TEXT NOT NULL,
    product_title TEXT NOT NULL,
    product_url TEXT NOT NULL,
    image TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT '',
    size TEXT NOT NULL,
    quantity INTEGER,
    available INTEGER,
    price REAL,
    variant_sku TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT ''
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def clean_url(url: str) -> str:
    url = (url or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    return url.rstrip("/")


def name_from_url(url: str) -> str:
    host = urlparse(url).netloc
    return host[4:] if host.startswith("www.") else host


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # --- siti -------------------------------------------------------------

    @staticmethod
    def _site(row: sqlite3.Row) -> Site:
        return Site(
            id=row["id"],
            name=row["name"],
            base_url=row["base_url"],
            platform=row["platform"],
            active=bool(row["active"]),
            cart_probe=bool(row["cart_probe"]),
            notes=row["notes"],
            config=json.loads(row["config"] or "{}"),
            last_checked=row["last_checked"],
            last_status=row["last_status"],
        )

    def list_sites(self, only_active: bool = False) -> list[Site]:
        sql = "SELECT * FROM sites" + (" WHERE active = 1" if only_active else "") + " ORDER BY name COLLATE NOCASE"
        with self.connect() as con:
            return [self._site(r) for r in con.execute(sql)]

    def get_site(self, site_id: int) -> Site | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
        return self._site(row) if row else None

    def save_site(self, site: Site) -> Site:
        site.base_url = clean_url(site.base_url)
        site.name = site.name.strip() or name_from_url(site.base_url)
        config = json.dumps({k: v for k, v in site.config.items() if v not in (None, "")})
        values = (site.name, site.base_url, site.platform, int(site.active), int(site.cart_probe), site.notes, config)
        with self.connect() as con:
            if site.id is None:
                cur = con.execute(
                    "INSERT INTO sites (name, base_url, platform, active, cart_probe, notes, config, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    values + (now(),),
                )
                site.id = cur.lastrowid
            else:
                con.execute(
                    "UPDATE sites SET name=?, base_url=?, platform=?, active=?, cart_probe=?, notes=?, config=?"
                    " WHERE id=?",
                    values + (site.id,),
                )
        return site

    def import_sites(self, text: str) -> tuple[int, int]:
        """Importa righe "url" oppure "nome;url". Restituisce (aggiunti, già presenti)."""
        existing = {s.base_url for s in self.list_sites()}
        added = skipped = 0
        for line in (text or "").splitlines():
            parts = [p.strip() for p in line.replace("\t", ";").split(";") if p.strip()]
            if not parts:
                continue
            name, url = (parts[0], parts[1]) if len(parts) > 1 else ("", parts[0])
            url = clean_url(url)
            if url in existing:
                skipped += 1
                continue
            self.save_site(Site(name=name, base_url=url))
            existing.add(url)
            added += 1
        return added, skipped

    def delete_site(self, site_id: int) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM sites WHERE id = ?", (site_id,))

    def set_site_status(self, site_id: int, platform: str, status: str) -> None:
        with self.connect() as con:
            con.execute(
                "UPDATE sites SET platform = ?, last_status = ?, last_checked = ? WHERE id = ?",
                (platform, status, now(), site_id),
            )

    # --- ricerche ---------------------------------------------------------

    def save_search(self, codes: list[str], outcomes: list[SiteOutcome]) -> int:
        with self.connect() as con:
            search_id = con.execute(
                "INSERT INTO searches (created_at, codes) VALUES (?, ?)", (now(), "\n".join(codes))
            ).lastrowid
            for o in outcomes:
                found = sum(len(h.variants) for h in o.hits)
                message = o.error or (f"{len(o.hits)} prodotti, {found} taglie" if o.hits else "nessun prodotto trovato")
                con.execute(
                    "INSERT INTO search_log (search_id, code, site_name, status, message) VALUES (?, ?, ?, ?, ?)",
                    (search_id, o.code, o.site.name, o.status, message),
                )
                for hit in o.hits:
                    for v in hit.variants:
                        con.execute(
                            "INSERT INTO results (search_id, code, site_id, site_name, product_title, product_url,"
                            " image, currency, size, quantity, available, price, variant_sku, method)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                search_id, o.code, o.site.id, o.site.name, hit.title, hit.url, hit.image,
                                hit.currency, v.size, v.quantity, None if v.available is None else int(v.available),
                                v.price, v.sku, v.method,
                            ),
                        )
        return search_id

    def get_search(self, search_id: int):
        with self.connect() as con:
            search = con.execute("SELECT * FROM searches WHERE id = ?", (search_id,)).fetchone()
            if not search:
                return None, [], []
            log = con.execute(
                "SELECT * FROM search_log WHERE search_id = ?"
                " ORDER BY code, CASE status WHEN 'ok' THEN 0 WHEN 'errore' THEN 1 ELSE 2 END, site_name",
                (search_id,),
            ).fetchall()
            rows = con.execute("SELECT * FROM results WHERE search_id = ? ORDER BY code, site_name, id", (search_id,)).fetchall()
        return search, log, rows

    def recent_searches(self, limit: int = 15):
        with self.connect() as con:
            return con.execute(
                "SELECT s.*, (SELECT COALESCE(SUM(quantity), 0) FROM results r WHERE r.search_id = s.id) AS pieces"
                " FROM searches s ORDER BY s.id DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def delete_search(self, search_id: int) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM searches WHERE id = ?", (search_id,))
