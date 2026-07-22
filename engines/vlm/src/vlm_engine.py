"""Request-scoped OpenAI-compatible VLM adapters."""

from __future__ import annotations

import base64
import json
import logging
import math
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from mimetypes import guess_type
from pathlib import Path
from typing import Any

import httpx
from openai import AzureOpenAI, OpenAI
from pydantic import BaseModel, create_model

from src.provider_transport import provider_http_client

logger = logging.getLogger(__name__)

_INTERNAL_METADATA_KEY = "_vlm_metadata"
_EMPTY_BEARER_HEADER = "Bearer"


class ApiStyle(str, Enum):
    openai = "openai"
    azure_openai = "azure_openai"


class CredentialKind(str, Enum):
    none = "none"
    api_key = "api_key"
    bearer = "bearer"


@dataclass(frozen=True)
class UpstreamConfig:
    base_url: str
    api_style: ApiStyle
    api_version: str | None
    ssl_verify: bool

    @classmethod
    def from_runtime_config(cls, config: dict[str, Any]) -> "UpstreamConfig":
        base_url = config.get("provider_base_url")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("VLM provider base URL is required")
        style = ApiStyle(str(config.get("provider_api_style", ApiStyle.openai.value)))
        raw_version = config.get("provider_api_version")
        api_version = raw_version.strip() if isinstance(raw_version, str) else None
        if style is ApiStyle.azure_openai and not api_version:
            raise ValueError("Azure OpenAI API version is required")
        return cls(
            base_url=base_url.rstrip("/"),
            api_style=style,
            api_version=api_version,
            ssl_verify=bool(config.get("provider_ssl_verify", True)),
        )


@dataclass(frozen=True)
class CompletionResult:
    content: str
    parsed: dict[str, Any] | None
    request_id: str | None
    usage: dict[str, Any] | None


