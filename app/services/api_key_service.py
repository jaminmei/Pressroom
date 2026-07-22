"""API key service: issuance, verification, revocation.

Self-check: ``python -m app.services.api_key_service``.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.repositories.api_key_repository import ApiKeyRecord, ApiKeyRepository

_KEY_PREFIX = "dca_"
_KEY_PREFIX_DISPLAY_LEN = 12  # first 12 chars, e.g. "dca_a1b2c3d4"


def hash_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def generate_key() -> tuple[str, str, str]:
    """Return ``(full_key, key_hash, key_prefix)``.

    The full key is returned exactly once at issuance; only its hash is stored.
    """
    random_part = secrets.token_urlsafe(24)  # ~32 urlsafe chars
    full_key = _KEY_PREFIX + random_part
    key_hash = hash_key(full_key)
    key_prefix = full_key[:_KEY_PREFIX_DISPLAY_LEN]
    return full_key, key_hash, key_prefix


class ApiKeyVerificationError(Exception):
    """Raised when an API key is missing, unknown, revoked, or expired."""

    def __init__(self, message: str = "invalid api key", *, code: str = "invalid") -> None:
        super().__init__(message)
        self.code: str = code


@dataclass(slots=True)
class VerifiedApiKey:
    id: str
    workflow_id: str
    key_prefix: str
    workspace_id: str | None = None


class ApiKeyService:
    def __init__(self, repository: ApiKeyRepository | None = None) -> None:
        self._repository = repository or ApiKeyRepository()

    async def issue(
        self,
        *,
        workflow_id: str,
        workspace_id: str | None = None,
        description: str | None = None,
        created_by: str | None = None,
        expires_at: datetime | None = None,
    ) -> tuple[str, ApiKeyRecord]:
        full_key, key_hash, key_prefix = generate_key()
        record = await self._repository.create(
            id=str(uuid4()),
            key_hash=key_hash,
            key_prefix=key_prefix,
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            description=description,
            created_by=created_by,
            expires_at=expires_at,
        )
        return full_key, record

    async def verify(self, full_key: str) -> VerifiedApiKey:
        if full_key.startswith("Bearer "):
            full_key = full_key[len("Bearer ") :].strip()

        key_hash = hash_key(full_key)
        record = await self._repository.get_by_hash_for_auth(key_hash)
        if record is None:
            raise ApiKeyVerificationError("invalid api key", code="invalid")

        if not record.is_active:
            raise ApiKeyVerificationError("api key revoked", code="revoked")

        if record.expires_at is not None:
            expires_at = record.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                raise ApiKeyVerificationError("api key expired", code="expired")

        # Best-effort: refresh last_used_at
        try:
            await self._repository.touch_last_used_for_auth(record.id, datetime.now(timezone.utc))
        except Exception:
            pass

        return VerifiedApiKey(
            id=record.id,
            workflow_id=record.workflow_id,
            key_prefix=record.key_prefix,
            workspace_id=record.workspace_id,
        )

    async def revoke(self, id: str, *, workspace_id: str | None = None) -> bool:
        return await self._repository.set_active(id, False, workspace_id=workspace_id)

    async def list_paginated(
        self,
        limit: int,
        offset: int,
        *,
        workspace_id: str | None = None,
        include_inactive: bool = True,
    ) -> tuple[list[ApiKeyRecord], int]:
        records = await self._repository.list_all(
            limit=limit,
            offset=offset,
            workspace_id=workspace_id,
            include_inactive=include_inactive,
        )
        total = await self._repository.count(
            workspace_id=workspace_id,
            include_inactive=include_inactive,
        )
        return records, total

    async def list_by_workflow_paginated(
        self,
        workflow_id: str,
        limit: int,
        offset: int,
        *,
        include_inactive: bool = True,
        workspace_id: str | None = None,
    ) -> tuple[list[ApiKeyRecord], int]:
        records = await self._repository.list_by_workflow(
            workflow_id,
            workspace_id=workspace_id,
        )
        if not include_inactive:
            records = [record for record in records if record.is_active]
        return records[offset : offset + limit], len(records)

    async def get_by_id(self, id: str, *, workspace_id: str | None = None) -> ApiKeyRecord | None:
        return await self._repository.get_by_id(id, workspace_id=workspace_id)


if __name__ == "__main__":
    # --- pure-function checks ---
    full, h, prefix = generate_key()
    assert full.startswith("dca_"), f"prefix wrong: {full[:8]}"
    assert len(full) > 30, f"key too short: {len(full)}"
    assert prefix.startswith("dca_"), f"display prefix wrong: {prefix}"
    assert hash_key(full) == h, "hash not deterministic"
    assert len(h) == 64, f"hash length wrong: {len(h)}"

    # --- stub repository for verify round-trip ---
    now = datetime.now(timezone.utc)

    class _FakeRepo:
        def __init__(self, record: ApiKeyRecord) -> None:
            self._record = record

        async def get_by_hash_for_auth(self, key_hash: str) -> ApiKeyRecord | None:
            if hmac.compare_digest(key_hash, h):
                return self._record
            return None

        async def touch_last_used_for_auth(self, id: str, when: datetime) -> None:
            pass

    base = ApiKeyRecord(
        id="x",
        key_hash=h,
        key_prefix=prefix,
        workflow_id="wf_test",
        description=None,
        created_by=None,
        created_at=now,
        expires_at=None,
        is_active=True,
        last_used_at=None,
    )

    # valid verify
    svc = ApiKeyService(repository=_FakeRepo(base))  # type: ignore[arg-type]
    verified = asyncio.run(svc.verify(full))
    assert verified.workflow_id == "wf_test"
    assert verified.key_prefix == prefix

    # revoked key
    revoked = ApiKeyRecord(
        id=base.id,
        key_hash=base.key_hash,
        key_prefix=base.key_prefix,
        workflow_id=base.workflow_id,
        description=None,
        created_by=None,
        created_at=base.created_at,
        expires_at=None,
        is_active=False,
        last_used_at=None,
    )
    svc_rev = ApiKeyService(repository=_FakeRepo(revoked))  # type: ignore[arg-type]
    try:
        asyncio.run(svc_rev.verify(full))
        raise AssertionError("revoked key should fail verify")
    except ApiKeyVerificationError as e:
        assert e.code == "revoked", f"unexpected code: {e.code}"

    # expired key
    expired = ApiKeyRecord(
        id=base.id,
        key_hash=base.key_hash,
        key_prefix=base.key_prefix,
        workflow_id=base.workflow_id,
        description=None,
        created_by=None,
        created_at=base.created_at,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        is_active=True,
        last_used_at=None,
    )
    svc_exp = ApiKeyService(repository=_FakeRepo(expired))  # type: ignore[arg-type]
    try:
        asyncio.run(svc_exp.verify(full))
        raise AssertionError("expired key should fail verify")
    except ApiKeyVerificationError as e:
        assert e.code == "expired", f"unexpected code: {e.code}"

    # invalid (unknown hash)
    class _EmptyRepo:
        async def get_by_hash_for_auth(self, key_hash: str) -> ApiKeyRecord | None:
            return None

        async def touch_last_used_for_auth(self, id: str, when: datetime) -> None:
            pass

    svc_inv = ApiKeyService(repository=_EmptyRepo())  # type: ignore[arg-type]
    try:
        asyncio.run(svc_inv.verify(full))
        raise AssertionError("unknown key should fail verify")
    except ApiKeyVerificationError as e:
        assert e.code == "invalid", f"unexpected code: {e.code}"

    print("api_key_service self-check OK")
