import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

export interface WorkflowPayloadNode {
  id: string;
  type: string;
  config: Record<string, unknown>;
  position?: { x: number; y: number };
}

export interface WorkflowPayloadConnection {
  source: string;
  target: string;
  source_port?: string;
  target_port?: string;
}

export interface WorkflowExecutionPayload {
  nodes: WorkflowPayloadNode[];
  connections: WorkflowPayloadConnection[];
}

export interface BuildWorkflowExecutionPayloadInput {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  nodeConfigs: Record<string, Record<string, unknown>>;
  uploadedFiles: Record<string, File>;
}

export interface BuildWorkflowExecutionPayloadResult {
  workflow: WorkflowExecutionPayload;
  orderedFiles: File[];
}

/**
 * Get the direct predecessor node IDs for a given node.
 * A predecessor is any node that has an edge pointing to the target.
 */
export function getDirectPredecessors(
  nodeId: string,
  edges: WorkflowEdge[]
): string[] {
  return edges
    .filter((edge) => edge.target === nodeId)
    .map((edge) => edge.source);
}

function cloneConfig(config: Record<string, unknown>): Record<string, unknown> {
  return { ...config };
}

function extractPortName(handle: string | undefined): string | undefined {
  if (!handle) return undefined;
  if (handle.startsWith("input-")) return handle.slice("input-".length);
  if (handle.startsWith("output-")) return handle.slice("output-".length);
  return undefined;
}

export function buildWorkflowExecutionPayload(
  input: BuildWorkflowExecutionPayloadInput
): BuildWorkflowExecutionPayloadResult {
  const { nodes, edges, nodeConfigs, uploadedFiles } = input;
  const orderedFiles: File[] = [];
  let fileIndex = 0;

  const workflowNodes: WorkflowPayloadNode[] = nodes.map((node) => {
    const config = cloneConfig(nodeConfigs[node.id] ?? node.data.config ?? {});
    if (node.type.startsWith("input/") && uploadedFiles[node.id]) {
      config.file = `$file_${fileIndex}`;
      orderedFiles.push(uploadedFiles[node.id]);
      fileIndex += 1;
    }

    const payloadNode: WorkflowPayloadNode = {
      id: node.id,
      type: node.type,
      config
    };
    if (node.position) {
      payloadNode.position = { x: node.position.x, y: node.position.y };
    }
    return payloadNode;
  });

  return {
    workflow: {
      nodes: workflowNodes,
      connections: edges.map((edge) => {
        const conn: WorkflowPayloadConnection = {
          source: edge.source,
          target: edge.target,
        };
        const sourcePort = extractPortName(edge.sourceHandle);
        const targetPort = extractPortName(edge.targetHandle);
        if (sourcePort) conn.source_port = sourcePort;
        if (targetPort) conn.target_port = targetPort;
        return conn;
      })
    },
    orderedFiles
  };
}
