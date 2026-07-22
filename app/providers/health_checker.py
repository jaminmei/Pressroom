"""Provider connection tests with protocol-aware auth and SSRF protection."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, cast
from urllib.parse import quote, urlencode

import httpx

from app.providers.auth import AuthResult, CredentialKind
from app.providers.models import ApiStyle, ModelProviderRow, ProviderType
from app.services.ssrf_guard import SsrfBlockedError
from app.services.ssrf_transport import provider_ssrf_safe_client


def _provider_ssl_verify(provider: ModelProviderRow) -> bool:
    raw_extra_config: object = provider.extra_config
    if not raw_extra_config:
        return True
    if isinstance(raw_extra_config, str):
        try:
            parsed = json.loads(raw_extra_config)
        except json.JSONDecodeError:
            return True
    elif isinstance(raw_extra_config, dict):
        parsed = raw_extra_config
    else:
        return True
    ssl_verify = parsed.get("ssl_verify")
    return True if ssl_verify is None else bool(ssl_verify)


@dataclass
class ModelTestDetail:
    model_id: str
    status: str
    display_name: str | None = None
    latency_ms: int | None = None
    error: str | None = None


@dataclass
class HealthResult:
    provider_id: str
    provider_name: str
    status: str
    latency_ms: int | None = None
    error: str | None = None
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    details: dict[str, Any] | None = None
    model_results: list[ModelTestDetail] | None = None


def _failure_message(exc: Exception) -> str:
    if isinstance(exc, SsrfBlockedError):
        return "Provider endpoint was rejected by network policy"
    if isinstance(exc, httpx.TimeoutException):
        return "Provider request timed out"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Provider returned HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return f"Provider request failed ({type(exc).__name__})"
    return f"Provider request failed ({type(exc).__name__})"


async def _resolve_auth(
    provider: ModelProviderRow,
    *,
    api_key: str | None,
    auth_resolver: Any | None,
) -> AuthResult:
    if auth_resolver is not None:
        return cast(AuthResult, await auth_resolver.resolve(provider))
    if api_key:
        return AuthResult(kind=CredentialKind.api_key, credential=api_key)
    if str(provider.auth_type) == "none":
        return AuthResult()
    raise ValueError("Configured provider credentials could not be resolved")


def _engine_headers(auth: AuthResult) -> dict[str, str]:
    if auth.kind == CredentialKind.none:
        return {}
    assert auth.credential is not None
    return {"Authorization": f"Bearer {auth.credential}"}


def _model_headers(style: ApiStyle, auth: AuthResult) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if auth.kind == CredentialKind.none:
        return headers
    assert auth.credential is not None
    if style == ApiStyle.azure_openai and auth.kind == CredentialKind.api_key:
        headers["api-key"] = auth.credential
    else:
        headers["Authorization"] = f"Bearer {auth.credential}"
    return headers


def _model_url(provider: ModelProviderRow, model_id: str) -> str:
    style = provider.api_style or ApiStyle.openai
    base = provider.base_url.rstrip("/")
    if style == ApiStyle.openai:
        return f"{base}/chat/completions"
    if not provider.api_version:
        raise ValueError("Azure OpenAI provider is missing api_version")
    deployment = quote(model_id, safe="")
    query = urlencode({"api-version": provider.api_version})
    return f"{base}/openai/deployments/{deployment}/chat/completions?{query}"


async def check_provider_health(
    provider: ModelProviderRow,
    api_key: str | None = None,
    timeout: float = 5.0,
    models: list[Any] | None = None,
    auth_resolver: Any | None = None,
) -> HealthResult:
    """Test the configured upstream without leaking its endpoint or body."""

    if provider.provider_type == ProviderType.openai_compatible and not models:
        return HealthResult(
            provider_id=provider.id,
            provider_name=provider.name,
            status="no_models",
            error="No models configured for this provider",
        )
    if provider.provider_type == ProviderType.engine_service and not provider.health_url:
        return HealthResult(
            provider_id=provider.id,
            provider_name=provider.name,
            status="no_health_url",
            error="No health URL configured for this provider",
        )

    try:
        auth = await _resolve_auth(
            provider,
            api_key=api_key,
            auth_resolver=auth_resolver,
        )
    except Exception:
        return HealthResult(
            provider_id=provider.id,
            provider_name=provider.name,
            status="unhealthy",
            error="Provider authentication could not be resolved",
        )

    if provider.provider_type == ProviderType.openai_compatible:
        return await _check_openai_compatible(provider, auth, timeout, models or [])
    return await _do_http_check(provider, provider.health_url or "", auth, timeout)


async def _check_openai_compatible(
    provider: ModelProviderRow,
    auth: AuthResult,
    timeout: float,
    models: list[Any],
) -> HealthResult:
    style = provider.api_style or ApiStyle.openai
    headers = _model_headers(style, auth)
    model_results: list[ModelTestDetail] = []
    client = provider_ssrf_safe_client(
        timeout=timeout,
        verify=_provider_ssl_verify(provider),
    )
    try:
        for model in models:
            if not model.is_enabled:
                continue
            started = time.monotonic()
            try:
                url = _model_url(provider, model.model_id)
                response = await client.post(
                    url,
                    json={
                        "model": model.model_id,
                        "messages": [{"role": "user", "content": "Respond with OK."}],
                    },
                    headers=headers,
                )
                response.raise_for_status()
                model_results.append(
                    ModelTestDetail(
                        model_id=model.model_id,
                        display_name=model.display_name,
                        status="ok",
                        latency_ms=int((time.monotonic() - started) * 1000),
                    )
                )
            except Exception as exc:
                model_results.append(
                    ModelTestDetail(
                        model_id=model.model_id,
                        display_name=model.display_name,
                        status="failed",
                        latency_ms=int((time.monotonic() - started) * 1000),
                        error=_failure_message(exc),
                    )
                )
    finally:
        await client.aclose()

    if not model_results:
        return HealthResult(
            provider_id=provider.id,
            provider_name=provider.name,
            status="no_models",
            error="No enabled models for this provider",
        )
    ok_count = sum(result.status == "ok" for result in model_results)
    return HealthResult(
        provider_id=provider.id,
        provider_name=provider.name,
        status="healthy" if ok_count == len(model_results) else "unhealthy",
        details={"ok": ok_count, "total": len(model_results)},
        model_results=model_results,
    )


async def _do_http_check(
    provider: ModelProviderRow,
    url: str,
    auth: AuthResult,
    timeout: float,
) -> HealthResult:
    started = time.monotonic()
    client = provider_ssrf_safe_client(
        timeout=timeout,
        verify=_provider_ssl_verify(provider),
    )
    try:
        response = await client.get(url, headers=_engine_headers(auth))
        response.raise_for_status()
        return HealthResult(
            provider_id=provider.id,
            provider_name=provider.name,
            status="healthy",
            latency_ms=int((time.monotonic() - started) * 1000),
            details={"http_status": response.status_code},
        )
    except Exception as exc:
        return HealthResult(
            provider_id=provider.id,
            provider_name=provider.name,
            status="unhealthy",
            latency_ms=int((time.monotonic() - started) * 1000),
            error=_failure_message(exc),
        )
    finally:
        await client.aclose()
