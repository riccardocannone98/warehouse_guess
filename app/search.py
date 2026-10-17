"""Esegue la ricerca di più codici su più siti in parallelo."""
from __future__ import annotations

import asyncio

from .adapters import ADAPTERS, detect_platform
from .http import ClientFactory, SiteError, make_client
from .models import Site, SiteOutcome

MAX_PARALLEL_SITES = 4


async def run_search(
    sites: list[Site],
    codes: list[str],
    client_factory: ClientFactory = make_client,
) -> list[SiteOutcome]:
    semaphore = asyncio.Semaphore(MAX_PARALLEL_SITES)

    async def one_site(site: Site) -> list[SiteOutcome]:
        async with semaphore, client_factory() as client:
            outcomes = []
            if site.platform == "auto":
                try:
                    site.platform = await detect_platform(client, site.base_url)
                except SiteError as exc:
                    return [SiteOutcome(site, code, error=str(exc)) for code in codes]
            adapter = ADAPTERS[site.platform]
            # Codici in sequenza sullo stesso sito, per non sovraccaricarlo.
            for code in codes:
                outcome = SiteOutcome(site, code)
                try:
                    outcome.hits = await adapter(client, site, code, client_factory)
                except SiteError as exc:
                    outcome.error = str(exc)
                except Exception as exc:  # un sito con dati anomali non deve fermare gli altri
                    outcome.error = f"errore inatteso: {exc.__class__.__name__}: {exc}"
                outcomes.append(outcome)
            return outcomes

    per_site = await asyncio.gather(*(one_site(site) for site in sites))
    return [outcome for outcomes in per_site for outcome in outcomes]
