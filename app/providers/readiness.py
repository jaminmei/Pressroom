"""Server-side readiness probe for llm_api Providers (spec: model-readiness-test).

Runs the 6 ordered steps from design D7 against the configured upstream,
returns a structured per-step result, and never leaks the upstream response
body, tokens, or Provider diagnostics. The result is persisted as
``chatbot_ready`` on the Provider by the route handler.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from app.providers.auth import AuthResult, CredentialKind
from app.providers.models import ApiProtocol, ModelProviderRow, ProviderType
from app.services.ssrf_guard import SsrfBlockedError
from app.services.ssrf_transport import provider_ssrf_safe_client

logger = logging.getLogger(__name__)

StepStatus = Literal["pass", "fail", "skipped"]
StepName = str

READINESS_TOOL_NAME = "doc_conv_readiness_ping"
ANTHROPIC_VERSION = "2023-06-01"
_REQUIRED_STEP_NAMES = frozenset(
    {
        "non_streaming_text",
        "streaming_text",
        "tool_call",
        "tool_result",
        "store_false",
        "cancellation_settle",
    }
)


@dataclass(frozen=True)
class StepResult:
    name: StepName
    status: StepStatus
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    provider_id: str
    chatbot_ready: bool
    steps: list[StepResult] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _ReadinessToolCall:
    call_id: str
    arguments_json: str
    arguments: dict[str, Any]
    assistant_context: dict[str, Any] | list[Any]


class _ReadinessValidationError(ValueError):
    """A sanitized protocol-shape failure safe to return to an operator."""


def _provider_ssl_verify(provider: ModelProviderRow) -> bool:
    raw: object = provider.extra_config
    if not raw:
        return True
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return True
    elif isinstance(raw, dict):
        parsed = raw
    else:
        return True
    ssl_verify = parsed.get("ssl_verify")
    return True if ssl_verify is None else bool(ssl_verify)


def _sanitize_failure(exc: Exception) -> str:
    if isinstance(exc, _ReadinessValidationError):
        return str(exc)
    if isinstance(exc, SsrfBlockedError):
        return "Provider endpoint was rejected by network policy"
    if isinstance(exc, httpx.TimeoutException):
        return "Provider request timed out"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Provider returned HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return f"Provider request failed ({type(exc).__name__})"
    logger.error(
        "Unexpected readiness probe failure error_type=%s",
        type(exc).__name__,
    )
    return f"Readiness probe failed internally ({type(exc).__name__})"


def _auth_headers(protocol: ApiProtocol, auth: AuthResult) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if auth.kind == CredentialKind.none:
        return headers
    if not auth.credential:
        raise ValueError("Provider credential is missing")
    if protocol == ApiProtocol.anthropic_messages:
        headers["x-api-key"] = auth.credential
        headers["anthropic-version"] = ANTHROPIC_VERSION
    else:
        headers["Authorization"] = f"Bearer {auth.credential}"
    return headers


def _resource_url(provider: ModelProviderRow) -> str:
    base = provider.base_url.rstrip("/")
    match provider.api_protocol:
        case ApiProtocol.openai_chat_completions:
            return f"{base}/chat/completions"
        case ApiProtocol.openai_responses:
            return f"{base}/responses"
        case ApiProtocol.anthropic_messages:
            return f"{base}/messages"
        case None:
            raise ValueError("llm_api provider has no api_protocol")


def _non_streaming_body(protocol: ApiProtocol, model_id: str) -> dict[str, Any]:
    match protocol:
        case ApiProtocol.openai_chat_completions:
            return {
                "model": model_id,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "stream": False,
            }
        case ApiProtocol.openai_responses:
            return {
                "model": model_id,
                "input": "Reply with OK.",
                "stream": False,
                "store": False,
            }
        case ApiProtocol.anthropic_messages:
            return {
                "model": model_id,
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "Reply with OK."}],
            }


def _streaming_body(protocol: ApiProtocol, model_id: str) -> dict[str, Any]:
    body = _non_streaming_body(protocol, model_id)
    body["stream"] = True
    return body


def _tool_definitions(protocol: ApiProtocol) -> list[dict[str, Any]] | dict[str, Any]:
    match protocol:
        case ApiProtocol.openai_chat_completions:
            return [
                {
                    "type": "function",
                    "function": {
                        "name": READINESS_TOOL_NAME,
                        "description": "Readiness probe; returns OK.",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]
        case ApiProtocol.openai_responses:
            return [
                {
                    "type": "function",
                    "name": READINESS_TOOL_NAME,
                    "description": "Readiness probe; returns OK.",
                    "parameters": {"type": "object", "properties": {}},
                }
            ]
        case ApiProtocol.anthropic_messages:
            return [
                {
                    "name": READINESS_TOOL_NAME,
                    "description": "Readiness probe; returns OK.",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ]


def _tool_choice(protocol: ApiProtocol) -> dict[str, Any] | str:
    match protocol:
        case ApiProtocol.openai_chat_completions:
            return {"type": "function", "function": {"name": READINESS_TOOL_NAME}}
        case ApiProtocol.openai_responses:
            return {"type": "function", "name": READINESS_TOOL_NAME}
        case ApiProtocol.anthropic_messages:
            return {"type": "tool", "name": READINESS_TOOL_NAME}


def _terminal_stream_marker(protocol: ApiProtocol) -> str:
    match protocol:
        case ApiProtocol.openai_chat_completions:
            return "[DONE]"
        case ApiProtocol.openai_responses:
            return "response.completed"
        case ApiProtocol.anthropic_messages:
            return "message_stop"


def _is_terminal_stream_payload(protocol: ApiProtocol, payload: str) -> bool:
    marker = _terminal_stream_marker(protocol)
    if protocol == ApiProtocol.openai_chat_completions:
        return payload == marker
    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return False
    return isinstance(event, dict) and event.get("type") == marker


def _response_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError) as exc:
        raise _ReadinessValidationError("Provider returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise _ReadinessValidationError("Provider response must be a JSON object")
    return payload


def _content_has_text(content: object, *, block_types: frozenset[str]) -> bool:
    if isinstance(content, str):
        return bool(content.strip())
    if not isinstance(content, list):
        return False
    return any(
        isinstance(block, dict)
        and block.get("type") in block_types
        and isinstance(block.get("text"), str)
        and bool(block["text"].strip())
        for block in content
    )


def _require_assistant_text(protocol: ApiProtocol, response: httpx.Response) -> None:
    payload = _response_object(response)
    valid = False
    match protocol:
        case ApiProtocol.openai_chat_completions:
            choices = payload.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                message = first.get("message") if isinstance(first, dict) else None
                valid = (
                    isinstance(message, dict)
                    and message.get("role") == "assistant"
                    and _content_has_text(message.get("content"), block_types=frozenset({"text"}))
                )
        case ApiProtocol.openai_responses:
            output = payload.get("output")
            if isinstance(output, list):
                valid = any(
                    isinstance(item, dict)
                    and item.get("type") == "message"
                    and item.get("role") == "assistant"
                    and _content_has_text(
                        item.get("content"), block_types=frozenset({"output_text", "text"})
                    )
                    for item in output
                )
        case ApiProtocol.anthropic_messages:
            valid = (
                payload.get("type") == "message"
                and payload.get("role") == "assistant"
                and _content_has_text(payload.get("content"), block_types=frozenset({"text"}))
            )
    if not valid:
        raise _ReadinessValidationError(
            "Provider did not return a non-empty assistant text response"
        )


def _tool_arguments(raw: object) -> tuple[str, dict[str, Any]]:
    if isinstance(raw, dict):
        return json.dumps(raw, separators=(",", ":")), raw
    if not isinstance(raw, str):
        raise _ReadinessValidationError("Provider returned invalid tool-call arguments")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _ReadinessValidationError("Provider returned invalid tool-call arguments") from exc
    if not isinstance(parsed, dict):
        raise _ReadinessValidationError("Provider returned invalid tool-call arguments")
    return raw, parsed


def _require_readiness_tool_call(
    protocol: ApiProtocol,
    response: httpx.Response,
) -> _ReadinessToolCall:
    payload = _response_object(response)
    call_id: object = None
    name: object = None
    arguments: object = None
    assistant_context: dict[str, Any] | list[Any] | None = None
    match protocol:
        case ApiProtocol.openai_chat_completions:
            choices = payload.get("choices")
            first = choices[0] if isinstance(choices, list) and choices else None
            message = first.get("message") if isinstance(first, dict) else None
            calls = message.get("tool_calls") if isinstance(message, dict) else None
            call = calls[0] if isinstance(calls, list) and calls else None
            function = call.get("function") if isinstance(call, dict) else None
            call_id = call.get("id") if isinstance(call, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            arguments = function.get("arguments") if isinstance(function, dict) else None
            assistant_context = message if isinstance(message, dict) else None
        case ApiProtocol.openai_responses:
            output = payload.get("output")
            call = (
                next(
                    (
                        item
                        for item in output
                        if isinstance(item, dict) and item.get("type") == "function_call"
                    ),
                    None,
                )
                if isinstance(output, list)
                else None
            )
            call_id = call.get("call_id") if isinstance(call, dict) else None
            name = call.get("name") if isinstance(call, dict) else None
            arguments = call.get("arguments") if isinstance(call, dict) else None
            assistant_context = output if isinstance(output, list) else None
        case ApiProtocol.anthropic_messages:
            content = payload.get("content")
            call = (
                next(
                    (
                        item
                        for item in content
                        if isinstance(item, dict) and item.get("type") == "tool_use"
                    ),
                    None,
                )
                if isinstance(content, list)
                else None
            )
            call_id = call.get("id") if isinstance(call, dict) else None
            name = call.get("name") if isinstance(call, dict) else None
            arguments = call.get("input") if isinstance(call, dict) else None
            assistant_context = content if isinstance(content, list) else None
    if (
        not isinstance(call_id, str)
        or not call_id
        or name != READINESS_TOOL_NAME
        or assistant_context is None
    ):
        raise _ReadinessValidationError("Provider did not return the forced readiness tool call")
    arguments_json, arguments_object = _tool_arguments(arguments)
    return _ReadinessToolCall(
        call_id=call_id,
        arguments_json=arguments_json,
        arguments=arguments_object,
        assistant_context=assistant_context,
    )


async def _step_non_streaming(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    protocol: ApiProtocol,
    model_id: str,
) -> StepResult:
    try:
        response = await client.post(
            url, json=_non_streaming_body(protocol, model_id), headers=headers
        )
        response.raise_for_status()
        _require_assistant_text(protocol, response)
        return StepResult(name="non_streaming_text", status="pass")
    except Exception as exc:
        return StepResult(name="non_streaming_text", status="fail", detail=_sanitize_failure(exc))


async def _step_streaming(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    protocol: ApiProtocol,
    model_id: str,
) -> StepResult:
    try:
        async with client.stream(
            "POST", url, json=_streaming_body(protocol, model_id), headers=headers
        ) as response:
            response.raise_for_status()
            saw_terminal = False
            async for line in response.aiter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if _is_terminal_stream_payload(protocol, payload):
                        saw_terminal = True
                        break
        if not saw_terminal:
            return StepResult(
                name="streaming_text",
                status="fail",
                detail="Stream closed without a terminal event",
            )
        return StepResult(name="streaming_text", status="pass")
    except Exception as exc:
        return StepResult(name="streaming_text", status="fail", detail=_sanitize_failure(exc))


async def _step_tool_call(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    protocol: ApiProtocol,
    model_id: str,
) -> tuple[StepResult, _ReadinessToolCall | None]:
    body = _non_streaming_body(protocol, model_id)
    body["tools"] = _tool_definitions(protocol)
    body["tool_choice"] = _tool_choice(protocol)
    body["stream"] = False
    if protocol == ApiProtocol.anthropic_messages:
        body.pop("stream", None)
    try:
        response = await client.post(url, json=body, headers=headers)
        response.raise_for_status()
        tool_call = _require_readiness_tool_call(protocol, response)
        return StepResult(name="tool_call", status="pass"), tool_call
    except Exception as exc:
        return (
            StepResult(name="tool_call", status="fail", detail=_sanitize_failure(exc)),
            None,
        )


async def _step_tool_result(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    protocol: ApiProtocol,
    model_id: str,
    tool_call: _ReadinessToolCall,
) -> StepResult:
    match protocol:
        case ApiProtocol.openai_chat_completions:
            body: dict[str, Any] = {
                "model": model_id,
                "messages": [
                    {"role": "user", "content": "Reply with OK."},
                    tool_call.assistant_context,
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.call_id,
                        "content": "OK",
                    },
                ],
            }
        case ApiProtocol.openai_responses:
            body = {
                "model": model_id,
                "input": [
                    {"role": "user", "content": "Reply with OK."},
                    *tool_call.assistant_context,
                    {
                        "type": "function_call_output",
                        "call_id": tool_call.call_id,
                        "output": "OK",
                    },
                ],
                "store": False,
            }
        case ApiProtocol.anthropic_messages:
            body = {
                "model": model_id,
                "max_tokens": 16,
                "messages": [
                    {"role": "user", "content": "Reply with OK."},
                    {
                        "role": "assistant",
                        "content": tool_call.assistant_context,
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_call.call_id,
                                "content": "OK",
                            }
                        ],
                    },
                ],
            }
    try:
        response = await client.post(url, json=body, headers=headers)
        response.raise_for_status()
        _require_assistant_text(protocol, response)
        return StepResult(name="tool_result", status="pass")
    except Exception as exc:
        return StepResult(name="tool_result", status="fail", detail=_sanitize_failure(exc))


async def _step_store_false(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    protocol: ApiProtocol,
    model_id: str,
) -> StepResult:
    body = _non_streaming_body(protocol, model_id)
    body["store"] = False
    try:
        response = await client.post(url, json=body, headers=headers)
        response.raise_for_status()
        _require_assistant_text(protocol, response)
        return StepResult(name="store_false", status="pass")
    except Exception as exc:
        return StepResult(name="store_false", status="fail", detail=_sanitize_failure(exc))


async def _step_cancellation_settle(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    protocol: ApiProtocol,
    model_id: str,
) -> StepResult:
    response: httpx.Response | None = None
    saw_data_event = False
    try:
        async with client.stream(
            "POST", url, json=_streaming_body(protocol, model_id), headers=headers
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload and not _is_terminal_stream_payload(protocol, payload):
                    saw_data_event = True
                    break
        if not saw_data_event:
            raise _ReadinessValidationError("Cancellation probe received no streaming data event")
        if response is None or not response.is_closed:
            raise _ReadinessValidationError("Cancellation probe did not close the stream")
        # Provider-specific cancellation is exercised above. Pi's agent_settled
        # response to abort and stream failure is covered by the real runtime
        # integration suite in tests/integration/test_pi_runtime.py.
        return StepResult(
            name="cancellation_settle",
            status="pass",
            detail=(
                "Provider stream cancellation completed; "
                "Pi settlement is integration-tested separately"
            ),
        )
    except Exception as exc:
        return StepResult(
            name="cancellation_settle",
            status="fail",
            detail=_sanitize_failure(exc),
        )


async def run_readiness_probe(
    provider: ModelProviderRow,
    auth: AuthResult,
    *,
    timeout: float = 30.0,
    overall_timeout: float = 25.0,
) -> ReadinessResult:
    """Run the probe within the frontend's 30-second request deadline."""

    if provider.provider_type != ProviderType.llm_api or provider.api_protocol is None:
        return ReadinessResult(provider_id=provider.id, chatbot_ready=False, steps=[])
    if not provider.model_id:
        return ReadinessResult(
            provider_id=provider.id,
            chatbot_ready=False,
            steps=[
                StepResult(
                    name="non_streaming_text",
                    status="fail",
                    detail="Provider is missing model_id",
                )
            ],
        )

    protocol = provider.api_protocol
    url = _resource_url(provider)
    try:
        headers = _auth_headers(protocol, auth)
    except ValueError:
        return ReadinessResult(
            provider_id=provider.id,
            chatbot_ready=False,
            steps=[
                StepResult(
                    name="non_streaming_text",
                    status="fail",
                    detail="Provider credential is missing",
                )
            ],
        )
    steps: list[StepResult] = []
    try:
        return await asyncio.wait_for(
            _run_readiness_steps(
                provider.id,
                protocol,
                provider.model_id,
                url,
                headers,
                timeout,
                steps,
                verify=_provider_ssl_verify(provider),
            ),
            timeout=overall_timeout,
        )
    except TimeoutError:
        completed = {step.name for step in steps}
        timed_out_step = next(
            (
                name
                for name in (
                    "non_streaming_text",
                    "streaming_text",
                    "tool_call",
                    "tool_result",
                    "store_false",
                    "cancellation_settle",
                )
                if name not in completed
            ),
            "cancellation_settle",
        )
        steps.append(
            StepResult(
                name=timed_out_step,
                status="fail",
                detail="Readiness probe exceeded its overall timeout",
            )
        )
        return _finalize(provider.id, steps)


