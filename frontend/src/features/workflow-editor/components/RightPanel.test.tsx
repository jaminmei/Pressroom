import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RightPanel from "@/features/workflow-editor/components/RightPanel";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { initialUIState, useUIStore } from "@/stores/uiStore";

vi.mock("@/features/workflow-editor/hooks/useWorkflowPersistence", () => ({
  useWorkflowPersistence: () => ({
    restoreVersion: vi.fn()
  })
}));

vi.mock("@/features/workflow-editor/components/ConfigPanel", () => ({
  default: () => <div>Config Panel Body</div>
}));

vi.mock("@/features/workflow-editor/components/RunPanel", () => ({
  default: () => <div>Run Panel Body</div>
}));

vi.mock("@/features/workflow-editor/components/ComparePanel", () => ({
  default: () => <div>Compare Panel Body</div>
}));

vi.mock("@/features/workflow-editor/components/HistoryPanel", () => ({
  default: () => <div>History Panel Body</div>
}));

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn()
  }))
});

describe("RightPanel", () => {
  beforeEach(() => {
    useUIStore.setState(initialUIState);
    useWorkflowStore.setState({
      nodes: [
        {
          id: "input_1",
          type: "input/pdf",
          data: {
            label: "Input",
            config: {},
            configSchema: { type: "object", properties: {} }
          }
        },
        {
          id: "end_1",
          type: "end/final",
          data: {
            label: "End",
            config: {},
            configSchema: { type: "object", properties: {} }
          }
        }
      ],
      edges: [],
      nodeConfigs: {},
      uploadedFiles: {},
      nodeRegistry: { nodes: [], connection_rules: [] },
      selectedNodeId: null
    });
  });

  it("switches to compare when the selected node is end/final", async () => {
    useWorkflowStore.setState({ selectedNodeId: "end_1" });

    render(<RightPanel />);

    await waitFor(() => {
      expect(useUIStore.getState().rightPanelTab).toBe("compare");
    });

    expect(screen.getByText("Result Compare")).toBeInTheDocument();
    expect(screen.getByText("Compare Panel Body")).toBeInTheDocument();
  });

  it("switches to config when a non-end node is selected", async () => {
    useUIStore.setState({ rightPanelTab: "compare" });
    useWorkflowStore.setState({ selectedNodeId: "input_1" });

    render(<RightPanel />);

    await waitFor(() => {
      expect(useUIStore.getState().rightPanelTab).toBe("config");
    });

    expect(screen.getByText("Node Configuration")).toBeInTheDocument();
    expect(screen.getByText("Config Panel Body")).toBeInTheDocument();
  });
});
