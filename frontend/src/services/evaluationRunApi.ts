import { apiClient } from "@/services/api";
import { useWorkspaceStore } from "@/stores/workspaceStore";

export interface EvaluationRunRequestContext {
  readonly workspaceId: string | null;
  readonly generation: number;
}

export function captureEvaluationRunRequestContext(): EvaluationRunRequestContext {
  const state = useWorkspaceStore.getState();
  return {
    workspaceId: state.currentWorkspace?.id ?? null,
    generation: state.contextGeneration
  };
}

export function isEvaluationRunRequestContextCurrent(context: EvaluationRunRequestContext): boolean {
  const state = useWorkspaceStore.getState();
  return (
    context.workspaceId === (state.currentWorkspace?.id ?? null) &&
    context.generation === state.contextGeneration
  );
}

export type EvaluationRunStatus =
  | "pending"
  | "running"
  | "completed"
  | "partial_completed"
  | "failed"
  | "cancelled";
export type EvaluationResultStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "skipped";

export const EVALUATION_RUN_TERMINAL_STATUSES: ReadonlySet<EvaluationRunStatus> = new Set([
  "completed",
  "partial_completed",
  "failed",
  "cancelled",
]);

export function isEvaluationRunTerminalStatus(status: string): boolean {
  return (EVALUATION_RUN_TERMINAL_STATUSES as ReadonlySet<string>).has(status);
}

export function generateClientRequestId(): string {
  const buffer = new Uint8Array(16);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(buffer);
  } else {
    for (let i = 0; i < buffer.length; i += 1) {
      buffer[i] = Math.floor(Math.random() * 256);
    }
  }
  const hex = Array.from(buffer, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `cli_req_${hex}`;
}

export interface CreateEvaluationRunPayload {
  workflow_id: string;
  name?: string;
  document_ids?: string[];
  client_request_id?: string;
}

export interface EvaluationRun {
  id: string;
  name: string | null;
  test_set_id: string;
  workflow_id: string;
  workflow_version: number | null;
  status: EvaluationRunStatus;
  total_documents: number;
  completed_count: number;
  failed_count: number;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface EvaluationRunResultsSummary {
  total: number;
  completed: number;
  failed: number;
  queued: number;
  running: number;
  skipped: number;
}

export interface EvaluationRunResultListItem {
  id: string;
  document_id: string;
  filename: string | null;
  status: EvaluationResultStatus;
  processing_time_ms: number | null;
  output_format: string | null;
  error: string | null;
}

export interface EvaluationRunResultsResponse {
  evaluation_run_id: string;
  status: EvaluationRunStatus;
  summary: EvaluationRunResultsSummary;
  results: EvaluationRunResultListItem[];
}

export interface EvaluationRunResultDetail {
  id: string;
  evaluation_run_id: string;
  document_id: string;
  filename: string | null;
  task_run_id: string | null;
  status: EvaluationResultStatus;
  output_content: string | null;
  output_format: string | null;
  processing_time_ms: number | null;
  created_at: string;
  error: string | null;
}

export async function createEvaluationRun(
  testSetId: string,
  payload: CreateEvaluationRunPayload
): Promise<EvaluationRun> {
  const response = await apiClient.post<EvaluationRun>(`/test-sets/${testSetId}/evaluation-runs`, payload);
  return response.data;
}

export async function getEvaluationRun(runId: string): Promise<EvaluationRun> {
  const response = await apiClient.get<EvaluationRun>(`/evaluation-runs/${runId}`);
  return response.data;
}

export async function getEvaluationRunResults(runId: string): Promise<EvaluationRunResultsResponse> {
  const response = await apiClient.get<EvaluationRunResultsResponse>(`/evaluation-runs/${runId}/results`);
  return response.data;
}

export async function getEvaluationResultDetail(
  runId: string,
  resultId: string
): Promise<EvaluationRunResultDetail> {
  const response = await apiClient.get<EvaluationRunResultDetail>(
    `/evaluation-runs/${runId}/results/${resultId}`
  );
  return response.data;
}
