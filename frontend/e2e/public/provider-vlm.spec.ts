import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";

import {
  applySession,
  expectStatus,
  provisionUser,
  requireBaseURL,
  uniqueLabel,
  useEnglish,
} from "./helpers/publicApi";

const VLM_MOCK_BASE_URL = "http://vlm-mock:8080";
const VLM_MOCK_CONTROL_URL = (
  process.env.PW_VLM_MOCK_CONTROL_URL?.trim()
  || process.env.VLM_MOCK_URL?.trim()
  || "http://127.0.0.1:18080"
).replace(/\/$/, "");
const AZURE_API_VERSION = "2025-04-01-preview";

interface ProviderResponse {
  readonly id: string;
  readonly name: string;
  readonly api_style: "openai" | "azure_openai" | null;
  readonly api_version: string | null;
  readonly base_url: string;
}

interface DiscoverResponse {
  readonly added: number;
  readonly discovery_supported: boolean;
  readonly message: string | null;
}

interface CreateTaskResponse {
  readonly task_id: string;
  readonly status: string;
}

interface TaskResultsResponse {
  readonly task_id: string;
  readonly status: string;
  readonly results: readonly { readonly content: string }[];
}

interface MockRequest {
  readonly path: string;
  readonly has_image: boolean;
  readonly has_api_key_header: boolean;
  readonly api_version: string | null;
}

interface MockRequestsResponse {
  readonly requests: readonly MockRequest[];
}

function providerCard(page: Page, name: string): Locator {
  return page
    .getByText(name, { exact: true })
    .locator("xpath=ancestor::div[contains(@class, 'ant-card')][1]");
}

