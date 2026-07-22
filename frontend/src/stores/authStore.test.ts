import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  setUnauthorizedHandler: vi.fn(),
  setActiveWorkspaceId: vi.fn()
}));

vi.mock("@/services/authApi", () => ({
  getCurrentSession: vi.fn(),
  loginWithPassword: vi.fn(),
  logoutCurrentSession: vi.fn(),
  registerWithPassword: vi.fn()
}));

vi.mock("@/stores/workspaceReset", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/stores/workspaceReset")>();
  return {
    ...actual,
    resetWorkspaceScopedState: vi.fn(actual.resetWorkspaceScopedState)
  };
});

import { useResultStore } from "@/features/result/store";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";
import {
  getCurrentSession,
  logoutCurrentSession,
  loginWithPassword,
  registerWithPassword
} from "@/services/authApi";
import * as api from "@/services/api";
import { initialAuthState, useAuthStore } from "@/stores/authStore";
import { initialUIState, useUIStore } from "@/stores/uiStore";
import * as workspaceReset from "@/stores/workspaceReset";
import { useWorkspaceStore } from "@/stores/workspaceStore";

function resetAuthStore() {
  useAuthStore.setState({
    ...initialAuthState,
    hydrateSession: useAuthStore.getState().hydrateSession,
    login: useAuthStore.getState().login,
    register: useAuthStore.getState().register,
    logout: useAuthStore.getState().logout,
    rememberIntendedRoute: useAuthStore.getState().rememberIntendedRoute,
    consumeIntendedRoute: useAuthStore.getState().consumeIntendedRoute,
    allowRedirectCapture: useAuthStore.getState().allowRedirectCapture,
    handleUnauthorized: useAuthStore.getState().handleUnauthorized
  });
}

