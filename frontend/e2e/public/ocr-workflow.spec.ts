import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import {
  applySession,
  expectStatus,
  provisionUser,
  requireBaseURL,
  useEnglish,
} from "./helpers/publicApi";

interface TaskResultsResponse {
  readonly task_id: string;
  readonly status: string;
  readonly results: readonly {
    readonly content: string;
  }[];
}

interface CreateTaskResponse {
  readonly task_id: string;
  readonly status: string;
}

test("uploads a fixture and renders the result of the real OCR template", async ({ baseURL, page }) => {
  const appURL = requireBaseURL(baseURL);
  const user = await provisionUser(appURL, "ocr");
  const fixturePath = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../fixtures/test-document.pdf",
  );
  if (!fs.existsSync(fixturePath)) {
    throw new Error(`Missing public OCR fixture: ${fixturePath}`);
  }

  await useEnglish(page);
  await applySession(page.context(), user);
  await page.goto("/templates");
  await expect(page.getByTestId("template-center-page")).toBeVisible();
  await page
    .getByTestId("template-card-tpl-ocr-basic")
    .getByRole("button", { name: "Apply now" })
    .click();
  await expect(page.getByTestId("workflow-editor-page")).toBeVisible();

  await page.locator(".workflow-node-card", { hasText: /PDF (?:Input|輸入)/ }).first().click();
  await page.locator('input[type="file"]').first().setInputFiles(fixturePath);
  await expect(page.locator(".workflow-node-card", { hasText: "OCR" }).first()).toContainText("RapidOCR");
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

  if (createdTask.status === "pending" || createdTask.status === "running") {
    await expect(page.getByTestId("progress-overlay")).toBeVisible();
  }
  await expect.poll(async () => {
    const statusResponse = await page.request.get(`/api/tasks/${createdTask.task_id}`);
    await expectStatus(statusResponse, 200);
    return ((await statusResponse.json()) as { status: string }).status;
  }, { timeout: 180_000, intervals: [500, 1_000, 2_000] }).toBe("completed");

  await page.evaluate((resultPath) => {
    window.history.pushState({}, "", resultPath);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, `/tasks/${createdTask.task_id}/results`);
  await expect(page).toHaveURL(new RegExp(`/tasks/${createdTask.task_id}/results$`));
  await expect(page.getByRole("heading", { name: "Conversion Result" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Download Markdown" })).toBeVisible();
  await expect(page.locator(".ant-alert-error")).toHaveCount(0);

  const resultsResponse = await page.request.get(`/api/tasks/${createdTask.task_id}/results`);
  await expectStatus(resultsResponse, 200);
  const results = (await resultsResponse.json()) as TaskResultsResponse;
  expect(results.task_id).toBe(createdTask.task_id);
  expect(results.status).toBe("completed");
  expect(results.results.length).toBeGreaterThan(0);
  expect(results.results[0]?.content.trim().length).toBeGreaterThan(0);
});
