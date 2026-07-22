import { useCallback, useEffect, useRef, useState } from "react";

import { getTaskStatus } from "@/services/taskApi";
import type { TaskStatus, TaskStatusResponse } from "@/types/task";

const DEFAULT_INTERVAL_MS = 2000;

const terminalTaskStatusSet = new Set<TaskStatus>([
  "completed",
  "failed",
  "cancelled"
]);

interface UseTaskPollingOptions {
  taskId: string | null;
  enabled?: boolean;
  intervalMs?: number;
  onStatusUpdate?: (status: TaskStatusResponse) => void;
  onFinished?: (status: TaskStatusResponse) => void | Promise<void>;
  onError?: (error: unknown) => void;
}

interface UseTaskPollingResult {
  status: TaskStatusResponse | null;
  error: unknown;
  isPolling: boolean;
  stopPolling: () => void;
}

export function useTaskPolling({
  taskId,
  enabled = true,
  intervalMs = DEFAULT_INTERVAL_MS,
  onStatusUpdate,
  onFinished,
  onError
}: UseTaskPollingOptions): UseTaskPollingResult {
  const [status, setStatus] = useState<TaskStatusResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [isPolling, setIsPolling] = useState(false);
  const intervalRef = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (intervalRef.current !== null) {
      window.clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setIsPolling(false);
  }, []);

  const pollTaskStatus = useCallback(async () => {
    if (!taskId) {
      return;
    }

    try {
      const nextStatus = await getTaskStatus(taskId);
      setStatus(nextStatus);
      setError(null);
      onStatusUpdate?.(nextStatus);

      if (terminalTaskStatusSet.has(nextStatus.status)) {
        stopPolling();
        await onFinished?.(nextStatus);
      }
    } catch (pollingError) {
      setError(pollingError);
      stopPolling();
      onError?.(pollingError);
    }
  }, [taskId, onStatusUpdate, onFinished, onError, stopPolling]);

  useEffect(() => {
    stopPolling();
    setStatus(null);
    setError(null);

    if (!enabled || !taskId) {
      return;
    }

    setIsPolling(true);
    void pollTaskStatus();

    intervalRef.current = window.setInterval(() => {
      void pollTaskStatus();
    }, intervalMs);

    return () => {
      stopPolling();
    };
  }, [enabled, taskId, intervalMs, pollTaskStatus, stopPolling]);

  return {
    status,
    error,
    isPolling,
    stopPolling
  };
}
