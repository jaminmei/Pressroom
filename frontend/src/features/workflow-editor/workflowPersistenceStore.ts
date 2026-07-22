import { create } from "zustand";

import type { WorkflowVersionRecord } from "@/services/workflowApi";

export type { WorkflowVersionRecord };

export interface WorkflowActorSummary {
  user_id: string;
  email: string;
  name?: string | null;
}

export interface WorkflowVersionConflictDetails {
  workflow_id?: string;
  workflow_key?: string;
  base_version?: number;
  latest_version?: number;
  current_name?: string | null;
  last_saved_by?: WorkflowActorSummary | null;
  updated_at?: string;
}

interface WorkflowPersistenceState {
  workflowId: string | null;
  workflowKey: string | null;
  workflowName: string | null;
  publishedVersion: number | null;
  latestVersion: number;
  baseVersion: number | null;
  versions: WorkflowVersionRecord[];
  isDirty: boolean;
  lastSavedAt: string | null;
  createdBy: WorkflowActorSummary | null;
  lastSavedBy: WorkflowActorSummary | null;
  newerVersionAvailable: boolean;
  hasLocalDraft: boolean;
  localDraftOwnerId: string | null;
  localDraftCacheKey: string | null;
  pendingConflict: WorkflowVersionConflictDetails | null;
  setWorkflowMeta: (payload: {
    workflowId: string;
    workflowKey?: string | null;
    workflowName?: string | null;
    publishedVersion?: number | null;
    latestVersion?: number;
    baseVersion?: number | null;
    lastSavedAt?: string | null;
    createdBy?: WorkflowActorSummary | null;
    lastSavedBy?: WorkflowActorSummary | null;
  }) => void;
  setVersions: (versions: WorkflowVersionRecord[]) => void;
  setDirty: (dirty: boolean) => void;
  setLocalDraftState: (payload: {
    hasLocalDraft?: boolean;
    localDraftOwnerId?: string | null;
    localDraftCacheKey?: string | null;
  }) => void;
  setPendingConflict: (conflict: WorkflowVersionConflictDetails | null) => void;
  setNewerVersionAvailable: (value: boolean) => void;
  reset: () => void;
}

export const initialWorkflowPersistenceState: Pick<
  WorkflowPersistenceState,
  | "workflowId"
  | "workflowKey"
  | "workflowName"
  | "publishedVersion"
  | "latestVersion"
  | "baseVersion"
  | "versions"
  | "isDirty"
  | "lastSavedAt"
  | "createdBy"
  | "lastSavedBy"
  | "newerVersionAvailable"
  | "hasLocalDraft"
  | "localDraftOwnerId"
  | "localDraftCacheKey"
  | "pendingConflict"
> = {
  workflowId: null,
  workflowKey: null,
  workflowName: null,
  publishedVersion: null,
  latestVersion: 0,
  baseVersion: null,
  versions: [],
  isDirty: false,
  lastSavedAt: null,
  createdBy: null,
  lastSavedBy: null,
  newerVersionAvailable: false,
  hasLocalDraft: false,
  localDraftOwnerId: null,
  localDraftCacheKey: null,
  pendingConflict: null
};

export const useWorkflowPersistenceStore = create<WorkflowPersistenceState>((set) => ({
  ...initialWorkflowPersistenceState,
  setWorkflowMeta: ({
    workflowId,
    workflowKey,
    workflowName,
    publishedVersion,
    latestVersion,
    baseVersion,
    lastSavedAt,
    createdBy,
    lastSavedBy
  }) =>
    set((state) => ({
      workflowId,
      workflowKey: workflowKey !== undefined ? workflowKey : state.workflowKey,
      workflowName: workflowName !== undefined ? workflowName : state.workflowName,
      publishedVersion: publishedVersion !== undefined ? publishedVersion : state.publishedVersion,
      latestVersion: latestVersion !== undefined ? latestVersion : state.latestVersion,
      baseVersion: baseVersion !== undefined ? baseVersion : state.baseVersion,
      lastSavedAt: lastSavedAt !== undefined ? lastSavedAt : state.lastSavedAt,
      createdBy: createdBy !== undefined ? createdBy : state.createdBy,
      lastSavedBy: lastSavedBy !== undefined ? lastSavedBy : state.lastSavedBy
    })),
  setVersions: (versions) => set({ versions }),
  setDirty: (dirty) => set({ isDirty: dirty }),
  setLocalDraftState: ({ hasLocalDraft, localDraftOwnerId, localDraftCacheKey }) =>
    set((state) => ({
      hasLocalDraft: hasLocalDraft !== undefined ? hasLocalDraft : state.hasLocalDraft,
      localDraftOwnerId: localDraftOwnerId !== undefined ? localDraftOwnerId : state.localDraftOwnerId,
      localDraftCacheKey: localDraftCacheKey !== undefined ? localDraftCacheKey : state.localDraftCacheKey
    })),
  setPendingConflict: (pendingConflict) => set({ pendingConflict }),
  setNewerVersionAvailable: (newerVersionAvailable) => set({ newerVersionAvailable }),
  reset: () => set({ ...initialWorkflowPersistenceState })
}));
