import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useWorkspaceMembers } from "./useWorkspaceMembers";
import * as workspaceApi from "@/services/workspaceApi";

vi.mock("@/services/workspaceApi", () => ({
  listWorkspaceMembers: vi.fn(),
  inviteWorkspaceMember: vi.fn(),
  changeWorkspaceMemberRole: vi.fn(),
  removeWorkspaceMember: vi.fn(),
}));

describe("useWorkspaceMembers", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("fetches members on mount", async () => {
    const mockMembers = [{ userId: "u1", email: "member@example.test", role: "admin" as const, status: "active" as const }];
    vi.mocked(workspaceApi.listWorkspaceMembers).mockResolvedValue({ items: mockMembers, total: 1 });

    const { result } = renderHook(() => useWorkspaceMembers("ws-1"));

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(workspaceApi.listWorkspaceMembers).toHaveBeenCalledWith("ws-1");
    expect(result.current.members).toEqual(mockMembers);
    expect(result.current.total).toBe(1);
    expect(result.current.error).toBeNull();
  });

  it("handles fetch error gracefully", async () => {
    vi.mocked(workspaceApi.listWorkspaceMembers).mockRejectedValue(new Error("API Error"));

    const { result } = renderHook(() => useWorkspaceMembers("ws-1"));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.members).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(result.current.error).toBe("API Error");
  });

  it("calls inviteMember and refreshes", async () => {
    vi.mocked(workspaceApi.listWorkspaceMembers).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(workspaceApi.inviteWorkspaceMember).mockResolvedValue({
      userId: "u2",
      email: "new-member@example.test",
      role: "viewer",
      status: "pending"
    });

    const { result } = renderHook(() => useWorkspaceMembers("ws-1"));

    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.inviteMember({ email: "new-member@example.test", role: "viewer" });
    });

    expect(workspaceApi.inviteWorkspaceMember).toHaveBeenCalledWith("ws-1", { email: "new-member@example.test", role: "viewer" });
    // Should have called list twice (mount + refresh)
    expect(workspaceApi.listWorkspaceMembers).toHaveBeenCalledTimes(2);
  });
});
