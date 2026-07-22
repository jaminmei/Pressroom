// Centralize endpoint examples so the session-authenticated admin path and the
// public /api/v1 path cannot be confused. The Vite and nginx deployments both
// proxy /api on the same origin, so no separate display URL is required.

import type {
  WorkflowImportExportNode,
  WorkflowImportExportPayload,
} from "@/services/workflowApi";

/**
 * Public workflow run endpoint shown to operators and external integrators.
 * Absolute URL via window.location.origin. Display-only; it is not routed
 * through the session-authenticated API client.
 */
export function buildPublicWorkflowRunPath(workflowId: string): string {
  return `${window.location.origin}/api/v1/workflows/${workflowId}/run`;
}

/**
 * Public API liveness endpoint. This one is intentionally unauthenticated.
 */
export function buildPublicApiHealthPath(): string {
  return `${window.location.origin}/api/v1/health`;
}

/**
 * Public multipart upload endpoint for local file invocation.
 */
export function buildPublicWorkflowUploadPath(workflowId: string): string {
  return `${buildPublicWorkflowRunPath(workflowId)}/upload`;
}

/**
 * Public run status endpoint. The placeholder form is used for UI docs before
 * an integrator has a concrete workflow_run_id from /run or /run/upload.
 */
export function buildPublicWorkflowRunStatusPath(
  workflowRunId = "{workflow_run_id}",
): string {
  return `${window.location.origin}/api/v1/workflow-runs/${workflowRunId}`;
}

/**
 * Public run results endpoint for terminal workflow runs.
 */
export function buildPublicWorkflowRunResultsPath(
  workflowRunId = "{workflow_run_id}",
): string {
  return `${buildPublicWorkflowRunStatusPath(workflowRunId)}/results`;
}

/**
 * Public workflow run history endpoint.
 */
export function buildPublicWorkflowRunsPath(
  workflowId: string,
  page = 1,
  limit = 20,
): string {
  return `${window.location.origin}/api/v1/workflows/${workflowId}/runs?page=${page}&limit=${limit}`;
}

/**
 * Mirror app/api/public/workflow_runs.py:102-105 — return the first node whose
 * type starts with "input/" AND whose config has a "file" key. Both conditions
 * required: an input/text node with empty config is a draft, not an input source.
 */
function findInputFileNode(
  definition: WorkflowImportExportPayload | null | undefined,
): WorkflowImportExportNode | null {
  if (!definition?.nodes) return null;
  for (const n of definition.nodes) {
    if (
      typeof n.type === "string" &&
      n.type.startsWith("input/") &&
      n.config &&
      "file" in n.config
    ) {
      return n;
    }
  }
  return null;
}

/**
 * Copyable curl example for invoking a published workflow via the public API.
 * The key placeholder is intentionally non-secret; the operator pastes their
 * own issued key. Defaults to the masked `dca_...` placeholder.
 *
 * Body shape mirrors the backend's real input contract:
 *  - If the definition has an input/* node with a `file` config key, emit a
 *    `file` field pointing at a public HTTPS URL. Operators may replace it
 *    with another URL or with a path that is visible inside the backend.
 *  - Otherwise emit `"inputs": {}` (valid curl, empty inputs).
 */
export function buildCurlExample(
  workflowId: string,
  definition: WorkflowImportExportPayload | null | undefined,
  keyPlaceholder = "dca_...",
): string {
  // Multi-input workflows use the first file input in the copyable example.
  // Body must always carry the top-level `inputs` wrapper — backend's
  // RunWorkflowRequest (app/api/public/workflow_runs.py:61) only accepts
  // {inputs, user}; passing `{file}` at the top level fails Pydantic.
  const inputFileNode = findInputFileNode(definition);
  const body = inputFileNode
    ? `"inputs": {"file": "https://example.com/document.pdf"}`
    : `"inputs": {}`;

  return [
    `curl -X POST ${buildPublicWorkflowRunPath(workflowId)} \\`,
    `  -H "Authorization: Bearer ${keyPlaceholder}" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '{`,
    `    ${body}`,
    `  }'`,
  ].join("\n");
}

/**
 * Copyable curl example for file upload via the multipart upload endpoint.
 * Sends a local file as multipart/form-data — no JSON body, no Content-Type
 * header needed (curl sets it automatically with -F).
 */
export function buildUploadCurlExample(
  workflowId: string,
  keyPlaceholder = "dca_...",
): string {
  return [
    `curl -X POST ${buildPublicWorkflowUploadPath(workflowId)} \\`,
    `  -H "Authorization: Bearer ${keyPlaceholder}" \\`,
    `  -F "file=@/path/to/your/document.pdf"`,
  ].join("\n");
}
