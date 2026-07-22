from __future__ import annotations

import hmac
import secrets

import httpx
from celery import Celery
from celery.signals import worker_init
from redis import Redis
from redis.exceptions import RedisError

from app.celery_queues import EVALUATION_CELERY_QUEUE, WORKFLOW_CELERY_QUEUE
from app.config import (
    WorkspaceRuntimeEnvError,
    get_settings,
    require_workspace_runtime_env,
    runtime_attestation_digest,
    runtime_attestation_request_proof,
)
from app.config.celery_config import CelerySettings, get_celery_settings
from app.providers.plugin_loader import bootstrap_provider_registry
from app.worker_tasks import (
    EXECUTE_EVALUATION_DOCUMENT_TASK_NAME,
    EXECUTE_WORKFLOW_TASK_NAME,
    register_worker_tasks,
)

bootstrap_provider_registry()


def create_celery_app(settings: CelerySettings | None = None) -> Celery:
    config = settings or get_celery_settings()
    celery_app = Celery("docconv")
    celery_app.conf.update(
        broker_url=config.broker_url,
        result_backend=config.result_backend,
        task_serializer=config.task_serializer,
        result_serializer=config.result_serializer,
        accept_content=list(config.accept_content),
        timezone=config.timezone,
        enable_utc=config.enable_utc,
        task_acks_late=config.celery_task_acks_late,
        task_reject_on_worker_lost=config.celery_task_reject_on_worker_lost,
        worker_prefetch_multiplier=config.celery_worker_prefetch_multiplier,
        task_routes={
            EXECUTE_WORKFLOW_TASK_NAME: {"queue": WORKFLOW_CELERY_QUEUE},
            EXECUTE_EVALUATION_DOCUMENT_TASK_NAME: {"queue": EVALUATION_CELERY_QUEUE},
        },
    )
    return celery_app


def ping_redis(
    settings: CelerySettings | None = None,
    *,
    timeout_seconds: float = 1.0,
) -> bool:
    config = settings or get_celery_settings()
    client = Redis.from_url(
        config.broker_url,
        socket_connect_timeout=timeout_seconds,
        socket_timeout=timeout_seconds,
    )
    try:
        return bool(client.ping())
    except RedisError:
        return False
    finally:
        client.close()


celery_app = create_celery_app()
register_worker_tasks(celery_app)

# Keep backward compatibility with legacy celery CLI/tests.
celery = celery_app


def attest_backend_runtime() -> None:
    """Fail closed unless the live backend proves it has the same runtime config."""
    settings = get_settings()
    if not settings.workspace_rbac_enforced:
        return

    nonce = secrets.token_hex(32)
    proof = runtime_attestation_request_proof(nonce)
    try:
        response = httpx.post(
            settings.runtime_attestation_url,
            json={"nonce": nonce, "proof": proof},
            timeout=settings.runtime_attestation_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise WorkspaceRuntimeEnvError("backend runtime attestation failed") from exc

    response_nonce = payload.get("nonce") if isinstance(payload, dict) else None
    remote_digest = payload.get("digest") if isinstance(payload, dict) else None
    local_digest = runtime_attestation_digest(nonce)
    if (
        not isinstance(response_nonce, str)
        or not hmac.compare_digest(response_nonce, nonce)
        or not isinstance(remote_digest, str)
        or not hmac.compare_digest(remote_digest, local_digest)
    ):
        raise WorkspaceRuntimeEnvError("backend runtime attestation mismatch")


@worker_init.connect
def validate_worker_runtime_env(**_kwargs: str) -> None:
    require_workspace_runtime_env("worker")
    attest_backend_runtime()
    bootstrap_provider_registry()


@celery_app.task(name="infra.noop")
def noop() -> str:
    return "ok"
