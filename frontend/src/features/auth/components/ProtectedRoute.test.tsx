import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProtectedRoute from "@/features/auth/components/ProtectedRoute";
import * as workspaceApi from "@/services/workspaceApi";
import { initialAuthState, useAuthStore } from "@/stores/authStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { WorkspaceSummary } from "@/types/workspace";

const originalHydrateWorkspaceSession = useWorkspaceStore.getState().hydrateWorkspaceSession;
const currentWorkspace: WorkspaceSummary = {
  id: "ws_1",
  name: "Primary Workspace",
  isDefault: true,
  role: "owner",
  capabilities: []
};

function resetAuthState() {
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

function renderProtectedRoute() {
  return render(
    <React.StrictMode>
      <MemoryRouter initialEntries={["/studio"]}>
        <Routes>
          <Route
            element={
              <ProtectedRoute>
                <div data-testid="protected-route-content">Protected</div>
              </ProtectedRoute>
            }
            path="/studio"
          />
          <Route element={<div data-testid="protected-route-login-target">Login</div>} path="/login" />
        </Routes>
      </MemoryRouter>
    </React.StrictMode>
  );
}

describe("ProtectedRoute", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    resetAuthState();
    useWorkspaceStore.setState({ hydrateWorkspaceSession: originalHydrateWorkspaceSession });
    useWorkspaceStore.getState().resetWorkspaceState();
  });

  it("renders an auth loading state while auth is hydrating", () => {
    useAuthStore.setState({ status: "unknown", isHydrating: true });

    renderProtectedRoute();

    expect(screen.getByTestId("protected-route-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("protected-route-content")).not.toBeInTheDocument();
  });

  it("redirects anonymous users to login and remembers the intended route", async () => {
    useAuthStore.setState({ status: "anonymous" });

    renderProtectedRoute();

    expect(await screen.findByTestId("protected-route-login-target")).toBeInTheDocument();
    expect(useAuthStore.getState().intendedRoute).toBe("/studio");
  });

  it("hydrates the workspace once under StrictMode when auth is authenticated", async () => {
    const getWorkspaceSession = vi.spyOn(workspaceApi, "getWorkspaceSession").mockResolvedValue({
      currentWorkspace,
      memberships: [],
      capabilities: []
    });
    useAuthStore.setState({
      status: "authenticated",
      currentUser: { id: "usr_1", email: "alice@example.com" }
    });

    renderProtectedRoute();

    expect(await screen.findByTestId("protected-route-content")).toBeInTheDocument();
    expect(getWorkspaceSession).toHaveBeenCalledTimes(1);
  });

  it("withholds children while workspace status is idle", async () => {
    let resolveSession: ((session: Awaited<ReturnType<typeof workspaceApi.getWorkspaceSession>>) => void) | undefined;
    const getWorkspaceSession = vi.spyOn(workspaceApi, "getWorkspaceSession").mockImplementation(
      () => new Promise((resolve) => {
        resolveSession = resolve;
      })
    );
    useAuthStore.setState({
      status: "authenticated",
      currentUser: { id: "usr_1", email: "alice@example.com" }
    });

    renderProtectedRoute();

    expect(screen.getByTestId("workspace-bootstrap-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("protected-route-content")).not.toBeInTheDocument();
    expect(getWorkspaceSession).toHaveBeenCalledTimes(1);

    resolveSession?.({ currentWorkspace, memberships: [], capabilities: [] });
    expect(await screen.findByTestId("protected-route-content")).toBeInTheDocument();
  });

  it("withholds children while workspace status is loading", () => {
    useAuthStore.setState({
      status: "authenticated",
      currentUser: { id: "usr_1", email: "alice@example.com" }
    });
    useWorkspaceStore.setState({ status: "loading" });

    renderProtectedRoute();

    expect(screen.getByTestId("workspace-bootstrap-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("protected-route-content")).not.toBeInTheDocument();
  });

  it("retries workspace hydration from the error state", async () => {
    const hydrateWorkspaceSession = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({
      status: "authenticated",
      currentUser: { id: "usr_1", email: "alice@example.com" }
    });
    useWorkspaceStore.setState({
      status: "error",
      error: "Workspace service unavailable",
      hydrateWorkspaceSession
    });

    renderProtectedRoute();
    fireEvent.click(screen.getByTestId("workspace-bootstrap-retry"));

    expect(screen.getByTestId("workspace-bootstrap-error")).toHaveTextContent("Workspace service unavailable");
    await waitFor(() => expect(hydrateWorkspaceSession).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("protected-route-content")).not.toBeInTheDocument();
  });

  it("renders an account-level Create Workspace CTA after successful empty hydration", () => {
    useAuthStore.setState({
      status: "authenticated",
      currentUser: { id: "usr_1", email: "alice@example.com" }
    });
    useWorkspaceStore.setState({ status: "ready", currentWorkspace: null });

    renderProtectedRoute();

    expect(screen.getByTestId("workspace-no-workspace")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create workspace" })).toBeInTheDocument();
    expect(screen.queryByTestId("protected-route-content")).not.toBeInTheDocument();
  });

  it("renders children when auth and workspace are ready", () => {
    useAuthStore.setState({
      status: "authenticated",
      currentUser: { id: "usr_1", email: "alice@example.com" }
    });
    useWorkspaceStore.setState({ status: "ready", currentWorkspace });

    renderProtectedRoute();

    expect(screen.getByTestId("protected-route-content")).toBeInTheDocument();
  });
});
