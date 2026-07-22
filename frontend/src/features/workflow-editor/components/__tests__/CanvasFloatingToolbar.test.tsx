import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Modal } from "antd";

import CanvasFloatingToolbar from "@/features/workflow-editor/components/CanvasFloatingToolbar";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { initialUIState, useUIStore } from "@/stores/uiStore";

/* ── Mock: useWorkflowValidation ── */
const mockValidation = {
  blockingErrors: [] as { code: string; severity: string; message: string }[],
  warnings: [],
  isExecutable: true,
  errorCountByNode: {},
  validateConnection: () => ({ valid: true })
};

vi.mock("@/features/workflow-editor/hooks/useWorkflowValidation", () => ({
  useWorkflowValidation: () => mockValidation
}));

/* ── Mock: useWorkflowPersistence ── */
const mockPublishUnified = vi.fn().mockResolvedValue(true);
const mockPublishAsWorkflow = vi.fn().mockResolvedValue(true);
const mockLoadVersion = vi.fn().mockResolvedValue(true);
const mockRestoreVersion = vi.fn().mockResolvedValue(true);
const mockPersistence = {
  workflowId: "wf-1" as string | null,
  workflowName: "Test Workflow",
  publishUnified: mockPublishUnified,
  publishAsWorkflow: mockPublishAsWorkflow,
  loadVersion: mockLoadVersion,
  latestVersion: 1,
  baseVersion: null as number | null,
  restoreVersion: mockRestoreVersion,
  versions: [{ version: 1, status: "published", created_at: "2026-01-01T00:00:00Z" }] as Array<{ version: number; status: "saved" | "published"; created_at: string }>
};

vi.mock("@/features/workflow-editor/hooks/useWorkflowPersistence", () => ({
  useWorkflowPersistence: () => mockPersistence
}));

/* ── Mock: sub-components to avoid deep rendering ── */
vi.mock("@/features/workflow-editor/components/ValidationPanel", () => ({
  default: (props: { isOpen: boolean }) => (
    <div data-testid="validation-panel" data-open={props.isOpen} />
  )
}));

vi.mock("@/features/workflow-editor/components/TemplateDialog", () => ({
  default: (props: { open: boolean; onCancel: () => void }) => (
    <div data-testid="template-dialog" data-open={props.open}>
      <button data-testid="template-dialog-close" onClick={props.onCancel} type="button">
        Close
      </button>
    </div>
  )
}));

vi.mock("@/features/workflow-editor/components/RunNameDialog", () => ({
  default: (props: { open: boolean; onConfirm: (name: string) => void; onCancel: () => void }) => (
    <div data-testid="run-name-dialog" data-open={props.open}>
      <button
        data-testid="run-name-confirm"
        onClick={() => props.onConfirm("test-run")}
        type="button"
      >
        Confirm
      </button>
      <button data-testid="run-name-cancel" onClick={props.onCancel} type="button">
        Cancel
      </button>
    </div>
  )
}));

import type { TaskStatus } from "@/types/task";

/* ── Helpers ── */
const defaultProps: {
  onExecuteWorkflow: () => Promise<{ ok: true; errors: never[] }>;
  taskStatus: TaskStatus | "idle";
} = {
  onExecuteWorkflow: vi.fn().mockResolvedValue({ ok: true, errors: [] }),
  taskStatus: "idle"
};

function renderToolbar(overrides: Partial<typeof defaultProps> = {}) {
  return render(<CanvasFloatingToolbar {...defaultProps} {...overrides} />);
}

