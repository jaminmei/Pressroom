import { apiClient } from "@/services/api";
import type {
  CreateTaskResponse,
  TaskHistoryItem,
  TaskHistoryMeta,
  TaskHistoryResponse,
  TaskResultsResponse,
  TaskStatusResponse
} from "@/types/task";
import { buildWorkspaceScopedUrl } from "@/services/workspaceTransport";

export interface NodeOutput {
  text: string | null;
  binary: Array<{
    ref: string;
    data?: string;
    mime_type: string;
    size_bytes: number;
    dimensions?: Record<string, number>;
  }>;
  structured: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
}

export interface NodeResultResponse {
  node_id: string;
  node_type: string;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | Record<string, unknown> | null;
  output_type: string | null;
  data: unknown;
  output?: NodeOutput | null;
}

interface TaskHistoryApiEnvelope {
  items?: TaskHistoryItem[];
  data?: TaskHistoryItem[];
  meta?: TaskHistoryMeta;
}

export async function createTask(formData: FormData): Promise<CreateTaskResponse> {
  const response = await apiClient.post<CreateTaskResponse>("/tasks", formData, {
    headers: {
      "Content-Type": "multipart/form-data"
    }
  });

  return response.data;
}

export async function getTaskStatus(taskId: string): Promise<TaskStatusResponse> {
  const response = await apiClient.get<TaskStatusResponse>(`/tasks/${taskId}`);
  return response.data;
}

export async function getTaskResults(taskId: string): Promise<TaskResultsResponse> {
  const response = await apiClient.get<TaskResultsResponse>(`/tasks/${taskId}/results`);
  return response.data;
}

export async function getTaskHistory(params: {
  page?: number;
  limit?: number;
  status?: string;
  workflow_id?: string;
} = {}): Promise<TaskHistoryResponse> {
  const response = await apiClient.get<TaskHistoryApiEnvelope>("/tasks/history", {
    params
  });
  const payload = response.data;
  return {
    items: payload.data ?? payload.items ?? [],
    meta: payload.meta
  };
}

export async function getNodeResult(taskId: string, nodeId: string): Promise<NodeResultResponse> {
  const response = await apiClient.get<NodeResultResponse>(
    `/tasks/${taskId}/nodes/${nodeId}/result`
  );
  return response.data;
}

export function getNodeImageUrl(
  taskId: string,
  nodeId: string,
  extraParams?: Readonly<Record<string, string>>
): string {
  return buildWorkspaceScopedUrl(`/api/tasks/${taskId}/nodes/${nodeId}/image`, extraParams);
}

export async function resetTask(taskId: string): Promise<{ task_id: string; status: string }> {
  const response = await apiClient.post<{ task_id: string; status: string }>(
    `/tasks/${taskId}/reset`
  );
  return response.data;
}

export async function retryTaskNode(
  taskId: string,
  nodeId: string
): Promise<{ task_id: string; node_id: string; status: string }> {
  const response = await apiClient.post<{
    task_id: string;
    node_id: string;
    status: string;
  }>(`/tasks/${taskId}/nodes/${nodeId}/retry`);
  return response.data;
}

export async function rerunNode(
  taskId: string,
  nodeId: string
): Promise<{ task_id: string; node_id: string; status: string; rerun_nodes: string[] }> {
  const response = await apiClient.post<{
    task_id: string;
    node_id: string;
    status: string;
    rerun_nodes: string[];
  }>(`/tasks/${taskId}/nodes/${nodeId}/rerun`);
  return response.data;
}

export async function retryWorkflow(
  taskId: string
): Promise<{ task_id: string; status: string; failed_nodes: string[]; dag_hash?: string; workflow_hash?: string }> {
  const response = await apiClient.post<{
    task_id: string;
    status: string;
    failed_nodes: string[];
    dag_hash?: string;
    workflow_hash?: string;
  }>(`/tasks/${taskId}/retry`);
  return response.data;
}
