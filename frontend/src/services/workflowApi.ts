import { apiClient } from "@/services/api";
import type { CreateTaskResponse, TaskStatus } from "@/types/task";
import type { WorkflowExecutionPayload } from "@/features/workflow-editor/utils/workflowBuilder";

export interface WorkflowActorSummary {
  user_id: string;
  email: string;
  name?: string | null;
}

export interface CancelTaskResponse {
  task_id: string;
  status: "cancelled";
  message?: string;
  cancelled_at?: string;
}

export interface WorkflowImportExportNode {
  id: string;
  type: string;
  config?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface WorkflowImportExportConnection {
  source: string;
  target: string;
  id?: string;
  [key: string]: unknown;
}

export interface WorkflowImportExportPayload {
  nodes: WorkflowImportExportNode[];
  connections: WorkflowImportExportConnection[];
}

export interface WorkflowSaveDraftPayload {
  workflow_id?: string;
  workflow_key?: string;
  base_version?: number | null;
  name?: string;
  description?: string | null;
  definition: WorkflowImportExportPayload;
}

export interface WorkflowMetadataUpdatePayload {
  name: string;
  description?: string | null;
}

export interface WorkflowListItem {
  id: string;
  workflow_key?: string | null;
  name?: string;
  description?: string;
  created_at: string;
  updated_at: string;
  published_version?: number | null;
  latest_version?: number;
  created_by?: WorkflowActorSummary | null;
  last_saved_by?: WorkflowActorSummary | null;
}

export interface WorkflowListMeta {
  total: number;
  page: number;
  limit: number;
}

interface WorkflowListApiEnvelope {
  success: boolean;
  data: WorkflowListItem[];
  meta: WorkflowListMeta;
}

export interface WorkflowListResponse {
  success: boolean;
  items: WorkflowListItem[];
  meta: WorkflowListMeta;
}

export interface WorkflowSaveDraftResponse {
  success: boolean;
  data: {
    id: string;
    workflow_key?: string | null;
    name?: string;
    description?: string;
    created_at: string;
    updated_at: string;
    published_version?: number | null;
    latest_version?: number;
    base_version?: number | null;
    created_by?: WorkflowActorSummary | null;
    last_saved_by?: WorkflowActorSummary | null;
  };
}

export interface WorkflowVersionRecord {
  version: number;
  status: "saved" | "published" | "draft";
  dag_hash?: string | null;
  created_at: string;
  created_by?: WorkflowActorSummary | null;
}

export interface WorkflowDeleteResponse {
  success: boolean;
}

export interface WorkflowMetadataUpdateResponse {
  success: boolean;
  data: {
    id: string;
    workflow_key?: string | null;
    name?: string;
    description?: string;
    created_at?: string;
    updated_at?: string;
    published_version?: number | null;
    latest_version?: number;
  };
}

export interface WorkflowDetailResponse {
  id: string;
  workflow_key?: string | null;
  name?: string;
  description?: string;
  definition: WorkflowImportExportPayload;
  created_at: string;
  updated_at: string;
  published_version?: number | null;
  latest_version?: number;
  created_by?: WorkflowActorSummary | null;
  last_saved_by?: WorkflowActorSummary | null;
  versions?: WorkflowVersionRecord[];
}

export interface PublishWorkflowResponse {
  success: boolean;
  data: {
    workflow_id: string;
    version: number;
    published_at: string;
    published_version: number;
  };
}

export interface WorkflowVersionsResponse {
  success: boolean;
  data: WorkflowVersionRecord[];
  meta?: {
    total: number;
  };
}

export interface RestoreWorkflowResponse {
  success: boolean;
  data: {
    id?: string;
    workflow_id?: string;
    workflow_key?: string;
    version?: number;
    restored_version?: number;
    status?: "draft" | "published";
    restored_from_version?: number;
    updated_at?: string;
  };
}

export interface NodeRunTaskResponse {
  task_id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  created_at?: string;
  node_id: string;
  output_format: string;
}

export interface WorkflowImportRequest {
  format_version: string;
  exported_at?: string;
  workflow: {
    name?: string;
    description?: string;
    definition: WorkflowImportExportPayload;
  };
}

export interface WorkflowImportResponse {
  success: boolean;
  data: {
    id: string;
    name?: string;
    created_at?: string;
  };
  warnings?: Array<Record<string, unknown>>;
}

export interface WorkflowExportResponse {
  format_version: string;
  exported_at?: string;
  workflow: {
    name?: string;
    description?: string;
    definition: WorkflowImportExportPayload;
  };
}

async function readFileText(file: File): Promise<string> {
  if (typeof file.text === "function") {
    return file.text();
  }

  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      resolve(typeof reader.result === "string" ? reader.result : "");
    };
    reader.onerror = () => {
      reject(reader.error ?? new Error("FILE_READ_FAILED"));
    };
    reader.readAsText(file);
  });
}

