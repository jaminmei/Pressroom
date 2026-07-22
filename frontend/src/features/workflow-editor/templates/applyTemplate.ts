import type { WorkflowTemplate } from "@/features/workflow-editor/templates/types";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { ENGINE_CATEGORY_MAP } from "@/features/workflow-editor/components/EngineConfigPanel";
import { getDefaultProvider } from "@/services/providerApi";
import { getProviderParamDefaults } from "@/features/workflow-editor/utils/providerDefaults";
import {
  ensureSingleEndNodeGraph,
  resolvePreferredEditableNodeId
} from "@/features/workflow-editor/utils/endNodeRepair";
import { resolveTargetHandleForEdge } from "@/features/workflow-editor/utils/handleRouting";
import type { NodeRegistryNode } from "@/types/node-registry";
import type { NodeConfigSchema } from "@/types/node-registry";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

function cloneConfig(config: Record<string, unknown>): Record<string, unknown> {
  return { ...config };
}

function fallbackConfigSchema(nodeType: string): NodeConfigSchema {
  if (nodeType.startsWith("input/")) {
    return {
      type: "object" as const,
      properties: {
        file: {
          type: "file" as const
        }
      },
      required: ["file"]
    };
  }

  return { type: "object" as const, properties: {} };
}

function toWorkflowNode(node: WorkflowTemplate["nodes"][number], metadata?: NodeRegistryNode): WorkflowNode {
  const normalizedNodeType = node.type;
  return {
    id: node.id,
    type: normalizedNodeType,
    position: node.position,
    data: {
      label: node.data.label,
      config: cloneConfig(node.data.config),
      configSchema: metadata?.config_schema ?? fallbackConfigSchema(normalizedNodeType),
      inputTypes: metadata?.input_types,
      outputTypes: metadata?.output_types,
      maxInputs: metadata?.max_inputs,
      inputPorts: metadata?.input_ports
    }
  };
}

function toWorkflowEdge(connection: WorkflowTemplate["connections"][number]): WorkflowEdge {
  return {
    id: connection.id,
    source: connection.source,
    target: connection.target
  };
}

export function applyTemplateToWorkflowStore(template: WorkflowTemplate): void {
  const store = useWorkflowStore.getState();
  const registryMap = new Map(store.nodeRegistry.nodes.map((node) => [node.node_type, node]));

  const initialNodes = template.nodes.map((node) =>
    toWorkflowNode(node, registryMap.get(node.type))
  );
  const initialEdges = template.connections.map((conn) => {
    const edge = toWorkflowEdge(conn);
    // Resolve targetHandle from registry so edges connect to the correct handle
    // (e.g. "input-primary" for multi-input nodes) instead of relying on
    // ReactFlow's first-handle fallback.
    const targetHandle = resolveTargetHandleForEdge(
      conn.source, conn.target, initialNodes, store.nodeRegistry.nodes
    );
    if (targetHandle) {
      edge.targetHandle = targetHandle;
    }
    return edge;
  });
  const { nodes, edges } = ensureSingleEndNodeGraph({
    nodes: initialNodes,
    edges: initialEdges,
    registry: store.nodeRegistry
  });
  const nodeConfigs = Object.fromEntries(nodes.map((node) => [node.id, cloneConfig(node.data.config)]));
  const selectedNodeId = resolvePreferredEditableNodeId(nodes);

  useWorkflowStore.setState((state) => ({
    ...state,
    nodes,
    edges,
    nodeConfigs,
    uploadedFiles: {},
    selectedNodeId
  }));

  // Auto-fill default providers for engine-category nodes that don't have one
  const engineNodes = nodes.filter(
    (n) => n.type in ENGINE_CATEGORY_MAP && !nodeConfigs[n.id]?.provider_id
  );
  if (engineNodes.length > 0) {
    // Group by engine category to minimize API calls
    const categoryMap = new Map<string, string[]>();
    for (const n of engineNodes) {
      const cat = ENGINE_CATEGORY_MAP[n.type];
      if (!categoryMap.has(cat)) categoryMap.set(cat, []);
      categoryMap.get(cat)!.push(n.id);
    }
    for (const [category, nodeIds] of categoryMap) {
      getDefaultProvider(category)
        .then((defaultProvider) => {
          if (!defaultProvider) return;
          for (const nodeId of nodeIds) {
            const patch: Record<string, unknown> = {
              provider_id: defaultProvider.id,
              provider_name: defaultProvider.name,
            };
            if (defaultProvider.provider_type === "openai_compatible") {
              const enabled = defaultProvider.models.filter((m) => m.is_enabled);
              patch.model = enabled.length === 1 ? enabled[0].model_id : undefined;
            }
            // Fill in param defaults (language, det_thresh, etc.)
            // Get node's current config to avoid overwriting template-set values
            const currentState = useWorkflowStore.getState();
            const nodeConfig = currentState.nodeConfigs[nodeId] ?? {};
            const node = currentState.nodes.find((n) => n.id === nodeId);
            const paramDefaults = getProviderParamDefaults(
              defaultProvider,
              node?.data.configSchema as NodeConfigSchema | undefined,
              nodeConfig,
            );
            Object.assign(patch, paramDefaults);
            currentState.updateNodeConfig(nodeId, patch);
          }
        })
        .catch(() => { /* no default provider */ });
    }
  }
}
