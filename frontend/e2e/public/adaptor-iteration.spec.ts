import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import {
  applySession,
  authenticatedApi,
  expectStatus,
  provisionUser,
  requireBaseURL,
  uniqueLabel,
  useEnglish as selectEnglishLocale,
} from "./helpers/publicApi";

interface SavedWorkflowResponse {
  readonly success: boolean;
  readonly data: {
    readonly id: string;
    readonly workflow_key?: string | null;
  };
}

interface PublishWorkflowResponse {
  readonly success: boolean;
  readonly data: {
    readonly workflow_id: string;
    readonly workflow_key?: string | null;
    readonly version: number;
    readonly published_version: number;
  };
}

interface CreateTaskResponse {
  readonly task_id: string;
  readonly status: string;
}

interface TaskResultsResponse {
  readonly task_id: string;
  readonly status: string;
  readonly results: readonly {
    readonly node_id: string;
    readonly node_type: string;
    readonly content: string;
  }[];
}

interface NodeResultResponse {
  readonly node_id: string;
  readonly node_type: string;
  readonly status: string;
  readonly error?: string | null;
  readonly output?: {
    readonly text: string | null;
    readonly binary: readonly unknown[];
    readonly structured: Record<string, unknown> | null;
    readonly metadata: Record<string, unknown>;
  };
}

interface WorkflowDefinitionPayload {
  readonly nodes: readonly Record<string, unknown>[];
  readonly connections: readonly Record<string, unknown>[];
}

interface SaveWorkflowInput {
  readonly name: string;
  readonly description: string;
  readonly definition: WorkflowDefinitionPayload;
}

test("runs a real adaptor workflow with deterministic binary binding and renders the result page", async ({
  baseURL,
  page,
}) => {
  const appURL = requireBaseURL(baseURL);
  const user = await provisionUser(appURL, "adaptor-success");
  const api = await authenticatedApi(appURL, user);
  const fixturePath = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../fixtures/test-image.png",
  );
  const workflowName = `Adaptor ${uniqueLabel("public")}`;

  let workflowId: string | undefined;

  try {
    const saved = await saveWorkflow(api, {
      name: workflowName,
      description: "Deterministic public adaptor success workflow",
      definition: createAdaptorSuccessWorkflowDefinition(),
    });
    workflowId = saved.data.id;

    await publishWorkflow(api, workflowId);
    const createdTask = await runWorkflowFromUi(page, user, workflowId, fixturePath);
    await waitForTaskTerminal(page, createdTask.task_id, "completed");

    const adaptorResult = await getNodeResult(page, createdTask.task_id, "adaptor_1");
    const finalResults = await getTaskResults(page, createdTask.task_id);

    expect(adaptorResult.status).toBe("completed");
    expect(adaptorResult.node_type).toBe("processor/adaptor");
    expect(adaptorResult.output?.structured).toMatchObject({
      summary: "adaptor-ok",
      file_count: 1,
      mime_type: "image/png",
      final_marker: "adaptor-success-final",
    });
    expect(adaptorResult.output?.metadata.processing_time_ms).toBeGreaterThanOrEqual(0);
    expect(JSON.stringify(adaptorResult.output?.structured ?? {})).not.toContain("AQID");

    await assertResultPage(page, createdTask.task_id, { allowStructuredOnlyView: true });
    expect(finalResults.status).toBe("completed");
    expect(finalResults.results).toHaveLength(1);
    expect(finalResults.results[0]?.content).toContain("adaptor-success-final");
  } finally {
    await cleanupWorkflow(api, workflowId);
    await api.dispose();
  }
});

