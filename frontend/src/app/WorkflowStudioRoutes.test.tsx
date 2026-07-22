import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

vi.mock("@/components/Layout/AppLayout", () => ({
  default: function MockAppLayout() {
    return (
      <div data-testid="mock-app-layout">
        <Outlet />
      </div>
    );
  }
}));

vi.mock("@/features/auth/components/LoginPage", () => ({
  default: function MockLoginPage() {
    return <div data-testid="route-login-page">Login Route</div>;
  }
}));

vi.mock("@/features/auth/components/RegisterPage", () => ({
  default: function MockRegisterPage() {
    return <div data-testid="route-register-page">Register Route</div>;
  }
}));

vi.mock("@/features/workflow-studio/components/WorkflowStudioPage", async () => {
  await new Promise((resolve) => setTimeout(resolve, 0));
  return {
    default: function MockWorkflowStudioPage() {
      return <div data-testid="route-workflow-studio-page">Workflow Studio Route</div>;
    }
  };
});

vi.mock("@/features/workflow-studio/components/PersistedWorkflowEditorPage", async () => {
  await new Promise((resolve) => setTimeout(resolve, 0));
  return {
    default: function MockPersistedWorkflowEditorPage() {
      return <div data-testid="route-persisted-workflow-editor-page">Persisted Workflow Route</div>;
    }
  };
});

vi.mock("@/features/template-center/components/TemplateCenterPage", async () => {
  await new Promise((resolve) => setTimeout(resolve, 0));
  return {
    default: function MockTemplateCenterPage() {
      return <div>Template Center Route</div>;
    }
  };
});

vi.mock("@/features/workflow-editor/components/WorkflowEditor", () => ({
  default: function MockWorkflowEditor() {
    return <div>Workflow Editor Route</div>;
  }
}));

vi.mock("@/features/result/components/ResultPage", () => ({
  default: function MockResultPage() {
    return <div data-testid="route-result-page">Result Route</div>;
  }
}));


import { appRoutes } from "@/app/routes";
import { initialAuthState, useAuthStore } from "@/stores/authStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";

function renderRoutes(initialEntries: string[]) {
  const router = createMemoryRouter(appRoutes, { initialEntries });
  return render(<RouterProvider router={router} />);
}

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

describe("WorkflowStudio routes", () => {
  beforeEach(() => {
    resetAuthState();
    useWorkspaceStore.setState({
      status: "ready",
      currentWorkspace: {
        id: "ws_1",
        name: "Primary Workspace",
        isDefault: true,
        role: "owner",
        capabilities: []
      },
      memberships: [],
      capabilities: [],
      error: null
    });
  });

  it("renders public auth routes without the app layout", async () => {
    useAuthStore.setState({ status: "anonymous" });

    renderRoutes(["/login"]);
    expect(screen.getByTestId("route-login-page")).toBeInTheDocument();

    renderRoutes(["/register"]);
    expect(screen.getByTestId("route-register-page")).toBeInTheDocument();
  });

  it("shows a route fallback before /studio finishes loading when authenticated", async () => {
    useAuthStore.setState({
      status: "authenticated",
      currentUser: { id: "usr_1", email: "alice@example.com" }
    });

    renderRoutes(["/studio"]);

    expect(screen.getByTestId("mock-app-layout")).toBeInTheDocument();
    expect(screen.getByTestId("route-loading-fallback")).toBeInTheDocument();
    expect(await screen.findByTestId("route-workflow-studio-page")).toBeInTheDocument();
  });

  it("shows a route fallback before /workflows/:workflowId finishes loading when authenticated", async () => {
    useAuthStore.setState({
      status: "authenticated",
      currentUser: { id: "usr_1", email: "alice@example.com" }
    });

    renderRoutes(["/workflows/wf_123"]);

    expect(screen.getByTestId("mock-app-layout")).toBeInTheDocument();
    expect(screen.getByTestId("route-loading-fallback")).toBeInTheDocument();
    expect(await screen.findByTestId("route-persisted-workflow-editor-page")).toBeInTheDocument();
  });

  it("shows a route fallback before /templates finishes loading when authenticated", async () => {
    useAuthStore.setState({
      status: "authenticated",
      currentUser: { id: "usr_1", email: "alice@example.com" }
    });

    renderRoutes(["/templates"]);

    expect(screen.getByTestId("mock-app-layout")).toBeInTheDocument();
    expect(screen.getByTestId("route-loading-fallback")).toBeInTheDocument();
    expect(await screen.findByText("Template Center Route")).toBeInTheDocument();
  });

});
