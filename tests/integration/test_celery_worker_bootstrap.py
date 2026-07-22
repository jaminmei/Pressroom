from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest

import app.providers.plugin_loader as provider_plugin_loader
from app.providers.plugin_loader import ProviderPluginError


def _reload_worker_module():
    import app.worker as worker

    return importlib.reload(worker)


def test_celery_worker_bootstrap_uses_env_overrides(monkeypatch) -> None:
    broker_url = "redis://127.0.0.1:6379/5"
    result_backend = "redis://127.0.0.1:6379/6"
    monkeypatch.setenv("CELERY_BROKER_URL", broker_url)
    monkeypatch.setenv("CELERY_RESULT_BACKEND", result_backend)

    worker = _reload_worker_module()

    assert worker.celery is worker.celery_app
    assert worker.celery_app.conf.broker_url == broker_url
    assert worker.celery_app.conf.result_backend == result_backend


def test_worker_module_import_bootstraps_provider_registry(monkeypatch) -> None:
    bootstrap_registry = Mock(return_value=())
    monkeypatch.setattr(
        provider_plugin_loader,
        "bootstrap_provider_registry",
        bootstrap_registry,
    )

    worker = _reload_worker_module()

    bootstrap_registry.assert_called_once_with()
    assert worker.bootstrap_provider_registry is bootstrap_registry


def test_worker_module_import_fails_closed_when_plugin_import_fails(monkeypatch) -> None:
    monkeypatch.setenv(
        "PROVIDER_PLUGIN_MODULES",
        "test_missing_worker_provider_plugin",
    )

    with pytest.raises(ProviderPluginError, match="failed to register"):
        _reload_worker_module()


def test_celery_noop_task_is_registered_and_callable() -> None:
    worker = _reload_worker_module()

    assert "infra.noop" in worker.celery_app.tasks
    assert worker.noop() == "ok"


def test_celery_noop_task_executes_deterministically_in_eager_mode(monkeypatch) -> None:
    # Keep this test fully local/deterministic: no external Redis dependency.
    broker_url = "memory://"
    result_backend = "cache+memory://"
    monkeypatch.setenv("CELERY_BROKER_URL", broker_url)
    monkeypatch.setenv("CELERY_RESULT_BACKEND", result_backend)
    worker = _reload_worker_module()

    original_task_always_eager = worker.celery_app.conf.task_always_eager
    original_store_eager_result = worker.celery_app.conf.task_store_eager_result
    worker.celery_app.conf.task_always_eager = True
    worker.celery_app.conf.task_store_eager_result = True

    try:
        async_result = worker.noop.delay()
        assert async_result.get(timeout=5) == "ok"
    finally:
        worker.celery_app.conf.task_always_eager = original_task_always_eager
        worker.celery_app.conf.task_store_eager_result = original_store_eager_result


def test_worker_init_bootstraps_provider_registry_after_runtime_validation(monkeypatch) -> None:
    worker = _reload_worker_module()
    calls: list[str] = []
    require_runtime = Mock(side_effect=lambda _role: calls.append("runtime"))
    attest_runtime = Mock(side_effect=lambda: calls.append("attestation"))
    bootstrap_registry = Mock(side_effect=lambda: calls.append("providers"))
    monkeypatch.setattr(worker, "require_workspace_runtime_env", require_runtime)
    monkeypatch.setattr(worker, "attest_backend_runtime", attest_runtime)
    monkeypatch.setattr(worker, "bootstrap_provider_registry", bootstrap_registry)

    worker.validate_worker_runtime_env()

    assert calls == ["runtime", "attestation", "providers"]
    require_runtime.assert_called_once_with("worker")
    attest_runtime.assert_called_once_with()
    bootstrap_registry.assert_called_once_with()


def test_worker_import_and_repeated_init_register_plugin_once(monkeypatch) -> None:
    plugin_module = ModuleType("test_worker_bootstrap_idempotent_plugin")
    registrations: list[str] = []
    plugin_module.register = lambda: registrations.append("registered")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, plugin_module.__name__, plugin_module)
    monkeypatch.setenv("PROVIDER_PLUGIN_MODULES", plugin_module.__name__)

    worker = _reload_worker_module()
    monkeypatch.setattr(worker, "require_workspace_runtime_env", lambda _role: None)
    monkeypatch.setattr(worker, "attest_backend_runtime", lambda: None)

    worker.validate_worker_runtime_env()
    worker.validate_worker_runtime_env()

    assert registrations == ["registered"]
