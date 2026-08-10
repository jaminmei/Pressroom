from __future__ import annotations

import base64
import binascii
import hashlib
import json
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SandboxStatus(str, Enum):
    OK = "ok"
    ERROR = "error"


class ErrorKind(str, Enum):
    INVALID = "invalid"
    CODE = "code"
    RUNTIME = "runtime"
    RESOURCE = "resource"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    QUEUE_FULL = "queue_full"
    PROTOCOL = "protocol"
    INTERNAL = "internal"


class BinaryPayload(StrictModel):
    data: str
    mime_type: str = ""
    size_bytes: int = Field(ge=0)
    dimensions: dict | None = None

    @model_validator(mode="after")
    def _validate_base64_and_size(self) -> "BinaryPayload":
        encoded_length = len(self.data.encode("ascii", "ignore"))
        max_encoded_size = ((self.size_bytes + 2) // 3) * 4 + 4
        if encoded_length > max_encoded_size:
            raise ValueError("encoded binary exceeds expected size")
        try:
            decoded = base64.b64decode(self.data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid base64") from exc
        if len(decoded) != self.size_bytes:
            raise ValueError("size mismatch")
        return self


class NodeOutputPayload(StrictModel):
    text: str | None = None
    binary: list[BinaryPayload] = Field(default_factory=list)
    structured: dict | None = None
    metadata: dict = Field(default_factory=dict)


class ErrorPayload(StrictModel):
    kind: ErrorKind
    message: str = Field(min_length=1, max_length=512)


class SandboxLimits(StrictModel):
    connect_timeout_ms: int = 250
    write_timeout_ms: int = 1000
    read_timeout_ms: int = 5000
    wall_timeout_ms: int = 8000
    queue_capacity: int = 1
    max_code_bytes: int = 65536
    max_binary_item_bytes: int = 524288
    max_binary_total_bytes: int = 2097152
    max_text_bytes: int = 131072
    max_structured_bytes: int = 262144
    max_request_bytes: int = 3145728
    max_output_text_bytes: int = 131072
    max_output_structured_bytes: int = 262144
    max_output_binary_bytes: int = 524288
    max_response_bytes: int = 1048576
    max_cpu_seconds: int = 5
    max_address_space_bytes: int = 268435456
    max_fsize_bytes: int = 1048576
    max_nofile: int = 32
    max_nproc: int = 32
    recursion_limit: int = 200
    max_stdio_bytes: int = 4096
    max_ast_nodes: int = 2000


class SandboxPolicy(StrictModel):
    engine: str = "adaptor-sandbox"
    version: str = "phase04-v1"
    network_policy: str = "runner-network-none"
    execution_mode: str = "child-only"
    builtin_policy: str = "allowlist"
    ast_policy: str = "restricted-python-main-only"
    limits: SandboxLimits = Field(default_factory=SandboxLimits)

    def digest(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


_DEFAULT_POLICY = SandboxPolicy()
POLICY_DIGEST = _DEFAULT_POLICY.digest()


class SandboxRequest(StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=65536)
    inputs: dict[str, NodeOutputPayload] = Field(default_factory=dict)
    limits: SandboxLimits = Field(default_factory=SandboxLimits)
    policy_digest: str = Field(min_length=64, max_length=64)

    @field_validator("code")
    @classmethod
    def _code_must_fit_utf8_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > SandboxLimits().max_code_bytes:
            raise ValueError("code exceeds max_code_bytes")
        return value

    @model_validator(mode="after")
    def _validate_binary_budget(self) -> "SandboxRequest":
        item_limit = self.limits.max_binary_item_bytes
        total_limit = self.limits.max_binary_total_bytes
        total = 0
        for payload in self.inputs.values():
            for item in payload.binary:
                if item.size_bytes > item_limit:
                    raise ValueError("binary item exceeds max_binary_item_bytes")
                total += item.size_bytes
        if total > total_limit:
            raise ValueError("binary total exceeds max_binary_total_bytes")
        return self


class RunnerAttestationRequest(StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    kind: Literal["attestation"] = "attestation"


class RunnerAttestationResponse(StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    runner_reachable: bool
    attested: bool
    policy_digest: str = Field(min_length=64, max_length=64)
    network_policy: str
    limits: dict[str, int]
    version: str


def validate_output_payload(result: object, limits: SandboxLimits) -> str:
    if not isinstance(result, dict):
        raise ValueError("invalid node output")
    payload = NodeOutputPayload.model_validate(result)
    if (
        payload.text is not None
        and len(payload.text.encode("utf-8")) > limits.max_output_text_bytes
    ):
        raise ValueError("output text exceeds max_output_text_bytes")
    if payload.structured is not None:
        structured_bytes = len(
            json.dumps(payload.structured, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        if structured_bytes > limits.max_output_structured_bytes:
            raise ValueError("output structured exceeds max_output_structured_bytes")
    metadata_bytes = len(
        json.dumps(payload.metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    if metadata_bytes > limits.max_output_structured_bytes:
        raise ValueError("output metadata exceeds response budget")
    total_binary = 0
    for item in payload.binary:
        if item.size_bytes > limits.max_output_binary_bytes:
            raise ValueError("output binary item exceeds max_output_binary_bytes")
        total_binary += item.size_bytes
    if total_binary > limits.max_binary_total_bytes:
        raise ValueError("output binary total exceeds max_binary_total_bytes")
    payload_json = payload.model_dump_json().encode("utf-8")
    if len(payload_json) > limits.max_response_bytes:
        raise ValueError("output payload exceeds max_response_bytes")
    return payload_json.decode("utf-8")


class SandboxResponse(StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    status: SandboxStatus
    result: NodeOutputPayload | None = None
    error: ErrorPayload | None = None
    metrics: dict[str, int | float | str | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_status_payloads(self) -> "SandboxResponse":
        if self.status == SandboxStatus.OK:
            if self.result is None or self.error is not None:
                raise ValueError("ok responses require result and forbid error")
        else:
            if self.error is None or self.result is not None:
                raise ValueError("error responses require error and forbid result")
        metrics_bytes = len(
            json.dumps(self.metrics, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        if metrics_bytes > 4096:
            raise ValueError("metrics payload exceeds response budget")
        return self
