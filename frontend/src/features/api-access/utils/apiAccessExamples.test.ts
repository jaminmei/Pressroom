import { beforeEach, describe, expect, it } from "vitest";

import {
  buildCurlExample,
  buildPublicApiHealthPath,
  buildPublicWorkflowRunResultsPath,
  buildPublicWorkflowRunPath,
  buildPublicWorkflowRunsPath,
  buildPublicWorkflowRunStatusPath,
  buildPublicWorkflowUploadPath,
  buildUploadCurlExample,
} from "@/features/api-access/utils/apiAccessExamples";
import type { WorkflowImportExportPayload } from "@/services/workflowApi";

const ORIGIN = "http://localhost:5173";

beforeEach(() => {
  // jsdom default is http://localhost:3000 — pin so expectations are stable
  Object.defineProperty(window, "location", {
    value: { origin: ORIGIN },
    writable: true,
  });
});

describe("buildPublicWorkflowRunPath", () => {
  it("returns an absolute same-origin URL for a workflow id", () => {
    expect(buildPublicWorkflowRunPath("wf_invoice_extract")).toBe(
      `${ORIGIN}/api/v1/workflows/wf_invoice_extract/run`
    );
  });

  it("preserves arbitrary workflow ids without collapsing segments", () => {
    expect(buildPublicWorkflowRunPath("wf_123")).toBe(
      `${ORIGIN}/api/v1/workflows/wf_123/run`
    );
  });
});

describe("buildPublicWorkflowUploadPath", () => {
  it("returns the multipart upload URL for a workflow id", () => {
    expect(buildPublicWorkflowUploadPath("wf_invoice_extract")).toBe(
      `${ORIGIN}/api/v1/workflows/wf_invoice_extract/run/upload`
    );
  });
});

describe("public query endpoint builders", () => {
  it("returns the unauthenticated health URL", () => {
    expect(buildPublicApiHealthPath()).toBe(`${ORIGIN}/api/v1/health`);
  });

  it("returns status and results URLs with placeholder workflow_run_id by default", () => {
    expect(buildPublicWorkflowRunStatusPath()).toBe(
      `${ORIGIN}/api/v1/workflow-runs/{workflow_run_id}`
    );
    expect(buildPublicWorkflowRunResultsPath()).toBe(
      `${ORIGIN}/api/v1/workflow-runs/{workflow_run_id}/results`
    );
  });

  it("returns concrete status and results URLs when a run id is available", () => {
    expect(buildPublicWorkflowRunStatusPath("task_123")).toBe(
      `${ORIGIN}/api/v1/workflow-runs/task_123`
    );
    expect(buildPublicWorkflowRunResultsPath("task_123")).toBe(
      `${ORIGIN}/api/v1/workflow-runs/task_123/results`
    );
  });

  it("returns the paginated workflow run history URL", () => {
    expect(buildPublicWorkflowRunsPath("wf_invoice_extract")).toBe(
      `${ORIGIN}/api/v1/workflows/wf_invoice_extract/runs?page=1&limit=20`
    );
  });
});