async def _run_readiness_steps(
    provider_id: str,
    protocol: ApiProtocol,
    model_id: str,
    url: str,
    headers: dict[str, str],
    timeout: float,
    steps: list[StepResult],
    *,
    verify: bool,
) -> ReadinessResult:
    client = provider_ssrf_safe_client(timeout=timeout, verify=verify)
    try:
        steps.append(await _step_non_streaming(client, url, headers, protocol, model_id))
        if steps[-1].status == "fail":
            return _finalize(provider_id, steps)
        streaming_step = await _step_streaming(client, url, headers, protocol, model_id)
        steps.append(streaming_step)
        if streaming_step.status == "fail":
            return _finalize(provider_id, steps)
        tool_step, tool_call = await _step_tool_call(client, url, headers, protocol, model_id)
        steps.append(tool_step)
        if steps[-1].status == "fail" or tool_call is None:
            return _finalize(provider_id, steps)
        tool_result_step = await _step_tool_result(
            client,
            url,
            headers,
            protocol,
            model_id,
            tool_call,
        )
        steps.append(tool_result_step)
        if tool_result_step.status == "fail":
            return _finalize(provider_id, steps)
        if protocol in {
            ApiProtocol.openai_chat_completions,
            ApiProtocol.openai_responses,
        }:
            store_step = await _step_store_false(
                client,
                url,
                headers,
                protocol,
                model_id,
            )
            steps.append(store_step)
            if store_step.status == "fail":
                return _finalize(provider_id, steps)
        else:
            steps.append(
                StepResult(
                    name="store_false",
                    status="skipped",
                    detail="store:false applies only to OpenAI protocols",
                )
            )
        steps.append(
            await _step_cancellation_settle(
                client,
                url,
                headers,
                protocol,
                model_id,
            )
        )
    finally:
        await client.aclose()

    return _finalize(provider_id, steps)


def _finalize(provider_id: str, steps: list[StepResult]) -> ReadinessResult:
    step_names = {step.name for step in steps}
    chatbot_ready = step_names == _REQUIRED_STEP_NAMES and all(
        step.status == "pass" or (step.name == "store_false" and step.status == "skipped")
        for step in steps
    )
    return ReadinessResult(provider_id=provider_id, chatbot_ready=chatbot_ready, steps=steps)
