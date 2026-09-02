"""Unit tests for app.providers."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.providers.auth import AuthResult
from app.providers.auth_registry import register_builtin_strategies, registry
from app.providers.db import get_connection, init_db
from app.providers.encryption import EncryptionError, decrypt, encrypt, get_fernet
from app.providers.models import (
    ModelProviderCreate,
    ModelProviderUpdate,
    ProviderModelCreate,
    ProviderScope,
    ProviderType,
)
from app.providers.seed import seed_default_providers
from app.providers.store import ProviderStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temp path for the test DB; avoids polluting ./storage."""
    return tmp_path / "test_providers.db"


@pytest.fixture
def fernet() -> Fernet:
    """Return a fresh Fernet instance for each test."""
    return get_fernet(Fernet.generate_key().decode())


@pytest.fixture
def store(db_path: Path, fernet: Fernet) -> ProviderStore:
    """Return an initialised ProviderStore backed by a temp DB."""
    init_db(db_path)
    return ProviderStore(db_path=db_path, fernet=fernet)


@pytest.fixture
def custom_auth_store(db_path: Path, fernet: Fernet) -> Iterator[ProviderStore]:
    async def _resolve_custom(*_args: object, **_kwargs: object) -> AuthResult:
        return AuthResult()

    register_builtin_strategies()
    registered_here = not registry.has("signed_request")
    if registered_here:
        registry.register("signed_request", _resolve_custom)
    try:
        init_db(db_path)
        yield ProviderStore(db_path=db_path, fernet=fernet)
    finally:
        if registered_here:
            registry.unregister("signed_request")


@pytest.fixture
def ocr_provider(store: ProviderStore):  # 回傳 ModelProviderRow
    """A minimal OCR provider for reuse across tests."""
    return store.create_provider(
        ModelProviderCreate(
            name="OCR Engine",
            provider_type=ProviderType.engine_service,
            engine_category="ocr",
            base_url="http://ocr:8002",
        )
    )


# ---------------------------------------------------------------------------
# DB Layer Tests
# ---------------------------------------------------------------------------


class TestInitDb:
    def test_init_db_creates_db_file(self, db_path: Path) -> None:
        """init_db should create the SQLite file at db_path."""
        result = init_db(db_path)
        assert result == db_path
        assert db_path.exists()

    def test_init_db_creates_model_providers_table(self, db_path: Path) -> None:
        """After init_db, model_providers table must exist."""
        init_db(db_path)
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='model_providers'"
            ).fetchone()
        assert row is not None, "model_providers table not found"

    def test_init_db_idempotent(self, db_path: Path) -> None:
        """Calling init_db twice must not raise any exception."""
        init_db(db_path)
        init_db(db_path)  # second call — should be no-op

    def test_migration_sets_user_version(self, db_path: Path) -> None:
        """After init_db, PRAGMA user_version must match latest migration."""
        init_db(db_path)
        with get_connection(db_path) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 9

    def test_foreign_keys_enabled(self, db_path: Path) -> None:
        """get_connection must enable foreign key enforcement."""
        init_db(db_path)
        with get_connection(db_path) as conn:
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1, "PRAGMA foreign_keys should be 1 (ON)"

    def test_plugin_registered_after_init_can_create_provider(
        self,
        db_path: Path,
        fernet: Fernet,
    ) -> None:
        auth_type = "late_custom_after_init"

        async def _resolve_custom(*_args: object, **_kwargs: object) -> AuthResult:
            return AuthResult()

        register_builtin_strategies()
        assert not registry.has(auth_type)
        init_db(db_path)
        registry.register(auth_type, _resolve_custom)
        try:
            store = ProviderStore(db_path=db_path, fernet=fernet)
            row = store.create_provider(
                ModelProviderCreate(
                    name="Late custom auth",
                    provider_type=ProviderType.openai_compatible,
                    engine_category="vlm",
                    base_url="https://provider.example/v1",
                    auth_type=auth_type,
                )
            )
        finally:
            registry.unregister(auth_type)

        assert row.auth_type == auth_type


# ---------------------------------------------------------------------------
# Encryption Tests
# ---------------------------------------------------------------------------


class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self, fernet: Fernet) -> None:
        """decrypt(encrypt(k)) must equal the original key."""
        original = "my-secret-api-key-abc123"
        assert decrypt(encrypt(original, fernet), fernet) == original

    def test_encrypt_output_differs_from_plaintext(self, fernet: Fernet) -> None:
        """Encrypted output must not equal the original plaintext."""
        plaintext = "secret"
        assert encrypt(plaintext, fernet) != plaintext

    def test_decrypt_wrong_key_raises(self, fernet: Fernet) -> None:
        """Decrypting with a different key must raise EncryptionError."""
        other_fernet = get_fernet(Fernet.generate_key().decode())
        ciphertext = encrypt("secret", fernet)
        with pytest.raises(EncryptionError):
            decrypt(ciphertext, other_fernet)

    def test_decrypt_invalid_token_raises(self, fernet: Fernet) -> None:
        """Decrypting a non-Fernet string must raise EncryptionError."""
        with pytest.raises(EncryptionError):
            decrypt("not-a-valid-token", fernet)


