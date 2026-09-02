from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.api.providers import ProviderCreateRequest
from app.providers.db import init_db
from app.providers.encryption import get_fernet
from app.providers.models import (
    ApiProtocol,
    ModelProviderCreate,
    ModelProviderUpdate,
    ProviderScope,
    ProviderType,
)
from app.providers.store import ProviderStore


@pytest.fixture
def store(tmp_path: Path) -> ProviderStore:
    return ProviderStore(
        db_path=init_db(tmp_path / "providers.db"),
        fernet=get_fernet(Fernet.generate_key().decode()),
    )


def _llm(name: str, *, is_chatbot_default: bool = False) -> ModelProviderCreate:
    return ModelProviderCreate(
        name=name,
        provider_type=ProviderType.llm_api,
        engine_category="llm",
        base_url="https://api.example/v1",
        api_protocol=ApiProtocol.openai_chat_completions,
        api_key="secret",
        model_id="gpt-test",
        is_chatbot_default=is_chatbot_default,
        scope=ProviderScope.workspace,
        workspace_id="ws-1",
    )


def test_create_llm_api_provider(store: ProviderStore) -> None:
    row = store.create_provider(_llm("Chat"))

    assert row.api_protocol == ApiProtocol.openai_chat_completions
    assert row.model_id == "gpt-test"
    assert row.model_context_window == 128_000
    assert row.model_max_tokens == 4_096
    assert row.model_reasoning is False


def test_llm_api_persists_custom_model_capabilities(store: ProviderStore) -> None:
    data = _llm("Custom")
    data.model_context_window = 200_000
    data.model_max_tokens = 8_192
    data.model_reasoning = True

    row = store.create_provider(data)

    assert row.model_context_window == 200_000
    assert row.model_max_tokens == 8_192
    assert row.model_reasoning is True


@pytest.mark.parametrize(
    ("context_window", "max_tokens"),
    [(0, 1), (128_000, 0), (4_096, 4_097), (2**53, 4_096)],
)
def test_llm_api_rejects_invalid_model_capabilities(
    context_window: int,
    max_tokens: int,
) -> None:
    with pytest.raises(ValidationError, match="model_(context_window|max_tokens)"):
        ModelProviderCreate(
            **{
                **_llm("Invalid").model_dump(),
                "model_context_window": context_window,
                "model_max_tokens": max_tokens,
            }
        )


def test_non_llm_provider_keeps_capabilities_null_and_rejects_metadata(
    store: ProviderStore,
) -> None:
    row = store.create_provider(
        ModelProviderCreate(
            name="OCR",
            provider_type=ProviderType.engine_service,
            engine_category="ocr",
            base_url="http://ocr:8080",
            scope=ProviderScope.workspace,
            workspace_id="ws-1",
        )
    )

    assert row.model_context_window is None
    assert row.model_max_tokens is None
    assert row.model_reasoning is None
    with pytest.raises(ValidationError, match="only llm_api providers"):
        ModelProviderCreate(
            name="OCR with model metadata",
            provider_type=ProviderType.engine_service,
            engine_category="ocr",
            base_url="http://ocr:8080",
            model_context_window=128_000,
        )


def test_switching_away_from_llm_api_clears_all_model_metadata(
    store: ProviderStore,
) -> None:
    data = _llm("Switch type")
    data.model_display_name = "Old model"
    provider = store.create_provider(data)

    updated = store.update_provider(
        provider.id,
        ModelProviderUpdate(
            provider_type=ProviderType.engine_service,
            engine_category="ocr",
        ),
    )

    assert updated is not None
    assert updated.provider_type == ProviderType.engine_service
    assert updated.api_protocol is None
    assert updated.model_id is None
    assert updated.model_display_name is None
    assert updated.model_context_window is None
    assert updated.model_max_tokens is None
    assert updated.model_reasoning is None


def test_llm_api_requires_protocol_and_model_id() -> None:
    with pytest.raises(ValidationError, match="require api_protocol"):
        ModelProviderCreate(
            name="Missing protocol",
            provider_type=ProviderType.llm_api,
            engine_category="llm",
            base_url="https://api.example/v1",
            api_key="secret",
            model_id="gpt-test",
        )
    with pytest.raises(ValidationError, match="require model_id"):
        ModelProviderCreate(
            name="Missing model",
            provider_type=ProviderType.llm_api,
            engine_category="llm",
            base_url="https://api.example/v1",
            api_protocol=ApiProtocol.openai_chat_completions,
            api_key="secret",
        )


def test_non_llm_api_rejects_api_protocol() -> None:
    with pytest.raises(ValidationError, match="only llm_api"):
        ModelProviderCreate(
            name="VLM",
            provider_type=ProviderType.openai_compatible,
            engine_category="vlm",
            base_url="https://api.example/v1",
            api_protocol=ApiProtocol.openai_chat_completions,
        )


