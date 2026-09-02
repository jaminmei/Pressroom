from pathlib import Path

from app.services.chatbox_projection import project_event


def test_message_update_keeps_only_delta_event(tmp_path: Path) -> None:
    result = project_event(
        {
            "type": "message_update",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "secret"}]},
            "assistantMessageEvent": {
                "type": "text_delta",
                "contentIndex": 0,
                "delta": "visible",
            },
        },
        tmp_path,
    )

    assert result == {
        "type": "message_update",
        "assistantMessageEvent": {
            "type": "text_delta",
            "contentIndex": 0,
            "delta": "visible",
        },
    }


def test_projection_strips_sensitive_message_fields_at_any_depth(tmp_path: Path) -> None:
    result = project_event(
        {
            "type": "message_end",
            "token": "secret",
            "message": {
                "id": "assistant-1",
                "role": "assistant",
                "content": [{"type": "text", "text": "safe"}],
                "authorization": "Bearer secret",
                "errorMessage": "raw provider detail",
                "rawStopReason": "provider-private",
            },
        },
        tmp_path,
    )

    assert result == {
        "type": "message_end",
        "message": {
            "id": "assistant-1",
            "role": "assistant",
            "content": [{"type": "text", "text": "safe"}],
        },
    }


def test_projection_strips_camel_case_sensitive_fields(tmp_path: Path) -> None:
    result = project_event(
        {
            "type": "tool_execution_start",
            "toolCallId": "tool-1",
            "toolName": "read",
            "args": {
                "apiKey": "secret",
                "apiKeyV2": "secret",
                "x-api-key": "secret",
                "accessToken": "secret",
                "my_token": "secret",
                "refresh_token": "secret",
                "clientSecret": "secret",
                "private-key": "secret",
                "password": "secret",
                "password_hint": "secret",
                "cookie": "secret",
                "headers": {"X-Custom-Token": "secret"},
                "sessionFile": "/host/session.json",
                "extensionSource": "/host/extension.mjs",
                "sourcePath": "/host/source.ts",
                "rawResponse": "private",
                "upstreamBody": "private",
                "text": "/usr/bin/env bash",
            },
        },
        tmp_path,
    )

    assert result == {
        "type": "tool_execution_start",
        "toolCallId": "tool-1",
        "toolName": "read",
        "args": {"text": "/usr/bin/env bash"},
    }


def test_projection_drops_hidden_custom_messages(tmp_path: Path) -> None:
    assert (
        project_event(
            {
                "type": "message_end",
                "message": {
                    "type": "custom_message",
                    "role": "custom",
                    "content": [{"type": "text", "text": "hidden"}],
                    "display": False,
                },
            },
            tmp_path,
        )
        is None
    )
    assert (
        project_event(
            {
                "type": "message_end",
                "message": {
                    "role": "custom",
                    "customType": "extension-status",
                    "content": [{"type": "text", "text": "hidden SDK message"}],
                    "display": False,
                },
            },
            tmp_path,
        )
        is None
    )


def test_tool_args_normalize_workspace_paths_and_drop_outside_artifacts(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = project_event(
        {
            "type": "tool_execution_start",
            "toolCallId": "tool-1",
            "toolName": "read",
            "args": {
                "path": str(workspace / "notes" / "plan.md"),
                "file_path": "/etc/passwd",
                "artifact": "/var/tmp/private.log",
                "text": "/usr/bin/env bash",
            },
        },
        workspace,
    )

    assert result == {
        "type": "tool_execution_start",
        "toolCallId": "tool-1",
        "toolName": "read",
        "args": {"path": "notes/plan.md", "text": "/usr/bin/env bash"},
    }


def test_projection_contains_nested_full_output_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = project_event(
        {
            "type": "tool_execution_end",
            "toolCallId": "tool-1",
            "toolName": "bash",
            "result": {
                "content": [{"type": "text", "text": "done"}],
                "details": {
                    "fullOutputPath": str(workspace / "tool-output.txt"),
                    "truncation": {
                        "truncated": True,
                        "fullOutputPath": "/var/tmp/tool-output.txt",
                    },
                },
            },
            "isError": False,
        },
        workspace,
    )

    assert result == {
        "type": "tool_execution_end",
        "toolCallId": "tool-1",
        "toolName": "bash",
        "result": {
            "content": [{"type": "text", "text": "done"}],
            "details": {
                "fullOutputPath": "tool-output.txt",
                "truncation": {"truncated": True},
            },
        },
        "isError": False,
    }


def test_projection_keeps_safe_pressroom_envelope_as_structured_details(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = project_event(
        {
            "type": "tool_execution_end",
            "toolCallId": "tool-workflow-list",
            "toolName": "workflow_list",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": '{"schema_version":"pressroom-envelope.v1","ok":true}',
                    }
                ],
                "details": {
                    "schema_version": "pressroom-envelope.v1",
                    "ok": True,
                    "data": {
                        "data": [
                            {
                                "id": "workflow-1",
                                "name": "Invoice OCR",
                                "token": "must-not-cross-projection",
                                "path": str(workspace / "exports" / "workflow.json"),
                            }
                        ],
                        "meta": {"total": 1},
                    },
                    "error": None,
                    "request_id": "request-1",
                    "authorization": "Bearer must-not-cross-projection",
                },
            },
            "isError": False,
        },
        workspace,
    )

    assert result == {
        "type": "tool_execution_end",
        "toolCallId": "tool-workflow-list",
        "toolName": "workflow_list",
        "result": {
            "content": [],
            "details": {
                "schema_version": "pressroom-envelope.v1",
                "ok": True,
                "data": {
                    "data": [
                        {
                            "id": "workflow-1",
                            "name": "Invoice OCR",
                            "path": "exports/workflow.json",
                        }
                    ],
                    "meta": {"total": 1},
                },
                "error": None,
                "request_id": "request-1",
            },
        },
        "isError": False,
    }


