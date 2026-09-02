"""Provider Store — SQLite-backed CRUD for model_providers and provider_models.

All API keys are stored encrypted (Fernet symmetric encryption).
JSON columns (auth_config, config_schema, extra_config, capabilities,
default_config) are persisted as JSON strings and returned as-is from
*Row / *Response models.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from cryptography.fernet import Fernet

from app.providers.db import get_connection
from app.providers.encryption import EncryptionError, decrypt, encrypt  # noqa: F401
from app.providers.models import (
    DEFAULT_LLM_MODEL_CONTEXT_WINDOW,
    DEFAULT_LLM_MODEL_MAX_TOKENS,
    ApiProtocol,
    ApiStyle,
    ModelProviderCreate,
    ModelProviderRow,
    ModelProviderUpdate,
    ProviderModelCreate,
    ProviderModelResponse,
    ProviderScope,
    ProviderType,
    normalize_llm_api_protocol,
    normalize_provider_protocol,
    validate_llm_model_capabilities,
)


class ProviderDefaultRequiredError(Exception):
    pass


class ProviderStore:
    """Thin data-access layer for the provider registry.

    All mutations are performed inside a single ``get_connection`` transaction
    (auto-commit on success, auto-rollback on exception).
    """

    def __init__(self, db_path: Path, fernet: Fernet) -> None:
        self._db_path = db_path
        self._fernet = fernet

    @property
    def fernet(self) -> Fernet:
        return self._fernet

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _serialize_json(self, value: dict | None) -> str | None:
        """Serialize a dict to JSON string, or return None."""
        if value is None:
            return None
        return json.dumps(value)

    # ------------------------------------------------------------------
    # Provider CRUD
    # ------------------------------------------------------------------

    def create_provider(self, data: ModelProviderCreate) -> ModelProviderRow:
        """Insert a new provider row and return the persisted record.

        A newly nonempty enabled scope/category receives its first default.
        """
        provider_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        encrypted_key: str | None
        if data.api_key is not None:
            encrypted_key = encrypt(data.api_key, self._fernet)
        else:
            encrypted_key = None

        # Encrypt client_secret inside auth_config before serializing
        auth_config_to_store = data.auth_config
        if auth_config_to_store and "client_secret" in auth_config_to_store:
            auth_config_to_store = dict(auth_config_to_store)
            client_secret = auth_config_to_store["client_secret"]
            if client_secret is None or not str(client_secret).strip():
                auth_config_to_store.pop("client_secret")
            else:
                auth_config_to_store["client_secret"] = encrypt(
                    str(client_secret),
                    self._fernet,
                )

        auth_config_json = self._serialize_json(auth_config_to_store)
        config_schema_json = self._serialize_json(data.config_schema)
        extra_config_json = self._serialize_json(data.extra_config)

        with get_connection(self._db_path) as conn:
            has_default = (
                conn.execute(
                    """
                SELECT 1 FROM model_providers
                 WHERE engine_category = ? AND scope = ? AND workspace_id IS ?
                   AND is_default = 1 AND is_enabled = 1
                """,
                    (data.engine_category, data.scope.value, data.workspace_id),
                ).fetchone()
                is not None
            )
            is_default = data.is_enabled and (data.is_default or not has_default)
            if is_default:
                conn.execute(
                    """
                    UPDATE model_providers
                       SET is_default = 0
                     WHERE engine_category = ? AND scope = ? AND workspace_id IS ?
                       AND is_default = 1
                    """,
                    (data.engine_category, data.scope.value, data.workspace_id),
                )
            if data.is_chatbot_default:
                conn.execute(
                    """UPDATE model_providers SET is_chatbot_default = 0
                       WHERE provider_type = 'llm_api' AND scope = ? AND workspace_id IS ?
                         AND is_chatbot_default = 1""",
                    (data.scope.value, data.workspace_id),
                )

            conn.execute(
                """
                INSERT INTO model_providers (
                    id, name, provider_type, engine_category,
                    base_url, api_style, api_version, api_protocol, api_key,
                    model_id, model_display_name, model_context_window,
                    model_max_tokens, model_reasoning,
                    auth_type, auth_config,
                    is_enabled, is_default, is_chatbot_default,
                    response_format, config_schema, extra_config,
                    health_url, created_at, updated_at, scope, workspace_id
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    provider_id,
                    data.name,
                    data.provider_type.value,
                    data.engine_category,
                    data.base_url,
                    data.api_style.value if data.api_style is not None else None,
                    data.api_version,
                    data.api_protocol.value if data.api_protocol is not None else None,
                    encrypted_key,
                    data.model_id,
                    data.model_display_name,
                    data.model_context_window,
                    data.model_max_tokens,
                    int(data.model_reasoning) if data.model_reasoning is not None else None,
                    data.auth_type,
                    auth_config_json,
                    int(data.is_enabled),
                    int(is_default),
                    int(data.is_chatbot_default),
                    data.response_format.value,
                    config_schema_json,
                    extra_config_json,
                    data.health_url,
                    now,
                    now,
                    data.scope.value,
                    data.workspace_id,
                ),
            )

        result = self.get_provider(provider_id)
        assert result is not None, f"Provider {provider_id!r} not found after INSERT"
        return result

    def get_provider(self, provider_id: str) -> ModelProviderRow | None:
        """Return a single provider by primary key, or None if not found."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM model_providers WHERE id = ?",
                (provider_id,),
            ).fetchone()

        if row is None:
            return None
        return ModelProviderRow(**dict(row))

    def get_for_runtime(self, provider_id: str, workspace_id: str) -> ModelProviderRow | None:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM model_providers
                 WHERE id = ?
                   AND (scope = 'system' OR (scope = 'workspace' AND workspace_id = ?))
                """,
                (provider_id, workspace_id),
            ).fetchone()
        return None if row is None else ModelProviderRow(**dict(row))

    def get_mutable(self, provider_id: str, workspace_id: str) -> ModelProviderRow | None:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM model_providers
                 WHERE id = ? AND scope = 'workspace' AND workspace_id = ?
                """,
                (provider_id, workspace_id),
            ).fetchone()
        return None if row is None else ModelProviderRow(**dict(row))

    def list_visible(
        self,
        workspace_id: str,
        category: str | None = None,
        provider_type: str | None = None,
        enabled_only: bool = True,
    ) -> list[ModelProviderRow]:
        conditions = ["(scope = 'system' OR (scope = 'workspace' AND workspace_id = ?))"]
        params: list[object] = [workspace_id]
        if category is not None:
            conditions.append("engine_category = ?")
            params.append(category)
        if provider_type is not None:
            conditions.append("provider_type = ?")
            params.append(provider_type)
        if enabled_only:
            conditions.append("is_enabled = 1")
        sql = "SELECT * FROM model_providers WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at"
        with get_connection(self._db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [ModelProviderRow(**dict(row)) for row in rows]

    def list_mutable(self, workspace_id: str) -> list[ModelProviderRow]:
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM model_providers
                 WHERE scope = 'workspace' AND workspace_id = ?
                 ORDER BY created_at
                """,
                (workspace_id,),
            ).fetchall()
        return [ModelProviderRow(**dict(row)) for row in rows]

    def list_providers(
        self,
        category: str | None = None,
        provider_type: str | None = None,
        enabled_only: bool = True,
    ) -> list[ModelProviderRow]:
        """Return providers, optionally filtered by category, provider_type and enabled flag."""
        conditions: list[str] = []
        params: list[object] = []

        if category is not None:
            conditions.append("engine_category = ?")
            params.append(category)

        if provider_type is not None:
            conditions.append("provider_type = ?")
            params.append(provider_type)

        if enabled_only:
            conditions.append("is_enabled = 1")

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"SELECT * FROM model_providers {where_clause} ORDER BY created_at"

        with get_connection(self._db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [ModelProviderRow(**dict(row)) for row in rows]

    def update_provider(
        self,
        provider_id: str,
        data: ModelProviderUpdate,
    ) -> ModelProviderRow | None:
        """Partially update a provider.  Returns None if the provider does not exist."""
        existing = self.get_provider(provider_id)
        if existing is None:
            return None

        updates: dict[str, object] = data.model_dump(exclude_unset=True)

        if not updates:
            return existing

        updates = self._validated_protocol_updates(existing, updates)

        # A blank edit field means "credential not supplied". Explicit null
        # remains the API contract for clearing a stored API key.
        if "api_key" in updates and isinstance(updates["api_key"], str):
            if not updates["api_key"].strip():
                updates.pop("api_key")
            else:
                updates["api_key"] = encrypt(str(updates["api_key"]), self._fernet)

        # Auth plugin forms only receive public config fields. Merge partial
        # edits with the stored object so an omitted secret remains encrypted
        # exactly once; auth_config=null still explicitly clears everything.
        if "auth_config" in updates and isinstance(updates["auth_config"], dict):
            incoming = dict(updates["auth_config"])
            stored: dict[str, object] = {}
            if existing.auth_config:
                try:
                    parsed = json.loads(existing.auth_config)
                    if isinstance(parsed, dict):
                        stored = parsed
                except (json.JSONDecodeError, TypeError):
                    stored = {}

            secret_missing = object()
            client_secret = incoming.pop("client_secret", secret_missing)
            stored.update(incoming)
            if client_secret is None:
                stored.pop("client_secret", None)
            elif client_secret is not secret_missing and str(client_secret).strip():
                stored["client_secret"] = encrypt(str(client_secret), self._fernet)
            updates["auth_config"] = stored

        # Serialize JSON dict columns
        for json_col in ("auth_config", "config_schema", "extra_config"):
            if json_col in updates and isinstance(updates[json_col], dict):
                updates[json_col] = json.dumps(updates[json_col])

        # Coerce enums to their string values so SQLite accepts them
        for enum_col in (
            "provider_type",
            "api_style",
            "api_protocol",
            "auth_type",
            "response_format",
        ):
            if enum_col in updates:
                val = updates[enum_col]
                if isinstance(val, Enum):
                    updates[enum_col] = val.value

        # Coerce bools to int for SQLite
        for bool_col in (
            "is_enabled",
            "is_default",
            "is_chatbot_default",
            "model_reasoning",
        ):
            if bool_col in updates:
                value = updates[bool_col]
                updates[bool_col] = int(bool(value)) if value is not None else None

        runtime_fields = {
            "provider_type",
            "base_url",
            "api_protocol",
            "api_key",
            "model_id",
            "model_context_window",
            "model_max_tokens",
            "model_reasoning",
            "auth_type",
            "auth_config",
            "is_enabled",
        }
        if runtime_fields.intersection(updates) and (
            existing.provider_type == ProviderType.llm_api
            or updates.get("provider_type") == ProviderType.llm_api.value
        ):
            # A successful readiness probe describes one exact runtime
            # configuration. Any invocation-affecting edit makes it stale.
            updates["chatbot_ready"] = 0

        updates["updated_at"] = datetime.now(timezone.utc).isoformat()

        set_clause = ", ".join(f"{col} = ?" for col in updates)
        values = list(updates.values()) + [provider_id]

        # Perform default-clearing and the actual UPDATE in a single transaction
        with get_connection(self._db_path) as conn:
            if updates.get("is_default") == 1:
                category = existing.engine_category
                # If engine_category is being changed, use the new one
                if "engine_category" in updates:
                    category = str(updates["engine_category"])
                conn.execute(
                    """
                    UPDATE model_providers
                       SET is_default = 0
                     WHERE engine_category = ? AND scope = ? AND workspace_id IS ?
                       AND is_default = 1 AND id != ?
                    """,
                    (category, existing.scope.value, existing.workspace_id, provider_id),
                )
            if updates.get("is_chatbot_default") == 1:
                conn.execute(
                    """UPDATE model_providers SET is_chatbot_default = 0
                       WHERE provider_type = 'llm_api' AND scope = ? AND workspace_id IS ?
                         AND is_chatbot_default = 1 AND id != ?""",
                    (existing.scope.value, existing.workspace_id, provider_id),
                )
            conn.execute(
                f"UPDATE model_providers SET {set_clause} WHERE id = ?",  # noqa: S608
                values,
            )

        return self.get_provider(provider_id)

    def _validated_protocol_updates(
        self,
        existing: ModelProviderRow,
        updates: dict[str, object],
    ) -> dict[str, object]:
        """Validate protocol fields against the complete prospective row."""

        provider_type_raw = updates.get("provider_type", existing.provider_type)
        provider_type = (
            provider_type_raw
            if isinstance(provider_type_raw, ProviderType)
            else ProviderType(str(provider_type_raw))
        )
        style_raw = updates.get("api_style", existing.api_style)
        if style_raw is not None and not isinstance(style_raw, (ApiStyle, str)):
            raise ValueError("api_style must be openai or azure_openai")
        version_raw = updates.get("api_version", existing.api_version)
        version = str(version_raw) if version_raw is not None else None
        protocol_raw = updates.get(
            "api_protocol",
            None
            if "provider_type" in updates and provider_type != ProviderType.llm_api
            else existing.api_protocol,
        )
        if protocol_raw is None:
            protocol_input: ApiProtocol | str | None = None
        elif isinstance(protocol_raw, (ApiProtocol, str)):
            protocol_input = protocol_raw
        else:
            raise ValueError("api_protocol must be a supported llm_api protocol")
        protocol = normalize_llm_api_protocol(provider_type, protocol_input)
        model_id_raw = updates.get("model_id", existing.model_id)
        if provider_type == ProviderType.llm_api and (
            not isinstance(model_id_raw, str) or not model_id_raw.strip()
        ):
            raise ValueError("llm_api providers require model_id")
        capability_fields = (
            "model_context_window",
            "model_max_tokens",
            "model_reasoning",
        )
        if provider_type == ProviderType.llm_api:
            context_window = updates.get(
                "model_context_window",
                existing.model_context_window or DEFAULT_LLM_MODEL_CONTEXT_WINDOW,
            )
            max_tokens = updates.get(
                "model_max_tokens",
                existing.model_max_tokens or DEFAULT_LLM_MODEL_MAX_TOKENS,
            )
            reasoning = updates.get(
                "model_reasoning",
                existing.model_reasoning if existing.model_reasoning is not None else False,
            )
            context_window, max_tokens, reasoning = validate_llm_model_capabilities(
                context_window,
                max_tokens,
                reasoning,
            )
            if "provider_type" in updates or any(field in updates for field in capability_fields):
                updates.update(
                    model_context_window=context_window,
                    model_max_tokens=max_tokens,
                    model_reasoning=reasoning,
                )
        elif any(updates.get(field) is not None for field in capability_fields):
            raise ValueError("only llm_api providers can set model capability metadata")
        elif "provider_type" in updates:
            updates.update(
                model_id=None,
                model_display_name=None,
                model_context_window=None,
                model_max_tokens=None,
                model_reasoning=None,
            )
        scope_raw = updates.get("scope", existing.scope)
        scope = scope_raw if isinstance(scope_raw, ProviderScope) else ProviderScope(str(scope_raw))
        chatbot_default_raw = updates.get(
            "is_chatbot_default",
            existing.is_chatbot_default,
        )
        if bool(chatbot_default_raw) and (
            provider_type != ProviderType.llm_api or scope != ProviderScope.workspace
        ):
            raise ValueError("only workspace llm_api providers can be chatbot default")

        if provider_type == ProviderType.openai_compatible and style_raw is None:
            style_raw = ApiStyle.openai

        style, version = normalize_provider_protocol(
            provider_type,
            style_raw,
            version,
            default_openai_style=True,
        )

        if updates.get("api_style") in {ApiStyle.openai, ApiStyle.openai.value} and (
            "api_version" not in updates
        ):
            version = None

        if "provider_type" in updates or "api_style" in updates:
            updates["api_style"] = style
        if "provider_type" in updates or "api_style" in updates or "api_version" in updates:
            updates["api_version"] = version
        if "provider_type" in updates or "api_protocol" in updates:
            updates["api_protocol"] = protocol
        return updates

    def delete_provider(self, provider_id: str, workspace_id: str | None = None) -> bool:
        with get_connection(self._db_path) as conn:
            existing = conn.execute(
                "SELECT * FROM model_providers WHERE id = ?", (provider_id,)
            ).fetchone()
            if existing is None:
                return False
            if existing["is_default"] and existing["scope"] in {
                ProviderScope.system.value,
                ProviderScope.workspace.value,
            }:
                replacement = conn.execute(
                    """
                    SELECT id FROM model_providers
                     WHERE engine_category = ? AND scope = ? AND workspace_id IS ?
                       AND is_enabled = 1 AND id != ?
                     ORDER BY created_at, id
                     LIMIT 1
                    """,
                    (
                        existing["engine_category"],
                        existing["scope"],
                        existing["workspace_id"],
                        provider_id,
                    ),
                ).fetchone()
                system_fallback = conn.execute(
                    """
                    SELECT 1 FROM model_providers
                     WHERE engine_category = ? AND scope = ?
                       AND is_enabled = 1 AND is_default = 1 AND id != ?
                    """,
                    (existing["engine_category"], ProviderScope.system.value, provider_id),
                ).fetchone()
                has_fallback = (
                    existing["scope"] == ProviderScope.workspace.value
                    and system_fallback is not None
                )
                if replacement is None and not has_fallback:
                    raise ProviderDefaultRequiredError(
                        "Delete another enabled provider or configure a system default first."
                    )
                if replacement is not None:
                    conn.execute(
                        "UPDATE model_providers SET is_default = 0 WHERE id = ?",
                        (provider_id,),
                    )
                    conn.execute(
                        "UPDATE model_providers SET is_default = 1 WHERE id = ?",
                        (replacement["id"],),
                    )
            cursor = conn.execute(
                "DELETE FROM model_providers WHERE id = ?",
                (provider_id,),
            )
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Default management
    # ------------------------------------------------------------------

    def set_default(self, provider_id: str, category: str | None = None) -> None:
        existing = self.get_provider(provider_id)
        if existing is None or not existing.is_enabled:
            raise ProviderDefaultRequiredError("Only enabled providers can be defaults.")
        if category is not None and category != existing.engine_category:
            raise ProviderDefaultRequiredError(
                "Provider category does not match the requested default."
            )
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE model_providers
                   SET is_default = 0
                 WHERE engine_category = ? AND scope = ? AND workspace_id IS ?
                   AND is_default = 1
                """,
                (existing.engine_category, existing.scope.value, existing.workspace_id),
            )
            conn.execute(
                "UPDATE model_providers SET is_default = 1 WHERE id = ?",
                (provider_id,),
            )

    def get_default_provider(
        self, category: str, workspace_id: str | None = None
    ) -> ModelProviderRow | None:
        with get_connection(self._db_path) as conn:
            if workspace_id is None:
                row = conn.execute(
                    """
                    SELECT * FROM model_providers
                     WHERE engine_category = ? AND is_default = 1 AND is_enabled = 1
                     ORDER BY created_at, id
                     LIMIT 1
                    """,
                    (category,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM model_providers
                     WHERE engine_category = ? AND is_default = 1 AND is_enabled = 1
                       AND (
                           (scope = 'workspace' AND workspace_id = ?)
                           OR scope = 'system'
                       )
                     ORDER BY CASE scope WHEN 'workspace' THEN 0 ELSE 1 END
                     LIMIT 1
                    """,
                    (category, workspace_id),
                ).fetchone()

        if row is None:
            return None
        return ModelProviderRow(**dict(row))

    # ------------------------------------------------------------------
    # API key
    # ------------------------------------------------------------------

    def set_chatbot_ready(
        self,
        provider_id: str,
        chatbot_ready: bool,
        workspace_id: str,
    ) -> bool:
        """Persist readiness only for a workspace-owned llm_api Provider."""

        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                """UPDATE model_providers
                      SET chatbot_ready = ?
                    WHERE id = ?
                      AND provider_type = 'llm_api'
                      AND scope = 'workspace'
                      AND workspace_id = ?""",
                (int(chatbot_ready), provider_id, workspace_id),
            )
        return cursor.rowcount == 1

    def get_api_key(self, provider_id: str) -> str | None:
        """Return the decrypted API key for *provider_id*, or None.

        Raises:
            EncryptionError: If the stored ciphertext cannot be decrypted.
        """
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT api_key FROM model_providers WHERE id = ?",
                (provider_id,),
            ).fetchone()

        if row is None or row["api_key"] is None:
            return None

        return decrypt(row["api_key"], self._fernet)

    # ------------------------------------------------------------------
    # Provider model sub-table
    # ------------------------------------------------------------------

    def add_model(
        self,
        provider_id: str,
        model_data: ProviderModelCreate,
    ) -> ProviderModelResponse:
        """Add a model entry under *provider_id*.

        Raises:
            ValueError: If the provider does not exist, or if the
                (provider_id, model_id) pair already exists.
        """
        if self.get_provider(provider_id) is None:
            raise ValueError(f"Provider {provider_id!r} not found")

        model_row_id = str(uuid.uuid4())
        capabilities_json = self._serialize_json(model_data.capabilities)
        default_config_json = self._serialize_json(model_data.default_config)

        try:
            with get_connection(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO provider_models (
                        id, provider_id, model_id, display_name,
                        is_enabled, capabilities, default_config,
                        model_group, sort_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        model_row_id,
                        provider_id,
                        model_data.model_id,
                        model_data.display_name,
                        int(model_data.is_enabled),
                        capabilities_json,
                        default_config_json,
                        model_data.model_group,
                        model_data.sort_order,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"Model {model_data.model_id!r} already exists for provider {provider_id!r}"
            ) from exc

        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM provider_models WHERE id = ?",
                (model_row_id,),
            ).fetchone()

        assert row is not None, f"provider_models row {model_row_id!r} missing after INSERT"
        return ProviderModelResponse(**dict(row))

    def remove_model(self, provider_id: str, model_id: str) -> bool:
        """Delete a single model from a provider. Returns True if deleted."""
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM provider_models WHERE provider_id = ? AND id = ?",
                (provider_id, model_id),
            )
        return cursor.rowcount > 0

    def list_models(self, provider_id: str) -> list[ProviderModelResponse]:
        """Return all models for *provider_id* ordered by sort_order, display_name."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM provider_models
                 WHERE provider_id = ?
                 ORDER BY sort_order, display_name
                """,
                (provider_id,),
            ).fetchall()

        return [ProviderModelResponse(**dict(row)) for row in rows]

    def toggle_model(
        self,
        provider_id: str,
        model_id: str,
        is_enabled: bool,
    ) -> ProviderModelResponse | None:
        """Toggle a model's ``is_enabled`` flag.

        Returns the updated model, or ``None`` if the model was not found.
        """
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE provider_models
                   SET is_enabled = ?
                 WHERE provider_id = ? AND id = ?
                """,
                (int(is_enabled), provider_id, model_id),
            )
            if conn.total_changes == 0:
                return None
            row = conn.execute(
                "SELECT * FROM provider_models WHERE id = ?",
                (model_id,),
            ).fetchone()
        if row is None:
            return None
        return ProviderModelResponse(**dict(row))

    def list_all_models(
        self, category: str | None = None, workspace_id: str | None = None
    ) -> list[dict]:
        """Return a flat list of models joined with their provider info.

        Only models belonging to *enabled* providers are included.
        Optionally filtered by *category*.
        """
        sql = """
            SELECT pm.id,
                   pm.provider_id,
                   mp.name          AS provider_name,
                   mp.engine_category,
                   pm.model_id,
                   pm.display_name,
                   pm.model_group,
                   pm.is_enabled
              FROM provider_models pm
              JOIN model_providers mp ON pm.provider_id = mp.id
             WHERE mp.is_enabled = 1
        """
        params: list[object] = []

        if workspace_id is not None:
            sql += " AND (mp.scope = 'system' OR (mp.scope = 'workspace' AND mp.workspace_id = ?))"
            params.append(workspace_id)

        if category is not None:
            sql += " AND mp.engine_category = ?"
            params.append(category)

        sql += " ORDER BY mp.engine_category, pm.sort_order, pm.display_name"

        with get_connection(self._db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [dict(row) for row in rows]
