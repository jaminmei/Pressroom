import { useState, useEffect, useCallback } from "react";
import * as workspaceApi from "@/services/workspaceApi";
import type { InviteWorkspaceMemberRequest, WorkspaceMember, WorkspaceRole } from "@/types/workspace";

export interface UseWorkspaceMembersResult {
  members: WorkspaceMember[];
  total: number;
  loading: boolean;
  error: string | null;
  inviteMember: (payload: InviteWorkspaceMemberRequest) => Promise<void>;
  changeRole: (userId: string, role: WorkspaceRole) => Promise<void>;
  removeMember: (userId: string) => Promise<void>;
  refresh: () => Promise<void>;
}

export function useWorkspaceMembers(workspaceId: string): UseWorkspaceMembersResult {
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchMembers = useCallback(async (isMounted: { current: boolean }) => {
    if (!workspaceId) return;

    setLoading(true);
    setError(null);
    try {
      const result = await workspaceApi.listWorkspaceMembers(workspaceId);
      if (isMounted.current) {
        setMembers(result.items);
        setTotal(result.total);
      }
    } catch (err: unknown) {
      if (isMounted.current) {
        setError(err instanceof Error ? err.message : "Failed to load workspace members");
      }
    } finally {
      if (isMounted.current) {
        setLoading(false);
      }
    }
  }, [workspaceId]);

  useEffect(() => {
    const isMounted = { current: true };
    fetchMembers(isMounted);
    return () => {
      isMounted.current = false;
    };
  }, [fetchMembers]);

  const refresh = useCallback(async () => {
    await fetchMembers({ current: true });
  }, [fetchMembers]);

  const inviteMember = useCallback(async (payload: InviteWorkspaceMemberRequest) => {
    await workspaceApi.inviteWorkspaceMember(workspaceId, payload);
    await refresh();
  }, [workspaceId, refresh]);

  const changeRole = useCallback(async (userId: string, role: WorkspaceRole) => {
    await workspaceApi.changeWorkspaceMemberRole(workspaceId, userId, { role });
    await refresh();
  }, [workspaceId, refresh]);

  const removeMember = useCallback(async (userId: string) => {
    await workspaceApi.removeWorkspaceMember(workspaceId, userId);
    await refresh();
  }, [workspaceId, refresh]);

  return {
    members,
    total,
    loading,
    error,
    inviteMember,
    changeRole,
    removeMember,
    refresh,
  };
}
