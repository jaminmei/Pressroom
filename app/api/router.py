from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.engines import router as engines_router
from app.api.evaluation_runs import router as evaluation_runs_router
from app.api.files import router as files_router
from app.api.ground_truths import router as ground_truths_router
from app.api.health import router as health_router
from app.api.nodes import router as nodes_router
from app.api.providers import models_router
from app.api.providers import router as providers_router
from app.api.runtime_attestation import router as runtime_attestation_router
from app.api.tasks import router as tasks_router
from app.api.test_documents import router as test_documents_router
from app.api.test_sets import router as test_sets_router
from app.api.workflows import router as workflows_router
from app.api.workspaces import router as workspaces_router
from app.errors.error_response import canonical_error_responses

api_router = APIRouter(responses=canonical_error_responses())
api_router.include_router(health_router)
api_router.include_router(runtime_attestation_router)
api_router.include_router(auth_router)
api_router.include_router(files_router)
api_router.include_router(tasks_router)
api_router.include_router(workflows_router)
api_router.include_router(test_sets_router)
api_router.include_router(test_documents_router)
api_router.include_router(workspaces_router)
api_router.include_router(ground_truths_router)
api_router.include_router(evaluation_runs_router)
api_router.include_router(nodes_router)
api_router.include_router(engines_router)  # → /api/engines
api_router.include_router(providers_router)  # → /api/providers
api_router.include_router(models_router)  # → /api/models
