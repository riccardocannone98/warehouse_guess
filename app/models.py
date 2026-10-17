"""Strutture dati condivise: siti censiti e risultati di disponibilità."""
from __future__ import annotations

from dataclasses import dataclass, field

PLATFORMS = ("auto", "shopify", "woocommerce", "generic")


@dataclass
class Site:
    name: str
    base_url: str
    platform: str = "auto"
    active: bool = True
    cart_probe: bool = False
    notes: str = ""
    config: dict = field(default_factory=dict)
    id: int | None = None
    last_checked: str | None = None
    last_status: str | None = None


@dataclass
class VariantStock:
    """Una taglia di un prodotto su un sito."""

    size: str
    quantity: int | None = None  # pezzi a magazzino, None = numero non esposto dal sito
    available: bool | None = None  # None = disponibilità non nota
    sku: str = ""
    price: float | None = None
    method: str = ""  # come è stata ricavata la quantità
    ref: str = ""  # id interno della variante sul sito (uso tecnico)


@dataclass
class ProductHit:
    title: str
    url: str
    image: str = ""
    price: float | None = None
    currency: str = ""
    variants: list[VariantStock] = field(default_factory=list)


@dataclass
class SiteOutcome:
    """Esito della ricerca di un codice su un sito."""

    site: Site
    code: str
    hits: list[ProductHit] = field(default_factory=list)
    error: str = ""

    @property
    def status(self) -> str:
        if self.error:
            return "errore"
        return "ok" if self.hits else "vuoto"
