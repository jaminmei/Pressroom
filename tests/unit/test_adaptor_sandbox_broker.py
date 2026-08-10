from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from sandbox_protocol.models import POLICY_DIGEST, SandboxLimits


class _FakeRunnerClient:
    def __init__(self) -> None:
        self.process_calls: list[dict] = []
        self.health_response = {
            "runner_reachable": True,
            "attested": True,
            "policy_digest": POLICY_DIGEST,
            "network_policy": "runner-network-none",
            "limits": {"max_code_bytes": 65536},
            "version": "1.0",
        }
        self.process_response = {
            "request_id": "req-1",
            "status": "ok",
            "result": {
                "text": "ok",
                "binary": [],
                "structured": {"done": True},
                "metadata": {},
            },
            "error": None,
            "metrics": {"wall_time_ms": 5},
        }

    def health(self) -> dict:
        return self.health_response

    def process(self, payload: dict) -> dict:
        self.process_calls.append(payload)
        return self.process_response


class _BlockingRunnerClient(_FakeRunnerClient):
    def __init__(self) -> None:
        super().__init__()
        self._release = threading.Event()

    def process(self, payload: dict) -> dict:
        self.process_calls.append(payload)
        if payload["request_id"] == "req-long":
            self._release.wait(timeout=1.0)
            return {
                "request_id": "req-long",
                "status": "error",
                "result": None,
                "error": {"kind": "timeout", "message": "request timed out"},
                "metrics": {},
            }
        return {
            "request_id": payload["request_id"],
            "status": "error",
            "result": None,
            "error": {"kind": "queue_full", "message": "runner busy"},
            "metrics": {},
        }


class _CountingRunnerClient(_FakeRunnerClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.release = threading.Event()

    def process(self, payload: dict) -> dict:
        self.calls += 1
        self.process_calls.append(payload)
        self.release.wait(timeout=1.0)
        return {
            "request_id": payload["request_id"],
            "status": "error",
            "result": None,
            "error": {"kind": "timeout", "message": "request timed out"},
            "metrics": {},
        }


@pytest.fixture()
def broker_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, _FakeRunnerClient]:
    from engines.adaptor_sandbox.broker import app as broker_app_module

    fake = _FakeRunnerClient()
    monkeypatch.setattr(broker_app_module, "runner_client", fake)
    client = TestClient(broker_app_module.app)
    return client, fake


def test_broker_exposes_only_process_health_and_config(
    broker_client: tuple[TestClient, _FakeRunnerClient],
) -> None:
    client, _ = broker_client

    assert client.get("/").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/health").status_code == 200
    assert client.get("/config").status_code == 200


