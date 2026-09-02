"""Security projection for Pi events before they cross into a browser."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Final

_DROP_KEYS: Final = frozenset(
    {
        "apikey",
        "apikeyheader",
        "authheader",
        "token",
        "accesstoken",
        "refreshtoken",
        "bearertoken",
        "authorization",
        "authorizationheader",
        "proxyauthorization",
        "credentials",
        "credential",
        "headers",
        "cookie",
        "cookies",
        "setcookie",
        "secret",
        "secretkey",
        "clientsecret",
        "privatekey",
        "password",
        "passphrase",
        "xapikey",
        "diagnostics",
        "upstreambody",
        "responsebody",
        "rawresponse",
        "internal",
        "sessionfile",
        "extensionsource",
        "sourcepath",
    }
)
_SENSITIVE_KEY_MARKERS: Final = frozenset(
    {
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "passphrase",
        "password",
        "privatekey",
        "secret",
        "token",
    }
)
_PATH_KEYS: Final = frozenset(
    {
        "artifact",
        "cwd",
        "dest",
        "destination",
        "dir",
        "directory",
        "file",
        "filename",
        "filepath",
        "fulloutputpath",
        "output",
        "path",
        "source",
        "src",
        "target",
        "workingdirectory",
    }
)
_LIFECYCLE_EVENTS: Final = frozenset(
    {"agent_start", "agent_end", "agent_settled", "turn_start", "turn_end"}
)
_MESSAGE_EVENTS: Final = frozenset({"message_start", "message_end"})
_TOOL_EVENTS: Final = frozenset(
    {"tool_execution_start", "tool_execution_update", "tool_execution_end"}
)
_RETRY_EVENTS: Final = frozenset({"auto_retry_start", "auto_retry_end"})
_SAFE_IMAGE_MIME_TYPES: Final = frozenset(
    {"image/avif", "image/bmp", "image/gif", "image/jpeg", "image/png", "image/webp"}
)
_DROP: Final = object()


def project_event(event: dict[str, object], workspace_root: Path) -> dict[str, object] | None:
    """Return the browser-visible subset of one documented Pi session event."""

    if _contains_hidden_custom_message(event):
        return None
    event_type = event.get("type")
    if not isinstance(event_type, str):
        return None
    root = workspace_root.resolve()

    if event_type in _LIFECYCLE_EVENTS:
        return {"type": event_type}
    if event_type in _MESSAGE_EVENTS:
        return _project_message_event(event_type, event, root)
    if event_type == "message_update":
        return _project_message_update(event)
    if event_type in _TOOL_EVENTS:
        return _project_tool_event(event_type, event, root)
    if event_type == "queue_update":
        steering = event.get("steering")
        follow_up = event.get("followUp")
        if not _is_string_list(steering) or not _is_string_list(follow_up):
            return None
        return {"type": event_type, "steering": steering, "followUp": follow_up}
    if event_type == "compaction_start":
        reason = event.get("reason")
        return {"type": event_type, "reason": reason} if isinstance(reason, str) else None
    if event_type == "compaction_end":
        return _project_compaction_end(event)
    if event_type in _RETRY_EVENTS:
        return _project_retry_event(event_type, event)
    return None


def _contains_hidden_custom_message(value: object) -> bool:
    if isinstance(value, dict):
        if value.get("display") is False and (
            value.get("type") == "custom_message" or value.get("role") == "custom"
        ):
            return True
        return any(_contains_hidden_custom_message(nested) for nested in value.values())
    if isinstance(value, list):
        return any(_contains_hidden_custom_message(item) for item in value)
    return False


def _canonical_key(key: str) -> str:
    return "".join(character for character in key.casefold() if character.isalnum())


def _is_sensitive_key(key: str) -> bool:
    canonical = _canonical_key(key)
    return canonical in _DROP_KEYS or any(marker in canonical for marker in _SENSITIVE_KEY_MARKERS)


def _is_path_key(key: str) -> bool:
    canonical = _canonical_key(key)
    return canonical in _PATH_KEYS or "path" in canonical


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _project_message_event(
    event_type: str,
    event: dict[str, object],
    workspace_root: Path,
) -> dict[str, object] | None:
    message = event.get("message")
    if not isinstance(message, dict):
        return None
    projected = _project_message(message, workspace_root)
    return {"type": event_type, "message": projected} if projected is not None else None


def _project_message(
    message: dict[object, object],
    workspace_root: Path,
) -> dict[str, object] | None:
    role = message.get("role")
    content = message.get("content")
    if not isinstance(role, str) or not isinstance(content, (str, list)):
        return None

    result: dict[str, object] = {"role": role}
    string_fields = {
        "id",
        "status",
        "stopReason",
        "toolCallId",
        "toolName",
        "api",
        "provider",
        "responseModel",
    }
    for key in string_fields:
        value = message.get(key)
        if isinstance(value, str):
            result[key] = value
    for key in ("timestamp",):
        value = message.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = value
    if isinstance(message.get("isError"), bool):
        result["isError"] = message["isError"]
    if isinstance(message.get("type"), str):
        result["type"] = message["type"]
    if isinstance(message.get("display"), bool):
        result["display"] = message["display"]

    if isinstance(content, str):
        result["content"] = content
    else:
        result["content"] = [
            projected
            for block in content
            if (projected := _project_content_block(block, workspace_root)) is not None
        ]

    model = message.get("model")
    if isinstance(model, str):
        result["model"] = model
    elif isinstance(model, dict):
        visible_model = {
            key: value for key in ("id", "provider") if isinstance((value := model.get(key)), str)
        }
        if visible_model:
            result["model"] = visible_model

    usage = _project_usage(message.get("usage"))
    if usage is not None:
        result["usage"] = usage
    return result


def _project_content_block(block: object, workspace_root: Path) -> dict[str, object] | None:
    if not isinstance(block, dict):
        return None
    block_type = block.get("type")
    if block_type == "text" and isinstance(block.get("text"), str):
        return {"type": "text", "text": block["text"]}
    if block_type == "thinking" and isinstance(block.get("thinking"), str):
        result: dict[str, object] = {"type": "thinking", "thinking": block["thinking"]}
        if isinstance(block.get("redacted"), bool):
            result["redacted"] = block["redacted"]
        return result
    if block_type == "image":
        data = block.get("data")
        mime_type = block.get("mimeType")
        if (
            isinstance(data, str)
            and isinstance(mime_type, str)
            and mime_type.casefold() in _SAFE_IMAGE_MIME_TYPES
        ):
            return {"type": "image", "data": data, "mimeType": mime_type}
        return None
    if block_type == "toolCall":
        result = {"type": "toolCall"}
        for key in ("toolCallId", "toolName", "id", "name"):
            value = block.get(key)
            if isinstance(value, str):
                result[key] = value
        for key in ("input", "arguments"):
            if key in block:
                projected = _project_argument_value(block[key], workspace_root, key)
                if projected is not _DROP:
                    result[key] = projected
        return result
    return None


def _project_usage(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, object] = {}
    for key in (
        "input",
        "output",
        "cacheRead",
        "cacheWrite",
        "cacheWrite1h",
        "reasoning",
        "totalTokens",
    ):
        item = value.get(key)
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            result[key] = item
    cost = value.get("cost")
    if isinstance(cost, dict):
        visible_cost = {
            key: item
            for key in ("input", "output", "cacheRead", "cacheWrite", "total")
            if isinstance((item := cost.get(key)), (int, float)) and not isinstance(item, bool)
        }
        if visible_cost:
            result["cost"] = visible_cost
    return result or None


def _project_message_update(event: dict[str, object]) -> dict[str, object] | None:
    delta = event.get("assistantMessageEvent")
    if not isinstance(delta, dict):
        return None
    delta_type = delta.get("type")
    content_index = delta.get("contentIndex")
    text = delta.get("delta")
    if (
        delta_type not in {"text_delta", "thinking_delta", "toolcall_delta"}
        or not isinstance(content_index, int)
        or isinstance(content_index, bool)
        or not isinstance(text, str)
    ):
        return None
    return {
        "type": "message_update",
        "assistantMessageEvent": {
            "type": delta_type,
            "contentIndex": content_index,
            "delta": text,
        },
    }


def _project_tool_event(
    event_type: str,
    event: dict[str, object],
    workspace_root: Path,
) -> dict[str, object] | None:
    call_id = event.get("toolCallId")
    tool_name = event.get("toolName")
    if not isinstance(call_id, str) or not isinstance(tool_name, str):
        return None
    result: dict[str, object] = {
        "type": event_type,
        "toolCallId": call_id,
        "toolName": tool_name,
    }
    if event_type in {"tool_execution_start", "tool_execution_update"}:
        if "args" not in event:
            return None
        args = _project_argument_value(event["args"], workspace_root, "args")
        if args is _DROP:
            return None
        result["args"] = args
    if event_type == "tool_execution_update":
        payload = _project_tool_payload(event.get("partialResult"), workspace_root, tool_name)
        if payload is None:
            return None
        result["partialResult"] = payload
    if event_type == "tool_execution_end":
        payload = _project_tool_payload(event.get("result"), workspace_root, tool_name)
        is_error = event.get("isError")
        if payload is None or not isinstance(is_error, bool):
            return None
        result["result"] = payload
        result["isError"] = is_error
    return result


def _project_tool_payload(
    value: object,
    workspace_root: Path,
    tool_name: str,
) -> dict[str, object] | None:
    if not isinstance(value, dict) or not isinstance(value.get("content"), list):
        return None
    details = _project_tool_details(value.get("details"), workspace_root, tool_name)
    # PressRoom envelopes already carry a browser-safe structured result. Do
    # not also project their JSON text block: Pi needs that text in its model
    # context, but displaying and persisting it in the browser projection would
    # duplicate the structured Tool Card as a large raw JSON payload.
    content = (
        []
        if _is_pressroom_envelope(details)
        else [
            projected
            for block in value["content"]
            if (projected := _project_tool_result_block(block)) is not None
        ]
    )
    result: dict[str, object] = {"content": content}
    if details is not None:
        result["details"] = details
    return result


def _project_tool_result_block(block: object) -> dict[str, object] | None:
    if not isinstance(block, dict):
        return None
    if block.get("type") == "text" and isinstance(block.get("text"), str):
        return {"type": "text", "text": block["text"]}
    if block.get("type") == "image":
        data = block.get("data")
        mime_type = block.get("mimeType")
        if (
            isinstance(data, str)
            and isinstance(mime_type, str)
            and mime_type.casefold() in _SAFE_IMAGE_MIME_TYPES
        ):
            return {"type": "image", "data": data, "mimeType": mime_type}
    return None


def _project_tool_details(
    value: object,
    workspace_root: Path,
    tool_name: str,
) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    pressroom_envelope = _project_pressroom_envelope(value, workspace_root, tool_name)
    if pressroom_envelope is not None:
        return pressroom_envelope
    result: dict[str, object] = {}
    if isinstance(value.get("diff"), str):
        result["diff"] = value["diff"]
    limit_reached = value.get("resultLimitReached")
    if isinstance(limit_reached, (bool, int, float)):
        result["resultLimitReached"] = limit_reached
    if isinstance(value.get("linesTruncated"), bool):
        result["linesTruncated"] = value["linesTruncated"]
    full_output_path = value.get("fullOutputPath")
    if isinstance(full_output_path, str):
        projected_path = _project_path(full_output_path, workspace_root)
        if projected_path is not _DROP:
            result["fullOutputPath"] = projected_path
    truncation = value.get("truncation")
    if isinstance(truncation, dict):
        visible_truncation: dict[str, object] = {}
        for key in (
            "truncated",
            "truncatedBy",
            "totalLines",
            "outputLines",
            "totalBytes",
            "outputBytes",
            "lastLinePartial",
            "firstLineExceedsLimit",
            "maxLines",
            "maxBytes",
        ):
            item = truncation.get(key)
            if isinstance(item, (str, bool, int, float)):
                visible_truncation[key] = item
        nested_path = truncation.get("fullOutputPath")
        if isinstance(nested_path, str):
            projected_path = _project_path(nested_path, workspace_root)
            if projected_path is not _DROP:
                visible_truncation["fullOutputPath"] = projected_path
        result["truncation"] = visible_truncation
    return result or None


def _project_pressroom_envelope(
    value: dict[object, object],
    workspace_root: Path,
    tool_name: str,
) -> dict[str, object] | None:
    """Project the stable CLI envelope without trusting arbitrary extension details."""

    if (
        not tool_name.startswith("workflow_")
        or value.get("schema_version") != "pressroom-envelope.v1"
        or not isinstance(value.get("ok"), bool)
    ):
        return None
    result: dict[str, object] = {
        "schema_version": "pressroom-envelope.v1",
        "ok": value["ok"],
    }
    for key in ("data", "error"):
        if key not in value:
            continue
        projected = _project_argument_value(value[key], workspace_root, key)
        if projected is not _DROP:
            result[key] = projected
    request_id = value.get("request_id")
    if request_id is None or isinstance(request_id, str):
        result["request_id"] = request_id
    return result


def _is_pressroom_envelope(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("schema_version") == "pressroom-envelope.v1"
        and isinstance(value.get("ok"), bool)
    )


def _project_argument_value(
    value: object,
    workspace_root: Path,
    field_name: str | None = None,
) -> object:
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, nested in value.items():
            if not isinstance(key, str) or _is_sensitive_key(key):
                continue
            projected = _project_argument_value(nested, workspace_root, key)
            if projected is not _DROP:
                result[key] = projected
        return result
    if isinstance(value, list):
        return [
            item
            for nested in value
            if (item := _project_argument_value(nested, workspace_root, field_name)) is not _DROP
        ]
    if isinstance(value, str):
        if field_name is not None and _is_path_key(field_name):
            return _project_path(value, workspace_root)
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _DROP


def _project_compaction_end(event: dict[str, object]) -> dict[str, object] | None:
    reason = event.get("reason")
    aborted = event.get("aborted")
    will_retry = event.get("willRetry")
    if (
        not isinstance(reason, str)
        or not isinstance(aborted, bool)
        or not isinstance(will_retry, bool)
    ):
        return None
    result: dict[str, object] = {
        "type": "compaction_end",
        "reason": reason,
        "aborted": aborted,
        "willRetry": will_retry,
    }
    compaction = event.get("result")
    if compaction is None:
        result["result"] = None
    elif isinstance(compaction, dict):
        summary = compaction.get("summary")
        result["result"] = {"summary": summary} if isinstance(summary, str) else {}
    return result


def _project_retry_event(
    event_type: str,
    event: dict[str, object],
) -> dict[str, object] | None:
    attempt = event.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool):
        return None
    result: dict[str, object] = {"type": event_type, "attempt": attempt}
    if event_type == "auto_retry_start":
        max_attempts = event.get("maxAttempts")
        delay_ms = event.get("delayMs")
        error_message = event.get("errorMessage")
        if (
            not isinstance(max_attempts, int)
            or isinstance(max_attempts, bool)
            or not isinstance(delay_ms, (int, float))
            or isinstance(delay_ms, bool)
            or not isinstance(error_message, str)
        ):
            return None
        result.update(
            {
                "maxAttempts": max_attempts,
                "delayMs": delay_ms,
                "errorMessage": "Provider request failed",
            }
        )
    else:
        success = event.get("success")
        if not isinstance(success, bool):
            return None
        result["success"] = success
        if isinstance(event.get("finalError"), str):
            result["finalError"] = "Provider retry failed"
    return result


def _project_path(value: str, workspace_root: Path) -> object:
    # A path using another platform's absolute/drive syntax cannot be proven
    # workspace-local on this host. Likewise, shell home expansion is not a
    # workspace-relative contract, so fail closed instead of exposing it.
    windows_path = PureWindowsPath(value)
    if windows_path.drive or value == "~" or value.startswith(("~/", "~\\")):
        return _DROP
    path = Path(value)
    try:
        candidate = path.resolve() if path.is_absolute() else (workspace_root / path).resolve()
        return str(candidate.relative_to(workspace_root))
    except (OSError, RuntimeError, ValueError):
        return _DROP
