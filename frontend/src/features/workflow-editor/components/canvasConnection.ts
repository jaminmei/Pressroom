import { getCustomEdgeStyle } from "@/features/workflow-editor/components/CustomEdge";
import {
  type ConnectionValidationReason,
  validateConnection
} from "@/features/workflow-editor/utils/connectionValidator";
import { resolveTargetHandleForEdge } from "@/features/workflow-editor/utils/handleRouting";
import type { NodeRegistryResponse } from "@/types/node-registry";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";
import type { TFunction } from "i18next";

const connectionFailureMessages: Record<ConnectionValidationReason, string> = {
  self_loop: "不能連接到自身節點",
  duplicate_edge: "這兩個節點之間已存在連線",
  type_incompatible: "輸出類型與輸入類型不相容",
  max_inputs: "目標節點已達到最大輸入連線數",
  max_outputs: "來源節點已達到最大輸出連線數",
  unknown_node: "找不到對應的節點",
  port_max_connections: "目標輸入埠已達到最大連線數"
};

export function getConnectionFailureMessage(reason: ConnectionValidationReason, t?: TFunction): string {
  return t?.(`workflows:editorText.connectionFailures.${reason}`, { defaultValue: connectionFailureMessages[reason] })
    ?? connectionFailureMessages[reason]
    ?? `連線失敗（${reason}）`;
}

interface SimpleConnection {
  source: string | null;
  target: string | null;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

export interface BuildValidatedEdgeInput {
  connection: SimpleConnection;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  registry: Pick<NodeRegistryResponse, "nodes" | "connection_rules">;
}

export interface BuildValidatedEdgeResult {
  edge: WorkflowEdge | null;
  errorReason?: ConnectionValidationReason;
  warningCode?: "type_mismatch";
}

export function buildValidatedEdge(input: BuildValidatedEdgeInput): BuildValidatedEdgeResult {
  const { connection, nodes, edges, registry } = input;

  if (!connection.source || !connection.target) {
    return {
      edge: null,
      errorReason: "unknown_node"
    };
  }

  const validation = validateConnection({
    sourceNodeId: connection.source,
    targetNodeId: connection.target,
    nodes,
    edges,
    registry
  });

  if (!validation.isValid) {
    return {
      edge: null,
      errorReason: validation.reason
    };
  }

  const isTypeWarning = !validation.isTypeCompatible;
  const resolvedTargetHandle =
    connection.targetHandle ??
    resolveTargetHandleForEdge(connection.source, connection.target, nodes, registry.nodes);
  const edge: WorkflowEdge = {
    id: `e-${connection.source}-${connection.target}-${edges.length + 1}`,
    source: connection.source,
    target: connection.target,
    ...(resolvedTargetHandle ? { targetHandle: resolvedTargetHandle } : {}),
    data: {
      isTypeWarning,
      warningCode: validation.warningCode
    },
    style: getCustomEdgeStyle({ isTypeWarning })
  };

  return {
    edge,
    warningCode: validation.warningCode
  };
}
