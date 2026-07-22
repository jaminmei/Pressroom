import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiClient, setActiveWorkspaceId } from "@/services/api";
import {
  getWorkspaceSession,
  listWorkspaces,
  switchWorkspace,
  createWorkspace,
  updateWorkspace,
  deleteWorkspace,
  transferWorkspaceOwner,
  listWorkspaceMembers,
  inviteWorkspaceMember,
  changeWorkspaceMemberRole,
  removeWorkspaceMember,
  listWorkspaceAuditEvents,
} from "./workspaceApi";

describe("workspaceApi", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe("API methods mapping", () => {
    it("getWorkspaceSession maps response", async () => {
      vi.spyOn(apiClient, "get").mockResolvedValueOnce({
        data: {
          current_workspace: { id: "ws_1", name: "WS 1", is_default: true, role: "owner", capabilities: [] },
          memberships: [],
          capabilities: [],
        },
      });

      const res = await getWorkspaceSession();
      expect(apiClient.get).toHaveBeenCalledWith("/workspaces/session");
      expect(res.currentWorkspace?.id).toBe("ws_1");
      expect(res.currentWorkspace?.isDefault).toBe(true);
    });

    it("listWorkspaces maps response", async () => {
      vi.spyOn(apiClient, "get").mockResolvedValueOnce({
        data: {
          items: [{ id: "ws_1", name: "WS 1", is_default: false, role: "admin", capabilities: [] }],
        },
      });

      const res = await listWorkspaces();
      expect(apiClient.get).toHaveBeenCalledWith("/workspaces");
      expect(res[0].id).toBe("ws_1");
      expect(res[0].isDefault).toBe(false);
    });

    it("switchWorkspace maps payload and response", async () => {
      vi.spyOn(apiClient, "post").mockResolvedValueOnce({
        data: {
          current_workspace: { id: "ws_2", name: "WS 2", is_default: true, role: "owner", capabilities: [] },
          memberships: [],
          capabilities: [],
        },
      });

      const res = await switchWorkspace({ workspaceId: "ws_2" });
      expect(apiClient.post).toHaveBeenCalledWith("/workspaces/ws_2/switch");
      expect(res.currentWorkspace?.id).toBe("ws_2");
    });

    it("createWorkspace maps payload and response", async () => {
      vi.spyOn(apiClient, "post").mockResolvedValueOnce({
        data: { id: "ws_new", name: "New", is_default: false, role: "owner", capabilities: [] },
      });

      const res = await createWorkspace({ name: "New", description: "Desc" });
      expect(apiClient.post).toHaveBeenCalledWith("/workspaces", { name: "New", description: "Desc" });
      expect(res.id).toBe("ws_new");
    });

    it("updateWorkspace maps payload and response", async () => {
      vi.spyOn(apiClient, "patch").mockResolvedValueOnce({
        data: { id: "ws_1", name: "Updated", is_default: true, role: "owner", capabilities: [] },
      });

      const res = await updateWorkspace("ws_1", { name: "Updated", isDefault: true });
      expect(apiClient.patch).toHaveBeenCalledWith("/workspaces/ws_1", { name: "Updated", is_default: true });
      expect(res.name).toBe("Updated");
      expect(res.isDefault).toBe(true);
    });

    it("deleteWorkspace calls delete", async () => {
      vi.spyOn(apiClient, "delete").mockResolvedValueOnce({});
      await deleteWorkspace("ws_1");
      expect(apiClient.delete).toHaveBeenCalledWith("/workspaces/ws_1");
    });

    it("transferWorkspaceOwner maps payload and response", async () => {
      vi.spyOn(apiClient, "post").mockResolvedValueOnce({
        data: { id: "ws_1", name: "WS", is_default: false, role: "admin", capabilities: [] },
      });

      await transferWorkspaceOwner("ws_1", { newOwnerUserId: "user_2" });
      expect(apiClient.post).toHaveBeenCalledWith("/workspaces/ws_1/transfer-owner", { new_owner_user_id: "user_2" });
    });

    it("listWorkspaceMembers maps response", async () => {
      vi.spyOn(apiClient, "get").mockResolvedValueOnce({
        data: {
          items: [{ user_id: "user_1", email: "owner@example.test", role: "owner", status: "active" }],
          total: 1,
        },
      });

      const res = await listWorkspaceMembers("ws_1");
      expect(apiClient.get).toHaveBeenCalledWith("/workspaces/ws_1/members");
      expect(res.items[0].userId).toBe("user_1");
    });

    it("inviteWorkspaceMember maps payload and response", async () => {
      vi.spyOn(apiClient, "post").mockResolvedValueOnce({
        data: { user_id: "user_2", email: "viewer@example.test", role: "viewer", status: "pending" },
      });

      const res = await inviteWorkspaceMember("ws_1", { email: "viewer@example.test", role: "viewer" });
      expect(apiClient.post).toHaveBeenCalledWith("/workspaces/ws_1/members", { email: "viewer@example.test", role: "viewer" });
      expect(res.userId).toBe("user_2");
    });

    it("changeWorkspaceMemberRole maps payload and response", async () => {
      vi.spyOn(apiClient, "patch").mockResolvedValueOnce({
        data: { user_id: "user_1", email: "owner@example.test", role: "admin", status: "active" },
      });

      const res = await changeWorkspaceMemberRole("ws_1", "user_1", { role: "admin" });
      expect(apiClient.patch).toHaveBeenCalledWith("/workspaces/ws_1/members/user_1", { role: "admin" });
      expect(res.role).toBe("admin");
    });

    it("removeWorkspaceMember calls delete", async () => {
      vi.spyOn(apiClient, "delete").mockResolvedValueOnce({});
      await removeWorkspaceMember("ws_1", "user_1");
      expect(apiClient.delete).toHaveBeenCalledWith("/workspaces/ws_1/members/user_1");
    });

    it("listWorkspaceAuditEvents maps response", async () => {
      vi.spyOn(apiClient, "get").mockResolvedValueOnce({
        data: {
          items: [
            {
              id: "ev_1",
              type: "workspace.created",
              message: "Created",
              created_at: "2026",
              actor: { user_id: "user_1", email: "owner@example.test" },
              target: { type: "workspace", id: "ws_1" },
            },
          ],
          total: 1,
        },
      });

      const res = await listWorkspaceAuditEvents("ws_1", { limit: 10 });
      expect(apiClient.get).toHaveBeenCalledWith("/workspaces/ws_1/audit-events", { params: { limit: 10 } });
      expect(res.items[0].id).toBe("ev_1");
      expect(res.items[0].actor?.userId).toBe("user_1");
      expect(res.items[0].target?.type).toBe("workspace");
    });
  });

  describe("API Interceptor", () => {
    it("injects X-Workspace-Id header when activeWorkspaceId is set", async () => {
      const adapterMock = vi.fn().mockResolvedValue({
        data: {},
        status: 200,
        statusText: "OK",
        headers: {},
        config: {},
      });
      apiClient.defaults.adapter = adapterMock;

      setActiveWorkspaceId("ws_1");
      await apiClient.get("/test");

      let config = adapterMock.mock.calls[0][0];
      expect(config.headers["X-Workspace-Id"]).toBe("ws_1");

      setActiveWorkspaceId(null);
      await apiClient.get("/test");

      config = adapterMock.mock.calls[1][0];
      expect(config.headers["X-Workspace-Id"]).toBeUndefined();
    });
  });
});