test("runs a real sequential iteration workflow with an inner adaptor and deterministic metadata", async ({
  baseURL,
  page,
}) => {
  const appURL = requireBaseURL(baseURL);
  const user = await provisionUser(appURL, "iteration-success");
  const api = await authenticatedApi(appURL, user);
  const fixturePath = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../fixtures/test-image.png",
  );
  const workflowName = `Iteration ${uniqueLabel("public")}`;

  let workflowId: string | undefined;

  try {
    const saved = await saveWorkflow(api, {
      name: workflowName,
      description: "Deterministic public iteration workflow",
      definition: createIterationWorkflowDefinition(),
    });
    workflowId = saved.data.id;

    await publishWorkflow(api, workflowId);
    const createdTask = await runWorkflowFromUi(page, user, workflowId, fixturePath);
    await waitForTaskTerminal(page, createdTask.task_id, "completed");

    const iterationResult = await getNodeResult(page, createdTask.task_id, "iter_1");
    const finalResults = await getTaskResults(page, createdTask.task_id);

    expect(iterationResult.status).toBe("completed");
    expect(iterationResult.node_type).toBe("processor/iteration");
    expect(iterationResult.output?.structured).toMatchObject({
      kind: "iteration_result",
      total: 1,
      success_count: 1,
      error_count: 0,
      items: [
        {
          index: 0,
          status: "success",
          error: null,
        },
      ],
    });
    expect(iterationResult.output?.metadata).toMatchObject({
      iteration_count: 1,
      mode: "sequential",
      engine: "processor/adaptor",
    });

    const structured = iterationResult.output?.structured as {
      items?: Array<{ output?: { structured?: Record<string, unknown> } }>;
    };
    expect(structured.items?.[0]?.output?.structured).toMatchObject({
      item_index: 0,
      mime_type: "image/png",
    });

    await assertResultPage(page, createdTask.task_id, { allowStructuredOnlyView: true });
    expect(finalResults.status).toBe("completed");
    expect(finalResults.results).toHaveLength(1);
    expect(finalResults.results[0]?.content).toContain("iteration_result");
  } finally {
    await cleanupWorkflow(api, workflowId);
    await api.dispose();
  }
});

test("fails deterministically when adaptor code raises a safe runtime error", async ({
  baseURL,
  page,
}) => {
  const appURL = requireBaseURL(baseURL);
  const user = await provisionUser(appURL, "adaptor-failure");
  const api = await authenticatedApi(appURL, user);
  const fixturePath = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../fixtures/test-image.png",
  );
  const workflowName = `Adaptor failure ${uniqueLabel("public")}`;

  let workflowId: string | undefined;

  try {
    const saved = await saveWorkflow(api, {
      name: workflowName,
      description: "Deterministic public adaptor failure workflow",
      definition: createAdaptorFailureWorkflowDefinition(),
    });
    workflowId = saved.data.id;

    await publishWorkflow(api, workflowId);
    const createdTask = await runWorkflowFromUi(page, user, workflowId, fixturePath);
    await waitForTaskTerminal(page, createdTask.task_id, "failed");

    const adaptorResult = await getNodeResult(page, createdTask.task_id, "adaptor_1");
    expect(adaptorResult.status).toBe("failed");
    expect(adaptorResult.node_type).toBe("processor/adaptor");
    expect(adaptorResult.error).toBeTruthy();
    expect(adaptorResult.error).not.toContain("safe deterministic adaptor failure");
    expect(adaptorResult.error).not.toContain("Traceback");
    expect(adaptorResult.error).not.toContain("File \"");

    await page.goto(`/tasks/${createdTask.task_id}/results`);
    await expect(page).toHaveURL(new RegExp(`/tasks/${createdTask.task_id}/results$`));
    await expect(page.getByText(/failed/i)).toBeVisible();
    await expect(page.getByText(/Traceback/)).toHaveCount(0);
    await expect(page.getByText(/safe deterministic adaptor failure/)).toHaveCount(0);
  } finally {
    await cleanupWorkflow(api, workflowId);
    await api.dispose();
  }
});

async function saveWorkflow(
  api: APIRequestContext,
  payload: SaveWorkflowInput,
): Promise<SavedWorkflowResponse> {
  const response = await api.post("/api/workflows/save", {
    data: payload,
  });
  await expectStatus(response, 200);
  const saved = (await response.json()) as SavedWorkflowResponse;
  expect(saved.success).toBe(true);
  expect(saved.data.id).toBeTruthy();
  return saved;
}

