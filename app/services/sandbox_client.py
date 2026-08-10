from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.errors.error_codes import ErrorCode
from app.errors.exceptions import EngineError
from app.models.execution import NodeOutput
from app.services.sandbox_serialization import deserialize_sandbox_result, serialize_sandbox_request
from sandbox_protocol.models import POLICY_DIGEST, SandboxLimits, SandboxResponse, SandboxStatus


class _StrictHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    version: str
    runner_reachable: bool


class _StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: str
    version: str
    schema_version: str
    policy_digest: str
    limits: dict[str, Any]
    network_policy: str


class SandboxClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def process(
        self,
        *,
        request_id: str,
        code: str,
        inputs: dict[str, NodeOutput],
        limits: SandboxLimits | None = None,
        policy_digest: str = POLICY_DIGEST,
    ) -> NodeOutput:
        try:
            request_payload = serialize_sandbox_request(
                request_id=request_id,
                code=code,
                inputs=inputs,
                limits=limits or SandboxLimits(),
                policy_digest=policy_digest,
            )
        except ValueError as exc:
            raise EngineError(
                ErrorCode.INVALID_NODE_CONFIG,
                "Sandbox request is invalid",
                engine_name="processor/adaptor",
            ) from exc

        response = await self._request(
            "POST",
            "/process",
            json=request_payload.model_dump(mode="json"),
        )
        try:
            payload = SandboxResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise EngineError(
                ErrorCode.ENGINE_INVALID_RESPONSE,
                "Sandbox broker returned an invalid response",
                engine_name="processor/adaptor",
            ) from exc

        if payload.status != SandboxStatus.OK or payload.result is None:
            raise EngineError(
                ErrorCode.INVALID_NODE_CONFIG,
                "Sandbox request was rejected",
                engine_name="processor/adaptor",
            )
        if not payload.result.model_fields_set:
            raise EngineError(
                ErrorCode.ENGINE_INVALID_RESPONSE,
                "Sandbox broker returned an invalid response",
                engine_name="processor/adaptor",
            )
        output = deserialize_sandbox_result(payload.result.model_dump(mode="json"))
        metrics = payload.metrics if isinstance(payload.metrics, dict) else {}
        wall_time_ms = metrics.get("wall_time_ms")
        if isinstance(wall_time_ms, int):
            metadata = dict(output.metadata)
            metadata.setdefault("processing_time_ms", wall_time_ms)
            output = output.model_copy(update={"metadata": metadata})
        return output

    async def health(self) -> dict[str, Any]:
        response = await self._request("GET", "/health")
        try:
            return _StrictHealth.model_validate(response.json()).model_dump(mode="json")
        except (ValueError, ValidationError) as exc:
            raise EngineError(
                ErrorCode.ENGINE_INVALID_RESPONSE,
                "Sandbox broker returned an invalid health response",
                engine_name="processor/adaptor",
            ) from exc

    async def config(self) -> dict[str, Any]:
        response = await self._request("GET", "/config")
        try:
            return _StrictConfig.model_validate(response.json()).model_dump(mode="json")
        except (ValueError, ValidationError) as exc:
            raise EngineError(
                ErrorCode.ENGINE_INVALID_RESPONSE,
                "Sandbox broker returned an invalid config response",
                engine_name="processor/adaptor",
            ) from exc

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, f"{self._base_url}{path}", **kwargs)
        except httpx.TimeoutException as exc:
            raise EngineError(
                ErrorCode.ENGINE_TIMEOUT,
                "Sandbox broker timed out",
                engine_name="processor/adaptor",
            ) from exc
        except httpx.RequestError as exc:
            raise EngineError(
                ErrorCode.ENGINE_UNREACHABLE,
                "Sandbox broker is unreachable",
                engine_name="processor/adaptor",
            ) from exc

        if response.status_code >= 400:
            error_kind: str | None = None
            error_details: dict[str, Any] | None = None
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    error = payload.get("error")
                    if isinstance(error, dict):
                        raw_kind = error.get("kind")
                        if isinstance(raw_kind, str):
                            error_kind = raw_kind
                            error_details = {"sandbox_kind": raw_kind}
            except ValueError:
                error_kind = None

            if error_kind == "queue_full":
                raise EngineError(
                    ErrorCode.ENGINE_RATE_LIMITED,
                    "Sandbox broker is busy",
                    engine_name="processor/adaptor",
                    details=error_details,
                )
            if error_kind == "unavailable":
                raise EngineError(
                    ErrorCode.ENGINE_UNREACHABLE,
                    "Sandbox broker is unreachable",
                    engine_name="processor/adaptor",
                    details=error_details,
                )
            if error_kind == "timeout":
                raise EngineError(
                    ErrorCode.ENGINE_TIMEOUT,
                    "Sandbox broker timed out",
                    engine_name="processor/adaptor",
                    details=error_details,
                )
            if error_kind in {"invalid", "code", "runtime", "resource"}:
                raise EngineError(
                    ErrorCode.INVALID_NODE_CONFIG,
                    "Sandbox request was rejected",
                    engine_name="processor/adaptor",
                    details=error_details,
                )
            if error_kind in {"protocol", "internal"}:
                raise EngineError(
                    ErrorCode.ENGINE_INVALID_RESPONSE,
                    "Sandbox broker returned an invalid response",
                    engine_name="processor/adaptor",
                    details=error_details,
                )
            error_code = (
                ErrorCode.INVALID_NODE_CONFIG
                if response.status_code == 422
                else ErrorCode.ENGINE_INVALID_RESPONSE
            )
            message = (
                "Sandbox request was rejected"
                if response.status_code == 422
                else f"Sandbox broker returned HTTP {response.status_code}"
            )
            raise EngineError(
                error_code,
                message,
                engine_name="processor/adaptor",
                details=error_details,
            )
        return response
