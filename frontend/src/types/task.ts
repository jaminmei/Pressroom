export type TaskStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type NodeExecutionStatus = TaskStatus | "skipped" | "awaiting_input" | "awaiting_user_input";

export interface BlockDetectionBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface BlockSelectionSourceImage {
  image_id: string;
  page_number: number;
  width: number;
  height: number;
  preview_url: string;
}

export interface BlockSelectionCandidate {
  block_id: string;
  type: string;
  bbox: BlockDetectionBox;
  confidence: number;
  label?: string;
}

export interface BlockSelectionPayload {
  source_image: BlockSelectionSourceImage;
  blocks: BlockSelectionCandidate[];
  summary?: {
    total_blocks: number;
    by_type?: Record<string, number>;
  };
}

export interface BlockSelectionRequest {
  node_id: string;
  node_type: string;
  input_type: "block_selection";
  payload: BlockSelectionPayload;
}

export interface SelectedBlockInput {
  block_id: string;
  engine: string;
  engine_config?: Record<string, unknown>;
}

export interface SubmitBlockSelectionPayload {
  input_type: "block_selection";
  payload: {
    source_image_id: string;
    selected_blocks: SelectedBlockInput[];
  };
}

export interface TaskProgress {
  total_nodes: number;
  completed_nodes: number;
  failed_nodes: number;
  pending_nodes: number;
  current_node: string | null;
  percentage: number;
}

export interface TaskNodeProgress {
  current_page: number;
  total_pages: number;
  percentage: number;
}

export interface TaskNodeStatus {
  node_id: string;
  node_type: string;
  status: NodeExecutionStatus;
  started_at: string | null;
  completed_at: string | null;
  output_preview?: Record<string, unknown>;
  progress?: TaskNodeProgress;
}

export interface CreateTaskResponse {
  task_id: string;
  run_name?: string;
  status: TaskStatus;
  created_at?: string;
  dag_hash?: string;
  input_files?: TaskInputFileIdentity[];
}

export interface TaskStatusResponse {
  task_id: string;
  status: TaskStatus;
  created_at?: string;
  updated_at?: string;
  progress?: TaskProgress;
  node_status?: TaskNodeStatus[];
  node_states?: Record<string, TaskNodeStatus>;
  dag_hash?: string;
  input_files?: TaskInputFileIdentity[];
  workflow?: {
    nodes: Array<{ id: string; type: string; config?: Record<string, unknown>; [key: string]: unknown }>;
    connections: Array<{ source: string; target: string; source_port?: string; target_port?: string; [key: string]: unknown }>;
  };
}

export interface TaskResultFile {
  filename: string;
  size_bytes: number;
  content_type: string;
  download_url: string;
}

export interface TaskResultMetadata {
  processing_time_ms: number;
  page_count: number;
  char_count: number;
  word_count: number;
}

export type TaskResultDownloadFormat = "markdown" | "text" | "yaml";

export interface TaskResult {
  result_id: string;
  node_id: string;
  node_type: string;
  status: NodeExecutionStatus;
  engine_name?: string;
  execution_time_ms?: number;
  result_preview?: string;
  char_count?: number;
  formats?: Partial<Record<TaskResultDownloadFormat, string>>;
  file: TaskResultFile;
  metadata: TaskResultMetadata;
  content: string;
}

export interface TaskResultsSummary {
  total_outputs: number;
  completed: number;
  failed: number;
}

export interface TaskResultsResponse {
  task_id: string;
  status: TaskStatus;
  results: TaskResult[];
  summary?: TaskResultsSummary;
}

export interface TaskHistoryItem {
  task_id: string;
  workflow_id?: string;
  workflow_name?: string;
  run_name?: string;
  status: TaskStatus;
  started_at: string;
  completed_at?: string;
  result_preview?: string;
  dag_hash?: string;
  input_files?: TaskInputFileIdentity[];
}

export interface TaskInputFileIdentity {
  name: string;
  size: number;
}

export interface TaskHistoryMeta {
  total: number;
  page: number;
  limit: number;
}

export interface TaskHistoryResponse {
  items: TaskHistoryItem[];
  meta?: TaskHistoryMeta;
}

export interface TaskResultRouteParams {
  taskId: string;
}
