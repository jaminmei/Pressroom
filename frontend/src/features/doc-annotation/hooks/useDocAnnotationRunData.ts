import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { App as AntApp } from "antd";
import { useTranslation } from "react-i18next";

import {
  createEvaluationRun,
  generateClientRequestId,
  getEvaluationResultDetail,
  getEvaluationRun,
  getEvaluationRunResults,
  isEvaluationRunTerminalStatus,
  type EvaluationRun,
  type EvaluationRunResultDetail,
  type EvaluationRunResultListItem,
  type EvaluationRunResultsSummary
} from "@/services/evaluationRunApi";
import { getWorkflowList, type WorkflowListItem } from "@/services/workflowApi";
import { getApiErrorMessage } from "@/services/api";

const POLL_INTERVAL_MS = 2000;

interface ActiveRunSnapshot {
  runId: string;
  testSetId: string;
  workflowId: string;
}

interface UseDocAnnotationRunDataOptions {
  selectedTestSetId: string | null;
  documentCount: number;
}

interface UseDocAnnotationRunDataResult {
  workflows: WorkflowListItem[];
  selectedWorkflowId: string | null;
  selectedWorkflow: WorkflowListItem | null;
  workflowsLoading: boolean;
  workflowsError: string | null;
  createRunPending: boolean;
  activeRun: EvaluationRun | null;
  runResults: EvaluationRunResultListItem[];
  runSummary: EvaluationRunResultsSummary | null;
  detailLoading: boolean;
  activeResultDetail: EvaluationRunResultDetail | null;
  pollWarning: string | null;
  hasInProgressRun: boolean;
  setSelectedWorkflowId: (value: string) => void;
  startRun: () => Promise<void>;
  retryPolling: () => void;
  openResultDetail: (resultId: string) => Promise<void>;
}

function isTerminalStatus(status: EvaluationRun["status"] | undefined): boolean {
  return status !== undefined && isEvaluationRunTerminalStatus(status);
}

