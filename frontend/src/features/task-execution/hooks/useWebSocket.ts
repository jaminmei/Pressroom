import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { useLiveStatusStore } from "@/features/task-execution/liveStatusStore";
import {
  finishTaskOperation,
  useTaskExecutionStore,
  type TaskNodeVisualStatus
} from "@/features/task-execution/store";
import { buildWorkspaceScopedUrl } from "@/services/workspaceTransport";
import { getTaskStatus } from "@/services/taskApi";
import type { TaskStatus } from "@/types/task";
import {
  captureWorkspaceContext,
  isWorkspaceContextCurrent,
  useWorkspaceStore
} from "@/stores/workspaceStore";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface UseWebSocketOptions {
  taskId: string | null;
  enabled?: boolean;
  onTaskFinished?: (taskId: string, status: TaskStatus) => void;
}

interface ServerMessage {
  type: "connected" | "node_event" | "workflow_state" | "error" | "ping" | "pong";
  data: Record<string, unknown>;
}

interface ClientCommand {
  command: string;
  data?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const terminalStatuses = new Set<TaskStatus>(["completed", "failed", "cancelled"]);
const maxReconnectAttempts = 5;
const baseReconnectDelayMs = 1000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseMessage(raw: string): ServerMessage | null {
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (typeof parsed.type === "string" && isObject(parsed.data)) {
      return parsed as unknown as ServerMessage;
    }
    // Allow messages where data may be missing or non-object (e.g. error messages)
    if (typeof parsed.type === "string") {
      return { type: parsed.type as ServerMessage["type"], data: (parsed.data as Record<string, unknown>) ?? {} };
    }
    return null;
  } catch {
    return null;
  }
}

function resolveNodeStatuses(snapshot: {
  node_status?: Array<{ node_id: string; status: unknown }>;
  node_states?: Record<string, { node_id: string; status: unknown }>;
}): Array<{ node_id: string; status: unknown }> {
  if (Array.isArray(snapshot.node_status) && snapshot.node_status.length > 0) {
    return snapshot.node_status;
  }
  if (snapshot.node_states) {
    return Object.values(snapshot.node_states);
  }
  return [];
}

