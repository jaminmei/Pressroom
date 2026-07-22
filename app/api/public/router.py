"""Parent public API router (mounted at ``/api/v1``).

Assembles the health and Bearer-authenticated workflow run, status, results,
and history routes.

Self-check: ``python -m app.api.public.router``.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter

from app.api.public.health import router as health_router
from app.api.public.workflow_runs import router as workflow_runs_router

router = APIRouter(prefix="/api/v1", tags=["public-api"])
router.include_router(health_router)
router.include_router(workflow_runs_router)


if __name__ == "__main__":
    import json

    from app.api.public.auth import ApiKeyIdentity, verify_api_key
    from app.api.public.error_response import (
        CODE_INVALID_API_KEY,
        CODE_UNAUTHORIZED,
        PublicApiError,
        public_api_exception_handler,
        public_error_response,
    )
    from app.repositories.api_key_repository import ApiKeyRecord
    from app.services.api_key_service import (
        ApiKeyService,
        ApiKeyVerificationError,
    )

    # --- envelope shape ---
    resp = public_error_response(401, "INVALID_API_KEY", "bad", workflow_id="wf_x")
    assert resp.status_code == 401
    parsed = json.loads(bytes(resp.body))
    assert parsed == {
        "error": {
            "code": "INVALID_API_KEY",
            "message": "bad",
            "workflow_id": "wf_x",
        }
    }, f"envelope shape wrong: {parsed}"

    # --- exception handler converts PublicApiError → same envelope ---
    async def _handler_check() -> None:
        # Build a fake raise → catch → handler invocation
        exc = PublicApiError(401, CODE_UNAUTHORIZED, "no auth")
        out = await public_api_exception_handler(request=None, exc=exc)  # type: ignore[arg-type]
        assert out.status_code == 401
        body = json.loads(bytes(out.body))
        assert body == {"error": {"code": "UNAUTHORIZED", "message": "no auth"}}, body

    asyncio.run(_handler_check())

    # --- verify_api_key end-to-end with a stubbed ApiKeyService ---
    # Pattern mirrors app/services/api_key_service.py __main__ block.
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    good_key = "dca_good_token_aaaaaaaaaaaaaaaa"
    revoked_key = "dca_revoked_token_bbbbbbbbbbbb"
    expired_key = "dca_expired_token_cccccccccccc"
    unknown_key = "dca_unknown_token_ddddddddddddd"

    good_hash = _hash(good_key)
    revoked_hash = _hash(revoked_key)
    expired_hash = _hash(expired_key)
    now = datetime.now(timezone.utc)

    records_by_hash: dict[str, ApiKeyRecord] = {
        good_hash: ApiKeyRecord(
            id="id_good",
            key_hash=good_hash,
            key_prefix="dca_good_to",
            workflow_id="wf_demo",
            description=None,
            created_by=None,
            created_at=now,
            expires_at=None,
            is_active=True,
            last_used_at=None,
        ),
        revoked_hash: ApiKeyRecord(
            id="id_revoked",
            key_hash=revoked_hash,
            key_prefix="dca_revoked",
            workflow_id="wf_demo",
            description=None,
            created_by=None,
            created_at=now,
            expires_at=None,
            is_active=False,
            last_used_at=None,
        ),
        expired_hash: ApiKeyRecord(
            id="id_expired",
            key_hash=expired_hash,
            key_prefix="dca_expired",
            workflow_id="wf_demo",
            description=None,
            created_by=None,
            created_at=now,
            expires_at=now - timedelta(seconds=1),
            is_active=True,
            last_used_at=None,
        ),
    }

    class _StubRepo:
        async def get_by_hash_for_auth(self, key_hash: str) -> ApiKeyRecord | None:
            return records_by_hash.get(key_hash)

        async def touch_last_used_for_auth(self, id: str, when: datetime) -> None:
            pass

    svc = ApiKeyService(repository=_StubRepo())  # type: ignore[arg-type]

    def _make_request(authorization: str | None) -> Any:
        # MagicMock is simpler than a real starlette Request scope here.
        from unittest.mock import MagicMock

        req = MagicMock()
        if authorization is None:
            req.headers = {}
        else:
            req.headers = {"Authorization": authorization}
        req.state = SimpleNamespace()
        app_state = SimpleNamespace(api_key_service=svc)
        req.app.state = app_state
        return req

    async def _verify(req: Any) -> ApiKeyIdentity:
        # Invoke the dependency body directly — bypass FastAPI's Depends wiring.
        # credentials=None forces the function down the header-parsing path,
        # which is what real clients hit when FastAPI's HTTPBearer doesn't
        # match (e.g. tests sending Authorization directly).
        return await verify_api_key(request=req, credentials=None)

    async def _run() -> None:
        # good token → workflow_id returned + stashed on request.state
        good_req = _make_request(f"Bearer {good_key}")
        identity = await _verify(good_req)
        assert identity.workflow_id == "wf_demo", f"workflow_id wrong: {identity}"
        assert good_req.state.api_key_workflow_id == "wf_demo"

        # missing Authorization → PublicApiError UNAUTHORIZED
        missing_req = _make_request(None)
        try:
            await _verify(missing_req)
            raise AssertionError("missing auth header should raise")
        except PublicApiError as e:
            assert e.code == CODE_UNAUTHORIZED, f"unexpected code: {e.code}"
            assert e.status_code == 401

        # revoked token → PublicApiError INVALID_API_KEY
        rev_req = _make_request(f"Bearer {revoked_key}")
        try:
            await _verify(rev_req)
            raise AssertionError("revoked token should raise")
        except PublicApiError as e:
            assert e.code == CODE_INVALID_API_KEY, f"unexpected code: {e.code}"
            assert e.status_code == 401

        # expired token → INVALID_API_KEY (collapsed per spec)
        exp_req = _make_request(f"Bearer {expired_key}")
        try:
            await _verify(exp_req)
            raise AssertionError("expired token should raise")
        except PublicApiError as e:
            assert e.code == CODE_INVALID_API_KEY, f"unexpected code: {e.code}"

        # unknown token → INVALID_API_KEY
        unk_req = _make_request(f"Bearer {unknown_key}")
        try:
            await _verify(unk_req)
            raise AssertionError("unknown token should raise")
        except PublicApiError as e:
            assert e.code == CODE_INVALID_API_KEY, f"unexpected code: {e.code}"

        # underlying ApiKeyVerificationError still carries internal .code
        # for our logs — sanity-check via direct service call.
        try:
            await svc.verify(revoked_key)
            raise AssertionError("should have raised ApiKeyVerificationError")
        except ApiKeyVerificationError as e:
            assert e.code == "revoked"

    asyncio.run(_run())
    print("public router self-check OK")
