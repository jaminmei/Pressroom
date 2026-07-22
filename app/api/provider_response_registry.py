"""Registry for optional provider response enrichment plugins."""

from __future__ import annotations

from collections.abc import Callable

ProviderResponseEnricher = Callable[[], dict[str, str] | None]


class ProviderResponseEnricherRegistry:
    def __init__(self) -> None:
        self._enrichers: dict[str, ProviderResponseEnricher] = {}

    def register(self, auth_type: str, enricher: ProviderResponseEnricher) -> None:
        self._enrichers[auth_type] = enricher

    def enrich(self, auth_type: str) -> dict[str, str] | None:
        enricher = self._enrichers.get(auth_type)
        return enricher() if enricher is not None else None


provider_response_enrichers = ProviderResponseEnricherRegistry()