async function publishWorkflow(
  api: APIRequestContext,
  workflowId: string,
): Promise<PublishWorkflowResponse> {
  const response = await api.post(`/api/workflows/${workflowId}/publish`);
  await expectStatus(response, 200);
  const published = (await response.json()) as PublishWorkflowResponse;
  expect(published.success).toBe(true);
  expect(published.data.workflow_id).toBe(workflowId);
  expect(published.data.version).toBeGreaterThanOrEqual(1);
  return published;
}

async function cleanupWorkflow(
  api: APIRequestContext,
  workflowId: string | undefined,
): Promise<void> {
  if (!workflowId) {
    return;
  }
  const response = await api.delete(`/api/workflows/${workflowId}`);
  expect([200, 404]).toContain(response.status());
}

async function runWorkflowFromUi(
  page: Page,
  user: Awaited<ReturnType<typeof provisionUser>>,
  workflowId: string,
  fixturePath: string,
): Promise<CreateTaskResponse> {
  if (!fs.existsSync(fixturePath)) {
    throw new Error(`Missing public adaptor fixture: ${fixturePath}`);
  }

  await selectEnglishLocale(page);
  await applySession(page.context(), user);
  await page.goto(`/workflows/${workflowId}`);
  await expect(page.getByTestId("workflow-editor-page")).toBeVisible();

  await page.locator(".workflow-node-card", { hasText: /Image Input|圖片輸入/ }).first().click();
  await page.locator('input[type="file"]').first().setInputFiles(fixturePath);

  const runButton = page.getByTestId("floating-btn-run");
  await expect(runButton).toBeEnabled();
  const runDialog = page.getByRole("dialog", { name: "Name this Run" });
  await runButton.click();
  if (!(await runDialog.isVisible())) {
    await expect(page.getByText("Validation passed", { exact: false })).toBeVisible();
    await runButton.click();
  }
  await expect(runDialog).toBeVisible();

  const createTaskResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/api/tasks") && response.request().method() === "POST",
  );
  await runDialog.getByRole("button", { name: "Execute", exact: true }).click();
  const createTaskResponse = await createTaskResponsePromise;
  expect(createTaskResponse.status()).toBe(202);
  return (await createTaskResponse.json()) as CreateTaskResponse;
}

async function waitForTaskTerminal(
  page: Page,
  taskId: string,
  expectedStatus: "completed" | "failed",
): Promise<void> {
  await expect
    .poll(
      async () => {
        const statusResponse = await page.request.get(`/api/tasks/${taskId}`);
        await expectStatus(statusResponse, 200);
        return ((await statusResponse.json()) as { status: string }).status;
      },
      { timeout: 180_000, intervals: [500, 1_000, 2_000] },
    )
    .toBe(expectedStatus);
}

async function getNodeResult(
  page: Page,
  taskId: string,
  nodeId: string,
): Promise<NodeResultResponse> {
  const response = await page.request.get(`/api/tasks/${taskId}/nodes/${nodeId}/result`);
  await expectStatus(response, 200);
  return (await response.json()) as NodeResultResponse;
}

async function getTaskResults(
  page: Page,
  taskId: string,
): Promise<TaskResultsResponse> {
  const response = await page.request.get(`/api/tasks/${taskId}/results`);
  await expectStatus(response, 200);
  return (await response.json()) as TaskResultsResponse;
}

