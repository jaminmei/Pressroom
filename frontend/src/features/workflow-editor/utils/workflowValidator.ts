import { isTypeCompatible } from "@/features/workflow-editor/utils/connectionValidator";
import type { InputPortDef, NodeRegistryConnectionRule, NodeRegistryNode } from "@/types/node-registry";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";
import type { TFunction } from "i18next";

export type WorkflowValidationCode =
  | "WORKFLOW_NO_INPUT"
  | "WORKFLOW_NO_END"
  | "WORKFLOW_MULTIPLE_END"
  | "END_NODE_NOT_TERMINAL"
  | "MISSING_REQUIRED_CONFIG"
  | "MISSING_PROVIDER"
  | "INVALID_CONNECTION"
  | "TYPE_INCOMPATIBLE"
  | "WORKFLOW_CYCLE"
  | "WORKFLOW_ORPHAN_NODE"
  | "ENGINE_UNAVAILABLE";

export interface WorkflowValidationIssue {
  code: WorkflowValidationCode;
  message: string;
  nodeId?: string;
  severity: "blocking" | "warning";
}

export interface ValidateWorkflowInput {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  nodeConfigs: Record<string, Record<string, unknown>>;
  uploadedFiles: Record<string, File>;
  registryNodes?: NodeRegistryNode[];
  connectionRules?: NodeRegistryConnectionRule[];
  unavailableEngines?: string[];
  t?: TFunction;
}

export interface WorkflowValidationResult {
  isExecutable: boolean;
  blockingErrors: WorkflowValidationIssue[];
  warnings: WorkflowValidationIssue[];
  issues: WorkflowValidationIssue[];
}

function categoryFromNodeType(nodeType: string): string {
  return nodeType.split("/")[0] ?? nodeType;
}

function isEndNode(node: WorkflowNode): boolean {
  return node.type === "end/final";
}

function hasMissingRequiredConfig(
  node: WorkflowNode,
  config: Record<string, unknown>,
  uploadedFiles: Record<string, File>
): boolean {
  const required = node.data.configSchema.required ?? [];
  return required.some((field) => {
    if (field === "file" && node.type.startsWith("input/")) {
      return !uploadedFiles[node.id];
    }

    const value = config[field];
    return value === undefined || value === null || value === "";
  });
}

function hasDirectedCycle(nodes: WorkflowNode[], edges: WorkflowEdge[]): boolean {
  const adjacency = new Map<string, string[]>();
  const visiting = new Set<string>();
  const visited = new Set<string>();

  nodes.forEach((node) => {
    adjacency.set(node.id, []);
  });
  edges.forEach((edge) => {
    adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target]);
  });

  const dfs = (nodeId: string): boolean => {
    if (visiting.has(nodeId)) {
      return true;
    }
    if (visited.has(nodeId)) {
      return false;
    }

    visiting.add(nodeId);
    for (const next of adjacency.get(nodeId) ?? []) {
      if (dfs(next)) {
        return true;
      }
    }
    visiting.delete(nodeId);
    visited.add(nodeId);
    return false;
  };

  return nodes.some((node) => dfs(node.id));
}

/**
 * @deprecated Category-based connection rules are replaced by port-type-based
 * validation (MIME type matching on input_types/output_types). This function is
 * retained for backward compatibility but connection_rules is always [].
 */
