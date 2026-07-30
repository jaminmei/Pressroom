import hmac
import json
import subprocess
import sys
import tempfile
from functools import lru_cache
from hashlib import sha256
from os import environ
from pathlib import Path
from typing import Literal, Mapping, TypedDict

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

RuntimeRole = Literal["backend", "worker"]


class RuntimeEnvReport(TypedDict):
    ok: bool
    checks: dict[str, bool]


class WorkspaceRuntimeEnvError(RuntimeError):
    pass


RUNTIME_ATTESTATION_REQUEST_PREFIX = b"docconv/runtime-attestation/request/v1\x00"
RUNTIME_ATTESTATION_RESPONSE_PREFIX = b"docconv/runtime-attestation/response/v1\x00"


class Settings(BaseSettings):
    app_name: str = "Document Conversion"
    app_version: str = "0.2.11"
    storage_root: str = "./storage"
    temp_dir: str = str(tempfile.gettempdir())

    ocr_engine_url: str = "http://localhost:8002"
    vlm_engine_url: str = "http://localhost:8003"
    text_engine_url: str = "http://localhost:8004"
    markitdown_engine_url: str = "http://localhost:8005"
    docling_engine_url: str = "http://localhost:8007"
    layout_detection_engine_url: str = "http://localhost:8006"
    image_enhancement_engine_url: str = "http://localhost:8008"
    image_rotation_engine_url: str = "http://localhost:8009"

    cors_origins: str = Field(
        default="http://localhost:5173",
        validation_alias=AliasChoices("CORS_ORIGINS", "BACKEND_CORS_ORIGINS"),
    )
    ocr_mock_mode: bool = True
    max_file_size_mb: int = 50
    max_pdf_pages: int = 100
    auth_session_secret: str | None = None
    auth_session_cookie_name: str = "docconv_session"
    auth_session_ttl_hours: int = 168
    auth_session_same_site: Literal["lax", "strict", "none"] = "lax"
    auth_session_secure: bool = False
    workspace_rbac_enforced: bool = True
    runtime_attestation_url: str = "http://backend:8000/api/internal/runtime-attestation"
    runtime_attestation_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    auth_session_domain: str | None = None
    auth_session_path: str = "/"

    workflow_api_timeout_seconds: int = Field(
        default=300,
        ge=1,
        description=(
            "Timeout in seconds for blocking-mode workflow run API "
            "(POST /api/v1/workflows/{id}/run)"
        ),
    )

    input_fetch_max_bytes: int = Field(
        default=104857600,  # 100 MiB
        ge=1,
        description="Hard ceiling in bytes on a single remote inputs.file download.",
    )
    input_fetch_timeout_seconds: int = Field(
        default=30,
        ge=1,
        description="Connect+read timeout in seconds for remote inputs.file fetches.",
    )
    input_fetch_allow_private_hosts: bool = Field(
        default=False,
        description=(
            "Opt-in to allow fetching from private/loopback/link-local hosts. "
            "Default false (SSRF-safe); set true only in trusted-internal deployments."
        ),
    )
    provider_allow_private_hosts: bool = Field(
        default=True,
        description=(
            "Allow Provider endpoints on private and loopback networks. "
            "Link-local, cloud metadata, multicast, reserved, and unspecified "
            "destinations remain blocked. Enable only with the documented "
            "multi-tenant network risk accepted."
        ),
    )

    input_upload_max_bytes: int = Field(
        default=20971520,  # 20 MiB
        ge=1,
        description="Hard ceiling on a single /run/upload multipart body in bytes",
    )
    input_upload_rate_limit_per_minute: int = Field(
        default=10,
        ge=1,
        description="Per-API-key request limit on /run/upload endpoint",
    )
    api_usage_retention_max_bytes_per_workflow: int = Field(
        default=52_428_800,
        ge=1,
        description="Per-workflow storage budget for API Forward usage traces.",
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def check_workspace_runtime_env(
    *, expect_enforced: bool, source: Mapping[str, str] = environ
) -> RuntimeEnvReport:
    current = _runtime_values(source)
    expected = "true" if expect_enforced else "false"
    checks = {
        "workspace_rbac_enforced_present": bool(current["WORKSPACE_RBAC_ENFORCED"]),
        "workspace_rbac_enforced_matches": current["WORKSPACE_RBAC_ENFORCED"].lower() == expected,
        "database_url_present": bool(current["DATABASE_URL"]),
        "provider_db_path_present": bool(current["PROVIDER_DB_PATH"]),
        "provider_encryption_key_present": bool(current["PROVIDER_ENCRYPTION_KEY"]),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _runtime_values(source: Mapping[str, str]) -> dict[str, str]:
    return {
        "WORKSPACE_RBAC_ENFORCED": source.get("WORKSPACE_RBAC_ENFORCED", ""),
        "DATABASE_URL": source.get("DATABASE_URL", ""),
        "PROVIDER_DB_PATH": source.get("PROVIDER_DB_PATH", ""),
        "PROVIDER_ENCRYPTION_KEY": source.get("PROVIDER_ENCRYPTION_KEY", ""),
    }


def canonical_runtime_config(source: Mapping[str, str] = environ) -> bytes:
    """Return the secret-bearing runtime config in a deterministic, non-display form."""
    values = _runtime_values(source)
    report = check_workspace_runtime_env(
        expect_enforced=values["WORKSPACE_RBAC_ENFORCED"].lower() == "true", source=source
    )
    if not report["ok"]:
        raise WorkspaceRuntimeEnvError("runtime configuration is incomplete")

    database_url = make_url(values["DATABASE_URL"])
    normalized_query = {
        key: list(items) for key, items in sorted(database_url.normalized_query.items())
    }
    payload = {
        "workspace_rbac_enforced": values["WORKSPACE_RBAC_ENFORCED"].lower() == "true",
        "database": {
            "drivername": database_url.drivername,
            "username": database_url.username,
            "password": database_url.password,
            "host": database_url.host,
            "port": database_url.port,
            "database": database_url.database,
            "query": normalized_query,
        },
        "provider_db_path": str(Path(values["PROVIDER_DB_PATH"]).expanduser().resolve()),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def runtime_attestation_request_proof(nonce: str, *, secret: str | None = None) -> str:
    key = secret if secret is not None else environ.get("PROVIDER_ENCRYPTION_KEY", "")
    if not key:
        raise WorkspaceRuntimeEnvError("provider encryption key is not configured")
    message = RUNTIME_ATTESTATION_REQUEST_PREFIX + nonce.encode()
    return hmac.new(key.encode(), message, sha256).hexdigest()


def runtime_attestation_digest(
    nonce: str,
    *,
    source: Mapping[str, str] = environ,
    secret: str | None = None,
) -> str:
    values = _runtime_values(source)
    key = secret if secret is not None else values["PROVIDER_ENCRYPTION_KEY"]
    if not key:
        raise WorkspaceRuntimeEnvError("provider encryption key is not configured")
    message = (
        RUNTIME_ATTESTATION_RESPONSE_PREFIX
        + nonce.encode()
        + b"\x00"
        + canonical_runtime_config(source)
    )
    return hmac.new(key.encode(), message, sha256).hexdigest()


def require_workspace_runtime_env(current_role: RuntimeRole) -> None:
    if not get_settings().workspace_rbac_enforced:
        raise WorkspaceRuntimeEnvError("public deployments require workspace RBAC enforcement")
    report = check_workspace_runtime_env(expect_enforced=True)
    if not report["ok"]:
        raise WorkspaceRuntimeEnvError
    # Force parsing and path normalization before either process starts.
    canonical_runtime_config()
    readiness = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "scripts/check-workspace-rbac-readiness.py"),
            "--mode",
            "pre-migration",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if readiness.returncode:
        raise WorkspaceRuntimeEnvError
