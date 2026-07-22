import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useResultStore } from "@/features/result/store";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import type { TaskResult } from "@/types/task";
import ComparePanel from "@/features/workflow-editor/components/ComparePanel";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { setActiveWorkspaceId } from "@/services/api";

interface RafController {
  flushAllFrames: () => void;
}

interface ScrollMetrics {
  clientHeight: number;
  scrollHeight: number;
  scrollTop?: number;
}

function makeResult(
  resultId: string,
  filename: string,
  content: string,
  overrides: Partial<TaskResult> = {}
): TaskResult {
  const metadata = {
    processing_time_ms: 100,
    page_count: 1,
    char_count: content.length,
    word_count: content.split(/\s+/).filter(Boolean).length
  };

  return {
    result_id: resultId,
    node_id: `node_${resultId}`,
    node_type: "output/markdown",
    status: "completed",
    file: {
      filename,
      size_bytes: content.length,
      content_type: "text/markdown",
      download_url: `/api/tasks/task_1/results/${resultId}/download`
    },
    metadata: {
      ...metadata,
      ...overrides.metadata
    },
    content,
    ...overrides
  };
}

function seedCompareResults() {
  useResultStore.getState().setTaskResults("task_1", [
    makeResult("result_1", "ocr.md", "same line\nbefore\nstable", {
      execution_time_ms: 2500,
      char_count: 15000,
      formats: {
        markdown: "/api/tasks/task_1/results/result_1/download?format=markdown",
        text: "/api/tasks/task_1/results/result_1/download?format=text",
        yaml: "/api/tasks/task_1/results/result_1/download?format=yaml"
      }
    }),
    makeResult("result_2", "vlm.md", "same line\nafter\nstable\nextra", {
      execution_time_ms: 1200,
      char_count: 12000
    })
  ]);
}

function seedIdenticalCompareResults() {
  const sameContent = "same line\nstable line\nending line";
  useResultStore.getState().setTaskResults("task_1", [
    makeResult("result_same_1", "ocr.md", sameContent),
    makeResult("result_same_2", "vlm.md", sameContent)
  ]);
}

function buildLongContent(lineCount: number): string {
  return Array.from({ length: lineCount }, (_, index) => `line-${index} ${"x".repeat(20)}`).join("\n");
}

function seedLongCompareResults() {
  const longContent = buildLongContent(900);
  useResultStore.getState().setTaskResults("task_1", [
    makeResult("result_long_1", "ocr.md", longContent),
    makeResult("result_long_2", "vlm.md", longContent)
  ]);
}

function seedThreePaneCompareResults() {
  useResultStore.getState().setTaskResults("task_1", [
    makeResult("result_1", "ocr.md", "header\nbefore\nstable"),
    makeResult("result_2", "vlm.md", "header\nafter\nstable"),
    makeResult("result_3", "markitdown.md", "third pane\nindependent\ncontent")
  ]);
}

function mockRequestAnimationFrame(): RafController {
  const frameQueue: Array<{ id: number; callback: FrameRequestCallback }> = [];
  let nextFrameId = 1;

  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback: FrameRequestCallback) => {
    const frameId = nextFrameId;
    nextFrameId += 1;
    frameQueue.push({ id: frameId, callback });
    return frameId;
  });

  vi.spyOn(window, "cancelAnimationFrame").mockImplementation((frameId: number) => {
    const targetIndex = frameQueue.findIndex((entry) => entry.id === frameId);
    if (targetIndex >= 0) {
      frameQueue.splice(targetIndex, 1);
    }
  });

  const flushAllFrames = () => {
    while (frameQueue.length > 0) {
      const frame = frameQueue.shift();
      if (!frame) {
        return;
      }

      frame.callback(performance.now());
    }
  };

  return {
    flushAllFrames
  };
}

function setScrollMetrics(element: HTMLElement, { clientHeight, scrollHeight, scrollTop = 0 }: ScrollMetrics): void {
  let currentTop = scrollTop;

  Object.defineProperty(element, "clientHeight", {
    configurable: true,
    get: () => clientHeight
  });

  Object.defineProperty(element, "scrollHeight", {
    configurable: true,
    get: () => scrollHeight
  });

  Object.defineProperty(element, "scrollTop", {
    configurable: true,
    get: () => currentTop,
    set: (value: number) => {
      currentTop = value;
    }
  });
}

