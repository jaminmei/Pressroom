from __future__ import annotations

import pytest
from redis.exceptions import RedisError

import app.config.celery_config as celery_config
from app.config.celery_config import CelerySettings
from app.worker import create_celery_app, ping_redis
from app.worker_tasks import (
    EXECUTE_EVALUATION_DOCUMENT_TASK_NAME,
    EXECUTE_WORKFLOW_TASK_NAME,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    celery_config.get_celery_settings.cache_clear()
    yield
    celery_config.get_celery_settings.cache_clear()


def test_get_celery_settings_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6380/2")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://localhost:6380/3")
    monkeypatch.setenv("CELERY_ACCEPT_CONTENT", "json,yaml")
    monkeypatch.setenv("CELERY_TIMEZONE", "Asia/Shanghai")
    monkeypatch.setenv("CELERY_ENABLE_UTC", "false")
    settings = celery_config.get_celery_settings()

    assert settings.broker_url == "redis://localhost:6380/2"
    assert settings.result_backend == "redis://localhost:6380/3"
    assert settings.accept_content == ("json", "yaml")
    assert settings.timezone == "Asia/Shanghai"
    assert settings.enable_utc is False


def test_create_celery_app_applies_configuration() -> None:
    settings = CelerySettings(
        celery_broker_url="redis://redis:6379/9",
        celery_result_backend="redis://redis:6379/8",
        celery_task_serializer="json",
        celery_result_serializer="json",
        celery_accept_content="json,yaml",
        celery_timezone="Asia/Shanghai",
        celery_enable_utc=False,
    )

    celery_app = create_celery_app(settings)

    assert celery_app.conf.broker_url == "redis://redis:6379/9"
    assert celery_app.conf.result_backend == "redis://redis:6379/8"
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert tuple(celery_app.conf.accept_content) == ("json", "yaml")
    assert celery_app.conf.timezone == "Asia/Shanghai"
    assert celery_app.conf.enable_utc is False
    assert celery_app.conf.task_routes[EXECUTE_WORKFLOW_TASK_NAME] == {"queue": "workflow"}
    assert celery_app.conf.task_routes[EXECUTE_EVALUATION_DOCUMENT_TASK_NAME] == {
        "queue": "evaluation"
    }


def test_smoke_celery_app_initialization_and_redis_ping(monkeypatch) -> None:
    class _Client:
        closed = False

        def ping(self) -> bool:
            return True

        def close(self) -> None:
            self.closed = True

    class _RedisFactory:
        client = _Client()

        @staticmethod
        def from_url(*_args, **_kwargs) -> _Client:
            return _RedisFactory.client

    monkeypatch.setattr("app.worker.Redis", _RedisFactory)

    settings = CelerySettings(
        celery_broker_url="redis://redis:6379/0",
        celery_result_backend="redis://redis:6379/1",
    )
    celery_app = create_celery_app(settings)
    ok = ping_redis(settings)

    assert celery_app.main == "docconv"
    assert celery_app.conf.broker_url == "redis://redis:6379/0"
    assert celery_app.conf.result_backend == "redis://redis:6379/1"
    assert ok is True
    assert _RedisFactory.client.closed is True


def test_ping_redis_returns_false_when_ping_raises(monkeypatch) -> None:
    class _Client:
        closed = False

        def ping(self) -> bool:
            raise RedisError("connection refused")

        def close(self) -> None:
            self.closed = True

    class _RedisFactory:
        client = _Client()

        @staticmethod
        def from_url(*_args, **_kwargs) -> _Client:
            return _RedisFactory.client

    monkeypatch.setattr("app.worker.Redis", _RedisFactory)

    ok = ping_redis(CelerySettings(celery_broker_url="redis://redis:6379/0"))

    assert ok is False
    assert _RedisFactory.client.closed is True
