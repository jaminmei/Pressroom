import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("@/services/taskApi", () => ({
  getTaskResults: vi.fn()
}));

vi.mock("@/features/result/components/DownloadButton", () => ({
  default: function MockDownloadButton() {
    return <button type="button">Download Markdown</button>;
  }
}));

vi.mock("@/features/result/components/MarkdownViewer", () => ({
  default: function MockMarkdownViewer({ content }: { content: string }) {
    return <div data-testid="markdown-viewer">{content}</div>;
  }
}));

import ResultPage from "@/features/result/components/ResultPage";
import { initialResultState, useResultStore } from "@/features/result/store";
import { getTaskResults } from "@/services/taskApi";
import type { TaskResult, TaskResultsResponse } from "@/types/task";

const mockedGetTaskResults = vi.mocked(getTaskResults);

const sampleResult: TaskResult = {
  result_id: "result_1",
  node_id: "output_1",
  node_type: "output/markdown",
  status: "completed",
  file: {
    filename: "sample.md",
    size_bytes: 128,
    content_type: "text/markdown",
    download_url: "/api/tasks/task_123/results/result_1/download"
  },
  metadata: {
    processing_time_ms: 1234,
    page_count: 2,
    char_count: 42,
    word_count: 9
  },
  content: "# Sample result"
};

// Captured from the public VLM live test. Running-task results can be sparser
// than the persisted TaskResult type (notably node and document-count fields).
const sparseVlmContent = `{
  "text": "mock vision response",
  "binary": [],
  "structured": {
    "result": "mock vision response"
  },
  "metadata": {
    "processing_time_ms": 7,
    "model": "azure-deployment-99fxlca",
    "request_id": null,
    "usage": {
      "completion_tokens": 4,
      "prompt_tokens": 10,
      "total_tokens": 14,
      "completion_tokens_details": null,
      "prompt_tokens_details": null
    },
    "upstream_latency_ms": 7
  }
}`;

const sparseVlmResponse = {
  task_id: "task_f061791c0348",
  status: "completed",
  results: [
    {
      result_id: "r_task_f061791c0348_engine_1",
      format: "json",
      file: {
        filename: "engine_1_output.json",
        size_bytes: 438,
        content_type: "application/json",
        download_url: "/api/tasks/task_f061791c0348/results/r_task_f061791c0348_engine_1/download"
      },
      content: sparseVlmContent,
      metadata: {
        processing_time_ms: 7,
        model: "azure-deployment-99fxlca",
        request_id: null,
        usage: {
          completion_tokens: 4,
          prompt_tokens: 10,
          total_tokens: 14,
          completion_tokens_details: null,
          prompt_tokens_details: null
        },
        upstream_latency_ms: 7
      },
      engine_type: "ocr",
      output_format: "markdown",
      status: "completed",
      result_preview: sparseVlmContent,
      duration_ms: 7
    }
  ],
  summary: {
    total_outputs: 1,
    completed: 1,
    failed: 0
  }
} as unknown as TaskResultsResponse;

function renderResultRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<ResultPage />} path="/tasks/:taskId/results" />
      </Routes>
    </MemoryRouter>
  );
}

describe("ResultPage", () => {
  beforeEach(() => {
    useResultStore.setState({ ...initialResultState });
    mockedGetTaskResults.mockReset();
  });

  it("starts a cold deep-link fetch when the store is empty", async () => {
    mockedGetTaskResults.mockResolvedValue({
      task_id: "task_123",
      status: "completed",
      results: [sampleResult]
    });

    renderResultRoute("/tasks/task_123/results");

    expect(document.querySelector(".ant-spin-spinning")).not.toBeNull();
    await waitFor(() => {
      expect(mockedGetTaskResults).toHaveBeenCalledWith("task_123");
    });
  });

  it("finishes loading and renders a sparse live VLM result on a cold deep link", async () => {
    mockedGetTaskResults.mockResolvedValue(sparseVlmResponse);

    renderResultRoute("/tasks/task_f061791c0348/results");

    expect(document.querySelector(".ant-spin-spinning")).not.toBeNull();
    expect(await screen.findByText("Conversion Result")).toBeInTheDocument();
    expect(screen.getByTestId("markdown-viewer")).toHaveTextContent("mock vision response");
    expect(document.querySelector(".ant-spin-spinning")).toBeNull();
  });

  it("renders warm-store results without refetching", async () => {
    useResultStore.setState({
      taskId: "task_123",
      results: [sampleResult],
      displayMode: "rendered"
    });

    renderResultRoute("/tasks/task_123/results");

    expect(await screen.findByText("Conversion Result")).toBeInTheDocument();
    expect(screen.getByText("Task ID: task_123")).toBeInTheDocument();
    expect(mockedGetTaskResults).not.toHaveBeenCalled();
  });
});
