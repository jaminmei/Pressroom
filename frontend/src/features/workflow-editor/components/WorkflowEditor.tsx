import { useEffect } from "react";

import Canvas from "@/features/workflow-editor/components/Canvas";
import NodePanel from "@/features/workflow-editor/components/NodePanel";
import { useNodeLevelRun } from "@/features/workflow-editor/hooks/useNodeLevelRun";
import { useNodeLevelRerun } from "@/features/workflow-editor/hooks/useNodeLevelRerun";
import {
  beginTaskOperation,
  finishTaskOperation,
  isTaskOperationCurrent,
  useTaskExecutionStore,
  type TaskNodeVisualStatus
} from "@/features/task-execution/store";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { useTaskOrchestration } from "@/hooks/useTaskOrchestration";
import { usePermission } from "@/hooks/usePermission";
import { getWorkflowApiUsageTrace } from "@/services/apiAccessApi";
import { executePersistedWorkflow } from "@/services/workflowApi";
import { useUIStore } from "@/stores/uiStore";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";
import { captureWorkspaceContext, isWorkspaceContextCurrent } from "@/stores/workspaceStore";

interface WorkflowEditorProps {
  traceRunId?: string | null;
  traceWorkflowId?: string | null;
  readOnlyTrace?: boolean;
}

function mapTraceStatus(status: string): "pending" | "running" | "completed" | "failed" | "cancelled" {
  if (status === "running" || status === "pending" || status === "failed" || status === "cancelled") return status;
  return status === "succeeded" || status === "partial_completed" ? "completed" : "completed";
}

function mapNodeStatus(status: string): TaskNodeVisualStatus {
  if (
    status === "pending" ||
    status === "running" ||
    status === "completed" ||
    status === "failed" ||
    status === "cancelled" ||
    status === "skipped"
  ) {
    return status;
  }
  return "pending";
}

function hydrateTraceWorkflow(workflow: NonNullable<Awaited<ReturnType<typeof getWorkflowApiUsageTrace>>["workflow"]>) {
  const { nodeRegistry } = useWorkflowStore.getState();
  const rawNodes = Array.isArray(workflow.nodes) ? workflow.nodes : [];
  const rawConnections = Array.isArray(workflow.connections)
    ? workflow.connections
    : Array.isArray(workflow.edges)
      ? workflow.edges
      : [];

  const nodes: WorkflowNode[] = rawNodes.map((node) => {
    const id = String(node.id ?? "");
    const nodeType = String(node.type ?? "");
    const metadata = nodeRegistry.nodes.find((item) => item.node_type === nodeType);
    const parts = nodeType.split("/");
    const defaultLabel = parts[parts.length - 1]?.toUpperCase() || nodeType || id;
    const position = node.position as { x?: number; y?: number } | undefined;
    return {
      id,
      type: nodeType,
      data: {
        label: metadata?.display_name ?? defaultLabel,
        config: (node.config as Record<string, unknown>) ?? {},
        configSchema: metadata?.config_schema ?? { type: "object", properties: {} },
        inputTypes: metadata?.input_types,
        outputTypes: metadata?.output_types,
        maxInputs: metadata?.max_inputs,
        inputPorts: metadata?.input_ports,
      },
      position: position && typeof position.x === "number" && typeof position.y === "number"
        ? { x: position.x, y: position.y }
        : undefined,
    };
  });

  const edges: WorkflowEdge[] = rawConnections.map((edge, index) => {
    const source = String(edge.source ?? "");
    const target = String(edge.target ?? "");
    const sourcePort = edge.source_port ?? edge.sourceHandle;
    const targetPort = edge.target_port ?? edge.targetHandle;
    return {
      id: String(edge.id ?? `e-${source}-${target}-${index}`),
      source,
      target,
      sourceHandle: sourcePort ? `output-${String(sourcePort)}` : undefined,
      targetHandle: targetPort ? `input-${String(targetPort)}` : undefined,
    };
  });

  const nodeConfigs: Record<string, Record<string, unknown>> = {};
  rawNodes.forEach((node) => {
    const id = String(node.id ?? "");
    if (id) nodeConfigs[id] = (node.config as Record<string, unknown>) ?? {};
  });

  useWorkflowStore.setState((state) => ({
    canvasResetKey: state.canvasResetKey + 1,
    nodes,
    edges,
    nodeConfigs,
    uploadedFiles: {},
    selectedNodeId: null,
  }));
}

