import "@testing-library/jest-dom/vitest";
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Header from "@/components/Layout/Header";
import {
  experimentalChatboxStorageKey,
  useChatboxPreferenceStore,
} from "@/features/chatbox/chatboxPreferenceStore";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { initialAuthState, useAuthStore } from "@/stores/authStore";
import { initialUIState, useUIStore } from "@/stores/uiStore";
import i18n from "@/i18n";
import { LANGUAGE_STORAGE_KEY } from "@/i18n/language";

interface MockDropdownItem {
  "data-testid"?: string;
  disabled?: boolean;
  key?: React.Key;
  label?: React.ReactNode;
  children?: MockDropdownItem[];
  onClick?: (info: { domEvent: React.MouseEvent<HTMLButtonElement> }) => void;
  type?: string;
}

function renderDropdownItems(items: MockDropdownItem[], selectedKeys: React.Key[] = []): React.ReactNode {
  return items.map((item, index) => {
    if (item?.type === "divider") return <hr key={`divider-${index}`} />;
    if (item?.type === "group") {
      return (
        <div key={item.key}>
          <span>{item.label}</span>
          {renderDropdownItems(item.children ?? [], selectedKeys)}
        </div>
      );
    }
    return (
      <button
        aria-checked={selectedKeys.includes(item.key ?? "")}
        data-testid={item?.["data-testid"]}
        disabled={item?.disabled}
        key={item?.key}
        onClick={(event) => item?.onClick?.({ domEvent: event })}
        role="menuitemradio"
        type="button"
      >
        {item?.label}
      </button>
    );
  });
}

const mocks = vi.hoisted(() => ({
  createWorkspace: vi.fn(),
  errorMessage: vi.fn(),
  refresh: vi.fn(),
  successMessage: vi.fn(),
  switchWorkspace: vi.fn(),
}));

vi.mock("@ant-design/icons", () => ({
  SearchOutlined: () => <span data-testid="search-icon-mock">search</span>,
  UserOutlined: () => <span data-testid="user-icon-mock">user</span>,
}));

vi.mock("@/hooks/useWorkspace", () => ({
  useWorkspace: () => ({
    currentWorkspace: {
      id: "ws-test",
      name: "Test Workspace",
      isDefault: true,
      role: "owner",
      capabilities: [],
    },
    memberships: [
      {
        workspace: {
          id: "ws-test",
          name: "Test Workspace",
          isDefault: true,
          role: "owner",
          capabilities: [],
        },
        role: "owner",
        capabilities: [],
      },
    ],
    status: "ready",
    isSwitching: false,
    error: null,
    switchWorkspace: mocks.switchWorkspace,
    createWorkspace: mocks.createWorkspace,
    refresh: mocks.refresh,
  }),
}));

vi.mock("@/components/Layout/WorkspaceSwitcher", () => ({
  WorkspaceSwitcher: ({
    currentWorkspace,
    onCreateWorkspace,
  }: {
    currentWorkspace: { name: string } | null;
    onCreateWorkspace: () => void;
  }) => (
    <div data-testid="workspace-switcher">
      <span>{currentWorkspace?.name ?? "No workspace"}</span>
      <button data-testid="workspace-switcher-create" onClick={onCreateWorkspace} type="button">
        New workspace
      </button>
    </div>
  ),
}));

vi.mock("@/features/workspaces/components/NewWorkspaceDialog", () => ({
  NewWorkspaceDialog: ({
    onCancel,
    onSubmit,
    open,
    submitting,
  }: {
    onCancel: () => void;
    onSubmit: (payload: { name: string; description?: string }) => void | Promise<void>;
    open: boolean;
    submitting?: boolean;
  }) => open ? (
    <div data-testid="new-workspace-dialog">
      <span>{submitting ? "Creating" : "Ready"}</span>
      <button onClick={onCancel} type="button">Cancel</button>
      <button onClick={() => void onSubmit({ name: "Legal Conversion Lab" })} type="button">Create workspace</button>
    </div>
  ) : null,
}));

