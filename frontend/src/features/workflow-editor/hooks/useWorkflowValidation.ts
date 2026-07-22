import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useWorkflowStore } from "@/features/workflow-editor/store";
import {
  type WorkflowValidationIssue,
  validateWorkflowDefinition
} from "@/features/workflow-editor/utils/workflowValidator";
import { useUIStore } from "@/stores/uiStore";
import type { NodeRegistryNode } from "@/types/node-registry";

interface WorkflowValidationSnapshot {
  nodes: ReturnType<typeof useWorkflowStore.getState>["nodes"];
  edges: ReturnType<typeof useWorkflowStore.getState>["edges"];
  nodeConfigs: ReturnType<typeof useWorkflowStore.getState>["nodeConfigs"];
  uploadedFiles: ReturnType<typeof useWorkflowStore.getState>["uploadedFiles"];
}

export interface ValidationResult {
  isValid: boolean;
  error?: string;
}

export interface UseWorkflowValidationResult {
  blockingErrors: WorkflowValidationIssue[];
  warnings: WorkflowValidationIssue[];
  isExecutable: boolean;
  errorCountByNode: Record<string, number>;
  warningCountByNode: Record<string, number>;
  validateConnection: (sourceNodeType: string, targetNodeType: string) => ValidationResult;
}

export function useWorkflowValidation(): UseWorkflowValidationResult {
  const { t } = useTranslation("workflows");
  const nodes = useWorkflowStore((state) => state.nodes);
  const edges = useWorkflowStore((state) => state.edges);
  const nodeConfigs = useWorkflowStore((state) => state.nodeConfigs);
  const uploadedFiles = useWorkflowStore((state) => state.uploadedFiles);
  const registryNodes = useWorkflowStore((state) => state.nodeRegistry.nodes);
  const connectionRules = useWorkflowStore((state) => state.nodeRegistry.connection_rules);
  const engineStatuses = useUIStore((state) => state.engineStatuses);

  const [snapshot, setSnapshot] = useState<WorkflowValidationSnapshot>({
    nodes,
    edges,
    nodeConfigs,
    uploadedFiles
  });

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSnapshot({
        nodes,
        edges,
        nodeConfigs,
        uploadedFiles
      });
    }, 300);

    return () => {
      window.clearTimeout(timer);
    };
  }, [edges, nodeConfigs, nodes, uploadedFiles]);

  const unavailableEngines = useMemo(
    () =>
      Object.entries(engineStatuses)
        .filter(([, status]) => status === "unavailable")
        .map(([name]) => name),
    [engineStatuses]
  );

  const validation = useMemo(
    () =>
      validateWorkflowDefinition({
        ...snapshot,
        registryNodes,
        connectionRules,
        unavailableEngines,
        t
      }),
    [connectionRules, registryNodes, snapshot, t, unavailableEngines]
  );

  const errorCountByNode = useMemo(() => {
    return validation.issues.reduce<Record<string, number>>((acc, issue) => {
      if (!issue.nodeId || issue.severity !== "blocking") {
        return acc;
      }
      acc[issue.nodeId] = (acc[issue.nodeId] ?? 0) + 1;
      return acc;
    }, {});
  }, [validation.issues]);

  const warningCountByNode = useMemo(() => {
    return validation.issues.reduce<Record<string, number>>((acc, issue) => {
      if (!issue.nodeId || issue.severity !== "warning") {
        return acc;
      }
      acc[issue.nodeId] = (acc[issue.nodeId] ?? 0) + 1;
      return acc;
    }, {});
  }, [validation.issues]);

  const validateConnection = (sourceNodeType: string, targetNodeType: string): ValidationResult => {
    const nodeRegistry = useWorkflowStore.getState().nodeRegistry;
    const sourceDef = nodeRegistry.nodes.find((node) => node.node_type === sourceNodeType) as
      | NodeRegistryNode
      | undefined;
    const targetDef = nodeRegistry.nodes.find((node) => node.node_type === targetNodeType) as
      | NodeRegistryNode
      | undefined;

    if (!sourceDef || !targetDef) {
      return { isValid: false, error: t("editorText.unknownNodeType") };
    }

    // Extract category from node type (e.g., "input/file" -> "input")
    const sourceCategory = sourceNodeType.split("/")[0] ?? sourceNodeType;
    const targetCategory = targetNodeType.split("/")[0] ?? targetNodeType;

    // Check target node restriction: simple_only can only accept input from 'input' category
    if (targetDef.pipeline_restriction === "simple_only") {
      if (sourceCategory !== "input") {
        return {
          isValid: false,
          error: t("editorText.inputOnlyNode", { name: targetDef.display_name })
        };
      }
    }

    // Check source node restriction: simple_only can only output to 'end' category
    if (sourceDef.pipeline_restriction === "simple_only") {
      if (targetCategory !== "end") {
        return {
          isValid: false,
          error: t("editorText.endOnlyOutput", { name: sourceDef.display_name })
        };
      }
    }

    // Check connection rules
    const allowedConnections = connectionRules.find(
      (rule) => rule.from_category === sourceCategory
    );

    if (allowedConnections && !allowedConnections.to_categories.includes(targetCategory)) {
      return {
        isValid: false,
        error: t("editorText.cannotConnect", { source: sourceDef.display_name, target: targetDef.display_name })
      };
    }

    return { isValid: true };
  };

  return {
    blockingErrors: validation.blockingErrors,
    warnings: validation.warnings,
    isExecutable: validation.isExecutable,
    errorCountByNode,
    warningCountByNode,
    validateConnection
  };
}
