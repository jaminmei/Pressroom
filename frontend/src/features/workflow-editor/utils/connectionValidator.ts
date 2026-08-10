import type { InputPortDef, NodeRegistryNode, NodeRegistryResponse } from "@/types/node-registry";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

export type ConnectionValidationReason =
  | "unknown_node"
  | "self_loop"
  | "duplicate_edge"
  | "type_incompatible"
  | "max_inputs"
  | "max_outputs"
  | "port_max_connections";

export interface ConnectionValidationResult {
  isValid: boolean;
  isTypeCompatible: boolean;
  reason?: ConnectionValidationReason;
  warningCode?: "type_mismatch";
}

export interface ConnectionValidationInput {
  sourceNodeId: string;
  targetNodeId: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  // connection_rules kept for API backward compatibility but no longer used for validation
  registry: Pick<NodeRegistryResponse, "nodes" | "connection_rules">;
}

interface ResolvedNode {
  node: WorkflowNode;
  metadata?: NodeRegistryNode;
}

export function isMimeMatch(source: string, target: string): boolean {
  if (source === target) {
    return true;
  }

  if (target === "*/*" || source === "*/*") {
    return true;
  }

  if (source.endsWith("/*")) {
    const [sourcePrefix] = source.split("/");
    return target.startsWith(`${sourcePrefix}/`);
  }

  if (target.endsWith("/*")) {
    const [targetPrefix] = target.split("/");
    return source.startsWith(`${targetPrefix}/`);
  }

  return false;
}

export function isTypeCompatible(
  sourceOutputTypes: string[] = [],
  targetInputTypes: string[] = []
): boolean {
  if (sourceOutputTypes.length === 0 || targetInputTypes.length === 0) {
    return true;
  }

  return sourceOutputTypes.some((sourceType) =>
    targetInputTypes.some((targetType) => isMimeMatch(sourceType, targetType))
  );
}

/**
 * Check if source output types are compatible with a specific input port's accepted types.
 */
function isPortTypeCompatible(
  sourceOutputTypes: string[] = [],
  portAcceptedTypes: string[] = []
): boolean {
  if (sourceOutputTypes.length === 0 || portAcceptedTypes.length === 0) {
    return true;
  }

  return sourceOutputTypes.some((sourceType) =>
    portAcceptedTypes.some((acceptedType) => isMimeMatch(sourceType, acceptedType))
  );
}

function resolveNode(
  nodes: WorkflowNode[],
  registryNodes: NodeRegistryNode[],
  nodeId: string
): ResolvedNode | null {
  const node = nodes.find((currentNode) => currentNode.id === nodeId);
  if (!node) {
    return null;
  }

  const metadata = registryNodes.find((registryNode) => registryNode.node_type === node.type);
  return { node, metadata };
}

/**
 * Resolve the input_ports for a target node, checking both registry metadata
 * and node data (for nodes already placed on canvas).
 */
function resolveInputPorts(target: ResolvedNode): InputPortDef[] | undefined {
  return target.metadata?.input_ports ?? target.node.data.inputPorts;
}

export function validateConnection(input: ConnectionValidationInput): ConnectionValidationResult {
  const { sourceNodeId, targetNodeId, nodes, edges, registry } = input;

  if (sourceNodeId === targetNodeId) {
    return { isValid: false, isTypeCompatible: true, reason: "self_loop" };
  }

  const source = resolveNode(nodes, registry.nodes, sourceNodeId);
  const target = resolveNode(nodes, registry.nodes, targetNodeId);

  if (!source || !target) {
    return { isValid: false, isTypeCompatible: true, reason: "unknown_node" };
  }

  if (edges.some((edge) => edge.source === sourceNodeId && edge.target === targetNodeId)) {
    return { isValid: false, isTypeCompatible: true, reason: "duplicate_edge" };
  }

  const currentTargetInputs = edges.filter((edge) => edge.target === targetNodeId).length;
  const targetMaxInputs = target.metadata?.max_inputs;
  if (
    targetMaxInputs !== undefined &&
    targetMaxInputs >= 0 &&
    currentTargetInputs >= targetMaxInputs
  ) {
    return { isValid: false, isTypeCompatible: true, reason: "max_inputs" };
  }

  const currentSourceOutputs = edges.filter((edge) => edge.source === sourceNodeId).length;
  const sourceMaxOutputs = source.metadata?.max_outputs;
  if (
    sourceMaxOutputs !== undefined &&
    sourceMaxOutputs >= 0 &&
    currentSourceOutputs >= sourceMaxOutputs
  ) {
    return { isValid: false, isTypeCompatible: true, reason: "max_outputs" };
  }

  // Resolve source output types
  const sourceOutputTypes = source.metadata?.output_types ?? source.node.data.outputTypes;

  // Per-port validation if input_ports are defined
  const inputPorts = resolveInputPorts(target);
  if (inputPorts && inputPorts.length > 0) {
    // Find a compatible port
    const compatiblePort = inputPorts.find((port) =>
      isPortTypeCompatible(sourceOutputTypes, port.accepted_types)
    );

    if (!compatiblePort) {
      return {
        isValid: false,
        isTypeCompatible: false,
        reason: "type_incompatible"
      };
    }

    // Check max_connections for the compatible port
    // Count existing edges connected to this port via targetHandle
    const portHandleId = `input-${compatiblePort.name}`;
    const existingPortConnections = edges.filter(
      (edge) => edge.target === targetNodeId && edge.targetHandle === portHandleId
    ).length;

    if (
      compatiblePort.max_connections >= 0 &&
      existingPortConnections >= compatiblePort.max_connections
    ) {
      return {
        isValid: false,
        isTypeCompatible: true,
        reason: "port_max_connections"
      };
    }

    return { isValid: true, isTypeCompatible: true };
  }

  // Fallback: flat input_types validation
  const typeCompatible = isTypeCompatible(
    sourceOutputTypes,
    target.metadata?.input_types
  );
  if (!typeCompatible) {
    return {
      isValid: false,
      isTypeCompatible: false,
      reason: "type_incompatible"
    };
  }

  return { isValid: true, isTypeCompatible: true };
}