vi.mock("antd", () => ({
  App: {
    useApp: () => ({
      message: {
        error: mocks.errorMessage,
        success: mocks.successMessage,
      },
    }),
  },
  Avatar: ({
    "aria-label": ariaLabel,
    children,
    "data-testid": dataTestId,
  }: {
    "aria-label"?: string;
    children?: React.ReactNode;
    "data-testid"?: string;
  }) => <span aria-label={ariaLabel} data-testid={dataTestId}>{children}</span>,
  Button: ({
    children,
    className,
    "data-testid": dataTestId,
    icon,
    onClick,
    title,
  }: {
    children?: React.ReactNode;
    className?: string;
    "data-testid"?: string;
    icon?: React.ReactNode;
    onClick?: () => void;
    title?: string;
  }) => (
    <button className={className} data-testid={dataTestId} onClick={onClick} title={title} type="button">
      {icon}
      {children}
    </button>
  ),
  Dropdown: ({ children, menu }: { children?: React.ReactNode; menu?: { items?: MockDropdownItem[]; selectedKeys?: React.Key[] } }) => (
    <div data-testid="dropdown-mock">
      {children}
      {renderDropdownItems(menu?.items ?? [], menu?.selectedKeys ?? [])}
    </div>
  ),
  Switch: ({
    "data-testid": dataTestId,
    checked,
    onClick,
  }: {
    "data-testid"?: string;
    checked?: boolean;
    onClick?: (checked: boolean, event: React.MouseEvent<HTMLElement>) => void;
  }) => (
    <span
      aria-checked={checked}
      data-testid={dataTestId}
      onClick={(event) => onClick?.(!checked, event)}
      role="switch"
      tabIndex={0}
    />
  ),
  theme: {
    useToken: () => ({ token: { colorPrimary: "#7132f5" } }),
  },
}));

