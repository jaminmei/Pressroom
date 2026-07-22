import axios from "axios";

import { apiClient } from "@/services/api";
import type {
  DocumentGroundTruth,
  DocumentRunHistoryPage,
  GroundTruthVersionSummary,
  GTVersion,
  Project,
  ProjectDocument,
  ProjectRun,
  RunResult,
  EvaluationResultExecutionStatus,
} from "@/types/project";

export interface CreateProjectPayload {
  name: string;
  description?: string;
}

export interface UpdateProjectPayload {
  name?: string;
  description?: string;
}

export interface CreateRunPayload {
  workflowId: string;
  documentIds: string[];
  runName?: string;
}

interface BackendTestSet {
  id: string;
  name: string;
  description: string | null;
  document_count: number;
  created_at: string;
  updated_at: string;
}

interface BackendWorkspaceSettings {
  id: string;
  name: string;
  description: string | null;
}

interface BackendTestDocument {
  id: string;
  test_set_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  page_count: number | null;
  has_ground_truth: boolean;
  gt_version_count: number;
  created_at: string;
}

interface BackendEvaluationRun {
  id: string;
  name: string | null;
  test_set_id: string;
  workflow_id: string;
  workflow_version: number | null;
  status: ProjectRun["status"];
  total_documents: number;
  completed_count: number;
  failed_count: number;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  created_at: string;
}

interface BackendEvaluationRunListItem extends BackendEvaluationRun {
  workflow_name: string | null;
  result_summary: {
    total: number;
    completed: number;
    failed: number;
    queued: number;
    running: number;
  };
  review_summary: {
    accepted: number;
    rejected: number;
    unreviewed: number;
  };
  comparison_summary?: {
    matched: number;
    mismatched: number;
    not_compared: number;
    unavailable: number;
  };
}

interface BackendDocumentRunHistoryItem {
  run_id: string;
  result_id: string;
  run_name: string | null;
  workflow_id: string;
  workflow_name: string | null;
  run_status: ProjectRun["status"];
  result_status: string;
  processing_time_ms: number | null;
  error: string | null;
  comparison_status: string | null;
  review_status: string | null;
  created_at: string;
  completed_at: string | null;
  run_duration_ms: number | null;
}

