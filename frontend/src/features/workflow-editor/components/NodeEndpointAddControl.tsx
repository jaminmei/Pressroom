import { Popover, message } from "antd";
import { Handle, Position, useStoreApi } from "@xyflow/react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { buildValidatedEdge } from "@/features/workflow-editor/components/canvasConnection";
import WorkflowNodePicker from "@/features/workflow-editor/components/WorkflowNodePicker";
import {
  buildEndpointConnection,
  resolveCompatibleNodeOptions,
  resolveEndpointNodePosition,
  type EndpointAddDirection
} from "@/features/workflow-editor/nodes/endpointAddOptions";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { useUIStore } from "@/stores/uiStore";

interface NodeEndpointAddControlProps {
  nodeId: string;
  nodeType?: string;
  direction: EndpointAddDirection;
  isConnectable?: boolean;
  handleId?: string;
}

export default function NodeEndpointAddControl({
  nodeId,
  nodeType,
  direction,
  isConnectable,
  handleId
}: NodeEndpointAddControlProps) {
  const { t } = useTranslation("workflows");
  const [open, setOpen] = useState(false);
  const nodeRegistry = useWorkflowStore((state) => state.nodeRegistry);
  const uiSelectNode = useUIStore((state) => state.selectNode);
  const reactFlowStore = useStoreApi();

  const compatibleNodes = useMemo(() => {
    if (!nodeType) {
      return [];
    }

    return resolveCompatibleNodeOptions({
      anchorNodeType: nodeType,
      direction,
      registry: nodeRegistry
    });
  }, [direction, nodeRegistry, nodeType]);

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
  };

  const handleCreateConnectedNode = (nextNodeType: string) => {
    const currentState = useWorkflowStore.getState();
    const anchorNode = currentState.nodes.find((node) => node.id === nodeId);
    if (!anchorNode) {
      return;
    }

    const siblingCount =
      direction === "downstream"
        ? currentState.edges.filter((edge) => edge.source === nodeId).length
        : currentState.edges.filter((edge) => edge.target === nodeId).length;

    const nodePosition = resolveEndpointNodePosition(anchorNode.position, direction, siblingCount);
    const createdNodeId = currentState.addNode(nextNodeType, nodePosition);

    const latestState = useWorkflowStore.getState();
    const connection = buildEndpointConnection(nodeId, createdNodeId, direction);
    const validationResult = buildValidatedEdge({
      connection,
      nodes: latestState.nodes,
      edges: latestState.edges,
      registry: latestState.nodeRegistry
    });

    if (!validationResult.edge) {
      latestState.removeNode(createdNodeId);
      message.warning(t("editorText.connectionRejected", { reason: validationResult.errorReason ?? "unknown" }));
      return;
    }

    // Add the edge synchronously — the hardcoded `measured` property on
    // nodes (in Canvas.tsx mapToReactFlowNode) ensures handleBounds are
    // preserved through adoptUserNodes slow-path reprocessing.
    latestState.addEdge(validationResult.edge);
    if (validationResult.warningCode === "type_mismatch") {
      message.warning(t("editorText.typeWarningConnection"));
    }

    // Force React Flow to re-measure both nodes after DOM renders,
    // ensuring edge path coordinates are computed correctly.
    setTimeout(() => {
      const { domNode, updateNodeInternals: storeUpdateNodeInternals } = reactFlowStore.getState();
      const container = domNode;
      const sourceEl = container?.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
      const targetEl = container?.querySelector(`.react-flow__node[data-id="${createdNodeId}"]`);
      if (sourceEl && targetEl) {
        const updates = new Map([
          [nodeId, { id: nodeId, nodeElement: sourceEl as HTMLDivElement, force: true }],
          [createdNodeId, { id: createdNodeId, nodeElement: targetEl as HTMLDivElement, force: true }]
        ]);
        storeUpdateNodeInternals(updates, { triggerFitView: false });
      }
    }, 100);

    latestState.selectNode(createdNodeId);
    uiSelectNode(createdNodeId);

    setOpen(false);
  };

  const menuContent = (
    <WorkflowNodePicker
      hint={direction === "downstream" ? t("editorText.addDownstreamHint") : t("editorText.addUpstreamHint")}
      nodes={compatibleNodes}
      onSelect={handleCreateConnectedNode}
      searchPlaceholder={direction === "downstream" ? t("editorText.searchDownstream") : t("editorText.searchUpstream")}
      title={direction === "downstream" ? t("editorText.addDownstream") : t("editorText.addUpstream")}
    />
  );

  return (
    <Popover
      content={menuContent}
      destroyOnHidden
      open={open}
      overlayClassName="workflow-node-endpoint-popover"
      placement={direction === "downstream" ? "rightTop" : "leftTop"}
      trigger={["click"]}
      onOpenChange={handleOpenChange}
    >
      <Handle
        aria-label={direction === "downstream" ? t("editorText.addDownstream") : t("editorText.addUpstream")}
        className={`workflow-node-endpoint-handle workflow-node-endpoint-handle-${direction}${open ? " is-open" : ""} nodrag nopan`}
        data-testid={`workflow-node-endpoint-handle-${direction}`}
        id={handleId}
        isConnectable={isConnectable}
        position={direction === "downstream" ? Position.Right : Position.Left}
        role="button"
        title={t("editorText.endpointHint")}
        type={direction === "downstream" ? "source" : "target"}
        onClick={(event) => event.stopPropagation()}
      />
    </Popover>
  );
}
