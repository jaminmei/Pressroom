import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useLiveStatusStore } from "@/features/task-execution/liveStatusStore";
import { getTaskHistory } from "@/services/taskApi";
import type { TaskHistoryItem } from "@/types/task";

interface UseRecentRunsOptions {
  pageSize?: number;
}

interface UseRecentRunsResult {
  items: TaskHistoryItem[];
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  refresh: () => Promise<void>;
  fetchMore: () => Promise<void>;
}

export function useRecentRuns(options: UseRecentRunsOptions = {}): UseRecentRunsResult {
  const { t } = useTranslation("workflows");
  const pageSize = options.pageSize ?? 20;
  const [items, setItems] = useState<TaskHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [page, setPage] = useState(1);

  // Patch items in-place when live status updates arrive via WebSocket
  const liveUpdates = useLiveStatusStore((state) => state.updates);
  useEffect(() => {
    setItems((prev) => {
      let changed = false;
      const next = prev.map((item) => {
        const liveStatus = liveUpdates[item.task_id];
        if (liveStatus && liveStatus !== item.status) {
          changed = true;
          return { ...item, status: liveStatus };
        }
        return item;
      });
      return changed ? next : prev;
    });
  }, [liveUpdates]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await getTaskHistory({ limit: pageSize, page: 1 });
      setItems(response.items);
      setPage(1);
      if (response.meta) {
        setHasMore(response.meta.page * response.meta.limit < response.meta.total);
      } else {
        setHasMore(response.items.length === pageSize);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : t("editorText.recentRunsLoadFailed");
      setError(message);
      setItems([]);
      setPage(1);
      setHasMore(false);
    } finally {
      setLoading(false);
    }
  }, [pageSize, t]);

  const fetchMore = useCallback(async () => {
    if (loading || !hasMore) {
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const nextPage = page + 1;
      const response = await getTaskHistory({ limit: pageSize, page: nextPage });
      setItems((current) => [...current, ...response.items]);
      setPage(nextPage);
      if (response.meta) {
        setHasMore(response.meta.page * response.meta.limit < response.meta.total);
      } else {
        setHasMore(response.items.length === pageSize);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : t("editorText.recentRunsLoadFailed");
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [hasMore, loading, page, pageSize, t]);

  return {
    items,
    loading,
    error,
    hasMore,
    refresh,
    fetchMore
  };
}
