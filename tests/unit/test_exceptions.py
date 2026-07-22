from __future__ import annotations

from app.errors import AppError, EngineError, ErrorCode, InfraError, ValidationError


def test_app_error_derives_status_from_error_code() -> None:
    error = AppError(
        error_code=ErrorCode.ENGINE_TIMEOUT,
        message="engine timeout",
        details={"node_id": "ocr_1"},
    )

    assert error.error_code is ErrorCode.ENGINE_TIMEOUT
    assert error.message == "engine timeout"
    assert error.status_code == 504
    assert error.details == {"node_id": "ocr_1"}


def test_app_error_allows_status_override() -> None:
    error = AppError(
        error_code=ErrorCode.ENGINE_TIMEOUT,
        message="custom status",
        status_code=499,
    )

    assert error.status_code == 499


def test_engine_error_merges_engine_and_retry_into_details() -> None:
    error = EngineError(
        error_code=ErrorCode.ENGINE_UNREACHABLE,
        message="engine unavailable",
        engine_name="ocr",
        retry_count=2,
        details={"node_id": "ocr_1"},
    )

    assert error.status_code == 503
    assert error.details == {
        "engine": "ocr",
        "retry_count": 2,
        "node_id": "ocr_1",
    }


def test_validation_and_infra_errors_inherit_app_error() -> None:
    validation_error = ValidationError(
        error_code=ErrorCode.INVALID_NODE_CONFIG,
        message="invalid config",
    )
    infra_error = InfraError(
        error_code=ErrorCode.REDIS_UNAVAILABLE,
        message="redis down",
    )

    assert isinstance(validation_error, AppError)
    assert isinstance(infra_error, AppError)
    assert validation_error.status_code == 422
    assert infra_error.status_code == 503