describe("Header", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    window.localStorage.clear();
    useChatboxPreferenceStore.setState({ enabledByUser: {} });
    await i18n.changeLanguage("en");
    document.documentElement.lang = "en";
    mocks.createWorkspace.mockResolvedValue({
      id: "ws-new",
      name: "Legal Conversion Lab",
      isDefault: false,
      role: "owner",
      capabilities: [],
    });
    mocks.successMessage.mockResolvedValue(undefined);
    mocks.errorMessage.mockResolvedValue(undefined);
    useUIStore.setState(initialUIState);
    useTaskExecutionStore.getState().reset();
    useAuthStore.setState({
      ...initialAuthState,
      status: "authenticated",
      currentUser: { id: "usr_1", email: "alice@example.com", name: "Alice" },
      hydrateSession: useAuthStore.getState().hydrateSession,
      login: useAuthStore.getState().login,
      register: useAuthStore.getState().register,
      logout: vi.fn().mockResolvedValue(undefined),
      rememberIntendedRoute: useAuthStore.getState().rememberIntendedRoute,
      consumeIntendedRoute: useAuthStore.getState().consumeIntendedRoute,
      allowRedirectCapture: useAuthStore.getState().allowRedirectCapture,
      handleUnauthorized: useAuthStore.getState().handleUnauthorized,
    });
  });

  it("renders the workspace switcher", () => {
    render(<MemoryRouter><Header /></MemoryRouter>);
    expect(screen.getByTestId("workspace-switcher")).toHaveTextContent("Test Workspace");
  });

  it("shows domain tabs and Search text", () => {
    render(<MemoryRouter><Header /></MemoryRouter>);

    expect(screen.getByTestId("domain-tab-workflows")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("domain-tab-database")).toHaveTextContent("Database");
    expect(screen.getByTestId("command-palette-trigger")).toHaveTextContent("Search");
  });

  it("does not highlight a product domain on Settings routes", () => {
    render(<MemoryRouter initialEntries={["/settings/workspace/members"]}><Header /></MemoryRouter>);

    expect(screen.getByTestId("domain-tab-workflows")).not.toHaveClass("is-active");
    expect(screen.getByTestId("domain-tab-workflows")).not.toHaveAttribute("aria-current");
    expect(screen.getByTestId("domain-tab-database")).not.toHaveClass("is-active");
    expect(screen.getByTestId("domain-tab-database")).not.toHaveAttribute("aria-current");
  });

  it("opens the command palette from the Search button", () => {
    render(<MemoryRouter><Header /></MemoryRouter>);
    fireEvent.click(screen.getByTestId("command-palette-trigger"));
    expect(useUIStore.getState().commandPaletteOpen).toBe(true);
  });

  it("gives the Search button its keyboard shortcut tooltip", () => {
    render(<MemoryRouter><Header /></MemoryRouter>);
    expect(screen.getByTestId("command-palette-trigger")).toHaveAttribute("title", "Search (Ctrl/Cmd+K)");
  });

  it("shows the user initial and logout action", () => {
    render(<MemoryRouter><Header /></MemoryRouter>);
    expect(screen.getByTestId("auth-current-user")).toHaveTextContent("A");
    expect(screen.getByTestId("auth-logout-button")).toBeInTheDocument();
  });

  it("shows both language choices and switches immediately with selection state", async () => {
    render(<MemoryRouter><Header /></MemoryRouter>);

    expect(screen.getByText("Language")).toBeInTheDocument();
    expect(screen.getByTestId("language-option-en")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("language-option-zh-TW")).toHaveAttribute("aria-checked", "false");

    fireEvent.click(screen.getByTestId("language-option-zh-TW"));

    await waitFor(() => {
      expect(document.documentElement.lang).toBe("zh-TW");
      expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("zh-TW");
      expect(screen.getByTestId("domain-tab-database")).toHaveTextContent("資料庫");
      expect(screen.getByTestId("language-option-zh-TW")).toHaveAttribute("aria-checked", "true");
    });

    fireEvent.click(screen.getByTestId("language-option-en"));
    await waitFor(() => {
      expect(document.documentElement.lang).toBe("en");
      expect(screen.getByTestId("domain-tab-database")).toHaveTextContent("Database");
    });
  });

  it("offers an opt-in experimental Chatbox switch scoped to the current user", () => {
    render(<MemoryRouter><Header /></MemoryRouter>);
    const toggle = screen.getByTestId("experimental-chatbox-toggle");

    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(window.localStorage.getItem(experimentalChatboxStorageKey("usr_1"))).toBe("true");
  });

  it("toggles the experimental Chatbox from the menu label", () => {
    render(<MemoryRouter><Header /></MemoryRouter>);

    fireEvent.click(screen.getByText("Chatbox (Experimental)"));

    expect(screen.getByTestId("experimental-chatbox-toggle")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(window.localStorage.getItem(experimentalChatboxStorageKey("usr_1"))).toBe("true");
  });

  it("keeps logout behavior unchanged", async () => {
    const logout = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({ logout });
    render(<MemoryRouter><Header /></MemoryRouter>);

    fireEvent.click(screen.getByTestId("auth-logout-button"));
    await waitFor(() => expect(logout).toHaveBeenCalledOnce());
  });

  it("creates a workspace without switching the current workspace", async () => {
    render(<MemoryRouter><Header /></MemoryRouter>);
    fireEvent.click(screen.getByTestId("workspace-switcher-create"));
    expect(screen.getByTestId("new-workspace-dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));

    await waitFor(() => {
      expect(mocks.createWorkspace).toHaveBeenCalledWith({ name: "Legal Conversion Lab" });
      expect(mocks.successMessage).toHaveBeenCalledWith(expect.stringContaining("Select it from the workspace menu"));
      expect(screen.queryByTestId("new-workspace-dialog")).not.toBeInTheDocument();
    });
    expect(mocks.switchWorkspace).not.toHaveBeenCalled();
    expect(screen.getByTestId("workspace-switcher")).toHaveTextContent("Test Workspace");
  });

  it("keeps the create dialog open and reports API failures", async () => {
    mocks.createWorkspace.mockRejectedValueOnce(new Error("Name already exists"));
    render(<MemoryRouter><Header /></MemoryRouter>);
    fireEvent.click(screen.getByTestId("workspace-switcher-create"));
    fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));

    await waitFor(() => expect(mocks.errorMessage).toHaveBeenCalledWith("Name already exists"));
    expect(screen.getByTestId("new-workspace-dialog")).toBeInTheDocument();
  });

  it("resets task execution and returns to config when clicking the brand", () => {
    useUIStore.getState().setRightPanelTab("history");
    useTaskExecutionStore.getState().setTaskId("task-123");
    useTaskExecutionStore.getState().setTaskStatus("running");
    useTaskExecutionStore.getState().appendEventLog("running");

    render(<MemoryRouter initialEntries={["/results"]}><Header /></MemoryRouter>);
    fireEvent.click(screen.getByTestId("app-brand"));

    expect(useUIStore.getState().rightPanelTab).toBe("config");
    expect(useTaskExecutionStore.getState().currentTaskId).toBeNull();
    expect(useTaskExecutionStore.getState().taskStatus).toBe("idle");
    expect(useTaskExecutionStore.getState().eventLogs).toHaveLength(0);
  });
});
