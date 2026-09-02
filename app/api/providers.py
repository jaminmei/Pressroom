"""Provider REST API — CRUD + action endpoints for model provider management."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.api.auth import ResolvedContext, get_authenticated_context, require_workspace_capability
from app.api.provider_response_registry import provider_response_enrichers
from app.errors import AppError
from app.models.auth import AuthenticatedContext
from app.providers.discover import ProviderAuthenticationError, discover_provider
from app.providers.models import (
    ApiProtocol,
    ApiStyle,
    ModelProviderCreate,
    ModelProviderRow,
    ModelProviderUpdate,
    ProviderModelCreate,
    ProviderModelResponse,
    ProviderScope,
    ProviderType,
    RegisteredAuthType,
    ResponseFormat,
    normalize_llm_api_protocol,
    normalize_provider_protocol,
)
from app.providers.store import ProviderDefaultRequiredError, ProviderStore
from app.services.ssrf_guard import SsrfBlockedError
from app.services.workspace_service import assert_workspace_active

# ---------------------------------------------------------------------------
# Router definitions
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/providers", tags=["providers"])
models_router = APIRouter(prefix="/models", tags=["models"])


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


async def get_provider_store(request: Request) -> ProviderStore:
    """DI helper — retrieve the ProviderStore from app.state.

    Returns 503 if the store has not been initialised (e.g. during testing
    without the lifespan context).
    """
    store: ProviderStore | None = getattr(request.app.state, "provider_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Provider store not initialised")
    return store


ProviderStoreDep = Annotated[ProviderStore, Depends(get_provider_store)]
AuthenticatedContextDep = Annotated[AuthenticatedContext, Depends(get_authenticated_context)]
ProviderViewDep = Annotated[ResolvedContext, Depends(require_workspace_capability("provider.view"))]
ProviderManageDep = Annotated[
    ResolvedContext,
    Depends(require_workspace_capability("provider.manage")),
]


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ProviderCreateRequest(BaseModel):
    name: str
    provider_type: ProviderType
    engine_category: str
    base_url: str
    api_style: ApiStyle | None = None
    api_version: str | None = None
    api_protocol: ApiProtocol | None = None
    api_key: str | None = None
    model_id: str | None = None
    model_display_name: str | None = None
    model_context_window: int | None = None
    model_max_tokens: int | None = None
    model_reasoning: bool | None = None
    auth_type: RegisteredAuthType = "none"
    auth_config: dict[str, Any] | None = None
    response_format: ResponseFormat = ResponseFormat.node_output
    is_enabled: bool = True
    is_default: bool = False
    is_chatbot_default: bool = False
    extra_config: dict[str, Any] | None = None
    health_url: str | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        parsed = urlsplit(v.strip())
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            raise ValueError(f"base_url scheme must be http or https, got {scheme!r}")
        if not parsed.hostname:
            raise ValueError("base_url must include a hostname")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("base_url cannot include credentials")
        return v.strip().rstrip("/")

    @field_validator("health_url")
    @classmethod
    def validate_health_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        parsed = urlsplit(v.strip())
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            raise ValueError("health_url must be an absolute http(s) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("health_url cannot include credentials")
        return v.strip()

    @model_validator(mode="after")
    def validate_protocol(self) -> "ProviderCreateRequest":
        self.api_protocol = normalize_llm_api_protocol(self.provider_type, self.api_protocol)
        self.api_style, self.api_version = normalize_provider_protocol(
            self.provider_type,
            self.api_style,
            self.api_version,
            default_openai_style=True,
        )
        _validate_llm_api_base_url(self.base_url, self.provider_type)
        return self


class ProviderUpdateRequest(BaseModel):
    # engine_category and provider_type are intentionally excluded — these fields
    # are immutable after creation; changing them would invalidate existing models
    # and adapter routing.
    name: str | None = None
    base_url: str | None = None
    api_style: ApiStyle | None = None
    api_version: str | None = None
    api_protocol: ApiProtocol | None = None
    api_key: str | None = None
    model_id: str | None = None
    model_display_name: str | None = None
    model_context_window: int | None = None
    model_max_tokens: int | None = None
    model_reasoning: bool | None = None
    auth_type: RegisteredAuthType | None = None
    auth_config: dict[str, Any] | None = None
    response_format: str | None = None
    is_enabled: bool | None = None
    is_default: bool | None = None
    is_chatbot_default: bool | None = None
    extra_config: dict[str, Any] | None = None
    health_url: str | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parsed = urlsplit(v.strip())
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            raise ValueError(f"base_url scheme must be http or https, got {scheme!r}")
        if not parsed.hostname:
            raise ValueError("base_url must include a hostname")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("base_url cannot include credentials")
        return v.strip().rstrip("/")

    @field_validator("health_url")
    @classmethod
    def validate_health_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        parsed = urlsplit(v.strip())
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            raise ValueError("health_url must be an absolute http(s) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("health_url cannot include credentials")
        return v.strip()

    @model_validator(mode="after")
    def reject_null_base_url(self) -> "ProviderUpdateRequest":
        if "base_url" in self.model_fields_set and self.base_url is None:
            raise ValueError("base_url cannot be null")
        return self


class ProviderResponse(BaseModel):
    """Provider HTTP response — never contains raw api_key."""

    id: str  # UUID serialized as str at API boundary; store layer uses uuid.UUID internally
    name: str
    provider_type: str
    engine_category: str
    base_url: str
    api_style: str | None = None
    api_version: str | None = None
    api_protocol: str | None = None
    model_id: str | None = None
    model_display_name: str | None = None
    model_context_window: int | None = None
    model_max_tokens: int | None = None
    model_reasoning: bool | None = None
    has_api_key: bool
    auth_type: str
    auth_config_public: dict[str, str] | None = None  # non-secret auth_config fields
    env_config: dict[str, str] | None = None  # read-only env-sourced config for display
    is_enabled: bool
    is_default: bool
    is_chatbot_default: bool
    chatbot_ready: bool = False
    response_format: str
    config_schema: dict[str, Any] | None = None  # parsed from SQLite JSON string
    parameter_schema: dict[str, Any] | None = None  # alias for config_schema
    extra_config: str | None = None
    models: list[dict[str, Any]] = []
    created_at: str
    updated_at: str
    health_url: str | None = None
    scope: str
    workspace_id: str | None = None

    @classmethod
    def from_row(
        cls,
        row: ModelProviderRow,
        models: list[ProviderModelResponse] | None = None,
    ) -> "ProviderResponse":
        def _str_val(v: object) -> str:
            val = getattr(v, "value", None)
            return str(val) if val is not None else str(v)

        # Extract non-secret fields from auth_config for the response
        auth_config_public: dict[str, str] | None = None
        if row.auth_config:
            try:
                ac = (
                    json.loads(row.auth_config)
                    if isinstance(row.auth_config, str)
                    else row.auth_config
                )
                auth_config_public = {
                    k: v for k, v in ac.items() if k in ("client_id",) and isinstance(v, str)
                }
                if not auth_config_public:
                    auth_config_public = None
            except (json.JSONDecodeError, TypeError, AttributeError):
                auth_config_public = None

        auth_type_str = _str_val(row.auth_type)
        env_config = provider_response_enrichers.enrich(auth_type_str)
        parsed_schema = json.loads(row.config_schema) if row.config_schema else None

        return cls(
            id=row.id,
            name=row.name,
            provider_type=_str_val(row.provider_type),
            engine_category=row.engine_category,
            base_url=row.base_url,
            api_style=_str_val(row.api_style) if row.api_style is not None else None,
            api_version=row.api_version,
            api_protocol=_str_val(row.api_protocol) if row.api_protocol is not None else None,
            model_id=row.model_id,
            model_display_name=row.model_display_name,
            model_context_window=row.model_context_window,
            model_max_tokens=row.model_max_tokens,
            model_reasoning=row.model_reasoning,
            has_api_key=row.api_key is not None,
            auth_type=auth_type_str,
            auth_config_public=auth_config_public,
            env_config=env_config,
            is_enabled=row.is_enabled,
            is_default=row.is_default,
            is_chatbot_default=row.is_chatbot_default,
            chatbot_ready=row.chatbot_ready,
            response_format=_str_val(row.response_format),
            config_schema=parsed_schema,
            parameter_schema=parsed_schema,
            extra_config=row.extra_config,
            models=[m.model_dump() for m in (models or [])],
            created_at=row.created_at,
            updated_at=row.updated_at,
            health_url=row.health_url,
            scope=row.scope.value,
            workspace_id=row.workspace_id,
        )


def _mutable_provider(
    store: ProviderStore, provider_id: str, workspace_id: str
) -> ModelProviderRow:
    row = store.get_mutable(provider_id, workspace_id)
    if row is not None:
        return row
    visible = store.get_for_runtime(provider_id, workspace_id)
    if visible is not None and visible.scope == ProviderScope.system:
        raise HTTPException(status_code=409, detail="System providers are read-only")
    raise HTTPException(status_code=404, detail="Provider not found")


def _validation_detail(exc: ValidationError) -> str:
    """First pydantic error as loc + msg; never includes the rejected input value."""

    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        msg = str(err.get("msg", "Invalid value"))
        return f"{loc}: {msg}" if loc else msg
    return "Invalid provider payload"


def _validation_http_error(exc: ValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail=_validation_detail(exc))


def _validate_llm_api_base_url(base_url: str, provider_type: ProviderType) -> None:
    if provider_type != ProviderType.llm_api:
        return
    parsed = urlsplit(base_url)
    if parsed.query:
        raise ValueError("llm_api base_url cannot include a query string")
    if parsed.fragment:
        raise ValueError("llm_api base_url cannot include a fragment")
    if parsed.path.rstrip("/").endswith(("/chat/completions", "/responses", "/messages")):
        raise ValueError("llm_api base_url cannot include a protocol resource path")


def _active_workspace_id(context: ResolvedContext) -> str:
    if context.workspace_id is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return context.workspace_id


class ModelTestResult(BaseModel):
    """Result of testing a single model within a VLM provider."""

    model_id: str
    display_name: str | None = None
    status: str  # "ok" | "failed"
    latency_ms: int | None = None
    error: str | None = None


class ProviderDiagnosticResponse(BaseModel):
    operation: Literal["provider.test", "provider.health", "provider.model.test"]
    target_type: Literal["provider", "model"]
    target_id: str
    target_name: str | None = None
    status: Literal["healthy", "unhealthy", "unavailable"]
    latency_ms: int | None = None
    error_code: str | None = None
    error: str | None = None
    checked_at: str
    details: dict[str, Any] | None = None
    model_results: list[ModelTestResult] | None = None
    provider_id: str
    provider_name: str
    model_response: str | None = None


TestConnectionResponse = ProviderDiagnosticResponse


def _diagnostic_status(status: str) -> Literal["healthy", "unhealthy", "unavailable"]:
    if status == "healthy":
        return "healthy"
    if status in {"no_health_url", "no_models"}:
        return "unavailable"
    return "unhealthy"


def _diagnostic_error_code(status: str, error: str | None) -> str | None:
    if status == "healthy" and error is None:
        return None
    return {
        "no_health_url": "PROVIDER_HEALTH_URL_MISSING",
        "no_models": "PROVIDER_MODELS_UNAVAILABLE",
    }.get(status, "PROVIDER_DIAGNOSTIC_FAILED")


class DiscoverResponse(BaseModel):
    discovered: list[dict[str, Any]]
    added: int
    skipped: int
    config_schema: dict[str, Any] | None = None  # engine_service only（§4.2 v3）
    schema_discovered: bool = False
    discovery_supported: bool = True
    message: str | None = None


class ModelsListResponse(BaseModel):
    models: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ProviderResponse])
async def list_providers(
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderViewDep,
    category: str | None = Query(default=None),
    provider_type: str | None = Query(default=None),
    enabled_only: bool = Query(default=True),
) -> list[ProviderResponse]:
    """List providers, optionally filtered by engine_category, provider_type and enabled flag."""
    rows = store.list_visible(
        _active_workspace_id(permission),
        category=category,
        provider_type=provider_type,
        enabled_only=enabled_only,
    )
    result = []
    for row in rows:
        models = store.list_models(row.id)
        result.append(ProviderResponse.from_row(row, models=models))
    return result


@router.post("", response_model=ProviderResponse, status_code=201)
async def create_provider(
    body: ProviderCreateRequest,
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderManageDep,
) -> ProviderResponse:
    """Create a provider with an explicit upstream URL and encrypted credentials."""
    payload = body.model_dump()

    workspace_id = _active_workspace_id(permission)
    payload.update(scope=ProviderScope.workspace, workspace_id=workspace_id)
    try:
        data = ModelProviderCreate(**payload)
    except ValidationError as exc:
        raise _validation_http_error(exc) from exc
    try:
        with assert_workspace_active(workspace_id):
            row = store.create_provider(data)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return ProviderResponse.from_row(row, models=[])


@router.get("/default", response_model=ProviderResponse | None)
async def get_default_provider(
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderViewDep,
    category: str = Query(..., description="Engine category to look up default provider for"),
) -> ProviderResponse | None:
    """Get the default provider for a given engine category, including its models."""
    row = store.get_default_provider(category, _active_workspace_id(permission))
    if row is None:
        return None
    models = store.list_models(row.id)
    return ProviderResponse.from_row(row, models=models)


@router.get("/{provider_id}", response_model=ProviderResponse)
async def get_provider(
    provider_id: str,
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderViewDep,
) -> ProviderResponse:
    """Get a single provider by ID, including its model list."""
    row = store.get_for_runtime(provider_id, _active_workspace_id(permission))
    if row is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    models = store.list_models(provider_id)
    return ProviderResponse.from_row(row, models=models)


@router.put("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: str,
    body: ProviderUpdateRequest,
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderManageDep,
) -> ProviderResponse:
    """Partially update a provider. Only supplied fields are changed."""
    existing = _mutable_provider(store, provider_id, _active_workspace_id(permission))
    if body.base_url is not None:
        try:
            _validate_llm_api_base_url(body.base_url, existing.provider_type)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        data = ModelProviderUpdate(**body.model_dump(exclude_unset=True))
    except ValidationError as exc:
        raise _validation_http_error(exc) from exc
    try:
        row = store.update_provider(provider_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    models = store.list_models(provider_id)
    return ProviderResponse.from_row(row, models=models)


@router.delete("/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: str,
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderManageDep,
) -> Response:
    """Delete a provider and all its models."""
    _mutable_provider(store, provider_id, _active_workspace_id(permission))
    try:
        deleted = store.delete_provider(provider_id, _active_workspace_id(permission))
    except ProviderDefaultRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Provider not found")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Action endpoints
# ---------------------------------------------------------------------------


@router.post("/{provider_id}/test", response_model=TestConnectionResponse)
async def test_connection(
    provider_id: str,
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderManageDep,
) -> TestConnectionResponse:
    """Test connectivity to a provider.

    engine_service: GET {health_url}
    openai_compatible: test ALL enabled models via chat completion
    Always returns HTTP 200; check ``status`` field for the business result.
    """
    row = store.get_for_runtime(provider_id, _active_workspace_id(permission))
    if row is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    from app.providers.health_checker import check_provider_health

    models = store.list_models(provider_id) if row.provider_type == "openai_compatible" else []

    # Pass AuthResolver for full auth support (api_key, none)
    from app.providers.auth import AuthResolver

    auth_resolver = AuthResolver(fernet=store.fernet)

    result = await check_provider_health(row, models=models, auth_resolver=auth_resolver)
    return TestConnectionResponse(
        operation="provider.test",
        target_type="provider",
        target_id=result.provider_id,
        target_name=result.provider_name,
        status=_diagnostic_status(result.status),
        latency_ms=result.latency_ms,
        error_code=_diagnostic_error_code(result.status, result.error),
        error=result.error,
        checked_at=result.checked_at,
        details=result.details,
        model_results=[
            ModelTestResult(
                model_id=r.model_id,
                display_name=r.display_name,
                status=r.status,
                latency_ms=r.latency_ms,
                error=r.error,
            )
            for r in (result.model_results or [])
        ],
        provider_id=result.provider_id,
        provider_name=result.provider_name,
    )


@router.post("/{provider_id}/discover", response_model=DiscoverResponse)
async def discover_models(
    provider_id: str,
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderManageDep,
) -> DiscoverResponse:
    """Discover and register available models from the provider's service.

    openai API style  → GET {base_url}/models → parse data[].id
    Azure API style   → manual deployment entry (no discovery request)
    engine_service    → GET {base_url}/config  → parse engine_name + config_schema
    Connection errors raise HTTP 502.
    """
    row = _mutable_provider(store, provider_id, _active_workspace_id(permission))

    try:
        from app.providers.auth import AuthResolver

        result = await discover_provider(
            row,
            store,
            auth_resolver=AuthResolver(fernet=store.fernet),
        )
    except SsrfBlockedError as exc:
        raise HTTPException(
            status_code=400, detail="Provider endpoint rejected by network policy"
        ) from exc
    except ProviderAuthenticationError as exc:
        raise HTTPException(status_code=502, detail="Provider authentication failed") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Provider discovery failed") from exc

    return DiscoverResponse(
        discovered=result.discovered,
        added=result.added,
        skipped=result.skipped,
        config_schema=result.config_schema,
        schema_discovered=result.config_schema is not None,
        discovery_supported=result.discovery_supported,
        message=result.message,
    )


@router.put("/{provider_id}/default", response_model=ProviderResponse)
async def set_default(
    provider_id: str,
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderManageDep,
) -> ProviderResponse:
    """Set this provider as the default for its engine_category."""
    workspace_id = _active_workspace_id(permission)
    row = _mutable_provider(store, provider_id, workspace_id)
    try:
        store.set_default(provider_id, row.engine_category)
    except ProviderDefaultRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    updated = store.get_mutable(provider_id, workspace_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Provider disappeared after set_default")
    models = store.list_models(provider_id)
    return ProviderResponse.from_row(updated, models=models)


# ---------------------------------------------------------------------------
# Readiness test endpoint
# ---------------------------------------------------------------------------


ReadinessStepStatus = Literal["pass", "fail", "skipped"]


class ReadinessStepResult(BaseModel):
    name: str
    status: ReadinessStepStatus
    detail: str | None = None


class ReadinessTestResponse(BaseModel):
    provider_id: str
    chatbot_ready: bool
    steps: list[ReadinessStepResult]


@router.post(
    "/{provider_id}/readiness-test",
    response_model=ReadinessTestResponse,
)
async def run_readiness_test(
    provider_id: str,
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderManageDep,
) -> ReadinessTestResponse:
    """Run the 6-step server-side readiness probe for an llm_api Provider."""

    workspace_id = _active_workspace_id(permission)
    row = _mutable_provider(store, provider_id, workspace_id)
    if row.provider_type != ProviderType.llm_api:
        raise HTTPException(
            status_code=400, detail="Readiness test applies only to llm_api providers"
        )

    from app.providers.auth import AuthResolver
    from app.providers.readiness import run_readiness_probe

    auth = await AuthResolver(fernet=store.fernet).resolve(row)
    result = await run_readiness_probe(row, auth)
    if not store.set_chatbot_ready(provider_id, result.chatbot_ready, workspace_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    return ReadinessTestResponse(
        provider_id=result.provider_id,
        chatbot_ready=result.chatbot_ready,
        steps=[
            ReadinessStepResult(name=step.name, status=step.status, detail=step.detail)
            for step in result.steps
        ],
    )


# ---------------------------------------------------------------------------
# Parameter Schema endpoint
# ---------------------------------------------------------------------------


class ParameterSchemaRequest(BaseModel):
    schema_: dict[str, Any] = Field(alias="schema")


@router.put("/{provider_id}/parameter-schema", response_model=ProviderResponse)
async def update_parameter_schema(
    provider_id: str,
    body: ParameterSchemaRequest,
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderManageDep,
) -> ProviderResponse:
    """Update the parameter schema (JSON Schema) for a provider.

    Validates that the schema has ``type: "object"`` and ``properties`` key.
    The schema is stored in the ``config_schema`` column.
    """
    _mutable_provider(store, provider_id, _active_workspace_id(permission))

    schema = body.schema_
    if schema.get("type") != "object":
        raise HTTPException(
            status_code=400,
            detail="Schema must have 'type: \"object\"'",
        )
    if "properties" not in schema:
        raise HTTPException(
            status_code=400,
            detail="Schema must contain 'properties'",
        )

    data = ModelProviderUpdate(config_schema=schema)
    updated = store.update_provider(provider_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    models = store.list_models(provider_id)
    return ProviderResponse.from_row(updated, models=models)


# ---------------------------------------------------------------------------
# Health Check endpoint
# ---------------------------------------------------------------------------


HealthCheckResponse = ProviderDiagnosticResponse


@router.post("/{provider_id}/health-check", response_model=HealthCheckResponse)
async def health_check_provider(
    provider_id: str,
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderManageDep,
) -> HealthCheckResponse:
    """Run a health check on a single provider via health_url."""
    row = store.get_for_runtime(provider_id, _active_workspace_id(permission))
    if row is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    from app.providers.health_checker import check_provider_health

    models = store.list_models(provider_id) if row.provider_type == "openai_compatible" else []

    from app.providers.auth import AuthResolver

    auth_resolver = AuthResolver(fernet=store.fernet)

    result = await check_provider_health(row, models=models, auth_resolver=auth_resolver)
    return HealthCheckResponse(
        operation="provider.health",
        target_type="provider",
        target_id=result.provider_id,
        target_name=result.provider_name,
        provider_id=result.provider_id,
        provider_name=result.provider_name,
        status=_diagnostic_status(result.status),
        latency_ms=result.latency_ms,
        error_code=_diagnostic_error_code(result.status, result.error),
        error=result.error,
        checked_at=result.checked_at,
        details=result.details,
        model_results=[
            ModelTestResult(
                model_id=item.model_id,
                display_name=item.display_name,
                status=item.status,
                latency_ms=item.latency_ms,
                error=item.error,
            )
            for item in (result.model_results or [])
        ],
    )


# ---------------------------------------------------------------------------
# PATCH /api/providers/{provider_id}/models/{model_id} — toggle model enabled
# ---------------------------------------------------------------------------


class ModelToggleRequest(BaseModel):
    is_enabled: bool


@router.patch(
    "/{provider_id}/models/{model_id}",
    response_model=ProviderModelResponse,
)
async def toggle_model(
    provider_id: str,
    model_id: str,
    body: ModelToggleRequest,
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderManageDep,
) -> ProviderModelResponse:
    """Toggle a model's ``is_enabled`` flag."""
    _mutable_provider(store, provider_id, _active_workspace_id(permission))
    result = store.toggle_model(provider_id, model_id, body.is_enabled)
    if result is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return result


