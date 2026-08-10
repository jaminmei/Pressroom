from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from sandbox_protocol import framing
from sandbox_protocol.models import (
    POLICY_DIGEST,
    BinaryPayload,
    ErrorKind,
    ErrorPayload,
    SandboxLimits,
    SandboxPolicy,
    SandboxRequest,
    SandboxResponse,
    SandboxStatus,
)


def test_request_model_forbids_extra_fields_and_requires_digest() -> None:
    with pytest.raises(ValidationError):
        SandboxRequest.model_validate(
            {
                "request_id": "req-1",
                "code": "def main(inputs):\n    return {'text': 'ok'}",
                "inputs": {},
                "limits": SandboxLimits().model_dump(),
                "policy_digest": POLICY_DIGEST,
                "unexpected": True,
            }
        )


def test_response_model_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SandboxResponse.model_validate(
            {
                "request_id": "req-1",
                "status": SandboxStatus.OK.value,
                "result": {
                    "text": "ok",
                    "binary": [],
                    "structured": None,
                    "metadata": {},
                },
                "error": None,
                "metrics": {"wall_time_ms": 1},
                "unexpected": True,
            }
        )


def test_policy_digest_is_stable_for_defaults() -> None:
    policy = SandboxPolicy()
    assert policy.digest() == POLICY_DIGEST


def test_binary_payload_requires_inline_data_only() -> None:
    with pytest.raises(ValidationError):
        BinaryPayload.model_validate(
            {
                "data": "aGVsbG8=",
                "mime_type": "text/plain",
                "size_bytes": 5,
                "ref": "/tmp/secret",
            }
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"data": "***", "mime_type": "text/plain", "size_bytes": 5},
            "invalid base64",
        ),
        (
            {"data": "aGVsbG8=", "mime_type": "text/plain", "size_bytes": 4},
            "size mismatch",
        ),
    ],
)
def test_binary_payload_validates_live_base64_and_size(payload: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        BinaryPayload.model_validate(payload)


def test_request_rejects_oversized_binary_item_and_total_before_execution() -> None:
    item_payload = {"data": "aGVsbG8=", "mime_type": "text/plain", "size_bytes": 5}

    with pytest.raises(ValidationError, match="binary item exceeds"):
        SandboxRequest.model_validate(
            {
                "request_id": "req-1",
                "code": "def main(inputs):\n    return {'text': 'ok'}",
                "inputs": {
                    "doc": {
                        "text": None,
                        "binary": [item_payload],
                        "structured": None,
                        "metadata": {},
                    }
                },
                "limits": {**SandboxLimits().model_dump(), "max_binary_item_bytes": 4},
                "policy_digest": POLICY_DIGEST,
            }
        )

    with pytest.raises(ValidationError, match="binary total exceeds"):
        SandboxRequest.model_validate(
            {
                "request_id": "req-1",
                "code": "def main(inputs):\n    return {'text': 'ok'}",
                "inputs": {
                    "doc": {
                        "text": None,
                        "binary": [item_payload, item_payload],
                        "structured": None,
                        "metadata": {},
                    }
                },
                "limits": {**SandboxLimits().model_dump(), "max_binary_total_bytes": 8},
                "policy_digest": POLICY_DIGEST,
            }
        )


def test_response_rejects_oversized_metrics_frame_budget() -> None:
    with pytest.raises(ValidationError, match="metrics payload exceeds"):
        SandboxResponse.model_validate(
            {
                "request_id": "req-1",
                "status": "ok",
                "result": {
                    "text": "ok",
                    "binary": [],
                    "structured": None,
                    "metadata": {},
                },
                "error": None,
                "metrics": {"blob": "x" * 5000},
            }
        )


def test_encode_decode_frame_round_trip() -> None:
    payload = SandboxRequest(
        request_id="req-1",
        code="def main(inputs):\n    return {'text': 'ok'}",
        inputs={},
        limits=SandboxLimits(),
        policy_digest=POLICY_DIGEST,
    )

    encoded = framing.encode_message(payload, max_bytes=4096)
    decoded = framing.decode_message(encoded, SandboxRequest, max_bytes=4096)

    assert decoded == payload


@pytest.mark.parametrize(
    "payload_bytes",
    [b"", b"\x00\x00\x00", b"\x00\x00\x00\x05{}", b"\x00\x00\x00\x02{}junk"],
)
def test_decode_message_rejects_malformed_frames(payload_bytes: bytes) -> None:
    with pytest.raises(framing.FrameError):
        framing.decode_message(payload_bytes, SandboxRequest, max_bytes=4096)


def test_decode_message_rejects_oversized_frame() -> None:
    raw = json.dumps(
        {
            "request_id": "req-1",
            "code": "x" * 100,
            "inputs": {},
            "limits": SandboxLimits().model_dump(),
            "policy_digest": POLICY_DIGEST,
        }
    ).encode("utf-8")
    frame = len(raw).to_bytes(4, "big") + raw

    with pytest.raises(framing.FrameTooLargeError):
        framing.decode_message(frame, SandboxRequest, max_bytes=32)


def test_error_payload_uses_stable_error_kinds() -> None:
    payload = ErrorPayload(kind=ErrorKind.TIMEOUT, message="request timed out")
    response = SandboxResponse(
        request_id="req-1",
        status=SandboxStatus.ERROR,
        result=None,
        error=payload,
        metrics={"wall_time_ms": 8000},
    )

    assert response.error is not None
    assert response.error.kind == ErrorKind.TIMEOUT
