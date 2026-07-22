import { apiClient } from "@/services/api";
import type {
  TestDocumentListResponse,
  TestDocumentUploadResponse,
  TestSetListResponse
} from "@/types/testSet";
import { buildWorkspaceScopedUrl } from "@/services/workspaceTransport";

export async function listTestSets(): Promise<TestSetListResponse> {
  const response = await apiClient.get<TestSetListResponse>("/test-sets");
  return response.data;
}

export async function listTestSetDocuments(testSetId: string): Promise<TestDocumentListResponse> {
  const response = await apiClient.get<TestDocumentListResponse>(`/test-sets/${testSetId}/documents`);
  return response.data;
}

export async function uploadTestSetDocuments(
  testSetId: string,
  files: File[]
): Promise<TestDocumentUploadResponse> {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append("files", file);
  });

  const response = await apiClient.post<TestDocumentUploadResponse>(
    `/test-sets/${testSetId}/documents/upload`,
    formData,
    {
      headers: {
        "Content-Type": "multipart/form-data"
      }
    }
  );

  return response.data;
}

export function getOriginalDocumentDownloadUrl(testSetId: string, documentId: string): string {
  return buildWorkspaceScopedUrl(`/api/test-sets/${testSetId}/documents/${documentId}/file`);
}

export function getDocumentPreviewUrl(testSetId: string, documentId: string): string {
  return buildWorkspaceScopedUrl(
    `/api/test-sets/${testSetId}/documents/${documentId}/file`,
    { disposition: "inline" }
  );
}

export type DocumentThumbnailSize = 96 | 640;

export function getDocumentThumbnailUrl(
  testSetId: string,
  documentId: string,
  size: DocumentThumbnailSize
): string {
  return buildWorkspaceScopedUrl(
    `/api/test-sets/${testSetId}/documents/${documentId}/thumbnail`,
    { size: String(size) }
  );
}
