import { create } from "zustand";

import { getCustomEdgeStyle } from "@/features/workflow-editor/components/CustomEdge";
import { buildDefaultValues } from "@/features/workflow-editor/utils/configDefaults";
import { validateConnection } from "@/features/workflow-editor/utils/connectionValidator";
import { ensureSingleEndNodeGraph } from "@/features/workflow-editor/utils/endNodeRepair";
import { resolveTargetHandleForEdge } from "@/features/workflow-editor/utils/handleRouting";
import type { NodeRegistryResponse } from "@/types/node-registry";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

export interface DynamicWarning {
  code: string;
  severity: "warning" | "info";
  node_id: string;
  message: string;
  model: string | null;
  edge_ids: string[];
}

export interface DynamicValidationState {
  warnings: DynamicWarning[];
  lastValidatedAt: number | null;
  isValidating: boolean;
}

export interface WorkflowState {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  nodeConfigs: Record<string, Record<string, unknown>>;
  uploadedFiles: Record<string, File>;
  nodeRegistry: Pick<NodeRegistryResponse, "nodes" | "connection_rules">;
  selectedNodeId: string | null;
  removeNodes: (nodeIds: string[]) => void;
  duplicateNodes: (nodeIds: string[], offset?: { x: number; y: number }) => string[];
  alignNodes: (nodeIds: string[], direction: "horizontal" | "vertical") => void;
  addNode: (nodeType: string, position?: { x: number; y: number }) => string;
  addEdge: (edge: WorkflowEdge) => void;
  insertNodeBetweenEdge: (
    edgeId: string,
    nodeType: string,
    position?: { x: number; y: number }
  ) => string | null;
  duplicateNode: (nodeId: string) => string | null;
  setNodeRegistry: (registry: Pick<NodeRegistryResponse, "nodes" | "connection_rules">) => void;
  setNodes: (nodes: WorkflowNode[]) => void;
  setEdges: (edges: WorkflowEdge[]) => void;
  selectNode: (nodeId: string | null) => void;
  updateNodeConfig: (nodeId: string, patch: Record<string, unknown>) => void;
  removeNode: (nodeId: string) => void;
  setUploadedFile: (nodeId: string, file: File) => void;
  removeUploadedFile: (nodeId: string) => void;
  clearCanvas: () => void;
  dynamicValidation: DynamicValidationState;
  setDynamicWarnings: (warnings: DynamicWarning[]) => void;
  setIsValidating: (isValidating: boolean) => void;
  clearDynamicWarnings: () => void;
  getDynamicWarningsForNode: (nodeId: string) => DynamicWarning[];
  hasDynamicBlockers: () => boolean;
  edgeRefreshEpoch: number;
  requestEdgeRefresh: () => void;
  canvasResetKey: number;
  resetCanvas: () => void;
}

const initialState: Pick<
  WorkflowState,
  "nodes" | "edges" | "nodeConfigs" | "uploadedFiles" | "nodeRegistry" | "selectedNodeId" | "edgeRefreshEpoch" | "canvasResetKey" | "dynamicValidation"
> = {
  nodes: [],
  edges: [],
  nodeConfigs: {},
  uploadedFiles: {},
  nodeRegistry: { nodes: [], connection_rules: [] },
  selectedNodeId: null,
  edgeRefreshEpoch: 0,
  canvasResetKey: 0,
  dynamicValidation: {
    warnings: [],
    lastValidatedAt: null,
    isValidating: false,
  },
};

function compactConfig(config: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(config).filter(([, value]) => value !== undefined));
}

