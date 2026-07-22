from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.runtime_attestation import router
from app.config import (
    WorkspaceRuntimeEnvError,
    get_settings,
    runtime_attestation_digest,
    runtime_attestation_request_proof,
)
from app.worker import attest_backend_runtime

NONCE = "ab" * 32
SECRET = "runtime-test-secret"
DATABASE_URL = "postgresql+psycopg://runtime-user:database-secret@db:5432/runtime"


@pytest.fixture()
def runtime_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("PROVIDER_DB_PATH", str(tmp_path / "providers.db"))
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", SECRET)
    monkeypatch.setenv(
        "RUNTIME_ATTESTATION_URL", "http://backend:8000/api/internal/runtime-attestation"
    )
    monkeypatch.setenv("RUNTIME_ATTESTATION_TIMEOUT_SECONDS", "0.5")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_hidden_endpoint_returns_only_nonce_and_digest(runtime_env: None) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    proof = runtime_attestation_request_proof(NONCE)

    with TestClient(app) as client:
        response = client.post(
            "/api/internal/runtime-attestation", json={"nonce": NONCE, "proof": proof}
        )
        schema = client.get("/openapi.json").json()

    assert response.status_code == 200
    assert response.json() == {"nonce": NONCE, "digest": runtime_attestation_digest(NONCE)}
    serialized = json.dumps(response.json())
    assert SECRET not in serialized
    assert DATABASE_URL not in serialized
    assert "/api/internal/runtime-attestation" not in schema["paths"]


def test_endpoint_rejects_invalid_proof_without_disclosing_config(runtime_env: None) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")

    with TestClient(app) as client:
        response = client.post(
            "/api/internal/runtime-attestation", json={"nonce": NONCE, "proof": "00" * 32}
        )

    assert response.status_code == 401
    assert SECRET not in response.text
    assert DATABASE_URL not in response.text


def test_digest_changes_for_every_attested_runtime_field(runtime_env: None, monkeypatch) -> None:
    baseline = runtime_attestation_digest(NONCE)

    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "false")
    assert runtime_attestation_digest(NONCE) != baseline
    monkeypatch.setenv("WORKSPACE_RBAC_ENFORCED", "true")

    monkeypatch.setenv("DATABASE_URL", DATABASE_URL.replace("runtime-user", "other-user"))
    assert runtime_attestation_digest(NONCE) != baseline
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)

    monkeypatch.setenv("PROVIDER_DB_PATH", "/different/providers.db")
    assert runtime_attestation_digest(NONCE) != baseline


def test_worker_verifies_live_backend_with_constant_time_digest(
    runtime_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_post(url: str, *, json: dict[str, str], timeout: float) -> httpx.Response:
        assert url.endswith("/api/internal/runtime-attestation")
        assert timeout == 0.5
        assert json["proof"] == runtime_attestation_request_proof(json["nonce"])
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"nonce": json["nonce"], "digest": runtime_attestation_digest(json["nonce"])},
            request=request,
        )

    monkeypatch.setattr("app.worker.httpx.post", fake_post)
    attest_backend_runtime()


@pytest.mark.parametrize("failure", ["timeout", "mismatch"])
def test_worker_fails_closed_when_backend_cannot_attest(
    runtime_env: None, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    if failure == "timeout":
        monkeypatch.setattr(
            "app.worker.httpx.post",
            lambda *args, **kwargs: (_ for _ in ()).throw(httpx.TimeoutException("timeout")),
        )
    else:

        def mismatched(url: str, *, json: dict[str, str], timeout: float) -> httpx.Response:
            return httpx.Response(
                200,
                json={"nonce": json["nonce"], "digest": "00" * 32},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr("app.worker.httpx.post", mismatched)

    with pytest.raises(WorkspaceRuntimeEnvError):
        attest_backend_runtime()
