import { expect, test } from "@playwright/test";

import {
  applySession,
  authenticatedApi,
  expectStatus,
  provisionUser,
  requireBaseURL,
  uniqueLabel,
  useEnglish,
} from "./helpers/publicApi";

interface WorkspaceSummary {
  readonly id: string;
  readonly name: string;
}

interface WorkspaceList {
  readonly items: readonly WorkspaceSummary[];
}

test("creates a workspace in the UI and hides it from another user", async ({ baseURL, page }) => {
  const appURL = requireBaseURL(baseURL);
  const [owner, outsider] = await Promise.all([
    provisionUser(appURL, "workspace-owner"),
    provisionUser(appURL, "workspace-outsider"),
  ]);
  const workspaceName = `Public Workspace ${uniqueLabel("rbac")}`;

  await useEnglish(page);
  await applySession(page.context(), owner);
  await page.goto("/");
  await expect(page.getByTestId("workspace-switcher")).toBeVisible();
  await page.getByTestId("workspace-switcher-trigger").click();
  await page.locator(".workspace-menu-surface").getByRole("button", { name: /New workspace/i }).click();
  const createDialog = page.getByRole("dialog", { name: /Create workspace/i });
  await expect(createDialog).toBeVisible();
  await page.getByTestId("new-workspace-name-input").fill(workspaceName);

  const createResponsePromise = page.waitForResponse((response) =>
    response.url().endsWith("/api/workspaces") && response.request().method() === "POST",
  );
  await createDialog.getByRole("button", { name: /Create workspace/i }).click();
  const createResponse = await createResponsePromise;
  expect(createResponse.status()).toBe(201);
  const created = (await createResponse.json()) as WorkspaceSummary;
  await expect(createDialog).toBeHidden();

  await page.getByTestId("workspace-switcher-trigger").click();
  await expect(page.getByTestId(`workspace-option-${created.id}`)).toContainText(workspaceName);

  const outsiderApi = await authenticatedApi(appURL, outsider);
  try {
    const listResponse = await outsiderApi.get("/api/workspaces");
    await expectStatus(listResponse, 200);
    const list = (await listResponse.json()) as WorkspaceList;
    expect(list.items.map((workspace) => workspace.id)).not.toContain(created.id);

    const switchResponse = await outsiderApi.post(`/api/workspaces/${created.id}/switch`);
    await expectStatus(switchResponse, 404);

    const membersResponse = await outsiderApi.get(`/api/workspaces/${created.id}/members`);
    await expectStatus(membersResponse, 404);
  } finally {
    await outsiderApi.dispose();
  }

  await applySession(page.context(), outsider);
  await page.goto("/");
  await page.getByTestId("workspace-switcher-trigger").click();
  await expect(
    page.locator(".workspace-menu-surface").getByText(workspaceName, { exact: true }),
  ).toHaveCount(0);

  const ownerApi = await authenticatedApi(appURL, owner);
  try {
    const cleanupResponse = await ownerApi.delete(`/api/workspaces/${created.id}`);
    await expectStatus(cleanupResponse, 204);
  } finally {
    await ownerApi.dispose();
  }
});
