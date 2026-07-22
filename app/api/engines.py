"""Engines REST API — ENGINE type metadata endpoints.

Provides read-only access to ENGINE type metadata from the code-level registry,
expanded with provider counts, health summaries, and provider lists.



"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.providers import ProviderManageDep, ProviderViewDep
from app.errors.error_response import CANONICAL_ERROR_RESPONSES
from app.providers.engine_registry import ENGINE_TYPES, EngineTypeMeta, get_engine_meta
from app.providers.store import ProviderStore
from app.services.workspace_access import ResolvedContext

router = APIRouter(
    prefix="/engines",
    tags=["engines"],
    responses=CANONICAL_ERROR_RESPONSES,
)


# ---------------------------------------------------------------------------
# Dependency injection (lazy — only needed for expanded endpoints)
# ---------------------------------------------------------------------------


async def _get_store(request: Request) -> ProviderStore:
    """Retrieve the ProviderStore from app.state."""
    store: ProviderStore | None = getattr(request.app.state, "provider_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Provider store not initialised")
    return store


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class EngineTypeResponse(BaseModel):
    """ENGINE type metadata response."""

    category: str
    display_name: str
    icon: str
    description: str
    default_provider_type: str
    supported_input_types: list[str]
    response_formats: list[str]
    allow_multiple_models: bool


class EnabledSummary(BaseModel):
    """Count of enabled providers for an engine category.

    Note: this is NOT a real health check — it only counts ``is_enabled``.
    For actual health status, use ``GET /engines/{category}/health``.
    """

    enabled: int
    total: int


class EngineWithProvidersResponse(BaseModel):
    """ENGINE type with provider counts and health summary."""

    category: str
    display_name: str
    icon: str
    description: str
    default_provider_type: str
    supported_input_types: list[str]
    response_formats: list[str]
    allow_multiple_models: bool
    provider_count: int = 0
    enabled_summary: EnabledSummary | None = None


class ProviderBriefResponse(BaseModel):
    """Brief provider info within an engine detail response."""

    id: str
    name: str
    is_enabled: bool
    is_default: bool
    config_schema: dict[str, Any] | None = None
    parameter_schema: dict[str, Any] | None = None


class EngineDetailResponse(BaseModel):
    """Full ENGINE detail with provider list."""

    category: str
    display_name: str
    icon: str
    description: str
    default_provider_type: str
    supported_input_types: list[str]
    response_formats: list[str]
    allow_multiple_models: bool
    provider_count: int = 0
    enabled_summary: EnabledSummary | None = None
    providers: list[ProviderBriefResponse] = []


class EngineListResponse(BaseModel):
    """List of all ENGINE types."""

    engines: list[EngineWithProvidersResponse]


class EngineHealthResponse(BaseModel):
    """Health check summary for all providers of an engine category."""

    category: str
    providers: list[dict[str, Any]]
    healthy_count: int
    total_count: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _meta_to_base(meta: EngineTypeMeta) -> dict[str, Any]:
    """Convert EngineTypeMeta to base response dict."""
    return {
        "category": meta.category,
        "display_name": meta.display_name,
        "icon": meta.icon,
        "description": meta.description,
        "default_provider_type": meta.default_provider_type,
        "supported_input_types": list(meta.supported_input_types),
        "response_formats": list(meta.response_formats),
        "allow_multiple_models": meta.allow_multiple_models,
    }


def _active_workspace_id(context: ResolvedContext) -> str:
    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return context.workspace_id


@router.get("", response_model=EngineListResponse)
async def list_engines(
    request: Request,
    permission: ProviderViewDep,
) -> EngineListResponse:
    """Return all registered ENGINE types with metadata, provider counts, and health summaries."""
    store = await _get_store(request)

    engines: list[EngineWithProvidersResponse] = []
    for meta in ENGINE_TYPES.values():
        providers = store.list_visible(
            _active_workspace_id(permission), category=meta.category, enabled_only=False
        )
        provider_count = len(providers)

        # Compute health summary from enabled providers only
        enabled = [p for p in providers if p.is_enabled]
        enabled_summary = EnabledSummary(
            enabled=len(enabled),
            total=len(enabled),
        )

        base = _meta_to_base(meta)
        engines.append(
            EngineWithProvidersResponse(
                **base,
                provider_count=provider_count,
                enabled_summary=enabled_summary,
            )
        )

    return EngineListResponse(engines=engines)


@router.get("/{category}", response_model=EngineDetailResponse)
async def get_engine(
    category: str,
    request: Request,
    permission: ProviderViewDep,
) -> EngineDetailResponse:
    """Return a single ENGINE type with full provider list."""
    meta = get_engine_meta(category)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown engine category: {category}")

    store = await _get_store(request)
    providers = store.list_visible(
        _active_workspace_id(permission), category=category, enabled_only=False
    )
    provider_count = len(providers)

    enabled = [p for p in providers if p.is_enabled]
    enabled_summary = EnabledSummary(
        enabled=sum(1 for p in enabled if p.is_enabled),
        total=len(enabled),
    )

    provider_briefs = [
        ProviderBriefResponse(
            id=p.id,
            name=p.name,
            is_enabled=p.is_enabled,
            is_default=p.is_default,
            config_schema=json.loads(p.config_schema) if p.config_schema else None,
            parameter_schema=json.loads(p.config_schema) if p.config_schema else None,
        )
        for p in providers
    ]

    base = _meta_to_base(meta)
    return EngineDetailResponse(
        **base,
        provider_count=provider_count,
        enabled_summary=enabled_summary,
        providers=provider_briefs,
    )


@router.get("/{category}/health", response_model=EngineHealthResponse)
async def engine_health(
    category: str,
    request: Request,
    permission: ProviderManageDep,
) -> EngineHealthResponse:
    """Run health checks on all providers of an engine category."""
    meta = get_engine_meta(category)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown engine category: {category}")

    store = await _get_store(request)
    providers = store.list_visible(
        _active_workspace_id(permission), category=category, enabled_only=True
    )

    from app.providers.auth import AuthResolver
    from app.providers.health_checker import check_provider_health

    auth_resolver = AuthResolver(fernet=store._fernet)

    results = []
    for p in providers:
        api_key = store.get_api_key(p.id)
        models = store.list_models(p.id) if p.provider_type == "openai_compatible" else []
        result = await check_provider_health(
            p, api_key=api_key, models=models, auth_resolver=auth_resolver
        )
        results.append(
            {
                "provider_id": result.provider_id,
                "provider_name": result.provider_name,
                "status": result.status,
                "latency_ms": result.latency_ms,
                "error": result.error,
                "checked_at": result.checked_at,
            }
        )

    healthy_count = sum(1 for r in results if r["status"] == "healthy")

    return EngineHealthResponse(
        category=category,
        providers=results,
        healthy_count=healthy_count,
        total_count=len(results),
    )
