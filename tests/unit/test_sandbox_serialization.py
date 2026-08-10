from __future__ import annotations

import base64

import pytest

from app.models.execution import BinaryRef, NodeOutput
from app.services.sandbox_serialization import (
    SandboxSerializationError,
    deserialize_sandbox_result,
    serialize_sandbox_request,
)
from sandbox_protocol.models import POLICY_DIGEST, SandboxLimits


def test_serialize_request_preserves_binding_source_and_inlines_binary_only() -> None:
    output = NodeOutput(
        text="hello",
        binary=[
            BinaryRef(
                data=base64.b64encode(b"payload").decode("ascii"),
                mime_type="image/png",
                size_bytes=7,
            )
        ],
        metadata={"_binding_source": {"node_id": "ocr_1", "output_path": ["$"]}, "tag": "safe"},
        structured={"answer": 1},
    )

    request = serialize_sandbox_request(
        request_id="req-1",
        code="def main(inputs):\n    return {'text': 'ok'}",
        inputs={"doc": output},
        limits=SandboxLimits(),
        policy_digest=POLICY_DIGEST,
    )

    assert request.inputs["doc"].metadata["_binding_source"] == {
        "node_id": "ocr_1",
        "output_path": ["$"],
    }
    assert request.inputs["doc"].binary[0].data == base64.b64encode(b"payload").decode("ascii")


def test_serialize_request_rejects_binary_refs_and_requires_inline_data() -> None:
    with pytest.raises(SandboxSerializationError, match="binary refs are not allowed"):
        serialize_sandbox_request(
            request_id="req-1",
            code="def main(inputs):\n    return {'text': 'ok'}",
            inputs={
                "doc": NodeOutput(
                    binary=[
                        BinaryRef(ref="/tmp/local-only.png", mime_type="image/png", size_bytes=5)
                    ]
                )
            },
            limits=SandboxLimits(),
            policy_digest=POLICY_DIGEST,
        )

    with pytest.raises(SandboxSerializationError, match="binary payload is missing data"):
        serialize_sandbox_request(
            request_id="req-1",
            code="def main(inputs):\n    return {'text': 'ok'}",
            inputs={"doc": NodeOutput(binary=[BinaryRef(mime_type="image/png", size_bytes=5)])},
            limits=SandboxLimits(),
            policy_digest=POLICY_DIGEST,
        )


def test_serialize_request_rejects_invalid_base64_and_size_mismatch() -> None:
    with pytest.raises(SandboxSerializationError, match="invalid base64"):
        serialize_sandbox_request(
            request_id="req-1",
            code="def main(inputs):\n    return {'text': 'ok'}",
            inputs={
                "doc": NodeOutput(
                    binary=[BinaryRef(data="***", mime_type="image/png", size_bytes=5)]
                )
            },
            limits=SandboxLimits(),
            policy_digest=POLICY_DIGEST,
        )

    with pytest.raises(SandboxSerializationError, match="size mismatch"):
        serialize_sandbox_request(
            request_id="req-1",
            code="def main(inputs):\n    return {'text': 'ok'}",
            inputs={
                "doc": NodeOutput(
                    binary=[
                        BinaryRef(
                            data=base64.b64encode(b"payload").decode("ascii"),
                            mime_type="image/png",
                            size_bytes=999,
                        )
                    ]
                )
            },
            limits=SandboxLimits(),
            policy_digest=POLICY_DIGEST,
        )


def test_serialize_request_rejects_oversized_decoded_binary() -> None:
    limits = SandboxLimits(max_binary_item_bytes=4)
    with pytest.raises(SandboxSerializationError, match="decoded binary exceeds item limit"):
        serialize_sandbox_request(
            request_id="req-1",
            code="def main(inputs):\n    return {'text': 'ok'}",
            inputs={
                "doc": NodeOutput(
                    binary=[
                        BinaryRef(
                            data=base64.b64encode(b"payload").decode("ascii"),
                            mime_type="image/png",
                            size_bytes=7,
                        )
                    ]
                )
            },
            limits=limits,
            policy_digest=POLICY_DIGEST,
        )


def test_deserialize_result_returns_deep_isolated_node_output() -> None:
    result = deserialize_sandbox_result(
        {
            "text": "ok",
            "binary": [
                {
                    "data": base64.b64encode(b"out").decode("ascii"),
                    "mime_type": "text/plain",
                    "size_bytes": 3,
                }
            ],
            "structured": {"answer": 1},
            "metadata": {"safe": True},
        }
    )

    result.structured["answer"] = 2
    assert result.binary[0].ref == ""
    assert result.metadata == {"safe": True}


def test_serialize_request_requires_non_empty_code_and_respects_code_bytes() -> None:
    with pytest.raises(SandboxSerializationError, match="code must be a non-empty string"):
        serialize_sandbox_request(
            request_id="req-1",
            code="",
            inputs={},
            limits=SandboxLimits(),
            policy_digest=POLICY_DIGEST,
        )

    with pytest.raises(SandboxSerializationError, match="code exceeds max_code_bytes"):
        serialize_sandbox_request(
            request_id="req-1",
            code="x" * 70_000,
            inputs={},
            limits=SandboxLimits(),
            policy_digest=POLICY_DIGEST,
        )