/* ── Tests ── */
describe("CanvasFloatingToolbar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTaskExecutionStore.getState().reset();
    useUIStore.setState(initialUIState);
    useWorkflowStore.setState({ nodes: [], edges: [], selectedNodeId: null });
    mockValidation.blockingErrors = [];
    mockValidation.isExecutable = true;
    mockPersistence.versions = [{ version: 1, status: "published", created_at: "2026-01-01T00:00:00Z" }];
    mockPersistence.workflowId = "wf-1";
  });

  /* T-01 */
  it("renders without error", () => {
    renderToolbar();
    expect(screen.getByTestId("canvas-floating-toolbar")).toBeInTheDocument();
  });

  /* T-02 */
  it("renders all 7 icon buttons", () => {
    renderToolbar();
    const testIds = [
      "floating-btn-run",
      "floating-btn-validate",
      "floating-btn-clear",
      "floating-btn-template",
      "floating-btn-publish-as",
      "floating-btn-publish",
      "floating-btn-restore"
    ];
    for (const testId of testIds) {
      expect(screen.getByTestId(testId)).toBeInTheDocument();
    }
  });

  /* T-03 */
  it("execution group has 4 buttons", () => {
    renderToolbar();
    const group = screen.getByTestId("canvas-floating-toolbar-execution");
    const buttons = group.querySelectorAll("button");
    expect(buttons).toHaveLength(4);
  });

  /* T-04 */
  it("persistence group has 3 buttons", () => {
    renderToolbar();
    const group = screen.getByTestId("canvas-floating-toolbar-persistence");
    const buttons = group.querySelectorAll("button");
    expect(buttons).toHaveLength(3);
  });

  /* T-05 */
  it("renders a divider element between groups", () => {
    renderToolbar();
    const toolbar = screen.getByTestId("canvas-floating-toolbar");
    const divider = toolbar.querySelector(".canvas-floating-toolbar-divider");
    expect(divider).toBeInTheDocument();
  });

  /* T-06 */
  it("shows 'Run' tooltip on Run button hover", async () => {
    renderToolbar();
    fireEvent.mouseEnter(screen.getByTestId("floating-btn-run"));
    await waitFor(() => {
      expect(screen.getByText("Run")).toBeInTheDocument();
    });
  });

  /* T-07 */
  it("shows 'Publish As' tooltip on Publish As button hover", async () => {
    renderToolbar();
    fireEvent.mouseEnter(screen.getByTestId("floating-btn-publish-as"));
    await waitFor(() => {
      expect(screen.getByText("Publish As")).toBeInTheDocument();
    });
  });

  /* T-08 */
  it("shows 'Re-run' tooltip when taskStatus is completed", async () => {
    renderToolbar({ taskStatus: "completed" });
    fireEvent.mouseEnter(screen.getByTestId("floating-btn-run"));
    await waitFor(() => {
      expect(screen.getByText("Re-run")).toBeInTheDocument();
    });
  });

  /* T-09 */
  it("click Run opens RunNameDialog when executable", async () => {
    renderToolbar();
    fireEvent.click(screen.getByTestId("floating-btn-run"));
    await waitFor(() => {
      expect(screen.getByTestId("run-name-dialog")).toHaveAttribute("data-open", "true");
    });
  });

  /* T-09b */
  it("Run button remains enabled with blocking errors and click opens ValidationPanel", async () => {
    mockValidation.blockingErrors = [{ code: "MISSING", severity: "blocking", message: "err" }];
    renderToolbar();
    const runBtn = screen.getByTestId("floating-btn-run");
    expect(runBtn).not.toBeDisabled();
    fireEvent.click(runBtn);
    await waitFor(() => {
      expect(screen.getByTestId("validation-panel")).toHaveAttribute("data-open", "true");
    });
  });

  /* T-09c */
  it("validation panel opens via CustomEvent when not executable", async () => {
    mockValidation.blockingErrors = [{ code: "MISSING", severity: "blocking", message: "err" }];
    renderToolbar();
    act(() => {
      window.dispatchEvent(new CustomEvent("workflow:execute-request"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("validation-panel")).toHaveAttribute("data-open", "true");
    });
  });

  /* T-10 */
  it("click Clear triggers Modal.confirm", () => {
    const confirmSpy = vi.spyOn(Modal, "confirm").mockImplementation(() => ({ destroy: vi.fn(), update: vi.fn(), then: vi.fn() }));
    renderToolbar();
    fireEvent.click(screen.getByTestId("floating-btn-clear"));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    confirmSpy.mockRestore();
  });

  /* T-11 */
  it("click Template opens TemplateDialog", () => {
    renderToolbar();
    fireEvent.click(screen.getByTestId("floating-btn-template"));
    expect(screen.getByTestId("template-dialog")).toHaveAttribute("data-open", "true");
  });

  /* T-12 */
  it("click Publish opens publishExisting dialog when workflowId exists", async () => {
    renderToolbar();
    fireEvent.click(screen.getByTestId("floating-btn-publish"));
    await waitFor(() => {
      expect(screen.getByText("Publish New Version")).toBeInTheDocument();
    });
  });

  /* T-13 */
  it("click Publish opens name dialog when no workflowId", async () => {
    mockPersistence.workflowId = null;
    renderToolbar();
    fireEvent.click(screen.getByTestId("floating-btn-publish"));
    await waitFor(() => {
      expect(screen.getByTestId("workflow-name-dialog-input")).toBeInTheDocument();
    });
  });

  /* T-14 */
  it("click Publish As opens the name dialog", async () => {
    renderToolbar();
    fireEvent.click(screen.getByTestId("floating-btn-publish-as"));
    await waitFor(() => {
      expect(screen.getByTestId("workflow-name-dialog-input")).toBeInTheDocument();
    });
  });

  /* T-17 */
  it("Run button is disabled when taskStatus is running", () => {
    renderToolbar({ taskStatus: "running" });
    expect(screen.getByTestId("floating-btn-run")).toBeDisabled();
  });

  /* T-18 */
  it("Run button is disabled when taskStatus is pending", () => {
    renderToolbar({ taskStatus: "pending" });
    expect(screen.getByTestId("floating-btn-run")).toBeDisabled();
  });

  /* T-20 */
  it("Restore button is disabled when versions are empty", () => {
    mockPersistence.versions = [];
    renderToolbar();
    expect(screen.getByTestId("floating-btn-restore")).toBeDisabled();
  });

  /* T-21 */
  it("renders version selector when workflowId and versions exist", () => {
    mockPersistence.versions = [{ version: 1, status: "published", created_at: "2026-01-01T00:00:00Z" }, { version: 2, status: "saved", created_at: "2026-01-02T00:00:00Z" }];
    mockPersistence.latestVersion = 2;
    mockPersistence.baseVersion = null;
    renderToolbar();
    expect(screen.getByTestId("version-selector")).toBeInTheDocument();
  });

  /* T-22 */
  it("does not render version selector when no workflowId", () => {
    mockPersistence.workflowId = null;
    mockPersistence.versions = [{ version: 1, status: "saved", created_at: "2026-01-01T00:00:00Z" }];
    renderToolbar();
    expect(screen.queryByTestId("version-selector")).not.toBeInTheDocument();
  });

  /* T-23 */
  it("does not render version selector when versions are empty", () => {
    mockPersistence.versions = [];
    renderToolbar();
    expect(screen.queryByTestId("version-selector")).not.toBeInTheDocument();
  });
});
