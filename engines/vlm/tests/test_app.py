from __future__ import annotations

import base64
import importlib.util
import logging
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient


def _load_app_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "app.py"
    spec = importlib.util.spec_from_file_location("vlm_service_app", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_health_is_liveness_only_and_full_health_is_absent() -> None:
    module = _load_app_module()
    with TestClient(module.app) as client:
        response = client.get("/health")
        full = client.get("/health/full")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "version": "1.0.0"}
    assert full.status_code == 404
    assert "gateway" not in response.text.lower()


def test_process_reads_typed_internal_credential_headers() -> None:
    module = _load_app_module()
    captured: dict = {}

    class FakeEngine:
        def process_base64(self, _image, config, **kwargs):
            captured.update(config=config, **kwargs)
            return {
                "result": "ok",
                "_vlm_metadata": {
                    "request_id": "req-1",
                    "usage": {"total_tokens": 3},
                    "model": "vision-model",
                },
            }

    module.get_vlm_engine = lambda: FakeEngine()
    payload = {
        "inputs": {
            "image": {
                "text": base64.b64encode(b"image").decode("ascii"),
                "binary": [],
                "metadata": {},
            }
        },
        "config": {
            "provider_base_url": "https://provider.test/v1",
            "provider_api_style": "openai",
            "model": "vision-model",
        },
    }
    with TestClient(module.app) as client:
        response = client.post(
            "/process",
            json=payload,
            headers={
                "X-DocConv-Credential-Kind": "api_key",
                "X-DocConv-Credential": "secret",
            },
        )

    assert response.status_code == 200
    assert captured["credential_kind"].value == "api_key"
    assert captured["credential"] == "secret"
    assert "secret" not in response.text
    assert response.json()["text"] == "ok"


def test_process_error_does_not_leak_upstream_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    module = _load_app_module()
    sentinel = "PRIVATE-UPSTREAM-RESPONSE"

    class FailingEngine:
        def process_base64(self, *_args, **_kwargs):
            raise RuntimeError(sentinel)

    module.get_vlm_engine = lambda: FailingEngine()
    payload = {
        "inputs": {
            "image": {
                "text": base64.b64encode(b"image").decode("ascii"),
                "binary": [],
                "metadata": {},
            }
        },
        "config": {
            "provider_base_url": "https://provider.test/v1",
            "provider_api_style": "openai",
            "model": "vision-model",
        },
    }
    caplog.set_level(logging.INFO)
    with TestClient(module.app) as client:
        response = client.post("/process", json=payload)

    assert response.status_code == 502
    assert response.json() == {"detail": "VLM provider request failed"}
    assert sentinel not in response.text
    assert sentinel not in caplog.text