function validateConnectionRules(
  nodesById: Map<string, WorkflowNode>,
  edges: WorkflowEdge[],
  connectionRules: NodeRegistryConnectionRule[],
  registryNodes: NodeRegistryNode[],
  t?: TFunction
): WorkflowValidationIssue[] {
  const registryByType = new Map(registryNodes.map((node) => [node.node_type, node]));
  const allowMap = new Map(
    connectionRules.map((rule) => [rule.from_category, new Set(rule.to_categories)])
  );
  const issues: WorkflowValidationIssue[] = [];
  const incomingCount = new Map<string, number>();
  const outgoingCount = new Map<string, number>();
  const portConnectionCounts = new Map<string, number>();

  for (const edge of edges) {
    const sourceNode = nodesById.get(edge.source);
    const targetNode = nodesById.get(edge.target);

    if (!sourceNode || !targetNode) {
      issues.push({
        code: "INVALID_CONNECTION",
        severity: "blocking",
        message: t?.("workflows:editorText.validationMessages.missingEdgeNode", { edgeId: edge.id }) ?? `連線 ${edge.id} 指向不存在的節點`,
        nodeId: edge.source
      });
      continue;
    }

    const sourceRegistryNode = registryByType.get(sourceNode.type);
    const targetRegistryNode = registryByType.get(targetNode.type);
    const sourceCategory = sourceRegistryNode?.category ?? categoryFromNodeType(sourceNode.type);
    const targetCategory = targetRegistryNode?.category ?? categoryFromNodeType(targetNode.type);
    const nextOutgoingCount = (outgoingCount.get(sourceNode.id) ?? 0) + 1;
    const nextIncomingCount = (incomingCount.get(targetNode.id) ?? 0) + 1;

    outgoingCount.set(sourceNode.id, nextOutgoingCount);
    incomingCount.set(targetNode.id, nextIncomingCount);

    const sourceMaxOutputs = sourceRegistryNode?.max_outputs;
    if (
      sourceMaxOutputs !== undefined &&
      sourceMaxOutputs >= 0 &&
      nextOutgoingCount > sourceMaxOutputs
    ) {
      issues.push({
        code: "INVALID_CONNECTION",
        severity: "blocking",
        message: t?.("workflows:editorText.validationMessages.maxOutputs", { nodeId: sourceNode.id }) ?? `節點 ${sourceNode.id} 超過最大輸出連線數`,
        nodeId: sourceNode.id
      });
    }

    const targetMaxInputs = targetRegistryNode?.max_inputs;
    if (
      targetMaxInputs !== undefined &&
      targetMaxInputs >= 0 &&
      nextIncomingCount > targetMaxInputs
    ) {
      issues.push({
        code: "INVALID_CONNECTION",
        severity: "blocking",
        message: t?.("workflows:editorText.validationMessages.maxInputs", { nodeId: targetNode.id }) ?? `節點 ${targetNode.id} 超過最大輸入連線數`,
        nodeId: targetNode.id
      });
    }

    if (connectionRules.length > 0) {
      const allowedTargets = allowMap.get(sourceCategory);
      if (!allowedTargets || !allowedTargets.has(targetCategory)) {
        issues.push({
          code: "INVALID_CONNECTION",
          severity: "blocking",
          message: t?.("workflows:editorText.validationMessages.ruleMismatch", { edgeId: edge.id, source: sourceCategory, target: targetCategory }) ?? `連線 ${edge.id} 不符合 ${sourceCategory} → ${targetCategory} 規則`,
          nodeId: edge.target
        });
      }
    }

    // Per-port validation when input_ports are defined
    const targetInputPorts: InputPortDef[] | undefined =
      targetRegistryNode?.input_ports ?? targetNode.data.inputPorts;

    const sourceOutputTypes = sourceRegistryNode?.output_types ?? sourceNode.data.outputTypes;

    if (targetInputPorts && targetInputPorts.length > 0) {
      // Determine which port this edge connects to
      const portName = edge.targetHandle?.startsWith("input-")
        ? edge.targetHandle.slice("input-".length)
        : undefined;

      const targetPort = portName
        ? targetInputPorts.find((p) => p.name === portName)
        : targetInputPorts[0];

      if (targetPort) {
        // Check port max_connections
        const portKey = `${targetNode.id}::${targetPort.name}`;
        const currentPortCount = portConnectionCounts.get(portKey) ?? 0;
        portConnectionCounts.set(portKey, currentPortCount + 1);

        if (targetPort.max_connections !== -1 && currentPortCount + 1 > targetPort.max_connections) {
          issues.push({
            code: "INVALID_CONNECTION",
            severity: "blocking",
            message: t?.("workflows:editorText.validationMessages.portMax", { nodeId: targetNode.id, port: targetPort.name }) ?? `節點 ${targetNode.id} 的輸入埠 ${targetPort.name} 超過最大連線數`,
            nodeId: targetNode.id
          });
        }

        // Check type compatibility against port accepted_types
        const targetInputTypes = targetPort.accepted_types;
        if (!isTypeCompatible(sourceOutputTypes, targetInputTypes)) {
          issues.push({
            code: "TYPE_INCOMPATIBLE",
            severity: "blocking",
            message: t?.("workflows:editorText.validationMessages.typePort", { source: sourceNode.id, target: targetNode.id, port: targetPort.name }) ?? `節點類型不相容：${sourceNode.id} -> ${targetNode.id}（埠 ${targetPort.name}）`,
            nodeId: targetNode.id
          });
        }
      } else {
        // Port not found — check type compatibility against all ports combined
        const allAcceptedTypes = targetInputPorts.flatMap((p) => p.accepted_types);
        if (!isTypeCompatible(sourceOutputTypes, allAcceptedTypes)) {
          issues.push({
            code: "TYPE_INCOMPATIBLE",
            severity: "blocking",
            message: t?.("workflows:editorText.validationMessages.type", { source: sourceNode.id, target: targetNode.id }) ?? `節點類型不相容：${sourceNode.id} -> ${targetNode.id}`,
            nodeId: targetNode.id
          });
        }
      }
    } else {
      // Fallback: flat input_types validation
      const targetInputTypes = targetRegistryNode?.input_types ?? targetNode.data.inputTypes;
      if (!isTypeCompatible(sourceOutputTypes, targetInputTypes)) {
        issues.push({
          code: "TYPE_INCOMPATIBLE",
          severity: "blocking",
          message: t?.("workflows:editorText.validationMessages.type", { source: sourceNode.id, target: targetNode.id }) ?? `節點類型不相容：${sourceNode.id} -> ${targetNode.id}`,
          nodeId: targetNode.id
        });
      }
    }
  }

  return issues;
}