function toNodeIdPrefix(nodeType: string): string {
  return nodeType.replace(/\//g, "_");
}

function createUniqueNodeId(nodeType: string, usedIds: Set<string>, startIndex: number): string {
  let index = startIndex;
  let candidate = `${toNodeIdPrefix(nodeType)}_${index}`;
  while (usedIds.has(candidate)) {
    index += 1;
    candidate = `${toNodeIdPrefix(nodeType)}_${index}`;
  }
  usedIds.add(candidate);
  return candidate;
}

function createUniqueEdgeId(sourceId: string, targetId: string, usedIds: Set<string>): string {
  let index = 1;
  let candidate = `${sourceId}-${targetId}-dup-${index}`;
  while (usedIds.has(candidate)) {
    index += 1;
    candidate = `${sourceId}-${targetId}-dup-${index}`;
  }
  usedIds.add(candidate);
  return candidate;
}

function buildValidatedWorkflowEdge(
  sourceNodeId: string,
  targetNodeId: string,
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  registry: Pick<NodeRegistryResponse, "nodes" | "connection_rules">
): WorkflowEdge | null {
  const validation = validateConnection({
    sourceNodeId,
    targetNodeId,
    nodes,
    edges,
    registry
  });
  if (!validation.isValid) {
    return null;
  }

  const isTypeWarning = !validation.isTypeCompatible;
  const targetHandle = resolveTargetHandleForEdge(
    sourceNodeId,
    targetNodeId,
    nodes,
    registry.nodes
  );
  return {
    id: `e-${sourceNodeId}-${targetNodeId}-${edges.length + 1}`,
    source: sourceNodeId,
    target: targetNodeId,
    ...(targetHandle ? { targetHandle } : {}),
    data: {
      isTypeWarning,
      warningCode: validation.warningCode
    },
    style: getCustomEdgeStyle({ isTypeWarning })
  };
}

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  ...initialState,
  removeNodes: (nodeIds) => {
    set((state) => {
      const nodeIdSet = new Set(nodeIds);
      if (nodeIdSet.size === 0) {
        return state;
      }
      const remainingConfigs = Object.fromEntries(
        Object.entries(state.nodeConfigs).filter(([id]) => !nodeIdSet.has(id))
      );
      const remainingFiles = Object.fromEntries(
        Object.entries(state.uploadedFiles).filter(([id]) => !nodeIdSet.has(id))
      );
      const repairedGraph = ensureSingleEndNodeGraph({
        nodes: state.nodes.filter((node) => !nodeIdSet.has(node.id)),
        edges: state.edges.filter((edge) => !nodeIdSet.has(edge.source) && !nodeIdSet.has(edge.target)),
        registry: state.nodeRegistry
      });
      const nextNodeConfigs = Object.fromEntries(
        repairedGraph.nodes.map((node) => [node.id, remainingConfigs[node.id] ?? node.data.config ?? {}])
      );

      return {
        nodes: repairedGraph.nodes,
        edges: repairedGraph.edges,
        nodeConfigs: nextNodeConfigs,
        uploadedFiles: remainingFiles,
        selectedNodeId:
          state.selectedNodeId && repairedGraph.nodes.every((node) => node.id !== state.selectedNodeId)
            ? null
            : state.selectedNodeId
      };
    });
  },
  duplicateNodes: (nodeIds, offset = { x: 50, y: 50 }) => {
    const duplicatedIds: string[] = [];

    set((state) => {
      const sourceNodes = nodeIds
        .map((nodeId) => state.nodes.find((node) => node.id === nodeId))
        .filter((node): node is WorkflowNode => node !== undefined);
      if (sourceNodes.length === 0) {
        return state;
      }

      const usedNodeIds = new Set(state.nodes.map((node) => node.id));
      const usedEdgeIds = new Set(state.edges.map((edge) => edge.id));
      const sourceToDuplicateId = new Map<string, string>();
      let nextNodeIndex = state.nodes.length + 1;

      const duplicatedNodes = sourceNodes.map((sourceNode) => {
        const nextNodeId = createUniqueNodeId(sourceNode.type, usedNodeIds, nextNodeIndex);
        nextNodeIndex += 1;
        duplicatedIds.push(nextNodeId);
        sourceToDuplicateId.set(sourceNode.id, nextNodeId);
        const basePosition = sourceNode.position ?? { x: 120, y: 120 };
        const nextConfig = { ...(state.nodeConfigs[sourceNode.id] ?? sourceNode.data.config ?? {}) };

        return {
          ...sourceNode,
          id: nextNodeId,
          position: {
            x: basePosition.x + offset.x,
            y: basePosition.y + offset.y
          },
          data: {
            ...sourceNode.data,
            config: nextConfig
          }
        } satisfies WorkflowNode;
      });

      const duplicatedEdges = state.edges
        .filter((edge) => sourceToDuplicateId.has(edge.source) && sourceToDuplicateId.has(edge.target))
        .map((edge) => {
          const duplicatedSource = sourceToDuplicateId.get(edge.source);
          const duplicatedTarget = sourceToDuplicateId.get(edge.target);
          if (!duplicatedSource || !duplicatedTarget) {
            return null;
          }
          return {
            ...edge,
            id: createUniqueEdgeId(duplicatedSource, duplicatedTarget, usedEdgeIds),
            source: duplicatedSource,
            target: duplicatedTarget
          } satisfies WorkflowEdge;
        })
        .filter((edge): edge is WorkflowEdge => edge !== null);

      const duplicatedConfigs = Object.fromEntries(
        duplicatedNodes.map((node) => [node.id, { ...(node.data.config ?? {}) }])
      );
      const repairedGraph = ensureSingleEndNodeGraph({
        nodes: [...state.nodes, ...duplicatedNodes],
        edges: [...state.edges, ...duplicatedEdges],
        registry: state.nodeRegistry
      });
      const nextNodeConfigs = Object.fromEntries(
        repairedGraph.nodes.map((node) => [
          node.id,
          duplicatedConfigs[node.id] ?? state.nodeConfigs[node.id] ?? node.data.config ?? {}
        ])
      );

      return {
        nodes: repairedGraph.nodes,
        edges: repairedGraph.edges,
        nodeConfigs: nextNodeConfigs,
        selectedNodeId: duplicatedIds[0] ?? state.selectedNodeId
      };
    });

    return duplicatedIds;
  },
  alignNodes: (nodeIds, direction) => {
    set((state) => {
      const anchorNodeId = nodeIds[0];
      if (!anchorNodeId) {
        return state;
      }

      const anchorNode = state.nodes.find((node) => node.id === anchorNodeId);
      if (!anchorNode) {
        return state;
      }

      const nodeIdSet = new Set(nodeIds);
      const anchorPosition = anchorNode.position ?? { x: 120, y: 120 };
      const alignedNodes = state.nodes.map((node) => {
        if (!nodeIdSet.has(node.id)) {
          return node;
        }
        if (node.id === anchorNodeId) {
          return {
            ...node,
            position: node.position ?? anchorPosition
          };
        }

        const currentPosition = node.position ?? { x: 120, y: 120 };
        return {
          ...node,
          position:
            direction === "horizontal"
              ? { x: currentPosition.x, y: anchorPosition.y }
              : { x: anchorPosition.x, y: currentPosition.y }
        };
      });

      return {
        nodes: alignedNodes
      };
    });
  },
  addNode: (nodeType, position) => {
    let createdNodeId = "";
    set((state) => {
      const index = state.nodes.length + 1;
      const nodeId = createUniqueNodeId(nodeType, new Set(state.nodes.map((node) => node.id)), index);
      createdNodeId = nodeId;
      const parts = nodeType.split("/");
      const metadata = state.nodeRegistry.nodes.find((node) => node.node_type === nodeType);
      const defaultLabel = (parts[parts.length - 1] ?? nodeType).toUpperCase();
      const configSchema = metadata?.config_schema ?? { type: "object", properties: {} };
      const defaultConfig = buildDefaultValues(configSchema);
      const nextNode: WorkflowNode = {
        id: nodeId,
        type: nodeType,
        data: {
          label: metadata?.display_name ?? defaultLabel,
          config: defaultConfig,
          configSchema,
          inputTypes: metadata?.input_types,
          outputTypes: metadata?.output_types,
          maxInputs: metadata?.max_inputs,
          inputPorts: metadata?.input_ports
        },
        position
      };
      const repairedGraph = ensureSingleEndNodeGraph({
        nodes: [...state.nodes, nextNode],
        edges: state.edges,
        registry: state.nodeRegistry
      });
      const nextNodeConfigs = Object.fromEntries(
        repairedGraph.nodes.map((node) => [node.id, state.nodeConfigs[node.id] ?? node.data.config ?? {}])
      );
      nextNodeConfigs[nodeId] = defaultConfig;

      return {
        nodes: repairedGraph.nodes,
        edges: repairedGraph.edges,
        nodeConfigs: nextNodeConfigs
      };
    });
    return createdNodeId;
  },
  addEdge: (edge) => {
    set((state) => ({ edges: [...state.edges, edge] }));
  },
  insertNodeBetweenEdge: (edgeId, nodeType, position) => {
    let createdNodeId: string | null = null;
    set((state) => {
      const targetEdge = state.edges.find((edge) => edge.id === edgeId);
      if (!targetEdge) {
        return state;
      }

      const index = state.nodes.length + 1;
      const nodeId = createUniqueNodeId(nodeType, new Set(state.nodes.map((node) => node.id)), index);
      const metadata = state.nodeRegistry.nodes.find((node) => node.node_type === nodeType);
      const nodeTypeParts = nodeType.split("/");
      const namePart = nodeTypeParts[nodeTypeParts.length - 1] ?? nodeType;
      const configSchema = metadata?.config_schema ?? { type: "object", properties: {} };
      const defaultConfig = buildDefaultValues(configSchema);
      const nextNode: WorkflowNode = {
        id: nodeId,
        type: nodeType,
        data: {
          label: metadata?.display_name ?? namePart.toUpperCase(),
          config: defaultConfig,
          configSchema,
          inputTypes: metadata?.input_types,
          outputTypes: metadata?.output_types,
          maxInputs: metadata?.max_inputs,
          inputPorts: metadata?.input_ports
        },
        position
      };

      const nextNodes = [...state.nodes, nextNode];
      const remainingEdges = state.edges.filter((edge) => edge.id !== edgeId);
      const firstEdge = buildValidatedWorkflowEdge(
        targetEdge.source,
        nodeId,
        nextNodes,
        remainingEdges,
        state.nodeRegistry
      );
      if (!firstEdge) {
        return state;
      }

      const secondEdge = buildValidatedWorkflowEdge(
        nodeId,
        targetEdge.target,
        nextNodes,
        [...remainingEdges, firstEdge],
        state.nodeRegistry
      );
      if (!secondEdge) {
        return state;
      }

      createdNodeId = nodeId;
      const repairedGraph = ensureSingleEndNodeGraph({
        nodes: nextNodes,
        edges: [...remainingEdges, firstEdge, secondEdge],
        registry: state.nodeRegistry
      });
      const nextNodeConfigs = Object.fromEntries(
        repairedGraph.nodes.map((node) => [node.id, state.nodeConfigs[node.id] ?? node.data.config ?? {}])
      );
      nextNodeConfigs[nodeId] = defaultConfig;

      return {
        nodes: repairedGraph.nodes,
        edges: repairedGraph.edges,
        nodeConfigs: nextNodeConfigs
      };
    });
    return createdNodeId;
  },
  duplicateNode: (nodeId) => {
    let duplicatedNodeId: string | null = null;
    set((state) => {
      const sourceNode = state.nodes.find((item) => item.id === nodeId);
      if (!sourceNode) {
        return state;
      }
      const index = state.nodes.length + 1;
      const nextNodeId = createUniqueNodeId(
        sourceNode.type,
        new Set(state.nodes.map((node) => node.id)),
        index
      );
      duplicatedNodeId = nextNodeId;
      const basePosition = sourceNode.position ?? { x: 120, y: 120 };
      const nextConfig = { ...(state.nodeConfigs[nodeId] ?? sourceNode.data.config ?? {}) };
      const duplicatedNode: WorkflowNode = {
        ...sourceNode,
        id: nextNodeId,
        position: { x: basePosition.x + 32, y: basePosition.y + 32 },
        data: {
          ...sourceNode.data,
          config: nextConfig
        }
      };
      const repairedGraph = ensureSingleEndNodeGraph({
        nodes: [...state.nodes, duplicatedNode],
        edges: state.edges,
        registry: state.nodeRegistry
      });
      const nextNodeConfigs = Object.fromEntries(
        repairedGraph.nodes.map((node) => [node.id, state.nodeConfigs[node.id] ?? node.data.config ?? {}])
      );
      nextNodeConfigs[nextNodeId] = nextConfig;
      return {
        nodes: repairedGraph.nodes,
        edges: repairedGraph.edges,
        nodeConfigs: nextNodeConfigs
      };
    });
    return duplicatedNodeId;
  },
  setNodeRegistry: (registry) => {
    set((state) => {
      const repairedGraph = ensureSingleEndNodeGraph({
        nodes: state.nodes,
        edges: state.edges,
        registry
      });

      return {
        nodeRegistry: registry,
        nodes: repairedGraph.nodes,
        edges: repairedGraph.edges,
        nodeConfigs: Object.fromEntries(
          repairedGraph.nodes.map((node) => [node.id, state.nodeConfigs[node.id] ?? node.data.config ?? {}])
        )
      };
    });
  },
  setNodes: (nodes) => {
    set({
      nodes,
      nodeConfigs: Object.fromEntries(nodes.map((node) => [node.id, node.data.config ?? {}]))
    });
  },
  setEdges: (edges) => {
    set({ edges });
  },
  selectNode: (nodeId) => {
    set({ selectedNodeId: nodeId });
  },
  updateNodeConfig: (nodeId, patch) => {
    set((state) => {
      const currentConfig = state.nodeConfigs[nodeId] ?? {};
      const nextConfig = compactConfig({ ...currentConfig, ...patch });

      return {
        nodeConfigs: {
          ...state.nodeConfigs,
          [nodeId]: nextConfig
        },
        nodes: state.nodes.map((node) =>
          node.id === nodeId
            ? {
                ...node,
                data: {
                  ...node.data,
                  config: nextConfig
                }
              }
            : node
        )
      };
    });
  },
  removeNode: (nodeId) => {
    set((state) => {
      const remainingConfigs = Object.fromEntries(
        Object.entries(state.nodeConfigs).filter(([id]) => id !== nodeId)
      );
      const remainingFiles = Object.fromEntries(
        Object.entries(state.uploadedFiles).filter(([id]) => id !== nodeId)
      );
      const repairedGraph = ensureSingleEndNodeGraph({
        nodes: state.nodes.filter((node) => node.id !== nodeId),
        edges: state.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId),
        registry: state.nodeRegistry
      });
      const nextNodeConfigs = Object.fromEntries(
        repairedGraph.nodes.map((node) => [node.id, remainingConfigs[node.id] ?? node.data.config ?? {}])
      );

      return {
        nodes: repairedGraph.nodes,
        edges: repairedGraph.edges,
        nodeConfigs: nextNodeConfigs,
        uploadedFiles: remainingFiles,
        selectedNodeId:
          state.selectedNodeId && repairedGraph.nodes.every((node) => node.id !== state.selectedNodeId)
            ? null
            : state.selectedNodeId
      };
    });
  },
  setUploadedFile: (nodeId, file) => {
    set((state) => ({
      uploadedFiles: {
        ...state.uploadedFiles,
        [nodeId]: file
      }
    }));
  },
  removeUploadedFile: (nodeId) => {
    set((state) => {
      const remainingFiles = Object.fromEntries(
        Object.entries(state.uploadedFiles).filter(([id]) => id !== nodeId)
      );
      return { uploadedFiles: remainingFiles };
    });
  },
  clearCanvas: () => {
    set((state) => ({
      ...initialState,
      nodeRegistry: state.nodeRegistry
    }));
  },
  setDynamicWarnings: (warnings) =>
    set({
      dynamicValidation: {
        warnings,
        lastValidatedAt: Date.now(),
        isValidating: false,
      },
    }),
  setIsValidating: (isValidating) =>
    set((state) => ({
      dynamicValidation: {
        ...state.dynamicValidation,
        isValidating,
      },
    })),
  clearDynamicWarnings: () =>
    set({
      dynamicValidation: {
        warnings: [],
        lastValidatedAt: null,
        isValidating: false,
      },
    }),
  getDynamicWarningsForNode: (nodeId) =>
    get().dynamicValidation.warnings.filter((w) => w.node_id === nodeId),
  hasDynamicBlockers: () =>
    get().dynamicValidation.warnings.some((w) => w.severity === "warning"),
  requestEdgeRefresh: () => set((s) => ({ edgeRefreshEpoch: s.edgeRefreshEpoch + 1 })),
  resetCanvas: () => set((s) => ({ canvasResetKey: s.canvasResetKey + 1 })),
}));

export function useDynamicWarningsForNode(nodeId: string) {
  return useWorkflowStore((s) =>
    s.dynamicValidation.warnings.filter((w) => w.node_id === nodeId)
  );
}

export function useHasDynamicBlockers() {
  return useWorkflowStore((s) =>
    s.dynamicValidation.warnings.some((w) => w.severity === "warning")
  );
}
