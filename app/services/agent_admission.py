"""Mandatory hard-rule and lightweight-LLM admission for Agent user turns."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, cast

import httpx

from app.api.internal_proxy import (
    INTERNAL_PROXY_AUTH_HEADER,
    issue_internal_proxy_grant,
    revoke_internal_proxy_grant,
)
from app.config import get_settings
from app.providers.models import ApiProtocol, ModelProviderRow

logger = logging.getLogger(__name__)

AdmissionStatus = Literal[
    "allow_platform_turn",
    "ask_for_clarification",
    "reject_out_of_scope",
    "reject_unsupported_capability",
    "reject_quota_or_rate",
]
SemanticAdmissionStatus = Literal[
    "allow_platform_turn",
    "ask_for_clarification",
    "reject_out_of_scope",
    "reject_unsupported_capability",
]

_SEMANTIC_REASON = {
    "allow_platform_turn": "platform_scope",
    "ask_for_clarification": "needs_clarification",
    "reject_out_of_scope": "not_pressroom_scope",
    "reject_unsupported_capability": "capability_not_registered",
}
_AGENT_TOOL_CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "cli" / "catalog" / "agent-tool-catalog.generated.json"
)


def _load_tool_catalog_summary() -> str:
    payload = json.loads(_AGENT_TOOL_CATALOG_PATH.read_text(encoding="utf-8"))
    tools = payload.get("tools")
    if not isinstance(tools, list) or not tools:
        raise RuntimeError("Agent admission tool catalog is unavailable")
    operations_by_domain: dict[str, list[str]] = defaultdict(list)
    for tool in tools:
        if not isinstance(tool, dict):
            raise RuntimeError("Agent admission tool catalog is invalid")
        operation = tool.get("operation")
        if not isinstance(operation, str):
            raise RuntimeError("Agent admission tool catalog is invalid")
        operations_by_domain[operation.split(".", 1)[0]].append(operation)
    lines = ["Available executable operation ids (literal catalog values):"]
    lines.extend(
        f"- {domain}: {', '.join(operations)}"
        for domain, operations in operations_by_domain.items()
    )
    lines.extend(
        [
            "The assistant may also explain these PressRoom concepts conversationally.",
            "Local-path upload/download, arbitrary shell/code, and unlisted platform operations "
            "are unavailable. Files used by workflows must already have been uploaded or selected "
            "by the user and represented by workspace file ids.",
        ]
    )
    return "\n".join(lines)


_TOOL_CATALOG_SUMMARY = _load_tool_catalog_summary()
_SYSTEM_PROMPT = """You are a low-cost admission classifier for the PressRoom workspace assistant.
Classify whether the latest user turn should reach the full agent. Do not answer the user and do
not call tools. Use recent context only to resolve references. Return exactly one JSON object with
one key named status and one of these values:
- allow_platform_turn: a PressRoom/workflow request answerable conversationally or by an
  available operation