export default function WorkflowEditor({ traceRunId = null, traceWorkflowId = null, readOnlyTrace = false }: WorkflowEditorProps) {
  const { executeWorkflow, cancelTask, manualReconnect, taskStatus } = useTaskOrchestration();
  const { can, role } = usePermission();
  const canEdit = (role === null || can("workflow.edit_draft")) && !readOnlyTrace;
  const canRun = (role === null || can("workflow.run")) && !readOnlyTrace && (canEdit || Boolean(traceWorkflowId));
  const { runNode } = useNodeLevelRun();
  const { rerunNodeById } = useNodeLevelRerun();

  useEffect(() => {
    if (!canEdit) return;
    const listener = (event: Event) => {
      const customEvent = event as CustomEvent<{ nodeId?: string }>;
      const nodeId = customEvent.detail?.nodeId;
      if (!nodeId) {
        return;
      }
      void runNode(nodeId);
    };
    window.addEventListener("workflow:node-run-request", listener as EventListener);
    return () => {
      window.removeEventListener("workflow:node-run-request", listener as EventListener);
    };
  }, [canEdit, runNode]);

  useEffect(() => {
    if (!canEdit) return;
    const listener = (event: Event) => {
      const customEvent = event as CustomEvent<{ nodeId?: string }>;
      const nodeId = customEvent.detail?.nodeId;
      if (!nodeId) {
        return;
      }
      void rerunNodeById(nodeId);
    };
    window.addEventListener("workflow:node-rerun-request", listener as EventListener);
    return () => {
      window.removeEventListener("workflow:node-rerun-request", listener as EventListener);
    };
  }, [canEdit, rerunNodeById]);

  const executeAllowedWorkflow = async (options?: { runName?: string }) => {
    if (!canRun) return { ok: false, errors: [] };
    if (canEdit) return executeWorkflow(options);
    if (!traceWorkflowId) return { ok: false, errors: [] };
    const workspaceToken = captureWorkspaceContext();
    const operationId = beginTaskOperation();
    const isCurrentOperation = () =>
      isWorkspaceContextCurrent(workspaceToken) && isTaskOperationCurrent(operationId);
    useTaskExecutionStore.getState().setTaskStatus("pending");
    try {
      const task = await executePersistedWorkflow(traceWorkflowId, options?.runName);
      if (!isCurrentOperation()) {
        return { ok: false, errors: [], errorMessage: "Workspace changed while creating the task." };
      }
      useTaskExecutionStore.getState().setTaskId(task.task_id);
      useTaskExecutionStore.getState().setTaskStatus(task.status);
      if (task.status === "completed" || task.status === "failed" || task.status === "cancelled") {
        finishTaskOperation(operationId);
      }
      return { ok: true, taskId: task.task_id, errors: [] };
    } catch {
      if (isCurrentOperation()) finishTaskOperation(operationId);
      return { ok: false, errors: [], errorMessage: "Workflow execution failed." };
    }
  };

  useEffect(() => {
    if (!readOnlyTrace || !traceRunId || !traceWorkflowId) {
      const executionStore = useTaskExecutionStore.getState();
      if (executionStore.traceMode) {
        executionStore.reset();
      } else {
        executionStore.setTraceContext({ enabled: false });
      }
      return;
    }

    const workflowIdForTrace = traceWorkflowId;
    const runIdForTrace = traceRunId;
    const workspaceToken = captureWorkspaceContext();
    let active = true;
    async function loadTrace() {
      try {
        const trace = await getWorkflowApiUsageTrace(workflowIdForTrace, runIdForTrace);
        if (!active || !isWorkspaceContextCurrent(workspaceToken)) return;
        if (trace.workflow) {
          hydrateTraceWorkflow(trace.workflow);
        }
        const nodeStatuses: Record<string, TaskNodeVisualStatus> = {};
        trace.node_status.forEach((item) => {
          nodeStatuses[item.node_id] = mapNodeStatus(item.status);
        });
        useTaskExecutionStore.setState((state) => ({
          ...state,
          currentTaskId: trace.workflow_run_id,
          taskStatus: mapTraceStatus(trace.status),
          nodeStatuses,
          nodeProgress: {},
          nodeErrors: Object.fromEntries(
            trace.node_status
              .filter((item) => item.error)
              .map((item) => [item.node_id, item.error ?? undefined]),
          ),
          progress: null,
          eventLogs: [
            {
              id: `trace_${trace.workflow_run_id}`,
              timestamp: new Date().toISOString(),
              level: "info",
              message: `Loaded API trace ${trace.workflow_run_id}`,
            },
          ],
          traceMode: true,
          traceInputMetadata: trace.input_metadata ?? null,
        }));
        useUIStore.getState().setRightPanelTab("result");
      } catch {
        if (!active || !isWorkspaceContextCurrent(workspaceToken)) return;
        useTaskExecutionStore.getState().appendEventLog("Failed to load API trace", "error");
      }
    }

    void loadTrace();
    return () => {
      active = false;
    };
  }, [readOnlyTrace, traceRunId, traceWorkflowId]);

  return (
    <section className="workflow-editor-page" data-testid="workflow-editor-page">
      <div className="workflow-editor-layout">
        <Canvas
          onCancelTask={cancelTask}
          onManualReconnect={manualReconnect}
          onExecuteWorkflow={executeAllowedWorkflow}
          taskStatus={taskStatus}
          readOnlyTrace={readOnlyTrace || !canEdit}
          runOnly={canRun && !canEdit}
        />
        <NodePanel onCancelTask={cancelTask} readOnlyTrace={readOnlyTrace || !canEdit} />
      </div>
    </section>
  );
}
