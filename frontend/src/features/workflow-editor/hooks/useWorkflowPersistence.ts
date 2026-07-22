import { isAxiosError, type AxiosError } from "axios";
import { message } from "antd";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import { useAuthStore } from "@/stores/authStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import {
  ensureSingleEndNodeGraph,
  resolvePreferredEditableNodeId
} from "@/features/workflow-editor/utils/endNodeRepair";
import {
  useWorkflowPersistenceStore,
  type WorkflowActorSummary,
  type WorkflowVersionConflictDetails,
  type WorkflowVersionRecord
} from "@/features/workflow-editor/workflowPersistenceStore";
import {
  getWorkflowDetail,
  getWorkflowVersionDetail,
  getWorkflowVersions,
  publishUnifiedWorkflow,
  publishAsWorkflow as publishAsWorkflowApi,
  restoreWorkflowVersion,
  saveWorkflowDraft,
  type WorkflowDetailResponse,
  type WorkflowImportExportPayload
} from "@/services/workflowApi";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

interface WorkflowConflictErrorEnvelope {
  error_code?: string;
  message?: string;
  details?: WorkflowVersionConflictDetails;
}

interface UseWorkflowPersistenceResult {
  workflowId: string | null;
  workflowKey: string | null;
  workflowName: string | null;
  isDirty: boolean;
  publishedVersion: number | null;
  latestVersion: number;
  baseVersion: number | null;
  versions: WorkflowVersionRecord[];
  newerVersionAvailable: boolean;
  pendingConflict: WorkflowVersionConflictDetails | null;
  hasLocalDraft: boolean;
  lastSavedBy: WorkflowActorSummary | null;
  lastSavedAt: string | null;
  saveDraft: () => Promise<boolean>;
  saveAsWorkflow: (name: string) => Promise<boolean>;
  publishUnified: (options?: { name?: string; description?: string }) => Promise<boolean>;
  publishAsWorkflow: (name: string, description?: string) => Promise<boolean>;
  restoreVersion: (version: number) => Promise<boolean>;
  loadWorkflow: (workflowId: string, options?: { preferLocalDraft?: boolean }) => Promise<boolean>;
  revalidateMetadata: () => Promise<boolean>;
  refreshLatestVersion: () => Promise<boolean>;
  loadVersion: (version: number) => Promise<boolean>;
  dismissConflict: () => void;
}

interface StoredWorkflowDraft {
  definition: WorkflowImportExportPayload;
  saved_at: string;
  workflow_id: string;
  workflow_key: string;
  workflow_name?: string | null;
  base_version: number;
  user_id: string;
}

interface WorkflowRequestContext {
  readonly workspaceId: string | null;
  readonly generation: number;
}

interface LocalDraftKeyParts {
  readonly userId: string;
  readonly workspaceId: string;
  readonly workflowKey: string;
  readonly baseVersion: number;
}

const FORCE_DIRTY_SERIALIZED_SENTINEL = "__RESTORE_REQUIRES_SAVE__";
const LOCAL_DRAFT_STORAGE_PREFIX = "dc.workflow.local-draft";

function toDefinition(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  nodeConfigs: Record<string, Record<string, unknown>>
): WorkflowImportExportPayload {
  return {
    nodes: nodes.map((node) => ({
      id: node.id,
      type: node.type,
      config: nodeConfigs[node.id] ?? node.data.config ?? {},
      position: node.position ?? null
    })),
    connections: edges.map((edge) => ({
      source: edge.source,
      target: edge.target
    }))
  };
}

function serializeDefinition(payload: WorkflowImportExportPayload): string {
  return JSON.stringify(payload);
}

function getWorkflowRequestContext(): WorkflowRequestContext {
  const state = useWorkspaceStore.getState();
  return {
    workspaceId: state.currentWorkspace?.id ?? null,
    generation: state.contextGeneration
  };
}

