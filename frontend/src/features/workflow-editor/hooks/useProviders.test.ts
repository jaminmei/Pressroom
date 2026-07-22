import "@testing-library/jest-dom/vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useProviders } from "./useProviders";

// Mock providerApi
vi.mock("@/services/providerApi", () => ({
  listProviders: vi.fn(),
}));

import { listProviders } from "@/services/providerApi";

const mockProviders: import("@/types/provider").Provider[] = [
  {
    id: "p1",
    name: "Vision Provider",
    provider_type: "openai_compatible",
    api_style: "openai",
    api_version: null,
    engine_category: "vlm",
    base_url: "http://vlm:8080",
    has_api_key: false,
    auth_type: "api_key",
    auth_config_public: null,
    env_config: null,
    is_enabled: true,
    is_default: true,
    config_schema: null,
    parameter_schema: null,
    extra_config: null,
    models: [],
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
    health_url: null,
  },
  {
    id: "p2",
    name: "Local Ollama",
    provider_type: "openai_compatible",
    api_style: "openai",
    api_version: null,
    engine_category: "vlm",
    base_url: "http://ollama:11434",
    has_api_key: false,
    auth_type: "api_key",
    auth_config_public: null,
    env_config: null,
    is_enabled: true,
    is_default: false,
    config_schema: null,
    parameter_schema: null,
    extra_config: null,
    models: [],
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
    health_url: null,
  },
];

describe("useProviders", () => {
  it("T-HOOK-01: fetches providers for given category", async () => {
    vi.mocked(listProviders).mockResolvedValue(mockProviders);

    const { result } = renderHook(() => useProviders("vlm"));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(listProviders).toHaveBeenCalledWith({
      category: "vlm",
      enabled_only: true,
    });
    expect(result.current.providers).toHaveLength(2);
  });

  it("T-HOOK-02: returns loading state during fetch", () => {
    vi.mocked(listProviders).mockReturnValue(new Promise(() => {})); // never resolves

    const { result } = renderHook(() => useProviders("vlm"));

    expect(result.current.loading).toBe(true);
    expect(result.current.providers).toHaveLength(0);
  });

  it("T-HOOK-03: returns error on API failure", async () => {
    vi.mocked(listProviders).mockRejectedValue(new Error("Network error"));

    const { result } = renderHook(() => useProviders("vlm"));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBeTruthy();
    expect(result.current.error?.message).toBe("Network error");
  });
});