interface BackendDocumentRunHistoryResponse {
  items: BackendDocumentRunHistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

interface BackendResultListItem {
  id: string;
  document_id: string;
  filename: string | null;
  status: string;
  processing_time_ms: number | null;
  output_format: string | null;
  error: string | null;
  comparison_status: string | null;
  review_status: string | null;
  has_ground_truth: boolean;
}

interface BackendResultsResponse {
  evaluation_run_id: string;
  status: string;
  summary: { total: number; completed: number; failed: number };
  results: BackendResultListItem[];
}

interface BackendReviewResult {
  id: string;
  evaluation_run_id: string;
  document_id: string;
  status: string;
  review_status: string;
  accepted_ground_truth_id: string | null;
  reviewed_at: string | null;
  review_notes: string | null;
  comparison_status: string | null;
  has_ground_truth: boolean;
}

export interface CompareResponse {
  result_id: string;
  document_id: string;
  comparison_status: string;
  diff_mode: string;
  expected_content: string | null;
  actual_content: string | null;
  diff_fields: Array<{ field_name: string; expected: string; actual: string }>;
}

interface BackendGTVersionItem {
  id: string;
  document_id?: string;
  version: number;
  source: string;
  format: string;
  content?: string;
  notes: string | null;
  created_at: string;
  source_task_run_id?: string;
}

function mapGroundTruthVersion(
  item: BackendGTVersionItem,
  projectId: string,
  documentId: string,
): GroundTruthVersionSummary {
  return {
    id: item.id,
    projectId,
    documentId,
    version: item.version,
    source: item.source,
    format: item.format,
    notes: item.notes ?? undefined,
    createdAt: item.created_at,
    sourceTaskRunId: item.source_task_run_id,
  };
}

function mapDocumentGroundTruth(
  item: BackendGTVersionItem,
  projectId: string,
  documentId: string,
): DocumentGroundTruth {
  return {
    ...mapGroundTruthVersion(item, projectId, documentId),
    content: item.content ?? "",
  };
}

function mapTestSetToProject(ts: BackendTestSet): Project {
  return {
    id: ts.id,
    name: ts.name,
    description: ts.description ?? undefined,
    documentCount: ts.document_count,
    lastUpdated: ts.updated_at,
    createdAt: ts.created_at,
  };
}

function mapDocumentToProjectDocument(doc: BackendTestDocument): ProjectDocument {
  return {
    id: doc.id,
    projectId: doc.test_set_id,
    filename: doc.filename,
    type: doc.mime_type,
    size: doc.size_bytes,
    uploadedAt: doc.created_at,
    gtStatus: doc.has_ground_truth ? "approved" : "none",
  };
}

function mapRunListItemToProjectRun(item: BackendEvaluationRunListItem): ProjectRun {
  const matched = item.comparison_summary?.matched ?? 0;
  const mismatched = item.comparison_summary?.mismatched ?? 0;
  const compared = matched + mismatched;
  const passRate = compared > 0
    ? Math.round((matched / compared) * 100)
    : undefined;

  return {
    id: item.id,
    projectId: item.test_set_id,
    workflowId: item.workflow_id,
    workflowName: item.workflow_name ?? "",
    name: item.name ?? undefined,
    status: item.status as ProjectRun["status"],
    startedAt: item.started_at ?? item.created_at,
    completedAt: item.completed_at ?? undefined,
    duration: item.duration_ms != null ? Math.round(item.duration_ms / 1000) : undefined,
    documentCount: item.total_documents,
    passRate,
  };
}

function mapRunToProjectRun(run: BackendEvaluationRun, workflowName?: string): ProjectRun {
  return {
    id: run.id,
    projectId: run.test_set_id,
    workflowId: run.workflow_id,
    workflowName: workflowName ?? "",
    name: run.name ?? undefined,
    status: run.status as ProjectRun["status"],
    startedAt: run.started_at ?? run.created_at,
    completedAt: run.completed_at ?? undefined,
    duration: run.duration_ms != null ? Math.round(run.duration_ms / 1000) : undefined,
    documentCount: run.total_documents,
  };
}

export function mapComparisonStatus(
  comparison_status: string | null,
  has_ground_truth: boolean,
): RunResult["status"] {
  if (!has_ground_truth) return "no_gt";
  if (comparison_status === "matched") return "pass";
  if (comparison_status === "mismatched") return "differs";
  return "unknown";
}

function mapResultStatus(
  result_status: string | null,
  comparison_status: string | null,
  review_status: string | null,
  has_ground_truth: boolean,
): RunResult["status"] {
  // Check execution status first — surfaces failures that comparison_status would mask
  if (result_status === "failed") return "failed";
  if (result_status === "running" || result_status === "queued" || result_status === "pending") return "running";
  if (result_status === "skipped") return "skipped";

  // Then comparison/review logic for completed results
  if (review_status === "accepted") return "pass";

  if (result_status === "completed") {
    return mapComparisonStatus(comparison_status, has_ground_truth);
  }
  return "unknown";
}

function mapExecutionStatus(status: string | null): EvaluationResultExecutionStatus {
  if (
    status === "queued" ||
    status === "running" ||
    status === "completed" ||
    status === "failed" ||
    status === "skipped"
  ) {
    return status;
  }
  return "queued";
}

function mapResultToRunResult(item: BackendResultListItem, runId: string): RunResult {
  return {
    id: item.id,
    runId,
    documentId: item.document_id,
    documentName: item.filename ?? "Unknown",
    status: mapResultStatus(
      item.status,
      item.comparison_status,
      item.review_status,
      item.has_ground_truth,
    ),
    executionStatus: mapExecutionStatus(item.status),
    hasGroundTruth: item.has_ground_truth,
    acceptedAsGT: item.review_status === "accepted",
    rejected: item.review_status === "rejected",
  };
}

function mapReviewToRunResult(review: BackendReviewResult): RunResult {
  return {
    id: review.id,
    runId: review.evaluation_run_id,
    documentId: review.document_id,
    documentName: "",
    status: mapResultStatus(
      review.status,
      review.comparison_status,
      review.review_status,
      review.has_ground_truth,
    ),
    executionStatus: mapExecutionStatus(review.status),
    hasGroundTruth: review.has_ground_truth,
    acceptedAsGT: review.review_status === "accepted",
    rejected: review.review_status === "rejected",
  };
}

export async function listProjects(): Promise<Project[]> {
  const response = await apiClient.get<{ items: BackendTestSet[]; total: number }>("/test-sets");
  return response.data.items.map(mapTestSetToProject);
}

export async function createProject(payload: CreateProjectPayload): Promise<Project> {
  const response = await apiClient.post<BackendTestSet>("/test-sets", {
    name: payload.name,
    description: payload.description ?? null,
  });
  return mapTestSetToProject(response.data);
}

export async function getProject(projectId: string): Promise<Project> {
  const response = await apiClient.get<BackendTestSet>(`/test-sets/${projectId}`);
  return mapTestSetToProject(response.data);
}

export async function updateProject(projectId: string, payload: UpdateProjectPayload): Promise<Project> {
  const body: Record<string, unknown> = {};
  if (payload.name !== undefined) body.name = payload.name;
  if (payload.description !== undefined) body.description = payload.description;

  const response = await apiClient.patch<BackendTestSet>(`/test-sets/${projectId}`, body);
  return mapTestSetToProject(response.data);
}

export async function deleteProject(projectId: string): Promise<void> {
  await apiClient.delete(`/test-sets/${projectId}`);
}

export async function updateDatabaseSettings(
  workspaceId: string,
  payload: UpdateProjectPayload,
): Promise<BackendWorkspaceSettings> {
  const response = await apiClient.patch<BackendWorkspaceSettings>(`/workspaces/${workspaceId}`, {
    name: payload.name,
    description: payload.description,
  });
  return response.data;
}

export async function deleteDatabase(workspaceId: string): Promise<void> {
  await apiClient.delete(`/workspaces/${workspaceId}`);
}

export async function listDocuments(projectId: string): Promise<ProjectDocument[]> {
  const response = await apiClient.get<{ items: BackendTestDocument[]; total: number }>(
    `/test-sets/${projectId}/documents`,
  );
  return response.data.items.map(mapDocumentToProjectDocument);
}

export async function uploadDocuments(
  projectId: string,
  files: File[],
): Promise<ProjectDocument[]> {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append("files", file);
  });

  const response = await apiClient.post<{
    uploaded: Array<{ id: string; filename: string; mime_type: string; size_bytes: number }>;
    errors: Array<{ filename: string; error: string }>;
  }>(`/test-sets/${projectId}/documents/upload`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });

  return response.data.uploaded.map((doc) => ({
    id: doc.id,
    projectId,
    filename: doc.filename,
    type: doc.mime_type,
    size: doc.size_bytes,
    uploadedAt: new Date().toISOString(),
    gtStatus: "none" as const,
  }));
}

