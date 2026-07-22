import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getWorkflowList, type WorkflowListItem, type WorkflowListMeta } from "@/services/workflowApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

interface UseWorkflowStudioListOptions {
  pageSize?: number;
  sort?: string;
  debounceMs?: number;
}

interface UseWorkflowStudioListResult {
  items: WorkflowListItem[];
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  hasMore: boolean;
  meta: WorkflowListMeta;
  query: string;
  setQuery: (value: string) => void;
  clearQuery: () => void;
  refresh: () => Promise<void>;
  fetchMore: () => Promise<void>;
}

const DEFAULT_META: WorkflowListMeta = {
  total: 0,
  page: 1,
  limit: 20
};

export function useWorkflowStudioList(options: UseWorkflowStudioListOptions = {}): UseWorkflowStudioListResult {
  const { t } = useTranslation("workflows");
  const pageSize = options.pageSize ?? 20;
  const sort = options.sort ?? "updated_at:desc";
  const debounceMs = options.debounceMs ?? 200;

  const [items, setItems] = useState<WorkflowListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [meta, setMeta] = useState<WorkflowListMeta>({ ...DEFAULT_META, limit: pageSize });
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const requestIdRef = useRef(0);
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id ?? null);
  const generation = useWorkspaceStore((state) => state.contextGeneration);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setDebouncedQuery(query.trim());
    }, debounceMs);

    return () => {
      window.clearTimeout(handle);
    };
  }, [debounceMs, query]);

  const runRequest = useCallback(
    async (nextPage: number, append: boolean, nextQuery: string) => {
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      const requestContext = { workspaceId, generation };
      const isCurrentRequest = () => {
        const state = useWorkspaceStore.getState();
        return (
          requestId === requestIdRef.current &&
          requestContext.workspaceId === (state.currentWorkspace?.id ?? null) &&
          requestContext.generation === state.contextGeneration
        );
      };

      setError(null);
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
      }

      try {
        const response = await getWorkflowList({
          page: nextPage,
          limit: pageSize,
          sort,
          q: nextQuery || undefined
        });

        if (!isCurrentRequest()) {
          return;
        }

        setItems((current) => (append ? [...current, ...response.items] : response.items));
        setMeta(response.meta);
        setPage(response.meta.page);
        setHasMore(response.meta.page * response.meta.limit < response.meta.total);
      } catch (err) {
        if (!isCurrentRequest()) {
          return;
        }

        const message = err instanceof Error ? err.message : t("studioText.loadFailed");
        setError(message);
        if (!append) {
          setItems([]);
          setMeta({
            total: 0,
            page: 1,
            limit: pageSize
          });
          setPage(1);
          setHasMore(false);
        }
      } finally {
        if (isCurrentRequest()) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [generation, pageSize, sort, t, workspaceId]
  );

  useEffect(() => {
    void runRequest(1, false, debouncedQuery);
  }, [debouncedQuery, runRequest]);

  const refresh = useCallback(async () => {
    await runRequest(1, false, debouncedQuery);
  }, [debouncedQuery, runRequest]);

  const fetchMore = useCallback(async () => {
    if (loading || loadingMore || !hasMore) {
      return;
    }

    await runRequest(page + 1, true, debouncedQuery);
  }, [debouncedQuery, hasMore, loading, loadingMore, page, runRequest]);

  return {
    items,
    loading,
    loadingMore,
    error,
    hasMore,
    meta,
    query,
    setQuery,
    clearQuery: () => setQuery(""),
    refresh,
    fetchMore
  };
}
