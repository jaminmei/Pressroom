import { create } from "zustand";

import type { BlockSelectionRequest, TaskInputFileIdentity, TaskProgress, TaskStatus } from "@/types/task";

export type TaskNodeVisualStatus =
  | "idle"
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "awaiting_input"
  | "awaiting_user_input"
  | "skipped"
  | "cancelled";

export type TaskExecutionLogLevel = "info" | "warning" | "error";

export interface TaskExecutionLogEntry {
  id: string;
  timestamp: string;
  level: TaskExecutionLogLevel;
  message: string;
}

export interface TaskExecutionState {
  currentTaskId: string | null;
  taskStatus: TaskStatus | "idle";
  wsConnected: boolean;
  nodeStatuses: Record<string, TaskNodeVisualStatus>;
  nodeProgress: Record<string, number>;
  nodeErrors: Record<string, string | undefined>;
  eventLogs: TaskExecutionLogEntry[];
  progress: TaskProgress | null;
  blockSelectionRequest: BlockSelectionRequest | null;
  wsWarning: string | null;
  manualReconnectAvailable: boolean;
  executionStartedAt: number | null;
  workflowPaused: boolean;
  sendCommandFn: ((command: string, data?: Record<string, unknown>) => void) | null;
  lastRunDagFingerprint: string | null;
  lastRunInputFiles: TaskInputFileIdentity[] | null;
  traceMode: boolean;
  traceInputMetadata: Record<string, unknown> | null;
  activeOperationId: string | null;
  setTaskId: (taskId: string | null) => void;
  setTaskStatus: (status: TaskStatus | "idle") => void;
  setWsConnected: (connected: boolean) => void;
  setProgress: (progress: TaskProgress | null) => void;
  updateNodeStatus: (nodeId: string, status: TaskNodeVisualStatus, error?: string) => void;
  batchUpdateNodeStatuses: (statuses: Record<string, TaskNodeVisualStatus>) => void;
  setNodeProgress: (nodeId: string, percentage: number) => void;
  appendEventLog: (message: string, level?: TaskExecutionLogLevel) => void;
  clearEventLogs: () => void;
  setBlockSelectionRequest: (request: BlockSelectionRequest | null) => void;
  setWsWarning: (warning: string | null) => void;
  setManualReconnectAvailable: (available: boolean) => void;
  setWorkflowPaused: (paused: boolean) => void;
  setSendCommandFn: (fn: ((command: string, data?: Record<string, unknown>) => void) | null) => void;
  setLastRunMeta: (dagFingerprint: string | null, inputFiles: TaskInputFileIdentity[] | null) => void;
  setTraceContext: (trace: { enabled: boolean; inputMetadata?: Record<string, unknown> | null }) => void;
  reset: () => void;
}

const initialTaskExecutionState: Pick<
  TaskExecutionState,
  | "currentTaskId"
  | "taskStatus"
  | "wsConnected"
  | "nodeStatuses"
  | "nodeProgress"
  | "nodeErrors"
  | "eventLogs"
  | "progress"
  | "blockSelectionRequest"
  | "wsWarning"
  | "manualReconnectAvailable"
  | "executionStartedAt"
  | "workflowPaused"
  | "sendCommandFn"
  | "lastRunDagFingerprint"
  | "lastRunInputFiles"
  | "traceMode"
  | "traceInputMetadata"
  | "activeOperationId"
> = {
  currentTaskId: null,
  taskStatus: "idle",
  wsConnected: false,
  nodeStatuses: {},
  nodeProgress: {},
  nodeErrors: {},
  eventLogs: [],
  progress: null,
  blockSelectionRequest: null,
  wsWarning: null,
  manualReconnectAvailable: false,
  executionStartedAt: null,
  workflowPaused: false,
  sendCommandFn: null,
  lastRunDagFingerprint: null,
  lastRunInputFiles: null,
  traceMode: false,
  traceInputMetadata: null,
  activeOperationId: null
};

const activeTaskStatuses = new Set<TaskStatus | "idle">(["pending", "running"]);
const maxEventLogEntries = 200;

export const useTaskExecutionStore = create<TaskExecutionState>((set) => ({
  ...initialTaskExecutionState,
  setTaskId: (taskId) => set({ currentTaskId: taskId }),
  setTaskStatus: (status) =>
    set((state) => ({
      taskStatus: status,
      executionStartedAt:
        activeTaskStatuses.has(status) && activeTaskStatuses.has(state.taskStatus)
          ? state.executionStartedAt
          : activeTaskStatuses.has(status)
            ? Date.now()
            : null
    })),
  setWsConnected: (connected) => set({ wsConnected: connected }),
  setProgress: (progress) => set({ progress }),
  updateNodeStatus: (nodeId, status, error) =>
    set((state) => ({
      nodeStatuses: {
        ...state.nodeStatuses,
        [nodeId]: status
      },
      nodeErrors: {
        ...state.nodeErrors,
        [nodeId]: error
      }
    })),
  batchUpdateNodeStatuses: (statuses) =>
    set((state) => ({
      nodeStatuses: {
        ...state.nodeStatuses,
        ...statuses
      }
    })),
  setNodeProgress: (nodeId, percentage) =>
    set((state) => ({
      nodeProgress: {
        ...state.nodeProgress,
        [nodeId]: percentage
      }
    })),
  appendEventLog: (message, level = "info") =>
    set((state) => {
      const nextEntry: TaskExecutionLogEntry = {
        id: `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
        timestamp: new Date().toISOString(),
        level,
        message
      };
      const merged = [...state.eventLogs, nextEntry];
      return {
        eventLogs: merged.slice(Math.max(merged.length - maxEventLogEntries, 0))
      };
    }),
  clearEventLogs: () => set({ eventLogs: [] }),
  setBlockSelectionRequest: (request) => set({ blockSelectionRequest: request }),
  setWsWarning: (warning) => set({ wsWarning: warning }),
  setManualReconnectAvailable: (available) => set({ manualReconnectAvailable: available }),
  setWorkflowPaused: (paused) => set({ workflowPaused: paused }),
  setSendCommandFn: (fn) => set({ sendCommandFn: fn }),
  setLastRunMeta: (dagFingerprint, inputFiles) => set({ lastRunDagFingerprint: dagFingerprint, lastRunInputFiles: inputFiles }),
  setTraceContext: (trace) => set({ traceMode: trace.enabled, traceInputMetadata: trace.inputMetadata ?? null }),
  reset: () => set({ ...initialTaskExecutionState })
}));

let operationSequence = 0;

export function beginTaskOperation(): string {
  operationSequence += 1;
  const operationId = `task-operation-${operationSequence}`;
  useTaskExecutionStore.setState({ activeOperationId: operationId });
  return operationId;
}

export function isTaskOperationCurrent(operationId: string): boolean {
  return useTaskExecutionStore.getState().activeOperationId === operationId;
}

export function finishTaskOperation(operationId: string): void {
  if (isTaskOperationCurrent(operationId)) {
    useTaskExecutionStore.setState({ activeOperationId: null });
  }
}
