import { request as playwrightRequest } from "@playwright/test";
import type {
  APIRequestContext,
  APIResponse,
  BrowserContext,
  Page,
} from "@playwright/test";

export const PUBLIC_E2E_PASSWORD = "Public-E2E-Strong-42!";

type StorageState = Awaited<ReturnType<APIRequestContext["storageState"]>>;

export interface PublicE2EUser {
  readonly id: string;
  readonly email: string;
  readonly name: string;
  readonly password: string;
  readonly storageState: StorageState;
}

interface AuthEnvelope {
  readonly data: {
    readonly user: {
      readonly id: string;
    };
  };
}

export function requireBaseURL(baseURL: string | undefined): string {
  if (!baseURL) {
    throw new Error("The public Playwright lane requires a baseURL");
  }
  return baseURL;
}

export function uniqueLabel(prefix: string): string {
  const random = Math.random().toString(36).slice(2, 9);
  return `${prefix}-${Date.now()}-${process.pid}-${random}`;
}

export async function expectStatus(response: APIResponse, expected: number): Promise<void> {
  if (response.status() !== expected) {
    throw new Error(
      `${response.url()} returned ${response.status()}: ${await response.text()}`,
    );
  }
}

export async function provisionUser(baseURL: string, label: string): Promise<PublicE2EUser> {
  const api = await playwrightRequest.newContext({ baseURL });
  const suffix = uniqueLabel(label);
  const email = `${suffix}@e2e.local`;
  const name = `Public ${label} ${suffix.slice(-7)}`;

  try {
    const response = await api.post("/api/auth/register", {
      data: { email, password: PUBLIC_E2E_PASSWORD, name },
    });
    await expectStatus(response, 201);
    const body = (await response.json()) as AuthEnvelope;

    return {
      id: body.data.user.id,
      email,
      name,
      password: PUBLIC_E2E_PASSWORD,
      storageState: await api.storageState(),
    };
  } finally {
    await api.dispose();
  }
}

export async function authenticatedApi(
  baseURL: string,
  user: PublicE2EUser,
): Promise<APIRequestContext> {
  return playwrightRequest.newContext({ baseURL, storageState: user.storageState });
}

export async function applySession(
  context: BrowserContext,
  user: PublicE2EUser,
): Promise<void> {
  await context.clearCookies();
  await context.addCookies(user.storageState.cookies);
}

export async function useEnglish(page: Page): Promise<void> {
  await page.addInitScript(() => {
    window.localStorage.setItem("dc.language", "en");
  });
}
