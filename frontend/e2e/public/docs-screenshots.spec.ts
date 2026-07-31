import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import {
  applySession,
  authenticatedApi,
  expectStatus,
  provisionUser,
  requireBaseURL,
  useEnglish as selectEnglishLocale
} from "./helpers/publicApi";

test.skip(
  process.env.CAPTURE_DOCS_SCREENSHOTS !== "1",
  "Documentation screenshots are regenerated only on an explicit maintainer run."
);

test.use({ viewport: { width: 1600, height: 1000 } });

const specDirectory = path.dirname(fileURLToPath(import.meta.url));
const captureDirectory = path.resolve(specDirectory, "../../test-results/docs-captures");
const documentFixture = path.resolve(specDirectory, "../fixtures/test-document.pdf");

interface WorkspaceSessionResponse {
  readonly current_workspace: { readonly id: string } | null;
}

interface PublishWorkflowResponse {
  readonly data: { readonly workflow_id: string };
}

interface CreateTestSetResponse {
  readonly id: string;
}

interface UploadDocumentsResponse {
  readonly uploaded: readonly { readonly id: string }[];
}

function capturePath(filename: string): string {
  fs.mkdirSync(captureDirectory, { recursive: true });
  return path.join(captureDirectory, filename);
}

async function prepareDocsUser(baseURL: string, page: Page, label: string) {
  const user = await provisionUser(baseURL, `docs-${label}`);
  const api = await authenticatedApi(baseURL, user);
  const workspaceResponse = await api.get("/api/workspaces/session");
  await expectStatus(workspaceResponse, 200);
  const workspace = (await workspaceResponse.json()) as WorkspaceSessionResponse;
  if (!workspace.current_workspace) throw new Error("Docs capture user has no workspace");
  const updateResponse = await api.patch(`/api/workspaces/${workspace.current_workspace.id}`, {
    data: { name: "Press Room Docs Demo", description: "Synthetic documentation workspace" }
  });
  await expectStatus(updateResponse, 200);

  await selectEnglishLocale(page);
  await applySession(page.context(), user);
  return api;
}

