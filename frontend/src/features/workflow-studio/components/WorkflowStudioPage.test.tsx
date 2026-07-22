import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import WorkflowStudioPage from "@/features/workflow-studio/components/WorkflowStudioPage";
import { useResultStore } from "@/features/result/store";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";
import { deleteWorkflow, getWorkflowList, updateWorkflowMetadata } from "@/services/workflowApi";
import { initialUIState, useUIStore } from "@/stores/uiStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";

const navigateMock = vi.fn();
const modalConfirmMock = vi.fn();
const messageSuccessMock = vi.fn();
const messageErrorMock = vi.fn();

vi.mock("@/services/workflowApi", async () => {
  const actual = await vi.importActual<typeof import("@/services/workflowApi")>("@/services/workflowApi");
  return {
    ...actual,
    deleteWorkflow: vi.fn(),
    getWorkflowList: vi.fn(),
    updateWorkflowMetadata: vi.fn()
  };
});

vi.mock("antd", async () => {
  const actual = await vi.importActual<typeof import("antd")>("antd");
  return {
    ...actual,
    Modal: Object.assign(actual.Modal, {
      confirm: (...args: unknown[]) => modalConfirmMock(...args)
    }),
    message: {
      success: (...args: unknown[]) => messageSuccessMock(...args),
      error: (...args: unknown[]) => messageErrorMock(...args)
    }
  };
});

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock
  };
});

function renderPage() {
  return render(
    <MemoryRouter>
      <WorkflowStudioPage />
    </MemoryRouter>
  );
}

function sampleWorkflow(overrides: Partial<Awaited<ReturnType<typeof getWorkflowList>>["items"][number]> = {}) {
  return {
    id: "wf_1",
    name: "Invoice OCR",
    description: "AP invoice compare",
    created_at: "2026-03-18T00:00:00Z",
    updated_at: "2026-03-18T00:01:00Z",
    published_version: 1,
    latest_version: 1,
    ...overrides
  };
}

function seedEditorState(uploadedFile: File) {
  useWorkflowStore.setState({
    nodes: [
      {
        id: "input_1",
        type: "input/pdf",
        position: { x: 120, y: 140 },
        data: {
          label: "PDF Input",
          config: {},
          configSchema: {
            type: "object",
            properties: {}
          }
        }
      }
    ],
    edges: [],
    nodeConfigs: {
      input_1: { file: "legacy.pdf" }
    },
    uploadedFiles: {
      input_1: uploadedFile
    },
    selectedNodeId: "input_1",
    nodeRegistry: { nodes: [], connection_rules: [] }
  });
  useWorkflowPersistenceStore.setState({
    workflowId: "wf_existing",
    isDirty: true,
    latestVersion: 3,
    publishedVersion: 2,
    versions: [
      {
        version: 2,
        status: "published",
        created_at: "2026-03-18T00:05:00Z"
      }
    ],
    lastSavedAt: "2026-03-18T00:05:00Z"
  });
  useTaskExecutionStore.setState({
    currentTaskId: "task_legacy",
    taskStatus: "completed",
    wsConnected: true,
    nodeStatuses: {
      input_1: "completed"
    },
    nodeProgress: {
      input_1: 100
    },
    nodeErrors: {
      input_1: "legacy error"
    },
    eventLogs: [
      {
        id: "log_1",
        timestamp: "2026-03-18T00:06:00Z",
        level: "info",
        message: "legacy run"
      }
    ],
    progress: {
      total_nodes: 1,
      completed_nodes: 1,
      failed_nodes: 0,
      pending_nodes: 0,
      current_node: null,
      percentage: 100
    },
    wsWarning: "stale warning",
    manualReconnectAvailable: true,
    executionStartedAt: 123
  });
  useResultStore.setState({
    taskId: "task_legacy",
    results: [
      {
        result_id: "result_1",
        node_id: "output_1",
        node_type: "output/markdown",
        status: "completed",
        result_preview: "legacy preview",
        file: {
          filename: "legacy.md",
          size_bytes: 12,
          content_type: "text/markdown",
          download_url: "/download/legacy.md"
        },
        metadata: {
          processing_time_ms: 200,
          page_count: 1,
          char_count: 12,
          word_count: 2
        },
        content: "legacy content"
      }
    ],
    displayMode: "raw"
  });
}

