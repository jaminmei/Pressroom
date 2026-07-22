import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useWorkspace } from "./useWorkspace";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { WorkspaceState } from "@/stores/workspaceStore";

vi.mock("@/stores/workspaceStore", async () => {
  const actual = await vi.importActual<typeof import("@/stores/workspaceStore")>("@/stores/workspaceStore");
  return {
    ...actual,
    useWorkspaceStore: vi.fn(),
  };
});

describe("useWorkspace", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("returns workspace data from store", () => {
    const mockStore = {
      status: "ready" as const,
      currentWorkspace: { id: "ws-1", name: "Test WS", isDefault: true, role: "owner" as const, capabilities: [] },
      memberships: [],
      capabilities: ["workflow.run" as const],
      isSwitching: false,
      error: null,
      switchWorkspace: vi.fn(),
      createWorkspace: vi.fn(),
      refreshWorkspaces: vi.fn(),
    } as unknown as WorkspaceState;

    vi.mocked(useWorkspaceStore).mockImplementation((selector) => selector(mockStore));

    const { result } = renderHook(() => useWorkspace());

    expect(result.current.status).toBe("ready");
    expect(result.current.currentWorkspace?.id).toBe("ws-1");
    expect(result.current.currentRole).toBe("owner");
    expect(result.current.capabilities).toContain("workflow.run");
  });

  it("calls store actions", async () => {
    const mockSwitch = vi.fn().mockResolvedValue(undefined);
    const createdWorkspace = {
      id: "ws-new",
      name: "New workspace",
      isDefault: false,
      role: "owner" as const,
      capabilities: [],
    };
    const mockCreate = vi.fn().mockResolvedValue(createdWorkspace);
    const mockRefresh = vi.fn().mockResolvedValue(undefined);

    const mockStore = {
      status: "ready" as const,
      currentWorkspace: null,
      memberships: [],
      capabilities: [],
      isSwitching: false,
      error: null,
      switchWorkspace: mockSwitch,
      createWorkspace: mockCreate,
      refreshWorkspaces: mockRefresh,
    } as unknown as WorkspaceState;

    vi.mocked(useWorkspaceStore).mockImplementation((selector) => selector(mockStore));

    const { result } = renderHook(() => useWorkspace());

    await result.current.switchWorkspace("ws-2");
    expect(mockSwitch).toHaveBeenCalledWith("ws-2");

    await expect(result.current.createWorkspace({ name: "New workspace" })).resolves.toEqual(createdWorkspace);
    expect(mockCreate).toHaveBeenCalledWith({ name: "New workspace" });

    await result.current.refresh();
    expect(mockRefresh).toHaveBeenCalled();
  });
});
