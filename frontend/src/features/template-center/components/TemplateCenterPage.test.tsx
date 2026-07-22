import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TemplateCenterPage from "@/features/template-center/components/TemplateCenterPage";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { initialUIState, useUIStore } from "@/stores/uiStore";

const navigateMock = vi.fn();
const applyTemplateMock = vi.fn();
const messageSuccessMock = vi.fn();
const messageErrorMock = vi.fn();

vi.mock("antd", async () => {
  const actual = await vi.importActual<typeof import("antd")>("antd");
  return {
    ...actual,
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

vi.mock("@/features/workflow-editor/templates/applyTemplate", () => ({
  applyTemplateToWorkflowStore: (...args: unknown[]) => applyTemplateMock(...args)
}));

describe("TemplateCenterPage", () => {
  beforeEach(() => {
    navigateMock.mockReset();
    applyTemplateMock.mockReset();
    messageSuccessMock.mockReset();
    messageErrorMock.mockReset();
    window.localStorage.clear();
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

  it("renders launchpad shell copy and 3 golden-path template cards with topology previews", () => {
    render(
      <MemoryRouter>
        <TemplateCenterPage />
      </MemoryRouter>
    );

    expect(screen.getByText("Curated workflow starters")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Start from polished document-conversion flows, then tune the canvas in the editor instead of rebuilding every path from scratch."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("Launchpad")).toBeInTheDocument();
    expect(screen.getByText("Pick a proven baseline, then tune it in the editor.")).toBeInTheDocument();
    expect(screen.getByText("Production-ready workflow starters")).toBeInTheDocument();
    expect(screen.getByText("Starters")).toBeInTheDocument();
    expect(screen.getByText("Input types")).toBeInTheDocument();
    expect(screen.getByText("Compare-ready")).toBeInTheDocument();
    expect(screen.getByText("Last launch")).toBeInTheDocument();
    expect(screen.getAllByTestId("template-card").length).toBe(3);
    expect(screen.getByText("Quick Convert")).toBeInTheDocument();
    expect(screen.getByText("Custom Workflow")).toBeInTheDocument();
    expect(screen.getByText("Multi-Engine Compare")).toBeInTheDocument();
    expect(screen.getByTestId("template-topology-quick-convert")).toBeInTheDocument();
    expect(screen.getByTestId("template-topology-custom-workflow")).toBeInTheDocument();
    expect(screen.getByTestId("template-topology-multi-engine-compare")).toBeInTheDocument();
  });

  it("applies template and navigates to editor", () => {
    render(
      <MemoryRouter>
        <TemplateCenterPage />
      </MemoryRouter>
    );

    const firstCard = screen.getByTestId("template-card-tpl-ocr-basic");
    fireEvent.click(screen.getAllByRole("button", { name: "Apply now" })[0]!);

    expect(applyTemplateMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith("/");
    expect(firstCard).toBeInTheDocument();
    expect(within(screen.getByText("Recently used").closest("section")!).getByText("Quick Convert")).toBeInTheDocument();
  });

  it("limits recently used list to at most 5 records", () => {
    window.localStorage.setItem(
      "template_recent_used",
      JSON.stringify([
        { templateId: "tpl-ocr-basic", usedAt: "2026-03-03T10:00:00Z" },
        { templateId: "tpl-vlm-basic", usedAt: "2026-03-03T09:00:00Z" },
        { templateId: "tpl-compare-ocr-vlm", usedAt: "2026-03-03T08:00:00Z" },
        { templateId: "tpl-ocr-basic", usedAt: "2026-03-03T07:00:00Z" },
        { templateId: "tpl-vlm-basic", usedAt: "2026-03-03T06:00:00Z" },
        { templateId: "tpl-compare-ocr-vlm", usedAt: "2026-03-03T05:00:00Z" }
      ])
    );

    render(
      <MemoryRouter>
        <TemplateCenterPage />
      </MemoryRouter>
    );

    const recentSection = screen.getByText("Recently used").closest("section");
    expect(recentSection?.querySelectorAll(".template-center-recent-item").length ?? 0).toBeLessThanOrEqual(5);
  });

  it("imports valid workflow json and navigates to editor", async () => {
    render(
      <MemoryRouter>
        <TemplateCenterPage />
      </MemoryRouter>
    );

    const file = new File(
      [
        JSON.stringify({
          name: "imported",
          nodes: [{ id: "input_1", type: "input/pdf", position: { x: 120, y: 180 } }],
          connections: []
        })
      ],
      "workflow.json",
      { type: "application/json" }
    );
    fireEvent.change(screen.getByTestId("import-json-input"), {
      target: { files: [file] }
    });

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith("/");
    });
  });

  it("repairs legacy imported workflows and selects the preferred editable node", async () => {
    render(
      <MemoryRouter>
        <TemplateCenterPage />
      </MemoryRouter>
    );

    const file = new File(
      [
        JSON.stringify({
          name: "legacy-import",
          nodes: [
            { id: "input_1", type: "input/pdf", position: { x: 120, y: 180 } },
            { id: "engine_1", type: "engine/ocr", position: { x: 320, y: 180 } },
            { id: "output_1", type: "output/text", position: { x: 520, y: 180 } }
          ],
          connections: [
            { source: "input_1", target: "engine_1" },
            { source: "engine_1", target: "output_1" }
          ]
        })
      ],
      "legacy-workflow.json",
      { type: "application/json" }
    );

    fireEvent.change(screen.getByTestId("import-json-input"), {
      target: { files: [file] }
    });

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith("/");
      expect(useWorkflowStore.getState().nodes.some((node) => node.type === "output/text")).toBe(false);
    });

    const state = useWorkflowStore.getState();
    expect(state.nodes.find((node) => node.id === "output_1")).toBeUndefined();
    expect(state.nodes.filter((node) => node.type === "end/final")).toHaveLength(0);
    expect(state.edges).toEqual([expect.objectContaining({ source: "input_1", target: "engine_1" })]);
    expect(state.selectedNodeId).toBe("input_1");
  });

  it("shows validation error when importing invalid json", async () => {
    render(
      <MemoryRouter>
        <TemplateCenterPage />
      </MemoryRouter>
    );

    const file = new File(["{broken"], "broken.json", { type: "application/json" });
    fireEvent.change(screen.getByTestId("import-json-input"), {
      target: { files: [file] }
    });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Invalid JSON: unable to parse file contents");
    });
  });

  it("shows schema error when importing json without workflow definition", async () => {
    render(
      <MemoryRouter>
        <TemplateCenterPage />
      </MemoryRouter>
    );

    const file = new File([JSON.stringify({ foo: "bar" })], "invalid-schema.json", { type: "application/json" });
    fireEvent.change(screen.getByTestId("import-json-input"), {
      target: { files: [file] }
    });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Invalid JSON: nodes and connections arrays are required");
    });
  });
});