export function buildWorkflowTaskFormData(workflow: WorkflowExecutionPayload, files: File[]): FormData {
  const formData = new FormData();
  formData.append("workflow", JSON.stringify(workflow));
  files.forEach((file) => {
    formData.append("files", file);
  });
  return formData;
}

export async function createWorkflowTask(formData: FormData): Promise<CreateTaskResponse> {
  const response = await apiClient.post<CreateTaskResponse>("/tasks", formData, {
    headers: {
      "Content-Type": "multipart/form-data"
    }
  });
  return response.data;
}

export async function cancelWorkflowTask(taskId: string): Promise<CancelTaskResponse> {
  const response = await apiClient.delete<CancelTaskResponse>(`/tasks/${taskId}`);
  return response.data;
}

export async function importWorkflow(file: File): Promise<WorkflowImportResponse> {
  let payload: WorkflowImportRequest;
  try {
    payload = JSON.parse(await readFileText(file)) as WorkflowImportRequest;
  } catch {
    throw new Error("WORKFLOW_SCHEMA_INVALID");
  }

  const response = await apiClient.post<WorkflowImportResponse>("/workflows/import", payload);
  return response.data;
}

export async function exportWorkflow(workflowId: string): Promise<WorkflowExportResponse> {
  const response = await apiClient.get<WorkflowExportResponse>(`/workflows/${workflowId}/export`);
  return response.data;
}

export async function saveWorkflowDraft(
  payload: WorkflowSaveDraftPayload
): Promise<WorkflowSaveDraftResponse> {
  const response = payload.workflow_id
    ? await apiClient.patch<WorkflowSaveDraftResponse>(`/workflows/${payload.workflow_id}`, {
        name: payload.name,
        description: payload.description,
        definition: payload.definition,
        base_version: payload.base_version,
      })
    : await apiClient.post<WorkflowSaveDraftResponse>("/workflows", {
        name: payload.name,
        description: payload.description,
        definition: payload.definition,
      });
  return response.data;
}

export async function getWorkflowList(params: {
  page?: number;
  limit?: number;
  sort?: string;
  q?: string;
} = {}): Promise<WorkflowListResponse> {
  const response = await apiClient.get<WorkflowListApiEnvelope>("/workflows", {
    params
  });
  const payload = response.data;

  return {
    success: payload.success,
    items: payload.data,
    meta: payload.meta,
  };
}

export async function getWorkflowDetail(workflowId: string): Promise<WorkflowDetailResponse> {
  const response = await apiClient.get<WorkflowDetailResponse>(`/workflows/${workflowId}`);
  return response.data;
}

export async function executePersistedWorkflow(
  workflowId: string,
  runName?: string,
): Promise<{ task_id: string; status: TaskStatus }> {
  const response = await apiClient.post<{ task_id: string; status: TaskStatus }>(
    `/workflows/${workflowId}/execute`,
    { run_name: runName?.trim() || null },
  );
  return response.data;
}

