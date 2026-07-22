import { useCallback, useEffect, useRef, useState } from "react";

import type { Workflow } from "@/types/project";
import { apiClient } from "@/services/api";
import { createRun } from "@/services/projectApi";
import {
  isEvaluationRunRequestContextCurrent,
} from "@/services/evaluationRunApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

interface BackendWorkflowSummary {
  id: string;
  name: string;
  description: string | null;
}

export interface UseRunWorkflowConfigResult {
  workflows: Workflow[];
  loading: boolean;
  error: string | null;
  selectedWorkflowId: string | null;
  selectedDocuments: string[];
  setSelectedWorkflow: (id: string | null) => void;
  setSelectedDocuments: (ids: string[]) => void;
  startRun: (workflowId: string, documentIds: string[], runName?: string) => Promise<string>;
}

export function useRunWorkflowConfig(projectId: string): UseRunWorkflowConfigResult {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id ?? null);
  const generation = useWorkspaceStore((state) => state.contextGeneration);

  const requestIdRef = useRef(0);

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    const requestContext = { workspaceId, generation };
    const isCurrentRequest = () =>
      requestId === requestIdRef.current && isEvaluationRunRequestContextCurrent(requestContext);
    setLoading(true);
    setError(null);
    setWorkflows([]);
    setSelectedWorkflowId(null);
    setSelectedDocuments([]);

    const load = async () => {
      try {
        const response = await apiClient.get<{
          success: boolean;
          data: BackendWorkflowSummary[];
        }>("/workflows");
        if (!isCurrentRequest()) return;
        setWorkflows(
          response.data.data.map((w) => ({
            id: w.id,
            name: w.name,
            description: w.description ?? undefined,
          })),
        );
      } catch (e) {
        if (!isCurrentRequest()) return;
        setError(e instanceof Error ? e.message : "Failed to load workflows");
      } finally {
        if (isCurrentRequest()) {
          setLoading(false);
        }
      }
    };

    void load();
  }, [generation, projectId, workspaceId]);

  const setSelectedWorkflow = useCallback((id: string | null) => {
    setSelectedWorkflowId(id);
  }, []);

  const startRun = useCallback(
    async (workflowId: string, documentIds: string[], runName?: string): Promise<string> => {
      const run = await createRun(projectId, { workflowId, documentIds, runName });
      return run.id;
    },
    [projectId],
  );

  return {
    workflows,
    loading,
    error,
    selectedWorkflowId,
    selectedDocuments,
    setSelectedWorkflow,
    setSelectedDocuments,
    startRun,
  };
}
