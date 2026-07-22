import { create } from "zustand";

import { useTaskExecutionStore } from "@/features/task-execution/store";
import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";
import { clearActiveWorkspaceId, setActiveWorkspaceId } from "@/services/api";
import * as workspaceApi from "@/services/workspaceApi";
import { resetWorkspaceScopedState } from "@/stores/workspaceReset";
import {
  CAPABILITY_MATRIX,
  type CreateWorkspaceRequest,
  type PermissionDecision,
  type UpdateWorkspaceRequest,
  type WorkspaceCapability,
  type WorkspaceMembership,
  type WorkspaceSession,
  type WorkspaceSummary
} from "@/types/workspace";

export type WorkspaceHydrationStatus = "idle" | "loading" | "ready" | "error";

export interface WorkspaceContextToken {
  workspaceId: string | null;
  generation: number;
}

export type WorkspaceSwitchBlockedReason = "unsaved_changes" | "active_execution";

export class WorkspaceSwitchBlockedError extends Error {
  readonly reason: WorkspaceSwitchBlockedReason;

  constructor(reason: WorkspaceSwitchBlockedReason, message: string) {
    super(message);
    this.name = "WorkspaceSwitchBlockedError";
    this.reason = reason;
  }
}

export interface WorkspaceState {
  status: WorkspaceHydrationStatus;
  currentWorkspace: WorkspaceSummary | null;
  memberships: WorkspaceMembership[];
  capabilities: WorkspaceCapability[];
  error: string | null;
  isSwitching: boolean;
  contextGeneration: number;
  hydrateWorkspaceSession: () => Promise<void>;
  refreshWorkspaces: () => Promise<void>;
  switchWorkspace: (workspaceId: string) => Promise<void>;
  createWorkspace: (payload: CreateWorkspaceRequest) => Promise<WorkspaceSummary>;
  updateWorkspace: (workspaceId: string, payload: UpdateWorkspaceRequest) => Promise<WorkspaceSummary>;
  can: (capability: WorkspaceCapability) => boolean;
  explain: (capability: WorkspaceCapability) => PermissionDecision;
  resetWorkspaceState: () => void;
}

const initialState = {
  status: "idle" as WorkspaceHydrationStatus,
  currentWorkspace: null,
  memberships: [],
  capabilities: [],
  error: null,
  isSwitching: false,
  contextGeneration: 0
};

let hydrationRequest: Promise<void> | null = null;
let hydrationRequestEpoch: number | null = null;
let requestEpoch = 0;
let generationSequence = 0;

function nextRequestEpoch(): number {
  requestEpoch += 1;
  return requestEpoch;
}

function nextContextGeneration(): number {
  generationSequence += 1;
  return generationSequence;
}