export async function deleteDocument(projectId: string, documentId: string): Promise<void> {
  await apiClient.delete(`/test-sets/${projectId}/documents/${documentId}`);
}

export async function listRuns(projectId: string): Promise<ProjectRun[]> {
  const response = await apiClient.get<{ items: BackendEvaluationRunListItem[]; total: number }>(
    `/test-sets/${projectId}/evaluation-runs`,
  );
  return response.data.items.map(mapRunListItemToProjectRun);
}

export async function getDocumentRunHistory(
  projectId: string,
  documentId: string,
  limit = 20,
  offset = 0,
): Promise<DocumentRunHistoryPage> {
  const response = await apiClient.get<BackendDocumentRunHistoryResponse>(
    `/test-sets/${projectId}/documents/${documentId}/evaluation-runs`,
    { params: { limit, offset } },
  );
  return {
    total: response.data.total,
    limit: response.data.limit,
    offset: response.data.offset,
    items: response.data.items.map((item) => ({
      runId: item.run_id,
      resultId: item.result_id,
      runName: item.run_name ?? undefined,
      workflowId: item.workflow_id,
      workflowName: item.workflow_name ?? undefined,
      runStatus: item.run_status,
      resultStatus: item.result_status,
      processingTimeMs: item.processing_time_ms ?? undefined,
      error: item.error ?? undefined,
      comparisonStatus: item.comparison_status ?? undefined,
      reviewStatus: item.review_status ?? undefined,
      createdAt: item.created_at,
      completedAt: item.completed_at ?? undefined,
      runDurationMs: item.run_duration_ms ?? undefined,
    })),
  };
}

export async function createRun(projectId: string, payload: CreateRunPayload): Promise<ProjectRun> {
  const response = await apiClient.post<BackendEvaluationRun>(
    `/test-sets/${projectId}/evaluation-runs`,
    {
      workflow_id: payload.workflowId,
      document_ids: payload.documentIds,
      name: payload.runName ?? null,
    },
  );
  return mapRunToProjectRun(response.data);
}

