import { expect, test } from "@playwright/test";

import { PUBLIC_E2E_PASSWORD, uniqueLabel } from "./helpers/publicApi";

test("registers, changes language, logs out, and logs back in through the UI", async ({ page }) => {
  const suffix = uniqueLabel("auth");
  const email = `${suffix}@e2e.local`;

  await page.goto("/register");
  await expect(page.getByTestId("register-page")).toBeVisible();
  await page.getByTestId("register-name").fill(`Public Auth ${suffix.slice(-7)}`);
  await page.getByTestId("register-email").fill(email);
  await page.getByTestId("register-password").fill(PUBLIC_E2E_PASSWORD);
  await page.getByTestId("register-confirm-password").fill(PUBLIC_E2E_PASSWORD);

  const registerResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/auth/register") && response.request().method() === "POST",
  );
  await page.getByTestId("register-submit").click();
  expect((await registerResponse).status()).toBe(201);

  await expect(page.getByTestId("auth-current-user")).toBeVisible();
  await page.getByTestId("auth-current-user").click();
  await page.getByTestId("language-option-zh-TW").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-TW");
  await expect(page.getByTestId("domain-tab-database")).toHaveText("資料庫");
  await expect.poll(() => page.evaluate(() => window.localStorage.getItem("dc.language"))).toBe("zh-TW");

  await page.getByTestId("auth-current-user").click();
  const logoutResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/auth/logout") && response.request().method() === "POST",
  );
  await page.getByTestId("auth-logout-button").click();
  expect((await logoutResponse).status()).toBe(200);
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByTestId("login-page")).toBeVisible();

  await page.getByTestId("login-email").fill(email);
  await page.getByTestId("login-password").fill(PUBLIC_E2E_PASSWORD);
  const loginResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/auth/login") && response.request().method() === "POST",
  );
  await page.getByTestId("login-submit").click();
  expect((await loginResponse).status()).toBe(200);
  await expect(page.getByTestId("auth-current-user")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-TW");

  await page.getByTestId("auth-current-user").click();
  await page.getByTestId("language-option-en").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByTestId("domain-tab-database")).toHaveText("Database");

  await page.getByTestId("auth-current-user").click();
  await page.getByTestId("auth-logout-button").click();
  await expect(page).toHaveURL(/\/login$/);
});
