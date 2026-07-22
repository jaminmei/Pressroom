import type { InputPortDef, NodeRegistryNode } from "@/types/node-registry";
import type { WorkflowNode } from "@/types/workflow";

export const HANDLE_ID_PRIMARY = "input-primary";
export const HANDLE_ID_CONTEXT = "input-context";

/**
 * Returns true when the node definition supports multi-input handles
 * (i.e. max_inputs === -1, meaning unlimited).
 */
export function isMultiInputNode(maxInputs: number | undefined): boolean {
  return maxInputs === -1;
}

/**
 * Resolve the input_ports for a node, checking both registry metadata
 * and node data (for nodes already placed on canvas).
 */
function resolveInputPortsFromRegistry(
  targetNode: WorkflowNode,
  registryNodes: NodeRegistryNode[]
): InputPortDef[] | undefined {
  const registryNode = registryNodes.find((rn) => rn.node_type === targetNode.type);
  return registryNode?.input_ports ?? targetNode.data.inputPorts;
}

/**
 * Determine which target handle an edge should connect to, using per-port
 * definitions when available.
 *
 * Rules:
 * - If target has input_ports: find the first port whose accepted_types matches
 *   the source output_types, return "input-{port_name}"
 * - If no port matches: fall back to input-primary
 * - If no input_ports: use legacy multi-input handle routing
 */
export function resolveTargetHandle(
  _sourceOutputTypes: string[] | undefined,
  targetMaxInputs: number | undefined,
  _targetInputPorts?: InputPortDef[]
): string | undefined {
  // Non-multi-input nodes render a single target Handle with no id,
  // so we must return undefined to avoid a handle-id mismatch.
  if (!isMultiInputNode(targetMaxInputs)) {
    return undefined;
  }

  // All connections route to the primary (left) handle.
  // The context (top) handle is hidden from the UI.
  return HANDLE_ID_PRIMARY;
}

/**
 * Resolve the target handle for an edge, looking up source/target metadata from
 * the provided nodes and registry.
 */
export function resolveTargetHandleForEdge(
  sourceNodeId: string,
  targetNodeId: string,
  nodes: WorkflowNode[],
  registryNodes: NodeRegistryNode[]
): string | undefined {
  const targetNode = nodes.find((node) => node.id === targetNodeId);
  if (!targetNode) {
    return undefined;
  }

  const targetMetadata = registryNodes.find(
    (registryNode) => registryNode.node_type === targetNode.type
  );
  const targetMaxInputs = targetMetadata?.max_inputs ?? targetNode.data.maxInputs;
  const targetInputPorts = resolveInputPortsFromRegistry(targetNode, registryNodes);

  const sourceNode = nodes.find((node) => node.id === sourceNodeId);
  if (!sourceNode) {
    return targetInputPorts && targetInputPorts.length > 0
      ? `input-${targetInputPorts[0].name}`
      : HANDLE_ID_PRIMARY;
  }

  const sourceMetadata = registryNodes.find(
    (registryNode) => registryNode.node_type === sourceNode.type
  );
  const sourceOutputTypes = sourceMetadata?.output_types ?? sourceNode.data.outputTypes;

  return resolveTargetHandle(sourceOutputTypes, targetMaxInputs, targetInputPorts);
}

/**
 * Returns a human-readable label for a handle ID.
 */
export function getHandleLabel(handleId: string | undefined): string {
  if (handleId === HANDLE_ID_CONTEXT) {
    return "Context";
  }
  if (handleId === HANDLE_ID_PRIMARY) {
    return "Primary";
  }
  // Port-based handle: "input-{portName}" -> portName
  if (handleId?.startsWith("input-")) {
    const portName = handleId.slice("input-".length);
    // Capitalize first letter
    return portName.charAt(0).toUpperCase() + portName.slice(1);
  }
  return "Primary";
}