export const useWorkspaceStore = create<WorkspaceState>((set, get) => {
  const _applyWorkspaceSession = (result: WorkspaceSession): void => {
    const previousWorkspaceId = get().currentWorkspace?.id ?? null;
    const nextWorkspaceId = result.currentWorkspace?.id ?? null;
    const contextChanged = previousWorkspaceId !== nextWorkspaceId;

    if (contextChanged) {
      resetWorkspaceScopedState();
    }
    setActiveWorkspaceId(nextWorkspaceId);
    set({
      currentWorkspace: result.currentWorkspace,
      memberships: result.memberships,
      capabilities: result.capabilities,
      contextGeneration: contextChanged ? nextContextGeneration() : get().contextGeneration,
      status: "ready",
      error: null,
      isSwitching: false
    });
  };

  return {
  ...initialState,

  can: (capability: WorkspaceCapability) => {
    return get().capabilities.includes(capability);
  },

  explain: (capability: WorkspaceCapability) => {
    const allowed = get().can(capability);
    const currentRole = get().currentWorkspace?.role ?? null;
    const allowedRoles = CAPABILITY_MATRIX[capability];

    return {
      allowed,
      capability,
      currentRole,
      allowedRoles,
      reason: allowed ? undefined : `Requires ${allowedRoles.join(", ")}.`
    };
  },

  hydrateWorkspaceSession: async () => {
    if (hydrationRequest) {
      return hydrationRequest;
    }

    const epoch = nextRequestEpoch();
    set({ status: "loading", error: null });
    const request = (async () => {
      try {
        const result = await workspaceApi.getWorkspaceSession();
        if (epoch !== requestEpoch) return;
        _applyWorkspaceSession(result);
        set({ status: "ready", error: null });
      } catch (err: unknown) {
        if (epoch !== requestEpoch) return;
        clearActiveWorkspaceId();
        set({
          status: "error",
          error: err instanceof Error ? err.message : "Failed to hydrate workspace session",
          currentWorkspace: null,
          memberships: [],
          capabilities: [],
          isSwitching: false
        });
      } finally {
        if (hydrationRequestEpoch === epoch) {
          hydrationRequest = null;
          hydrationRequestEpoch = null;
        }
      }
    })();
    hydrationRequest = request;
    hydrationRequestEpoch = epoch;

    return hydrationRequest;
  },

  refreshWorkspaces: async () => {
    const epoch = nextRequestEpoch();
    set({ error: null });
    try {
      const result = await workspaceApi.getWorkspaceSession();
      if (epoch !== requestEpoch) return;
      _applyWorkspaceSession(result);
    } catch (err: unknown) {
      if (epoch !== requestEpoch) return;
      set({
        error: err instanceof Error ? err.message : "Failed to refresh workspaces",
        isSwitching: false,
        status: get().currentWorkspace ? "ready" : "error"
      });
      throw err;
    }
  },

  switchWorkspace: async (workspaceId: string) => {
    const executionState = useTaskExecutionStore.getState();
    if (
      executionState.activeOperationId !== null ||
      executionState.taskStatus === "pending" ||
      executionState.taskStatus === "running"
    ) {
      throw new WorkspaceSwitchBlockedError(
        "active_execution",
        "Cannot switch workspace while a task is running"
      );
    }
    const pStore = useWorkflowPersistenceStore.getState();
    if (pStore.isDirty || pStore.hasLocalDraft || pStore.pendingConflict !== null) {
      throw new WorkspaceSwitchBlockedError(
        "unsaved_changes",
        "Cannot switch workspace with unsaved changes or active conflict"
      );
    }
    const epoch = nextRequestEpoch();
    set({ isSwitching: true });
    try {
      const result = await workspaceApi.switchWorkspace({ workspaceId });
      if (epoch !== requestEpoch) return;
      if (!result.currentWorkspace) {
        throw new TypeError("Workspace switch returned no current workspace");
      }
      _applyWorkspaceSession(result);
    } finally {
      if (epoch === requestEpoch) set({ isSwitching: false });
    }
  },

  createWorkspace: async (payload: CreateWorkspaceRequest) => {
    const result = await workspaceApi.createWorkspace(payload);
    await get().refreshWorkspaces();
    return result;
  },

  updateWorkspace: async (workspaceId: string, payload: UpdateWorkspaceRequest) => {
    const result = await workspaceApi.updateWorkspace(workspaceId, payload);
    await get().refreshWorkspaces();
    return result;
  },

  resetWorkspaceState: () => {
    nextRequestEpoch();
    hydrationRequest = null;
    hydrationRequestEpoch = null;
    setActiveWorkspaceId(null);
    set({ ...initialState, contextGeneration: nextContextGeneration() });
  }
  };
});

export function captureWorkspaceContext(): WorkspaceContextToken {
  const state = useWorkspaceStore.getState();
  return {
    workspaceId: state.currentWorkspace?.id ?? null,
    generation: state.contextGeneration
  };
}

export function isWorkspaceContextCurrent(token: WorkspaceContextToken): boolean {
  const current = captureWorkspaceContext();
  return current.workspaceId === token.workspaceId && current.generation === token.generation;
}