function extractUnavailableEngines(unavailableEngines: string[] = []): Set<string> {
  return new Set(
    unavailableEngines
      .map((engine) => engine.trim().toLowerCase())
      .filter(Boolean)
      .map((engine) => (engine.startsWith("engine/") ? engine.replace("engine/", "") : engine))
  );
}

function collectWarnings(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  unavailableEngines: Set<string>,
  t?: TFunction
): WorkflowValidationIssue[] {
  const warnings: WorkflowValidationIssue[] = [];

  const connectedNodes = new Set<string>();
  edges.forEach((edge) => {
    connectedNodes.add(edge.source);
    connectedNodes.add(edge.target);
  });

  nodes.forEach((node) => {
    if (!connectedNodes.has(node.id)) {
      warnings.push({
        code: "WORKFLOW_ORPHAN_NODE",
        severity: "warning",
        nodeId: node.id,
        message: t?.("workflows:editorText.validationMessages.orphan", { nodeId: node.id }) ?? `節點 ${node.id} 未連接到任何連線`
      });
    }

    if (node.type.startsWith("engine/")) {
      const engineName = node.type.replace("engine/", "").toLowerCase();
      // Skip health check warnings for VLM engines — validating model availability
      // is expensive and errors will surface at runtime instead.
      if (engineName !== "model" && unavailableEngines.has(engineName)) {
        warnings.push({
          code: "ENGINE_UNAVAILABLE",
          severity: "warning",
          nodeId: node.id,
          message: t?.("workflows:editorText.validationMessages.engineOffline", { nodeId: node.id }) ?? `${node.id} 引擎目前離線，執行可能失敗`
        });
      }
    }
  });

  return warnings;
}