export async function deleteWorkflow(workflowId: string): Promise<WorkflowDeleteResponse> {
  const response = await apiClient.delete<WorkflowDeleteResponse>(`/workflows/${workflowId}`);
  return response.data;
}

export async function updateWorkflowMetadata(
  workflowId: string,
  payload: WorkflowMetadataUpdatePayload
): Promise<WorkflowMetadataUpdateResponse> {
  const response = await apiClient.patch<WorkflowMetadataUpdateResponse>(`/workflows/${workflowId}`, payload);
  return response.data;
}

export async function publishWorkflow(workflowId: string): Promise<PublishWorkflowResponse> {
  const response = await apiClient.post<PublishWorkflowResponse>(`/workflows/${workflowId}/publish`);
  return response.data;
}

export async function getWorkflowVersions(workflowId: string): Promise<WorkflowVersionsResponse> {
  const response = await apiClient.get<WorkflowVersionsResponse>(`/workflows/${workflowId}/versions`);
  return response.data;
}

export async function getWorkflowVersionDetail(workflowId: string, version: number) {
  const resp = await apiClient.get(`/workflows/${workflowId}/versions/${version}`);
  return resp.data;
}

export async function restoreWorkflowVersion(
  workflowId: string,
  version: number
): Promise<RestoreWorkflowResponse> {
  const response = await apiClient.post<RestoreWorkflowResponse>(
    `/workflows/${workflowId}/versions/${version}/restore`,
  );
  return response.data;
}

export function buildNodeRunTaskFormData(
  workflow: WorkflowExecutionPayload,
  nodeId: string,
  files: File[],
  outputFormat: "markdown" | "plaintext" | "yaml" | "text" = "markdown"
): FormData {
  const formData = new FormData();
  formData.append("workflow", JSON.stringify(workflow));
  formData.append("node_id", nodeId);
  formData.append("output_format", outputFormat);
  files.forEach((file) => {
    formData.append("files", file);
  });
  return formData;
}

export async function createNodeRunTask(formData: FormData): Promise<NodeRunTaskResponse> {
  const response = await apiClient.post<NodeRunTaskResponse>("/tasks/node-run", formData, {
    headers: {
      "Content-Type": "multipart/form-data"
    }
  });
  return response.data;
}

// --- Workflow Lifecycle: DAG Hash Publish & Lookup ---

export interface PublishByHashRequest {
  name: string;
  description: string;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  node_configs: Record<string, Record<string, unknown>>;
}

export interface PublishByHashResponse {
  id: string;
  name: string;
  dag_hash: string;
}

export async function publishWorkflowByHash(payload: PublishByHashRequest): Promise<PublishByHashResponse> {
  const response = await apiClient.post<PublishByHashResponse>("/workflows/publish", payload);
  return response.data;
}

// --- Unified Publish & Publish As ---

export interface UnifiedPublishPayload {
  workflow_id?: string;
  name?: string;
  description?: string;
  definition: { nodes: unknown[]; connections: unknown[] };
  base_version?: number;
}

export interface UnifiedPublishResponse {
  success: boolean;
  data: {
    workflow_id: string;
    workflow_key?: string | null;
    name?: string;
    version: number;
    published_version: number;
    published_at: string;
    dag_hash?: string;
  };
}

export async function publishUnifiedWorkflow(payload: UnifiedPublishPayload): Promise<UnifiedPublishResponse> {
  const resp = await apiClient.post<UnifiedPublishResponse>("/workflows/publish", payload);
  return resp.data;
}

export interface PublishAsPayload {
  workflow_id: string;
  name: string;
  description?: string;
}

export interface PublishAsResponse {
  success: boolean;
  data: {
    workflow_id: string;
    workflow_key?: string | null;
    name?: string;
    version: number;
    published_version: number;
    published_at: string;
    dag_hash?: string;
  };
}

export async function publishAsWorkflow(payload: PublishAsPayload): Promise<PublishAsResponse> {
  const resp = await apiClient.post<PublishAsResponse>("/workflows/publish-as", payload);
  return resp.data;
}
