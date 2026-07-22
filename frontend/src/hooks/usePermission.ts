import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { PermissionDecision, WorkspaceCapability, WorkspaceRole } from "@/types/workspace";

export interface UsePermissionResult {
  can: (capability: WorkspaceCapability) => boolean;
  explain: (capability: WorkspaceCapability) => PermissionDecision;
  role: WorkspaceRole | null;
}

export function usePermission(): UsePermissionResult {
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const can = useWorkspaceStore((state) => state.can);
  const explain = useWorkspaceStore((state) => state.explain);

  return {
    can,
    explain,
    role: currentWorkspace?.role ?? null,
  };
}
