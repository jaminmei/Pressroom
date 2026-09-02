"""Execute and retry durable Test Set storage cleanup jobs."""

from __future__ import annotations

import json
import logging

from app.repositories.test_set_repository import TestSetRepository
from app.storage.test_set_storage import TestSetStorage

logger = logging.getLogger(__name__)


async def execute_storage_cleanup_job(
    cleanup_job_id: str,
    *,
    repository: TestSetRepository,
    storage: TestSetStorage,
) -> bool:
    job = await repository.get_storage_cleanup_job(cleanup_job_id)
    if job is None or job.status == "completed":
        return True
    resource_type = job.resource_type
    try:
        payload = json.loads(job.payload_json)
    except json.JSONDecodeError:
        await repository.mark_storage_cleanup_failed(
            cleanup_job_id,
            error_code="CLEANUP_PAYLOAD_INVALID",
        )
        return False
    try:
        if resource_type == "test_set":
            await storage.delete_test_set(str(payload["test_set_id"]))
        elif resource_type == "test_document":
            await storage.delete_document(str(payload["storage_path"]))
            await storage.delete_document_thumbnails(
                str(payload["test_set_id"]),
                str(payload["document_id"]),
            )
        else:
            raise ValueError("Unsupported cleanup resource type")
    except Exception as exc:  # noqa: BLE001
        await repository.mark_storage_cleanup_failed(
            cleanup_job_id,
            error_code="STORAGE_DELETE_FAILED",
        )
        logger.warning(
            "Storage cleanup deferred: cleanup_job_id=%s resource_type=%s error_type=%s",
            cleanup_job_id,
            resource_type,
            type(exc).__name__,
        )
        return False
    await repository.mark_storage_cleanup_completed(cleanup_job_id)
    return True


async def retry_pending_storage_cleanups(
    *,
    repository: TestSetRepository,
    storage: TestSetStorage,
    limit: int = 100,
) -> tuple[int, int]:
    job_ids = await repository.list_pending_storage_cleanup_job_ids(limit=limit)
    completed = 0
    failed = 0
    for job_id in job_ids:
        if await execute_storage_cleanup_job(
            job_id,
            repository=repository,
            storage=storage,
        ):
            completed += 1
        else:
            failed += 1
    return completed, failed
