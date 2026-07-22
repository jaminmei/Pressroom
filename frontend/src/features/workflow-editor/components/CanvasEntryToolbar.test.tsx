import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CanvasEntryToolbar from "@/features/workflow-editor/components/CanvasEntryToolbar";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { getNodeRegistry } from "@/services/nodeRegistryApi";
import { initialUIState, useUIStore } from "@/stores/uiStore";
import type { NodeRegistryResponse } from "@/types/node-registry";

vi.mock("@/services/nodeRegistryApi", () => ({
  getNodeRegistry: vi.fn()
}));

const mockedGetNodeRegistry = vi.mocked(getNodeRegistry);

const registryPayload: NodeRegistryResponse = {
  version: "1.0.0",
  categories: [
    { category_id: "input", display_name: "輸入源", description: "" },
    { category_id: "engine", display_name: "轉換引擎", description: "" },
    { category_id: "end", display_name: "工作流終點", description: "" }
  ],
  nodes: [
    {
      node_type: "input/pdf",
      display_name: "PDF 輸入",
      category: "input",
      description: "上傳 PDF 文件作為輸入",
      config_schema: { type: "object", properties: {} },
      output_types: ["application/pdf"]
    },
    {
      node_type: "engine/ocr",
      display_name: "OCR Engine",
      category: "engine",
      description: "執行文字 OCR 轉換",
      config_schema: { type: "object", properties: {} },
      input_types: ["application/pdf"],
      output_types: ["text/raw"]
    },
    {
      node_type: "end/final",
      display_name: "Workflow End",
      category: "end",
      description: "系統管理的終點節點",
      config_schema: { type: "object", properties: {} },
      input_types: ["text/raw"],
      output_types: []
    }
  ],
  connection_rules: []
};

describe("CanvasEntryToolbar", () => {
  beforeEach(() => {
    useUIStore.setState(initialUIState);
    useWorkflowStore.setState({
      nodes: [],
      edges: [],
      nodeConfigs: {},
      uploadedFiles: {},
      nodeRegistry: { nodes: [], connection_rules: [] },
      selectedNodeId: null
    });
  });

  it("loads node registry into workflow store", async () => {
    mockedGetNodeRegistry.mockResolvedValue(registryPayload);

    render(<CanvasEntryToolbar />);

    await waitFor(() => {
      expect(useWorkflowStore.getState().nodeRegistry.nodes).toEqual(registryPayload.nodes);
    });
  });

  it("opens the floating panel and adds a node", async () => {
    mockedGetNodeRegistry.mockResolvedValue(registryPayload);

    render(<CanvasEntryToolbar />);

    fireEvent.click(screen.getByRole("button", { name: "Open add node" }));
    expect(await screen.findByText("上傳 PDF 文件作為輸入")).toBeInTheDocument();
    expect(screen.getByText("執行文字 OCR 轉換")).toBeInTheDocument();
    const nodeButton = await screen.findByTestId("canvas-entry-node-input_pdf");
    fireEvent.click(nodeButton);

    await waitFor(() => {
      expect(useWorkflowStore.getState().nodes).toHaveLength(1);
    });

    expect(useWorkflowStore.getState().nodes[0]?.type).toBe("input/pdf");
    expect(useWorkflowStore.getState().selectedNodeId).toBe("input_pdf_1");
    expect(useUIStore.getState().selectedNodeId).toBe("input_pdf_1");
    expect(screen.queryByTestId("canvas-entry-toolbar-panel")).not.toBeInTheDocument();
  });

  it("exposes the user-managed end node in the toolbar", async () => {
    mockedGetNodeRegistry.mockResolvedValue(registryPayload);

    render(<CanvasEntryToolbar />);

    fireEvent.click(screen.getByRole("button", { name: "Open add node" }));

    expect(await screen.findByText("上傳 PDF 文件作為輸入")).toBeInTheDocument();
    expect(screen.getByTestId("canvas-entry-node-end_final")).toBeInTheDocument();
    expect(screen.getByText("系統管理的終點節點")).toBeInTheDocument();
  });
});
