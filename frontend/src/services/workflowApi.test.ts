import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/services/api";
import {
  buildWorkflowTaskFormData,
  cancelWorkflowTask,
  createWorkflowTask,
  deleteWorkflow,
  exportWorkflow,
  getWorkflowList,
  importWorkflow,
  restoreWorkflowVersion,
  updateWorkflowMetadata
} from "@/services/workflowApi";

vi.mock("@/services/api", () => ({
  apiClient: {
    post: vi.fn(),
    get: vi.fn(),
    delete: vi.fn(),
    patch: vi.fn()
  }
}));

describe("workflowApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("builds multipart form data with workflow and files", () => {
    const fileA = new File(["a"], "a.pdf", { type: "application/pdf" });
    const fileB = new File(["b"], "b.pdf", { type: "application/pdf" });
    const formData = buildWorkflowTaskFormData(
      {
        nodes: [{ id: "input_1", type: "input/pdf", config: { file: "$file_0" } }],
        connections: []
      },
      [fileA, fileB]
    );

    expect(formData.get("workflow")).toContain("\"id\":\"input_1\"");
    expect(formData.getAll("files")).toEqual([fileA, fileB]);
  });

  it("posts workflow form data to /tasks", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { task_id: "task_1", status: "pending" }
    } as never);
    const formData = new FormData();

    const response = await createWorkflowTask(formData);

    expect(apiClient.post).toHaveBeenCalledWith("/tasks", formData, {
      headers: {
        "Content-Type": "multipart/form-data"
      }
    });
    expect(response.task_id).toBe("task_1");
  });

  it("cancels task using delete endpoint", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue({
      data: { task_id: "task_1", status: "cancelled" }
    } as never);

    await cancelWorkflowTask("task_1");

    expect(apiClient.delete).toHaveBeenCalledWith("/tasks/task_1");
  });

  it("imports workflow json via contract payload", async () => {
    const file = new File(
      [
        JSON.stringify({
          format_version: "1.0",
          workflow: {
            definition: { nodes: [], connections: [] }
          }
        })
      ],
      "workflow.json",
      {
      type: "application/json"
      }
    );
    vi.mocked(apiClient.post).mockResolvedValue({
      data: {
        success: true,
        data: {
          id: "wf_1",
          name: "imported"
        }
      }
    } as never);

    const response = await importWorkflow(file);

    expect(apiClient.post).toHaveBeenCalledWith(
      "/workflows/import",
      {
        format_version: "1.0",
        workflow: {
          definition: {
            nodes: [],
            connections: []
          }
        }
      }
    );
    expect(response.data.id).toBe("wf_1");
  });

  it("exports workflow json by id", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        format_version: "1.0",
        workflow: {
          definition: {
            nodes: [],
            connections: []
          }
        }
      }
    } as never);

    const response = await exportWorkflow("wf_1");

    expect(apiClient.get).toHaveBeenCalledWith("/workflows/wf_1/export");
    expect(response.workflow.definition.nodes).toHaveLength(0);
  });

  it("loads workflow list with query params and metadata", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        success: true,
        data: [
          {
            id: "wf_1",
            name: "Invoice OCR",
            description: "first saved",
            created_at: "2026-03-18T00:00:00Z",
            updated_at: "2026-03-18T00:01:00Z",
            published_version: 1,
            latest_version: 1
          }
        ],
        meta: {
          total: 2,
          page: 1,
          limit: 20
        }
      }
    } as never);

    const response = await getWorkflowList({
      page: 1,
      limit: 20,
      sort: "updated_at:desc",
      q: "invoice"
    });

    expect(apiClient.get).toHaveBeenCalledWith("/workflows", {
      params: {
        page: 1,
        limit: 20,
        sort: "updated_at:desc",
        q: "invoice"
      }
    });
    expect(response.items[0]?.name).toBe("Invoice OCR");
    expect(response.meta.total).toBe(2);
  });

  it("deletes workflow by id", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue({
      data: {
        success: true
      }
    } as never);

    const response = await deleteWorkflow("wf_1");

    expect(apiClient.delete).toHaveBeenCalledWith("/workflows/wf_1");
    expect(response.success).toBe(true);
  });

  it("updates workflow metadata by id", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({
      data: {
        success: true,
        data: {
          id: "wf_1",
          name: "Invoice OCR v2",
          description: "updated by review"
        }
      }
    } as never);

    const response = await updateWorkflowMetadata("wf_1", {
      name: "Invoice OCR v2",
      description: "updated by review"
    });

    expect(apiClient.patch).toHaveBeenCalledWith("/workflows/wf_1", {
      name: "Invoice OCR v2",
      description: "updated by review"
    });
    expect(response.data.name).toBe("Invoice OCR v2");
  });

  it("calls restore with path parameter endpoint by default", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { success: true, data: { id: "wf_restored" } }
    } as never);

    const response = await restoreWorkflowVersion("wf_1", 2);

    expect(apiClient.post).toHaveBeenCalledWith("/workflows/wf_1/restore/2");
    expect(response.data.id).toBe("wf_restored");
  });

  it("falls back to legacy restore endpoint when path endpoint is unavailable", async () => {
    vi.mocked(apiClient.post)
      .mockRejectedValueOnce({
        response: { status: 404 }
      } as never)
      .mockResolvedValueOnce({
        data: { success: true, data: { workflow_id: "wf_1", restored_version: 2 } }
      } as never);

    const response = await restoreWorkflowVersion("wf_1", 2);

    expect(apiClient.post).toHaveBeenNthCalledWith(1, "/workflows/wf_1/restore/2");
    expect(apiClient.post).toHaveBeenNthCalledWith(2, "/workflows/wf_1/restore", {
      version: 2
    });
    expect(response.data.workflow_id).toBe("wf_1");
  });
});
