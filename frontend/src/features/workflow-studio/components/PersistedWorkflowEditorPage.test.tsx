import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PersistedWorkflowEditorPage from "@/features/workflow-studio/components/PersistedWorkflowEditorPage";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { getNodeRegistry } from "@/services/nodeRegistryApi";
import { getWorkflowDetail, getWorkflowVersions } from "@/services/workflowApi";
import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";

vi.mock("@/services/nodeRegistryApi", () => ({
  getNodeRegistry: vi.fn()
}));

vi.mock("@/services/workflowApi", async () => {
  const actual = await vi.importActual<typeof import("@/services/workflowApi")>("@/services/workflowApi");
  return {
    ...actual,
    getWorkflowDetail: vi.fn(),
    getWorkflowVersions: vi.fn()
  };
});

describe("PersistedWorkflowEditorPage", () => {
  beforeEach(() => {
    vi.mocked(getNodeRegistry).mockResolvedValue({
      version: "1.0.0",
      categories: [
        {
          category_id: "engine",
          display_name: "Engine"
        }
      ],
      nodes: [
        {
          node_type: "engine/ocr",
          display_name: "OCR Engine",
          description: "OCR node",
          category: "engine",
          input_types: [],
          output_types: [],
          config_schema: {
            type: "object",
            properties: {}
          }
        }
      ],
      connection_rules: []
    });
    vi.mocked(getWorkflowDetail).mockResolvedValue({
      id: "wf_123",
      name: "Persisted OCR",
      description: "Saved workflow",
      definition: {
        nodes: [
          {
            id: "node_1",
            type: "engine/ocr",
            config: {}
          }
        ],
        connections: []
      },
      created_at: "2026-03-18T00:00:00Z",
      updated_at: "2026-03-18T00:00:00Z",
      published_version: 1,
      latest_version: 1
    });
    vi.mocked(getWorkflowVersions).mockResolvedValue({
      success: true,
      data: [
        {
          version: 1,
          status: "published",
          created_at: "2026-03-18T00:00:00Z"
        }
      ]
    });
    useWorkflowStore.setState({
      nodes: [],
      edges: [],
      nodeConfigs: {},
      uploadedFiles: {},
      selectedNodeId: null,
      nodeRegistry: { nodes: [], connection_rules: [] }
    });
    useWorkflowPersistenceStore.getState().reset();
  });

  it("loads the persisted workflow from the route id before rendering the editor", async () => {
    render(
      <MemoryRouter initialEntries={["/workflows/wf_123"]}>
        <Routes>
          <Route element={<PersistedWorkflowEditorPage />} path="/workflows/:workflowId" />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByTestId("persisted-workflow-editor-loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(getWorkflowDetail).toHaveBeenCalledWith("wf_123");
    });

    expect(await screen.findByTestId("workflow-canvas-panel")).toBeInTheDocument();
    expect(useWorkflowPersistenceStore.getState().workflowId).toBe("wf_123");
    expect(useWorkflowStore.getState().selectedNodeId).toBe("node_1");
    expect((await screen.findAllByRole("button", { name: "Delete node" })).length).toBeGreaterThan(0);
    expect(screen.queryByText("Select a node to configure it")).not.toBeInTheDocument();

    await waitFor(
      () => {
        expect(getWorkflowDetail).toHaveBeenCalledTimes(1);
        expect(getWorkflowVersions).toHaveBeenCalledTimes(1);
        expect(screen.getAllByRole("button", { name: "Delete node" }).length).toBeGreaterThan(0);
        expect(screen.queryByTestId("persisted-workflow-editor-loading")).not.toBeInTheDocument();
      },
      { timeout: 3000 }
    );
  });

  it("clears stale uploaded files when hydrating a persisted workflow", async () => {
    const staleFile = new File(["legacy"], "legacy.pdf", { type: "application/pdf" });
    vi.mocked(getNodeRegistry).mockResolvedValue({
      version: "1.0.0",
      categories: [
        {
          category_id: "input",
          display_name: "Input"
        }
      ],
      nodes: [
        {
          node_type: "input/pdf",
          display_name: "PDF Input",
          description: "Input node",
          category: "input",
          input_types: [],
          output_types: ["application/pdf"],
          config_schema: {
            type: "object",
            properties: {}
          }
        }
      ],
      connection_rules: []
    });
    vi.mocked(getWorkflowDetail).mockResolvedValue({
      id: "wf_456",
      name: "Persisted Input Workflow",
      description: "Saved workflow",
      definition: {
        nodes: [
          {
            id: "input_1",
            type: "input/pdf",
            config: {}
          }
        ],
        connections: []
      },
      created_at: "2026-03-18T00:00:00Z",
      updated_at: "2026-03-18T00:00:00Z",
      published_version: 1,
      latest_version: 1
    });
    useWorkflowStore.setState({
      nodes: [],
      edges: [],
      nodeConfigs: {
        input_1: { file: "legacy.pdf" }
      },
      uploadedFiles: {
        input_1: staleFile
      },
      selectedNodeId: null,
      nodeRegistry: { nodes: [], connection_rules: [] }
    });

    render(
      <MemoryRouter initialEntries={["/workflows/wf_456"]}>
        <Routes>
          <Route element={<PersistedWorkflowEditorPage />} path="/workflows/:workflowId" />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByTestId("workflow-canvas-panel")).toBeInTheDocument();
    expect(useWorkflowStore.getState().uploadedFiles).toEqual({});
    expect(useWorkflowStore.getState().selectedNodeId).toBe("input_1");
    expect(useWorkflowPersistenceStore.getState().workflowId).toBe("wf_456");
  });
});
