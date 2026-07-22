import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/services/api";
import {
  getDocumentThumbnailUrl,
  getOriginalDocumentDownloadUrl,
  listTestSetDocuments,
  listTestSets,
  uploadTestSetDocuments
} from "@/services/testSetApi";
import {
  activateWorkspaceUser,
  setValidatedActiveWorkspaceId,
} from "@/services/workspaceTransport";

vi.mock("@/services/api", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn()
  }
}));

describe("testSetApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    activateWorkspaceUser("usr-test-set-api");
    setValidatedActiveWorkspaceId("ws-1");
  });

  it("loads test sets from /test-sets", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        items: [
          {
            id: "ts_1",
            name: "Invoices",
            description: "OCR smoke set",
            document_count: 2,
            created_at: "2026-04-28T00:00:00Z",
            updated_at: "2026-04-28T00:00:00Z"
          }
        ],
        total: 1
      }
    } as never);

    const response = await listTestSets();

    expect(apiClient.get).toHaveBeenCalledWith("/test-sets");
    expect(response.items[0]?.id).toBe("ts_1");
    expect(response.total).toBe(1);
  });

  it("loads documents for a selected test set", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        items: [
          {
            id: "doc_1",
            test_set_id: "ts_1",
            filename: "invoice.pdf",
            mime_type: "application/pdf",
            size_bytes: 12,
            page_count: 1,
            has_ground_truth: false,
            gt_version_count: 0,
            created_at: "2026-04-28T00:00:00Z"
          }
        ],
        total: 1
      }
    } as never);

    const response = await listTestSetDocuments("ts_1");

    expect(apiClient.get).toHaveBeenCalledWith("/test-sets/ts_1/documents");
    expect(response.items[0]?.filename).toBe("invoice.pdf");
  });

  it("uploads selected documents as multipart form data", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: {
        uploaded: [
          {
            id: "doc_1",
            filename: "invoice.pdf",
            mime_type: "application/pdf",
            size_bytes: 12
          }
        ],
        errors: []
      }
    } as never);

    const fileA = new File(["pdf"], "invoice.pdf", { type: "application/pdf" });
    const fileB = new File(["img"], "photo.png", { type: "image/png" });

    const response = await uploadTestSetDocuments("ts_1", [fileA, fileB]);

    expect(apiClient.post).toHaveBeenCalledWith(
      "/test-sets/ts_1/documents/upload",
      expect.any(FormData),
      {
        headers: {
          "Content-Type": "multipart/form-data"
        }
      }
    );

    const formData = vi.mocked(apiClient.post).mock.calls[0]?.[1] as FormData;
    expect(formData.getAll("files")).toEqual([fileA, fileB]);
    expect(response.uploaded).toHaveLength(1);
  });

  it("builds original-document download URLs under /api", () => {
    expect(getOriginalDocumentDownloadUrl("ts_1", "doc_1")).toBe(
      "/api/test-sets/ts_1/documents/doc_1/file?workspace_id=ws-1"
    );
  });

  it("builds workspace-scoped thumbnail URLs for the fixed size variants", () => {
    expect(getDocumentThumbnailUrl("ts_1", "doc_1", 96)).toBe(
      "/api/test-sets/ts_1/documents/doc_1/thumbnail?size=96&workspace_id=ws-1"
    );
    expect(getDocumentThumbnailUrl("ts_1", "doc_1", 640)).toBe(
      "/api/test-sets/ts_1/documents/doc_1/thumbnail?size=640&workspace_id=ws-1"
    );
  });
});
