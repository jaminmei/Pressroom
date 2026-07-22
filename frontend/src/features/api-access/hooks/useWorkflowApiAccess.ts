import { useCallback, useEffect, useRef, useState } from "react";

import {
  type ApiKeyRecord,
  type IssueApiKeyRequest,
  type IssueApiKeyResponse,
  issueWorkflowApiKey,
  listWorkflowApiKeys,
  revokeWorkflowApiKey,
} from "@/services/apiAccessApi";
import { type WorkflowDetailResponse, getWorkflowDetail } from "@/services/workflowApi";

export interface UseWorkflowApiAccessResult {
  workflow: WorkflowDetailResponse | null;
  keys: ApiKeyRecord[];
  loading: boolean;
  error: string | null;
  isPublished: boolean;
  page: number;
  total: number;
  limit: number;
  setPage: (newPage: number) => void;
  actions: {
    issueKey: (req: IssueApiKeyRequest) => Promise<IssueApiKeyResponse>;
    revokeKey: (keyId: string) => Promise<void>;
    refresh: () => Promise<void>;
  };
}

export function useWorkflowApiAccess(workflowId: string | undefined): UseWorkflowApiAccessResult {
  const [workflow, setWorkflow] = useState<WorkflowDetailResponse | null>(null);
  const [keys, setKeys] = useState<ApiKeyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  // Keep the limit fixed until the UI exposes an adjustable page size.
  const [limit] = useState(10);

  const requestIdRef = useRef(0);

  const load = useCallback(async (id: string) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;

    setLoading(true);
    setError(null);

    try {
      const [wf, result] = await Promise.all([getWorkflowDetail(id), listWorkflowApiKeys(id, page, limit)]);
      if (requestId !== requestIdRef.current) return;
      setWorkflow(wf);
      setKeys(result.data);
      setTotal(result.meta.total);
    } catch {
      if (requestId !== requestIdRef.current) return;
      setError("Failed to load workflow API access data.");
      setWorkflow(null);
      setKeys([]);
      setTotal(0);
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }, [page, limit]);

  const refresh = useCallback(
    async (id: string) => {
      const result = await listWorkflowApiKeys(id, page, limit);
      setKeys(result.data);
      setTotal(result.meta.total);
    },
    [page, limit]
  );

  useEffect(() => {
    if (!workflowId) {
      setWorkflow(null);
      setKeys([]);
      setLoading(false);
      setPage(1);
      setTotal(0);
      return;
    }
    void load(workflowId);
    // Pagination state intentionally resets when the view unmounts.
  }, [load, workflowId]);

  const issueKey = useCallback(
    async (req: IssueApiKeyRequest): Promise<IssueApiKeyResponse> => {
      const response = await issueWorkflowApiKey(req);
      try {
        await refresh(req.workflow_id);
      } catch {
        // non-fatal: never hide the one-time full key after successful creation
      }
      return response;
    },
    [refresh]
  );

  const revokeKey = useCallback(
    async (keyId: string): Promise<void> => {
      await revokeWorkflowApiKey(keyId);
      if (workflowId) {
        const result = await listWorkflowApiKeys(workflowId, page, limit);
        const totalPages = Math.max(1, Math.ceil(result.meta.total / limit));
        if (page > totalPages) {
          // Clamp to the last page when revoking the final key on a page.
          const clampedResult = await listWorkflowApiKeys(workflowId, totalPages, limit);
          setKeys(clampedResult.data);
          setTotal(clampedResult.meta.total);
          setPage(totalPages);
        } else {
          setKeys(result.data);
          setTotal(result.meta.total);
        }
      }
    },
    [page, limit, workflowId]
  );

  const refreshAction = useCallback(async () => {
    if (workflowId) {
      try {
        await refresh(workflowId);
      } catch {
        // manual refresh failures are non-fatal; list will appear stale
      }
    }
  }, [refresh, workflowId]);

  return {
    workflow,
    keys,
    loading,
    error,
    isPublished: Boolean(workflow?.published_version),
    page,
    total,
    limit,
    setPage,
    actions: { issueKey, revokeKey, refresh: refreshAction },
  };
}