export async function getRunDetail(projectId: string, runId: string): Promise<ProjectRun> {
  void projectId;
  const response = await apiClient.get<BackendEvaluationRun>(`/evaluation-runs/${runId}`);
  return mapRunToProjectRun(response.data);
}

export async function getRunResults(runId: string): Promise<RunResult[]> {
  const response = await apiClient.get<BackendResultsResponse>(`/evaluation-runs/${runId}/results`);
  return response.data.results.map((item) => mapResultToRunResult(item, runId));
}

export async function getRunStatus(runId: string): Promise<{
  status: ProjectRun["status"];
  completedCount: number;
  totalDocuments: number;
}> {
  const response = await apiClient.get<BackendEvaluationRun>(`/evaluation-runs/${runId}`);
  return {
    status: response.data.status,
    completedCount: response.data.completed_count,
    totalDocuments: response.data.total_documents,
  };
}

export async function compareResult(runId: string, resultId: string): Promise<CompareResponse> {
  const response = await apiClient.get<CompareResponse>(
    `/evaluation-runs/${runId}/results/${resultId}/compare`,
  );
  return response.data;
}

export async function acceptAsGT(
  _projectId: string,
  runId: string,
  resultId: string,
  notes?: string,
): Promise<RunResult> {
  const body = notes ? { notes } : undefined;
  const response = await apiClient.post<BackendReviewResult>(
    `/evaluation-runs/${runId}/results/${resultId}/accept-as-ground-truth`,
    body,
  );
  return mapReviewToRunResult(response.data);
}

export async function rejectResult(
  _projectId: string,
  runId: string,
  resultId: string,
  reason?: string,
): Promise<RunResult> {
  const body = reason ? { reason } : undefined;
  const response = await apiClient.post<BackendReviewResult>(
    `/evaluation-runs/${runId}/results/${resultId}/reject`,
    body,
  );
  return mapReviewToRunResult(response.data);
}

export async function getGTVersions(projectId: string, documentId: string): Promise<GTVersion[]> {
  const response = await apiClient.get<{ items: BackendGTVersionItem[]; total: number }>(
    `/test-sets/${projectId}/documents/${documentId}/ground-truth/versions`,
  );
  return response.data.items.map((item) => ({
    id: item.id,
    projectId,
    version: item.version,
    createdAt: item.created_at,
    documentCount: 1,
    source: (item.source === "manual" ? "manual" : "accepted_run") as GTVersion["source"],
  }));
}

export async function getLatestDocumentGroundTruth(
  projectId: string,
  documentId: string,
): Promise<DocumentGroundTruth | null> {
  try {
    const response = await apiClient.get<BackendGTVersionItem>(
      `/test-sets/${projectId}/documents/${documentId}/ground-truth`,
    );
    return mapDocumentGroundTruth(response.data, projectId, documentId);
  } catch (error: unknown) {
    if (axios.isAxiosError(error) && error.response?.status === 404) return null;
    throw error;
  }
}

export async function listDocumentGroundTruthVersions(
  projectId: string,
  documentId: string,
): Promise<GroundTruthVersionSummary[]> {
  const response = await apiClient.get<{ items: BackendGTVersionItem[]; total: number }>(
    `/test-sets/${projectId}/documents/${documentId}/ground-truth/versions`,
  );
  return response.data.items
    .map((item) => mapGroundTruthVersion(item, projectId, documentId))
    .sort((left, right) => right.version - left.version);
}

export async function getDocumentGroundTruthVersion(
  projectId: string,
  documentId: string,
  version: number,
): Promise<DocumentGroundTruth> {
  const response = await apiClient.get<BackendGTVersionItem>(
    `/test-sets/${projectId}/documents/${documentId}/ground-truth/versions/${version}`,
  );
  return mapDocumentGroundTruth(response.data, projectId, documentId);
}

export async function uploadGroundTruth(
  projectId: string,
  documentId: string,
  content: string,
  source: string = "manual",
): Promise<GTVersion> {
  const response = await apiClient.post<BackendGTVersionItem>(
    `/test-sets/${projectId}/documents/${documentId}/ground-truth`,
    { content, source, format: "json" },
  );
  return {
    id: response.data.id,
    projectId,
    version: response.data.version,
    createdAt: response.data.created_at,
    documentCount: 1,
    source: (response.data.source === "manual" ? "manual" : "accepted_run") as GTVersion["source"],
  };
}
