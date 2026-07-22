import { describe, expect, it } from "vitest";

import { appRoutes } from "@/app/routes";
import { resolveWorkspaceSwitchPath } from "@/components/Layout/WorkspaceSwitcher";
import type { WorkspaceCapability } from "@/types/workspace";

const allSettingsCapabilities: readonly WorkspaceCapability[] = [
  "workspace.view",
  "workspace.update",
  "members.view",
  "provider.view",
  "audit.view",
];

describe("workspace navigation", () => {
  it("redirects workflow details to Studio after a workspace switch", () => {
    expect(resolveWorkspaceSwitchPath("/workflows/wf_1", allSettingsCapabilities)).toBe("/studio");
    expect(resolveWorkspaceSwitchPath("/workflows/wf_1/api-access", allSettingsCapabilities)).toBe("/studio");
    expect(resolveWorkspaceSwitchPath("/tasks/task_1/results", allSettingsCapabilities)).toBe("/studio");
  });

  it("redirects database details and runs to the canonical Database list", () => {
    expect(resolveWorkspaceSwitchPath("/database/db_1", allSettingsCapabilities)).toBe("/database");
    expect(resolveWorkspaceSwitchPath("/projects/db_1/run", allSettingsCapabilities)).toBe("/database");
  });

  it("preserves safe routes and permitted workspace settings pages", () => {
    expect(resolveWorkspaceSwitchPath("/studio", allSettingsCapabilities)).toBeNull();
    expect(resolveWorkspaceSwitchPath("/database", allSettingsCapabilities)).toBeNull();
    expect(resolveWorkspaceSwitchPath("/settings/workspace/providers", allSettingsCapabilities)).toBeNull();
  });

  it("falls back to workspace settings when the new role cannot open the subpage", () => {
    expect(resolveWorkspaceSwitchPath("/settings/workspace/audit", ["workspace.view"])).toBe(
      "/settings/workspace",
    );
  });

  it("does not define a workflows list pseudo-route", () => {
    const protectedRoot = appRoutes.find((route) => route.path === "/");
    expect(protectedRoot?.children?.some((route) => route.path === "workflows")).toBe(false);
  });

  it("renders Run Workflow inside the protected AppLayout route", () => {
    const protectedRoot = appRoutes.find((route) => route.path === "/");
    expect(
      protectedRoot?.children?.some((route) => route.path === "database/:projectId/run"),
    ).toBe(true);
    expect(appRoutes.some((route) => route.path === "/database/:projectId/run")).toBe(false);
    expect(appRoutes.some((route) => route.path === "/projects/:projectId/run")).toBe(true);
  });
});