# ---------------------------------------------------------------------------
# Provider CRUD Tests
# ---------------------------------------------------------------------------


class TestProviderCRUD:
    def test_input_models_reject_unregistered_auth_type(self) -> None:
        auth_type = "unregistered_auth_for_provider_test"
        assert not registry.has(auth_type)

        with pytest.raises(ValidationError, match="is not registered"):
            ModelProviderCreate(
                name="Unknown auth",
                provider_type=ProviderType.openai_compatible,
                engine_category="vlm",
                base_url="https://provider.example/v1",
                auth_type=auth_type,
            )
        with pytest.raises(ValidationError, match="is not registered"):
            ModelProviderUpdate(auth_type=auth_type)

    def test_scoped_provider_queries_separate_visible_mutable_and_runtime(
        self, store: ProviderStore
    ) -> None:
        system = store.create_provider(
            ModelProviderCreate(
                name="System OCR",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://system-ocr:8002",
                scope=ProviderScope.system,
            )
        )
        workspace_a = store.create_provider(
            ModelProviderCreate(
                name="Workspace A OCR",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://workspace-a-ocr:8002",
                scope=ProviderScope.workspace,
                workspace_id="ws-a",
            )
        )

        assert {row.id for row in store.list_visible("ws-a")} == {
            system.id,
            workspace_a.id,
        }
        assert [row.id for row in store.list_visible("ws-b")] == [system.id]
        assert [row.id for row in store.list_mutable("ws-a")] == [workspace_a.id]
        assert store.get_for_runtime(workspace_a.id, "ws-b") is None
        assert store.get_for_runtime(system.id, "ws-b") == system
        assert store.get_mutable(system.id, "ws-a") is None
        assert store.get_mutable(workspace_a.id, "ws-a") == workspace_a

    def test_explicit_provider_lookup_does_not_fallback_to_default(
        self, store: ProviderStore
    ) -> None:
        store.create_provider(
            ModelProviderCreate(
                name="System default",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://system-ocr:8002",
                is_default=True,
                scope=ProviderScope.system,
            )
        )

        assert store.get_for_runtime("missing-provider", "ws-a") is None

    def test_create_provider_basic(self, store: ProviderStore) -> None:
        """create_provider returns a row with a non-empty id."""
        row = store.create_provider(
            ModelProviderCreate(
                name="Test",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://ocr:8002",
            )
        )
        assert row.id
        assert row.name == "Test"

    def test_create_provider_stores_api_key_encrypted(self, store: ProviderStore) -> None:
        """api_key stored in DB must not equal the plaintext value."""
        row = store.create_provider(
            ModelProviderCreate(
                name="VLM",
                provider_type=ProviderType.openai_compatible,
                engine_category="vlm",
                base_url="http://vlm:8003",
                api_key="plain-secret",
            )
        )
        # The Row carries the encrypted value — not the plaintext
        assert row.api_key is not None
        assert row.api_key != "plain-secret"

    def test_get_api_key_decrypts(self, store: ProviderStore) -> None:
        """get_api_key must return the original plaintext."""
        row = store.create_provider(
            ModelProviderCreate(
                name="VLM",
                provider_type=ProviderType.openai_compatible,
                engine_category="vlm",
                base_url="http://vlm:8003",
                api_key="plain-secret",
            )
        )
        assert store.get_api_key(row.id) == "plain-secret"

    def test_get_api_key_none_when_no_key(self, store: ProviderStore, ocr_provider) -> None:
        """get_api_key returns None when no api_key was set."""
        assert store.get_api_key(ocr_provider.id) is None

    def test_get_provider_not_found(self, store: ProviderStore) -> None:
        """get_provider returns None for a nonexistent id."""
        assert store.get_provider("nonexistent-id") is None

    def test_list_providers_by_category(self, store: ProviderStore) -> None:
        """list_providers with category filters correctly."""
        store.create_provider(
            ModelProviderCreate(
                name="VLM 1",
                provider_type=ProviderType.openai_compatible,
                engine_category="vlm",
                base_url="http://vlm:8003",
            )
        )
        store.create_provider(
            ModelProviderCreate(
                name="VLM 2",
                provider_type=ProviderType.openai_compatible,
                engine_category="vlm",
                base_url="http://vlm:8003",
            )
        )
        store.create_provider(
            ModelProviderCreate(
                name="OCR 1",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://ocr:8002",
            )
        )
        assert len(store.list_providers(category="vlm")) == 2
        assert len(store.list_providers(category="ocr")) == 1

    def test_list_providers_enabled_only(self, store: ProviderStore) -> None:
        """enabled_only=True excludes disabled providers."""
        store.create_provider(
            ModelProviderCreate(
                name="Active",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://ocr:8002",
                is_enabled=True,
            )
        )
        store.create_provider(
            ModelProviderCreate(
                name="Disabled",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://ocr:8002",
                is_enabled=False,
            )
        )
        assert len(store.list_providers(enabled_only=True)) == 1
        assert len(store.list_providers(enabled_only=False)) == 2

    def test_update_provider_partial(self, store: ProviderStore, ocr_provider) -> None:
        """update_provider changes only the specified fields."""
        updated = store.update_provider(ocr_provider.id, ModelProviderUpdate(name="Updated OCR"))
        assert updated is not None
        assert updated.name == "Updated OCR"
        assert updated.base_url == ocr_provider.base_url  # unchanged

    def test_update_provider_api_key(self, store: ProviderStore, ocr_provider) -> None:
        """Updating api_key stores it encrypted; get_api_key decrypts correctly."""
        store.update_provider(ocr_provider.id, ModelProviderUpdate(api_key="new-key"))
        assert store.get_api_key(ocr_provider.id) == "new-key"

    def test_blank_api_key_update_preserves_existing_credential(self, store: ProviderStore) -> None:
        row = store.create_provider(
            ModelProviderCreate(
                name="Custom API",
                provider_type=ProviderType.openai_compatible,
                engine_category="vlm",
                base_url="https://provider.example/v1",
                api_key="existing-key",
            )
        )

        store.update_provider(row.id, ModelProviderUpdate(api_key="  "))

        assert store.get_api_key(row.id) == "existing-key"

        store.update_provider(row.id, ModelProviderUpdate(api_key=None))
        assert store.get_api_key(row.id) is None

    def test_partial_auth_config_update_preserves_omitted_secret(
        self, custom_auth_store: ProviderStore, fernet: Fernet
    ) -> None:
        row = custom_auth_store.create_provider(
            ModelProviderCreate(
                name="Custom Auth",
                provider_type=ProviderType.openai_compatible,
                engine_category="vlm",
                base_url="https://provider.example/v1",
                auth_type="signed_request",
                auth_config={
                    "client_id": "client-before",
                    "client_secret": "secret-before",
                },
            )
        )

        updated = custom_auth_store.update_provider(
            row.id,
            ModelProviderUpdate(auth_config={"client_id": "client-after"}),
        )

        assert updated is not None
        assert updated.auth_config is not None
        auth_config = json.loads(updated.auth_config)
        assert auth_config["client_id"] == "client-after"
        assert decrypt(auth_config["client_secret"], fernet) == "secret-before"

        blank_secret = custom_auth_store.update_provider(
            row.id,
            ModelProviderUpdate(auth_config={"client_secret": ""}),
        )
        assert blank_secret is not None
        assert blank_secret.auth_config is not None
        preserved = json.loads(blank_secret.auth_config)
        assert decrypt(preserved["client_secret"], fernet) == "secret-before"

        cleared = custom_auth_store.update_provider(
            row.id,
            ModelProviderUpdate(auth_config=None),
        )
        assert cleared is not None
        assert cleared.auth_config is None

    def test_update_provider_not_found(self, store: ProviderStore) -> None:
        """update_provider returns None for a nonexistent id."""
        result = store.update_provider("bad-id", ModelProviderUpdate(name="X"))
        assert result is None

    def test_delete_provider(self, store: ProviderStore, ocr_provider) -> None:
        """delete_provider returns True and the row is gone."""
        assert store.delete_provider(ocr_provider.id) is True
        assert store.get_provider(ocr_provider.id) is None

    def test_delete_provider_cascades_models(self, store: ProviderStore, ocr_provider) -> None:
        """Deleting a provider must cascade-delete its models."""
        store.add_model(ocr_provider.id, ProviderModelCreate(model_id="m1", display_name="Model 1"))
        store.delete_provider(ocr_provider.id)
        assert store.list_models(ocr_provider.id) == []

    def test_delete_provider_not_found(self, store: ProviderStore) -> None:
        """delete_provider returns False for a nonexistent id."""
        assert store.delete_provider("nonexistent") is False


