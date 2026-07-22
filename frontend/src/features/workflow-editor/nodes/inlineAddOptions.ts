import { validateConnection } from "@/features/workflow-editor/utils/connectionValidator";
import type { NodeRegistryNode, NodeRegistryResponse } from "@/types/node-registry";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

interface ResolveInlineAddNodeOptionsInput {
  edgeId: string;
  sourceNodeId: string;
  targetNodeId: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  registry: Pick<NodeRegistryResponse, "nodes" | "connection_rules">;
}

function sortByDisplayName(a: NodeRegistryNode, b: NodeRegistryNode): number {
  if (a.display_name === b.display_name) {
    return a.node_type.localeCompare(b.node_type);
  }

  return a.display_name.localeCompare(b.display_name);
}

function buildCandidateNode(node: NodeRegistryNode, id: string): WorkflowNode {
  return {
    id,
    type: node.node_type,
    data: {
      label: node.display_name,
      config: {},
      configSchema: node.config_schema,
      inputTypes: node.input_types,
      outputTypes: node.output_types
    }
  };
}

export function resolveInlineAddNodeOptions({
  edgeId,
  sourceNodeId,
  targetNodeId,
  nodes,
  edges,
  registry
}: ResolveInlineAddNodeOptionsInput): NodeRegistryNode[] {
  const remainingEdges = edges.filter((edge) => edge.id !== edgeId);

  return registry.nodes
    .filter((candidate, index) => {
      const candidateId = `__inline_add_candidate_${candidate.node_type.replace(/[\\/]/g, "_")}_${index}`;
      const candidateNode = buildCandidateNode(candidate, candidateId);
      const candidateNodes = [...nodes, candidateNode];

      const incomingValidation = validateConnection({
        sourceNodeId,
        targetNodeId: candidateId,
        nodes: candidateNodes,
        edges: remainingEdges,
        registry
      });
      if (!incomingValidation.isValid) {
        return false;
      }

      const outgoingValidation = validateConnection({
        sourceNodeId: candidateId,
        targetNodeId,
        nodes: candidateNodes,
        edges: [
          ...remainingEdges,
          {
            id: `__inline_add_edge_${index}`,
            source: sourceNodeId,
            target: candidateId
          }
        ],
        registry
      });

      return outgoingValidation.isValid;
    })
    .sort(sortByDisplayName);
}