- ask_for_clarification: plausibly PressRoom-related, but too ambiguous to determine the action
- reject_out_of_scope: unrelated to PressRoom and its workspace/workflow use
- reject_unsupported_capability: PressRoom-related but requires an unavailable operation
Simple greetings or questions asking what this assistant can do are allowed. Never infer that an
unlisted operation exists."""
_ADMISSION_MAX_TOKENS = 256


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    status: AdmissionStatus
    reason_code: str
    receipt: str | None = None

    @property
    def allowed(self) -> bool:
        return self.status == "allow_platform_turn"


@dataclass(frozen=True, slots=True)
class AdmissionReceipt:
    token: str
    session_id: str
    runtime_generation: int
    message_digest: str
    catalog_version: str
    expires_at_monotonic: float


AdmissionClassifier = Callable[..., Awaitable[SemanticAdmissionStatus]]


class AgentAdmissionService:
    """Enforce cost/protocol rules, then classify semantic scope with a bounded LLM call.

    Admission controls whether a turn reaches the Agent. Gateway catalog validation and backend
    RBAC remain authoritative for every business operation.
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        self.settings = get_settings()

    async def evaluate(
        self,
        *,
        user_id: str,
        workspace_id: str,
        session_id: str,
        runtime_generation: int,
        message: str,
        catalog_version: str,
        provider: ModelProviderRow,
        recent_messages: list[object] | None = None,
    ) -> AdmissionDecision:
        normalized = " ".join(message.strip().split())
        if not normalized:
            return AdmissionDecision("ask_for_clarification", "empty_message")
        if len(normalized.encode("utf-8")) > self.settings.agent_admission_max_message_bytes:
            return AdmissionDecision("reject_quota_or_rate", "message_too_large")
        if not self._consume_rate_slot(user_id=user_id, workspace_id=workspace_id):
            return AdmissionDecision("reject_quota_or_rate", "turn_rate_exceeded")
        if not session_id or runtime_generation < 1 or not workspace_id or not user_id:
            return AdmissionDecision(
                "reject_unsupported_capability",
                "admission_context_invalid",
            )

        classifier = cast(
            AdmissionClassifier | None,
            getattr(self.app.state, "agent_admission_classifier", None),
        )
        try:
            if classifier is not None:
                semantic_status = await classifier(
                    message=normalized,
                    recent_context=_bounded_context(recent_messages),
                    catalog_summary=_TOOL_CATALOG_SUMMARY,
                )
            else:
                semantic_status = await self._classify_with_provider(
                    provider=provider,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    message=normalized,
                    recent_context=_bounded_context(recent_messages),
                )
            if semantic_status not in _SEMANTIC_REASON:
                raise ValueError("classifier returned an unsupported status")
        except Exception as exc:
            failure_reason = _classifier_failure_reason(exc)
            logger.warning(
                "Agent admission classifier failed error_type=%s reason=%s",
                type(exc).__name__,
                failure_reason,
            )
            return AdmissionDecision(
                "reject_unsupported_capability",
                "admission_classifier_unavailable",
            )

        if semantic_status != "allow_platform_turn":
            return AdmissionDecision(semantic_status, _SEMANTIC_REASON[semantic_status])
        receipt = self._issue_receipt(
            session_id=session_id,
            runtime_generation=runtime_generation,
            message=message,
            catalog_version=catalog_version,
        )
        return AdmissionDecision("allow_platform_turn", "platform_scope", receipt.token)

    async def _classify_with_provider(
        self,
        *,
        provider: ModelProviderRow,
        workspace_id: str,
        session_id: str,
        message: str,
        recent_context: str,
    ) -> SemanticAdmissionStatus:
        if provider.model_id is None or provider.api_protocol is None:
            raise ValueError("admission provider configuration is incomplete")
        grant = issue_internal_proxy_grant(
            self.app,
            chatbox_session_id=f"{session_id}:admission",
            workspace_id=workspace_id,
            provider_id=provider.id,
        )
        user_prompt = (
            f"{_TOOL_CATALOG_SUMMARY}\n\nRecent context:\n{recent_context or '(none)'}"
            f"\n\nLatest user turn:\n{message}"
        )
        payload = _classification_payload(provider.api_protocol, user_prompt)
        url = (
            f"{self.settings.chatbox_internal_proxy_base_url.rstrip('/')}"
            f"/internal/proxy/invoke/{provider.id}"
        )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
                response = await client.post(
                    url,
                    headers={INTERNAL_PROXY_AUTH_HEADER: grant},
                    json={
                        "model_id": provider.model_id,
                        "api_protocol": provider.api_protocol.value,
                        "payload": payload,
                    },
                )
                response.raise_for_status()
                text = _assistant_text(provider.api_protocol, response.json())
        finally:
            revoke_internal_proxy_grant(self.app, grant)
        return _parse_semantic_status(text)

    def consume(
        self,
        *,
        token: str,
        session_id: str,
        runtime_generation: int,
        message: str,
        catalog_version: str,
    ) -> bool:
        receipts = self._receipts()
        receipt = receipts.pop(token, None)
        if receipt is None or receipt.expires_at_monotonic <= time.monotonic():
            return False
        return (
            receipt.session_id == session_id
            and receipt.runtime_generation == runtime_generation
            and receipt.catalog_version == catalog_version
            and secrets.compare_digest(receipt.message_digest, _message_digest(message))
        )

    def _issue_receipt(
        self,
        *,
        session_id: str,
        runtime_generation: int,
        message: str,
        catalog_version: str,
    ) -> AdmissionReceipt:
        token = secrets.token_urlsafe(24)
        receipt = AdmissionReceipt(
            token=token,
            session_id=session_id,
            runtime_generation=runtime_generation,
            message_digest=_message_digest(message),
            catalog_version=catalog_version,
            expires_at_monotonic=time.monotonic() + 30.0,
        )
        self._receipts()[token] = receipt
        return receipt

    def _receipts(self) -> dict[str, AdmissionReceipt]:
        receipts = getattr(self.app.state, "agent_admission_receipts", None)
        if receipts is None:
            receipts = {}
            self.app.state.agent_admission_receipts = receipts
        now = time.monotonic()
        for token in [key for key, value in receipts.items() if value.expires_at_monotonic <= now]:
            receipts.pop(token, None)
        return receipts

    def _consume_rate_slot(self, *, user_id: str, workspace_id: str) -> bool:
        buckets = getattr(self.app.state, "agent_admission_turn_buckets", None)
        if buckets is None:
            buckets = defaultdict(deque)
            self.app.state.agent_admission_turn_buckets = buckets
        key = (user_id, workspace_id)
        now = time.monotonic()
        bucket = buckets[key]
        while bucket and bucket[0] <= now - 60.0:
            bucket.popleft()
        if len(bucket) >= self.settings.agent_admission_turns_per_minute:
            return False
        bucket.append(now)
        return True


