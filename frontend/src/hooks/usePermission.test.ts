import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { usePermission } from "./usePermission";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { WorkspaceState } from "@/stores/workspaceStore";

vi.mock("@/stores/workspaceStore", async () => {
  const actual = await vi.importActual<typeof import("@/stores/workspaceStore")>("@/stores/workspaceStore");
  return {
    ...actual,
    useWorkspaceStore: vi.fn(),
  };
});

describe("usePermission", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("returns can, explain, and role", () => {
    const mockCan = vi.fn().mockReturnValue(true);
    const mockExplain = vi.fn().mockReturnValue({ allowed: true });

    const mockStore = {
      currentWorkspace: { id: "ws-1", name: "Test WS", isDefault: true, role: "admin", capabilities: [] },
      can: mockCan,
      explain: mockExplain,
    } as unknown as WorkspaceState;

    vi.mocked(useWorkspaceStore).mockImplementation((selector) => selector(mockStore));

    const { result } = renderHook(() => usePermission());

    expect(result.current.role).toBe("admin");
    expect(result.current.can("workflow.run")).toBe(true);
    expect(mockCan).toHaveBeenCalledWith("workflow.run");

    expect(result.current.explain("workflow.run")).toEqual({ allowed: true });
    expect(mockExplain).toHaveBeenCalledWith("workflow.run");
  });
});
