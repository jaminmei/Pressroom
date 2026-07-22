export interface TestSet {
  id: string;
  name: string;
  description: string | null;
  document_count: number;
  created_at: string;
  updated_at: string;
}

export interface TestSetListResponse {
  items: TestSet[];
  total: number;
}

export interface TestDocument {
  id: string;
  test_set_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number | null;
  page_count: number | null;
  has_ground_truth: boolean;
  gt_version_count: number;
  created_at: string;
}

export interface TestDocumentListResponse {
  items: TestDocument[];
  total: number;
}

export interface TestDocumentUploadItem {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number | null;
}

export interface TestDocumentUploadError {
  filename: string;
  error: string;
}

export interface TestDocumentUploadResponse {
  uploaded: TestDocumentUploadItem[];
  errors: TestDocumentUploadError[];
}