export function useDocAnnotationRunData({
  selectedTestSetId,
  documentCount
}: UseDocAnnotationRunDataOptions): UseDocAnnotationRunDataResult {
  const { t } = useTranslation("projects");
  const { message } = AntApp.useApp();
  const [workflows, setWorkflows] = useState<WorkflowListItem[]>([]);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);
  const [workflowsLoading, setWorkflowsLoading] = useState(false);
  const [workflowsError, setWorkflowsError] = useState<string | null>(null);
  const [createRunPending, setCreateRunPending] = useState(false);
  const [activeRunSnapshot, setActiveRunSnapshot] = useState<ActiveRunSnapshot | null>(null);
  const [activeRun, setActiveRun] = useState<EvaluationRun | null>(null);
  const [runResults, setRunResults] = useState<EvaluationRunResultListItem[]>([]);
  const [runSummary, setRunSummary] = useState<EvaluationRunResultsSummary | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeResultDetail, setActiveResultDetail] = useState<EvaluationRunResultDetail | null>(null);
  const [pollWarning, setPollWarning] = useState<string | null>(null);
  const [pollRetryNonce, setPollRetryNonce] = useState(0);
  const selectedTestSetIdRef = useRef<string | null>(null);
  const workflowRequestIdRef = useRef(0);
  const resultsRequestIdRef = useRef(0);
  const detailRequestIdRef = useRef(0);
  const pollCycleIdRef = useRef(0);
  const pollTimeoutRef = useRef<number | null>(null);

  const clearPollingTimeout = useCallback(() => {
    if (pollTimeoutRef.current !== null) {
      window.clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
  }, []);

  const loadRunResults = useCallback(async (runId: string, expectedSnapshot: ActiveRunSnapshot) => {
    const requestId = resultsRequestIdRef.current + 1;
    resultsRequestIdRef.current = requestId;

    const response = await getEvaluationRunResults(runId);
    if (
      requestId !== resultsRequestIdRef.current ||
      selectedTestSetIdRef.current !== expectedSnapshot.testSetId ||
      expectedSnapshot.runId !== runId
    ) {
      return;
    }

    setRunSummary(response.summary);
    setRunResults(response.results);
  }, []);

  const loadWorkflows = useCallback(async () => {
    if (!selectedTestSetIdRef.current) {
      return;
    }

    const requestId = workflowRequestIdRef.current + 1;
    workflowRequestIdRef.current = requestId;
    setWorkflowsLoading(true);
    setWorkflowsError(null);

    try {
      const response = await getWorkflowList({ limit: 200, sort: "updated_at:desc" });
      if (requestId !== workflowRequestIdRef.current || !selectedTestSetIdRef.current) {
        return;
      }

      setWorkflows(response.items);
    } catch {
      if (requestId !== workflowRequestIdRef.current) {
        return;
      }

      setWorkflows([]);
      setWorkflowsError(t("legacy.loadWorkflowsFailed"));
    } finally {
      if (requestId === workflowRequestIdRef.current) {
        setWorkflowsLoading(false);
      }
    }
  }, [t]);

  useEffect(() => {
    selectedTestSetIdRef.current = selectedTestSetId;

    if (!selectedTestSetId) {
      clearPollingTimeout();
      setWorkflows([]);
      setSelectedWorkflowId(null);
      setWorkflowsError(null);
      setActiveRunSnapshot(null);
      setActiveRun(null);
      setRunResults([]);
      setRunSummary(null);
      setActiveResultDetail(null);
      setPollWarning(null);
      return;
    }

    clearPollingTimeout();
    setSelectedWorkflowId(null);
    setWorkflows([]);
    setWorkflowsError(null);
    setActiveRunSnapshot(null);
    setActiveRun(null);
    setRunResults([]);
    setRunSummary(null);
    setActiveResultDetail(null);
    setPollWarning(null);
    void loadWorkflows();
  }, [clearPollingTimeout, loadWorkflows, selectedTestSetId]);

  const startRun = useCallback(async () => {
    if (!selectedTestSetId || !selectedWorkflowId || documentCount === 0) {
      return;
    }

    const targetTestSetId = selectedTestSetId;
    const targetWorkflowId = selectedWorkflowId;

    setCreateRunPending(true);
    setPollWarning(null);
    setRunResults([]);
    setRunSummary(null);
    setActiveResultDetail(null);

    try {
      const run = await createEvaluationRun(targetTestSetId, {
        workflow_id: targetWorkflowId,
        client_request_id: generateClientRequestId()
      });

      if (selectedTestSetIdRef.current !== targetTestSetId) {
        return;
      }

      const nextSnapshot = {
        runId: run.id,
        testSetId: targetTestSetId,
        workflowId: targetWorkflowId
      };

      setActiveRunSnapshot({
        runId: run.id,
        testSetId: targetTestSetId,
        workflowId: targetWorkflowId
      });
      setActiveRun(run);
      if (isTerminalStatus(run.status)) {
        await loadRunResults(run.id, nextSnapshot);
      }
    } catch (error: unknown) {
      if (selectedTestSetIdRef.current !== targetTestSetId) {
        return;
      }
      const errorMessage = getApiErrorMessage(error, t("legacy.startBatchFailed"));
      setPollWarning(errorMessage);
      message.error(errorMessage);
    } finally {
      if (selectedTestSetIdRef.current === targetTestSetId) {
        setCreateRunPending(false);
      }
    }
  }, [documentCount, loadRunResults, message, selectedTestSetId, selectedWorkflowId, t]);

  useEffect(() => {
    clearPollingTimeout();
    pollCycleIdRef.current += 1;

    if (!activeRunSnapshot || !activeRun || isTerminalStatus(activeRun.status) || pollWarning) {
      return;
    }

    const cycleId = pollCycleIdRef.current;

    const pollOnce = async () => {
      try {
        const nextRun = await getEvaluationRun(activeRunSnapshot.runId);
        if (
          cycleId !== pollCycleIdRef.current ||
          selectedTestSetIdRef.current !== activeRunSnapshot.testSetId ||
          activeRunSnapshot.runId !== nextRun.id
        ) {
          return;
        }

        setActiveRun(nextRun);
        setPollWarning(null);

        if (isTerminalStatus(nextRun.status)) {
          await loadRunResults(nextRun.id, activeRunSnapshot);
          return;
        }

        pollTimeoutRef.current = window.setTimeout(() => {
          void pollOnce();
        }, POLL_INTERVAL_MS);
      } catch {
        if (cycleId !== pollCycleIdRef.current) {
          return;
        }
        setPollWarning(t("legacy.pollingPaused"));
      }
    };

    void pollOnce();

    return () => {
      clearPollingTimeout();
      pollCycleIdRef.current += 1;
    };
  }, [activeRun, activeRunSnapshot, clearPollingTimeout, loadRunResults, pollRetryNonce, pollWarning, t]);

  const retryPolling = useCallback(() => {
    setPollWarning(null);
    setPollRetryNonce((current) => current + 1);
  }, []);

  const openResultDetail = useCallback(async (resultId: string) => {
    if (!activeRunSnapshot) {
      return;
    }

    const requestId = detailRequestIdRef.current + 1;
    detailRequestIdRef.current = requestId;
    setDetailLoading(true);
    setActiveResultDetail(null);

    try {
      const detail = await getEvaluationResultDetail(activeRunSnapshot.runId, resultId);
      if (requestId !== detailRequestIdRef.current || activeRunSnapshot.runId !== detail.evaluation_run_id) {
        return;
      }
      setActiveResultDetail(detail);
    } finally {
      if (requestId === detailRequestIdRef.current) {
        setDetailLoading(false);
      }
    }
  }, [activeRunSnapshot]);

  const selectedWorkflow = useMemo(
    () => workflows.find((workflow) => workflow.id === selectedWorkflowId) ?? null,
    [selectedWorkflowId, workflows]
  );

  const hasInProgressRun = activeRun?.status === "pending" || activeRun?.status === "running";

  return {
    workflows,
    selectedWorkflowId,
    selectedWorkflow,
    workflowsLoading,
    workflowsError,
    createRunPending,
    activeRun,
    runResults,
    runSummary,
    detailLoading,
    activeResultDetail,
    pollWarning,
    hasInProgressRun,
    setSelectedWorkflowId,
    startRun,
    retryPolling,
    openResultDetail
  };
}
