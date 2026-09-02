import { useCallback, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { useResultStore } from "@/features/result/store";
import { useWebSocket } from "@/features/task-execution/hooks/useWebSocket";
import {
  beginTaskOperation,
  finishTaskOperation,
  isTaskOperationCurrent,
  useTaskExecutionStore,
  type TaskNodeVisualStatus
} from "@/features/task-execution/store";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import {
  type WorkflowValidationCode,
  validateWorkflowDefinition
} from "@/features/workflow-editor/utils/workflowValidator";
import { buildWorkflowExecutionPayload } from "@/features/workflow-editor/utils/workflowBuilder";
import { getTaskResults, getTaskStatus } from "@/services/taskApi";
import {
  buildWorkflowTaskFormData,
  cancelWorkflowTask,
  createWorkflowTask
} from "@/services/workflowApi";
import type { TaskStatus } from "@/types/task";
import { computeDagFingerprint } from "@/utils/dagFingerprint";
import { mapNodeVisualStatus } from "@/utils/nodeStatus";
import { captureWorkspaceContext, isWorkspaceContextCurrent } from "@/stores/workspaceStore";

type ExecutionErrorCode = WorkflowValidationCode | "backend_validation" | "request_failed" | "workspace_context_changed";

export interface WorkflowExecutionError {
  code: ExecutionErrorCode;
  message: string;
  nodeId?: string;
}

export interface ExecuteWorkflowResult {
  ok: boolean;
  taskId?: string;
  errors: WorkflowExecutionError[];
  // Keep compatibility with callers that still read scalar error fields.
  errorMessage?: string;
  errorNodeId?: string;
}

export interface ExecuteWorkflowOptions {
  runName?: string;
}

const FALLBACK_EXECUTION_ERROR = "Workflow execution failed. Check the configuration and try again.";

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }

  return value as Record<string, unknown>;
}

function parseExecutionError(error: unknown, fallbackMessage = FALLBACK_EXECUTION_ERROR): WorkflowExecutionError {
  const errorRecord = asRecord(error);
  const responseRecord = asRecord(errorRecord?.response);
  const responseStatus = typeof responseRecord?.status === "number" ? responseRecord.status : null;

  let message: string | undefined;
  let nodeId: string | undefined;

  const responseData = asRecord(responseRecord?.data);
  const payloadError = asRecord(responseData?.error) ?? responseData;

  if (payloadError) {
    if (typeof payloadError.message === "string" && payloadError.message.trim().length > 0) {
      message = payloadError.message;
    }

    const details = asRecord(payloadError.details);
    if (typeof details?.node_id === "string") {
      nodeId = details.node_id;
    } else if (typeof details?.nodeId === "string") {
      nodeId = details.nodeId;
    } else if (typeof payloadError.node_id === "string") {
      nodeId = payloadError.node_id;
    } else if (typeof payloadError.nodeId === "string") {
      nodeId = payloadError.nodeId;
    }
  }

  if (
    !message &&
    typeof errorRecord?.message === "string" &&
    errorRecord.message.trim().length > 0
  ) {
    message = errorRecord.message;
  }

  return {
    code: responseStatus === 400 ? "backend_validation" : "request_failed",
    message: message ?? fallbackMessage,
    nodeId
  };
}

function parseBackendValidationErrors(error: unknown, fallbackMessage = FALLBACK_EXECUTION_ERROR): WorkflowExecutionError[] {
  const errorRecord = asRecord(error);
  const responseRecord = asRecord(errorRecord?.response);
  const responseStatus = typeof responseRecord?.status === "number" ? responseRecord.status : null;
  const responseData = asRecord(responseRecord?.data);
  const validation = asRecord(responseData?.validation);
  const errorItems = Array.isArray(validation?.errors) ? validation?.errors : [];

  if (responseStatus !== 400 || errorItems.length === 0) {
    return [];
  }

  const parsedErrors = errorItems
    .map((item): WorkflowExecutionError | null => {
      const errorItem = asRecord(item);
      if (!errorItem) {
        return null;
      }

      const message =
        typeof errorItem.message === "string" ? errorItem.message : fallbackMessage;
      const details = asRecord(errorItem.details);
      const nodeId =
        typeof details?.node_id === "string"
          ? details.node_id
          : typeof details?.nodeId === "string"
            ? details.nodeId
            : undefined;

      return {
        code: "backend_validation",
        message,
        nodeId
      };
    })
    .filter((error): error is WorkflowExecutionError => Boolean(error));

  return parsedErrors;
}

