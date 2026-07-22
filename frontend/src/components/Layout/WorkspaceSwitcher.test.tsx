import React, { useEffect } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import { WorkspaceSwitcher, type WorkspaceSwitcherProps } from "./WorkspaceSwitcher";
import { useWorkflowPersistence } from "@/features/workflow-editor/hooks/useWorkflowPersistence";
import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";
import { usePermission } from "@/hooks/usePermission";
import { WorkspaceSwitchBlockedError } from "@/stores/workspaceStore";
import type { WorkspaceMembership, WorkspaceSummary } from "@/types/workspace";

const mockNavigate = vi.fn();

interface MockMenuItem {
  key?: React.Key;
  type?: "divider" | "group";
  label?: React.ReactNode;
  children?: MockMenuItem[];
  disabled?: boolean;
  onClick?: () => void;
}

vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock("@ant-design/icons", () => {
  const Icon = () => <span aria-hidden="true">icon</span>;
  return {
    ApiOutlined: Icon,
    DownOutlined: Icon,
    ExclamationCircleOutlined: Icon,
    HistoryOutlined: Icon,
    LoadingOutlined: Icon,
    PlusOutlined: Icon,
    SettingOutlined: Icon,
    TeamOutlined: Icon,
    UpOutlined: Icon,
  };
});

vi.mock("@/components/Permissions/RoleBadge", () => ({
  RoleBadge: ({ role }: { role: string }) => <span data-testid={`role-${role}`}>{role[0].toUpperCase() + role.slice(1)}</span>,
}));

vi.mock("antd", () => {
  const renderItem = (
    item: MockMenuItem,
    onOpenChange?: (open: boolean) => void,
  ): React.ReactNode => {
    if (!item) return null;
    if (item.type === "divider") return <hr key={Math.random()} />;
    if (item.type === "group") {
      return (
        <section key={item.key}>
          <div>{item.label}</div>
          <ul>{(item.children ?? []).map((child) => renderItem(child, onOpenChange))}</ul>
        </section>
      );
    }
    return (
      <li key={item.key} role="menuitem" aria-disabled={item.disabled ? "true" : undefined}>
        <button
          disabled={item.disabled}
          type="button"
          onClick={() => {
            item.onClick?.();
            onOpenChange?.(false);
          }}
        >
          {item.label}
        </button>
      </li>
    );
  };

  return {
    Alert: ({ message, action }: { message?: React.ReactNode; action?: React.ReactNode }) => (
      <div role="alert">
        <div>{message}</div>
        {action}
      </div>
    ),
    Button: ({
      block: _block,
      children,
      className,
      danger: _danger,
      disabled,
      htmlType,
      icon,
      loading: _loading,
      onClick,
      size: _size,
      type: _buttonType,
      "aria-label": ariaLabel,
      "data-testid": dataTestId,
    }: {
      children?: React.ReactNode;
      disabled?: boolean;
      icon?: React.ReactNode;
      onClick?: () => void;
      [key: string]: unknown;
    }) => (
      <button
        className={className as string | undefined}
        aria-label={ariaLabel as string | undefined}
        data-testid={dataTestId as string | undefined}
        disabled={disabled}
        onClick={onClick}
        type={(htmlType as "button" | "submit" | "reset" | undefined) ?? "button"}
      >
        {icon}
        {children}
      </button>
    ),
    Dropdown: ({
      children,
      disabled,
      menu,
      onOpenChange,
      open,
      popupRender,
    }: {
      children?: React.ReactNode;
      disabled?: boolean;
      menu?: { items?: MockMenuItem[] };
      onOpenChange?: (open: boolean) => void;
      open?: boolean;
      popupRender?: (menu: React.ReactNode) => React.ReactNode;
    }) => {
      useEffect(() => {
        if (!open) return;
        const closeOnEscape = (event: KeyboardEvent) => {
          if (event.key === "Escape") onOpenChange?.(false);
        };
        document.addEventListener("keydown", closeOnEscape);
        return () => document.removeEventListener("keydown", closeOnEscape);
      }, [onOpenChange, open]);

      const trigger = React.isValidElement(children)
        ? React.cloneElement(children, {
            onClick: () => {
              if (!disabled) onOpenChange?.(!open);
            },
          })
        : children;
      const menuNode = <div role="menu">{(menu?.items ?? []).map((item) => renderItem(item, onOpenChange))}</div>;
      return (
        <div>
          {trigger}
          {open ? (popupRender ? popupRender(menuNode) : menuNode) : null}
        </div>
      );
    },
    Modal: ({
      children,
      closable: _closable,
      destroyOnHidden: _destroyOnHidden,
      footer,
      maskClosable: _maskClosable,
      onCancel: _onCancel,
      open,
      title,
      "data-testid": dataTestId,
    }: {
      children?: React.ReactNode;
      footer?: React.ReactNode;
      open?: boolean;
      title?: React.ReactNode;
      [key: string]: unknown;
    }) => open ? (
      <div data-testid={dataTestId as string | undefined}>
        <div>{title}</div>
        <div>{children}</div>
        <div>{footer}</div>
      </div>
    ) : null,
    Tooltip: ({ children, title }: { children?: React.ReactNode; title?: React.ReactNode }) => (
      <span data-tooltip={typeof title === "string" ? title : undefined}>{children}</span>
    ),
  };
});

