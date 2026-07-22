import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useWorkspaceAudit } from "./useWorkspaceAudit";
import * as workspaceApi from "@/services/workspaceApi";

vi.mock("@/services/workspaceApi", () => ({
  listWorkspaceAuditEvents: vi.fn(),
}));

describe("useWorkspaceAudit", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("fetches audit events on mount", async () => {
    const mockEvents = [{ id: "e1", type: "workspace.created" as const, message: "Created", createdAt: "2024-01-01" }];
    vi.mocked(workspaceApi.listWorkspaceAuditEvents).mockResolvedValue({ items: mockEvents, total: 1 });

    const { result } = renderHook(() => useWorkspaceAudit("ws-1"));

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(workspaceApi.listWorkspaceAuditEvents).toHaveBeenCalledWith("ws-1");
    expect(result.current.events).toEqual(mockEvents);
    expect(result.current.total).toBe(1);
    expect(result.current.error).toBeNull();
  });

  it("handles fetch error gracefully without throwing", async () => {
    vi.mocked(workspaceApi.listWorkspaceAuditEvents).mockRejectedValue(new Error("API Not Implemented"));

    const { result } = renderHook(() => useWorkspaceAudit("ws-1"));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.events).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(result.current.error).toBe("API Not Implemented");
    // Ensure no unhandled rejection leaks
  });

  it("does not fetch when disabled", () => {
    const { result } = renderHook(() => useWorkspaceAudit("ws-1", false));

    expect(workspaceApi.listWorkspaceAuditEvents).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
    expect(result.current.events).toEqual([]);
  });
});
