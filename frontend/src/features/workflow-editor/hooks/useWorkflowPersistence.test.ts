import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore, initialAuthState } from "@/stores/authStore";
import { useWorkflowPersistence } from "@/features/workflow-editor/hooks/useWorkflowPersistence";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import {
  getWorkflowDetail,
  getWorkflowVersions,
  restoreWorkflowVersion,
  saveWorkflowDraft
} from "@/services/workflowApi";

vi.mock("@/services/workflowApi", () => ({
  getWorkflowDetail: vi.fn(),
  getWorkflowVersions: vi.fn(),
  publishWorkflow: vi.fn(),
  restoreWorkflowVersion: vi.fn(),
  saveWorkflowDraft: vi.fn()
}));

describe("useWorkflowPersistence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    useAuthStore.setState({
      ...initialAuthState,
      status: "authenticated",
      currentUser: { id: "usr_1", email: "alice@example.com" },
      hydrateSession: useAuthStore.getState().hydrateSession,
      login: useAuthStore.getState().login,
      register: useAuthStore.getState().register,
      logout: useAuthStore.getState().logout,
      rememberIntendedRoute: useAuthStore.getState().rememberIntendedRoute,
      consumeIntendedRoute: useAuthStore.getState().consumeIntendedRoute,
      allowRedirectCapture: useAuthStore.getState().allowRedirectCapture,
      handleUnauthorized: useAuthStore.getState().handleUnauthorized
    });
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "workspace-test",
        name: "Test Workspace",
        isDefault: true,
        role: "owner",
        capabilities: []
      },
      contextGeneration: 1
    });
    useWorkflowStore.getState().clearCanvas();
    useWorkflowStore.getState().setNodeRegistry({
      nodes: [
        {
          node_type: "engine/ocr",
          display_name: "OCR",
          category: "engine",
          config_schema: {
            type: "object",
            properties: {}
          }
        },
        {
          node_type: "output/markdown",
          display_name: "Markdown",
          category: "output",
          config_schema: {
            type: "object",
            properties: {}
          }
        },
        {
          node_type: "end/final",
          display_name: "Workflow End",
          category: "end",
          config_schema: {
            type: "object",
            properties: {}
          }
        }
      ],
      connection_rules: []
    });
    useWorkflowStore.getState().setNodes([
      {
        id: "engine_ocr_1",
        type: "engine/ocr",
        position: { x: 120, y: 140 },
        data: {
          label: "OCR",
          config: { language: "zh" },
          configSchema: {
            type: "object",
            properties: {}
          }
        }
      }
    ]);
    useWorkflowStore.getState().setEdges([]);

    useWorkflowPersistenceStore.getState().reset();
    useWorkflowPersistenceStore.getState().setWorkflowMeta({
      workflowId: "wk_1",
      workflowKey: "wk_shared_1",
      workflowName: "Invoice OCR",
      baseVersion: 3,
      latestVersion: 3,
      publishedVersion: 2,
      lastSavedAt: "2026-03-04T09:00:00Z"
    });

    vi.mocked(restoreWorkflowVersion).mockResolvedValue({
      success: true,
      data: {
        workflow_id: "wk_2",
        restored_version: 1
      }
    });

    vi.mocked(getWorkflowDetail).mockResolvedValue({
      id: "wk_2",
      workflow_key: "wk_shared_2",
      definition: {
        nodes: [
          {
            id: "engine_ocr_1",
            type: "engine/ocr",
            config: { language: "zh" },
            position: { x: 120, y: 140 }
          }
        ],
        connections: []
      },
      created_at: "2026-03-04T09:00:00Z",
      updated_at: "2026-03-04T09:02:00Z",
      published_version: 2,
      latest_version: 4,
      created_by: { user_id: "usr_1", email: "alice@example.com" },
      last_saved_by: { user_id: "usr_2", email: "bob@example.com" }
    });

    vi.mocked(getWorkflowVersions).mockResolvedValue({
      success: true,
      data: [{ version: 2, status: "published", created_at: "2026-03-03T11:00:00Z" }]
    });
  });

  it("marks workflow dirty after restore and resolves restored workflow_id fallback", async () => {
    const { result } = renderHook(() => useWorkflowPersistence());

    await act(async () => {
      const restored = await result.current.restoreVersion(1);
      expect(restored).toBe(true);
    });

    await waitFor(() => {
      const state = useWorkflowPersistenceStore.getState();
      expect(state.workflowId).toBe("wk_2");
      expect(state.workflowKey).toBe("wk_shared_2");
      expect(state.isDirty).toBe(true);
    });

    expect(restoreWorkflowVersion).toHaveBeenCalledWith("wk_shared_1", 1);
    expect(getWorkflowDetail).toHaveBeenCalledWith("wk_2");
    expect(getWorkflowVersions).toHaveBeenCalledWith("wk_shared_2");
  });

  it("surfaces workflow conflict details when save returns a stale base_version response", async () => {
    vi.mocked(saveWorkflowDraft).mockRejectedValue({
      response: {
        data: {
          error_code: "WORKFLOW_VERSION_CONFLICT",
          details: {
            workflow_id: "wk_1",
            workflow_key: "wk_shared_1",
            base_version: 3,
            latest_version: 4,
            current_name: "Invoice OCR v4",
            last_saved_by: { user_id: "usr_2", email: "bob@example.com" },
            updated_at: "2026-03-19T09:30:00Z"
          }
        }
      }
    });

    const { result } = renderHook(() => useWorkflowPersistence());

    await act(async () => {
      const saved = await result.current.saveDraft();
      expect(saved).toBe(false);
    });

    expect(useWorkflowPersistenceStore.getState()).toMatchObject({
      newerVersionAvailable: true,
      pendingConflict: {
        workflow_key: "wk_shared_1",
        latest_version: 4,
        current_name: "Invoice OCR v4"
      }
    });
  });

  it("loads a user-bound local draft ahead of the shared saved definition", async () => {
    vi.mocked(getWorkflowDetail).mockResolvedValueOnce({
      id: "wf_3",
      workflow_key: "wk_shared_3",
      name: "Shared OCR",
      description: "shared",
      definition: {
        nodes: [
          {
            id: "engine_ocr_1",
            type: "engine/ocr",
            config: { language: "en" },
            position: { x: 120, y: 140 }
          }
        ],
        connections: []
      },
      created_at: "2026-03-04T09:00:00Z",
      updated_at: "2026-03-04T09:02:00Z",
      published_version: 1,
      latest_version: 4,
      created_by: { user_id: "usr_1", email: "alice@example.com" },
      last_saved_by: { user_id: "usr_2", email: "bob@example.com" }
    });

    window.localStorage.setItem(
      "dc.workflow.local-draft.usr_1.workspace-test.wk_shared_3.4",
      JSON.stringify({
        definition: {
          nodes: [
            {
              id: "engine_ocr_1",
              type: "engine/ocr",
              config: { language: "zh" },
              position: { x: 120, y: 140 }
            }
          ],
          connections: []
        },
        saved_at: "2026-03-19T10:00:00Z",
        workflow_id: "wf_3",
        workflow_key: "wk_shared_3",
        workflow_name: "Shared OCR",
        base_version: 4,
        user_id: "usr_1"
      })
    );

    const { result } = renderHook(() => useWorkflowPersistence());

    await act(async () => {
      const loaded = await result.current.loadWorkflow("wf_3");
      expect(loaded).toBe(true);
    });

    expect(useWorkflowPersistenceStore.getState()).toMatchObject({
      workflowId: "wf_3",
      workflowKey: "wk_shared_3",
      baseVersion: 4,
      hasLocalDraft: true,
      localDraftCacheKey: "dc.workflow.local-draft.usr_1.workspace-test.wk_shared_3.4"
    });
    expect(useWorkflowStore.getState().nodeConfigs.engine_ocr_1).toEqual({ language: "zh" });
    expect(getWorkflowVersions).toHaveBeenCalledWith("wk_shared_3");
  });

  it("repairs legacy persisted workflows during load", async () => {
    vi.mocked(getWorkflowDetail).mockResolvedValueOnce({
      id: "wk_legacy",
      definition: {
        nodes: [
          {
            id: "engine_ocr_1",
            type: "engine/ocr",
            config: { language: "zh" },
            position: { x: 120, y: 140 }
          },
          {
            id: "output_1",
            type: "output/markdown",
            config: {},
            position: { x: 420, y: 140 }
          }
        ],
        connections: [{ source: "engine_ocr_1", target: "output_1" }]
      },
      created_at: "2026-03-04T09:00:00Z",
      updated_at: "2026-03-04T09:02:00Z",
      published_version: 2,
      latest_version: 4
    });

    const { result } = renderHook(() => useWorkflowPersistence());

    await act(async () => {
      const loaded = await result.current.loadWorkflow("wk_legacy");
      expect(loaded).toBe(true);
    });

    const state = useWorkflowStore.getState();
    expect(state.nodes.find((node) => node.id === "output_1")).toBeUndefined();
    expect(state.nodes.find((node) => node.type === "end/final")).toBeUndefined();
    expect(state.edges).toEqual([]);
    expect(state.selectedNodeId).toBe("engine_ocr_1");
  });
});