class OpenAIAdapter:
    def __init__(
        self,
        upstream: UpstreamConfig,
        credential_kind: CredentialKind,
        credential: str | None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._upstream = upstream
        self._credential_kind = credential_kind
        self._credential = credential
        self._transport = transport

    def complete(self, kwargs: dict[str, Any]) -> CompletionResult:
        api_key = self._credential if self._credential_kind is not CredentialKind.none else ""
        http_client = provider_http_client(
            verify=self._upstream.ssl_verify,
            transport=self._transport,
        )
        if self._credential_kind is CredentialKind.none:
            http_client.event_hooks["request"].append(_strip_empty_credential_headers)
        default_headers = (
            {"Authorization": _EMPTY_BEARER_HEADER}
            if self._credential_kind is CredentialKind.none
            else None
        )
        client = OpenAI(
            base_url=self._upstream.base_url,
            api_key=api_key,
            http_client=http_client,
            default_headers=default_headers,
            _enforce_credentials=self._credential_kind is not CredentialKind.none,
        )
        try:
            return _invoke_completion(client, kwargs)
        finally:
            client.close()


class AzureOpenAIAdapter:
    def __init__(
        self,
        upstream: UpstreamConfig,
        credential_kind: CredentialKind,
        credential: str | None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._upstream = upstream
        self._credential_kind = credential_kind
        self._credential = credential
        self._transport = transport

    def complete(self, kwargs: dict[str, Any]) -> CompletionResult:
        http_client = provider_http_client(
            verify=self._upstream.ssl_verify,
            transport=self._transport,
        )
        if self._credential_kind is CredentialKind.none:
            http_client.event_hooks["request"].append(_strip_empty_credential_headers)
        client_kwargs: dict[str, Any] = {
            "azure_endpoint": self._upstream.base_url,
            "api_version": self._upstream.api_version,
            "http_client": http_client,
        }
        if self._credential_kind is CredentialKind.api_key:
            client_kwargs["api_key"] = self._credential
        elif self._credential_kind is CredentialKind.bearer:
            client_kwargs["azure_ad_token"] = self._credential
        else:
            # Explicitly suppress ambient AZURE_OPENAI_* credentials.
            client_kwargs["api_key"] = ""
            # The SDK requires an auth-shaped default even with credential
            # enforcement disabled. The request hook removes this empty bearer.
            client_kwargs["default_headers"] = {"Authorization": _EMPTY_BEARER_HEADER}
            client_kwargs["_enforce_credentials"] = False

        client = AzureOpenAI(**client_kwargs)
        try:
            return _invoke_completion(client, kwargs)
        finally:
            client.close()


def _strip_empty_credential_headers(request: httpx.Request) -> None:
    for header in ("api-key", "authorization"):
        value = request.headers.get(header)
        if value is not None and not value.strip().removeprefix("Bearer").strip():
            del request.headers[header]


def _invoke_completion(client: OpenAI | AzureOpenAI, kwargs: dict[str, Any]) -> CompletionResult:
    response_format = kwargs.get("response_format")
    if isinstance(response_format, type) and issubclass(response_format, BaseModel):
        completion = client.chat.completions.parse(**kwargs)
    else:
        completion = client.chat.completions.create(**kwargs)

    parsed: dict[str, Any] | None = None
    content = ""
    if completion.choices:
        message = completion.choices[0].message
        parsed_value = getattr(message, "parsed", None)
        if isinstance(parsed_value, BaseModel):
            parsed = parsed_value.model_dump()
        elif isinstance(parsed_value, dict):
            parsed = parsed_value
        if isinstance(message.content, str):
            content = message.content
    if parsed is None and not content:
        raise ValueError("VLM provider returned no content")

    usage_value = getattr(completion, "usage", None)
    usage = usage_value.model_dump() if isinstance(usage_value, BaseModel) else None
    request_id = getattr(completion, "_request_id", None)
    return CompletionResult(
        content=json.dumps(parsed) if parsed is not None else content,
        parsed=parsed,
        request_id=str(request_id) if request_id else None,
        usage=usage,
    )


class VLMEngine:
    """Process document images with a provider selected for each request."""

    def __init__(self, deployment_name: str = "gpt-4.1") -> None:
        self.deployment_name = deployment_name
        logger.info("VLM engine initialized")

    def process_image(
        self,
        image_path: str,
        config: dict[str, Any] | None = None,
        *,
        credential_kind: CredentialKind | str = CredentialKind.none,
        credential: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> dict[str, Any]:
        data_url = self._image_to_data_url(image_path)
        return self._process_data_url(
            data_url,
            config or {},
            credential_kind=credential_kind,
            credential=credential,
            transport=transport,
        )

    def process_base64(
        self,
        base64_data: str,
        config: dict[str, Any] | None = None,
        *,
        credential_kind: CredentialKind | str = CredentialKind.none,
        credential: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> dict[str, Any]:
        image_data = base64.b64decode(base64_data, validate=True)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as file:
            file.write(image_data)
            temp_path = file.name
        try:
            return self.process_image(
                temp_path,
                config,
                credential_kind=credential_kind,
                credential=credential,
                transport=transport,
            )
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def _process_data_url(
        self,
        data_url: str,
        config: dict[str, Any],
        *,
        credential_kind: CredentialKind | str,
        credential: str | None,
        transport: httpx.BaseTransport | None,
    ) -> dict[str, Any]:
        upstream = UpstreamConfig.from_runtime_config(config)
        kind = CredentialKind(credential_kind)
        if kind is CredentialKind.none:
            credential = None
        elif not isinstance(credential, str) or not credential:
            raise ValueError("VLM credential is required for the selected credential kind")

        model_value = config.get("model")
        model = (
            model_value.strip()
            if isinstance(model_value, str) and model_value.strip()
            else self.deployment_name
        )
        kwargs = self._build_completion_kwargs(config, model=model, image_data_url=data_url)
        adapter: OpenAIAdapter | AzureOpenAIAdapter
        if upstream.api_style is ApiStyle.openai:
            adapter = OpenAIAdapter(upstream, kind, credential, transport=transport)
        else:
            adapter = AzureOpenAIAdapter(upstream, kind, credential, transport=transport)

        started_at = time.monotonic()
        try:
            completion = adapter.complete(kwargs)
        except Exception as exc:
            logger.error(
                "VLM upstream failed model=%s adapter=%s error_type=%s",
                model,
                upstream.api_style.value,
                type(exc).__name__,
            )
            raise
        latency_ms = max(int((time.monotonic() - started_at) * 1000), 0)
        logger.info(
            "VLM upstream completed request_id=%s model=%s latency_ms=%d usage=%s",
            completion.request_id or "unknown",
            model,
            latency_ms,
            completion.usage or {},
        )

        result = completion.parsed or self._parse_response(completion.content)
        result[_INTERNAL_METADATA_KEY] = {
            "request_id": completion.request_id,
            "usage": completion.usage,
            "model": model,
            "upstream_latency_ms": latency_ms,
        }
        return result

    def _build_completion_kwargs(
        self,
        config: dict[str, Any],
        *,
        model: str,
        image_data_url: str,
    ) -> dict[str, Any]:
        custom_prompt = config.get("prompt")
        reference_text = config.get("reference_text")
        if isinstance(custom_prompt, str) and custom_prompt.strip():
            user_prompt = custom_prompt
            if isinstance(reference_text, str) and reference_text.strip():
                user_prompt = f"--- Reference Text ---\n{reference_text}\n\n{user_prompt}"
        else:
            user_prompt = (
                "Analyze this document and extract all content. Output JSON with a result key "
                "containing the full extracted text and optional structured block detail."
            )

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a helpful AI assistant with vision capabilities.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                },
            ],
        }
        response_format = self._response_format_model(config.get("response_format"))
        if response_format is not None:
            kwargs["response_format"] = response_format

        max_completion_tokens = self._safe_positive_int(config.get("max_completion_tokens"))
        max_tokens = self._safe_positive_int(config.get("max_tokens"))
        if max_completion_tokens is not None:
            kwargs["max_completion_tokens"] = max_completion_tokens
        else:
            kwargs["max_tokens"] = max_tokens or 4096

        temperature = self._safe_number(config.get("temperature"))
        inference_model = any(
            pattern in model.lower() for pattern in ("gpt-5", "o1-", "o3-", "o4-")
        )
        if temperature is not None and not inference_model:
            kwargs["temperature"] = temperature
        reasoning_effort = config.get("reasoning_effort")
        if inference_model and isinstance(reasoning_effort, str) and reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort.lower()
        return kwargs

    def _response_format_model(self, value: Any) -> type[BaseModel] | None:
        if not isinstance(value, dict) or value.get("type") != "json_schema":
            return None
        json_schema = value.get("json_schema")
        if not isinstance(json_schema, dict):
            return None
        schema = json_schema.get("schema")
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(properties, dict) or not properties:
            return None
        type_mapping: dict[str, type[Any]] = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        fields: dict[str, Any] = {}
        for name, field_schema in properties.items():
            field_type = str
            if isinstance(field_schema, dict):
                field_type = type_mapping.get(str(field_schema.get("type", "string")), str)
            fields[str(name)] = (field_type | None, None)
        return create_model(str(json_schema.get("name", "DynamicModel")), **fields)

    @staticmethod
    def _parse_response(response: str) -> dict[str, Any]:
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            return {"result": response}
        return parsed if isinstance(parsed, dict) else {"result": response}

    @staticmethod
    def _image_to_data_url(image_path: str) -> str:
        mime_type, _ = guess_type(image_path)
        mime_type = mime_type or "image/png"
        with open(image_path, "rb") as file:
            encoded = base64.b64encode(file.read()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _safe_positive_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _safe_number(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    def get_model_info(self) -> dict[str, Any]:
        return {"engine": "openai_compatible", "gpu_available": False}


__all__ = [
    "ApiStyle",
    "AzureOpenAIAdapter",
    "CompletionResult",
    "CredentialKind",
    "OpenAIAdapter",
    "UpstreamConfig",
    "VLMEngine",
]