function mapNodeExecutionStatusToVisual(status: unknown): TaskNodeVisualStatus | null {
  if (status === "pending") return "pending";
  if (status === "running") return "running";
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  if (status === "cancelled") return "cancelled";
  if (status === "skipped") return "skipped";
  if (status === "awaiting_input" || status === "awaiting_user_input") return "awaiting_input";
  return null;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useWebSocket({ taskId, enabled = true, onTaskFinished }: UseWebSocketOptions) {
  const { t } = useTranslation(["workflows", "common"]);
  const contextGeneration = useWorkspaceStore((state) => state.contextGeneration);
  const setTaskId = useTaskExecutionStore((state) => state.setTaskId);
  const setTaskStatus = useTaskExecutionStore((state) => state.setTaskStatus);
  const setWsConnected = useTaskExecutionStore((state) => state.setWsConnected);
  const setProgress = useTaskExecutionStore((state) => state.setProgress);
  const updateNodeStatus = useTaskExecutionStore((state) => state.updateNodeStatus);
  const batchUpdateNodeStatuses = useTaskExecutionStore((state) => state.batchUpdateNodeStatuses);
  const appendEventLog = useTaskExecutionStore((state) => state.appendEventLog);
  const setBlockSelectionRequest = useTaskExecutionStore((state) => state.setBlockSelectionRequest);
  const setWsWarning = useTaskExecutionStore((state) => state.setWsWarning);
  const setManualReconnectAvailable = useTaskExecutionStore((state) => state.setManualReconnectAvailable);
  const setWorkflowPaused = useTaskExecutionStore((state) => state.setWorkflowPaused);

  // Refs -------------------------------------------------------------------
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptRef = useRef(0);
  const lastSeqRef = useRef(0);
  const stoppedRef = useRef(false);
  const connectRef = useRef<(() => void) | null>(null);
  const syncTaskStatusRef = useRef<(() => Promise<boolean>) | null>(null);
  const closeStreamRef = useRef<(() => void) | null>(null);
  const cleanupReconnectTimerRef = useRef<(() => void) | null>(null);

  // Effect -----------------------------------------------------------------

  useEffect(() => {
    stoppedRef.current = false;

    if (!enabled || !taskId) {
      return;
    }

    reconnectAttemptRef.current = 0;
    lastSeqRef.current = 0;
    const terminalProcessedRef = new Set<string>();
    const workspaceToken = captureWorkspaceContext();
    const operationId = useTaskExecutionStore.getState().activeOperationId;
    const isCurrentTaskContext = () =>
      isWorkspaceContextCurrent(workspaceToken) &&
      useTaskExecutionStore.getState().currentTaskId === taskId;

    // ----- Utilities -------------------------------------------------------

    const cleanupReconnectTimer = () => {
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    const closeStream = () => {
      if (wsRef.current) {
        // Prevent onclose from triggering reconnect
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.onmessage = null;
        wsRef.current.close();
        wsRef.current = null;
      }
      if (isCurrentTaskContext()) setWsConnected(false);
    };

    const syncTaskStatus = async (): Promise<boolean> => {
      if (!isCurrentTaskContext()) return false;
      try {
        const snapshot = await getTaskStatus(taskId);
        if (!isCurrentTaskContext()) return false;
        setTaskStatus(snapshot.status);
        if (snapshot.progress) {
          setProgress(snapshot.progress);
        }

        const nodeStatuses = resolveNodeStatuses(snapshot);
        if (nodeStatuses.length > 0) {
          const currentStatuses = useTaskExecutionStore.getState().nodeStatuses;
          const statusPatch: Record<string, TaskNodeVisualStatus> = {};
          nodeStatuses.forEach((node) => {
            const mapped = mapNodeExecutionStatusToVisual(node.status);
            if (!mapped) return;
            const currentStatus = currentStatuses[node.node_id];
            if (currentStatus === "completed" && mapped === "pending") return;
            statusPatch[node.node_id] = mapped;
          });
          batchUpdateNodeStatuses(statusPatch);
        }

        return true;
      } catch {
        return false;
      }
    };

    const finishTask = (status: TaskStatus) => {
      if (terminalStatuses.has(status) && isCurrentTaskContext()) {
        setTaskStatus(status);
        setBlockSelectionRequest(null);
        useLiveStatusStore.getState().patchStatus(taskId, status);
        closeStream();
        cleanupReconnectTimer();
        setWsWarning(null);
        setManualReconnectAvailable(false);
        onTaskFinished?.(taskId, status);
        if (operationId) finishTaskOperation(operationId);
      }
    };

    const sendCommand = (command: string, data?: Record<string, unknown>) => {
      if (!isCurrentTaskContext()) return;
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const msg: ClientCommand = { command, data: data ?? {} };
      ws.send(JSON.stringify(msg));
    };

    // ----- Event handlers --------------------------------------------------

    const handleConnected = (data: Record<string, unknown>) => {
      if (!isCurrentTaskContext()) return;
      const reportedTaskId = typeof data.task_id === "string" ? data.task_id : taskId;
      if (reportedTaskId !== taskId) {
        stoppedRef.current = true;
        appendEventLog(
          t("editorText.wsTaskMismatch", { expected: taskId, received: reportedTaskId }),
          "error"
        );
        closeStream();
        cleanupReconnectTimer();
        return;
      }
      setTaskId(taskId);
      setWsConnected(true);

      // On (re)connection, send catch-up command so server replays missed events
      sendCommand("catch_up", { last_seq: lastSeqRef.current });

      appendEventLog(t("editorText.wsBound", { taskId }));
    };

    const handleNodeEvent = (data: Record<string, unknown>) => {
      if (!isCurrentTaskContext()) return;
      const nodeId = typeof data.node_id === "string" ? data.node_id : null;
      if (!nodeId) return;

      const eventType = typeof data.event_type === "string" ? data.event_type : "";
      const seq = typeof data.sequence === "number" ? data.sequence : undefined;

      // Track sequence for catch-up
      if (typeof seq === "number" && Number.isFinite(seq) && seq >= 0) {
        lastSeqRef.current = Math.max(lastSeqRef.current, Math.floor(seq));
      }

      switch (eventType) {
        case "started": {
          setTaskStatus("running");
          updateNodeStatus(nodeId, "running");
          appendEventLog(t("editorText.nodeStarted", { nodeId }));
          break;
        }
        case "completed": {
          updateNodeStatus(nodeId, "completed");
          appendEventLog(t("editorText.nodeCompleted", { nodeId }));
          if (terminalProcessedRef.has(nodeId)) break;
          terminalProcessedRef.add(nodeId);
          const previous = useTaskExecutionStore.getState().progress;
          if (previous) {
            const completedNodes = Math.min(previous.completed_nodes + 1, previous.total_nodes);
            const pendingNodes = Math.max(previous.pending_nodes - 1, 0);
            const percentage =
              previous.total_nodes > 0 ? Math.round((completedNodes / previous.total_nodes) * 100) : 0;
            setProgress({
              ...previous,
              completed_nodes: completedNodes,
              pending_nodes: pendingNodes,
              percentage
            });
          }
          break;
        }
        case "failed": {
          const errorData = isObject(data.error) ? data.error : {};
          const message = typeof errorData.message === "string" ? errorData.message : undefined;
          updateNodeStatus(nodeId, "failed", message);
          appendEventLog(message ? t("editorText.nodeFailedWithMessage", { nodeId, message }) : t("editorText.nodeFailed", { nodeId }), "error");
          if (terminalProcessedRef.has(nodeId)) break;
          terminalProcessedRef.add(nodeId);
          const previous = useTaskExecutionStore.getState().progress;
          if (previous) {
            const failedNodes = previous.failed_nodes + 1;
            const pendingNodes = Math.max(previous.pending_nodes - 1, 0);
            const doneNodes = previous.completed_nodes + failedNodes;
            const percentage =
              previous.total_nodes > 0 ? Math.round((doneNodes / previous.total_nodes) * 100) : 0;
            setProgress({
              ...previous,
              failed_nodes: failedNodes,
              pending_nodes: pendingNodes,
              percentage
            });
          }
          break;
        }
        case "skipped": {
          updateNodeStatus(nodeId, "skipped");
          appendEventLog(t("editorText.nodeSkipped", { nodeId }), "warning");
          if (terminalProcessedRef.has(nodeId)) break;
          terminalProcessedRef.add(nodeId);
          const previous = useTaskExecutionStore.getState().progress;
          if (previous) {
            const pendingNodes = Math.max(previous.pending_nodes - 1, 0);
            const doneNodes = previous.completed_nodes + previous.failed_nodes + 1;
            const percentage =
              previous.total_nodes > 0 ? Math.round((doneNodes / previous.total_nodes) * 100) : 0;
            setProgress({
              ...previous,
              pending_nodes: pendingNodes,
              percentage
            });
          }
          break;
        }
        default:
          break;
      }
    };

    const handleWorkflowState = (data: Record<string, unknown>) => {
      if (!isCurrentTaskContext()) return;
      const status = typeof data.status === "string" ? data.status : "";

      if (status === "paused") {
        setWsWarning(t("editorText.workflowPausedWarning"));
        setWorkflowPaused(true);
        appendEventLog(t("editorText.workflowPaused"), "warning");
        return;
      }

      if (status === "running") {
        setWorkflowPaused(false);
      }

      if (status === "cancelled") {
        appendEventLog(t("editorText.taskCancelled", { taskId }), "info");
        finishTask("cancelled");
        return;
      }

      // Terminal statuses delivered via workflow_state
      if (
        status === "completed" ||
        status === "failed"
      ) {
        const finalStatus = status as TaskStatus;
        appendEventLog(
          t("editorText.taskFinished", { taskId, status: t(`common:statuses.${finalStatus}`, { defaultValue: finalStatus }) }),
          finalStatus === "failed" ? "error" : "info"
        );
        finishTask(finalStatus);
      }
    };

    const handleError = (data: Record<string, unknown>) => {
      if (!isCurrentTaskContext()) return;
      const message = typeof data.message === "string" ? data.message : t("common:unknown");
      appendEventLog(t("editorText.serverError", { message }), "error");
    };

    // ----- Connection ------------------------------------------------------

    const connect = () => {
      if (stoppedRef.current || !isWorkspaceContextCurrent(workspaceToken)) return;

      closeStream();

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      let scopedPath: string;
      if (workspaceToken.workspaceId) {
        const scopedUrl = new URL(`/ws/workflow/${taskId}`, window.location.origin);
        scopedUrl.searchParams.set("workspace_id", workspaceToken.workspaceId);
        scopedPath = `${scopedUrl.pathname}${scopedUrl.search}`;
      } else {
        try {
          scopedPath = buildWorkspaceScopedUrl(`/ws/workflow/${taskId}`);
        } catch {
          scopedPath = `/ws/workflow/${taskId}`;
        }
      }
      const url = new URL(scopedPath, window.location.origin);
      url.protocol = protocol;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (stoppedRef.current || !isCurrentTaskContext()) {
          ws.close();
          return;
        }
        reconnectAttemptRef.current = 0;
        setWsConnected(true);
        setWsWarning(null);
        setManualReconnectAvailable(false);
        appendEventLog(t("editorText.wsConnected"));
      };

      ws.onmessage = (event: MessageEvent) => {
        if (stoppedRef.current || !isCurrentTaskContext()) return;

        const msg = parseMessage(typeof event.data === "string" ? event.data : "");
        if (!msg) return;

        switch (msg.type) {
          case "connected":
            handleConnected(msg.data);
            break;
          case "node_event":
            handleNodeEvent(msg.data);
            break;
          case "workflow_state":
            handleWorkflowState(msg.data);
            break;
          case "error":
            handleError(msg.data);
            break;
          case "ping":
            sendCommand("pong");
            break;
          case "pong":
            break;
        }
      };

      ws.onerror = () => {
        if (stoppedRef.current || !isCurrentTaskContext()) return;
        appendEventLog(t("editorText.wsConnectionError"), "error");
      };

      ws.onclose = (event) => {
        if (stoppedRef.current || !isCurrentTaskContext()) return;

        closeStream();

        if (event.code === 1008) {
          stoppedRef.current = true;
          setWsWarning(t("editorText.permissionConnectionClosed"));
          setManualReconnectAvailable(false);
          appendEventLog(t("editorText.wsPermissionRevoked"), "error");
          cleanupReconnectTimer();
          return;
        }

        if (reconnectAttemptRef.current >= maxReconnectAttempts) {
          setWsWarning(t("editorText.connectionFailedManual"));
          setManualReconnectAvailable(true);
          appendEventLog(t("editorText.wsReconnectLimit"), "error");
          cleanupReconnectTimer();
          return;
        }

        const delay = baseReconnectDelayMs * 2 ** reconnectAttemptRef.current;
        reconnectAttemptRef.current += 1;
        setWsWarning(t("editorText.reconnecting"));
        setManualReconnectAvailable(false);
        appendEventLog(
          t("editorText.wsReconnectScheduled", { seconds: Math.round(delay / 1000), attempt: reconnectAttemptRef.current }),
          "warning"
        );
        cleanupReconnectTimer();
        reconnectTimerRef.current = window.setTimeout(async () => {
          if (stoppedRef.current || !isCurrentTaskContext()) return;
          const synced = await syncTaskStatus();
          if (!synced || !isCurrentTaskContext()) return;
          connect();
        }, delay);
      };
    };

    // ----- Store refs for external use ------------------------------------

    connectRef.current = connect;
    syncTaskStatusRef.current = syncTaskStatus;
    closeStreamRef.current = closeStream;
    cleanupReconnectTimerRef.current = cleanupReconnectTimer;

    connect();

    return () => {
      stoppedRef.current = true;
      cleanupReconnectTimer();
      closeStream();
      connectRef.current = null;
      syncTaskStatusRef.current = null;
      closeStreamRef.current = null;
      cleanupReconnectTimerRef.current = null;
    };
  }, [
    batchUpdateNodeStatuses,
    contextGeneration,
    enabled,
    onTaskFinished,
    appendEventLog,
    setBlockSelectionRequest,
    setManualReconnectAvailable,
    setProgress,
    setWsConnected,
    setWsWarning,
    setWorkflowPaused,
    setTaskId,
    setTaskStatus,
    taskId,
    updateNodeStatus,
    t
  ]);

  // ----- Public API --------------------------------------------------------

  const manualReconnect = useCallback(async (): Promise<boolean> => {
    const workspaceToken = captureWorkspaceContext();
    const isCurrentTaskContext = () =>
      isWorkspaceContextCurrent(workspaceToken) &&
      useTaskExecutionStore.getState().currentTaskId === taskId;
    if (!taskId || !enabled || stoppedRef.current || !isCurrentTaskContext()) {
      return false;
    }

    cleanupReconnectTimerRef.current?.();
    closeStreamRef.current?.();

    setManualReconnectAvailable(false);
    setWsWarning(t("editorText.reconnecting"));

    const synced = await (syncTaskStatusRef.current?.() ?? Promise.resolve(false));
    if (!isCurrentTaskContext()) return false;
    if (!synced) {
      setWsWarning(t("editorText.connectionFailedRefresh"));
      setManualReconnectAvailable(false);
      appendEventLog(t("editorText.manualReconnectFailed"), "error");
      return false;
    }

    reconnectAttemptRef.current = 0;
    connectRef.current?.();
    appendEventLog(t("editorText.manualReconnectTriggered"), "warning");
    return true;
  }, [appendEventLog, enabled, setManualReconnectAvailable, setWsWarning, taskId, t]);

  const sendCommand = useCallback((command: string, data?: Record<string, unknown>) => {
    if (!taskId || useTaskExecutionStore.getState().currentTaskId !== taskId) return;
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const msg: ClientCommand = { command, data: data ?? {} };
    ws.send(JSON.stringify(msg));
  }, [taskId]);

  const isConnected = useTaskExecutionStore((state) => state.wsConnected);

  return { isConnected, manualReconnect, sendCommand };
}