export function useTaskOrchestration() {
  const { t } = useTranslation(["workflows", "common"]);
  const nodes = useWorkflowStore((state) => state.nodes);
  const edges = useWorkflowStore((state) => state.edges);
  const nodeConfigs = useWorkflowStore((state) => state.nodeConfigs);
  const uploadedFiles = useWorkflowStore((state) => state.uploadedFiles);

  const currentTaskId = useTaskExecutionStore((state) => state.currentTaskId);
  const taskStatus = useTaskExecutionStore((state) => state.taskStatus);
  const setTaskId = useTaskExecutionStore((state) => state.setTaskId);
  const setTaskStatus = useTaskExecutionStore((state) => state.setTaskStatus);
  const setProgress = useTaskExecutionStore((state) => state.setProgress);
  const updateNodeStatus = useTaskExecutionStore((state) => state.updateNodeStatus);
  const batchUpdateNodeStatuses = useTaskExecutionStore((state) => state.batchUpdateNodeStatuses);
  const clearEventLogs = useTaskExecutionStore((state) => state.clearEventLogs);
  const appendEventLog = useTaskExecutionStore((state) => state.appendEventLog);
  const setSendCommandFn = useTaskExecutionStore((state) => state.setSendCommandFn);
  const setLastRunMeta = useTaskExecutionStore((state) => state.setLastRunMeta);

  const setTaskResults = useResultStore((state) => state.setTaskResults);
  const clearResults = useResultStore((state) => state.clearResults);

  const handleTaskFinished = useCallback(
    (taskId: string, status: TaskStatus) => {
      const workspaceToken = captureWorkspaceContext();
      const operationId = useTaskExecutionStore.getState().activeOperationId;
      const isCurrentTask = () =>
        isWorkspaceContextCurrent(workspaceToken) &&
        useTaskExecutionStore.getState().currentTaskId === taskId;
      if (!isCurrentTask()) return;
      setTaskStatus(status);
      appendEventLog(
        t("editorText.taskFinished", { taskId, status: t(`common:statuses.${status}`, { defaultValue: status }) }),
        status === "failed" ? "error" : "info"
      );

      // Sync all node statuses from backend to catch any missed SSE events
      void getTaskStatus(taskId)
        .then((snapshot) => {
          if (!isCurrentTask()) return;
          const nodeStatuses = Array.isArray(snapshot.node_status)
            ? snapshot.node_status
            : snapshot.node_states
              ? Object.values(snapshot.node_states)
              : [];
          if (nodeStatuses.length > 0) {
            const statusPatch: Record<string, TaskNodeVisualStatus> = {};
            nodeStatuses.forEach((node) => {
              const mapped = mapNodeVisualStatus(node.status);
              if (mapped) {
                statusPatch[node.node_id] = mapped;
              }
            });
            batchUpdateNodeStatuses(statusPatch);
          }
        })
        .catch(() => {
          // Ignore — best-effort sync
        });

      if (status !== "completed") {
        if (operationId) finishTaskOperation(operationId);
        return;
      }

      void getTaskResults(taskId)
        .then((response) => {
          if (!isCurrentTask() || response.task_id !== taskId) return;
          setTaskResults(response.task_id, response.results);
        })
        .catch(() => {
          if (isCurrentTask()) appendEventLog(t("editorText.resultLoadRefresh"), "error");
        });
      if (operationId) finishTaskOperation(operationId);
    },
    [appendEventLog, batchUpdateNodeStatuses, setTaskResults, setTaskStatus, t]
  );

  const sseEnabled = useMemo(
    () => Boolean(currentTaskId) && (taskStatus === "pending" || taskStatus === "running"),
    [currentTaskId, taskStatus]
  );
  const { isConnected, manualReconnect, sendCommand } = useWebSocket({
    taskId: currentTaskId,
    enabled: sseEnabled,
    onTaskFinished: handleTaskFinished
  });

  useEffect(() => {
    setSendCommandFn(sendCommand);
    return () => {
      if (useTaskExecutionStore.getState().sendCommandFn === sendCommand) {
        useTaskExecutionStore.getState().setSendCommandFn(null);
      }
    };
  }, [sendCommand, setSendCommandFn]);

  const executeWorkflow = useCallback(async (options?: ExecuteWorkflowOptions): Promise<ExecuteWorkflowResult> => {
    const validation = validateWorkflowDefinition({
      nodes,
      edges,
      nodeConfigs,
      uploadedFiles,
      registryNodes: useWorkflowStore.getState().nodeRegistry.nodes,
      connectionRules: useWorkflowStore.getState().nodeRegistry.connection_rules,
      t
    });

    if (!validation.isExecutable) {
      return {
        ok: false,
        errors: validation.blockingErrors.map((issue) => ({
          code: issue.code,
          message: issue.message,
          nodeId: issue.nodeId
        }))
      };
    }

    const { workflow, orderedFiles } = buildWorkflowExecutionPayload({
      nodes,
      edges,
      nodeConfigs,
      uploadedFiles
    });
    const formData = buildWorkflowTaskFormData(workflow, orderedFiles);
    const workspaceToken = captureWorkspaceContext();
    const operationId = beginTaskOperation();
    const isCurrentOperation = () =>
      isWorkspaceContextCurrent(workspaceToken) && isTaskOperationCurrent(operationId);

    // Add run_name if provided
    if (options?.runName) {
      formData.append("run_name", options.runName);
    }

    clearResults();
    clearEventLogs();
    appendEventLog(t("editorText.creatingTask"));
    useTaskExecutionStore.setState((state) => ({
      ...state,
      nodeStatuses: {},
      nodeProgress: {},
      nodeErrors: {},
      progress: null,
      wsConnected: false,
      wsWarning: null,
      manualReconnectAvailable: false,
      executionStartedAt: null
    }));

    // Set initial progress — all nodes start pending, backend will report completions
    setTaskStatus("pending");
    setProgress({
      total_nodes: nodes.length,
      completed_nodes: 0,
      failed_nodes: 0,
      pending_nodes: nodes.length,
      current_node: null,
      percentage: 0
    });

    try {
      const task = await createWorkflowTask(formData);
      if (!isCurrentOperation()) {
        return {
          ok: false,
          errors: [{ code: "workspace_context_changed", message: t("editorText.workspaceChangedCreating") }]
        };
      }
      setTaskId(task.task_id);
      setTaskStatus(task.status);

      const dagFingerprint = computeDagFingerprint(
        nodes.map((n) => ({ id: n.id, type: n.type })),
        edges.map((e) => ({ source: e.source, target: e.target, sourceHandle: e.sourceHandle, targetHandle: e.targetHandle })),
        nodeConfigs
      );
      setLastRunMeta(dagFingerprint, task.input_files ?? null);

      // Set node statuses AFTER API call - input nodes are completed, others pending
      // This ensures the status is set after the task is created
      nodes.forEach((node) => {
        if (node.type.startsWith("input/")) {
          updateNodeStatus(node.id, "completed");
        } else {
          updateNodeStatus(node.id, "pending");
        }
      });

      if (task.status === "completed") {
        try {
          const response = await getTaskResults(task.task_id);
          if (!isCurrentOperation() || response.task_id !== task.task_id) {
            return {
              ok: false,
              errors: [{ code: "workspace_context_changed", message: t("editorText.workspaceChangedLoadingResults") }]
            };
          }
          setTaskResults(response.task_id, response.results);
        } catch {
          if (isCurrentOperation()) {
            appendEventLog(t("editorText.resultLoadRefresh"), "error");
          }
        } finally {
          if (isCurrentOperation()) finishTaskOperation(operationId);
        }
      } else if (task.status === "failed" || task.status === "cancelled") {
        finishTaskOperation(operationId);
      }

      appendEventLog(t("editorText.taskCreated", { taskId: task.task_id, status: t(`common:statuses.${task.status}`, { defaultValue: task.status }) }));
      return {
        ok: true,
        taskId: task.task_id,
        errors: []
      };
    } catch (error: unknown) {
      if (!isCurrentOperation()) {
        return {
          ok: false,
          errors: [{ code: "workspace_context_changed", message: t("editorText.workspaceChangedCreating") }]
        };
      }
      const fallbackError = t("editorText.executionFallbackError");
      const backendValidationErrors = parseBackendValidationErrors(error, fallbackError);
      const parsedErrors =
        backendValidationErrors.length > 0 ? backendValidationErrors : [parseExecutionError(error, fallbackError)];
      const firstError = parsedErrors[0];

      if (firstError?.nodeId) {
        updateNodeStatus(firstError.nodeId, "failed", firstError.message);
      }
      setTaskStatus("failed");
      appendEventLog(firstError?.message ?? fallbackError, "error");
      finishTaskOperation(operationId);
      return {
        ok: false,
        errors: parsedErrors,
        errorMessage: firstError?.message,
        errorNodeId: firstError?.nodeId
      };
    }
  }, [
    clearResults,
    clearEventLogs,
    edges,
    nodeConfigs,
    nodes,
    appendEventLog,
    setLastRunMeta,
    setProgress,
    setTaskId,
    setTaskResults,
    setTaskStatus,
    updateNodeStatus,
    uploadedFiles,
    t
  ]);

  const cancelTask = useCallback(async () => {
    if (!currentTaskId) {
      return;
    }

    const workspaceToken = captureWorkspaceContext();
    const operationId = useTaskExecutionStore.getState().activeOperationId;
    await cancelWorkflowTask(currentTaskId);
    if (
      !isWorkspaceContextCurrent(workspaceToken) ||
      useTaskExecutionStore.getState().currentTaskId !== currentTaskId
    ) return;
    setTaskStatus("cancelled");
    appendEventLog(t("editorText.taskCancelled", { taskId: currentTaskId }), "warning");
    if (operationId) finishTaskOperation(operationId);
  }, [appendEventLog, currentTaskId, setTaskStatus, t]);

  return {
    executeWorkflow,
    cancelTask,
    manualReconnect,
    isConnected,
    sendCommand,
    currentTaskId,
    taskStatus
  };
}