describe("authStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetAuthStore();
    useWorkflowStore.getState().clearCanvas();
    useWorkflowPersistenceStore.getState().reset();
    useTaskExecutionStore.getState().reset();
    useResultStore.getState().reset();
    useUIStore.setState(initialUIState);
    useWorkspaceStore.getState().resetWorkspaceState();
    vi.clearAllMocks();
  });

  it("hydrates an existing session into authenticated state", async () => {
    vi.mocked(getCurrentSession).mockResolvedValue({
      success: true,
      data: {
        user: { id: "usr_1", email: "alice@example.com", name: "Alice" },
        session: { expires_at: "2026-03-26T09:00:00Z" }
      }
    });

    await useAuthStore.getState().hydrateSession();

    expect(useAuthStore.getState()).toMatchObject({
      status: "authenticated",
      currentUser: { id: "usr_1", email: "alice@example.com", name: "Alice" },
      sessionExpiresAt: "2026-03-26T09:00:00Z"
    });
  });

  it("falls back to anonymous when session hydrate fails", async () => {
    vi.mocked(getCurrentSession).mockRejectedValue(new Error("AUTH_REQUIRED"));

    await useAuthStore.getState().hydrateSession();

    expect(useAuthStore.getState()).toMatchObject({
      status: "anonymous",
      currentUser: null,
      sessionExpiresAt: null
    });
  });

  it("stores and consumes intended routes", () => {
    useAuthStore.getState().rememberIntendedRoute("/studio");

    expect(useAuthStore.getState().consumeIntendedRoute("/")).toBe("/studio");
    expect(useAuthStore.getState().consumeIntendedRoute("/")).toBe("/");
  });

  it("logs in and registers users through the auth API", async () => {
    vi.mocked(loginWithPassword).mockResolvedValue({
      success: true,
      data: {
        user: { id: "usr_login", email: "login@example.com" },
        session: { expires_at: "2026-03-26T09:00:00Z" }
      }
    });
    vi.mocked(registerWithPassword).mockResolvedValue({
      success: true,
      data: {
        user: { id: "usr_register", email: "register@example.com" },
        session: { expires_at: "2026-03-27T09:00:00Z" }
      }
    });

    const loginUser = await useAuthStore.getState().login({ email: "login@example.com", password: "pw" });
    const registerUser = await useAuthStore.getState().register({ email: "register@example.com", password: "pw" });

    expect(loginUser.id).toBe("usr_login");
    expect(registerUser.id).toBe("usr_register");
    expect(useAuthStore.getState().status).toBe("authenticated");
  });

  it("clears workflow-scoped state on logout", async () => {
    vi.mocked(logoutCurrentSession).mockResolvedValue({ success: true });
    useWorkflowStore.setState({
      nodes: [
        {
          id: "node_1",
          type: "engine/ocr",
          position: { x: 10, y: 20 },
          data: {
            label: "OCR",
            config: {},
            configSchema: { type: "object", properties: {} }
          }
        }
      ],
      edges: [],
      nodeConfigs: {},
      uploadedFiles: {},
      selectedNodeId: "node_1",
      nodeRegistry: { nodes: [], connection_rules: [] }
    });
    useWorkflowPersistenceStore.setState({
      workflowId: "wf_1",
      latestVersion: 3,
      publishedVersion: 2,
      versions: [],
      isDirty: true,
      lastSavedAt: "2026-03-19T09:00:00Z"
    });
    useTaskExecutionStore.getState().setTaskId("task_1");
    useResultStore.getState().setTaskResults("task_1", []);
    useAuthStore.setState({
      status: "authenticated",
      currentUser: { id: "usr_1", email: "alice@example.com" },
      sessionExpiresAt: "2026-03-26T09:00:00Z"
    });

    await useAuthStore.getState().logout();

    expect(useAuthStore.getState()).toMatchObject({
      status: "anonymous",
      currentUser: null,
      shouldRememberRedirect: false
    });
    expect(useWorkflowStore.getState().nodes).toEqual([]);
    expect(useWorkflowPersistenceStore.getState()).toMatchObject({
      workflowId: null,
      latestVersion: 0,
      publishedVersion: null,
      isDirty: false
    });
    expect(useTaskExecutionStore.getState().currentTaskId).toBeNull();
    expect(useResultStore.getState().taskId).toBeNull();
  });

  it("resets scoped and workspace state before logout exposes anonymous auth", async () => {
    vi.mocked(logoutCurrentSession).mockResolvedValue({ success: true });
    useAuthStore.setState({
      status: "authenticated",
      currentUser: { id: "usr_1", email: "alice@example.com" }
    });
    useWorkspaceStore.setState({
      status: "ready",
      currentWorkspace: { id: "ws-1", name: "Workspace", isDefault: true, role: "admin", capabilities: [] },
      memberships: [{ workspace: { id: "ws-1", name: "Workspace", isDefault: true, role: "admin", capabilities: [] }, role: "admin", capabilities: [] }],
      capabilities: ["workflow.run"]
    });
    const scopedReset = vi.spyOn(workspaceReset, "resetWorkspaceScopedState");
    const workspaceStateReset = vi.spyOn(useWorkspaceStore.getState(), "resetWorkspaceState");
    const anonymousObserver = vi.fn();
    const unsubscribe = useAuthStore.subscribe((state) => {
      if (state.status === "anonymous") anonymousObserver();
    });

    await useAuthStore.getState().logout();
    unsubscribe();

    expect(scopedReset.mock.invocationCallOrder[0]).toBeLessThan(workspaceStateReset.mock.invocationCallOrder[0]);
    expect(workspaceStateReset.mock.invocationCallOrder[0]).toBeLessThan(anonymousObserver.mock.invocationCallOrder[0]);
    expect(useWorkspaceStore.getState()).toMatchObject({
      status: "idle",
      currentWorkspace: null,
      memberships: [],
      capabilities: []
    });
    expect(api.setActiveWorkspaceId).toHaveBeenCalledWith(null);
    expect(useAuthStore.getState().status).toBe("anonymous");
  });

  it.each(["expired", "required"] as const)(
    "resets scoped and workspace state before %s unauthorized exposes anonymous auth",
    (reason) => {
      useAuthStore.setState({
        status: "authenticated",
        currentUser: { id: "usr_1", email: "alice@example.com" }
      });
      useWorkspaceStore.setState({
        status: "ready",
        currentWorkspace: { id: "ws-1", name: "Workspace", isDefault: true, role: "admin", capabilities: [] },
        memberships: [],
        capabilities: ["workflow.run"]
      });
      const scopedReset = vi.spyOn(workspaceReset, "resetWorkspaceScopedState");
      const workspaceStateReset = vi.spyOn(useWorkspaceStore.getState(), "resetWorkspaceState");
      const anonymousObserver = vi.fn();
      const unsubscribe = useAuthStore.subscribe((state) => {
        if (state.status === "anonymous") anonymousObserver();
      });

      useAuthStore.getState().handleUnauthorized(reason);
      unsubscribe();

      expect(scopedReset.mock.invocationCallOrder[0]).toBeLessThan(workspaceStateReset.mock.invocationCallOrder[0]);
      expect(workspaceStateReset.mock.invocationCallOrder[0]).toBeLessThan(anonymousObserver.mock.invocationCallOrder[0]);
      expect(useWorkspaceStore.getState()).toMatchObject({
        status: "idle",
        currentWorkspace: null,
        memberships: [],
        capabilities: []
      });
      expect(api.setActiveWorkspaceId).toHaveBeenCalledWith(null);
      expect(useAuthStore.getState().status).toBe("anonymous");
    }
  );
});
