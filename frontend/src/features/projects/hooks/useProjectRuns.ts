import { useCallback, useEffect, useRef, useState } from "react";

import type { ProjectRun } from "@/types/project";

import { listRuns } from "@/services/projectApi";
import {
  isEvaluationRunRequestContextCurrent,
} from "@/services/evaluationRunApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

export interface UseProjectRunsResult {
  items: ProjectRun[];
  loading: boolean;
  error: string | null;
  getRunDetail: (runId: string) => ProjectRun | undefined;
}

const filterByProject = (runs: ProjectRun[], _projectId: string): ProjectRun[] =>
  runs;

export function useProjectRuns(projectId: string): UseProjectRunsResult {
  const [items, setItems] = useState<ProjectRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id ?? null);
  const generation = useWorkspaceStore((state) => state.contextGeneration);

  const requestIdRef = useRef(0);
  const baseRef = useRef<ProjectRun[]>([]);

  const fetchRuns = useCallback(async (pid: string) => {
    const requestId = ++requestIdRef.current;
    const requestContext = { workspaceId, generation };
    const isCurrentRequest = () =>
      requestId === requestIdRef.current && isEvaluationRunRequestContextCurrent(requestContext);
    setLoading(true);
    setError(null);

    try {
      const runs = await listRuns(pid);
      if (!isCurrentRequest()) return;
      baseRef.current = filterByProject(runs, pid);
      setItems([...baseRef.current]);
    } catch (e) {
      if (!isCurrentRequest()) return;
      const msg = e instanceof Error ? e.message : "Failed to load runs";
      setError(msg);
      setItems([]);
    } finally {
      if (isCurrentRequest()) {
        setLoading(false);
      }
    }
  }, [generation, workspaceId]);

  useEffect(() => {
    ++requestIdRef.current;
    setItems([]);
    setError(null);

    if (!projectId) return;
    void fetchRuns(projectId);
  }, [fetchRuns, projectId]);

  const getRunDetail = useCallback(
    (runId: string): ProjectRun | undefined =>
      baseRef.current.find((r) => r.id === runId),
    [],
  );

  return {
    items,
    loading,
    error,
    getRunDetail,
  };
}