def test_chatbot_default_requires_workspace_llm_api() -> None:
    with pytest.raises(ValidationError, match="only workspace llm_api"):
        ModelProviderCreate(
            name="OCR",
            provider_type=ProviderType.engine_service,
            engine_category="ocr",
            base_url="http://ocr:8080",
            is_chatbot_default=True,
            scope=ProviderScope.workspace,
            workspace_id="ws-1",
        )
    with pytest.raises(ValidationError, match="only workspace llm_api"):
        ModelProviderCreate(
            name="System chat",
            provider_type=ProviderType.llm_api,
            engine_category="llm",
            base_url="https://api.example/v1",
            api_protocol=ApiProtocol.openai_chat_completions,
            api_key="secret",
            model_id="gpt-test",
            is_chatbot_default=True,
            scope=ProviderScope.system,
        )


def test_chatbot_default_is_unique_within_workspace(store: ProviderStore) -> None:
    first = store.create_provider(_llm("First", is_chatbot_default=True))
    second = store.create_provider(_llm("Second", is_chatbot_default=True))

    assert store.get_provider(first.id).is_chatbot_default is False  # type: ignore[union-attr]
    assert store.get_provider(second.id).is_chatbot_default is True  # type: ignore[union-attr]


def test_store_rejects_non_llm_chatbot_default_update(store: ProviderStore) -> None:
    provider = store.create_provider(
        ModelProviderCreate(
            name="OCR",
            provider_type=ProviderType.engine_service,
            engine_category="ocr",
            base_url="http://ocr:8080",
            scope=ProviderScope.workspace,
            workspace_id="ws-1",
        )
    )

    with pytest.raises(ValueError, match="only workspace llm_api"):
        store.update_provider(
            provider.id,
            ModelProviderUpdate(is_chatbot_default=True),
        )


def test_chatbot_ready_update_is_workspace_and_type_scoped(store: ProviderStore) -> None:
    workspace_provider = store.create_provider(_llm("Workspace"))
    system_provider = store.create_provider(
        ModelProviderCreate(
            name="System",
            provider_type=ProviderType.llm_api,
            engine_category="llm",
            base_url="https://api.example/v1",
            api_protocol=ApiProtocol.openai_chat_completions,
            api_key="secret",
            model_id="gpt-test",
            scope=ProviderScope.system,
        )
    )

    assert store.set_chatbot_ready(workspace_provider.id, True, "other-workspace") is False
    assert store.get_provider(workspace_provider.id).chatbot_ready is False  # type: ignore[union-attr]
    assert store.set_chatbot_ready(system_provider.id, True, "ws-1") is False
    assert store.get_provider(system_provider.id).chatbot_ready is False  # type: ignore[union-attr]
    assert store.set_chatbot_ready(workspace_provider.id, True, "ws-1") is True
    assert store.get_provider(workspace_provider.id).chatbot_ready is True  # type: ignore[union-attr]


def test_runtime_affecting_update_invalidates_chatbot_readiness(store: ProviderStore) -> None:
    provider = store.create_provider(_llm("Ready"))
    assert store.set_chatbot_ready(provider.id, True, "ws-1") is True

    updated = store.update_provider(
        provider.id,
        ModelProviderUpdate(model_max_tokens=8_192),
    )

    assert updated is not None
    assert updated.model_max_tokens == 8_192
    assert updated.chatbot_ready is False


def test_non_runtime_update_preserves_chatbot_readiness(store: ProviderStore) -> None:
    provider = store.create_provider(_llm("Ready"))
    assert store.set_chatbot_ready(provider.id, True, "ws-1") is True

    updated = store.update_provider(
        provider.id,
        ModelProviderUpdate(model_display_name="Display only"),
    )

    assert updated is not None
    assert updated.chatbot_ready is True


def test_blank_api_key_update_preserves_llm_api_credential(store: ProviderStore) -> None:
    row = store.create_provider(_llm("Chat"))

    store.update_provider(row.id, ModelProviderUpdate(api_key=" "))

    assert store.get_api_key(row.id) == "secret"


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.example/v1?tenant=x",
        "https://api.example/v1#fragment",
        "https://api.example/v1/chat/completions",
        "https://api.example/v1/responses",
        "https://api.example/v1/messages",
        "https://user:secret@api.example/v1",
    ],
)
def test_llm_api_rejects_invalid_base_url(base_url: str) -> None:
    with pytest.raises(ValidationError):
        ProviderCreateRequest(
            name="Chat",
            provider_type=ProviderType.llm_api,
            engine_category="llm",
            base_url=base_url,
            api_protocol=ApiProtocol.openai_chat_completions,
            api_key="secret",
            model_id="gpt-test",
        )


def test_llm_api_strips_trailing_base_url_slash() -> None:
    request = ProviderCreateRequest(
        name="Chat",
        provider_type=ProviderType.llm_api,
        engine_category="llm",
        base_url="https://api.example/v1/",
        api_protocol=ApiProtocol.openai_chat_completions,
        api_key="secret",
        model_id="gpt-test",
    )

    assert request.base_url == "https://api.example/v1"
