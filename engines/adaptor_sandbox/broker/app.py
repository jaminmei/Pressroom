from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from engines.adaptor_sandbox.broker.uds_client import RunnerUdsClient, RunnerUnavailableError
from sandbox_protocol.models import POLICY_DIGEST, SandboxLimits, SandboxRequest, SandboxResponse


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    version: str
    runner_reachable: bool


class ConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: str
    version: str
    schema_version: str
    policy_digest: str
    limits: dict[str, Any]
    network_policy: str


runner_client: Any = RunnerUdsClient(Path("/run/adaptor-sandbox/runner.sock"))

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, title="Adaptor Sandbox Broker")


_LIMITS = SandboxLimits()
_VERSION = "1.0"
_PROCESS_LOCK = threading.Lock()


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = "unknown"
    if isinstance(exc.body, dict):
        raw_request_id = exc.body.get("request_id")
        if isinstance(raw_request_id, str) and raw_request_id:
            request_id = raw_request_id
    message = "invalid request"
    for error in exc.errors():
        msg = error.get("msg")
        if isinstance(msg, str) and msg:
            message = msg.replace("Value error, ", "")
            break
    payload = {
        "request_id": request_id,
        "status": "error",
        "result": None,
        "error": {"kind": "invalid", "message": message},
        "metrics": {},
    }
    return JSONResponse(status_code=422, content=payload)


def _runner_attestation() -> dict[str, Any]:
    status = runner_client.health()
    attested = (
        bool(status.get("runner_reachable"))
        and bool(status.get("attested", False))
        and status.get("policy_digest") == POLICY_DIGEST
        and status.get("network_policy") == "runner-network-none"
    )
    return {
        **status,
        "runner_reachable": attested,
        "attested": attested,
    }


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    try:
        status = _runner_attestation()
    except Exception:
        status = {"runner_reachable": False, "attested": False}
    return HealthResponse(
        status="ok",
        version=_VERSION,
        runner_reachable=bool(status.get("runner_reachable")),
    )


@app.get("/config", response_model=ConfigResponse)
def config() -> ConfigResponse:
    try:
        status = _runner_attestation()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Runner attestation unavailable") from exc
    if not status.get("attested"):
        raise HTTPException(status_code=503, detail="Runner attestation unavailable")
    return ConfigResponse(
        engine="adaptor-sandbox",
        version=str(status.get("version", _VERSION)),
        schema_version="v1",
        policy_digest=str(status.get("policy_digest", POLICY_DIGEST)),
        limits=dict(status.get("limits", {"max_code_bytes": _LIMITS.max_code_bytes})),
        network_policy=str(status.get("network_policy", "runner-network-none")),
    )


@app.post("/process", response_model=SandboxResponse)
def process(request: SandboxRequest) -> SandboxResponse | JSONResponse:
    if not _PROCESS_LOCK.acquire(blocking=False):
        queue_full = {
            "request_id": request.request_id,
            "status": "error",
            "result": None,
            "error": {"kind": "queue_full", "message": "runner busy"},
            "metrics": {},
        }
        return JSONResponse(status_code=503, content=queue_full)
    try:
        status = _runner_attestation()
        if not status.get("attested"):
            unavailable = {
                "request_id": request.request_id,
                "status": "error",
                "result": None,
                "error": {"kind": "unavailable", "message": request.request_id},
                "metrics": {},
            }
            return JSONResponse(status_code=503, content=unavailable)
        try:
            raw_response = runner_client.process(request.model_dump(mode="json"))
        except RunnerUnavailableError:
            raw_response = {
                "request_id": request.request_id,
                "status": "error",
                "result": None,
                "error": {"kind": "unavailable", "message": request.request_id},
                "metrics": {},
            }
        response = SandboxResponse.model_validate(raw_response)
        if response.status == "ok":
            return response
        assert response.error is not None
        kind = response.error.kind.value
        status_code = {
            "invalid": 422,
            "code": 422,
            "runtime": 422,
            "resource": 422,
            "timeout": 504,
            "unavailable": 503,
            "queue_full": 503,
            "protocol": 502,
            "internal": 502,
        }[kind]
        return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))
    finally:
        _PROCESS_LOCK.release()