describe("ComparePanel", () => {
  beforeEach(() => {
    useResultStore.getState().reset();
    useTaskExecutionStore.getState().reset();
    // Set currentTaskId to match the task ID used in seedCompareResults
    useTaskExecutionStore.getState().setTaskId("task_1");
    useTaskExecutionStore.getState().setTaskStatus("completed");
    useWorkspaceStore.setState({ capabilities: ["run.view"] });
    setActiveWorkspaceId("workspace-1");
    useWorkflowStore.setState({
      nodes: [],
      edges: [],
      nodeConfigs: {},
      uploadedFiles: {},
      nodeRegistry: { nodes: [], connection_rules: [] },
      selectedNodeId: null
    });
    seedCompareResults();
  });

  it("does not expose results without run view permission", () => {
    useWorkspaceStore.setState({ capabilities: [] });

    render(<ComparePanel />);

    expect(screen.getByTestId("compare-panel-empty-state")).toBeInTheDocument();
    expect(screen.queryByText("ocr.md")).not.toBeInTheDocument();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows duration and char count statistics for each result", () => {
    render(<ComparePanel />);

    expect(screen.getByText("Result Compare")).toBeInTheDocument();
    expect(screen.getByText("2.5s | 15,000 chars")).toBeInTheDocument();
    expect(screen.getByText("1.2s | 12,000 chars")).toBeInTheDocument();
  });

  it("shows workflow final result empty state when end node is selected with no results", () => {
    useResultStore.getState().reset();
    useWorkflowStore.setState({
      nodes: [
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
      selectedNodeId: "end_1"
    });

    render(<ComparePanel />);

    expect(screen.getByTestId("compare-panel-end-node-empty-state")).toBeInTheDocument();
    expect(screen.getByText("The workflow final result will appear here")).toBeInTheDocument();
  });

  it("toggles diff mode on and off", () => {
    render(<ComparePanel />);

    const diffToggle = screen.getByRole("button", { name: "Diff" });
    expect(diffToggle).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(diffToggle);
    expect(diffToggle).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(diffToggle);
    expect(diffToggle).toHaveAttribute("aria-pressed", "false");
  });

  it("renders diff classes when diff mode is enabled", () => {
    const { container } = render(<ComparePanel />);

    fireEvent.click(screen.getByRole("button", { name: "Diff" }));

    expect(container.querySelectorAll(".compare-line-modified").length).toBeGreaterThan(0);
    expect(container.querySelectorAll(".compare-line-added").length).toBeGreaterThan(0);
  });

  it("does not render diff classes when diff mode is disabled", () => {
    const { container } = render(<ComparePanel />);
    const diffToggle = screen.getByRole("button", { name: "Diff" });

    fireEvent.click(diffToggle);
    expect(container.querySelectorAll(".compare-line-modified").length).toBeGreaterThan(0);

    fireEvent.click(diffToggle);
    expect(container.querySelectorAll(".compare-line-added")).toHaveLength(0);
    expect(container.querySelectorAll(".compare-line-removed")).toHaveLength(0);
    expect(container.querySelectorAll(".compare-line-modified")).toHaveLength(0);
  });

  it("shows identical-content hint when diff mode is enabled and no diffs exist", () => {
    seedIdenticalCompareResults();
    render(<ComparePanel />);

    fireEvent.click(screen.getByRole("button", { name: "Diff" }));

    expect(screen.getByText("Content is identical")).toBeInTheDocument();
  });

  it("downloads single result in selected format", () => {
    const appendSpy = vi.spyOn(document.body, "appendChild");
    const removeSpy = vi.spyOn(document.body, "removeChild");
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<ComparePanel />);

    fireEvent.click(screen.getAllByRole("button", { name: "TXT" })[0]);

    const appendedLinks = appendSpy.mock.calls
      .map((call) => call[0])
      .filter((node): node is HTMLAnchorElement => node instanceof HTMLAnchorElement);
    const appendedLink = appendedLinks[appendedLinks.length - 1];
    if (!appendedLink) throw new Error("Expected a download link");
    expect(appendedLink.href).toContain("/api/tasks/task_1/results/result_1/download?format=text");
    expect(appendedLink.download).toBe("ocr.txt");
    expect(clickSpy).toHaveBeenCalledTimes(1);

    appendSpy.mockRestore();
    removeSpy.mockRestore();
    clickSpy.mockRestore();
  });

  it("downloads all results using the active segmented format", () => {
    const appendSpy = vi.spyOn(document.body, "appendChild");
    const removeSpy = vi.spyOn(document.body, "removeChild");
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<ComparePanel />);

    fireEvent.click(screen.getByRole("radio", { name: "YAML" }));
    fireEvent.click(screen.getByRole("button", { name: "Download All" }));

    const appendedLinks = appendSpy.mock.calls
      .map((call) => call[0])
      .filter((node): node is HTMLAnchorElement => node instanceof HTMLAnchorElement);
    const lastTwoDownloads = appendedLinks.slice(-2);

    expect(lastTwoDownloads).toHaveLength(2);
    expect(lastTwoDownloads[0].href).toContain("result_1/download?format=yaml");
    expect(lastTwoDownloads[1].href).toContain("result_2/download?format=yaml");
    expect(clickSpy).toHaveBeenCalledTimes(2);

    appendSpy.mockRestore();
    removeSpy.mockRestore();
    clickSpy.mockRestore();
  });

  it("syncs first two compare panes when scroll sync is enabled", () => {
    const raf = mockRequestAnimationFrame();
    const { container } = render(<ComparePanel />);
    fireEvent.click(screen.getByRole("radio", { name: "Raw" }));
    const compareContents = container.querySelectorAll<HTMLElement>(".compare-panel-content");
    const leftPane = compareContents[0];
    const rightPane = compareContents[1];

    if (!leftPane || !rightPane) {
      throw new Error("Expected at least two compare panes");
    }

    setScrollMetrics(leftPane, { scrollHeight: 300, clientHeight: 100, scrollTop: 100 });
    setScrollMetrics(rightPane, { scrollHeight: 500, clientHeight: 100, scrollTop: 0 });

    fireEvent.scroll(leftPane);
    act(() => {
      raf.flushAllFrames();
    });

    expect(rightPane.scrollTop).toBeCloseTo(200, 4);
  });

  it("keeps panes independent after disabling scroll sync", () => {
    const raf = mockRequestAnimationFrame();
    const { container } = render(<ComparePanel />);
    fireEvent.click(screen.getByRole("radio", { name: "Raw" }));
    const compareContents = container.querySelectorAll<HTMLElement>(".compare-panel-content");
    const leftPane = compareContents[0];
    const rightPane = compareContents[1];

    if (!leftPane || !rightPane) {
      throw new Error("Expected at least two compare panes");
    }

    setScrollMetrics(leftPane, { scrollHeight: 300, clientHeight: 100, scrollTop: 100 });
    setScrollMetrics(rightPane, { scrollHeight: 500, clientHeight: 100, scrollTop: 0 });

    fireEvent.click(screen.getByRole("button", { name: "Disable sync" }));
    fireEvent.scroll(leftPane);
    act(() => {
      raf.flushAllFrames();
    });

    expect(rightPane.scrollTop).toBe(0);
  });

  it("virtualizes long content rendering when text exceeds 10,000 characters", () => {
    seedLongCompareResults();
    render(<ComparePanel />);
    fireEvent.click(screen.getByRole("radio", { name: "Raw" }));

    const firstPane = screen.getByTestId("compare-panel-content-0");
    const secondPane = screen.getByTestId("compare-panel-content-1");

    expect(firstPane).toHaveAttribute("data-virtualized", "true");
    expect(secondPane).toHaveAttribute("data-virtualized", "true");

    const totalLineCount = buildLongContent(900).split("\n").length;
    const renderedLineCount = firstPane.querySelectorAll(".compare-line").length;

    expect(renderedLineCount).toBeGreaterThan(0);
    expect(renderedLineCount).toBeLessThan(totalLineCount);
    expect(firstPane.querySelector(".compare-virtual-spacer")).not.toBeNull();
  });

  it("shows explicit multi-pane policy and keeps third pane diff-independent", () => {
    seedThreePaneCompareResults();
    render(<ComparePanel />);

    expect(
      screen.getByText("Multi-pane mode: Diff and synchronized scrolling apply only to the first two panes; other panes scroll independently.")
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Diff" }));

    const thirdPane = screen.getByTestId("compare-panel-content-2");
    expect(thirdPane).toHaveAttribute("data-diff-scope", "independent");
    expect(thirdPane.querySelectorAll(".compare-line-added,.compare-line-removed,.compare-line-modified")).toHaveLength(0);
  });

  it("keeps third pane out of scroll sync in multi-pane mode", () => {
    seedThreePaneCompareResults();
    const raf = mockRequestAnimationFrame();
    const { container } = render(<ComparePanel />);
    fireEvent.click(screen.getByRole("radio", { name: "Raw" }));
    const compareContents = container.querySelectorAll<HTMLElement>(".compare-panel-content");
    const leftPane = compareContents[0];
    const rightPane = compareContents[1];
    const thirdPane = compareContents[2];

    if (!leftPane || !rightPane || !thirdPane) {
      throw new Error("Expected three compare panes");
    }

    setScrollMetrics(leftPane, { scrollHeight: 300, clientHeight: 100, scrollTop: 100 });
    setScrollMetrics(rightPane, { scrollHeight: 500, clientHeight: 100, scrollTop: 0 });
    setScrollMetrics(thirdPane, { scrollHeight: 700, clientHeight: 100, scrollTop: 0 });

    fireEvent.scroll(leftPane);
    act(() => {
      raf.flushAllFrames();
    });

    expect(rightPane).toHaveAttribute("data-sync-scope", "paired");
    expect(thirdPane).toHaveAttribute("data-sync-scope", "independent");
    expect(rightPane.scrollTop).toBeCloseTo(200, 4);
    expect(thirdPane.scrollTop).toBe(0);
  });
});
