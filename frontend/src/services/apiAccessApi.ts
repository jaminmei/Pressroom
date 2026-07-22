import { apiClient } from "@/services/api";

/**
 * API Access service.
 *
 * All calls hit the session-auth admin namespace at /admin/api-keys. The public
 * invocation URL (/api/v1/workflows/{id}/run) is display-only and lives in
 * apiAccessExamples.ts, not here.
 */

export interface ApiKeyRecord {
  id: string;
  key_prefix: string;
  workflow_id: string;
  description?: string | null;
  is_active: boolean;
  created_at?: string | null;
  last_used_at?: string | null;
  expires_at?: string | null;
}

export interface IssueApiKeyRequest {
  workflow_id: string;
  description?: string | null;
}

export interface IssueApiKeyResponse {
  id: string;
  /** Full secret; returned exactly once. Caller must persist immediately. */
  key: string;
  key_prefix: string;
  workflow_id: string;
  description?: string | null;
  created_at?: string | null;
}

interface ListApiKeysEnvelope {
  data?: ApiKeyRecord[];
  meta: { total: number; page: number; limit: number };
}

export interface RevokeApiKeyResponse {
  id: string;
  is_active: boolean;
}

export type ApiUsageRange = "24h" | "7d" | "30d";

export interface ApiUsageTrendPoint {
  date: string;
  calls: number;
  failures: number;
  avg_response_time_ms: number;
}

export interface ApiUsageSummary {
  range: ApiUsageRange;
  calls: number;
  success_rate: number;
  avg_response_time_ms: number;
  p95_response_time_ms: number;
  failures: number;
  storage_used_bytes: number;
  storage_limit_bytes: number;
  storage_over_limit: boolean;
  trend: ApiUsageTrendPoint[];
}

export interface ApiUsageRun {
  id: string;
  workflow_id: string;
  workflow_run_id?: string | null;
  api_key_id?: string | null;
  api_key_prefix?: string | null;
  api_key_description?: string | null;
  endpoint_kind: string;
  http_status?: number | null;
  workflow_status: string;
  response_time_ms?: number | null;
  input_metadata?: Record<string, unknown> | null;
  error?: Record<string, unknown> | null;
  storage_bytes: number;
  created_at: string;
  finished_at?: string | null;
  result_preview?: string | null;
  task_status?: string | null;
  completed_at?: string | null;
}

export interface ApiUsageRunsResponse {
  data: ApiUsageRun[];
  meta: { total: number; page: number; limit: number };
}

export interface ApiUsageTraceNodeStatus {
  node_id: string;
  node_type: string;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
}

export interface ApiUsageTrace {
  workflow_id: string;
  workflow_run_id: string;
  status: string;
  created_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  endpoint_kind: string;
  api_key_prefix?: string | null;
  input_metadata?: Record<string, unknown> | null;
  workflow?: {
    nodes: Array<Record<string, unknown>>;
    connections?: Array<Record<string, unknown>>;
    edges?: Array<Record<string, unknown>>;
  } | null;
  node_status: ApiUsageTraceNodeStatus[];
  event_count: number;
  result_preview?: string | null;
}

export async function listWorkflowApiKeys(
  workflowId: string,
  page?: number,
  limit?: number,
): Promise<{ data: ApiKeyRecord[]; meta: { total: number; page: number; limit: number } }> {
  const params: Record<string, string | number | boolean> = { workflow_id: workflowId, include_inactive: false };
  if (page !== undefined) params.page = page;
  if (limit !== undefined) params.limit = limit;
  const response = await apiClient.get<ListApiKeysEnvelope>("/admin/api-keys", { params });
  return {
    data: (response.data.data ?? []).filter((key) => key.workflow_id === workflowId),
    meta: response.data.meta,
  };
}

export async function issueWorkflowApiKey(payload: IssueApiKeyRequest): Promise<IssueApiKeyResponse> {
  const response = await apiClient.post<IssueApiKeyResponse>("/admin/api-keys", {
    workflow_id: payload.workflow_id,
    description: payload.description ?? null,
  });
  return response.data;
}

export async function revokeWorkflowApiKey(keyId: string): Promise<RevokeApiKeyResponse> {
  const response = await apiClient.post<RevokeApiKeyResponse>(`/admin/api-keys/${keyId}/revoke`);
  return response.data;
}

export async function getWorkflowApiUsageSummary(
  workflowId: string,
  range: ApiUsageRange = "7d",
): Promise<ApiUsageSummary> {
  const response = await apiClient.get<ApiUsageSummary>(
    `/admin/workflows/${workflowId}/api-usage/summary`,
    { params: { range } },
  );
  return response.data;
}

export async function listWorkflowApiUsageRuns(params: {
  workflowId: string;
  range?: ApiUsageRange;
  status?: string;
  keyId?: string;
  endpoint?: string;
  page?: number;
  limit?: number;
}): Promise<ApiUsageRunsResponse> {
  const response = await apiClient.get<ApiUsageRunsResponse>(
    `/admin/workflows/${params.workflowId}/api-usage/runs`,
    {
      params: {
        range: params.range ?? "7d",
        status: params.status || undefined,
        key_id: params.keyId || undefined,
        endpoint: params.endpoint || undefined,
        page: params.page,
        limit: params.limit,
      },
    },
  );
  return response.data;
}

export async function getWorkflowApiUsageTrace(
  workflowId: string,
  workflowRunId: string,
): Promise<ApiUsageTrace> {
  const response = await apiClient.get<ApiUsageTrace>(
    `/admin/workflows/${workflowId}/api-usage/runs/${workflowRunId}/trace`,
  );
  return response.data;
}