describe("buildCurlExample", () => {
  it("uses the absolute public run path, Bearer header, and JSON content type", () => {
    const example = buildCurlExample("wf_invoice_extract", null, "dca_secret");

    expect(example).toContain(`curl -X POST ${ORIGIN}/api/v1/workflows/wf_invoice_extract/run`);
    expect(example).toContain("Authorization: Bearer dca_secret");
    expect(example).toContain("Content-Type: application/json");
  });

  it("falls back to the default placeholder when no key is provided", () => {
    const example = buildCurlExample("wf_invoice_extract", null);

    expect(example).toContain("Authorization: Bearer dca_...");
    expect(example).toContain(`${ORIGIN}/api/v1/workflows/wf_invoice_extract/run`);
  });

  it("keeps the curl on a single command using line continuations, not multiple commands", () => {
    const example = buildCurlExample("wf_invoice_extract", null, "dca_secret");

    expect(example.startsWith("curl -X POST ")).toBe(true);
    expect(example.trim().endsWith("'")).toBe(true);
  });

  it("emits a replaceable HTTPS URL when the definition has an input/* node with a file config", () => {
    const definition: WorkflowImportExportPayload = {
      nodes: [
        { id: "n1", type: "input/pdf", config: { file: "$file_0" } },
      ],
      connections: [],
    };
    const example = buildCurlExample("wf_invoice_extract", definition);

    expect(example).toContain('"https://example.com/document.pdf"');
    expect(example).not.toContain("/app/storage/");
    // body must nest "file" under "inputs" — top-level "file" is the old buggy shape
    expect(example).toContain('"inputs": {"file": "https://example.com/document.pdf"}');
    expect(example).not.toContain('{\n    "file":');
  });

  it("emits empty inputs when no input/file node is present", () => {
    const definition: WorkflowImportExportPayload = {
      // input/text with empty config — matches backend draft-node skip rule
      nodes: [{ id: "n1", type: "input/text", config: {} }],
      connections: [],
    };
    const example = buildCurlExample("wf_invoice_extract", definition);

    expect(example).toContain('"inputs": {}');
    expect(example).not.toContain('"file"');
  });

  it("emits empty inputs when definition is null/undefined", () => {
    const example = buildCurlExample("wf_invoice_extract", undefined);

    expect(example).toContain('"inputs": {}');
    // legacy unsupported fields must not appear
    expect(example).not.toContain('"user"');
    expect(example).not.toContain("https://example.com");
  });

  it("matches the first input/file node when several exist", () => {
    const definition: WorkflowImportExportPayload = {
      nodes: [
        { id: "n1", type: "input/image", config: { file: "a.png" } },
        { id: "n2", type: "input/pdf", config: { file: "b.pdf" } },
      ],
      connections: [],
    };
    const example = buildCurlExample("wf_invoice_extract", definition);

    // Multi-input workflows use the first file input as the canonical example.
    expect(example).toContain('"https://example.com/document.pdf"');
    // body must nest "file" under "inputs" — top-level "file" is the old buggy shape
    expect(example).toContain('"inputs": {"file": "https://example.com/document.pdf"}');
    expect(example).not.toContain('{\n    "file":');
  });
});

describe("buildUploadCurlExample", () => {
  it("uses the same-origin upload path, Bearer header, and -F file attachment", () => {
    const example = buildUploadCurlExample("wf_invoice_extract", "dca_secret");

    expect(example).toContain(
      `curl -X POST ${ORIGIN}/api/v1/workflows/wf_invoice_extract/run/upload`
    );
    expect(example).toContain("Authorization: Bearer dca_secret");
    expect(example).toContain('-F "file=@/path/to/your/document.pdf"');
  });

  it("emits no Content-Type header (-F lets curl set multipart automatically)", () => {
    const example = buildUploadCurlExample("wf_123");

    expect(example).not.toContain("Content-Type");
  });

  it("falls back to the default placeholder when no key is provided", () => {
    const example = buildUploadCurlExample("wf_abc");

    expect(example).toContain("Authorization: Bearer dca_...");
    expect(example).toContain(`${ORIGIN}/api/v1/workflows/wf_abc/run/upload`);
  });

  it("uses window.location.origin for the base URL", () => {
    const example = buildUploadCurlExample("wf_xyz");

    expect(example.startsWith(`curl -X POST ${ORIGIN}/`)).toBe(true);
  });

  it("produces a valid single curl command with line continuations", () => {
    const example = buildUploadCurlExample("wf_test");

    expect(example.startsWith("curl -X POST ")).toBe(true);
    const lines = example.split("\n");
    for (let i = 0; i < lines.length - 1; i++) {
      expect(lines[i].trimEnd().endsWith("\\")).toBe(true);
    }
  });
});