# ---------------------------------------------------------------------------
# Default Management Tests
# ---------------------------------------------------------------------------


class TestDefaultManagement:
    def test_set_default_replaces_previous(self, store: ProviderStore) -> None:
        """set_default must unset the previous default in the same category."""
        p1 = store.create_provider(
            ModelProviderCreate(
                name="OCR 1",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://ocr:8002",
                is_default=True,
            )
        )
        p2 = store.create_provider(
            ModelProviderCreate(
                name="OCR 2",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://ocr:8002",
            )
        )
        store.set_default(p2.id, "ocr")
        assert store.get_provider(p1.id).is_default is False  # type: ignore[union-attr]
        assert store.get_provider(p2.id).is_default is True  # type: ignore[union-attr]

    def test_set_default_cross_category_isolation(self, store: ProviderStore) -> None:
        """Setting default in vlm must not affect ocr default."""
        _vlm = store.create_provider(
            ModelProviderCreate(
                name="VLM",
                provider_type=ProviderType.openai_compatible,
                engine_category="vlm",
                base_url="http://vlm:8003",
                is_default=True,
            )
        )
        ocr = store.create_provider(
            ModelProviderCreate(
                name="OCR",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://ocr:8002",
                is_default=True,
            )
        )
        # Add another vlm and make it default — ocr should stay unchanged
        vlm2 = store.create_provider(
            ModelProviderCreate(
                name="VLM 2",
                provider_type=ProviderType.openai_compatible,
                engine_category="vlm",
                base_url="http://vlm:8003",
            )
        )
        store.set_default(vlm2.id, "vlm")
        assert store.get_provider(ocr.id).is_default is True  # type: ignore[union-attr]

    def test_get_default_provider(self, store: ProviderStore) -> None:
        """get_default_provider returns the current default for a category."""
        p = store.create_provider(
            ModelProviderCreate(
                name="OCR",
                provider_type=ProviderType.engine_service,
                engine_category="ocr",
                base_url="http://ocr:8002",
                is_default=True,
            )
        )
        default = store.get_default_provider("ocr")
        assert default is not None
        assert default.id == p.id

    def test_get_default_provider_none(self, store: ProviderStore) -> None:
        """get_default_provider returns None when no default is set."""
        assert store.get_default_provider("nonexistent_category") is None


