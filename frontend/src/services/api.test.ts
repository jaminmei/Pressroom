import type { AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { beforeEach, describe, expect, it } from "vitest";

import { apiClient } from "./api";
import {
  activateWorkspaceUser,
  clearWorkspaceUser,
  setValidatedActiveWorkspaceId
} from "./workspaceTransport";

describe("api workspace transport", () => {
  beforeEach(() => {
    clearWorkspaceUser("usr-api");
    activateWorkspaceUser("usr-api");
  });

  it("captures the validated workspace id when the request starts", async () => {
    setValidatedActiveWorkspaceId("ws-A");
    let capturedWorkspaceId: string | undefined;
    const adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
      capturedWorkspaceId = config.headers?.["X-Workspace-Id"]?.toString();
      return { data: {}, status: 200, statusText: "OK", headers: {}, config };
    };

    const request = apiClient.get("/resource", { adapter });
    await Promise.resolve();
    setValidatedActiveWorkspaceId("ws-B");
    await request;

    expect(capturedWorkspaceId).toBe("ws-A");
  });

  it("does not send an unvalidated stored preference", async () => {
    sessionStorage.setItem("dc.workspace.active-id:usr-api", "ws-stale");
    activateWorkspaceUser("usr-api");
    let capturedWorkspaceId: string | undefined;
    const adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
      capturedWorkspaceId = config.headers?.["X-Workspace-Id"]?.toString();
      return { data: {}, status: 200, statusText: "OK", headers: {}, config };
    };

    await apiClient.get("/workspaces/session", { adapter });

    expect(capturedWorkspaceId).toBeUndefined();
  });

  it("preserves an explicitly pinned workspace header", async () => {
    setValidatedActiveWorkspaceId("ws-B");
    let capturedWorkspaceId: string | undefined;
    const adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
      capturedWorkspaceId = config.headers?.["X-Workspace-Id"]?.toString();
      return { data: {}, status: 200, statusText: "OK", headers: {}, config };
    };

    await apiClient.get("/resource", {
      adapter,
      headers: { "X-Workspace-Id": "ws-A" }
    });

    expect(capturedWorkspaceId).toBe("ws-A");
  });
});
