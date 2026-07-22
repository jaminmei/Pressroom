import { useCallback } from "react";
import { useWorkspaceStore, type WorkspaceHydrationStatus } from "@/stores/workspaceStore";
import type {
  CreateWorkspaceRequest,
  WorkspaceCapability,
  WorkspaceMembership,
  WorkspaceRole,
  WorkspaceSummary,
} from "@/types/workspace";

export interface UseWorkspaceResult {
  status: WorkspaceHydrationStatus;
  currentWorkspace: WorkspaceSummary | null;
  memberships: WorkspaceMembership[];
  currentRole: WorkspaceRole | null;
  capabilities: WorkspaceCapability[];
  isSwitching: boolean;
  error: string | null;
  switchWorkspace: (workspaceId: string) => Promise<void>;
  createWorkspace: (payload: CreateWorkspaceRequest) => Promise<WorkspaceSummary>;
  refresh: () => Promise<void>;
}

export function useWorkspace(): UseWorkspaceResult {
  const status = useWorkspaceStore((state) => state.status);
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const memberships = useWorkspaceStore((state) => state.memberships);
  const capabilities = useWorkspaceStore((state) => state.capabilities);
  const isSwitching = useWorkspaceStore((state) => state.isSwitching);
  const error = useWorkspaceStore((state) => state.error);

  const switchWorkspaceAction = useWorkspaceStore((state) => state.switchWorkspace);
  const createWorkspaceAction = useWorkspaceStore((state) => state.createWorkspace);
  const refreshWorkspacesAction = useWorkspaceStore((state) => state.refreshWorkspaces);

  const switchWorkspace = useCallback(
    async (workspaceId: string) => {
      await switchWorkspaceAction(workspaceId);
    },
    [switchWorkspaceAction]
  );

  const refresh = useCallback(
    async () => {
      await refreshWorkspacesAction();
    },
    [refreshWorkspacesAction]
  );

  const createWorkspace = useCallback(
    async (payload: CreateWorkspaceRequest) => {
      return createWorkspaceAction(payload);
    },
    [createWorkspaceAction]
  );

  return {
    status,
    currentWorkspace,
    memberships,
    currentRole: currentWorkspace?.role ?? null,
    capabilities,
    isSwitching,
    error,
    switchWorkspace,
    createWorkspace,
    refresh,
  };
}