async function stabilizePage(page: Page): Promise<void> {
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        transition-duration: 0s !important;
        caret-color: transparent !important;
      }
      [data-testid="auth-current-user"] { visibility: hidden !important; }
    `
  });
  await page.evaluate(() => {
    for (const element of document.querySelectorAll<HTMLElement>(
      ".ant-message, .ant-notification"
    )) {
      element.remove();
    }
  });
}

async function capture(page: Page, filename: string): Promise<void> {
  await stabilizePage(page);
  await page.screenshot({
    animations: "disabled",
    caret: "hide",
    path: capturePath(filename),
    scale: "css"
  });
}

test("captures the OCR template center", async ({ baseURL, page }) => {
  const appURL = requireBaseURL(baseURL);
  const api = await prepareDocsUser(appURL, page, "templates");
  try {
    await page.goto("/templates");
    await expect(page.getByTestId("template-center-page")).toBeVisible();
    await expect(page.getByTestId("template-card-tpl-ocr-basic")).toBeVisible();
    await capture(page, "template-center-ocr.png");
  } finally {
    await api.dispose();
  }
});

test("captures the current workflow editor product hero", async ({ baseURL, page }) => {
  const appURL = requireBaseURL(baseURL);
  const api = await prepareDocsUser(appURL, page, "workflow-editor");
  try {
    await page.goto("/templates");
    await expect(page.getByTestId("template-center-page")).toBeVisible();
    await page
      .getByTestId("template-card-tpl-compare-ocr-vlm")
      .getByRole("button", { name: "Apply now" })
      .click();
    await expect(page.getByTestId("workflow-editor-page")).toBeVisible();
    await expect(page.locator(".workflow-node-card")).toHaveCount(5);
    const closePanel = page.getByRole("button", { name: "Close panel" });
    if (await closePanel.isVisible()) await closePanel.click();
    await page.getByTitle("Center view").click();
    await page.getByTestId("react-flow-shell").click({ position: { x: 480, y: 180 } });
    await page.waitForTimeout(400);
    await capture(page, "workflow-editor.png");
  } finally {
    await api.dispose();
  }
});

test("captures the synthetic Provider configuration form", async ({ baseURL, page }) => {
  const appURL = requireBaseURL(baseURL);
  const api = await prepareDocsUser(appURL, page, "provider");
  try {
    await page.goto("/settings/workspace/providers");
    await expect(page.getByTestId("workspace-provider-settings")).toBeVisible();
    await page.getByRole("button", { name: "Add Provider" }).click();
    const dialog = page.getByRole("dialog", { name: "Add Model Provider" });
    await dialog.getByLabel("Name").fill("Invoice Vision Demo");
    await dialog.getByLabel("Base URL").fill("https://api.example.invalid/v1");
    await dialog.getByLabel("API Key").fill("synthetic-placeholder");
    await capture(page, "provider-configuration.png");
  } finally {
    await api.dispose();
  }
});

test("captures published workflow API setup without rendering a full key", async ({
  baseURL,
  page
}) => {
  const appURL = requireBaseURL(baseURL);
  const api = await prepareDocsUser(appURL, page, "api-access");
  try {
    const publishResponse = await api.post("/api/workflows/publish", {
      data: {
        name: "Invoice Quality Baseline",
        description: "Synthetic documentation workflow",
        definition: {
          nodes: [
            { id: "input_image", type: "input/image", config: { file: "$file_0" } },
            { id: "final", type: "end/final", config: {} }
          ],
          connections: [{ source: "input_image", target: "final", target_port: "input" }]
        }
      }
    });
    await expectStatus(publishResponse, 201);
    const published = (await publishResponse.json()) as PublishWorkflowResponse;

    const keyResponse = await api.post("/api/admin/api-keys", {
      data: {
        workflow_id: published.data.workflow_id,
        description: "Docs upload client"
      }
    });
    await expectStatus(keyResponse, 201);

    await page.goto(`/workflows/${published.data.workflow_id}/api-access`);
    await expect(page.getByTestId("api-access-page")).toBeVisible();
    await expect(page.getByTestId("public-endpoint-card")).toBeVisible();
    await page.evaluate(() => {
      document.body.innerHTML = document.body.innerHTML
        .replaceAll(/wf_[0-9a-f-]{36}/g, "wf_your_workflow_id")
        .replaceAll(/dca_[a-zA-Z0-9_-]+/g, "dca_demo…");
    });
    await capture(page, "api-access-setup.png");
  } finally {
    await api.dispose();
  }
});

test("captures Database Ground Truth with public fixtures", async ({ baseURL, page }) => {
  if (!fs.existsSync(documentFixture)) {
    throw new Error(`Missing public documentation fixture: ${documentFixture}`);
  }
  const appURL = requireBaseURL(baseURL);
  const api = await prepareDocsUser(appURL, page, "ground-truth");
  try {
    const createResponse = await api.post("/api/test-sets", {
      data: {
        name: "Invoice Regression Set",
        description: "Synthetic invoices for documentation"
      }
    });
    await expectStatus(createResponse, 201);
    const testSet = (await createResponse.json()) as CreateTestSetResponse;

    const uploadResponse = await api.post(`/api/test-sets/${testSet.id}/documents/upload`, {
      multipart: {
        files: {
          name: "synthetic-invoice.pdf",
          mimeType: "application/pdf",
          buffer: fs.readFileSync(documentFixture)
        }
      }
    });
    await expectStatus(uploadResponse, 201);
    const uploaded = (await uploadResponse.json()) as UploadDocumentsResponse;
    const documentId = uploaded.uploaded[0]?.id;
    if (!documentId) throw new Error("Synthetic documentation upload returned no document");

    const groundTruthResponse = await api.post(
      `/api/test-sets/${testSet.id}/documents/${documentId}/ground-truth`,
      {
        data: {
          content: JSON.stringify({ invoice_number: "INV-2026-001", total: "3420.00" }),
          source: "manual",
          format: "json"
        }
      }
    );
    await expectStatus(groundTruthResponse, 201);

    await page.goto(`/database/${testSet.id}`);
    await expect(page.getByTestId("project-workspace")).toBeVisible();
    await page.getByTestId("ws-nav-ground-truth").click();
    await expect(page.getByTestId("gt-view")).toBeVisible();
    await expect(page.getByText("synthetic-invoice.pdf", { exact: true })).toBeVisible();
    await capture(page, "database-ground-truth.png");
  } finally {
    await api.dispose();
  }
});
