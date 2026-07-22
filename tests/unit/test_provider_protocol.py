from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.providers.auth import AuthResolver, AuthResult, CredentialKind
from app.providers.auth_registry import register_builtin_strategies, registry
from app.providers.db import init_db
from app.providers.encryption import get_fernet
from app.providers.models import (
    ApiStyle,
    ModelProviderCreate,
    ModelProviderUpdate,
    ProviderType,
)
from app.providers.plugin_loader import (
    ProviderPluginError,
    bootstrap_provider_registry,
    load_provider_plugins,
)
from app.providers.store import ProviderStore


def _store(tmp_path: Path) -> ProviderStore:
    return ProviderStore(
        db_path=init_db(tmp_path / "providers.db"),
        fernet=get_fernet(Fernet.generate_key().decode()),
    )


def test_new_openai_provider_defaults_to_standard_style(tmp_path: Path) -> None:
    row = _store(tmp_path).create_provider(
        ModelProviderCreate(
            name="OpenAI-compatible",
            provider_type=ProviderType.openai_compatible,
            engine_category="vlm",
            base_url="https://provider.example/v1",
        )
    )
    assert row.api_style == ApiStyle.openai
    assert row.api_version is None


def test_azure_requires_api_version() -> None:
    with pytest.raises(ValidationError, match="require api_version"):
        ModelProviderCreate(
            name="Azure",
            provider_type=ProviderType.openai_compatible,
            engine_category="vlm",
            base_url="https://resource.example",
            api_style=ApiStyle.azure_openai,
        )


def test_engine_service_rejects_protocol_fields() -> None:
    with pytest.raises(ValidationError, match="cannot set api_style"):
        ModelProviderCreate(
            name="OCR",
            provider_type=ProviderType.engine_service,
            engine_category="ocr",
            base_url="https://ocr.example",
            api_style=ApiStyle.openai,
        )


def test_store_validates_updates_and_clears_azure_version(tmp_path: Path) -> None:
    store = _store(tmp_path)
    row = store.create_provider(
        ModelProviderCreate(
            name="Azure",
            provider_type=ProviderType.openai_compatible,
            engine_category="vlm",
            base_url="https://resource.example",
            api_style=ApiStyle.azure_openai,
            api_version="2025-04-01-preview",
        )
    )

    updated = store.update_provider(row.id, ModelProviderUpdate(api_style=ApiStyle.openai))
    assert updated is not None
    assert updated.api_style == ApiStyle.openai
    assert updated.api_version is None

    with pytest.raises(ValueError, match="require api_version"):
        store.update_provider(
            row.id,
            ModelProviderUpdate(api_style=ApiStyle.azure_openai),
        )


@pytest.mark.asyncio
async def test_auth_result_exposes_explicit_credential_kind(tmp_path: Path) -> None:
    register_builtin_strategies()
    store = _store(tmp_path)
    row = store.create_provider(
        ModelProviderCreate(
            name="Authenticated",
            provider_type=ProviderType.openai_compatible,
            engine_category="vlm",
            base_url="https://provider.example/v1",
            auth_type="api_key",
            api_key="secret-value",
        )
    )

    result = await AuthResolver(fernet=store.fernet).resolve(row)
    assert result == AuthResult(kind=CredentialKind.api_key, credential="secret-value")
    assert not hasattr(result, "headers")


def test_auth_result_rejects_invalid_kind_value_pair() -> None:
    with pytest.raises(ValueError, match="cannot carry"):
        AuthResult(kind=CredentialKind.none, credential="secret")
    with pytest.raises(ValueError, match="non-empty"):
        AuthResult(kind=CredentialKind.bearer)


def test_generic_plugin_loader_calls_register(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("test_provider_plugin")
    calls: list[str] = []
    module.register = lambda: calls.append("registered")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)

    assert load_provider_plugins([module.__name__, module.__name__]) == (module.__name__,)
    assert load_provider_plugins([module.__name__]) == (module.__name__,)
    assert calls == ["registered"]


def test_provider_registry_bootstrap_registers_builtins_idempotently() -> None:
    assert bootstrap_provider_registry([]) == ()
    assert bootstrap_provider_registry([]) == ()
    assert registry.has("none")
    assert registry.has("api_key")


def test_generic_plugin_loader_rejects_missing_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("invalid_provider_plugin")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(ProviderPluginError, match="register"):
        load_provider_plugins([module.__name__])
