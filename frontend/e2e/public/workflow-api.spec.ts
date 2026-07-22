import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, request as playwrightRequest, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import {
  authenticatedApi,
  expectStatus,
  provisionUser,
  requireBaseURL,
  uniqueLabel
} from "./helpers/publicApi";

interface PublishWorkflowResponse {
  readonly success: boolean;
  readonly data: {
    readonly workflow_id: string;
    readonly workflow_key: string;
    readonly version: number;
    readonly dag_hash: string;
  };
}

interface IssueApiKeyResponse {
  readonly id: string;
  readonly key: unknown;
  readonly key_prefix: string;
  readonly workflow_id: string;
  readonly description: string;
  readonly created_at: string;
}

interface WorkflowResult {
  readonly result_id: string;
  readonly format: string;
  readonly file: {
    readonly filename: string;
    readonly size_bytes: number;
    readonly content_type: string;
    readonly download_url: string;
  };
  readonly content: string;
  readonly metadata: {
    readonly filename: string;
    readonly mime_type: string;
    readonly size_bytes: number;
  };
}

interface UploadedImageOutput {
  readonly text: null;
  readonly binary: readonly {
    readonly ref: string;
    readonly mime_type: string;
    readonly size_bytes: number;
    readonly dimensions: null;
  }[];
  readonly structured: null;
  readonly metadata: {
    readonly filename: string;
    readonly mime_type: string;
    readonly size_bytes: number;
  };
}

interface RunUploadResponse {
  readonly workflow_run_id: string;
  readonly status: string;
  readonly inputs: {
    readonly file: string;
    readonly user: string;
  };
  readonly outputs: {
    readonly text: string;
    readonly results: readonly WorkflowResult[];
  };
  readonly elapsed_time_ms: number;
  readonly total_steps: number;
  readonly created_at: string;
  readonly finished_at: string;
}

interface RunStatusResponse {
  readonly workflow_run_id: string;
  readonly workflow_id: string;
  readonly status: string;
  readonly elapsed_time_ms: number;
  readonly total_steps: number;
  readonly created_at: string;
  readonly finished_at: string;
}

interface RunResultsResponse {
  readonly workflow_run_id: string;
  readonly status: string;
  readonly results: readonly WorkflowResult[];
}

interface WorkflowRunHistoryResponse {
  readonly data: readonly {
    readonly workflow_run_id: string;
    readonly status: string;
    readonly created_at: string;
    readonly finished_at: string;
    readonly elapsed_time_ms: number;
  }[];
  readonly meta: {
    readonly total: number;
    readonly page: number;
    readonly limit: number;
  };
}

function expectIsoTimestamp(value: string): void {
  expect(Number.isNaN(Date.parse(value))).toBe(false);
}

