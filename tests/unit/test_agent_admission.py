from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.agent_admission import (
    _TOOL_CATALOG_SUMMARY,
    AgentAdmissionService,
    _parse_semantic_status,
)


def _app(status: str = "allow_platform_turn") -> SimpleNamespace:
    async def classifier(**_kwargs: object) -> str:
        return status

    return SimpleNamespace(state=SimpleNamespace(agent_admission_classifier=classifier))


def test_admission_summary_uses_the_registered_agent_tool_catalog() -> None:
    operation_lines = [line for line in _TOOL_CATALOG_SUMMARY.splitlines() if line.startswith("- ")]

    assert len(operation_lines) == 8
    assert "workflow.publish" in _TOOL_CATALOG_SUMMARY
    assert "evaluation.create" in _TOOL_CATALOG_SUMMARY
    assert "file.list" in _TOOL_CATALOG_SUMMARY
    assert "file.upload" not in _TOOL_CATALOG_SUMMARY
    assert "already have been uploaded or selected by the user" in _TOOL_CATALOG_SUMMARY


@pytest.mark.asyncio
async def test_platform_turn_receipt_is_single_use_and_message_bound() -> None:
    service = AgentAdmissionService(_app())
    decision = await service.evaluate(
        user_id="user-a",
        workspace_id="workspace-a",
        session_id="session-a",
        runtime_generation=3,
        message="Create a workflow for OCR",
        catalog_version="0.1",
        provider=SimpleNamespace(),
    )

    assert decision.allowed is True
    assert decision.receipt is not None
    assert service.consume(
        token=decision.receipt,
        session_id="session-a",
        runtime_generation=3,
        message="Create a workflow for OCR",
        catalog_version="0.1",
    )
    assert not service.consume(
        token=decision.receipt,
        session_id="session-a",
        runtime_generation=3,
        message="Create a workflow for OCR",
        catalog_version="0.1",
    )


@pytest.mark.asyncio
async def test_admission_rejects_semantic_decisions_from_classifier() -> None:
    out_of_scope_service = AgentAdmissionService(_app("reject_out_of_scope"))
    unsupported_service = AgentAdmissionService(_app("reject_unsupported_capability"))

    out_of_scope = await out_of_scope_service.evaluate(
        user_id="user-a",
        workspace_id="workspace-a",
        session_id="session-a",
        runtime_generation=1,
        message="Write a poem about the sea",
        catalog_version="0.1",
        provider=SimpleNamespace(),
    )
    unsupported = await unsupported_service.evaluate(
        user_id="user-a",
        workspace_id="workspace-a",
        session_id="session-a",
        runtime_generation=1,
        message="Delete a provider",
        catalog_version="0.1",
        provider=SimpleNamespace(),
    )

    assert out_of_scope.status == "reject_out_of_scope"
    assert unsupported.status == "reject_unsupported_capability"


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ('{"status":"allow_platform_turn"}', "allow_platform_turn"),
        (
            '```json\n{"status":"reject_out_of_scope"}\n```',
            "reject_out_of_scope",
        ),
        (
            'Classification result:\n{"status":"ask_for_clarification"}',
            "ask_for_clarification",
        ),
    ],
)
def test_parse_semantic_status_accepts_one_strict_status_object(
    response: str,
    expected: str,
) -> None:
    assert _parse_semantic_status(response) == expected


@pytest.mark.parametrize(
    "response",
    [
        "no JSON",
        '{"status":"allow_platform_turn","reason":"extra field"}',
        '{"status":"allow_platform_turn"} {"status":"reject_out_of_scope"}',
        '{"status":"unknown"}',
    ],
)
def test_parse_semantic_status_fails_closed_for_ambiguous_or_invalid_output(
    response: str,
) -> None:
    with pytest.raises(ValueError, match="response schema is invalid"):
        _parse_semantic_status(response)