def test_projection_does_not_trust_pressroom_shaped_details_from_other_tools(
    tmp_path: Path,
) -> None:
    result = project_event(
        {
            "type": "tool_execution_end",
            "toolCallId": "tool-extension",
            "toolName": "untrusted_extension",
            "result": {
                "content": [{"type": "text", "text": "visible fallback"}],
                "details": {
                    "schema_version": "pressroom-envelope.v1",
                    "ok": True,
                    "data": {"private": "not projected"},
                },
            },
            "isError": False,
        },
        tmp_path,
    )

    assert result == {
        "type": "tool_execution_end",
        "toolCallId": "tool-extension",
        "toolName": "untrusted_extension",
        "result": {"content": [{"type": "text", "text": "visible fallback"}]},
        "isError": False,
    }


def test_tool_args_normalize_relative_paths_and_drop_unverifiable_paths(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = project_event(
        {
            "type": "tool_execution_start",
            "toolCallId": "tool-1",
            "toolName": "read",
            "args": {
                "path": "docs/../README.md",
                "file_path": "../../etc/passwd",
                "cwd": "~/.ssh",
                "artifact": r"\\server\share\file",
                "workingDirectory": r"C:\Users\operator\private",
                "file": "/home/operator/private.txt",
                "filename": "/home/operator/private.txt",
                "src": "/home/operator/source.txt",
                "dest": "/home/operator/destination.txt",
                "dir": "/home/operator/private-dir",
                "output": "/home/operator/output.txt",
                "target": "/home/operator/target.txt",
                "source": "/home/operator/source.txt",
                "customPathV2": "/home/operator/custom.txt",
            },
        },
        workspace,
    )

    assert result == {
        "type": "tool_execution_start",
        "toolCallId": "tool-1",
        "toolName": "read",
        "args": {"path": "README.md"},
    }


def test_projection_allows_only_safe_raster_images(tmp_path: Path) -> None:
    safe = project_event(
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"}],
            },
        },
        tmp_path,
    )
    unsafe = project_event(
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "image", "data": "PHN2Zz4=", "mimeType": "image/svg+xml"}],
            },
        },
        tmp_path,
    )

    assert safe is not None
    assert safe["message"]["content"] == [  # type: ignore[index]
        {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"}
    ]
    assert unsafe is not None
    assert unsafe["message"]["content"] == []  # type: ignore[index]


def test_lifecycle_events_strip_sdk_transcript_payloads(tmp_path: Path) -> None:
    assert project_event(
        {
            "type": "agent_end",
            "messages": [{"role": "assistant", "content": "private transcript"}],
            "willRetry": False,
        },
        tmp_path,
    ) == {"type": "agent_end"}
    assert project_event(
        {
            "type": "turn_end",
            "message": {"role": "assistant", "content": "private turn"},
            "toolResults": [{"content": "private tool output"}],
        },
        tmp_path,
    ) == {"type": "turn_end"}


def test_internal_and_unknown_sdk_events_are_dropped(tmp_path: Path) -> None:
    assert (
        project_event(
            {"type": "entry_appended", "entry": {"content": "private transcript"}}, tmp_path
        )
        is None
    )
    assert (
        project_event(
            {"type": "response", "success": False, "error": "raw provider diagnostic"},
            tmp_path,
        )
        is None
    )
    assert project_event({"type": "session_info_changed", "name": "private"}, tmp_path) is None


def test_compaction_preserves_null_result(tmp_path: Path) -> None:
    result = project_event(
        {
            "type": "compaction_end",
            "reason": "manual",
            "result": None,
            "aborted": False,
            "willRetry": False,
            "internal": "private",
        },
        tmp_path,
    )

    assert result == {
        "type": "compaction_end",
        "reason": "manual",
        "result": None,
        "aborted": False,
        "willRetry": False,
    }
