import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ExceptionHandler

from app.api.admin.api_keys import router as admin_api_keys_router
from app.api.admin.api_usage import router as admin_api_usage_router
from app.api.public.error_response import (
    PublicApiError,
    public_api_exception_handler,
)
from app.api.public.router import router as public_api_router
from app.api.router import api_router
from app.api.websocket import router as ws_router
from app.config import get_settings, require_workspace_runtime_env
from app.errors import register_exception_handlers
from app.errors.error_response import canonical_error_responses
from app.providers.auth import AuthResolver
from app.providers.db import init_db
from app.providers.discover import discover_seed_configs
from app.providers.encryption import get_fernet
from app.providers.plugin_loader import bootstrap_provider_registry
from app.providers.seed import seed_default_providers
from app.providers.store import ProviderStore
from app.repositories.api_key_repository import ApiKeyRepository
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.ground_truth_repository import GroundTruthRepository
from app.repositories.test_set_repository import TestSetRepository
from app.services.api_key_service import ApiKeyService
from app.services.document_router import DocumentRouter
from app.services.evaluation_service import EvaluationService
from app.services.output_formatter.markdown_formatter import MarkdownFormatter
from app.services.rate_limiter import RateLimiter
from app.services.task_orchestrator import TaskOrchestrator
from app.services.workflow_execution import WorkflowExecutionService
from app.storage.local import get_storage
from app.storage.test_set_storage import TestSetStorage

# Configure logging to show INFO level logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

settings = get_settings()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise application-wide resources on startup.

    The ProviderStore is attached to ``app.state.provider_store`` so that
    route handlers can access it via ``request.app.state.provider_store``
    without relying on a module-level global.
    dependency injection to retrieve this object.
    """
    require_workspace_runtime_env("backend")
    bootstrap_provider_registry()

    db_path = init_db()
    fernet = get_fernet()

    import os

    app.state.provider_store = ProviderStore(db_path=db_path, fernet=fernet)
    seeded = seed_default_providers(app.state.provider_store)
    if seeded:
        logger.info("Seeded %d default providers", seeded)
    else:
        logger.info("Provider store ready")

    # Auto-discover config_schema for seed providers whose engines expose /config
    try:
        populated = await discover_seed_configs(app.state.provider_store)
        if populated:
            logger.info("Auto-discovered config for %d seed provider(s)", populated)
    except Exception as exc:
        logger.warning("Seed auto-discover failed error_type=%s", type(exc).__name__)

    app.state.auth_resolver = AuthResolver(fernet=fernet)
    runtime_settings = get_settings()
    app.state.test_set_repository = TestSetRepository()
    app.state.test_set_storage = TestSetStorage(runtime_settings.storage_root)
    app.state.ground_truth_repository = GroundTruthRepository()
    app.state.evaluation_repository = EvaluationRepository()
    app.state.api_key_repository = ApiKeyRepository()
    app.state.api_key_service = ApiKeyService(repository=app.state.api_key_repository)
    # Per-process in-memory token bucket; singleton so bucket state persists
    # across requests (per-request instantiation would never trip 429).
    app.state.rate_limiter = RateLimiter(runtime_settings.input_upload_rate_limit_per_minute)

    from app.api.tasks import init_dag_components

    skip_dag = os.environ.get("SKIP_DAG_INIT", "").lower() in ("1", "true", "yes")
    if skip_dag:
        logger.info("SKIP_DAG_INIT set — skipping DAG component initialization")
    else:
        try:
            init_dag_components(app.state)
        except Exception as exc:
            logger.error(
                "init_dag_components failed — DAG execution will be unavailable error_type=%s",
                type(exc).__name__,
            )

    storage = get_storage()
    dag_scheduler = getattr(app.state, "dag_scheduler", None)
    engine_client = getattr(app.state, "engine_client", None)
    # Import here to avoid a circular import at module load.
    from app.api.files import get_file_store

    task_orchestrator = TaskOrchestrator(
        storage=storage,
        document_router=DocumentRouter(storage=storage),
        markdown_formatter=MarkdownFormatter(),
        dag_scheduler=dag_scheduler,
        engine_client=engine_client,
        auth_resolver=app.state.auth_resolver,
        provider_store=app.state.provider_store,
        file_store=get_file_store(),
    )
    app.state.task_orchestrator = task_orchestrator
    app.state.workflow_execution = WorkflowExecutionService(task_orchestrator)
    app.state.evaluation_service = EvaluationService(
        orchestrator=task_orchestrator,
        test_set_repository=app.state.test_set_repository,
        evaluation_repository=app.state.evaluation_repository,
        ground_truth_repository=app.state.ground_truth_repository,
    )
    logger.info("EvaluationService initialised")

    # Mark stale "running" tasks as cancelled (orphaned by prior restart)
    try:
        from app.repositories.task_run_repository import TaskRunRepository

        stale_repo = TaskRunRepository()
        stale_fixed = await stale_repo.cancel_stale_running()
        if stale_fixed:
            logger.info("Marked %d stale 'running' task(s) as cancelled", stale_fixed)
    except Exception as exc:
        logger.warning(
            "Failed to clean up stale running tasks error_type=%s",
            type(exc).__name__,
        )

    # Outbox publisher is queue-mode only; serial mode never creates dispatch rows.
    publisher_task: asyncio.Task[None] | None = None
    from app.core.feature_flags import FeatureFlags, OrchestratorMode

    if FeatureFlags.get_orchestrator_mode() == OrchestratorMode.QUEUE:
        try:
            from app.services.evaluation_outbox_publisher import EvaluationOutboxPublisher
            from app.worker import celery_app as worker_celery_app

            publisher = EvaluationOutboxPublisher(celery_app=worker_celery_app)
            publisher_task = asyncio.create_task(
                publisher.run(),
                name="evaluation_outbox_publisher",
            )
            logger.info("Evaluation outbox publisher started (queue mode)")
        except Exception as exc:
            logger.error(
                "Failed to start evaluation outbox publisher error_type=%s",
                type(exc).__name__,
            )

    yield  # application runs here

    if publisher_task is not None:
        publisher_task.cancel()
        try:
            await publisher_task
        except (asyncio.CancelledError, Exception):
            pass

    # Cancel evaluation background tasks if any
    background_tasks = getattr(app.state, "evaluation_background_tasks", None)
    if background_tasks:
        tasks = list(background_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        background_tasks.clear()

    # Shutdown: close EngineClient's httpx.AsyncClient
    engine_client = getattr(app.state, "engine_client", None)
    if engine_client is not None:
        try:
            await engine_client.close()
        except Exception:
            pass


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)
register_exception_handlers(app)
app.add_exception_handler(
    PublicApiError,
    cast(ExceptionHandler, public_api_exception_handler),
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Workspace-Id"],
)

app.include_router(api_router, prefix="/api")
app.include_router(admin_api_keys_router, responses=canonical_error_responses())
app.include_router(admin_api_usage_router, responses=canonical_error_responses())
app.include_router(public_api_router)  # Public API at /api/v1/* (Bearer auth)
app.include_router(ws_router)  # WebSocket at /ws/workflow/{run_id}
