from __future__ import annotations

import base64
import binascii
from copy import deepcopy

from app.models.execution import BinaryRef, NodeOutput
from sandbox_protocol.models import (
    BinaryPayload,
    NodeOutputPayload,
    SandboxLimits,
    SandboxRequest,
)


class SandboxSerializationError(ValueError):
    pass


def _validated_code(code: str, limits: SandboxLimits) -> str:
    if not isinstance(code, str) or not code.strip():
        raise SandboxSerializationError("code must be a non-empty string")
    if len(code.encode("utf-8")) > limits.max_code_bytes:
        raise SandboxSerializationError("code exceeds max_code_bytes")
    return code


def _decode_binary(binary: BinaryRef, limits: SandboxLimits) -> BinaryPayload:
    if binary.ref:
        raise SandboxSerializationError("binary refs are not allowed")

    encoded_data = binary.data
    if not encoded_data:
        raise SandboxSerializationError("binary payload is missing data")
    try:
        decoded = base64.b64decode(encoded_data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SandboxSerializationError("invalid base64") from exc
    if binary.size_bytes != len(decoded):
        raise SandboxSerializationError("size mismatch")
    if len(decoded) > limits.max_binary_item_bytes:
        raise SandboxSerializationError("decoded binary exceeds item limit")
    return BinaryPayload(
        data=encoded_data,
        mime_type=binary.mime_type,
        size_bytes=binary.size_bytes,
        dimensions=deepcopy(binary.dimensions),
    )


def _serialize_output(output: NodeOutput, limits: SandboxLimits) -> NodeOutputPayload:
    binary = [_decode_binary(item, limits) for item in output.binary]
    total_binary = sum(item.size_bytes for item in binary)
    if total_binary > limits.max_binary_total_bytes:
        raise SandboxSerializationError("decoded binary exceeds total limit")
    if output.text is not None and len(output.text.encode("utf-8")) > limits.max_text_bytes:
        raise SandboxSerializationError("text exceeds max_text_bytes")
    if output.structured is not None:
        import json

        structured_bytes = len(
            json.dumps(output.structured, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        if structured_bytes > limits.max_structured_bytes:
            raise SandboxSerializationError("structured exceeds max_structured_bytes")
    return NodeOutputPayload(
        text=output.text,
        binary=binary,
        structured=deepcopy(output.structured),
        metadata=deepcopy(output.metadata),
    )


def serialize_sandbox_request(
    *,
    request_id: str,
    code: str,
    inputs: dict[str, NodeOutput],
    limits: SandboxLimits,
    policy_digest: str,
) -> SandboxRequest:
    payload = SandboxRequest(
        request_id=request_id,
        code=_validated_code(code, limits),
        inputs={name: _serialize_output(output, limits) for name, output in inputs.items()},
        limits=limits,
        policy_digest=policy_digest,
    )
    return payload


def deserialize_sandbox_result(result: dict) -> NodeOutput:
    payload = NodeOutputPayload.model_validate(result)
    return NodeOutput(
        text=payload.text,
        binary=[
            BinaryRef(
                ref="",
                data=item.data,
                mime_type=item.mime_type,
                size_bytes=item.size_bytes,
                dimensions=deepcopy(item.dimensions),
            )
            for item in payload.binary
        ],
        structured=deepcopy(payload.structured),
        metadata=deepcopy(payload.metadata),
    )
