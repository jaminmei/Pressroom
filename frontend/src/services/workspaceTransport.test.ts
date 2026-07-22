import { beforeEach, describe, expect, it, vi } from "vitest";

function storage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value)
  };
}

describe("workspaceTransport", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubGlobal("sessionStorage", storage());
  });

  it("retains independent workspace preferences across tab refreshes", async () => {
    const tabA = storage();
    const tabB = storage();

    vi.stubGlobal("sessionStorage", tabA);
    let transport = await import("./workspaceTransport");
    transport.activateWorkspaceUser("usr-1");
    transport.setValidatedActiveWorkspaceId("ws-A");

    vi.resetModules();
    vi.stubGlobal("sessionStorage", tabB);
    transport = await import("./workspaceTransport");
    transport.activateWorkspaceUser("usr-1");
    transport.setValidatedActiveWorkspaceId("ws-B");

    vi.resetModules();
    vi.stubGlobal("sessionStorage", tabA);
    transport = await import("./workspaceTransport");
    expect(transport.activateWorkspaceUser("usr-1")).toBe("ws-A");
    expect(transport.getActiveWorkspaceId()).toBeNull();

    vi.resetModules();
    vi.stubGlobal("sessionStorage", tabB);
    transport = await import("./workspaceTransport");
    expect(transport.activateWorkspaceUser("usr-1")).toBe("ws-B");
  });

  it("repairs a stale preference only after a validated session response", async () => {
    sessionStorage.setItem("dc.workspace.active-id:usr-1", "ws-revoked");
    const transport = await import("./workspaceTransport");

    expect(transport.activateWorkspaceUser("usr-1")).toBe("ws-revoked");
    expect(transport.getActiveWorkspaceId()).toBeNull();

    transport.setValidatedActiveWorkspaceId("ws-fallback");

    expect(transport.getActiveWorkspaceId()).toBe("ws-fallback");
    expect(sessionStorage.getItem("dc.workspace.active-id:usr-1")).toBe("ws-fallback");
  });

  it("clears only the logged-out user's preference", async () => {
    sessionStorage.setItem("dc.workspace.active-id:usr-1", "ws-A");
    sessionStorage.setItem("dc.workspace.active-id:usr-2", "ws-B");
    const transport = await import("./workspaceTransport");
    transport.activateWorkspaceUser("usr-1");

    transport.clearWorkspaceUser("usr-1");

    expect(sessionStorage.getItem("dc.workspace.active-id:usr-1")).toBeNull();
    expect(sessionStorage.getItem("dc.workspace.active-id:usr-2")).toBe("ws-B");
    expect(transport.getActiveWorkspaceId()).toBeNull();
  });

  it("adds workspace query to same-origin API URLs without replacing existing params", async () => {
    const transport = await import("./workspaceTransport");
    transport.activateWorkspaceUser("usr-1");
    transport.setValidatedActiveWorkspaceId("ws-A");

    expect(transport.buildWorkspaceScopedUrl("/api/documents/1?disposition=inline")).toBe(
      "/api/documents/1?disposition=inline&workspace_id=ws-A"
    );
    expect(transport.buildWorkspaceScopedUrl("blob:example")).toBe("blob:example");
    expect(transport.buildWorkspaceScopedUrl("https://example.com/file")).toBe("https://example.com/file");
  });
});