async function createProvider(
  page: Page,
  values: {
    readonly name: string;
    readonly style: "openai" | "azure_openai";
    readonly baseURL: string;
  },
): Promise<ProviderResponse> {
  await page.getByRole("button", { name: "Add Provider" }).click();
  const dialog = page.getByRole("dialog", { name: "Add Model Provider" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Name").fill(values.name);

  if (values.style === "azure_openai") {
    await dialog.locator("#api_style")
      .locator("xpath=ancestor::div[contains(@class, 'ant-select-selector')]")
      .click();
    await page
      .locator(".ant-select-dropdown:visible .ant-select-item-option", { hasText: "Azure OpenAI" })
      .click();
    await dialog.getByLabel("Azure API Version").fill(AZURE_API_VERSION);
  }

  await dialog.getByLabel("Base URL").fill(values.baseURL);
  await dialog.getByLabel("API Key").fill("public-mock-key");
  const responsePromise = page.waitForResponse((response) =>
    response.url().endsWith("/api/providers") && response.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: "Create", exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(201);
  return (await response.json()) as ProviderResponse;
}

async function addModelManually(page: Page, providerName: string, modelId: string): Promise<void> {
  const card = providerCard(page, providerName);
  await card.getByRole("button", { name: "Show Models" }).click();
  await card.getByRole("button", { name: "Add Model" }).click();
  const dialog = page.getByRole("dialog", { name: "Add Model" });
  await dialog.getByPlaceholder("e.g. vision-model").fill(modelId);
  const responsePromise = page.waitForResponse((response) =>
    response.url().includes("/api/providers/")
      && response.url().endsWith("/models")
      && response.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: "Add", exact: true }).click();
  expect((await responsePromise).status()).toBe(201);
  await page.reload();
  const refreshedCard = providerCard(page, providerName);
  await refreshedCard.getByRole("button", { name: "Show Models" }).click();
  await expect(refreshedCard.getByText(modelId, { exact: true })).toBeVisible();
}

async function expectHealthy(page: Page, providerName: string): Promise<void> {
  const card = providerCard(page, providerName);
  const responsePromise = page.waitForResponse((response) =>
    response.url().includes("/api/providers/")
      && response.url().endsWith("/test")
      && response.request().method() === "POST",
  );
  await card.getByRole("button", { name: "Test Connection" }).click();
  expect((await responsePromise).status()).toBe(200);
  await expect(card.getByText("1/1 models OK", { exact: true })).toBeVisible();
}

async function closeNodePanel(page: Page): Promise<void> {
  const closeButton = page.getByRole("button", { name: "Close panel" });
  if (await closeButton.isVisible()) {
    await closeButton.click();
    await expect(closeButton).toBeHidden();
  }
}

test("manages OpenAI and Azure providers against the local mock", async ({ baseURL, page }) => {
  const appURL = requireBaseURL(baseURL);
  const user = await provisionUser(appURL, "providers");
  const runId = uniqueLabel("provider");
  const openAIName = `OpenAI ${runId}`;
  const azureName = `Azure ${runId}`;
  const updatedAzureName = `${azureName} Updated`;
  const azureModel = `azure-deployment-${runId.slice(-7)}`;
  const fixturePath = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../fixtures/test-document.pdf",
  );
  if (!fs.existsSync(fixturePath)) {
    throw new Error(`Missing public VLM fixture: ${fixturePath}`);
  }

  await useEnglish(page);
  await applySession(page.context(), user);
  await page.goto("/settings/workspace/providers");
  await expect(page.getByTestId("workspace-provider-settings")).toBeVisible();

  const openAI = await createProvider(page, {
    name: openAIName,
    style: "openai",
    baseURL: VLM_MOCK_BASE_URL,
  });
  expect(openAI.api_style).toBe("openai");
  expect(openAI.api_version).toBeNull();
  expect(openAI.base_url).toBe(VLM_MOCK_BASE_URL);
  await expect(providerCard(page, openAIName)).toBeVisible();

  const openAIDiscovery = await page.request.post(`/api/providers/${openAI.id}/discover`);
  await expectStatus(openAIDiscovery, 200);
  const openAIDiscoveryBody = (await openAIDiscovery.json()) as DiscoverResponse;
  expect(openAIDiscoveryBody.discovery_supported).toBe(true);
  expect(openAIDiscoveryBody.added).toBe(1);
  await page.reload();
  await expect(providerCard(page, openAIName)).toContainText("1 model");
  await expectHealthy(page, openAIName);

  const azure = await createProvider(page, {
    name: azureName,
    style: "azure_openai",
    baseURL: `${VLM_MOCK_BASE_URL}/azure`,
  });
  expect(azure.api_style).toBe("azure_openai");
  expect(azure.api_version).toBe(AZURE_API_VERSION);
  await expect(providerCard(page, azureName)).toBeVisible();

  const azureDiscovery = await page.request.post(`/api/providers/${azure.id}/discover`);
  await expectStatus(azureDiscovery, 200);
  const azureDiscoveryBody = (await azureDiscovery.json()) as DiscoverResponse;
  expect(azureDiscoveryBody).toMatchObject({
    added: 0,
    discovery_supported: false,
    message: "Azure OpenAI deployments must be added manually.",
  });
  await addModelManually(page, azureName, azureModel);
  await expectHealthy(page, azureName);

  await providerCard(page, azureName).getByRole("button", { name: "Set Default" }).click();
  await expect(providerCard(page, azureName).getByText("Default", { exact: true })).toBeVisible();

  await providerCard(page, azureName).getByRole("button", { name: "Edit" }).click();
  const editDialog = page.getByRole("dialog", { name: "Edit Model Provider" });
  await editDialog.getByLabel("Name").fill(updatedAzureName);
  const updateResponsePromise = page.waitForResponse((response) =>
    response.url().endsWith(`/api/providers/${azure.id}`) && response.request().method() === "PUT",
  );
  await editDialog.getByRole("button", { name: "Save", exact: true }).click();
  expect((await updateResponsePromise).status()).toBe(200);
  await expect(providerCard(page, updatedAzureName)).toBeVisible();

  await page.goto("/templates");
  await page
    .getByTestId("template-card-tpl-vlm-basic")
    .getByRole("button", { name: "Apply now" })
    .click();
  await expect(page.getByTestId("workflow-editor-page")).toBeVisible();
  await closeNodePanel(page);
  await page.locator(".workflow-node-card", { hasText: "Model" }).first().click();
  const configPanel = page.getByTestId("engine-config-panel");
  await expect(configPanel).toBeVisible();
  await expect(configPanel.locator(".ant-select-selection-item").nth(0)).toContainText(updatedAzureName);
  await expect(configPanel.locator(".ant-select-selection-item").nth(1)).toContainText(azureModel);

  await closeNodePanel(page);
  await page.locator(".workflow-node-card", { hasText: /PDF (?:Input|輸入)/ }).first().click();
  await page.locator('input[type="file"]').first().setInputFiles(fixturePath);

  const clearMockResponse = await fetch(`${VLM_MOCK_CONTROL_URL}/requests`, { method: "DELETE" });
  expect(clearMockResponse.status).toBe(200);

  const runButton = page.getByTestId("floating-btn-run");
  await expect(runButton).toBeEnabled();
  const runDialog = page.getByRole("dialog", { name: "Name this Run" });
  await runButton.click();
  if (!(await runDialog.isVisible())) {
    await expect(page.getByText("Validation passed", { exact: false })).toBeVisible();
    await runButton.click();
  }
  await expect(runDialog).toBeVisible();

  const createTaskResponsePromise = page.waitForResponse((response) =>
    response.url().endsWith("/api/tasks") && response.request().method() === "POST",
  );
  await runDialog.getByRole("button", { name: "Execute", exact: true }).click();
  const createTaskResponse = await createTaskResponsePromise;
  expect(createTaskResponse.status()).toBe(202);
  const createdTask = (await createTaskResponse.json()) as CreateTaskResponse;
  expect(createdTask.task_id).toBeTruthy();

  await expect.poll(async () => {
    const statusResponse = await page.request.get(`/api/tasks/${createdTask.task_id}`);
    await expectStatus(statusResponse, 200);
    return ((await statusResponse.json()) as { status: string }).status;
  }, { timeout: 180_000, intervals: [500, 1_000, 2_000] }).toBe("completed");

  const taskResultsResponse = await page.request.get(`/api/tasks/${createdTask.task_id}/results`);
  await expectStatus(taskResultsResponse, 200);
  const taskResults = (await taskResultsResponse.json()) as TaskResultsResponse;
  expect(taskResults).toMatchObject({ task_id: createdTask.task_id, status: "completed" });
  expect(taskResults.results.length).toBeGreaterThan(0);
  expect(JSON.stringify(taskResults.results)).toContain("mock vision response");

  await page.goto(`/tasks/${createdTask.task_id}/results`);
  await expect(page).toHaveURL(new RegExp(`/tasks/${createdTask.task_id}/results$`));
  await expect(page.getByRole("heading", { name: "Conversion Result" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Download Markdown" })).toBeVisible();

  const mockRequestsResponse = await fetch(`${VLM_MOCK_CONTROL_URL}/requests`);
  expect(mockRequestsResponse.status).toBe(200);
  const mockRequests = (await mockRequestsResponse.json()) as MockRequestsResponse;
  const imageRequests = mockRequests.requests.filter((request) => request.has_image);
  expect(imageRequests).toHaveLength(1);
  expect(imageRequests[0]).toMatchObject({
    path: `/azure/openai/deployments/${azureModel}/chat/completions`,
    has_image: true,
    has_api_key_header: true,
    api_version: AZURE_API_VERSION,
  });

  await page.goto("/settings/workspace/providers");
  const openAICard = providerCard(page, openAIName);
  await openAICard.getByRole("button", { name: "Delete" }).click();
  const deleteDialog = page.getByRole("dialog", { name: `Delete ${openAIName}?` });
  const deleteResponsePromise = page.waitForResponse((response) =>
    response.url().endsWith(`/api/providers/${openAI.id}`) && response.request().method() === "DELETE",
  );
  await deleteDialog.getByRole("button", { name: "Delete", exact: true }).click();
  expect((await deleteResponsePromise).status()).toBe(204);
  await expect(providerCard(page, openAIName)).toHaveCount(0);
  await expect(providerCard(page, updatedAzureName).getByText("Default", { exact: true })).toBeVisible();
});
