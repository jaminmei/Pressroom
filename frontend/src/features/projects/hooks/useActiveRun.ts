import { useCallback, useEffect, useRef, useState } from "react";
import { App as AntApp } from "antd";

import type { RunProgressItem, RunResult } from "@/types/project";
import {
  acceptAsGT as apiAcceptAsGT,
  getRunResults,
  getRunStatus,
  mapComparisonStatus,
  rejectResult as apiRejectResult,
} from "@/services/projectApi";
import {
  captureEvaluationRunRequestContext,
  type EvaluationRunStatus,
  isEvaluationRunRequestContextCurrent,
  isEvaluationRunTerminalStatus,
} from "@/services/evaluationRunApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { getApiErrorMessage } from "@/services/api";

export type RunStatus = "idle" | EvaluationRunStatus;

export interface UseActiveRunResult {
  activeRunId: string | null;
  error: string | null;
  runStatus: RunStatus;
  runProgress: RunProgressItem[];
  results: RunResult[];
  acceptAsGT: (docId: string) => void;
  rejectResult: (docId: string) => void;
  updateResultComparison: (resultId: string, comparisonStatus: string) => void;
  startMonitoring: (runId: string) => void;
}

const POLL_INTERVAL_MS = 2000;

export function useActiveRun(projectId: string): UseActiveRunResult {
  const { message } = AntApp.useApp();
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [runProgress, setRunProgress] = useState<RunProgressItem[]>([]);
  const [results, setResults] = useState<RunResult[]>([]);
  const canViewRuns = useWorkspaceStore((state) => state.capabilities.includes("run.view"));
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id ?? null);
  const generation = useWorkspaceStore((state) => state.contextGeneration);

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRunIdRef = useRef<string | null>(null);
  const requestIdRef = useRef(0);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    requestIdRef.current += 1;
    activeRunIdRef.current = null;
    stopPolling();
    setActiveRunId(null);
    setError(null);
    setRunStatus("idle");
    setRunProgress([]);
    setResults([]);
    return stopPolling;
  }, [canViewRuns, generation, stopPolling, workspaceId]);

  const poll = useCallback(
    async (runId: string) => {
      const requestId = requestIdRef.current;
      const requestContext = captureEvaluationRunRequestContext();
      const isCurrentRequest = () =>
        requestId === requestIdRef.current &&
        activeRunIdRef.current === runId &&
        isEvaluationRunRequestContextCurrent(requestContext) &&
        useWorkspaceStore.getState().capabilities.includes("run.view");
      if (!isCurrentRequest()) return;

      try {
        const status = await getRunStatus(runId);

        if (!isCurrentRequest()) return;

        const resultsData = await getRunResults(runId);

        if (!isCurrentRequest()) return;

        const progressItems: RunProgressItem[] = resultsData.map((r) => ({
          documentId: r.documentId,
          documentName: r.documentName,
          status:
            r.executionStatus === "completed"
              ? "complete"
              : r.executionStatus === "failed"
                ? "failed"
                : r.executionStatus === "skipped"
                  ? "skipped"
                  : r.executionStatus === "running"
                    ? "processing"
                    : "pending",
        }));

        setRunProgress(progressItems);
        setResults(resultsData);
        setError(null);

        if (isEvaluationRunTerminalStatus(status.status)) {
          setRunStatus(status.status);
          return;
        }

        setRunStatus(status.status);
        pollRef.current = setTimeout(() => void poll(runId), POLL_INTERVAL_MS);
      } catch (caught: unknown) {
        if (!isCurrentRequest()) return;
        const errorMessage = getApiErrorMessage(
          caught,
          "Failed to monitor the evaluation run.",
        );
        setError(errorMessage);
        setRunStatus("failed");
        message.error(errorMessage);
      }
    },
    [message],
  );

  const startMonitoring = useCallback(
    (runId: string) => {
      if (
        !canViewRuns ||
        !useWorkspaceStore.getState().capabilities.includes("run.view")
      ) return;
      stopPolling();
      requestIdRef.current += 1;
      activeRunIdRef.current = runId;
      setActiveRunId(runId);
      setError(null);
      setRunStatus("pending");
      setResults([]);
      setRunProgress([]);

      pollRef.current = setTimeout(() => void poll(runId), 500);
    },
    [canViewRuns, stopPolling, poll],
  );

  const updateResultComparison = useCallback(
    (resultId: string, comparisonStatus: string) => {
      setResults((previous) =>
        previous.map((result) => {
          if (result.id !== resultId) return result;
          const hasGroundTruth = comparisonStatus === "unavailable"
            ? false
            : comparisonStatus === "matched" || comparisonStatus === "mismatched"
              ? true
              : result.hasGroundTruth;
          return {
            ...result,
            hasGroundTruth,
            status: result.acceptedAsGT
              ? "pass"
              : mapComparisonStatus(comparisonStatus, hasGroundTruth),
          };
        }),
      );
    },
    [],
  );

  const acceptAsGT = useCallback(
    (docId: string) => {
      const runId = activeRunIdRef.current;
      if (!runId) return;

      const result = results.find((r) => r.documentId === docId);
      if (!result) return;

      setResults((prev) =>
        prev.map((r) =>
          r.documentId === docId
            ? {
                ...r,
                acceptedAsGT: true,
                hasGroundTruth: true,
                rejected: false,
                status: "pass",
              }
            : r,
        ),
      );

      void apiAcceptAsGT(projectId, runId, result.id).catch(() => {
        setResults((prev) => prev.map((item) => item.documentId === docId ? result : item));
      });
    },
    [projectId, results],
  );

  const rejectResult = useCallback(
    (docId: string) => {
      const runId = activeRunIdRef.current;
      if (!runId) return;

      const result = results.find((r) => r.documentId === docId);
      if (!result) return;

      setResults((prev) =>
        prev.map((r) =>
          r.documentId === docId
            ? { ...r, acceptedAsGT: false, rejected: true }
            : r,
        ),
      );

      void apiRejectResult(projectId, runId, result.id).catch(() => {
        setResults((prev) => prev.map((item) => item.documentId === docId ? result : item));
      });
    },
    [projectId, results],
  );

  return {
    activeRunId,
    error,
    runStatus,
    runProgress,
    results,
    acceptAsGT,
    rejectResult,
    updateResultComparison,
    startMonitoring,
  };
}
