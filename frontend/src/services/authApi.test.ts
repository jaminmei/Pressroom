import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/services/api";
import {
  getCurrentSession,
  loginWithPassword,
  logoutCurrentSession,
  registerWithPassword
} from "@/services/authApi";

vi.mock("@/services/api", () => ({
  apiClient: {
    post: vi.fn(),
    get: vi.fn()
  }
}));

describe("authApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("registers with POST /auth/register", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: {
        success: true,
        data: {
          user: { id: "usr_1", email: "alice@example.com", name: "Alice" },
          session: { expires_at: "2026-03-26T09:00:00Z" }
        }
      }
    } as never);

    const response = await registerWithPassword({
      email: "alice@example.com",
      password: "StrongerPassword123!",
      name: "Alice"
    });

    expect(apiClient.post).toHaveBeenCalledWith("/auth/register", {
      email: "alice@example.com",
      password: "StrongerPassword123!",
      name: "Alice"
    });
    expect(response.data.user.id).toBe("usr_1");
  });

  it("logs in with POST /auth/login", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: {
        success: true,
        data: {
          user: { id: "usr_1", email: "alice@example.com" },
          session: { expires_at: "2026-03-26T09:00:00Z" }
        }
      }
    } as never);

    const response = await loginWithPassword({
      email: "alice@example.com",
      password: "StrongerPassword123!"
    });

    expect(apiClient.post).toHaveBeenCalledWith("/auth/login", {
      email: "alice@example.com",
      password: "StrongerPassword123!"
    });
    expect(response.data.session.expires_at).toBe("2026-03-26T09:00:00Z");
  });

  it("logs out with POST /auth/logout", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { success: true }
    } as never);

    const response = await logoutCurrentSession();

    expect(apiClient.post).toHaveBeenCalledWith("/auth/logout");
    expect(response.success).toBe(true);
  });

  it("hydrates current session with GET /auth/me", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        success: true,
        data: {
          user: { id: "usr_1", email: "alice@example.com" },
          session: { expires_at: "2026-03-26T09:00:00Z" }
        }
      }
    } as never);

    const response = await getCurrentSession();

    expect(apiClient.get).toHaveBeenCalledWith("/auth/me");
    expect(response.data.user.email).toBe("alice@example.com");
  });
});