function isWorkflowRequestCurrent(context: WorkflowRequestContext): boolean {
  const current = getWorkflowRequestContext();
  return current.workspaceId === context.workspaceId && current.generation === context.generation;
}

function buildLocalDraftKey(parts: LocalDraftKeyParts): string {
  return `${LOCAL_DRAFT_STORAGE_PREFIX}.${parts.userId}.${parts.workspaceId}.${parts.workflowKey}.${parts.baseVersion}`;
}

function readLocalDraft(key: string): StoredWorkflowDraft | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as StoredWorkflowDraft;
    if (!parsed || typeof parsed !== "object" || !parsed.definition) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function writeLocalDraft(key: string, payload: StoredWorkflowDraft): void {
  window.localStorage.setItem(key, JSON.stringify(payload));
}

function clearLocalDraft(key: string | null | undefined): void {
  if (!key) {
    return;
  }
  window.localStorage.removeItem(key);
}

function normalizeWorkflowKey(detail: WorkflowDetailResponse, workflowId: string): string {
  return detail.workflow_key ?? workflowId;
}

function normalizeBaseVersion(detail: WorkflowDetailResponse): number | null {
  return detail.latest_version ?? null;
}

function extractConflictDetails(error: unknown): WorkflowVersionConflictDetails | null {
  const response = (error as AxiosError<WorkflowConflictErrorEnvelope> | undefined)?.response;
  if (response?.data?.error_code !== "WORKFLOW_VERSION_CONFLICT") {
    return null;
  }
  return response.data.details ?? null;
}