export function validateWorkflowDefinition(input: ValidateWorkflowInput): WorkflowValidationResult {
  const {
    nodes,
    edges,
    nodeConfigs,
    uploadedFiles,
    registryNodes = [],
    connectionRules = [],
    unavailableEngines = [],
    t
  } = input;
  const blockingErrors: WorkflowValidationIssue[] = [];
  const nodesById = new Map(nodes.map((node) => [node.id, node]));

  const inputNodes = nodes.filter((node) => node.type.startsWith("input/"));
  const endNodes = nodes.filter(isEndNode);

  if (inputNodes.length === 0) {
    blockingErrors.push({
      code: "WORKFLOW_NO_INPUT",
      severity: "blocking",
      message: t?.("workflows:editorText.validationMessages.noInput") ?? "至少需要一個 input 節點"
    });
  }

  if (endNodes.length === 0) {
    blockingErrors.push({
      code: "WORKFLOW_NO_END",
      severity: "blocking",
      message: t?.("workflows:editorText.validationMessages.noEnd") ?? "至少需要一個 end/final 節點"
    });
  }

  if (endNodes.length > 1) {
    blockingErrors.push({
      code: "WORKFLOW_MULTIPLE_END",
      severity: "blocking",
      message: t?.("workflows:editorText.validationMessages.multipleEnd") ?? "Workflow 僅允許一個 end/final 節點"
    });
  }

  if (endNodes.length === 1) {
    const [endNode] = endNodes;
    const endOutgoingEdges = edges.filter((edge) => edge.source === endNode.id);
    if (endOutgoingEdges.length > 0) {
      blockingErrors.push({
        code: "END_NODE_NOT_TERMINAL",
        severity: "blocking",
        nodeId: endNode.id,
        message: t?.("workflows:editorText.validationMessages.endNotTerminal", { nodeId: endNode.id }) ?? `節點 ${endNode.id} 不可有下游連線`
      });
    }
  }

  nodes.forEach((node) => {
    const config = nodeConfigs[node.id] ?? node.data.config ?? {};
    if (hasMissingRequiredConfig(node, config, uploadedFiles)) {
      blockingErrors.push({
        code: "MISSING_REQUIRED_CONFIG",
        severity: "blocking",
        nodeId: node.id,
        message: t?.("workflows:editorText.validationMessages.missingConfig", { nodeId: node.id }) ?? `節點 ${node.id} 缺少必填配置`
      });
    }

    // Engine nodes and external processors require a provider_id
    // Built-in processors (handled by DAG scheduler) are excluded
    const BUILTIN_PROCESSORS = new Set([
      "processor/document_to_image",
      "processor/adaptor",
      "processor/iteration"
    ]);
    const category = categoryFromNodeType(node.type);
    const needsProvider = (category === "engine" || category === "processor") && !BUILTIN_PROCESSORS.has(node.type ?? "");
    if (needsProvider && !config.provider_id) {
      blockingErrors.push({
        code: "MISSING_PROVIDER",
        severity: "blocking",
        nodeId: node.id,
        message: t?.("workflows:editorText.validationMessages.missingProvider", { nodeId: node.id }) ?? `節點 ${node.id} 尚未選擇 Provider`
      });
    }
  });

  blockingErrors.push(...validateConnectionRules(nodesById, edges, connectionRules, registryNodes, t));

  if (nodes.length > 0 && hasDirectedCycle(nodes, edges)) {
    blockingErrors.push({
      code: "WORKFLOW_CYCLE",
      severity: "blocking",
      message: t?.("workflows:editorText.validationMessages.cycle") ?? "Workflow 含有循環依賴"
    });
  }

  const warnings = collectWarnings(nodes, edges, extractUnavailableEngines(unavailableEngines), t);

  return {
    isExecutable: blockingErrors.length === 0,
    blockingErrors,
    warnings,
    issues: [...blockingErrors, ...warnings]
  };
}