@router.post("/{provider_id}/models", response_model=ProviderModelResponse, status_code=201)
async def add_model_to_provider(
    provider_id: str,
    model_data: ProviderModelCreate,
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderManageDep,
) -> ProviderModelResponse:
    """Manually add a model to a provider."""
    _mutable_provider(store, provider_id, _active_workspace_id(permission))
    try:
        return store.add_model(provider_id, model_data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{provider_id}/models/{model_id}", status_code=204)
async def remove_model_from_provider(
    provider_id: str,
    model_id: str,
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderManageDep,
) -> None:
    """Remove a model from a provider."""
    _mutable_provider(store, provider_id, _active_workspace_id(permission))
    deleted = store.remove_model(provider_id, model_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Model not found")


TestModelResponse = ProviderDiagnosticResponse


@router.post("/{provider_id}/models/{model_id}/test", response_model=TestModelResponse)
async def test_model(
    provider_id: str,
    model_id: str,
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderManageDep,
) -> TestModelResponse:
    """Test one configured model using the provider's declared API style."""
    from app.providers.auth import AuthResolver
    from app.providers.health_checker import check_provider_health

    row = store.get_for_runtime(provider_id, _active_workspace_id(permission))
    if row is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    models = store.list_models(provider_id)
    model = next((m for m in models if m.id == model_id), None)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    result = await check_provider_health(
        row,
        models=[model.model_copy(update={"is_enabled": True})],
        auth_resolver=AuthResolver(fernet=store.fernet),
        timeout=30.0,
    )
    detail = result.model_results[0] if result.model_results else None
    healthy = detail is not None and detail.status == "ok"
    checked_at = result.checked_at or datetime.now(timezone.utc).isoformat()
    return TestModelResponse(
        operation="provider.model.test",
        target_type="model",
        target_id=model.id,
        target_name=model.display_name,
        status="healthy" if healthy else "unhealthy",
        latency_ms=detail.latency_ms if detail is not None else result.latency_ms,
        error_code=None if healthy else "PROVIDER_MODEL_TEST_FAILED",
        error=detail.error if detail is not None else result.error,
        checked_at=checked_at,
        details=None,
        provider_id=row.id,
        provider_name=row.name,
    )


# ---------------------------------------------------------------------------
# GET /api/models — aggregate model list
# ---------------------------------------------------------------------------


@models_router.get("", response_model=ModelsListResponse)
async def list_all_models(
    store: ProviderStoreDep,
    _context: AuthenticatedContextDep,
    permission: ProviderViewDep,
    category: str | None = Query(default=None),
) -> ModelsListResponse:
    """Return all registered models across all providers, optionally filtered by category."""
    rows = store.list_all_models(category=category, workspace_id=_active_workspace_id(permission))
    return ModelsListResponse(models=rows)
