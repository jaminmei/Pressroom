from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.yml"


def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_sandbox_services_absent_from_core_and_present_in_standard_full() -> None:
    services = _compose()["services"]
    broker = services["adaptor-sandbox-broker"]
    runner = services["adaptor-sandbox-runner"]

    assert "core" not in broker["profiles"]
    assert broker["profiles"] == ["standard", "full"]
    assert runner["profiles"] == ["standard", "full"]


def test_runner_uses_network_none_and_named_socket_volume_only() -> None:
    services = _compose()["services"]
    runner = services["adaptor-sandbox-runner"]

    assert runner["network_mode"] == "none"
    assert "networks" not in runner
    assert "ports" not in runner
    assert "devices" not in runner
    mounts = runner["volumes"]
    assert mounts == ["adaptor-sandbox-socket:/run/adaptor-sandbox"]


def test_broker_exposes_no_host_port_and_only_named_socket_volume() -> None:
    services = _compose()["services"]
    broker = services["adaptor-sandbox-broker"]

    assert "ports" not in broker
    assert broker["networks"] == ["doc-conv-network"]
    assert broker["volumes"] == ["adaptor-sandbox-socket:/run/adaptor-sandbox"]


def test_backend_and_worker_receive_broker_only_runtime_wiring() -> None:
    services = _compose()["services"]
    backend = services["backend"]
    worker = services["celery-worker"]

    backend_env = "\n".join(backend["environment"])
    worker_env = "\n".join(worker["environment"])
    assert "ADAPTOR_SANDBOX_BROKER_URL" in backend_env
    assert "ADAPTOR_SANDBOX_BROKER_URL" in worker_env
    assert "adaptor-sandbox-runner" not in backend_env
    assert "adaptor-sandbox-runner" not in worker_env

    backend_depends = backend["depends_on"]
    worker_depends = worker["depends_on"]
    assert backend_depends["adaptor-sandbox-broker"]["condition"] == "service_healthy"
    assert worker_depends["adaptor-sandbox-broker"]["condition"] == "service_healthy"
    assert "adaptor-sandbox-runner" not in backend_depends
    assert "adaptor-sandbox-runner" not in worker_depends


def test_broker_and_runner_have_hardening_fields() -> None:
    services = _compose()["services"]
    expected_users = {
        "adaptor-sandbox-broker": "10002:10003",
        "adaptor-sandbox-runner": "10001:10003",
    }
    for service_name in ("adaptor-sandbox-broker", "adaptor-sandbox-runner"):
        service = services[service_name]
        assert service["user"] == expected_users[service_name]
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["init"] is True
        assert service["tmpfs"] == ["/tmp:rw,noexec,nosuid,nodev"]
        assert "pids_limit" in service
        assert "mem_limit" in service
        assert "cpus" in service


def test_socket_named_volume_declared() -> None:
    volumes = _compose()["volumes"]
    assert "adaptor-sandbox-socket" in volumes
