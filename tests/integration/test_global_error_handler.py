from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import ErrorCode, ValidationError, register_exception_handlers

TRACE_ID_PATTERN = re.compile(r"^tr-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _build_test_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/raise-app-error")
    async def raise_app_error() -> None:
        raise ValidationError(
            error_code=ErrorCode.INVALID_NODE_CONFIG,
            message="invalid node config",
            details={"node_id": "ocr_1"},
        )

    @app.get("/raise-unhandled-error")
    async def raise_unhandled_error() -> None:
        raise RuntimeError("boom")

    return app


def test_app_error_is_translated_to_unified_error_response() -> None:
    app = _build_test_app()

    with TestClient(app) as client:
        response = client.get("/raise-app-error")

    assert response.status_code == 422
    payload = response.json()
    assert payload["error_code"] == "INVALID_NODE_CONFIG"
    assert payload["message"] == "invalid node config"
    assert payload["details"] == {"node_id": "ocr_1"}
    assert TRACE_ID_PATTERN.match(payload["trace_id"]) is not None


def test_unhandled_error_is_translated_to_internal_error_response() -> None:
    app = _build_test_app()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-unhandled-error")

    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == "INTERNAL_ERROR"
    assert payload["details"] is None
    assert TRACE_ID_PATTERN.match(payload["trace_id"]) is not None
