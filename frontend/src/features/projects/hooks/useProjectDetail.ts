import { useCallback, useEffect, useRef, useState } from "react";

import type { Project, ProjectRun } from "@/types/project";
import { getProject, listRuns } from "@/services/projectApi";
import {
  isEvaluationRunRequestContextCurrent,
} from "@/services/evaluationRunApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { usePermission } from "@/hooks/usePermission";

export interface ActivityItem {
  id: string;
  action: string;
  detail: string;
  timestamp: string;
}

export interface RunSummary {
  id: string;
  name: string;
  status: ProjectRun["status"];
  passRate: number;
  date: string;
}

export interface ProjectDetailData {
  project: Project & { version: string };
  recentRuns: RunSummary[];
  activity: ActivityItem[];
}

function mapRunToSummary(run: ProjectRun): RunSummary {
  return {
    id: run.id,
    name: run.name || "Unnamed run",
    status: run.status,
    passRate: run.passRate ?? 0,
    date: run.startedAt,
  };
}

function deriveActivity(runs: ProjectRun[]): ActivityItem[] {
  return runs
    .filter(
      (r) =>
        r.status === "completed" ||
        r.status === "partial_completed" ||
        r.status === "failed" ||
        r.status === "cancelled",
    )
    .slice(0, 5)
    .map((r) => ({
      id: `act-${r.id}`,
      action:
        r.status === "completed"
          ? "Run completed"
          : r.status === "partial_completed"
            ? "Run partially completed"
            : r.status === "cancelled"
              ? "Run cancelled"
              : "Run failed",
      detail: `${r.name || "Unnamed run"}${r.passRate != null ? ` — ${r.passRate}% pass rate` : ""}`,
      timestamp: r.completedAt || r.startedAt,
    }));
}

export interface UseProjectDetailResult {
  project: (Project & { version: string }) | null;
  recentRuns: RunSummary[];
  activity: ActivityItem[];
  loading: boolean;
  error: string | null;
}

export function useProjectDetail(projectId: string): UseProjectDetailResult {
  const { can } = usePermission();
  const canViewRuns = can("run.view");
  const [project, setProject] = useState<(Project & { version: string }) | null>(null);
  const [recentRuns, setRecentRuns] = useState<RunSummary[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id ?? null);
  const generation = useWorkspaceStore((state) => state.contextGeneration);

  const requestIdRef = useRef(0);

  const fetchProjectDetail = useCallback(async (id: string) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    const requestContext = { workspaceId, generation };
    const isCurrentRequest = () =>
      requestId === requestIdRef.current && isEvaluationRunRequestContextCurrent(requestContext);

    setLoading(true);
    setError(null);
    setProject(null);
    setRecentRuns([]);
    setActivity([]);

    try {
      const [projectData, runs] = await Promise.all([
        getProject(id),
        canViewRuns ? listRuns(id) : Promise.resolve([]),
      ]);
      if (!isCurrentRequest()) return;

      setProject({ ...projectData, version: "1.0" });
      const summaries = runs.map(mapRunToSummary);
      setRecentRuns(summaries);
      setActivity(deriveActivity(runs));
    } catch {
      if (!isCurrentRequest()) return;
      setError("Failed to load project details.");
      setProject(null);
      setRecentRuns([]);
      setActivity([]);
    } finally {
      if (isCurrentRequest()) {
        setLoading(false);
      }
    }
  }, [canViewRuns, generation, workspaceId]);

  useEffect(() => {
    requestIdRef.current += 1;
    setProject(null);
    setRecentRuns([]);
    setActivity([]);
    setError(null);

    if (!projectId) return;
    void fetchProjectDetail(projectId);
  }, [fetchProjectDetail, projectId]);

  return {
    project,
    recentRuns: canViewRuns ? recentRuns : [],
    activity: canViewRuns ? activity : [],
    loading,
    error,
  };
}
