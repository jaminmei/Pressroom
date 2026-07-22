import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  useStoreApi,
  type EdgeProps
} from "@xyflow/react";
import { Popover } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import WorkflowNodePicker from "@/features/workflow-editor/components/WorkflowNodePicker";
import {
  getCustomEdgeStyle,
  type WorkflowEdgeExecutionStatus
} from "@/features/workflow-editor/components/CustomEdge";
import { resolveInlineAddNodeOptions } from "@/features/workflow-editor/nodes/inlineAddOptions";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { useUIStore } from "@/stores/uiStore";

const workflowEdgeExecutionStatuses = new Set<WorkflowEdgeExecutionStatus>([
  "idle",
  "pending",
  "running",
  "completed",
  "failed",
  "awaiting_input",
  "skipped",
  "cancelled"
]);

function getExecutionStatus(data: unknown): WorkflowEdgeExecutionStatus {
  if (typeof data !== "object" || data === null || !("executionStatus" in data)) {
    return "idle";
  }
  const status = (data as { executionStatus?: unknown }).executionStatus;
  return typeof status === "string" && workflowEdgeExecutionStatuses.has(status as WorkflowEdgeExecutionStatus)
    ? status as WorkflowEdgeExecutionStatus
    : "idle";
}

export default function InlineAddEdge({
  id,
  source,
  target,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  data
}: EdgeProps) {
  const { t } = useTranslation("workflows");
  const [open, setOpen] = useState(false);
  const nodes = useWorkflowStore((state) => state.nodes);
  const edges = useWorkflowStore((state) => state.edges);
  const nodeRegistry = useWorkflowStore((state) => state.nodeRegistry);
  const selectNode = useWorkflowStore((state) => state.selectNode);
  const uiSelectNode = useUIStore((state) => state.selectNode);
  const reactFlowStore = useStoreApi();
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition
  });
  const isTypeWarning =
    typeof data === "object" &&
    data !== null &&
    "isTypeWarning" in data &&
    Boolean((data as { isTypeWarning?: boolean }).isTypeWarning);
  const executionStatus = getExecutionStatus(data);
  const hideAddControl =
    typeof data === "object" &&
    data !== null &&
    "hideAddControl" in data &&
    Boolean((data as { hideAddControl?: boolean }).hideAddControl);
  const activeStatusLabel = hideAddControl
    ? executionStatus === "running"
      ? t("editorText.running")
      : executionStatus === "awaiting_input"
        ? t("editorText.awaitingInput")
        : null
    : null;
  const insertableNodes = useMemo(
    () =>
      resolveInlineAddNodeOptions({
        edgeId: id,
        sourceNodeId: source,
        targetNodeId: target,
        nodes,
        edges,
        registry: nodeRegistry
      }),
    [edges, id, nodeRegistry, nodes, source, target]
  );

  const handleInsertNode = (nodeType: string) => {
    const insertedNodeId = useWorkflowStore.getState().insertNodeBetweenEdge(id, nodeType, {
      x: labelX - 100,
      y: labelY - 40
    });
    if (!insertedNodeId) {
      return;
    }

    // Force React Flow to re-measure the inserted node and its neighbors
    setTimeout(() => {
      const { domNode, updateNodeInternals: storeUpdateNodeInternals } = reactFlowStore.getState();
      const container = domNode;
      const updates = new Map<string, { id: string; nodeElement: HTMLDivElement; force: boolean }>();
      for (const nodeId of [source, target, insertedNodeId]) {
        const el = container?.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
        if (el) updates.set(nodeId, { id: nodeId, nodeElement: el as HTMLDivElement, force: true });
      }
      if (updates.size > 0) storeUpdateNodeInternals(updates, { triggerFitView: false });
    }, 50);

    selectNode(insertedNodeId);
    uiSelectNode(insertedNodeId);
    setOpen(false);
  };

  return (
    <>
      <BaseEdge
        className={`workflow-edge workflow-edge--${executionStatus}`}
        markerEnd={markerEnd}
        path={edgePath}
        style={getCustomEdgeStyle({ isTypeWarning, executionStatus })}
      />
      {activeStatusLabel || !hideAddControl ? (
        <EdgeLabelRenderer>
          {activeStatusLabel ? (
            <span
              className={`workflow-edge-status-label workflow-edge-status-label--${executionStatus}`}
              data-testid={`workflow-edge-status-${executionStatus}`}
              style={{
                left: 0,
                top: 0,
                transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`
              }}
            >
              {activeStatusLabel}
            </span>
          ) : null}
          {!hideAddControl ? (
            <Popover
              content={
                <WorkflowNodePicker
                  emptyText={t("editorText.noInsertableNodes")}
                  hint={t("editorText.insertNodeHint")}
                  nodes={insertableNodes}
                  onSelect={handleInsertNode}
                  searchPlaceholder={t("editorText.searchInsertableNodes")}
                  title={t("editorText.insertIntermediateNode")}
                />
              }
              destroyOnHidden
              open={open}
              overlayClassName="workflow-inline-edge-popover"
              placement="bottom"
              trigger={["click"]}
              onOpenChange={setOpen}
            >
              <button
                aria-label={t("editorText.insertNodeOnEdge")}
                className={`inline-add-button nodrag nopan${open ? " is-open" : ""}`}
                data-testid={`inline-add-button-${id}`}
                style={{
                  left: 0,
                  top: 0,
                  transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`
                }}
                type="button"
                onClick={(event) => event.stopPropagation()}
                onMouseDown={(event) => event.stopPropagation()}
              >
                +
              </button>
            </Popover>
          ) : null}
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}