def _classification_payload(protocol: ApiProtocol, user_prompt: str) -> dict[str, object]:
    if protocol == ApiProtocol.openai_chat_completions:
        return {
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            # Reasoning-capable compatibility endpoints may spend part of this budget before
            # emitting the tiny JSON result. Keep the call bounded while leaving room for text.
            "max_tokens": _ADMISSION_MAX_TOKENS,
            "temperature": 0,
            "stream": False,
        }
    if protocol == ApiProtocol.openai_responses:
        return {
            "input": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": _ADMISSION_MAX_TOKENS,
            "temperature": 0,
            "stream": False,
            "store": False,
        }
    return {
        "system": _SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
        "max_tokens": _ADMISSION_MAX_TOKENS,
        "temperature": 0,
        "stream": False,
    }


def _assistant_text(protocol: ApiProtocol, payload: object) -> str:
    if not isinstance(payload, dict):
        raise ValueError("admission response is not an object")
    if protocol == ApiProtocol.openai_chat_completions:
        choices = payload.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            content_text = message.get("content") if isinstance(message, dict) else None
            if isinstance(content_text, str):
                return content_text
    elif protocol == ApiProtocol.openai_responses:
        output_text = payload.get("output_text")
        if isinstance(output_text, str):
            return output_text
        output = payload.get("output")
        if isinstance(output, list):
            texts: list[str] = []
            for item in output:
                content = item.get("content") if isinstance(item, dict) else None
                if not isinstance(content, list):
                    continue
                for part in content:
                    text = part.get("text") if isinstance(part, dict) else None
                    if isinstance(text, str):
                        texts.append(text)
            if texts:
                return "".join(texts)
    else:
        content = payload.get("content")
        if isinstance(content, list):
            texts = []
            for item in content:
                text = item.get("text") if isinstance(item, dict) else None
                if isinstance(text, str):
                    texts.append(text)
            if texts:
                return "".join(texts)
    raise ValueError("admission response has no assistant text")


def _bounded_context(messages: list[object] | None) -> str:
    if not messages:
        return ""
    lines: list[str] = []
    for raw in messages[-4:]:
        if not isinstance(raw, dict) or raw.get("role") not in {"user", "assistant"}:
            continue
        content = raw.get("content")
        if not isinstance(content, list):
            continue
        text = " ".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ).strip()
        if text:
            lines.append(f"{raw['role']}: {text[:1000]}")
    return "\n".join(lines)[-4000:]


def _strip_json_fence(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _parse_semantic_status(value: str) -> SemanticAdmissionStatus:
    """Accept one strict status object, even when a Provider wraps it in prose.

    Some OpenAI-compatible and Anthropic-compatible Providers ignore the instruction to emit
    bare JSON and add a Markdown fence or a short preamble. We keep the result fail-closed by
    requiring exactly one object whose complete schema is ``{"status": <known value>}``.
    """

    candidate = _strip_json_fence(value)
    decoder = json.JSONDecoder()
    valid_statuses: list[SemanticAdmissionStatus] = []
    for index, character in enumerate(candidate):
        if character != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict) or set(parsed) != {"status"}:
            continue
        status = parsed.get("status")
        if status in _SEMANTIC_REASON:
            valid_statuses.append(cast(SemanticAdmissionStatus, status))
    if len(valid_statuses) != 1:
        raise ValueError("admission classifier response schema is invalid")
    return valid_statuses[0]


def _classifier_failure_reason(exc: Exception) -> str:
    if isinstance(exc, ValueError):
        allowed = {
            "admission provider configuration is incomplete",
            "admission classifier response schema is invalid",
            "admission classifier status is invalid",
            "admission response is not an object",
            "admission response has no assistant text",
            "classifier returned an unsupported status",
        }
        message = str(exc)
        return message if message in allowed else "invalid_classifier_response"
    if isinstance(exc, httpx.HTTPError):
        return "provider_request_failed"
    return "classifier_failed"


def _message_digest(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


__all__ = ["AdmissionDecision", "AdmissionReceipt", "AgentAdmissionService"]