export function useWorkflowPersistence(): UseWorkflowPersistenceResult {
  const { t } = useTranslation("workflows");
  const currentUser = useAuthStore((state) => state.currentUser);
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id ?? null);
  const generation = useWorkspaceStore((state) => state.contextGeneration);
  const nodes = useWorkflowStore((state) => state.nodes);
  const edges = useWorkflowStore((state) => state.edges);
  const nodeConfigs = useWorkflowStore((state) => state.nodeConfigs);
  const nodeRegistry = useWorkflowStore((state) => state.nodeRegistry);

  const workflowId = useWorkflowPersistenceStore((state) => state.workflowId);
  const workflowKey = useWorkflowPersistenceStore((state) => state.workflowKey);
  const workflowName = useWorkflowPersistenceStore((state) => state.workflowName);
  const isDirty = useWorkflowPersistenceStore((state) => state.isDirty);
  const publishedVersion = useWorkflowPersistenceStore((state) => state.publishedVersion);
  const latestVersion = useWorkflowPersistenceStore((state) => state.latestVersion);
  const baseVersion = useWorkflowPersistenceStore((state) => state.baseVersion);
  const versions = useWorkflowPersistenceStore((state) => state.versions);
  const newerVersionAvailable = useWorkflowPersistenceStore((state) => state.newerVersionAvailable);
  const pendingConflict = useWorkflowPersistenceStore((state) => state.pendingConflict);
  const hasLocalDraft = useWorkflowPersistenceStore((state) => state.hasLocalDraft);
  const lastSavedBy = useWorkflowPersistenceStore((state) => state.lastSavedBy);
  const lastSavedAt = useWorkflowPersistenceStore((state) => state.lastSavedAt);
  const setWorkflowMeta = useWorkflowPersistenceStore((state) => state.setWorkflowMeta);
  const setVersions = useWorkflowPersistenceStore((state) => state.setVersions);
  const setDirty = useWorkflowPersistenceStore((state) => state.setDirty);
  const setLocalDraftState = useWorkflowPersistenceStore((state) => state.setLocalDraftState);
  const setPendingConflict = useWorkflowPersistenceStore((state) => state.setPendingConflict);
  const setNewerVersionAvailable = useWorkflowPersistenceStore((state) => state.setNewerVersionAvailable);

  const currentDefinition = useMemo(
    () => toDefinition(nodes, edges, nodeConfigs),
    [edges, nodeConfigs, nodes]
  );
  const currentSerialized = useMemo(() => serializeDefinition(currentDefinition), [currentDefinition]);
  const lastServerSerializedRef = useRef<string | null>(null);
  const draftDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const applyWorkflowDefinition = useCallback(
    (definition: WorkflowImportExportPayload) => {
      const mappedNodes = definition.nodes.map((node, index) => {
        const normalizedType = node.type;
        const metadata = nodeRegistry.nodes.find((item) => item.node_type === normalizedType);
        const nodeTypeParts = normalizedType.split("/");
        const namePart = nodeTypeParts[nodeTypeParts.length - 1] ?? normalizedType;
        return {
          id: node.id,
          type: normalizedType,
          position:
            typeof node.position === "object" && node.position !== null
              ? (node.position as { x: number; y: number })
              : { x: 140 + index * 20, y: 120 + index * 20 },
          data: {
            label: metadata?.display_name ?? namePart.toUpperCase(),
            config: (() => {
              const cfg = node.config ?? {};
              if (normalizedType.startsWith("input/")) {
                const { file: _, ...rest } = cfg;
                return rest;
              }
              return cfg;
            })(),
            configSchema: metadata?.config_schema ?? { type: "object", properties: {} },
            inputTypes: metadata?.input_types,
            outputTypes: metadata?.output_types
          }
        };
      });
      const mappedEdges = definition.connections.map((connection, index) => ({
        id: `edge_${index}_${connection.source}_${connection.target}`,
        source: connection.source,
        target: connection.target
      }));
      const repairedGraph = ensureSingleEndNodeGraph({
        nodes: mappedNodes,
        edges: mappedEdges,
        registry: nodeRegistry
      });
      const selectedNodeId = resolvePreferredEditableNodeId(repairedGraph.nodes);
      useWorkflowStore.setState((state) => ({
        ...state,
        nodes: repairedGraph.nodes,
        edges: repairedGraph.edges,
        nodeConfigs: Object.fromEntries(repairedGraph.nodes.map((node) => [node.id, node.data.config ?? {}])),
        uploadedFiles: {},
        selectedNodeId
      }));
    },
    [nodeRegistry]
  );

  useEffect(() => {
    if (lastServerSerializedRef.current === null) {
      lastServerSerializedRef.current = currentSerialized;
      return;
    }
    setDirty(lastServerSerializedRef.current !== currentSerialized);
  }, [currentSerialized, setDirty]);

  useEffect(() => {
    const draftKey = useWorkflowPersistenceStore.getState().localDraftCacheKey;
    const persistedWorkflowId = useWorkflowPersistenceStore.getState().workflowId;
    const persistedWorkflowKey = useWorkflowPersistenceStore.getState().workflowKey;
    const persistedBaseVersion = useWorkflowPersistenceStore.getState().baseVersion;

    if (!draftKey || !currentUser?.id || !workspaceId || !persistedWorkflowId || !persistedWorkflowKey || !persistedBaseVersion) {
      return;
    }
    const userId = currentUser.id;

    if (lastServerSerializedRef.current !== null && lastServerSerializedRef.current === currentSerialized) {
      clearLocalDraft(draftKey);
      setLocalDraftState({
        hasLocalDraft: false,
        localDraftOwnerId: currentUser.id,
        localDraftCacheKey: draftKey
      });
      return;
    }

    if (draftDebounceRef.current) {
      clearTimeout(draftDebounceRef.current);
    }
    const requestContext = { workspaceId, generation };
    draftDebounceRef.current = setTimeout(() => {
      if (!isWorkflowRequestCurrent(requestContext)) {
        return;
      }
      writeLocalDraft(draftKey, {
        definition: currentDefinition,
        saved_at: new Date().toISOString(),
        workflow_id: persistedWorkflowId,
        workflow_key: persistedWorkflowKey,
        workflow_name: useWorkflowPersistenceStore.getState().workflowName,
        base_version: persistedBaseVersion,
        user_id: userId
      });
      setLocalDraftState({
        hasLocalDraft: true,
        localDraftOwnerId: userId,
        localDraftCacheKey: draftKey
      });
    }, 300);

    return () => {
      if (draftDebounceRef.current) {
        clearTimeout(draftDebounceRef.current);
      }
    };
  }, [currentDefinition, currentSerialized, currentUser?.id, generation, setLocalDraftState, workspaceId]);

  const refreshVersions = useCallback(
    async (targetWorkflowKey: string, requestContext = getWorkflowRequestContext()) => {
      const response = await getWorkflowVersions(targetWorkflowKey);
      if (!isWorkflowRequestCurrent(requestContext)) {
        return;
      }
      setVersions(response.data ?? []);
    },
    [setVersions]
  );

  const loadWorkflowAction = useCallback(
    async (targetWorkflowId: string, options?: { preferLocalDraft?: boolean }): Promise<boolean> => {
      const requestContext = { workspaceId, generation };
      const preferLocalDraft = options?.preferLocalDraft ?? true;
      const detail = await getWorkflowDetail(targetWorkflowId);
      if (!isWorkflowRequestCurrent(requestContext)) {
        return false;
      }
      const normalizedWorkflowKey = normalizeWorkflowKey(detail, targetWorkflowId);
      const normalizedBaseVersion = normalizeBaseVersion(detail);
      const draftKey =
        currentUser?.id && requestContext.workspaceId && normalizedBaseVersion
          ? buildLocalDraftKey({
              userId: currentUser.id,
              workspaceId: requestContext.workspaceId,
              workflowKey: normalizedWorkflowKey,
              baseVersion: normalizedBaseVersion
            })
          : null;
      const storedDraft = draftKey && preferLocalDraft ? readLocalDraft(draftKey) : null;
      const serverSerialized = serializeDefinition(detail.definition);

      if (storedDraft) {
        applyWorkflowDefinition(storedDraft.definition);
        lastServerSerializedRef.current = serverSerialized;
        setDirty(serverSerialized !== serializeDefinition(storedDraft.definition));
      } else {
        applyWorkflowDefinition(detail.definition);
        lastServerSerializedRef.current = serverSerialized;
        setDirty(false);
      }

      setWorkflowMeta({
        workflowId: detail.id,
        workflowKey: normalizedWorkflowKey,
        workflowName: detail.name ?? null,
        publishedVersion: detail.published_version,
        latestVersion: detail.latest_version,
        baseVersion: normalizedBaseVersion,
        lastSavedAt: detail.updated_at,
        createdBy: detail.created_by ?? null,
        lastSavedBy: detail.last_saved_by ?? null
      });
      setLocalDraftState({
        hasLocalDraft: Boolean(storedDraft),
        localDraftOwnerId: currentUser?.id ?? null,
        localDraftCacheKey: draftKey
      });
      setPendingConflict(null);
      setNewerVersionAvailable(false);
      await refreshVersions(normalizedWorkflowKey, requestContext);
      return isWorkflowRequestCurrent(requestContext);
    },
    [applyWorkflowDefinition, currentUser?.id, generation, refreshVersions, setDirty, setLocalDraftState, setNewerVersionAvailable, setPendingConflict, setWorkflowMeta, workspaceId]
  );

  const saveViaContract = useCallback(
    async ({ name, saveAs }: { name?: string | null; saveAs?: boolean } = {}): Promise<boolean> => {
      const requestContext = { workspaceId, generation };
      const currentState = useWorkflowPersistenceStore.getState();
      const trimmedName = name?.trim();
      if (saveAs && !trimmedName) {
        message.warning(t("editorText.saveAsNameRequired"));
        return false;
      }

      const previousDraftKey = currentState.localDraftCacheKey;
      const response = await saveWorkflowDraft({
        workflow_id: saveAs ? undefined : currentState.workflowId ?? undefined,
        workflow_key: saveAs ? undefined : currentState.workflowKey ?? undefined,
        base_version: saveAs ? undefined : currentState.baseVersion,
        name: trimmedName ?? currentState.workflowName ?? undefined,
        description: undefined,
        definition: currentDefinition
      });
      if (!isWorkflowRequestCurrent(requestContext)) {
        return false;
      }

      clearLocalDraft(previousDraftKey);

      const nextWorkflowId = response.data.id;
      const nextWorkflowKey = response.data.workflow_key ?? currentState.workflowKey ?? nextWorkflowId;
      const nextLatestVersion = response.data.latest_version ?? currentState.latestVersion;
      const nextBaseVersion = response.data.latest_version ?? response.data.base_version ?? currentState.baseVersion;
      const nextDraftKey =
        currentUser?.id && requestContext.workspaceId && nextBaseVersion
          ? buildLocalDraftKey({
              userId: currentUser.id,
              workspaceId: requestContext.workspaceId,
              workflowKey: nextWorkflowKey,
              baseVersion: nextBaseVersion
            })
          : null;

      setWorkflowMeta({
        workflowId: nextWorkflowId,
        workflowKey: nextWorkflowKey,
        workflowName: response.data.name ?? trimmedName ?? currentState.workflowName,
        latestVersion: nextLatestVersion,
        baseVersion: nextBaseVersion,
        publishedVersion: response.data.published_version,
        lastSavedAt: response.data.updated_at,
        createdBy: response.data.created_by ?? currentState.createdBy,
        lastSavedBy: response.data.last_saved_by ?? currentState.lastSavedBy
      });
      lastServerSerializedRef.current = currentSerialized;
      setDirty(false);
      setLocalDraftState({
        hasLocalDraft: false,
        localDraftOwnerId: currentUser?.id ?? null,
        localDraftCacheKey: nextDraftKey
      });
      setPendingConflict(null);
      setNewerVersionAvailable(false);
      await refreshVersions(nextWorkflowKey, requestContext);
      if (!isWorkflowRequestCurrent(requestContext)) {
        return false;
      }
      message.success(saveAs ? t("editorText.savedAsNew") : t("editorText.workflowSaved"));
      return true;
    },
    [currentDefinition, currentSerialized, currentUser?.id, generation, refreshVersions, setDirty, setLocalDraftState, setNewerVersionAvailable, setPendingConflict, setWorkflowMeta, t, workspaceId]
  );

  const saveDraftAction = useCallback(async (): Promise<boolean> => {
    const requestContext = { workspaceId, generation };
    try {
      return await saveViaContract();
    } catch (error) {
      if (!(error instanceof Error) && (typeof error !== "object" || error === null)) throw error;
      if (!isWorkflowRequestCurrent(requestContext)) return false;
      const conflictDetails = extractConflictDetails(error);
      if (conflictDetails) {
        setPendingConflict(conflictDetails);
        setNewerVersionAvailable(true);
        message.warning(t("editorText.newerVersionSaveWarning"));
        return false;
      }
      message.error(t("saveFailed"));
      return false;
    }
  }, [generation, saveViaContract, setNewerVersionAvailable, setPendingConflict, t, workspaceId]);

  const saveAsWorkflowAction = useCallback(
    async (name: string): Promise<boolean> => {
      const requestContext = { workspaceId, generation };
      try {
        return await saveViaContract({ name, saveAs: true });
      } catch (error) {
        if (!(error instanceof Error) && (typeof error !== "object" || error === null)) throw error;
        if (!isWorkflowRequestCurrent(requestContext)) return false;
        message.error(t("saveAsFailed"));
        return false;
      }
    },
    [generation, saveViaContract, t, workspaceId]
  );

  const publishUnifiedAction = useCallback(async (options?: { name?: string; description?: string }): Promise<boolean> => {
    const requestContext = { workspaceId, generation };
    const definition = toDefinition(nodes, edges, nodeConfigs);
    if (workflowId) {
      try {
        const result = await publishUnifiedWorkflow({
          workflow_id: workflowId,
          definition,
          base_version: baseVersion ?? undefined,
          description: options?.description,
        });
        if (!isWorkflowRequestCurrent(requestContext)) return false;
        setWorkflowMeta({
          workflowId: result.data.workflow_id,
          latestVersion: result.data.version,
          publishedVersion: result.data.published_version,
          baseVersion: result.data.version,
        });
        setDirty(false);
        setNewerVersionAvailable(false);
        await refreshVersions(useWorkflowPersistenceStore.getState().workflowKey ?? workflowId, requestContext);
        if (!isWorkflowRequestCurrent(requestContext)) return false;
        message.success(t("editorText.workflowPublished", { version: result.data.version }));
        return true;
      } catch (err) {
        if (!(err instanceof Error) && (typeof err !== "object" || err === null)) throw err;
        if (!isWorkflowRequestCurrent(requestContext)) return false;
        if (isAxiosError(err) && err.response?.status === 409) {
          const detail = (err.response.data as { details?: { duplicate_of_version?: number } })?.details?.duplicate_of_version;
          if (detail) {
            message.warning(t("editorText.noChangesSince", { version: detail }));
            return false;
          }
          setPendingConflict((err.response.data as WorkflowConflictErrorEnvelope).details ?? null);
          setNewerVersionAvailable(true);
          message.error(t("versionConflict"));
          return false;
        }
        const serverMsg = isAxiosError(err) && err.response?.data?.message
          ? String(err.response.data.message)
          : t("editorText.publishFailed");
        const validationErrors = isAxiosError(err) && err.response?.data?.details?.errors;
        if (Array.isArray(validationErrors) && validationErrors.length > 0) {
          const errorSummary = validationErrors
            .slice(0, 3)
            .map((e: { message?: string; node_id?: string }) =>
              e.node_id ? `${e.node_id}: ${e.message ?? "error"}` : (e.message ?? "error"))
            .join("\n");
          message.error({ content: `${serverMsg}\n${errorSummary}`, duration: 6 });
        } else {
          message.error(serverMsg);
        }
        return false;
      }
    } else {
      if (!options?.name) return false;
      try {
        const result = await publishUnifiedWorkflow({
          name: options.name,
          definition,
          description: options.description,
        });
        if (!isWorkflowRequestCurrent(requestContext)) return false;
        setWorkflowMeta({
          workflowId: result.data.workflow_id,
          workflowKey: result.data.workflow_key ?? null,
          workflowName: result.data.name ?? options.name,
          latestVersion: result.data.version,
          publishedVersion: result.data.published_version,
          baseVersion: result.data.version,
        });
        setDirty(false);
        setNewerVersionAvailable(false);
        await refreshVersions(useWorkflowPersistenceStore.getState().workflowKey ?? "", requestContext);
        if (!isWorkflowRequestCurrent(requestContext)) return false;
        message.success(t("editorText.workflowNamePublished", { name: options.name, version: result.data.version }));
        return true;
      } catch (err) {
        if (!(err instanceof Error) && (typeof err !== "object" || err === null)) throw err;
        if (!isWorkflowRequestCurrent(requestContext)) return false;
        const serverMsg = isAxiosError(err) && err.response?.data?.message
          ? String(err.response.data.message)
          : t("editorText.publishFailed");
        const validationErrors = isAxiosError(err) && err.response?.data?.details?.errors;
        if (Array.isArray(validationErrors) && validationErrors.length > 0) {
          const errorSummary = validationErrors
            .slice(0, 3)
            .map((e: { message?: string; node_id?: string }) =>
              e.node_id ? `${e.node_id}: ${e.message ?? "error"}` : (e.message ?? "error"))
            .join("\n");
          message.error({ content: `${serverMsg}\n${errorSummary}`, duration: 6 });
        } else {
          message.error(serverMsg);
        }
        return false;
      }
    }
  }, [workflowId, baseVersion, nodes, edges, nodeConfigs, setWorkflowMeta, setDirty, setNewerVersionAvailable, setPendingConflict, refreshVersions, workspaceId, generation, t]);

  const publishAsWorkflowAction = useCallback(async (name: string, description?: string): Promise<boolean> => {
    const requestContext = { workspaceId, generation };
    if (!workflowId) return false;
    try {
      const result = await publishAsWorkflowApi({
        workflow_id: workflowId,
        name,
        description,
      });
      if (!isWorkflowRequestCurrent(requestContext)) return false;
      setWorkflowMeta({
        workflowId: result.data.workflow_id,
        workflowKey: result.data.workflow_key ?? null,
        workflowName: result.data.name ?? name,
        latestVersion: result.data.version,
        publishedVersion: result.data.published_version,
        baseVersion: result.data.version,
      });
      setDirty(false);
      setNewerVersionAvailable(false);
      await refreshVersions(useWorkflowPersistenceStore.getState().workflowKey ?? "", requestContext);
      if (!isWorkflowRequestCurrent(requestContext)) return false;
      message.success(t("editorText.publishedAsNew", { name, version: result.data.version }));
      return true;
    } catch (err) {
      if (!(err instanceof Error) && (typeof err !== "object" || err === null)) throw err;
      if (!isWorkflowRequestCurrent(requestContext)) return false;
      if (isAxiosError(err)) {
        const serverMsg = err.response?.data?.message
          ? String(err.response.data.message)
          : t("editorText.publishAsFailed");
        const validationErrors = err.response?.data?.details?.errors;
        if (Array.isArray(validationErrors) && validationErrors.length > 0) {
          const errorSummary = validationErrors
            .slice(0, 3)
            .map((e: { message?: string; node_id?: string }) =>
              e.node_id ? `${e.node_id}: ${e.message ?? "error"}` : (e.message ?? "error"))
            .join("\n");
          message.error({ content: `${serverMsg}\n${errorSummary}`, duration: 6 });
        } else {
          message.error(serverMsg);
        }
      } else {
        message.error(t("editorText.publishAsFailed"));
      }
      return false;
    }
  }, [workflowId, setWorkflowMeta, setDirty, setNewerVersionAvailable, refreshVersions, workspaceId, generation, t]);

  const restoreVersionAction = useCallback(
    async (version: number): Promise<boolean> => {
      const requestContext = { workspaceId, generation };
      const state = useWorkflowPersistenceStore.getState();
      const targetWorkflowKey = state.workflowKey ?? state.workflowId;
      if (!targetWorkflowKey) {
        message.warning(t("editorText.restoreUnsaved"));
        return false;
      }
      const restoreResponse = await restoreWorkflowVersion(targetWorkflowKey, version);
      if (!isWorkflowRequestCurrent(requestContext)) return false;
      const restoredWorkflowId = restoreResponse.data.id ?? restoreResponse.data.workflow_id ?? state.workflowId;
      if (!restoredWorkflowId) {
        return false;
      }
      const detail = await getWorkflowDetail(restoredWorkflowId);
      if (!isWorkflowRequestCurrent(requestContext)) return false;
      applyWorkflowDefinition(detail.definition);
      lastServerSerializedRef.current = FORCE_DIRTY_SERIALIZED_SENTINEL;
      setDirty(true);
      setWorkflowMeta({
        workflowId: detail.id,
        workflowKey: normalizeWorkflowKey(detail, detail.id),
        workflowName: detail.name ?? null,
        publishedVersion: detail.published_version,
        latestVersion: detail.latest_version,
        baseVersion: normalizeBaseVersion(detail),
        lastSavedAt: detail.updated_at,
        createdBy: detail.created_by ?? null,
        lastSavedBy: detail.last_saved_by ?? null
      });
      await refreshVersions(normalizeWorkflowKey(detail, detail.id), requestContext);
      return isWorkflowRequestCurrent(requestContext);
    },
    [applyWorkflowDefinition, generation, refreshVersions, setDirty, setWorkflowMeta, t, workspaceId]
  );

  const revalidateMetadataAction = useCallback(async (): Promise<boolean> => {
    const requestContext = { workspaceId, generation };
    const currentState = useWorkflowPersistenceStore.getState();
    if (!currentState.workflowId) {
      return false;
    }

    const detail = await getWorkflowDetail(currentState.workflowId);
    if (!isWorkflowRequestCurrent(requestContext)) return false;
    const nextLatestVersion = detail.latest_version ?? currentState.latestVersion;
    const nextBaseVersion = currentState.baseVersion ?? normalizeBaseVersion(detail);
    const hasNewerVersion = Boolean(nextBaseVersion && nextLatestVersion > nextBaseVersion);
    setWorkflowMeta({
      workflowId: detail.id,
      workflowKey: normalizeWorkflowKey(detail, detail.id),
      workflowName: detail.name ?? null,
      publishedVersion: detail.published_version,
      latestVersion: nextLatestVersion,
      baseVersion: nextBaseVersion,
      lastSavedAt: detail.updated_at,
      createdBy: detail.created_by ?? null,
      lastSavedBy: detail.last_saved_by ?? null
    });
    setNewerVersionAvailable(hasNewerVersion);
    return hasNewerVersion;
  }, [generation, setNewerVersionAvailable, setWorkflowMeta, workspaceId]);

  const refreshLatestVersionAction = useCallback(async (): Promise<boolean> => {
    const state = useWorkflowPersistenceStore.getState();
    clearLocalDraft(state.localDraftCacheKey);
    setLocalDraftState({
      hasLocalDraft: false,
      localDraftOwnerId: currentUser?.id ?? null,
      localDraftCacheKey: state.localDraftCacheKey
    });
    if (!state.workflowId) {
      return false;
    }
    const reloaded = await loadWorkflowAction(state.workflowId, { preferLocalDraft: false });
    if (reloaded) {
      message.success(t("editorText.latestReloaded"));
    }
    return reloaded;
  }, [currentUser?.id, loadWorkflowAction, setLocalDraftState, t]);

  const loadVersionAction = useCallback(
    async (version: number): Promise<boolean> => {
      const requestContext = { workspaceId, generation };
      const state = useWorkflowPersistenceStore.getState();
      if (!state.workflowId) return false;
      try {
        const result = await getWorkflowVersionDetail(state.workflowId, version);
        if (!isWorkflowRequestCurrent(requestContext)) return false;
        applyWorkflowDefinition(result.data.definition);
        // Don't update baseVersion — version viewing is read-only, just display the DAG
        lastServerSerializedRef.current = FORCE_DIRTY_SERIALIZED_SENTINEL;
        setDirty(true);
        message.info(t("editorText.versionLoaded", { version }));
        return true;
      } catch (error) {
        if (!(error instanceof Error) && (typeof error !== "object" || error === null)) throw error;
        if (!isWorkflowRequestCurrent(requestContext)) return false;
        message.error(t("editorText.versionLoadFailed", { version }));
        return false;
      }
    },
    [applyWorkflowDefinition, generation, setDirty, t, workspaceId]
  );

  const dismissConflict = useCallback(() => {
    setPendingConflict(null);
    setNewerVersionAvailable(false);
  }, [setNewerVersionAvailable, setPendingConflict]);

  return {
    workflowId,
    workflowKey,
    workflowName,
    isDirty,
    publishedVersion,
    latestVersion,
    baseVersion,
    versions,
    newerVersionAvailable,
    pendingConflict,
    hasLocalDraft,
    lastSavedBy,
    lastSavedAt,
    saveDraft: saveDraftAction,
    saveAsWorkflow: saveAsWorkflowAction,
    publishUnified: publishUnifiedAction,
    publishAsWorkflow: publishAsWorkflowAction,
    restoreVersion: restoreVersionAction,
    loadWorkflow: loadWorkflowAction,
    revalidateMetadata: revalidateMetadataAction,
    refreshLatestVersion: refreshLatestVersionAction,
    loadVersion: loadVersionAction,
    dismissConflict
  };
}
