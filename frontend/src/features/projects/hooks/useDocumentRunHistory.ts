import { useCallback, useEffect, useState } from "react";

import { getApiErrorMessage } from "@/services/api";
import { isEvaluationRunRequestContextCurrent } from "@/services/evaluationRunApi";
import { getDocumentRunHistory } from "@/services/projectApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { DocumentRunHistoryItem } from "@/types/project";

export interface UseDocumentRunHistoryResult {
  items: DocumentRunHistoryItem[];
  total: number;
  loading: boolean;
  error: string | null;
  retry: () => void;
}

const HISTORY_LIMIT = 20;

export function useDocumentRunHistory(
  projectId: string,
  documentId: string | null,
  refreshKey = "",
): UseDocumentRunHistoryResult {
  const [items, setItems] = useState<DocumentRunHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id ?? null);
  const generation = useWorkspaceStore((state) => state.contextGeneration);

  useEffect(() => {
    let cancelled = false;
    const requestContext = { workspaceId, generation };
    const isCurrentRequest = () =>
      !cancelled && isEvaluationRunRequestContextCurrent(requestContext);

    setItems([]);
    setTotal(0);
    setError(null);
    setLoading(Boolean(projectId && documentId));
    if (projectId && documentId) {
      void (async () => {
        try {
          const page = await getDocumentRunHistory(
            projectId,
            documentId,
            HISTORY_LIMIT,
            0,
          );
          if (!isCurrentRequest()) return;
          setItems(page.items);
          setTotal(page.total);
        } catch (caught: unknown) {
          if (!isCurrentRequest()) return;
          setItems([]);
          setTotal(0);
          setError(
            getApiErrorMessage(
              caught,
              "Failed to load this document's run history.",
            ),
          );
        } finally {
          if (isCurrentRequest()) setLoading(false);
        }
      })();
    }
    return () => {
      cancelled = true;
    };
  }, [documentId, generation, projectId, refreshKey, retryCount, workspaceId]);

  const retry = useCallback(() => {
    setRetryCount((current) => current + 1);
  }, []);

  return { items, total, loading, error, retry };
}
