"""
app/providers/discover.py
------------------------
Reusable provider discovery logic.

Extracted from the API handler so that startup seed auto-discover
and the ``POST /{id}/discover`` endpoint share the same logic.

Side effects:
    ``discover_provider()`` persists ``config_schema`` to the database
    (via ``store.update_provider()``) and registers discovered models.
    It is NOT a read-only operation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.providers.auth import AuthResolver, CredentialKind
from app.providers.models import (
    ApiStyle,
    ModelProviderRow,
    ModelProviderUpdate,
    ProviderModelCreate,
    ProviderType,
)
from app.providers.store import ProviderStore
from app.services.ssrf_transport import provider_ssrf_safe_client

logger = logging.getLogger(__name__)

# Standard timeout for engine HTTP requests.
_DISCOVER_TIMEOUT = 5.0


class DiscoverResult:
    """Lightweight container returned by :func:`discover_provider`."""

    __slots__ = (
        "discovered",
        "added",
        "skipped",
        "config_schema",
        "engine_name",
        "discovery_supported",
        "message",
    )

    def __init__(self) -> None:
        self.discovered: list[dict[str, Any]] = []
        self.added: int = 0
        self.skipped: int = 0
        self.config_schema: dict[str, Any] | None = None
        self.engine_name: str | None = None
        self.discovery_supported: bool = True
        self.message: str | None = None


class ProviderAuthenticationError(RuntimeError):
    """Raised when discovery cannot resolve configured credentials."""


def _provider_ssl_verify(provider: ModelProviderRow) -> bool:
    if not provider.extra_config:
        return True
    try:
        parsed = (
            json.loads(provider.extra_config)
            if isinstance(provider.extra_config, str)
            else provider.extra_config
        )
    except (ValueError, TypeError):
        return True
    return bool(parsed.get("ssl_verify", True)) if isinstance(parsed, dict) else True


async def _discovery_headers(
    row: ModelProviderRow,
    auth_resolver: AuthResolver | None,
) -> dict[str, str]:
    if auth_resolver is None:
        return {}
    try:
        auth = await auth_resolver.resolve(row)
    except Exception as exc:
        raise ProviderAuthenticationError("Provider authentication could not be resolved") from exc
    if auth.kind == CredentialKind.none:
        return {}
    assert auth.credential is not None
    return {"Authorization": f"Bearer {auth.credential}"}


async def discover_provider(
    row: ModelProviderRow,
    store: ProviderStore,
    *,
    timeout: float = _DISCOVER_TIMEOUT,
    auth_resolver: AuthResolver | None = None,
    client: httpx.AsyncClient | None = None,
) -> DiscoverResult:
    """Discover models / config from a provider's engine service.

    * ``openai_compatible`` → ``GET {base_url}/models``
    * ``engine_service``    → ``GET {base_url}/config``

    On success the provider's ``config_schema`` column is updated (for
    engine_service providers) and any new models are registered.

    Raises :class:`httpx.HTTPError` on connection failure so callers
    can decide how to handle it.
    """
    result = DiscoverResult()

    if (
        row.provider_type == ProviderType.openai_compatible
        and row.api_style == ApiStyle.azure_openai
    ):
        result.discovery_supported = False
        result.message = "Azure OpenAI deployments must be added manually."
        return result

    headers = await _discovery_headers(row, auth_resolver)
    http_client = client or provider_ssrf_safe_client(
        timeout=timeout,
        verify=_provider_ssl_verify(row),
    )
    owns_client = client is None
    try:
        if row.provider_type == ProviderType.openai_compatible:
            resp = await http_client.get(f"{row.base_url}/models", headers=headers)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            candidates: list[dict[str, str]] = [
                {"model_id": item["id"], "display_name": item["id"]}
                for item in data
                if isinstance(item, dict) and "id" in item
            ]
        else:
            # engine_service: /config → engine_name + config_schema
            resp = await http_client.get(f"{row.base_url}/config", headers=headers)
            resp.raise_for_status()
            payload = resp.json()
            config_data: dict[str, Any] | None = payload.get("config_schema")
            result.config_schema = config_data
            engine_name: str = payload.get("engine_name") or row.name
            result.engine_name = engine_name
            candidates = [{"model_id": engine_name, "display_name": row.name}]

            # Persist config_schema into the provider record
            store.update_provider(
                str(row.id),
                ModelProviderUpdate(config_schema=config_data),
            )
    finally:
        if owns_client:
            await http_client.aclose()

    for candidate in candidates:
        try:
            model = store.add_model(
                str(row.id),
                ProviderModelCreate(
                    model_id=candidate["model_id"],
                    display_name=candidate["display_name"],
                ),
            )
            result.added += 1
            result.discovered.append(model.model_dump())
        except ValueError:
            result.skipped += 1

    return result


async def discover_seed_configs(store: ProviderStore) -> int:
    """Auto-discover config_schema for seed providers that have none.

    Called once at application startup after seeding. For each
    ``engine_service`` provider with ``config_schema IS NULL``,
    attempts ``GET {base_url}/config`` and stores the result.

    Failures are logged but **not** raised — the engine container may
    not be ready yet when the backend starts.

    Returns the number of providers whose config_schema was successfully
    populated.
    """
    all_providers = store.list_providers(enabled_only=False)
    engine_service_no_schema = [
        p
        for p in all_providers
        if p.provider_type == ProviderType.engine_service and p.config_schema is None
    ]

    if not engine_service_no_schema:
        return 0

    populated = 0
    for row in engine_service_no_schema:
        try:
            result = await discover_provider(row, store)
            populated += 1
            logger.info(
                "Auto-discovered provider config id=%s model_count=%d schema=%s",
                row.id,
                result.added,
                "yes" if result.config_schema else "no",
            )
        except Exception as exc:
            logger.warning(
                "Auto-discover failed for provider id=%s error_type=%s",
                row.id,
                type(exc).__name__,
            )

    return populated
