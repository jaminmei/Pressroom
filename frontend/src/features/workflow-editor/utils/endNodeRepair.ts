import type { NodeRegistryNode, NodeRegistryResponse } from "@/types/node-registry";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

export const END_NODE_TYPE = "end/final";

function buildRegistryMap(
  registry: Pick<NodeRegistryResponse, "nodes" | "connection_rules">
): Map<string, NodeRegistryNode> {
  return new Map(registry.nodes.map((node) => [node.node_type, node]));
}

function withRegistryMetadata(node: WorkflowNode, registryNode?: NodeRegistryNode): WorkflowNode {
  return {
    ...node,
    data: {
      ...node.data,
      label: registryNode?.display_name ?? node.data.label,
      configSchema: registryNode?.config_schema ?? node.data.configSchema,
      inputTypes: registryNode?.input_types,
      outputTypes: registryNode?.output_types
    }
  };
}

function buildWorkflowEdgeId(source: string, target: string, edges: WorkflowEdge[]): string {
  let suffix = edges.length + 1;
  let candidate = `e-${source}-${target}-${suffix}`;
  const usedIds = new Set(edges.map((edge) => edge.id));

  while (usedIds.has(candidate)) {
    suffix += 1;
    candidate = `e-${source}-${target}-${suffix}`;
  }

  return candidate;
}

export function isEndNodeType(nodeType: string): boolean {
  return nodeType === END_NODE_TYPE;
}

export function isSystemManagedNodeType(_nodeType: string): boolean {
  return false;
}

export function resolvePreferredEditableNodeId(nodes: WorkflowNode[]): string | null {
  return (
    nodes.find((node) => node.type.startsWith("input/"))?.id ??
    nodes.find((node) => !isEndNodeType(node.type))?.id ??
    null
  );
}

/**
 * Migrate legacy output nodes: remove them and reconnect their upstream
 * engines directly to end/final. Does NOT auto-create end nodes or
 * auto-connect dangling nodes — that is the user's responsibility.
 * Validation will flag missing end nodes.
 */
export function ensureSingleEndNodeGraph(input: {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  registry: Pick<NodeRegistryResponse, "nodes" | "connection_rules">;
}): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } {
  const { registry } = input;
  const registryMap = buildRegistryMap(registry);
  const normalizedNodes = input.nodes.map((node) =>
    withRegistryMetadata(node, registryMap.get(node.type))
  );
  const normalizedEdges = input.edges.map((edge) => ({ ...edge }));

  // Migrate: remove legacy output nodes, reconnect upstream to end
  const outputNodeIds = new Set(
    normalizedNodes.filter((node) => node.type.startsWith("output/")).map((node) => node.id)
  );

  if (outputNodeIds.size === 0) {
    return { nodes: normalizedNodes, edges: normalizedEdges };
  }

  // Build upstream map for output nodes
  const upstreamOfOutput = new Map<string, string>();
  for (const edge of normalizedEdges) {
    if (outputNodeIds.has(edge.target)) {
      upstreamOfOutput.set(edge.target, edge.source);
    }
  }

  // Remove output nodes and their edges
  const filteredNodes = normalizedNodes.filter((node) => !outputNodeIds.has(node.id));
  const filteredEdges = normalizedEdges.filter(
    (edge) => !outputNodeIds.has(edge.source) && !outputNodeIds.has(edge.target)
  );

  // Find existing end node (don't create one)
  const endNodes = filteredNodes.filter((node) => isEndNodeType(node.type));
  if (endNodes.length === 0) {
    // No end node exists — just remove output nodes, validation will flag it
    return { nodes: filteredNodes, edges: filteredEdges };
  }

  const endNode = endNodes[0];

  // Reconnect upstream engines directly to end
  const alreadyConnected = new Set(
    filteredEdges.filter((edge) => edge.target === endNode.id).map((edge) => edge.source)
  );
  for (const [_outputId, upstreamId] of upstreamOfOutput) {
    if (!alreadyConnected.has(upstreamId)) {
      filteredEdges.push({
        id: buildWorkflowEdgeId(upstreamId, endNode.id, filteredEdges),
        source: upstreamId,
        target: endNode.id
      });
    }
  }

  return { nodes: filteredNodes, edges: filteredEdges };
}