# ---------------------------------------------------------------------------
# Model Sub-Table Tests
# ---------------------------------------------------------------------------


class TestModelSubTable:
    def test_add_model(self, store: ProviderStore, ocr_provider) -> None:
        """add_model makes the model visible via list_models."""
        model = store.add_model(
            ocr_provider.id,
            ProviderModelCreate(
                model_id="m1",
                display_name="Model 1",
            ),
        )
        assert model.model_id == "m1"
        assert len(store.list_models(ocr_provider.id)) == 1

    def test_add_model_invalid_provider(self, store: ProviderStore) -> None:
        """add_model with nonexistent provider_id must raise ValueError."""
        with pytest.raises(ValueError):
            store.add_model("bad-id", ProviderModelCreate(model_id="m1", display_name="Model 1"))

    def test_list_all_models_by_category(self, store: ProviderStore, ocr_provider) -> None:
        """list_all_models with category filters to the given category."""
        store.add_model(ocr_provider.id, ProviderModelCreate(model_id="m1", display_name="Model 1"))
        results = store.list_all_models(category="ocr")
        assert len(results) == 1
        assert results[0]["provider_name"] == "OCR Engine"

    def test_list_all_models_empty(self, store: ProviderStore) -> None:
        """list_all_models returns [] when no models exist."""
        assert store.list_all_models() == []


# ---------------------------------------------------------------------------
# Seed Tests
# ---------------------------------------------------------------------------


class TestSeed:
    def test_seed_inserts_all_defaults(self, store: ProviderStore) -> None:
        """seed_default_providers inserts exactly 8 providers."""
        count = seed_default_providers(store)
        assert count == 8
        assert len(store.list_providers(enabled_only=False)) == 8

    def test_seed_inserts_ocr_provider(self, store: ProviderStore) -> None:
        """Seeding must include an OCR provider."""
        seed_default_providers(store)
        all_providers = store.list_providers(enabled_only=False)
        ocr = next(p for p in all_providers if p.engine_category == "ocr")
        assert ocr.name == "RapidOCR"
        assert ocr.is_default is True

    def test_seed_inserts_docling_provider(self, store: ProviderStore) -> None:
        """Seeding must include a Docling provider."""
        seed_default_providers(store)
        all_providers = store.list_providers(enabled_only=False)
        docling = next(p for p in all_providers if p.engine_category == "docling")
        assert docling.name == "Docling"
        assert docling.is_default is True
        assert docling.provider_type == "engine_service"

    def test_seed_idempotent(self, store: ProviderStore) -> None:
        """Calling seed twice must not duplicate providers."""
        seed_default_providers(store)
        count2 = seed_default_providers(store)
        assert count2 == 0
        assert len(store.list_providers(enabled_only=False)) == 8