vi.mock("@/hooks/usePermission", () => ({
  usePermission: vi.fn(),
}));

vi.mock("@/features/workflow-editor/workflowPersistenceStore", () => ({
  useWorkflowPersistenceStore: vi.fn(),
}));

vi.mock("@/features/workflow-editor/hooks/useWorkflowPersistence", () => ({
  useWorkflowPersistence: vi.fn(),
}));

const mockCurrentWorkspace = {
  id: "ws-1",
  name: "Alpha Legal Lab",
  role: "owner" as const,
  isDefault: true,
  capabilities: [],
  memberCount: 12,
} as WorkspaceSummary;

const mockMemberships = [
  { workspace: mockCurrentWorkspace, role: "owner" as const, joinedAt: "2023-01-01", capabilities: [] },
  {
    workspace: { id: "ws-2", name: "Beta Review Ops", role: "runner" as const, isDefault: false, capabilities: [] },
    role: "runner" as const,
    joinedAt: "2023-01-01",
    capabilities: [],
  },
] as WorkspaceMembership[];

function openWorkspaceMenu() {
  fireEvent.click(screen.getByTestId("workspace-switcher-trigger"));
}

describe("WorkspaceSwitcher", () => {
  let defaultProps: WorkspaceSwitcherProps;
  let mockExplain: Mock;
  let mockReset: Mock;
  let mockSaveDraft: Mock;

  beforeEach(() => {
    mockNavigate.mockReset();
    window.history.pushState({}, "", "/settings/workspace");
    mockExplain = vi.fn().mockImplementation((capability: string) => ({
      allowed: true,
      capability,
      reason: undefined,
    }));
    vi.mocked(usePermission).mockReturnValue({
      explain: mockExplain,
      can: () => true,
      role: "owner",
    });

    mockReset = vi.fn();
    vi.mocked(useWorkflowPersistenceStore).mockReturnValue(mockReset);

    mockSaveDraft = vi.fn().mockResolvedValue(true);
    vi.mocked(useWorkflowPersistence).mockReturnValue({
      saveDraft: mockSaveDraft,
    } as unknown as ReturnType<typeof useWorkflowPersistence>);

    defaultProps = {
      currentWorkspace: mockCurrentWorkspace,
      memberships: mockMemberships,
      loading: false,
      switching: false,
      error: null,
      onSwitchWorkspace: vi.fn().mockResolvedValue(undefined),
      onRetry: vi.fn().mockResolvedValue(undefined),
      onOpenMembers: vi.fn(),
      onOpenProviders: vi.fn(),
      onOpenAudit: vi.fn(),
      onOpenSettings: vi.fn(),
      onCreateWorkspace: vi.fn(),
    };
  });

  it("renders the rich trigger with initials and role access", () => {
    render(<WorkspaceSwitcher {...defaultProps} />);

    const trigger = screen.getByTestId("workspace-switcher-trigger");
    expect(trigger).toHaveAccessibleName("Open workspace menu: Alpha Legal Lab");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveTextContent("AL");
    expect(trigger).toHaveTextContent("Owner access");
    expect(trigger).not.toHaveTextContent(/default workspace/i);
    expect(within(trigger).getByTestId("role-owner")).toHaveTextContent("Owner");
  });

  it("renders loading and switching as busy trigger states", () => {
    const { rerender } = render(<WorkspaceSwitcher {...defaultProps} loading />);
    let trigger = screen.getByTestId("workspace-switcher-trigger");
    expect(trigger).toBeDisabled();
    expect(trigger).toHaveAttribute("aria-busy", "true");
    expect(trigger).toHaveTextContent("Loading workspaces");

    rerender(<WorkspaceSwitcher {...defaultProps} switching />);
    trigger = screen.getByTestId("workspace-switcher-trigger");
    expect(trigger).toBeDisabled();
    expect(trigger).toHaveTextContent("Switching...");
  });

  it("renders an empty state with a working create action", () => {
    render(<WorkspaceSwitcher {...defaultProps} currentWorkspace={null} memberships={[]} />);
    expect(screen.getByText("No workspaces")).toBeInTheDocument();

    openWorkspaceMenu();
    expect(screen.getByText("No workspaces yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /New workspace/i }));
    expect(defaultProps.onCreateWorkspace).toHaveBeenCalledOnce();
  });

  it("allows authenticated-global workspace creation when the current workspace denies it", () => {
    mockExplain.mockImplementation((capability: string) => ({
      allowed: capability !== "workspace.create",
      capability,
      reason: "Requires a workspace role",
    }));
    render(<WorkspaceSwitcher {...defaultProps} />);

    openWorkspaceMenu();

    expect(screen.getByRole("button", { name: /New workspace/i })).toBeEnabled();
  });

  it("renders both rich menu sections, member count, and footer", () => {
    render(<WorkspaceSwitcher {...defaultProps} />);
    openWorkspaceMenu();

    expect(screen.getByText("Switch workspace")).toBeInTheDocument();
    expect(screen.getByText("Manage current workspace")).toBeInTheDocument();
    expect(screen.getByText("Invite people and assign access")).toBeInTheDocument();
    expect(screen.getByLabelText("12 members")).toHaveTextContent("12");
    expect(screen.getByRole("button", { name: /New workspace/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Settings/i })).toBeInTheDocument();
  });

  it("marks the current workspace and does not switch it again", () => {
    render(<WorkspaceSwitcher {...defaultProps} />);
    openWorkspaceMenu();

    const currentOption = screen.getByTestId("workspace-option-ws-1");
    expect(currentOption).toHaveAttribute("aria-current", "true");
    fireEvent.click(currentOption.closest("button")!);
    expect(defaultProps.onSwitchWorkspace).not.toHaveBeenCalled();
  });

  it("shows capability reasons on disabled management actions", () => {
    mockExplain.mockImplementation((capability: string) => ({
      allowed: capability !== "audit.view",
      reason: capability === "audit.view" ? "Requires owner or admin" : undefined,
    }));
    render(<WorkspaceSwitcher {...defaultProps} />);
    openWorkspaceMenu();

    const auditItem = screen.getByText("Audit").closest("li");
    expect(auditItem).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByText("Requires owner or admin")).toBeInTheDocument();
  });

  it("retries hydration errors without losing the rich trigger", async () => {
    render(<WorkspaceSwitcher {...defaultProps} error="Session unavailable" />);
    expect(screen.getByTestId("workspace-switcher-trigger")).toBeInTheDocument();
    openWorkspaceMenu();

    expect(screen.getAllByText("Session unavailable").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(defaultProps.onRetry).toHaveBeenCalledOnce());
  });

  it("renders revoked access with available recovery workspaces", () => {
    render(<WorkspaceSwitcher {...defaultProps} currentWorkspace={null} />);
    expect(screen.getByTestId("workspace-revoked-modal")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Switch to Beta Review Ops, Runner access" }));
    expect(defaultProps.onSwitchWorkspace).toHaveBeenCalledWith("ws-2");
  });

  it("shows a retryable menu error when switching fails", async () => {
    vi.mocked(defaultProps.onSwitchWorkspace).mockRejectedValueOnce(new Error("Switch failed"));
    render(<WorkspaceSwitcher {...defaultProps} />);

    openWorkspaceMenu();
    fireEvent.click(screen.getByTestId("workspace-option-ws-2").closest("button")!);

    await waitFor(() => expect(screen.getAllByText("Switch failed").length).toBeGreaterThan(0));
    vi.mocked(defaultProps.onSwitchWorkspace).mockResolvedValueOnce(undefined);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(defaultProps.onSwitchWorkspace).toHaveBeenLastCalledWith("ws-2"));
  });

  it("navigates to database after switching from a resource route", async () => {
    window.history.pushState({}, "", "/projects/abc");
    render(<WorkspaceSwitcher {...defaultProps} />);

    openWorkspaceMenu();
    fireEvent.click(screen.getByTestId("workspace-option-ws-2").closest("button")!);

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/database"));
  });

  it("remains on workspace settings after switching", async () => {
    render(<WorkspaceSwitcher {...defaultProps} />);

    openWorkspaceMenu();
    fireEvent.click(screen.getByTestId("workspace-option-ws-2").closest("button")!);

    await waitFor(() => expect(defaultProps.onSwitchWorkspace).toHaveBeenCalledWith("ws-2"));
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("does not switch if saveDraft fails in the block modal", async () => {
    vi.mocked(defaultProps.onSwitchWorkspace).mockRejectedValueOnce(
      new WorkspaceSwitchBlockedError("unsaved_changes", "Blocked")
    );
    render(<WorkspaceSwitcher {...defaultProps} />);

    openWorkspaceMenu();
    fireEvent.click(screen.getByTestId("workspace-option-ws-2").closest("button")!);
    expect(await screen.findByTestId("workspace-switch-blocked-modal")).toBeInTheDocument();

    mockSaveDraft.mockResolvedValueOnce(false);
    fireEvent.click(screen.getByRole("button", { name: "Save & switch" }));

    await waitFor(() => {
      expect(mockSaveDraft).toHaveBeenCalled();
      expect(defaultProps.onSwitchWorkspace).toHaveBeenCalledTimes(1);
      expect(screen.getByText("Failed to save draft. Please try again.")).toBeInTheDocument();
    });
  });

  it("shows an active-task blocker without save or discard actions", async () => {
    vi.mocked(defaultProps.onSwitchWorkspace).mockRejectedValueOnce(
      new WorkspaceSwitchBlockedError("active_execution", "Task is running")
    );
    render(<WorkspaceSwitcher {...defaultProps} />);

    openWorkspaceMenu();
    fireEvent.click(screen.getByTestId("workspace-option-ws-2").closest("button")!);

    const modal = await screen.findByTestId("workspace-switch-blocked-modal");
    expect(modal).toHaveTextContent("Task in progress");
    expect(modal).toHaveTextContent("Wait for the active task to finish or cancel it");
    expect(screen.queryByRole("button", { name: "Save & switch" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Discard changes & switch" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stay in current workspace" })).toBeInTheDocument();
  });

  it("keeps a retry path when switching fails after a successful draft save", async () => {
    vi.mocked(defaultProps.onSwitchWorkspace)
      .mockRejectedValueOnce(new WorkspaceSwitchBlockedError("unsaved_changes", "Blocked"))
      .mockRejectedValueOnce(new Error("Switch retry failed"));
    render(<WorkspaceSwitcher {...defaultProps} />);

    openWorkspaceMenu();
    fireEvent.click(screen.getByTestId("workspace-option-ws-2").closest("button")!);
    expect(await screen.findByTestId("workspace-switch-blocked-modal")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save & switch" }));

    await waitFor(() => expect(screen.getAllByText("Switch retry failed").length).toBeGreaterThan(0));
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("restores the old workflow context when discard switch fails", async () => {
    const oldContext = { workflowId: "workflow-1", isDirty: true };
    const setState = vi.fn();
    Object.assign(useWorkflowPersistenceStore, {
      getState: () => oldContext,
      setState,
    });
    vi.mocked(defaultProps.onSwitchWorkspace)
      .mockRejectedValueOnce(new WorkspaceSwitchBlockedError("unsaved_changes", "Blocked"))
      .mockRejectedValueOnce(new Error("Switch failed"));
    window.localStorage.setItem("workspace-context", "ws-1");
    render(<WorkspaceSwitcher {...defaultProps} />);

    openWorkspaceMenu();
    fireEvent.click(screen.getByTestId("workspace-option-ws-2").closest("button")!);
    expect(await screen.findByTestId("workspace-switch-blocked-modal")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Discard changes & switch" }));

    await waitFor(() => expect(screen.getAllByText("Switch failed").length).toBeGreaterThan(0));
    expect(setState).toHaveBeenCalledWith(oldContext, true);
    expect(window.localStorage.getItem("workspace-context")).toBe("ws-1");
  });

  it("closes with Escape and restores focus to the trigger", async () => {
    render(<WorkspaceSwitcher {...defaultProps} />);
    const trigger = screen.getByTestId("workspace-switcher-trigger");
    openWorkspaceMenu();
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => {
      expect(trigger).toHaveAttribute("aria-expanded", "false");
      expect(trigger).toHaveFocus();
    });
  });
});
