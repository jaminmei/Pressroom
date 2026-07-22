import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";
import { beginTaskOperation, finishTaskOperation, useTaskExecutionStore } from "@/features/task-execution/store";
import * as api from "@/services/api";
import * as workspaceApi from "@/services/workspaceApi";
import * as workspaceReset from "@/stores/workspaceReset";
import { useWorkspaceStore } from "./workspaceStore";
import { CAPABILITY_MATRIX } from "@/types/workspace";

vi.mock("@/services/workspaceApi");
vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    clearActiveWorkspaceId: vi.fn(),
    setActiveWorkspaceId: vi.fn()
  };
});
vi.mock("@/stores/workspaceReset", () => ({
  resetWorkspaceScopedState: vi.fn()
}));
vi.mock("@/features/workflow-editor/workflowPersistenceStore", () => ({
  useWorkflowPersistenceStore: {
    getState: vi.fn()
  }
}));

describe("workspaceStore", () => {
  beforeEach(() => {
    useWorkspaceStore.getState().resetWorkspaceState();
    useTaskExecutionStore.getState().reset();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("should have initial state", () => {
    const state = useWorkspaceStore.getState();
    expect(state.status).toBe("idle");
    expect(state.currentWorkspace).toBeNull();
  });

  it("hydrateWorkspaceSession handles success", async () => {
    const generationBefore = useWorkspaceStore.getState().contextGeneration;
    const mockSession = {
      currentWorkspace: { id: "ws-1", name: "Test WS", isDefault: false, role: "admin" as const, capabilities: [] },
      memberships: [],
      capabilities: ["workflow.run" as const]
    };
    vi.mocked(workspaceApi.getWorkspaceSession).mockResolvedValueOnce(mockSession);

    await useWorkspaceStore.getState().hydrateWorkspaceSession();

    const state = useWorkspaceStore.getState();
    expect(state.status).toBe("ready");
    expect(state.currentWorkspace).toEqual(mockSession.currentWorkspace);
    expect(state.capabilities).toEqual(["workflow.run"]);
    expect(state.contextGeneration).toBeGreaterThan(generationBefore);
    expect(api.setActiveWorkspaceId).toHaveBeenCalledWith("ws-1");
  });

  it("shares one workspace hydration request across concurrent callers", async () => {
    const mockSession = {
      currentWorkspace: { id: "ws-1", name: "Test WS", isDefault: false, role: "admin" as const, capabilities: [] },
      memberships: [],
      capabilities: ["workflow.run" as const]
    };
    vi.mocked(workspaceApi.getWorkspaceSession).mockResolvedValueOnce(mockSession);

    await Promise.all([
      useWorkspaceStore.getState().hydrateWorkspaceSession(),
      useWorkspaceStore.getState().hydrateWorkspaceSession()
    ]);

    expect(workspaceApi.getWorkspaceSession).toHaveBeenCalledTimes(1);
  });

  it("sets the active workspace before exposing ready state", async () => {
    const readyObserver = vi.fn();
    const unsubscribe = useWorkspaceStore.subscribe((state) => {
      if (state.status === "ready") {
        readyObserver();
      }
    });
    vi.mocked(workspaceApi.getWorkspaceSession).mockResolvedValueOnce({
      currentWorkspace: { id: "ws-1", name: "Test WS", isDefault: false, role: "admin", capabilities: [] },
      memberships: [],
      capabilities: []
    });

    await useWorkspaceStore.getState().hydrateWorkspaceSession();
    unsubscribe();

    expect(vi.mocked(api.setActiveWorkspaceId).mock.invocationCallOrder[0]).toBeLessThan(
      readyObserver.mock.invocationCallOrder[0]
    );
  });

  it("hydrateWorkspaceSession handles error", async () => {
    vi.mocked(workspaceApi.getWorkspaceSession).mockRejectedValueOnce(new Error("API Error"));

    await useWorkspaceStore.getState().hydrateWorkspaceSession();

    const state = useWorkspaceStore.getState();
    expect(state.status).toBe("error");
    expect(state.error).toBe("API Error");
    expect(api.clearActiveWorkspaceId).toHaveBeenCalledOnce();
  });

  it("clears failed hydration so one new request can retry", async () => {
    vi.mocked(workspaceApi.getWorkspaceSession)
      .mockRejectedValueOnce(new Error("API Error"))
      .mockResolvedValueOnce({
        currentWorkspace: { id: "ws-2", name: "Retry WS", isDefault: false, role: "admin", capabilities: [] },
        memberships: [],
        capabilities: []
      });

    await useWorkspaceStore.getState().hydrateWorkspaceSession();
    expect(useWorkspaceStore.getState()).toMatchObject({ status: "error", error: "API Error" });
    expect(api.clearActiveWorkspaceId).toHaveBeenCalledOnce();

    await Promise.all([
      useWorkspaceStore.getState().hydrateWorkspaceSession(),
      useWorkspaceStore.getState().hydrateWorkspaceSession()
    ]);

    expect(workspaceApi.getWorkspaceSession).toHaveBeenCalledTimes(2);
    expect(useWorkspaceStore.getState()).toMatchObject({ status: "ready", error: null });
  });

  it("refreshWorkspaces clears a stale error after success", async () => {
    useWorkspaceStore.setState({ error: "Previous refresh failed" });
    const mockSession = {
      currentWorkspace: { id: "ws-refresh", name: "Refreshed WS", isDefault: false, role: "admin" as const, capabilities: [] },
      memberships: [],
      capabilities: ["workspace.view" as const]
    };
    vi.mocked(workspaceApi.getWorkspaceSession).mockResolvedValueOnce(mockSession);

    await useWorkspaceStore.getState().refreshWorkspaces();

    expect(useWorkspaceStore.getState()).toMatchObject({
      currentWorkspace: mockSession.currentWorkspace,
      capabilities: ["workspace.view"],
      error: null
    });
    expect(api.setActiveWorkspaceId).toHaveBeenCalledWith("ws-refresh");
  });

  it("same-workspace refresh updates metadata without resetting scoped state or generation", async () => {
    const currentWorkspace = {
      id: "ws-refresh",
      name: "Before",
      isDefault: false,
      role: "admin" as const,
      capabilities: []
    };
    useWorkspaceStore.setState({
      currentWorkspace,
      memberships: [],
      capabilities: ["workspace.view"],
      contextGeneration: 41
    });
    vi.mocked(workspaceApi.getWorkspaceSession).mockResolvedValueOnce({
      currentWorkspace: { ...currentWorkspace, name: "After" },
      memberships: [],
      capabilities: ["workspace.view", "workflow.run"]
    });

    await useWorkspaceStore.getState().refreshWorkspaces();

    expect(useWorkspaceStore.getState()).toMatchObject({
      currentWorkspace: { id: "ws-refresh", name: "After" },
      contextGeneration: 41
    });
    expect(workspaceReset.resetWorkspaceScopedState).not.toHaveBeenCalled();
  });

  it("implicit fallback refresh resets scoped state and advances generation", async () => {
    const currentWorkspace = {
      id: "ws-old",
      name: "Old",
      isDefault: false,
      role: "admin" as const,
      capabilities: []
    };
    useWorkspaceStore.setState({ currentWorkspace, contextGeneration: 50 });
    vi.mocked(workspaceApi.getWorkspaceSession).mockResolvedValueOnce({
      currentWorkspace: { ...currentWorkspace, id: "ws-fallback", name: "Fallback" },
      memberships: [],
      capabilities: []
    });

    await useWorkspaceStore.getState().refreshWorkspaces();

    expect(workspaceReset.resetWorkspaceScopedState).toHaveBeenCalledOnce();
    expect(useWorkspaceStore.getState().currentWorkspace?.id).toBe("ws-fallback");
    expect(useWorkspaceStore.getState().contextGeneration).not.toBe(50);
  });

  it("drops a late refresh response after a newer refresh wins", async () => {
    let resolveOld!: (value: Awaited<ReturnType<typeof workspaceApi.getWorkspaceSession>>) => void;
    let resolveNew!: (value: Awaited<ReturnType<typeof workspaceApi.getWorkspaceSession>>) => void;
    vi.mocked(workspaceApi.getWorkspaceSession)
      .mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve; }))
      .mockReturnValueOnce(new Promise((resolve) => { resolveNew = resolve; }));

    const oldRequest = useWorkspaceStore.getState().refreshWorkspaces();
    const newRequest = useWorkspaceStore.getState().refreshWorkspaces();
    resolveNew({
      currentWorkspace: { id: "ws-new", name: "New", isDefault: false, role: "admin", capabilities: [] },
      memberships: [],
      capabilities: []
    });
    await newRequest;
    resolveOld({
      currentWorkspace: { id: "ws-old", name: "Old", isDefault: false, role: "admin", capabilities: [] },
      memberships: [],
      capabilities: []
    });
    await oldRequest;

    expect(useWorkspaceStore.getState().currentWorkspace?.id).toBe("ws-new");
  });

  it("a winning refresh settles loading and switching state while dropping a late switch", async () => {
    vi.mocked(useWorkflowPersistenceStore.getState).mockReturnValue({
      isDirty: false,
      hasLocalDraft: false,
      pendingConflict: null
    } as ReturnType<typeof useWorkflowPersistenceStore.getState>);
    let resolveSwitch!: (value: Awaited<ReturnType<typeof workspaceApi.switchWorkspace>>) => void;
    vi.mocked(workspaceApi.switchWorkspace).mockReturnValueOnce(
      new Promise((resolve) => { resolveSwitch = resolve; })
    );
    vi.mocked(workspaceApi.getWorkspaceSession).mockResolvedValueOnce({
      currentWorkspace: { id: "ws-refresh", name: "Refresh", isDefault: false, role: "admin", capabilities: [] },
      memberships: [],
      capabilities: []
    });

    const switchRequest = useWorkspaceStore.getState().switchWorkspace("ws-switch");
    expect(useWorkspaceStore.getState().isSwitching).toBe(true);
    await useWorkspaceStore.getState().refreshWorkspaces();
    resolveSwitch({
      currentWorkspace: { id: "ws-switch", name: "Switch", isDefault: false, role: "admin", capabilities: [] },
      memberships: [],
      capabilities: []
    });
    await switchRequest;

    expect(useWorkspaceStore.getState()).toMatchObject({
      currentWorkspace: { id: "ws-refresh" },
      status: "ready",
      isSwitching: false
    });
  });

  it("reset invalidates an in-flight refresh and never revives its token", async () => {
    let resolveRefresh!: (value: Awaited<ReturnType<typeof workspaceApi.getWorkspaceSession>>) => void;
    vi.mocked(workspaceApi.getWorkspaceSession).mockReturnValueOnce(
      new Promise((resolve) => { resolveRefresh = resolve; })
    );
    const oldGeneration = useWorkspaceStore.getState().contextGeneration;
    const request = useWorkspaceStore.getState().refreshWorkspaces();

    useWorkspaceStore.getState().resetWorkspaceState();
    resolveRefresh({
      currentWorkspace: { id: "ws-revived", name: "Revived", isDefault: false, role: "admin", capabilities: [] },
      memberships: [],
      capabilities: []
    });
    await request;

    expect(useWorkspaceStore.getState().currentWorkspace).toBeNull();
    expect(useWorkspaceStore.getState().contextGeneration).toBeGreaterThan(oldGeneration);
  });

  it("refreshWorkspaces records and rejects a refresh error", async () => {
    const refreshError = new Error("Refresh failed");
    vi.mocked(workspaceApi.getWorkspaceSession).mockRejectedValueOnce(refreshError);

    await expect(useWorkspaceStore.getState().refreshWorkspaces()).rejects.toThrow(
      "Refresh failed"
    );

    expect(useWorkspaceStore.getState().error).toBe("Refresh failed");
  });

  it("can() correctly checks capabilities", () => {
    useWorkspaceStore.setState({ capabilities: ["workflow.run"] });
    expect(useWorkspaceStore.getState().can("workflow.run")).toBe(true);
    expect(useWorkspaceStore.getState().can("workspace.update")).toBe(false);
  });

  it("explain() returns PermissionDecision", () => {
    useWorkspaceStore.setState({
      capabilities: ["workflow.run"],
      currentWorkspace: { id: "ws-1", name: "Test WS", isDefault: false, role: "editor", capabilities: [] }
    });

    const decisionAllowed = useWorkspaceStore.getState().explain("workflow.run");
    expect(decisionAllowed.allowed).toBe(true);
     expect(decisionAllowed.currentRole).toBe("editor");
    expect(decisionAllowed.allowedRoles).toEqual(CAPABILITY_MATRIX["workflow.run"]);
    expect(decisionAllowed.reason).toBeUndefined();

    const decisionDenied = useWorkspaceStore.getState().explain("workspace.update");
    expect(decisionDenied.allowed).toBe(false);
     expect(decisionDenied.currentRole).toBe("editor");
    expect(decisionDenied.allowedRoles).toEqual(CAPABILITY_MATRIX["workspace.update"]);
    expect(decisionDenied.reason).toContain("Requires owner, admin.");
  });

  it("switchWorkspace blocks on dirty state", async () => {
    vi.mocked(useWorkflowPersistenceStore.getState).mockReturnValue({
      isDirty: true,
      hasLocalDraft: false,
      pendingConflict: null
    } as ReturnType<typeof useWorkflowPersistenceStore.getState>);

    await expect(useWorkspaceStore.getState().switchWorkspace("ws-2")).rejects.toMatchObject({
      name: "WorkspaceSwitchBlockedError",
      reason: "unsaved_changes"
    });
    expect(workspaceApi.switchWorkspace).not.toHaveBeenCalled();
    expect(workspaceReset.resetWorkspaceScopedState).not.toHaveBeenCalled();
    expect(api.setActiveWorkspaceId).not.toHaveBeenCalled();
  });

  it("switchWorkspace reports active execution separately from unsaved changes", async () => {
    vi.mocked(useWorkflowPersistenceStore.getState).mockReturnValue({
      isDirty: true,
      hasLocalDraft: false,
      pendingConflict: null
    } as ReturnType<typeof useWorkflowPersistenceStore.getState>);
    const operationId = beginTaskOperation();

    await expect(useWorkspaceStore.getState().switchWorkspace("ws-2")).rejects.toMatchObject({
      name: "WorkspaceSwitchBlockedError",
      reason: "active_execution"
    });
    expect(workspaceApi.switchWorkspace).not.toHaveBeenCalled();
    finishTaskOperation(operationId);
  });

  it("switchWorkspace handles success with correct order", async () => {
    vi.mocked(useWorkflowPersistenceStore.getState).mockReturnValue({
      isDirty: false,
      hasLocalDraft: false,
      pendingConflict: null
    } as ReturnType<typeof useWorkflowPersistenceStore.getState>);

    const mockSession = {
      currentWorkspace: { id: "ws-2", name: "Other WS", isDefault: false, role: "admin" as const, capabilities: [] },
      memberships: [],
      capabilities: []
    };
    vi.mocked(workspaceApi.switchWorkspace).mockResolvedValueOnce(mockSession);
    const sessionObserver = vi.fn();
    const unsubscribe = useWorkspaceStore.subscribe((state) => {
      if (state.currentWorkspace?.id === "ws-2") sessionObserver();
    });

    const generationBefore = useWorkspaceStore.getState().contextGeneration;
    await useWorkspaceStore.getState().switchWorkspace("ws-2");
    unsubscribe();

    const apiCallOrder = vi.mocked(workspaceApi.switchWorkspace).mock.invocationCallOrder[0];
    const resetCallOrder = vi.mocked(workspaceReset.resetWorkspaceScopedState).mock.invocationCallOrder[0];
    const setActiveWsOrder = vi.mocked(api.setActiveWorkspaceId).mock.invocationCallOrder[0];

    expect(apiCallOrder).toBeLessThan(resetCallOrder);
    expect(resetCallOrder).toBeLessThan(setActiveWsOrder);
    expect(setActiveWsOrder).toBeLessThan(sessionObserver.mock.invocationCallOrder[0]);

    const state = useWorkspaceStore.getState();
    expect(state.currentWorkspace?.id).toBe("ws-2");
    expect(state.contextGeneration).toBeGreaterThan(generationBefore);
    expect(api.setActiveWorkspaceId).toHaveBeenCalledWith("ws-2");
  });

  it.each([404, 409])("switchWorkspace preserves old context on %i failure", async (status) => {
    vi.mocked(useWorkflowPersistenceStore.getState).mockReturnValue({
      isDirty: false,
      hasLocalDraft: false,
      pendingConflict: null
    } as ReturnType<typeof useWorkflowPersistenceStore.getState>);
    const oldWorkspace = { id: "ws-1", name: "Original WS", isDefault: false, role: "owner" as const, capabilities: [] };
    useWorkspaceStore.setState({
      currentWorkspace: oldWorkspace,
      memberships: [],
      capabilities: ["workspace.view"]
    });
    vi.mocked(api.setActiveWorkspaceId).mockClear();

    vi.mocked(workspaceApi.switchWorkspace).mockRejectedValueOnce(
      Object.assign(new Error("Switch Failed"), { status })
    );

    await expect(useWorkspaceStore.getState().switchWorkspace("ws-2")).rejects.toThrow("Switch Failed");

    expect(workspaceReset.resetWorkspaceScopedState).not.toHaveBeenCalled();
    expect(api.setActiveWorkspaceId).not.toHaveBeenCalled();
    const state = useWorkspaceStore.getState();
    expect(state).toMatchObject({
      currentWorkspace: oldWorkspace,
      capabilities: ["workspace.view"],
      isSwitching: false
    });
  });

  it("switchWorkspace rejects a successful response without a current workspace", async () => {
    vi.mocked(useWorkflowPersistenceStore.getState).mockReturnValue({
      isDirty: false,
      hasLocalDraft: false,
      pendingConflict: null
    } as ReturnType<typeof useWorkflowPersistenceStore.getState>);
    vi.mocked(workspaceApi.switchWorkspace).mockResolvedValueOnce({
      currentWorkspace: null,
      memberships: [],
      capabilities: []
    });

    await expect(useWorkspaceStore.getState().switchWorkspace("ws-2")).rejects.toThrow(
      "Workspace switch returned no current workspace"
    );

    expect(workspaceReset.resetWorkspaceScopedState).not.toHaveBeenCalled();
    expect(api.setActiveWorkspaceId).not.toHaveBeenCalled();
  });
});