async function assertResultPage(
  page: Page,
  taskId: string,
  options?: { allowStructuredOnlyView?: boolean },
): Promise<void> {
  await page.goto(`/tasks/${taskId}/results`);
  await expect(page).toHaveURL(new RegExp(`/tasks/${taskId}/results$`));
  if (options?.allowStructuredOnlyView) {
    await expect(page.locator("main")).toBeVisible();
    await expect(page.locator(".ant-alert-error")).toHaveCount(0);
    return;
  }
  await expect(page.getByRole("heading", { name: "Conversion Result" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Download Markdown" })).toBeVisible();
  await expect(page.locator(".ant-alert-error")).toHaveCount(0);
}

function createAdaptorSuccessWorkflowDefinition(): WorkflowDefinitionPayload {
  return {
    nodes: [
      {
        id: "input_1",
        type: "input/image",
        config: { file: "$file_0" },
        position: { x: 40, y: 40 },
      },
      {
        id: "adaptor_1",
        type: "processor/adaptor",
        config: {
          code: [
            "def main(inputs):",
            "    image = inputs['image']",
            "    binary = image.get('binary') or []",
            "    first = binary[0] if binary else {}",
            "    metadata = image.get('metadata') or {}",
            "    return {",
            "        'text': 'adaptor-success-final',",
            "        'structured': {",
            "            'summary': 'adaptor-ok',",
            "            'file_count': len(binary),",
            "            'filename': metadata.get('filename'),",
            "            'mime_type': first.get('mime_type'),",
            "            'size_bytes': first.get('size_bytes'),",
            "            'final_marker': 'adaptor-success-final',",
            "        }",
            "    }",
          ].join("\n"),
          input_mode: "custom_bindings",
          input_bindings: [{ name: "image", selector: ["input_1", "binary"] }],
        },
        position: { x: 300, y: 40 },
      },
      {
        id: "end_1",
        type: "end/final",
        config: {},
        position: { x: 560, y: 40 },
      },
    ],
    connections: [
      {
        source: "input_1",
        target: "adaptor_1",
        target_port: "input",
      },
      {
        source: "adaptor_1",
        target: "end_1",
        target_port: "input",
      },
    ],
  };
}

function createIterationWorkflowDefinition(): WorkflowDefinitionPayload {
  return {
    nodes: [
      {
        id: "input_1",
        type: "input/image",
        config: { file: "$file_0" },
        position: { x: 40, y: 40 },
      },
      {
        id: "iter_1",
        type: "processor/iteration",
        config: {
          engine_node_type: "processor/adaptor",
          engine_config: {
            code: [
              "def main(inputs):",
              "    item = inputs['item']",
              "    index = inputs['index']",
              "    binary = item.get('binary') or []",
              "    first = binary[0] if binary else {}",
              "    metadata = item.get('metadata') or {}",
              "    value = ((index.get('structured') or {}).get('value'))",
              "    return {",
              "        'structured': {",
              "            'item_name': metadata.get('filename'),",
              "            'item_index': value,",
              "            'mime_type': first.get('mime_type'),",
              "            'size_bytes': first.get('size_bytes'),",
              "        }",
              "    }",
            ].join("\n"),
            input_mode: "custom_bindings",
            input_bindings: [
              { name: "item", selector: ["iter_1", "item"] },
              { name: "index", selector: ["iter_1", "index"] },
            ],
          },
          iterate_over: "binary",
          item_input_port: "image",
          mode: "sequential",
          max_concurrency: 1,
          error_handling: "terminate",
        },
        position: { x: 300, y: 40 },
      },
      {
        id: "end_1",
        type: "end/final",
        config: {},
        position: { x: 560, y: 40 },
      },
    ],
    connections: [
      {
        source: "input_1",
        target: "iter_1",
        target_port: "input",
      },
      {
        source: "iter_1",
        target: "end_1",
        target_port: "input",
      },
    ],
  };
}

function createAdaptorFailureWorkflowDefinition(): WorkflowDefinitionPayload {
  return {
    nodes: [
      {
        id: "input_1",
        type: "input/image",
        config: { file: "$file_0" },
        position: { x: 40, y: 40 },
      },
      {
        id: "adaptor_1",
        type: "processor/adaptor",
        config: {
          code: [
            "def main(inputs):",
            "    _ = inputs['image']",
            "    raise RuntimeError('safe deterministic adaptor failure')",
          ].join("\n"),
          input_mode: "custom_bindings",
          input_bindings: [{ name: "image", selector: ["input_1", "binary"] }],
        },
        position: { x: 300, y: 40 },
      },
      {
        id: "end_1",
        type: "end/final",
        config: {},
        position: { x: 560, y: 40 },
      },
    ],
    connections: [
      {
        source: "input_1",
        target: "adaptor_1",
        target_port: "input",
      },
      {
        source: "input_1",
        target: "end_1",
        target_port: "input",
      },
    ],
  };
}
