"""Authenticated backend/worker runtime configuration attestation."""

from __future__ import annotations

import hmac
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import (
    WorkspaceRuntimeEnvError,
    runtime_attestation_digest,
    runtime_attestation_request_proof,
)

router = APIRouter()
_NONCE_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RuntimeAttestationRequest(BaseModel):
    nonce: str
    proof: str


class RuntimeAttestationResponse(BaseModel):
    nonce: str
    digest: str


@router.post(
    "/internal/runtime-attestation",
    response_model=RuntimeAttestationResponse,
    include_in_schema=False,
)
async def attest_runtime(payload: RuntimeAttestationRequest) -> RuntimeAttestationResponse:
    if not _NONCE_PATTERN.fullmatch(payload.nonce) or not _NONCE_PATTERN.fullmatch(payload.proof):
        raise HTTPException(status_code=400, detail="Invalid attestation request")
    try:
        expected_proof = runtime_attestation_request_proof(payload.nonce)
        if not hmac.compare_digest(payload.proof, expected_proof):
            raise HTTPException(status_code=401, detail="Invalid attestation request")
        digest = runtime_attestation_digest(payload.nonce)
    except WorkspaceRuntimeEnvError as exc:
        raise HTTPException(status_code=503, detail="Runtime attestation unavailable") from exc
    return RuntimeAttestationResponse(nonce=payload.nonce, digest=digest)
