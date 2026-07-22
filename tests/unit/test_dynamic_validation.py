"""Tests for WorkflowValidator.

Covers:
  TestValidationWarningModel: ValidationWarning Pydantic model serialization
  TestValidateDynamic: validate_dynamic() parametrized across model x edge combinations
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.models.node_registry import InputPortDef, NodeDefinition
from app.models.task import NodeState, NodeStatus, TaskContext, TaskStatus, WorkflowExecutionPlan
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.node_registry import NodeRegistryService
from app.services.task_runner import SerialTaskRunner
from app.services.topological_sort import ExecutionPlan
from app.services.workflow_validator import ValidationWarning, WorkflowValidator


class TestValidationWarningModel:
    def test_validation_warning_full_fields(self) -> None:
        warning = ValidationWarning(
            code="MODEL_NO_VISION",
            severity="warning",
            node_id="engine_1",
            message="Selected model does not support vision input",
            model="gpt-4o-mini",
        )

        data = warning.model_dump()

        assert data["code"] == "MODEL_NO_VISION"
        assert data["severity"] == "warning"
        assert data["node_id"] == "engine_1"
        assert data["message"] == "Selected model does not support vision input"
        assert data["model"] == "gpt-4o-mini"

    def test_validation_warning_defaults(self) -> None:
        warning = ValidationWarning(
            code="MODEL_NOT_SELECTED",
            severity="info",
            node_id="engine_2",
            message="No model selected for this engine node",
        )

        data = warning.model_dump()

        assert data["model"] is None

    def test_validation_warning_severity_values(self) -> None:
        warning_severity = ValidationWarning(
            code="MODEL_NO_VISION",
            severity="warning",
            node_id="n1",
            message="warning level",
        )
        info_severity = ValidationWarning(
            code="MODEL_NOT_SELECTED",
            severity="info",
            node_id="n2",
            message="info level",
        )

        assert warning_severity.severity == "warning"
        assert info_severity.severity == "info"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TEXT_ONLY_MODEL_KEY = "text-only-test-model"
_TEXT_ONLY_CAPABILITY: dict[str, object] = {
    "has_vision": False,
    "display_name": "Text-Only Test Model",
}


@pytest.fixture()
def registry() -> NodeRegistryService:
    return NodeRegistryService()


@pytest.fixture()
def validator(registry: NodeRegistryService) -> WorkflowValidator:
    return WorkflowValidator(node_registry=registry)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workflow(
    model_key: str | None,
    source_type: str = "input/image",
) -> WorkflowDefinition:
    """Build a minimal workflow: source -> engine/model -> output -> end."""
    model_config: dict[str, object] = {"model": model_key} if model_key is not None else {}
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="n1", type=source_type, config={"file": "$file_0"}),
            WorkflowNode(id="n2", type="engine/model", config=model_config),
            WorkflowNode(id="n3", type="end/final", config={}),
            WorkflowNode(id="n4", type="end/final", config={}),
        ],
        connections=[
            WorkflowConnection(source="n1", target="n2"),
            WorkflowConnection(source="n2", target="n3"),
            WorkflowConnection(source="n3", target="n4"),
        ],
    )


def _patched_get_model_capability(
    original_method: object,
) -> object:
    """Return a side_effect callable that intercepts the text-only test model."""

    def _side_effect(node_type: str, model_key: str) -> dict[str, object] | None:
        if model_key == _TEXT_ONLY_MODEL_KEY:
            return _TEXT_ONLY_CAPABILITY
        return original_method(node_type, model_key)  # type: ignore[operator]

    return _side_effect


# ---------------------------------------------------------------------------
# Group: Dynamic Validation Tests
# ---------------------------------------------------------------------------


class TestValidateDynamic:
    """Tests for WorkflowValidator.validate_dynamic() method."""

    @pytest.mark.parametrize(
        "model_key,source_type,expected_code,expected_count",
        [
            # Vision model + image input -> no warning
            ("gpt-4.1", "input/image", None, 0),
            # Vision model + text input -> no warning
            ("gpt-4.1", "input/text", None, 0),
            # Text-only model + image input -> MODEL_NO_VISION warning
            (_TEXT_ONLY_MODEL_KEY, "input/image", "MODEL_NO_VISION", 1),
            # Text-only model + text input -> no warning
            (_TEXT_ONLY_MODEL_KEY, "input/text", None, 0),
            # No model selected + image input -> MODEL_NOT_SELECTED info
            (None, "input/image", "MODEL_NOT_SELECTED", 1),
            # No model selected + text input -> no warning
            (None, "input/text", None, 0),
        ],
        ids=[
            "vision_model_image_input",
            "vision_model_text_input",
            "text_only_model_image_input",
            "text_only_model_text_input",
            "no_model_image_input",
            "no_model_text_input",
        ],
    )
    def test_validate_dynamic_parametrized(
        self,
        validator: WorkflowValidator,
        model_key: str | None,
        source_type: str,
        expected_code: str | None,
        expected_count: int,
    ) -> None:
        """Dynamic validation produces correct warnings based on model capability and edge type."""
        workflow = _make_workflow(model_key=model_key, source_type=source_type)
        original = validator._node_registry.get_model_capability

        with patch.object(
            validator._node_registry,
            "get_model_capability",
            side_effect=_patched_get_model_capability(original),
        ):
            warnings = validator.validate_dynamic(workflow)

        assert len(warnings) == expected_count
        if expected_code is not None:
            assert warnings[0].code == expected_code
            assert warnings[0].node_id == "n2"

    def test_no_warnings_for_non_model_nodes(self, validator: WorkflowValidator) -> None:
        """Dynamic validation skips nodes that are not engine/model."""
        workflow = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="n1", type="input/image", config={"file": "$file_0"}),
                WorkflowNode(id="n2", type="engine/ocr", config={}),
                WorkflowNode(id="n3", type="end/final", config={}),
                WorkflowNode(id="n4", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="n1", target="n2"),
                WorkflowConnection(source="n2", target="n3"),
                WorkflowConnection(source="n3", target="n4"),
            ],
        )
        warnings = validator.validate_dynamic(workflow)

        assert len(warnings) == 0

    def test_multiple_model_nodes_independent_warnings(self, validator: WorkflowValidator) -> None:
        """Each engine/model node is validated independently; only text-only gets warning."""
        workflow = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="n1", type="input/image", config={"file": "$file_0"}),
                WorkflowNode(
                    id="n2",
                    type="engine/model",
                    config={"model": _TEXT_ONLY_MODEL_KEY},
                ),
                WorkflowNode(
                    id="n3",
                    type="engine/model",
                    config={"model": "gpt-4.1"},
                ),
                WorkflowNode(id="n4", type="end/final", config={}),
                WorkflowNode(id="n5", type="end/final", config={}),
                WorkflowNode(id="n6", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="n1", target="n2"),
                WorkflowConnection(source="n1", target="n3"),
                WorkflowConnection(source="n2", target="n4"),
                WorkflowConnection(source="n3", target="n5"),
                WorkflowConnection(source="n4", target="n6"),
                WorkflowConnection(source="n5", target="n6"),
            ],
        )
        original = validator._node_registry.get_model_capability

        with patch.object(
            validator._node_registry,
            "get_model_capability",
            side_effect=_patched_get_model_capability(original),
        ):
            warnings = validator.validate_dynamic(workflow)

        assert len(warnings) == 1
        assert warnings[0].code == "MODEL_NO_VISION"
        assert warnings[0].node_id == "n2"

    def test_warning_severity_levels(self, validator: WorkflowValidator) -> None:
        """MODEL_NO_VISION has severity 'warning'; MODEL_NOT_SELECTED has severity 'info'."""
        wf_no_vision = _make_workflow(model_key=_TEXT_ONLY_MODEL_KEY, source_type="input/image")
        wf_no_model = _make_workflow(model_key=None, source_type="input/image")
        original = validator._node_registry.get_model_capability

        with patch.object(
            validator._node_registry,
            "get_model_capability",
            side_effect=_patched_get_model_capability(original),
        ):
            warns_no_vision = validator.validate_dynamic(wf_no_vision)

        warns_no_model = validator.validate_dynamic(wf_no_model)

        assert len(warns_no_vision) == 1
        assert warns_no_vision[0].severity == "warning"
        assert len(warns_no_model) == 1
        assert warns_no_model[0].severity == "info"

    def test_cropped_blocks_triggers_vision_check(self, validator: WorkflowValidator) -> None:
        """image/cropped_blocks from block_selector also triggers vision check."""
        # Register a temporary block_selector node definition for this test.
        block_selector_def = NodeDefinition(
            node_type="processor/block_selector",
            display_name="Block Selector",
            category="processor",
            description="User block selection from layout detection results",
            config_schema={"type": "object", "properties": {}},
            input_types=["application/x-layout-result"],
            input_ports=[
                InputPortDef(
                    name="layout",
                    accepted_types=["application/x-layout-result"],
                    required=True,
                    max_connections=1,
                ),
            ],
            output_types=["image/cropped_blocks"],
            max_inputs=1,
            max_outputs=-1,
        )
        validator._node_registry._by_type["processor/block_selector"] = block_selector_def

        workflow = WorkflowDefinition(
            nodes=[
                WorkflowNode(id="n1", type="input/image", config={"file": "$file_0"}),
                WorkflowNode(id="n2", type="processor/layout_detection", config={}),
                WorkflowNode(id="n3", type="processor/block_selector", config={}),
                WorkflowNode(
                    id="n4",
                    type="engine/model",
                    config={"model": _TEXT_ONLY_MODEL_KEY},
                ),
                WorkflowNode(id="n5", type="end/final", config={}),
                WorkflowNode(id="n6", type="end/final", config={}),
            ],
            connections=[
                WorkflowConnection(source="n1", target="n2"),
                WorkflowConnection(source="n2", target="n3"),
                WorkflowConnection(source="n3", target="n4"),
                WorkflowConnection(source="n4", target="n5"),
                WorkflowConnection(source="n5", target="n6"),
            ],
        )
        original = validator._node_registry.get_model_capability

        with patch.object(
            validator._node_registry,
            "get_model_capability",
            side_effect=_patched_get_model_capability(original),
        ):
            warnings = validator.validate_dynamic(workflow)

        assert len(warnings) == 1
        assert warnings[0].code == "MODEL_NO_VISION"


# ---------------------------------------------------------------------------
# Group: Pre-flight Validation in SerialTaskRunner
# ---------------------------------------------------------------------------


def _build_preflight_context() -> TaskContext:
    """Build a minimal TaskContext with an engine/model node for pre-flight tests."""
    workflow = _make_workflow(model_key="some-model", source_type="input/image")
    now = datetime.now(timezone.utc)
    return TaskContext(
        task_id="test-preflight-001",
        workflow=workflow,
        execution_plan=WorkflowExecutionPlan(
            total_nodes=len(workflow.nodes),
            execution_order=[["n1"], ["n2"], ["n3"], ["n4"]],
            parallel_groups=0,
        ),
        node_states={
            node.id: NodeState(node_id=node.id, node_type=node.type) for node in workflow.nodes
        },
        created_at=now,
        updated_at=now,
    )


def _build_execution_plan() -> ExecutionPlan:
    """Build a minimal ExecutionPlan matching the 4-node test workflow."""
    return ExecutionPlan(
        total_nodes=4,
        execution_order=[["n1"], ["n2"], ["n3"], ["n4"]],
        parallel_groups=0,
    )


@pytest.mark.skip(reason="Compatibility runner does not execute workflows")
class TestPreflightValidation:
    """Tests for the pre-flight dynamic validation check in SerialTaskRunner.run()."""

    @staticmethod
    def _make_execute_node_side_effect(
        context: TaskContext,
    ) -> object:
        """Return a side_effect that marks each node as COMPLETED when execute_node is called."""

        async def _side_effect(node_id: str, ctx: TaskContext) -> None:
            state = ctx.node_states[node_id]
            state.status = NodeStatus.COMPLETED
            state.output = {"mock": True}

        return _side_effect

    @pytest.mark.asyncio
    async def test_preflight_logs_on_dynamic_warning(self) -> None:
        """When validate_dynamic returns a warning, it is logged but execution proceeds."""
        mock_publisher = AsyncMock()

        runner = SerialTaskRunner(
            event_publisher=mock_publisher,
        )

        context = _build_preflight_context()
        plan = _build_execution_plan()

        blocking_warning = ValidationWarning(
            code="MODEL_NO_VISION",
            severity="warning",
            node_id="n2",
            message=(
                "Model 'Text-Only' does not support vision input, but image edges are connected."
            ),
            model="text-only-model",
        )

        with patch.object(
            WorkflowValidator,
            "validate_dynamic",
            return_value=[blocking_warning],
        ):
            await runner.run(plan, context)

        # M10: pre-flight now logs instead of blocking
        assert context.status != TaskStatus.FAILED
        assert context.error is None

    @pytest.mark.asyncio
    async def test_preflight_allows_info_only(self) -> None:
        """When validate_dynamic returns only info warnings, execution proceeds."""
        mock_publisher = AsyncMock()

        runner = SerialTaskRunner(
            event_publisher=mock_publisher,
        )

        context = _build_preflight_context()
        plan = _build_execution_plan()

        info_warning = ValidationWarning(
            code="MODEL_NOT_SELECTED",
            severity="info",
            node_id="n2",
            message="No model selected. Select a vision-capable model to process image input.",
        )

        with patch.object(
            WorkflowValidator,
            "validate_dynamic",
            return_value=[info_warning],
        ):
            # Mock execute_node with a side_effect that transitions node states
            # to avoid infinite loop in the while-remaining execution loop
            with patch.object(
                runner,
                "execute_node",
                side_effect=self._make_execute_node_side_effect(context),
            ):
                await runner.run(plan, context)

        # Pre-flight should NOT have blocked execution
        assert context.status != TaskStatus.FAILED
        assert context.error is None

    @pytest.mark.asyncio
    async def test_preflight_allows_no_warnings(self) -> None:
        """When validate_dynamic returns an empty list, execution proceeds normally."""
        mock_publisher = AsyncMock()

        runner = SerialTaskRunner(
            event_publisher=mock_publisher,
        )

        context = _build_preflight_context()
        plan = _build_execution_plan()

        with patch.object(
            WorkflowValidator,
            "validate_dynamic",
            return_value=[],
        ):
            # Mock execute_node with a side_effect that transitions node states
            # to avoid infinite loop in the while-remaining execution loop
            with patch.object(
                runner,
                "execute_node",
                side_effect=self._make_execute_node_side_effect(context),
            ):
                await runner.run(plan, context)

        # Pre-flight should NOT have blocked execution
        assert context.status != TaskStatus.FAILED
        assert context.error is None
