"""HTTP client for communicating with engine containers.

Provides :class:`EngineClient` that resolves node types to container URLs,
sends ``POST /process`` requests with retry logic, and returns
:class:`~app.models.execution.NodeOutput`.

Also exposes :func:`make_node_executor` which wraps an ``EngineClient`` as
a :class:`~app.services.dag_scheduler.NodeExecutor`-compatible callable.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

import httpx

from app.config import Settings
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import EngineError
from app.models.execution import NodeOutput
from app.providers.auth import AuthResult, CredentialKind
from app.services.dag_scheduler import DAGNode, NodeExecutor
from app.services.ssrf_guard import SsrfBlockedError
from app.services.ssrf_transport import provider_ssrf_safe_client

logger = logging.getLogger(__name__)

INTERNAL_CREDENTIAL_KIND_HEADER = "X-DocConv-Credential-Kind"
INTERNAL_CREDENTIAL_HEADER = "X-DocConv-Credential"

_UPSTREAM_CONFIG_KEYS = {
    "provider_base_url",
    "provider_api_style",
    "provider_api_version",
    "provider_ssl_verify",
    "provider_fixed_config",
}

# Node type prefix -> Settings attribute mapping
_NODE_TYPE_TO_URL_KEY: dict[str, str] = {
    "engine/ocr": "ocr_engine_url",
    "engine/model": "vlm_engine_url",
    "engine/text": "text_engine_url",
    "engine/markitdown": "markitdown_engine_url",
    "engine/docling": "docling_engine_url",
    "processor/layout_detection": "layout_detection_engine_url",
    "processor/image_enhance": "image_enhancement_engine_url",
    "processor/rotate": "image_rotation_engine_url",
}


def _normalize_input_ports(inputs: dict[str, Any]) -> dict[str, Any]:
    """Ensure single-input payloads are reachable under common port names."""
    if len(inputs) == 1:
        sole_value = next(iter(inputs.values()))
        for alias in ("image", "images"):
            inputs.setdefault(alias, sole_value)
    return inputs


def _inline_binary_refs(output_dict: dict[str, Any]) -> dict[str, Any]:
    """Inline local file refs as base64 into text field for engines without shared filesystems.

    Keeps the original binary ref intact so engines with shared filesystems
    can still use the file path directly. Engines without access will fall
    back to the base64 data in the text field.
    """
    binary_list = output_dict.get("binary")
    if not binary_list:
        return output_dict
    for item in binary_list:
        ref = item.get("ref", "")
        if os.path.isfile(ref):
            with open(ref, "rb") as f:
                output_dict["text"] = base64.b64encode(f.read()).decode("ascii")
            metadata = output_dict.setdefault("metadata", {})
            ext = os.path.splitext(ref)[1]
            if ext:
                metadata.setdefault("file_extension", ext)
            mime = item.get("mime_type")
            if mime:
                metadata.setdefault("mime_type", mime)
            break
    return output_dict


class EngineClient:
    """Async HTTP client that talks to engine/processor containers.

    Parameters
    ----------
    settings:
        Optional pre-built :class:`app.config.Settings` instance.
        If *None*, settings are lazily imported on first use.
    timeout:
        HTTP request timeout in seconds (default 120).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._settings = settings
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._insecure_client: httpx.AsyncClient | None = None
        self._provider_clients: dict[bool, httpx.AsyncClient] = {}

    # -- lifecycle ---------------------------------------------------------------

    async def _get_client(self, verify: bool = True) -> httpx.AsyncClient:
        """Return the shared ``httpx.AsyncClient``, creating it on first call."""
        if verify:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=self._timeout)
            return self._client
        if self._insecure_client is None:
            self._insecure_client = httpx.AsyncClient(timeout=self._timeout, verify=False)
        return self._insecure_client

    async def _get_provider_client(self, verify: bool = True) -> httpx.AsyncClient:
        client = self._provider_clients.get(verify)
        if client is None:
            client = provider_ssrf_safe_client(
                settings=self._settings,
                timeout=self._timeout,
                verify=verify,
            )
            self._provider_clients[verify] = client
        return client

    async def close(self) -> None:
        """Gracefully close the underlying HTTP clients."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._insecure_client is not None:
            await self._insecure_client.aclose()
            self._insecure_client = None
        for client in self._provider_clients.values():
            await client.aclose()
        self._provider_clients.clear()

    # -- URL resolution ----------------------------------------------------------

    def _resolve_url(self, node_type: str) -> str:
        """Resolve engine container URL from a node type string."""
        url_key = _NODE_TYPE_TO_URL_KEY.get(node_type)
        if url_key is None:
            raise ValueError(f"Unknown node type: {node_type}")
        if self._settings is None:
            self._settings = Settings()
        return str(getattr(self._settings, url_key))

    # -- core API ---------------------------------------------------------------

    async def process(
        self,
        node_type: str,
        inputs: dict[str, NodeOutput],
        config: dict[str, Any],
        headers: dict[str, str] | None = None,
        base_url: str | None = None,
        verify: bool = True,
        provider_request: bool = False,
    ) -> NodeOutput:
        """Send ``POST /process`` to the engine container.

        When *base_url* is provided, it overrides settings-based URL
        resolution (used for per-request provider routing).
        """
        url = base_url if base_url is not None else self._resolve_url(node_type)
        endpoint = f"{url.rstrip('/')}/process"

        body: dict[str, Any] = {
            "inputs": _normalize_input_ports(
                {
                    port: _inline_binary_refs(output.model_dump(mode="json"))
                    for port, output in inputs.items()
                }
            ),
            "config": config,
        }

        try:
            client = (
                await self._get_provider_client(verify=verify)
                if provider_request
                else await self._get_client(verify=verify)
            )
            response = await client.post(endpoint, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
            return NodeOutput.model_validate(data)
        except httpx.HTTPStatusError as exc:
            raise EngineError(
                ErrorCode.ENGINE_INVALID_RESPONSE,
                f"Engine {node_type} returned HTTP {exc.response.status_code}",
                engine_name=node_type,
            ) from exc
        except httpx.TimeoutException as exc:
            raise EngineError(
                ErrorCode.ENGINE_TIMEOUT,
                f"Engine {node_type} timed out",
                engine_name=node_type,
            ) from exc
        except httpx.RequestError as exc:
            raise EngineError(
                ErrorCode.ENGINE_UNREACHABLE,
                f"Engine {node_type} is unreachable",
                engine_name=node_type,
            ) from exc
        except SsrfBlockedError as exc:
            raise EngineError(
                ErrorCode.ENGINE_UNREACHABLE,
                f"Engine {node_type} provider address is blocked",
                engine_name=node_type,
            ) from exc


# ---------------------------------------------------------------------------
# NodeExecutor factory
# ---------------------------------------------------------------------------


def _provider_extra_config(provider: Any) -> dict[str, Any]:
    import json

    raw = getattr(provider, "extra_config", None)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return dict(parsed)


def _resolve_ssl_verify(provider: Any) -> bool:
    """Read ssl_verify from provider.extra_config (JSON string in SQLite row)."""
    parsed = _provider_extra_config(provider)
    return bool(parsed.get("ssl_verify", True))


def _resolve_fixed_config(provider: Any) -> dict[str, Any]:
    fixed_config = _provider_extra_config(provider).get("fixed_config")
    return dict(fixed_config) if isinstance(fixed_config, dict) else {}


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _runtime_node_config(node: DAGNode) -> dict[str, Any]:
    return {
        key: value
        for key, value in node.config.items()
        if key != "provider_id" and key not in _UPSTREAM_CONFIG_KEYS
    }


def _engine_service_headers(auth_result: AuthResult) -> dict[str, str] | None:
    if auth_result.kind is CredentialKind.none:
        return None
    assert auth_result.credential is not None
    return {"Authorization": f"Bearer {auth_result.credential}"}


def _vlm_internal_headers(auth_result: AuthResult) -> dict[str, str]:
    headers = {INTERNAL_CREDENTIAL_KIND_HEADER: auth_result.kind.value}
    if auth_result.credential is not None:
        headers[INTERNAL_CREDENTIAL_HEADER] = auth_result.credential
    return headers


def make_node_executor(
    engine_client: EngineClient,
    auth_resolver: Any = None,
    provider_resolver: Any = None,
) -> NodeExecutor:
    """Create a :class:`NodeExecutor`-compatible callable from an ``EngineClient``.

    The returned coroutine function matches the
    :class:`~app.services.dag_scheduler.NodeExecutor` protocol signature::

        async def executor(node: DAGNode, inputs: dict[str, NodeOutput]) -> NodeOutput
    """

    async def executor(
        node: DAGNode,
        inputs: dict[str, NodeOutput],
    ) -> NodeOutput:
        provider = None
        auth_result = AuthResult()

        provider_id = node.config.get("provider_id")
        if isinstance(provider_id, str) and provider_id:
            if provider_resolver is None:
                raise EngineError(
                    ErrorCode.PROVIDER_NOT_FOUND,
                    f"Provider {provider_id} is unavailable in this workspace",
                    engine_name=node.node_type,
                )
            try:
                provider = provider_resolver(provider_id)
            except Exception as exc:
                raise EngineError(
                    ErrorCode.PROVIDER_NOT_FOUND,
                    f"Provider {provider_id} lookup failed",
                    engine_name=node.node_type,
                ) from exc

            if provider is None or not provider.is_enabled:
                raise EngineError(
                    ErrorCode.PROVIDER_NOT_FOUND,
                    f"Provider {provider_id} is unavailable in this workspace",
                    engine_name=node.node_type,
                )
            if auth_resolver is None:
                if _enum_value(provider.auth_type) != "none":
                    raise EngineError(
                        ErrorCode.AUTH_INVALID_CREDENTIALS,
                        f"Provider {provider_id} authentication is unavailable",
                        engine_name=node.node_type,
                    )
            else:
                try:
                    auth_result = await auth_resolver.resolve(provider)
                except Exception as exc:
                    raise EngineError(
                        ErrorCode.AUTH_INVALID_CREDENTIALS,
                        f"Provider {provider_id} authentication failed",
                        engine_name=node.node_type,
                    ) from exc

        merged_config = _runtime_node_config(node)
        if provider is None:
            return await engine_client.process(
                node_type=node.node_type,
                inputs=inputs,
                config=merged_config,
            )

        provider_type = _enum_value(provider.provider_type)
        if provider_type == "engine_service":
            merged_config.update(_resolve_fixed_config(provider))
            return await engine_client.process(
                node_type=node.node_type,
                inputs=inputs,
                config=merged_config,
                headers=_engine_service_headers(auth_result),
                base_url=provider.base_url,
                verify=_resolve_ssl_verify(provider),
                provider_request=True,
            )

        if provider_type != "openai_compatible":
            raise EngineError(
                ErrorCode.INVALID_NODE_CONFIG,
                f"Provider {provider.id} has an unsupported provider type",
                engine_name=node.node_type,
            )

        api_style = getattr(provider, "api_style", None)
        merged_config.update(
            {
                "provider_base_url": provider.base_url,
                "provider_api_style": _enum_value(api_style) if api_style is not None else "openai",
                "provider_api_version": getattr(provider, "api_version", None),
                "provider_ssl_verify": _resolve_ssl_verify(provider),
            }
        )

        return await engine_client.process(
            node_type=node.node_type,
            inputs=inputs,
            config=merged_config,
            headers=_vlm_internal_headers(auth_result),
        )

    return executor
