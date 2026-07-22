export interface Project {
  id: string;
  name: string;
  description?: string;
  tags?: string[];
  documentCount: number;
  lastUpdated: string;
  createdAt: string;
}

export interface ProjectDocument {
  id: string;
  projectId: string;
  filename: string;
  type: string;
  size: number;
  uploadedAt: string;
  gtStatus: "none" | "pending" | "approved";
}

export interface ProjectRun {
  id: string;
  projectId: string;
  workflowId: string;
  workflowName: string;
  name?: string;
  status: "pending" | "running" | "completed" | "partial_completed" | "failed" | "cancelled";
  startedAt: string;
  completedAt?: string;
  duration?: number;
  documentCount: number;
  passRate?: number;
  results?: RunResult[];
}

export interface DocumentRunHistoryItem {
  runId: string;
  resultId: string;
  runName?: string;
  workflowId: string;
  workflowName?: string;
  runStatus: ProjectRun["status"];
  resultStatus: string;
  processingTimeMs?: number;
  error?: string;
  comparisonStatus?: string;
  reviewStatus?: string;
  createdAt: string;
  completedAt?: string;
  runDurationMs?: number;
}

export interface DocumentRunHistoryPage {
  items: DocumentRunHistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export type EvaluationResultExecutionStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "skipped";

export interface RunResult {
  id: string;
  runId: string;
  documentId: string;
  documentName: string;
  status:
    | "pass"
    | "differs"
    | "error"
    | "queued"
    | "running"
    | "completed"
    | "failed"
    | "skipped"
    | "no_gt"
    | "unknown";
  executionStatus: EvaluationResultExecutionStatus;
  hasGroundTruth: boolean;
  acceptedAsGT: boolean;
  rejected?: boolean;
  diff?: DiffField[];
}

export interface DiffField {
  fieldName: string;
  expected: string;
  actual: string;
  match: boolean;
}

export interface GTVersion {
  id: string;
  projectId: string;
  version: number;
  createdAt: string;
  documentCount: number;
  source: "manual" | "accepted_run";
}

export interface GroundTruthVersionSummary {
  id: string;
  projectId: string;
  documentId: string;
  version: number;
  source: string;
  format: string;
  notes?: string;
  createdAt: string;
  sourceTaskRunId?: string;
}

export interface DocumentGroundTruth extends GroundTruthVersionSummary {
  content: string;
}

export interface Workflow {
  id: string;
  name: string;
  description?: string;
}

export interface RunProgressItem {
  documentId: string;
  documentName: string;
  status: "pending" | "processing" | "complete" | "failed" | "skipped";
}
