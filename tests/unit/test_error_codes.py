from __future__ import annotations

from app.errors.error_codes import ERROR_CODE_STATUS_MAP, ErrorCode, resolve_status_code


def test_error_code_status_map_covers_all_enum_members() -> None:
    assert set(ERROR_CODE_STATUS_MAP) == set(ErrorCode)


def test_error_code_status_map_matches_public_api_contract() -> None:
    expected = {
        ErrorCode.AUTH_REQUIRED: 401,
        ErrorCode.AUTH_INVALID_CREDENTIALS: 401,
        ErrorCode.AUTH_SESSION_EXPIRED: 401,
        ErrorCode.AUTH_TOKEN_INVALID: 401,
        ErrorCode.AUTH_TOKEN_EXPIRED: 401,
        ErrorCode.AUTH_EMAIL_ALREADY_EXISTS: 409,
        ErrorCode.INVALID_WORKFLOW: 400,
        ErrorCode.INVALID_NODE_CONFIG: 422,
        ErrorCode.FILE_TOO_LARGE: 413,
        ErrorCode.FILE_QUOTA_EXCEEDED: 413,
        ErrorCode.UNSUPPORTED_FORMAT: 422,
        ErrorCode.WORKFLOW_NOT_FOUND: 404,
        ErrorCode.TASK_NOT_FOUND: 404,
        ErrorCode.TASK_RESULT_NOT_READY: 409,
        ErrorCode.NODE_NOT_FOUND: 404,
        ErrorCode.DUPLICATE_WORKFLOW_VERSION: 409,
        ErrorCode.WORKFLOW_VERSION_CONFLICT: 409,
        ErrorCode.WORKSPACE_NOT_FOUND: 404,
        ErrorCode.WORKSPACE_FORBIDDEN: 403,
        ErrorCode.WORKSPACE_NOT_EMPTY: 409,
        ErrorCode.PROVIDER_NOT_FOUND: 404,
        ErrorCode.FILE_NOT_FOUND: 404,
        ErrorCode.FILE_IN_USE: 409,
        ErrorCode.FILE_CLEANUP_FAILED: 503,
        ErrorCode.TEST_SET_NOT_FOUND: 404,
        ErrorCode.TEST_SET_IN_USE: 409,
        ErrorCode.DOCUMENT_NOT_FOUND: 404,
        ErrorCode.DOCUMENT_IN_USE: 409,
        ErrorCode.REQUIRED_CAPABILITY_MISSING: 403,
        ErrorCode.RESOURCE_NOT_FOUND: 404,
        ErrorCode.REQUEST_CONFLICT: 409,
        ErrorCode.REQUEST_VALIDATION_FAILED: 422,
        ErrorCode.ENGINE_TIMEOUT: 504,
        ErrorCode.ENGINE_UNREACHABLE: 503,
        ErrorCode.ENGINE_INTERNAL_ERROR: 500,
        ErrorCode.ENGINE_INVALID_RESPONSE: 502,
        ErrorCode.ENGINE_RATE_LIMITED: 503,
        ErrorCode.TASK_CANCELLED: 200,
        ErrorCode.TASK_ALREADY_RUNNING: 409,
        ErrorCode.NODE_NOT_FAILED: 409,
        ErrorCode.NODE_DEPENDENCY_FAILED: 500,
        ErrorCode.WORKFLOW_CYCLE_DETECTED: 400,
        ErrorCode.DB_WRITE_FAILED: 500,
        ErrorCode.DB_READ_FAILED: 500,
        ErrorCode.REDIS_UNAVAILABLE: 503,
        ErrorCode.CELERY_WORKER_UNAVAILABLE: 503,
        ErrorCode.STORAGE_FULL: 500,
        ErrorCode.INTERNAL_ERROR: 500,
    }
    assert ERROR_CODE_STATUS_MAP == expected


def test_resolve_status_code_uses_map_and_default() -> None:
    assert resolve_status_code(ErrorCode.ENGINE_TIMEOUT) == 504

    removed = ERROR_CODE_STATUS_MAP.pop(ErrorCode.INTERNAL_ERROR)
    try:
        assert resolve_status_code(ErrorCode.INTERNAL_ERROR, default=599) == 599
    finally:
        ERROR_CODE_STATUS_MAP[ErrorCode.INTERNAL_ERROR] = removed
