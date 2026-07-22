import { useState, useEffect, useCallback } from "react";
import * as workspaceApi from "@/services/workspaceApi";
import type { WorkspaceAuditEvent } from "@/types/workspace";

export interface UseWorkspaceAuditResult {
  events: WorkspaceAuditEvent[];
  total: number;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useWorkspaceAudit(workspaceId: string, enabled = true): UseWorkspaceAuditResult {
  const [events, setEvents] = useState<WorkspaceAuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchAuditEvents = useCallback(async (isMounted: { current: boolean }) => {
    if (!workspaceId || !enabled) return;

    setLoading(true);
    setError(null);
    try {
      const result = await workspaceApi.listWorkspaceAuditEvents(workspaceId);
      if (isMounted.current) {
        setEvents(result.items);
        setTotal(result.total);
      }
    } catch (err: unknown) {
      if (isMounted.current) {
        setEvents([]);
        setTotal(0);
        setError(err instanceof Error ? err.message : "Failed to load audit events");
      }
    } finally {
      if (isMounted.current) {
        setLoading(false);
      }
    }
  }, [workspaceId, enabled]);

  useEffect(() => {
    const isMounted = { current: true };
    fetchAuditEvents(isMounted);
    return () => {
      isMounted.current = false;
    };
  }, [fetchAuditEvents]);

  const refresh = useCallback(async () => {
    await fetchAuditEvents({ current: true });
  }, [fetchAuditEvents]);

  return {
    events,
    total,
    loading,
    error,
    refresh,
  };
}
