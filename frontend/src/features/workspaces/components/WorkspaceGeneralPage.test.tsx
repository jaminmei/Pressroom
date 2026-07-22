import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { message } from "antd";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkspaceGeneralPage from "./WorkspaceGeneralPage";
import { usePermission } from "@/hooks/usePermission";
import {
  deleteWorkspace,
  getWorkspaceDeletionImpact,
  listWorkspaceMembers,
  transferWorkspaceOwner,
} from "@/services/workspaceApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

const setFieldsValue = vi.fn();
const navigate = vi.fn();
const formInstance = {
  getFieldValue: vi.fn(),
  resetFields: vi.fn(),
  setFieldsValue,
  validateFields: vi.fn().mockResolvedValue({}),
};
const submittedValues = {
  name: "Renamed Workspace",
  description: "Updated description",
  isDefault: false,
};

vi.mock("antd", () => ({
  Alert: ({ message }: { message?: ReactNode }) => <div>{message}</div>,
  Button: ({ children, disabled, htmlType, danger: _danger, ...props }: { children?: ReactNode; disabled?: boolean; htmlType?: "button" | "submit"; danger?: boolean }) => (
    <button type={htmlType ?? "button"} disabled={disabled} {...props}>
      {children}
    </button>
  ),
  Card: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Form: Object.assign(
    ({ children, onFinish }: { children?: ReactNode; onFinish?: (values: typeof submittedValues) => void }) => (
      <form
        onSubmit={(event) => {
          event.preventDefault();
          onFinish?.(submittedValues);
        }}
      >
        {children}
      </form>
    ),
    {
      Item: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
      useForm: () => [formInstance],
    }
  ),
  Input: Object.assign(({ ...props }: Record<string, unknown>) => <input {...props} />, {
    TextArea: (props: Record<string, unknown>) => <textarea {...props} />,
  }),
  Modal: ({
    children,
    open,
    okText,
    okButtonProps,
    onOk,
    onCancel,
    title,
  }: {
    children?: ReactNode;
    open?: boolean;
    okText?: ReactNode;
    okButtonProps?: { disabled?: boolean };
    onOk?: () => void;
    onCancel?: () => void;
    title?: ReactNode;
  }) => open ? (
    <div role="dialog" aria-label={String(title)}>
      <h2>{title}</h2>
      {children}
      <button type="button" disabled={okButtonProps?.disabled} onClick={onOk}>{okText}</button>
      <button type="button" onClick={onCancel}>Cancel</button>
    </div>
  ) : null,
  Select: ({
    "aria-label": ariaLabel,
    onChange,
    options = [],
    value,
  }: {
    "aria-label"?: string;
    onChange?: (value: string) => void;
    options?: Array<{ value: string; label: string }>;
    value?: string;
  }) => (
    <select
      aria-label={ariaLabel}
      value={value ?? ""}
      onChange={(event) => onChange?.(event.target.value)}
    >
      <option value="" />
      {options.map((option) => (
        <option key={option.value} value={option.value}>{option.label}</option>
      ))}
    </select>
  ),
  Space: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Tooltip: ({ children }: { children?: ReactNode }) => <>{children}</>,
  Switch: (props: Record<string, unknown>) => <input type="checkbox" {...props} />,
  Typography: {
    Paragraph: ({ children }: { children?: ReactNode }) => <p>{children}</p>,
    Text: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
    Title: ({ children }: { children?: ReactNode }) => <h1>{children}</h1>,
  },
  message: { error: vi.fn(), info: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigate,
}));

vi.mock("@/stores/workspaceStore", () => ({
  useWorkspaceStore: Object.assign(vi.fn(), { getState: vi.fn() }),
}));

vi.mock("@/hooks/usePermission", () => ({
  usePermission: vi.fn(),
}));

vi.mock("@/services/workspaceApi", () => ({
  deleteWorkspace: vi.fn(),
  getWorkspaceDeletionImpact: vi.fn(),
  listWorkspaceMembers: vi.fn(),
  transferWorkspaceOwner: vi.fn(),
}));

describe("WorkspaceGeneralPage", () => {
  const updateWorkspace = vi.fn();
  const refreshWorkspaces = vi.fn();
  const baseState = {
    status: "ready" as const,
    currentWorkspace: {
      id: "ws-1",
      name: "Test Workspace",
      role: "admin" as const,
      description: null,
      isDefault: false,
      capabilities: [],
    },
    memberships: [],
    capabilities: [],
    error: null,
    isSwitching: false,
    contextGeneration: 0,
    hydrateWorkspaceSession: vi.fn(),
    refreshWorkspaces,
    switchWorkspace: vi.fn(),
    createWorkspace: vi.fn(),
    updateWorkspace,
    can: vi.fn(),
    explain: vi.fn(),
    resetWorkspaceState: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listWorkspaceMembers).mockResolvedValue({
      items: [
        {
          userId: "owner-1",
          email: "owner@example.com",
          name: "Workspace Owner",
          role: "owner",
          status: "active",
        },
      ],
      total: 1,
    });
    vi.mocked(getWorkspaceDeletionImpact).mockResolvedValue({
      canDelete: true,
      counts: {
        membersExcludingOwner: 0,
        workflows: 0,
        databases: 0,
        evaluationRuns: 0,
        taskRuns: 0,
        workspaceProviders: 0,
      },
    });
    refreshWorkspaces.mockResolvedValue(undefined);
  });

  it("saves details without exposing a default workspace control", async () => {
    updateWorkspace.mockResolvedValue({
      ...baseState.currentWorkspace,
      name: submittedValues.name,
      description: submittedValues.description,
    });
    vi.mocked(useWorkspaceStore).mockImplementation((selector) => selector(baseState));
    vi.mocked(useWorkspaceStore.getState).mockReturnValue(baseState);
    vi.mocked(usePermission).mockReturnValue({
      can: () => true,
      explain: () => ({ allowed: true, capability: "workspace.update", allowedRoles: [] }),
      role: "admin",
    });

    render(<WorkspaceGeneralPage />);
    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => {
      expect(updateWorkspace).toHaveBeenCalledWith("ws-1", submittedValues);
    });
    expect(setFieldsValue).toHaveBeenCalledWith({
      name: submittedValues.name,
      description: submittedValues.description,
    });
  });

  it("disables delete when lacking capability", async () => {
    vi.mocked(useWorkspaceStore).mockImplementation((selector) => selector(baseState));
    vi.mocked(usePermission).mockReturnValue({
      can: (cap) => cap !== "workspace.delete",
      explain: () => ({ allowed: false, capability: "workspace.delete", allowedRoles: [] }),
      role: "admin",
    });

    render(<WorkspaceGeneralPage />);

    await waitFor(() => expect(listWorkspaceMembers).toHaveBeenCalledWith("ws-1"));
    expect(screen.getByRole("button", { name: /delete workspace/i })).toBeDisabled();
  });

  it("keeps self-service leave disabled with the supported-contract reason", async () => {
    vi.mocked(useWorkspaceStore).mockImplementation((selector) =>
      selector({
        ...baseState,
        currentWorkspace: {
          ...baseState.currentWorkspace,
          role: "owner",
        },
      })
    );
    vi.mocked(usePermission).mockReturnValue({
      can: () => true,
      explain: () => ({ allowed: true, capability: "workspace.transfer_owner", allowedRoles: [] }),
      role: "owner",
    });

    render(<WorkspaceGeneralPage />);

    await waitFor(() => expect(listWorkspaceMembers).toHaveBeenCalledWith("ws-1"));
    expect(screen.getByRole("button", { name: /leave workspace/i })).toBeDisabled();
    expect(screen.getByText("Self-service leave is not yet supported")).toBeInTheDocument();
  });

  it("offers only active non-owner members and refreshes the session after transfer", async () => {
    vi.mocked(listWorkspaceMembers).mockResolvedValue({
      items: [
        {
          userId: "owner-1",
          email: "owner@example.com",
          role: "owner",
          status: "active",
        },
        {
          userId: "active-1",
          email: "active@example.com",
          name: "Active Member",
          role: "admin",
          status: "active",
        },
        {
          userId: "pending-1",
          email: "pending@example.com",
          role: "editor",
          status: "pending",
        },
      ],
      total: 3,
    });
    vi.mocked(transferWorkspaceOwner).mockResolvedValue({
      ...baseState.currentWorkspace,
      role: "admin",
    });
    vi.mocked(useWorkspaceStore).mockImplementation((selector) => selector({
      ...baseState,
      currentWorkspace: { ...baseState.currentWorkspace, role: "owner" },
    }));
    vi.mocked(usePermission).mockReturnValue({
      can: () => true,
      explain: () => ({ allowed: true, capability: "workspace.transfer_owner", allowedRoles: [] }),
      role: "owner",
    });

    render(<WorkspaceGeneralPage />);
    await waitFor(() => expect(listWorkspaceMembers).toHaveBeenCalledWith("ws-1"));
    fireEvent.click(screen.getByRole("button", { name: "Transfer" }));

    const ownerSelect = screen.getByLabelText("New workspace owner");
    expect(screen.getByRole("option", { name: /Active Member/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /pending@example.com/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /owner@example.com/ })).not.toBeInTheDocument();
    fireEvent.change(ownerSelect, { target: { value: "active-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Transfer ownership" }));

    await waitFor(() => {
      expect(transferWorkspaceOwner).toHaveBeenCalledWith("ws-1", {
        newOwnerUserId: "active-1",
      });
      expect(refreshWorkspaces).toHaveBeenCalled();
    });
  });

  it("requires the exact workspace name before deleting and navigates safely", async () => {
    vi.mocked(deleteWorkspace).mockResolvedValue(undefined);
    vi.mocked(useWorkspaceStore).mockImplementation((selector) => selector(baseState));
    vi.mocked(usePermission).mockReturnValue({
      can: () => true,
      explain: () => ({ allowed: true, capability: "workspace.delete", allowedRoles: [] }),
      role: "owner",
    });

    render(<WorkspaceGeneralPage />);
    await waitFor(() => expect(listWorkspaceMembers).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Delete workspace" }));

    const confirmation = screen.getByLabelText("Workspace name confirmation");
    const confirmButton = screen.getAllByRole("button", { name: "Delete workspace" })[1];
    fireEvent.change(confirmation, { target: { value: "test workspace" } });
    expect(confirmButton).toBeDisabled();
    fireEvent.change(confirmation, { target: { value: "Test Workspace" } });
    expect(confirmButton).toBeEnabled();
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(deleteWorkspace).toHaveBeenCalledWith("ws-1");
      expect(refreshWorkspaces).toHaveBeenCalled();
      expect(navigate).toHaveBeenCalledWith("/", { replace: true });
    });
  });

  it("blocks deletion from the canonical impact response", async () => {
    vi.mocked(getWorkspaceDeletionImpact).mockResolvedValue({
      canDelete: false,
      counts: {
        membersExcludingOwner: 1,
        workflows: 0,
        databases: 0,
        evaluationRuns: 0,
        taskRuns: 0,
        workspaceProviders: 0,
      },
    });
    vi.mocked(useWorkspaceStore).mockImplementation((selector) => selector(baseState));
    vi.mocked(usePermission).mockReturnValue({
      can: () => true,
      explain: () => ({ allowed: true, capability: "workspace.delete", allowedRoles: [] }),
      role: "owner",
    });

    render(<WorkspaceGeneralPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Delete workspace" })).toBeDisabled();
    });
    expect(screen.getByText(/still owns resources/i)).toBeInTheDocument();
  });

  it("ignores a stale member response after the active workspace changes", async () => {
    let resolveFirst!: (value: Awaited<ReturnType<typeof listWorkspaceMembers>>) => void;
    let resolveSecond!: (value: Awaited<ReturnType<typeof listWorkspaceMembers>>) => void;
    const firstResponse = new Promise<Awaited<ReturnType<typeof listWorkspaceMembers>>>((resolve) => {
      resolveFirst = resolve;
    });
    const secondResponse = new Promise<Awaited<ReturnType<typeof listWorkspaceMembers>>>((resolve) => {
      resolveSecond = resolve;
    });
    vi.mocked(listWorkspaceMembers).mockImplementation((workspaceId) =>
      workspaceId === "ws-1" ? firstResponse : secondResponse,
    );

    let selectedState = baseState;
    vi.mocked(useWorkspaceStore).mockImplementation((selector) => selector(selectedState));
    vi.mocked(usePermission).mockReturnValue({
      can: () => true,
      explain: () => ({ allowed: true, capability: "workspace.transfer_owner", allowedRoles: [] }),
      role: "owner",
    });

    const { rerender } = render(<WorkspaceGeneralPage />);
    await waitFor(() => expect(listWorkspaceMembers).toHaveBeenCalledWith("ws-1"));

    selectedState = {
      ...baseState,
      currentWorkspace: {
        ...baseState.currentWorkspace,
        id: "ws-2",
        name: "Second Workspace",
      },
    };
    rerender(<WorkspaceGeneralPage />);
    await waitFor(() => expect(listWorkspaceMembers).toHaveBeenCalledWith("ws-2"));
    fireEvent.click(screen.getByRole("button", { name: "Transfer" }));

    await act(async () => {
      resolveSecond({
        items: [{
          userId: "second-member",
          email: "second@example.com",
          role: "admin",
          status: "active",
        }],
        total: 1,
      });
    });
    expect(await screen.findByRole("option", { name: /second@example.com/ })).toBeInTheDocument();

    await act(async () => {
      resolveFirst({
        items: [{
          userId: "stale-member",
          email: "stale@example.com",
          role: "admin",
          status: "active",
        }],
        total: 1,
      });
    });
    expect(screen.queryByRole("option", { name: /stale@example.com/ })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: /second@example.com/ })).toBeInTheDocument();
  });

  it("clears a deleted workspace context when fallback refresh fails", async () => {
    vi.mocked(deleteWorkspace).mockResolvedValue(undefined);
    refreshWorkspaces.mockRejectedValue(new Error("Session unavailable"));
    vi.mocked(useWorkspaceStore).mockImplementation((selector) => selector(baseState));
    vi.mocked(usePermission).mockReturnValue({
      can: () => true,
      explain: () => ({ allowed: true, capability: "workspace.delete", allowedRoles: [] }),
      role: "owner",
    });

    render(<WorkspaceGeneralPage />);
    await waitFor(() => expect(listWorkspaceMembers).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Delete workspace" }));
    fireEvent.change(screen.getByLabelText("Workspace name confirmation"), {
      target: { value: "Test Workspace" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Delete workspace" })[1]);

    await waitFor(() => {
      expect(baseState.resetWorkspaceState).toHaveBeenCalled();
      expect(navigate).toHaveBeenCalledWith("/", { replace: true });
    });
    expect(message.warning).toHaveBeenCalledWith(
      expect.stringContaining("Workspace deleted, but the fallback session could not refresh"),
    );
  });
});
