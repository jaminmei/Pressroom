"""
app/providers/models.py
-----------------------
Pydantic v2 data models for Provider Store input/output/DB mapping.

Layered design:
- Enums              — ProviderType / ResponseFormat / AuthType
- *Create            — API input (create resource)
- *Update            — API input (partial update, all fields Optional)
- *Row               — Maps to SQLite row (JSON columns remain str)
- *Response          — API response (hides sensitive fields, expands JSON)
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, assert_never

from pydantic import AfterValidator, BaseModel, ConfigDict, model_validator
from pydantic_core import PydanticCustomError

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProviderType(str, Enum):
    """Provider technology type."""

    openai_compatible = "openai_compatible"
    engine_service = "engine_service"


class ApiStyle(str, Enum):
    """Upstream API dialect used by an OpenAI-compatible provider."""

    openai = "openai"
    azure_openai = "azure_openai"


class ResponseFormat(str, Enum):
    """Engine response format type."""

    node_output = "node_output"
    simple_blocks = "simple_blocks"
    hocr = "hocr"
    openai_chat = "openai_chat"
    raw_text = "raw_text"


class ProviderScope(str, Enum):
    system = "system"
    workspace = "workspace"
    legacy_unassigned = "legacy_unassigned"


# AuthType: string type with known literal values.
# Built-in: "none", "api_key". Additional types are registered at runtime
# via the auth strategy registry and accepted as plain strings.
AuthType = Literal["none", "api_key"] | str


def validate_registered_auth_type(auth_type: str) -> str:
    """Accept built-in or currently registered Provider auth strategy names."""

    if auth_type in {"none", "api_key"}:
        return auth_type

    from app.providers.auth_registry import registry

    if registry.has(auth_type):
        return auth_type
    raise PydanticCustomError(
        "provider_auth_type_unregistered",
        "Auth type '{auth_type}' is not registered",
        {"auth_type": auth_type},
    )


RegisteredAuthType = Annotated[AuthType, AfterValidator(validate_registered_auth_type)]


def normalize_provider_protocol(
    provider_type: ProviderType,
    api_style: ApiStyle | str | None,
    api_version: str | None,
    *,
    default_openai_style: bool,
) -> tuple[ApiStyle | None, str | None]:
    """Normalize and validate protocol fields shared by API and store models."""

    style = ApiStyle(api_style) if api_style is not None else None
    version = api_version.strip() if isinstance(api_version, str) else None
    if version == "":
        version = None

    if provider_type == ProviderType.engine_service:
        if style is not None or version is not None:
            raise ValueError("engine_service providers cannot set api_style or api_version")
        return None, None

    if style is None and default_openai_style:
        style = ApiStyle.openai
    if style is None:
        raise ValueError("openai_compatible providers require api_style")
    if style == ApiStyle.azure_openai and version is None:
        raise ValueError("azure_openai providers require api_version")
    return style, version


# ---------------------------------------------------------------------------
# ProviderModel (sub-resource) — defined first to avoid forward reference
# ---------------------------------------------------------------------------


class ProviderModelCreate(BaseModel):
    """Input model for creating a provider model."""

    model_id: str
    display_name: str
    is_enabled: bool = True
    capabilities: dict[str, Any] | None = None
    default_config: dict[str, Any] | None = None
    model_group: str | None = None
    sort_order: int = 0


class ProviderModelResponse(BaseModel):
    """Provider model API response model.

    Note: capabilities / default_config are stored as JSON strings in SQLite;
    this model keeps str | None for consistency with Row. Callers needing
    dicts should json.loads() themselves.
    """

    id: str
    provider_id: str
    model_id: str
    display_name: str
    is_enabled: bool = True
    capabilities: str | None = None
    default_config: str | None = None
    model_group: str | None = None
    sort_order: int = 0

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# ModelProvider (main resource)
# ---------------------------------------------------------------------------


class ModelProviderCreate(BaseModel):
    """API input model for creating a provider."""

    name: str
    provider_type: ProviderType
    engine_category: str
    base_url: str
    api_style: ApiStyle | None = None
    api_version: str | None = None
    api_key: str | None = None
    auth_type: RegisteredAuthType = "none"
    auth_config: dict[str, Any] | None = None
    is_enabled: bool = True
    is_default: bool = False
    response_format: ResponseFormat = ResponseFormat.node_output
    config_schema: dict[str, Any] | None = None
    extra_config: dict[str, Any] | None = None
    health_url: str | None = None
    scope: ProviderScope = ProviderScope.legacy_unassigned
    workspace_id: str | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> "ModelProviderCreate":
        self.api_style, self.api_version = normalize_provider_protocol(
            self.provider_type,
            self.api_style,
            self.api_version,
            default_openai_style=True,
        )
        match self.scope:
            case ProviderScope.workspace:
                if not self.workspace_id:
                    raise PydanticCustomError(
                        "provider_workspace_required",
                        "workspace scope requires workspace_id",
                    )
            case ProviderScope.system | ProviderScope.legacy_unassigned:
                if self.workspace_id is not None:
                    raise PydanticCustomError(
                        "provider_workspace_forbidden",
                        "{scope} scope cannot have workspace_id",
                        {"scope": self.scope.value},
                    )
            case unreachable:
                assert_never(unreachable)
        return self


class ModelProviderUpdate(BaseModel):
    """API input model for updating a provider (all fields Optional).

    Use model_dump(exclude_none=True) to get the set of fields to update.
    """

    name: str | None = None
    provider_type: ProviderType | None = None
    engine_category: str | None = None
    base_url: str | None = None
    api_style: ApiStyle | None = None
    api_version: str | None = None
    api_key: str | None = None
    auth_type: RegisteredAuthType | None = None
    auth_config: dict[str, Any] | None = None
    is_enabled: bool | None = None
    is_default: bool | None = None
    response_format: ResponseFormat | None = None
    config_schema: dict[str, Any] | None = None
    extra_config: dict[str, Any] | None = None
    health_url: str | None = None


class ModelProviderRow(BaseModel):
    """Maps to a SQLite row (includes id and timestamps).

    JSON columns (auth_config / config_schema / extra_config) are stored as
    TEXT in SQLite, so their type is str | None and they are not auto-parsed.
    """

    id: str
    name: str
    provider_type: ProviderType
    engine_category: str
    base_url: str
    api_style: ApiStyle | None = None
    api_version: str | None = None
    api_key: str | None = None
    auth_type: AuthType = "none"
    auth_config: str | None = None  # SQLite: JSON string
    is_enabled: bool = True
    is_default: bool = False
    response_format: ResponseFormat = ResponseFormat.node_output
    config_schema: str | None = None  # SQLite: JSON string
    extra_config: str | None = None  # SQLite: JSON string
    created_at: str
    updated_at: str
    health_url: str | None = None
    scope: ProviderScope = ProviderScope.legacy_unassigned
    workspace_id: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ModelProviderResponse(BaseModel):
    """Provider API response model.

    - No raw api_key (replaced by has_api_key bool)
    - Includes models list (ProviderModelResponse)
    """

    id: str
    name: str
    provider_type: ProviderType
    engine_category: str
    base_url: str
    api_style: ApiStyle | None = None
    api_version: str | None = None
    auth_type: AuthType = "none"
    auth_config: str | None = None  # SQLite: JSON string
    is_enabled: bool = True
    is_default: bool = False
    response_format: ResponseFormat = ResponseFormat.node_output
    config_schema: str | None = None  # SQLite: JSON string
    parameter_schema: str | None = None  # alias for config_schema
    extra_config: str | None = None  # SQLite: JSON string
    created_at: str
    updated_at: str
    has_api_key: bool = False
    health_url: str | None = None
    scope: ProviderScope = ProviderScope.legacy_unassigned
    workspace_id: str | None = None
    models: list[ProviderModelResponse] = []

    model_config = ConfigDict(from_attributes=True)