def test_broker_process_forwards_strict_payload_and_returns_runner_result(
    broker_client: tuple[TestClient, _FakeRunnerClient],
) -> None:
    client, fake = broker_client

    response = client.post(
        "/process",
        json={
            "request_id": "req-1",
            "code": "def main(inputs):\n    return {'text': 'ok'}",
            "inputs": {},
            "limits": {"max_code_bytes": 65536},
            "policy_digest": POLICY_DIGEST,
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["text"] == "ok"
    assert fake.process_calls[0]["request_id"] == "req-1"


@pytest.mark.parametrize(
    ("runner_response", "expected_status"),
    [
        (
            {
                "request_id": "req-1",
                "status": "error",
                "result": None,
                "error": {"kind": "invalid", "message": "bad request req-1"},
                "metrics": {},
            },
            422,
        ),
        (
            {
                "request_id": "req-1",
                "status": "error",
                "result": None,
                "error": {"kind": "code", "message": "bad request req-1"},
                "metrics": {},
            },
            422,
        ),
        (
            {
                "request_id": "req-1",
                "status": "error",
                "result": None,
                "error": {"kind": "runtime", "message": "bad request req-1"},
                "metrics": {},
            },
            422,
        ),
        (
            {
                "request_id": "req-1",
                "status": "error",
                "result": None,
                "error": {"kind": "resource", "message": "bad request req-1"},
                "metrics": {},
            },
            422,
        ),
        (
            {
                "request_id": "req-1",
                "status": "error",
                "result": None,
                "error": {"kind": "timeout", "message": "bad request req-1"},
                "metrics": {},
            },
            504,
        ),
        (
            {
                "request_id": "req-1",
                "status": "error",
                "result": None,
                "error": {"kind": "unavailable", "message": "bad request req-1"},
                "metrics": {},
            },
            503,
        ),
        (
            {
                "request_id": "req-1",
                "status": "error",
                "result": None,
                "error": {"kind": "queue_full", "message": "bad request req-1"},
                "metrics": {},
            },
            503,
        ),
        (
            {
                "request_id": "req-1",
                "status": "error",
                "result": None,
                "error": {"kind": "protocol", "message": "bad request req-1"},
                "metrics": {},
            },
            502,
        ),
        (
            {
                "request_id": "req-1",
                "status": "error",
                "result": None,
                "error": {"kind": "internal", "message": "bad request req-1"},
                "metrics": {},
            },
            502,
        ),
    ],
)
def test_broker_maps_runner_error_kinds_to_http_status(
    broker_client: tuple[TestClient, _FakeRunnerClient],
    runner_response: dict,
    expected_status: int,
) -> None:
    client, fake = broker_client
    fake.process_response = runner_response

    response = client.post(
        "/process",
        json={
            "request_id": "req-1",
            "code": "def main(inputs):\n    return {'text': 'ok'}",
            "inputs": {},
            "limits": {"max_code_bytes": 65536},
            "policy_digest": POLICY_DIGEST,
        },
    )

    assert response.status_code == expected_status
    assert response.json()["request_id"] == "req-1"
    assert "def main" not in response.text
    assert "/tmp/secret" not in response.text


def test_broker_health_and_config_are_static_and_safe(
    broker_client: tuple[TestClient, _FakeRunnerClient],
) -> None:
    client, _ = broker_client

    health = client.get("/health")
    config = client.get("/config")

    assert health.json() == {
        "status": "ok",
        "version": "1.0",
        "runner_reachable": True,
    }
    assert config.json()["engine"] == "adaptor-sandbox"
    assert config.json()["policy_digest"] == POLICY_DIGEST
    assert config.json()["network_policy"] == "runner-network-none"


def test_broker_rejects_invalid_base64_request_with_sanitized_422(
    broker_client: tuple[TestClient, _FakeRunnerClient],
) -> None:
    client, _ = broker_client

    response = client.post(
        "/process",
        json={
            "request_id": "req-bad-b64",
            "code": "def main(inputs):\n    return {'text': 'ok'}",
            "inputs": {
                "doc": {
                    "text": None,
                    "binary": [{"data": "***", "mime_type": "text/plain", "size_bytes": 5}],
                    "structured": None,
                    "metadata": {},
                }
            },
            "limits": SandboxLimits().model_dump(),
            "policy_digest": POLICY_DIGEST,
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["request_id"] == "req-bad-b64"
    assert body["error"]["kind"] == "invalid"
    assert "invalid base64" in body["error"]["message"]
    assert "def main" not in response.text


def test_broker_health_and_config_reflect_live_runner_attestation(
    broker_client: tuple[TestClient, _FakeRunnerClient],
) -> None:
    client, fake = broker_client
    fake.health_response = {
        "runner_reachable": True,
        "attested": True,
        "policy_digest": POLICY_DIGEST,
        "network_policy": "runner-network-none",
        "limits": {"max_code_bytes": 65536},
        "version": "1.0",
    }

    health = client.get("/health")
    config = client.get("/config")

    assert health.json()["runner_reachable"] is True
    assert config.json()["policy_digest"] == POLICY_DIGEST


def test_broker_reports_unattested_runner_when_live_policy_mismatches(
    broker_client: tuple[TestClient, _FakeRunnerClient],
) -> None:
    client, fake = broker_client
    fake.health_response = {
        "runner_reachable": True,
        "attested": True,
        "policy_digest": "0" * 64,
        "network_policy": "runner-network-none",
        "limits": {"max_code_bytes": 65536},
        "version": "1.0",
    }

    health = client.get("/health")
    config = client.get("/config")

    assert health.json()["runner_reachable"] is False
    assert config.status_code == 503


def test_broker_process_fails_closed_when_runner_attestation_mismatches(
    broker_client: tuple[TestClient, _FakeRunnerClient],
) -> None:
    client, fake = broker_client
    fake.health_response = {
        "runner_reachable": True,
        "attested": True,
        "policy_digest": "0" * 64,
        "network_policy": "runner-network-none",
        "limits": {"max_code_bytes": 65536},
        "version": "1.0",
    }

    response = client.post(
        "/process",
        json={
            "request_id": "req-mismatch",
            "code": "def main(inputs):\n    return {'text': 'ok'}",
            "inputs": {},
            "limits": SandboxLimits().model_dump(),
            "policy_digest": POLICY_DIGEST,
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["kind"] == "unavailable"
    assert fake.process_calls == []


def test_broker_returns_queue_full_without_waiting_for_blocked_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from engines.adaptor_sandbox.broker import app as broker_app_module

    fake = _BlockingRunnerClient()
    monkeypatch.setattr(broker_app_module, "runner_client", fake)
    client = TestClient(broker_app_module.app)

    first_holder: dict[str, object] = {}

    def run_first() -> None:
        first_holder["response"] = client.post(
            "/process",
            json={
                "request_id": "req-long",
                "code": "def main(inputs):\n    return {'text': 'ok'}",
                "inputs": {},
                "limits": SandboxLimits().model_dump(),
                "policy_digest": POLICY_DIGEST,
            },
        )

    thread = threading.Thread(target=run_first)
    thread.start()
    time.sleep(0.05)

    second = client.post(
        "/process",
        json={
            "request_id": "req-second",
            "code": "def main(inputs):\n    return {'text': 'ok'}",
            "inputs": {},
            "limits": SandboxLimits().model_dump(),
            "policy_digest": POLICY_DIGEST,
        },
    )

    assert second.status_code == 503
    assert second.json()["error"]["kind"] == "queue_full"

    fake._release.set()
    thread.join(timeout=2.0)
    first = first_holder["response"]
    assert first.status_code == 504


def test_broker_rejects_second_request_before_second_uds_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from engines.adaptor_sandbox.broker import app as broker_app_module

    fake = _CountingRunnerClient()
    monkeypatch.setattr(broker_app_module, "runner_client", fake)
    client = TestClient(broker_app_module.app)

    first_holder: dict[str, object] = {}

    def run_first() -> None:
        first_holder["response"] = client.post(
            "/process",
            json={
                "request_id": "req-first",
                "code": "def main(inputs):\n    return {'text': 'ok'}",
                "inputs": {},
                "limits": SandboxLimits().model_dump(),
                "policy_digest": POLICY_DIGEST,
            },
        )

    thread = threading.Thread(target=run_first)
    thread.start()
    time.sleep(0.05)

    second = client.post(
        "/process",
        json={
            "request_id": "req-second",
            "code": "def main(inputs):\n    return {'text': 'ok'}",
            "inputs": {},
            "limits": SandboxLimits().model_dump(),
            "policy_digest": POLICY_DIGEST,
        },
    )

    assert second.status_code == 503
    assert second.json()["error"]["kind"] == "queue_full"
    assert fake.calls == 1

    fake.release.set()
    thread.join(timeout=2.0)