test("runs a published workflow through the cookie-free public API", async ({ baseURL }) => {
  const appURL = requireBaseURL(baseURL);
  const user = await provisionUser(appURL, "workflow-api");
  const sessionApi = await authenticatedApi(appURL, user);
  const fixturePath = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../fixtures/test-image.png"
  );
  if (!fs.existsSync(fixturePath)) {
    await sessionApi.dispose();
    throw new Error(`Missing public API fixture: ${fixturePath}`);
  }
  const fixture = fs.readFileSync(fixturePath);

  let publicApi: APIRequestContext | undefined;
  let apiKeyId: string | undefined;

  try {
    const publishResponse = await sessionApi.post("/api/workflows/publish", {
      data: {
        name: `Public API ${uniqueLabel("workflow")}`,
        description: "Synthetic public API Playwright smoke workflow",
        definition: {
          nodes: [
            {
              id: "input_image",
              type: "input/image",
              config: { file: "$file_0" }
            },
            { id: "final", type: "end/final", config: {} }
          ],
          connections: [
            {
              source: "input_image",
              target: "final",
              target_port: "input"
            }
          ]
        }
      }
    });
    await expectStatus(publishResponse, 201);
    const published = (await publishResponse.json()) as PublishWorkflowResponse;
    expect(published.success).toBe(true);
    expect(published.data.workflow_id).toMatch(/^wf_[0-9a-f-]{36}$/);
    expect(published.data.workflow_key).toMatch(/^wk_[0-9a-f-]{36}$/);
    expect(published.data.version).toBe(1);
    expect(published.data.dag_hash).toMatch(/^[0-9a-f]{64}$/);

    const keyDescription = `Playwright ${uniqueLabel("public-api-key")}`;
    const issueKeyResponse = await sessionApi.post("/api/admin/api-keys", {
      data: {
        workflow_id: published.data.workflow_id,
        description: keyDescription
      }
    });
    await expectStatus(issueKeyResponse, 201);
    const issued = (await issueKeyResponse.json()) as IssueApiKeyResponse;
    expect(issued.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(issued.workflow_id).toBe(published.data.workflow_id);
    expect(issued.description).toBe(keyDescription);
    expectIsoTimestamp(issued.created_at);
    if (typeof issued.key !== "string" || issued.key.length === 0) {
      throw new Error("API key issuance response did not contain a usable key");
    }
    const fullKey = issued.key;
    expect(fullKey.startsWith("dca_")).toBe(true);
    expect(fullKey.length).toBeGreaterThan(30);
    expect(issued.key_prefix).toBe(fullKey.slice(0, 12));
    apiKeyId = issued.id;

    publicApi = await playwrightRequest.newContext({
      baseURL: appURL,
      extraHTTPHeaders: { Authorization: `Bearer ${fullKey}` }
    });
    expect((await publicApi.storageState()).cookies).toHaveLength(0);

    const runResponse = await publicApi.post(
      `/api/v1/workflows/${published.data.workflow_id}/run/upload`,
      {
        multipart: {
          file: {
            name: "test-image.png",
            mimeType: "image/png",
            buffer: fixture
          },
          options: JSON.stringify({ user: "public-api-playwright" })
        }
      }
    );
    await expectStatus(runResponse, 200);
    const run = (await runResponse.json()) as RunUploadResponse;
    expect(run.workflow_run_id).toMatch(/^task_[0-9a-f]{12}$/);
    expect(run.status).toBe("succeeded");
    expect(run.inputs.file).toMatch(/test-image\.png$/);
    expect(run.inputs.user).toBe("public-api-playwright");
    expect(run.elapsed_time_ms).toBeGreaterThanOrEqual(0);
    expect(run.total_steps).toBeGreaterThan(0);
    expectIsoTimestamp(run.created_at);
    expectIsoTimestamp(run.finished_at);
    expect(run.outputs.results).toHaveLength(1);

    const [result] = run.outputs.results;
    expect(result.result_id).toBe(`r_${run.workflow_run_id}_input_image`);
    expect(result.format).toBe("json");
    expect(result.file.filename).toBe("input_image_output.json");
    expect(result.file.content_type).toBe("application/json");
    expect(result.file.size_bytes).toBe(Buffer.byteLength(result.content));
    expect(result.file.download_url).toBe(
      `/api/tasks/${run.workflow_run_id}/results/${result.result_id}/download`
    );
    expect(result.metadata).toEqual({
      filename: "test-image.png",
      mime_type: "image/png",
      size_bytes: fixture.length
    });
    expect(run.outputs.text).toBe(result.content);

    const uploadedOutput = JSON.parse(result.content) as UploadedImageOutput;
    expect(uploadedOutput.text).toBeNull();
    expect(uploadedOutput.structured).toBeNull();
    expect(uploadedOutput.binary).toHaveLength(1);
    expect(uploadedOutput.binary[0]).toMatchObject({
      mime_type: "image/png",
      size_bytes: fixture.length,
      dimensions: null
    });
    expect(uploadedOutput.binary[0]?.ref).toMatch(/test-image\.png$/);
    expect(uploadedOutput.metadata).toEqual(result.metadata);

    const statusResponse = await publicApi.get(`/api/v1/workflow-runs/${run.workflow_run_id}`);
    await expectStatus(statusResponse, 200);
    const status = (await statusResponse.json()) as RunStatusResponse;
    expect(status).toEqual({
      workflow_run_id: run.workflow_run_id,
      workflow_id: published.data.workflow_id,
      status: "completed",
      elapsed_time_ms: run.elapsed_time_ms,
      total_steps: run.total_steps,
      created_at: run.created_at,
      finished_at: run.finished_at
    });

    const resultsResponse = await publicApi.get(
      `/api/v1/workflow-runs/${run.workflow_run_id}/results`
    );
    await expectStatus(resultsResponse, 200);
    const results = (await resultsResponse.json()) as RunResultsResponse;
    expect(results).toEqual({
      workflow_run_id: run.workflow_run_id,
      status: "succeeded",
      results: run.outputs.results
    });

    const historyResponse = await publicApi.get(
      `/api/v1/workflows/${published.data.workflow_id}/runs?page=1&limit=10`
    );
    await expectStatus(historyResponse, 200);
    const history = (await historyResponse.json()) as WorkflowRunHistoryResponse;
    expect(history.meta).toEqual({ total: 1, page: 1, limit: 10 });
    expect(history.data).toEqual([
      {
        workflow_run_id: run.workflow_run_id,
        status: "completed",
        created_at: run.created_at,
        finished_at: run.finished_at,
        elapsed_time_ms: run.elapsed_time_ms
      }
    ]);
  } finally {
    try {
      if (apiKeyId !== undefined) {
        const revokeResponse = await sessionApi.post(`/api/admin/api-keys/${apiKeyId}/revoke`);
        await expectStatus(revokeResponse, 200);
        expect(await revokeResponse.json()).toEqual({
          id: apiKeyId,
          is_active: false
        });
      }
    } finally {
      await publicApi?.dispose();
      await sessionApi.dispose();
    }
  }
});