describe("WorkflowStudioPage", () => {
  beforeEach(() => {
    navigateMock.mockReset();
    modalConfirmMock.mockReset();
    messageSuccessMock.mockReset();
    messageErrorMock.mockReset();
    vi.mocked(getWorkflowList).mockReset();
    vi.mocked(deleteWorkflow).mockReset();
    vi.mocked(updateWorkflowMetadata).mockReset();
    useWorkflowStore.getState().clearCanvas();
    useWorkflowPersistenceStore.getState().reset();
    useTaskExecutionStore.getState().reset();
    useResultStore.getState().reset();
    useUIStore.setState({ ...initialUIState });
    useWorkspaceStore.setState({
      currentWorkspace: null,
      capabilities: ["workflow.create", "workflow.edit_draft", "workflow.delete", "api_key.view"]
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders workflow rows with metadata from the backend list contract", async () => {
    vi.mocked(getWorkflowList).mockResolvedValue({
      success: true,
      items: [sampleWorkflow({ published_version: 2, latest_version: 3 })],
      meta: {
        total: 1,
        page: 1,
        limit: 20
      }
    });

    renderPage();

    expect(await screen.findByText("Invoice OCR")).toBeInTheDocument();
    expect(screen.getByText("AP invoice compare")).toBeInTheDocument();
    expect(screen.getByText("Published v2")).toBeInTheDocument();
    expect(screen.getByText("Latest v3")).toBeInTheDocument();
    expect(screen.getByTestId("workflow-studio-total")).toHaveTextContent("1 saved workflow");
  });

  it.each([
    {
      role: "editor" as const,
      capabilities: ["workflow.create", "workflow.edit_draft"] as const,
      canCreate: true,
      canRename: true
    },
    { role: "runner" as const, capabilities: [] as const, canCreate: false, canRename: false },
    { role: "viewer" as const, capabilities: [] as const, canCreate: false, canRename: false }
  ])("applies Studio capabilities for $role", async ({ role, capabilities, canCreate, canRename }) => {
    vi.mocked(getWorkflowList).mockResolvedValue({
      success: true,
      items: [sampleWorkflow({ published_version: 1 })],
      meta: { total: 1, page: 1, limit: 20 }
    });
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: `ws-${role}`,
        name: `${role} workspace`,
        isDefault: false,
        role,
        capabilities: []
      },
      capabilities: [...capabilities]
    });

    renderPage();

    expect(await screen.findByText("Invoice OCR")).toBeInTheDocument();
    const createButton = screen.getByTestId("workflow-studio-create-button");
    const renameButton = screen.getByTestId("workflow-studio-rename-wf_1");
    if (canCreate) expect(createButton).toBeEnabled();
    else expect(createButton).toBeDisabled();
    if (canRename) expect(renameButton).toBeEnabled();
    else expect(renameButton).toBeDisabled();
    expect(screen.getByTestId("workflow-studio-api-access-wf_1")).toBeDisabled();
    expect(screen.getByTestId("workflow-studio-open-wf_1")).toBeEnabled();
  });

  it("does not show a late workflow response from the previous workspace", async () => {
    type WorkflowListResponse = Awaited<ReturnType<typeof getWorkflowList>>;
    let resolveOldWorkspace: ((response: WorkflowListResponse) => void) | undefined;
    const oldWorkspaceResponse = new Promise<WorkflowListResponse>((resolve) => {
      resolveOldWorkspace = resolve;
    });
    vi.mocked(getWorkflowList)
      .mockReturnValueOnce(oldWorkspaceResponse)
      .mockResolvedValueOnce({
        success: true,
        items: [sampleWorkflow({ id: "wf_new", name: "New Workspace Workflow" })],
        meta: { total: 1, page: 1, limit: 20 }
      });
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "ws_1",
        name: "Workspace One",
        isDefault: false,
        role: "owner",
        capabilities: []
      }
    });

    renderPage();
    await waitFor(() => expect(getWorkflowList).toHaveBeenCalledTimes(1));

    act(() => {
      useWorkspaceStore.setState({
        currentWorkspace: {
          id: "ws_2",
          name: "Workspace Two",
          isDefault: false,
          role: "owner",
          capabilities: []
        }
      });
    });

    expect(await screen.findByText("New Workspace Workflow")).toBeInTheDocument();
    await act(async () => {
      resolveOldWorkspace?.({
        success: true,
        items: [sampleWorkflow({ id: "wf_old", name: "Old Workspace Workflow" })],
        meta: { total: 1, page: 1, limit: 20 }
      });
      await oldWorkspaceResponse;
    });

    expect(screen.queryByText("Old Workspace Workflow")).not.toBeInTheDocument();
    expect(screen.getByText("New Workspace Workflow")).toBeInTheDocument();
  });


  it("shows a newer-version badge for the currently opened workflow when list metadata advances", async () => {
    vi.mocked(getWorkflowList).mockResolvedValue({
      success: true,
      items: [sampleWorkflow({ published_version: 2, latest_version: 3 })],
      meta: {
        total: 1,
        page: 1,
        limit: 20
      }
    });
    useWorkflowPersistenceStore.setState({
      workflowId: "wf_1",
      baseVersion: 2
    });

    renderPage();

    expect(await screen.findByTestId("workflow-studio-newer-version-wf_1")).toBeInTheDocument();
    expect(screen.getByTestId("workflow-studio-newer-version-wf_1")).toHaveTextContent("New saved version available");
  });

  it("shows onboarding empty state and routes back to editor", async () => {
    vi.mocked(getWorkflowList).mockResolvedValue({
      success: true,
      items: [],
      meta: {
        total: 0,
        page: 1,
        limit: 20
      }
    });

    renderPage();

    expect(await screen.findByTestId("workflow-studio-empty")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Go to Workflow Editor" }));

    expect(navigateMock).toHaveBeenCalledWith("/");
  });

  it("confirms before starting a blank workflow from the toolbar CTA when the editor is dirty", async () => {
    const uploadedFile = new File(["legacy"], "legacy.pdf", { type: "application/pdf" });
    vi.mocked(getWorkflowList).mockResolvedValue({
      success: true,
      items: [sampleWorkflow()],
      meta: {
        total: 1,
        page: 1,
        limit: 20
      }
    });
    seedEditorState(uploadedFile);
    useUIStore.setState({
      rightPanelTab: "history",
      selectedNodeId: "input_1",
      recentRunsDrawerOpen: true
    });

    renderPage();

    expect(await screen.findByText("Invoice OCR")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("workflow-studio-create-button"));

    expect(modalConfirmMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).not.toHaveBeenCalled();
    expect(useWorkflowStore.getState().nodes).toHaveLength(1);
    expect(useWorkflowStore.getState().uploadedFiles).toEqual({
      input_1: uploadedFile
    });
    expect(useWorkflowPersistenceStore.getState()).toMatchObject({
      workflowId: "wf_existing",
      isDirty: true
    });
    expect(useTaskExecutionStore.getState()).toMatchObject({
      currentTaskId: "task_legacy",
      taskStatus: "completed"
    });
    expect(useResultStore.getState()).toMatchObject({
      taskId: "task_legacy",
      displayMode: "raw"
    });
    expect(useUIStore.getState()).toMatchObject({
      rightPanelTab: "history",
      selectedNodeId: "input_1",
      recentRunsDrawerOpen: true
    });

    const config = modalConfirmMock.mock.calls[0]?.[0] as { onOk?: () => Promise<void> | void };
    await act(async () => {
      await config.onOk?.();
    });

    expect(navigateMock).toHaveBeenCalledWith("/");
    expect(useWorkflowStore.getState().nodes).toEqual([]);
    expect(useWorkflowStore.getState().uploadedFiles).toEqual({});
    expect(useWorkflowPersistenceStore.getState()).toMatchObject({
      workflowId: null,
      isDirty: false,
      latestVersion: 0,
      publishedVersion: null,
      versions: [],
      lastSavedAt: null
    });
    expect(useTaskExecutionStore.getState()).toMatchObject({
      currentTaskId: null,
      taskStatus: "idle",
      wsConnected: false,
      nodeStatuses: {},
      nodeProgress: {},
      nodeErrors: {},
      eventLogs: [],
      progress: null,
      wsWarning: null,
      manualReconnectAvailable: false,
      executionStartedAt: null
    });
    expect(useResultStore.getState()).toMatchObject({
      taskId: null,
      results: [],
      displayMode: "rendered"
    });
    expect(useUIStore.getState()).toMatchObject({
      rightPanelTab: "config",
      selectedNodeId: null,
      recentRunsDrawerOpen: false
    });
  });

  it("confirms before starting a blank workflow from the empty-state CTA when the editor is dirty", async () => {
    const uploadedFile = new File(["legacy"], "legacy.pdf", { type: "application/pdf" });
    vi.mocked(getWorkflowList).mockResolvedValue({
      success: true,
      items: [],
      meta: {
        total: 0,
        page: 1,
        limit: 20
      }
    });
    seedEditorState(uploadedFile);
    useWorkflowPersistenceStore.setState({
      latestVersion: 2,
      publishedVersion: 1,
      versions: [
        {
          version: 1,
          status: "published",
          created_at: "2026-03-18T00:00:00Z"
        }
      ],
      lastSavedAt: "2026-03-18T00:02:00Z"
    });
    useUIStore.setState({
      rightPanelTab: "compare",
      selectedNodeId: "input_1"
    });

    renderPage();

    expect(await screen.findByTestId("workflow-studio-empty")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Go to Workflow Editor" }));

    expect(modalConfirmMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).not.toHaveBeenCalled();
    expect(useWorkflowStore.getState().nodes).toHaveLength(1);
    expect(useWorkflowStore.getState().uploadedFiles).toEqual({
      input_1: uploadedFile
    });
    expect(useWorkflowPersistenceStore.getState()).toMatchObject({
      workflowId: "wf_existing",
      isDirty: true
    });
    expect(useTaskExecutionStore.getState()).toMatchObject({
      currentTaskId: "task_legacy",
      taskStatus: "completed"
    });
    expect(useResultStore.getState()).toMatchObject({
      taskId: "task_legacy",
      displayMode: "raw"
    });
    expect(useUIStore.getState()).toMatchObject({
      rightPanelTab: "compare",
      selectedNodeId: "input_1"
    });

    const config = modalConfirmMock.mock.calls[0]?.[0] as { onOk?: () => void };
    await act(async () => {
      config.onOk?.();
    });

    expect(navigateMock).toHaveBeenCalledWith("/");
    expect(useWorkflowStore.getState().nodes).toEqual([]);
    expect(useWorkflowStore.getState().uploadedFiles).toEqual({});
    expect(useWorkflowPersistenceStore.getState()).toMatchObject({
      workflowId: null,
      isDirty: false,
      latestVersion: 0,
      publishedVersion: null,
      versions: [],
      lastSavedAt: null
    });
    expect(useTaskExecutionStore.getState()).toMatchObject({
      currentTaskId: null,
      taskStatus: "idle",
      eventLogs: [],
      progress: null
    });
    expect(useResultStore.getState()).toMatchObject({
      taskId: null,
      results: [],
      displayMode: "rendered"
    });
    expect(useUIStore.getState()).toMatchObject({
      rightPanelTab: "config",
      selectedNodeId: null
    });
  });

  it("uses debounced backend search and supports clearing a no-result state", async () => {
    vi.mocked(getWorkflowList)
      .mockResolvedValueOnce({
        success: true,
        items: [sampleWorkflow()],
        meta: {
          total: 1,
          page: 1,
          limit: 20
        }
      })
      .mockResolvedValueOnce({
        success: true,
        items: [],
        meta: {
          total: 0,
          page: 1,
          limit: 20
        }
      })
      .mockResolvedValueOnce({
        success: true,
        items: [sampleWorkflow()],
        meta: {
          total: 1,
          page: 1,
          limit: 20
        }
      });

    renderPage();
    expect(await screen.findByText("Invoice OCR")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Search workflow names or descriptions"), {
      target: { value: "missing" }
    });

    expect(vi.mocked(getWorkflowList)).toHaveBeenCalledTimes(1);

    await waitFor(() => {
      expect(vi.mocked(getWorkflowList)).toHaveBeenNthCalledWith(2, {
        page: 1,
        limit: 20,
        sort: "updated_at:desc",
        q: "missing"
      });
    });

    expect(await screen.findByTestId("workflow-studio-empty-search")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("workflow-studio-clear-search"));

    await waitFor(() => {
      expect(vi.mocked(getWorkflowList)).toHaveBeenNthCalledWith(3, {
        page: 1,
        limit: 20,
        sort: "updated_at:desc",
        q: undefined
      });
    });
    expect(await screen.findByText("Invoice OCR")).toBeInTheDocument();
  });

  it("supports pagination via load more", async () => {
    vi.mocked(getWorkflowList)
      .mockResolvedValueOnce({
        success: true,
        items: [sampleWorkflow()],
        meta: {
          total: 2,
          page: 1,
          limit: 1
        }
      })
      .mockResolvedValueOnce({
        success: true,
        items: [
          sampleWorkflow({
            id: "wf_2",
            name: "Receipt Compare",
            description: "Store receipt fallback",
            created_at: "2026-03-18T00:02:00Z",
            updated_at: "2026-03-18T00:03:00Z",
            published_version: null,
            latest_version: 0
          })
        ],
        meta: {
          total: 2,
          page: 2,
          limit: 1
        }
      });

    renderPage();

    expect(await screen.findByText("Invoice OCR")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("workflow-studio-load-more"));

    await waitFor(() => {
      expect(vi.mocked(getWorkflowList)).toHaveBeenNthCalledWith(2, {
        page: 2,
        limit: 20,
        sort: "updated_at:desc",
        q: undefined
      });
    });

    expect(await screen.findByText("Receipt Compare")).toBeInTheDocument();
  });

  it("shows retry UI after a failed load", async () => {
    vi.mocked(getWorkflowList)
      .mockRejectedValueOnce(new Error("network error"))
      .mockResolvedValueOnce({
        success: true,
        items: [sampleWorkflow()],
        meta: {
          total: 1,
          page: 1,
          limit: 20
        }
      });

    renderPage();

    expect(await screen.findByTestId("workflow-studio-error")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("workflow-studio-retry"));

    expect(await screen.findByText("Invoice OCR")).toBeInTheDocument();
  });

  it("opens workflow directly when there are no unsaved changes", async () => {
    vi.mocked(getWorkflowList).mockResolvedValue({
      success: true,
      items: [sampleWorkflow()],
      meta: {
        total: 1,
        page: 1,
        limit: 20
      }
    });

    renderPage();

    expect(await screen.findByText("Invoice OCR")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("workflow-studio-open-wf_1"));

    expect(modalConfirmMock).not.toHaveBeenCalled();
    expect(navigateMock).toHaveBeenCalledWith("/workflows/wf_1");
  });

  it("renames workflow metadata from the studio list and refreshes the current query", async () => {
    vi.mocked(getWorkflowList)
      .mockResolvedValueOnce({
        success: true,
        items: [sampleWorkflow()],
        meta: {
          total: 1,
          page: 1,
          limit: 20
        }
      })
      .mockResolvedValueOnce({
        success: true,
        items: [
          sampleWorkflow({
            name: "Invoice OCR v2",
            description: "updated by review"
          })
        ],
        meta: {
          total: 1,
          page: 1,
          limit: 20
        }
      });
    vi.mocked(updateWorkflowMetadata).mockResolvedValue({
      success: true,
      data: {
        id: "wf_1",
        name: "Invoice OCR v2",
        description: "updated by review",
        created_at: "2026-03-18T00:00:00Z",
        updated_at: "2026-03-18T00:05:00Z",
        published_version: 1,
        latest_version: 1
      }
    });

    renderPage();

    expect(await screen.findByText("Invoice OCR")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("workflow-studio-rename-wf_1"));
    fireEvent.change(await screen.findByTestId("workflow-studio-rename-name"), {
      target: { value: "Invoice OCR v2" }
    });
    fireEvent.change(screen.getByTestId("workflow-studio-rename-description"), {
      target: { value: "updated by review" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(updateWorkflowMetadata).toHaveBeenCalledWith("wf_1", {
        name: "Invoice OCR v2",
        description: "updated by review"
      });
    });
    expect(messageSuccessMock).toHaveBeenCalledWith("Workflow name updated.");
    expect(await screen.findByText("Invoice OCR v2")).toBeInTheDocument();
  });

  it("prompts before opening a workflow when the editor is dirty", async () => {
    useWorkflowPersistenceStore.setState({
      workflowId: "wf_current",
      isDirty: true,
      latestVersion: 3,
      publishedVersion: 2,
      versions: [],
      lastSavedAt: "2026-03-18T00:05:00Z"
    });
    vi.mocked(getWorkflowList).mockResolvedValue({
      success: true,
      items: [sampleWorkflow()],
      meta: {
        total: 1,
        page: 1,
        limit: 20
      }
    });

    renderPage();

    expect(await screen.findByText("Invoice OCR")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("workflow-studio-open-wf_1"));

    expect(modalConfirmMock).toHaveBeenCalledTimes(1);
    const config = modalConfirmMock.mock.calls[0]?.[0] as { onOk?: () => Promise<void> | void };
    await act(async () => {
      await config.onOk?.();
    });

    expect(navigateMock).toHaveBeenCalledWith("/workflows/wf_1");
  });

  it("confirms delete, refreshes the list, and clears stale loaded workflow references", async () => {
    useWorkflowStore.setState({
      nodes: [
        {
          id: "engine_ocr_1",
          type: "engine/ocr",
          position: { x: 120, y: 140 },
          data: {
            label: "OCR",
            config: {},
            configSchema: {
              type: "object",
              properties: {}
            }
          }
        }
      ],
      edges: [],
      nodeConfigs: {},
      uploadedFiles: {},
      selectedNodeId: null,
      nodeRegistry: { nodes: [], connection_rules: [] }
    });
    useWorkflowPersistenceStore.setState({
      workflowId: "wf_1",
      isDirty: false,
      latestVersion: 1,
      publishedVersion: 1,
      versions: [],
      lastSavedAt: "2026-03-18T00:01:00Z"
    });
    vi.mocked(getWorkflowList)
      .mockResolvedValueOnce({
        success: true,
        items: [sampleWorkflow()],
        meta: {
          total: 1,
          page: 1,
          limit: 20
        }
      })
      .mockResolvedValueOnce({
        success: true,
        items: [],
        meta: {
          total: 0,
          page: 1,
          limit: 20
        }
      });
    vi.mocked(deleteWorkflow).mockResolvedValue({
      success: true
    });

    renderPage();

    expect(await screen.findByText("Invoice OCR")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("workflow-studio-delete-wf_1"));

    const config = modalConfirmMock.mock.calls[0]?.[0] as { onOk?: () => Promise<void> };
    await act(async () => {
      await config.onOk?.();
    });

    expect(deleteWorkflow).toHaveBeenCalledWith("wf_1");
    expect(messageSuccessMock).toHaveBeenCalledWith("Workflow deleted.");
    expect(vi.mocked(getWorkflowList)).toHaveBeenNthCalledWith(2, {
      page: 1,
      limit: 20,
      sort: "updated_at:desc",
      q: undefined
    });
    expect(useWorkflowPersistenceStore.getState().workflowId).toBeNull();
    expect(useWorkflowStore.getState().nodes).toHaveLength(0);
  });

  it("shows not-found feedback and refreshes after delete stale-data errors", async () => {
    vi.mocked(getWorkflowList)
      .mockResolvedValueOnce({
        success: true,
        items: [sampleWorkflow()],
        meta: {
          total: 1,
          page: 1,
          limit: 20
        }
      })
      .mockResolvedValueOnce({
        success: true,
        items: [],
        meta: {
          total: 0,
          page: 1,
          limit: 20
        }
      });
    vi.mocked(deleteWorkflow).mockRejectedValue({
      response: {
        data: {
          error_code: "WORKFLOW_NOT_FOUND",
          message: "找不到 Workflow"
        }
      }
    });

    renderPage();

    expect(await screen.findByText("Invoice OCR")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("workflow-studio-delete-wf_1"));

    const config = modalConfirmMock.mock.calls[0]?.[0] as { onOk?: () => Promise<void> };
    await act(async () => {
      await config.onOk?.();
    });

    expect(messageErrorMock).toHaveBeenCalledWith("The workflow no longer exists. The list has been refreshed.");
    expect(vi.mocked(getWorkflowList)).toHaveBeenNthCalledWith(2, {
      page: 1,
      limit: 20,
      sort: "updated_at:desc",
      q: undefined
    });
  });
});
