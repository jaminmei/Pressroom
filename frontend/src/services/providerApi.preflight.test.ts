import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Provider } from "@/types/provider";

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  requestHandler: undefined as ((config: MockRequestConfig) => Promise<MockRequestConfig>) | undefined,
}));

interface MockRequestConfig {
  url?: string;
  data?: unknown;
  headers: Record<string, string>;
}

vi.mock("@/services/api", () => ({
  apiClient: {
    get: apiMocks.get,
    put: apiMocks.put,
    interceptors: {
      request: {
        use: vi.fn((handler: (config: MockRequestConfig) => Promise<MockRequestConfig>) => {
          apiMocks.requestHandler = handler;
        }),
      },
    },
  },
}));

import {
  assertWorkflowProvidersAvailable,
  ProviderUnavailableError,
  getProvider,
  listProviders,
  replaceVisibleProviders,
  resetProviderScopeState,
  updateProvider,
} from "@/services/providerApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

function provider(id: string): Provider {
  return {
    id,
    name: id,
    provider_type: "openai_compatible",
    api_style: "openai",
    api_version: null,
    engine_category: "vlm",
    base_url: "http://example.test",
    has_api_key: false,
    auth_config_public: null,
    env_config: null,
    auth_type: "api_key",
    is_enabled: true,
    is_default: false,
    config_schema: null,
    parameter_schema: null,
    extra_config: null,
    models: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    health_url: null,
  };
}

function setContext(workspaceId: string, generation: number): void {
  useWorkspaceStore.setState({
    currentWorkspace: {
      id: workspaceId,
      name: workspaceId,
      isDefault: false,
      role: "admin",
      capabilities: [],
    },
    contextGeneration: generation,
  });
}

describe("provider workflow preflight", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetProviderScopeState();
    setContext("workspace-a", 10);
  });

  it("pins both the provider lookup and outer mutation to the captured workspace", async () => {
    let resolveProviders!: (value: { data: Provider[] }) => void;
    apiMocks.get.mockReturnValueOnce(new Promise((resolve) => { resolveProviders = resolve; }));
    const config = {
      url: "/tasks",
      data: { nodes: [{ config: { provider_id: "provider-a" } }] },
      headers: {},
    };

    const request = apiMocks.requestHandler!(config);

    expect(config.headers).toMatchObject({ "X-Workspace-Id": "workspace-a" });
    expect(apiMocks.get).toHaveBeenCalledWith("/providers", {
      headers: { "X-Workspace-Id": "workspace-a" },
    });
    resolveProviders({ data: [provider("provider-a")] });

    await expect(request).resolves.toBe(config);
  });

  it("validates against only the providers returned by this preflight", async () => {
    replaceVisibleProviders([provider("provider-from-old-cache")]);
    apiMocks.get.mockResolvedValueOnce({ data: [provider("provider-current")] });

    await expect(apiMocks.requestHandler!({
      url: "/workflows/save",
      data: { definition: { nodes: [{ config: { provider_id: "provider-from-old-cache" } }] } },
      headers: {},
    })).rejects.toBeInstanceOf(ProviderUnavailableError);
  });

  it("drops an A response after A-B-A and never pollutes the revived A cache", async () => {
    let resolveProviders!: (value: { data: Provider[] }) => void;
    apiMocks.get.mockReturnValueOnce(new Promise((resolve) => { resolveProviders = resolve; }));
    const request = apiMocks.requestHandler!({
      url: "/tasks",
      data: { nodes: [{ config: { provider_id: "provider-stale-a" } }] },
      headers: {},
    });

    setContext("workspace-b", 11);
    replaceVisibleProviders([provider("provider-b")]);
    setContext("workspace-a", 12);
    replaceVisibleProviders([provider("provider-current-a")]);
    resolveProviders({ data: [provider("provider-stale-a")] });

    await expect(request).rejects.toMatchObject({ message: "workspace switched mid-request" });
    expect(() => assertWorkflowProvidersAvailable({ provider_id: "provider-stale-a" }))
      .toThrow(ProviderUnavailableError);
    expect(() => assertWorkflowProvidersAvailable({ provider_id: "provider-current-a" }))
      .not.toThrow();
  });

  it("drops a late list response instead of caching it into a revived workspace", async () => {
    let resolveProviders!: (value: { data: Provider[] }) => void;
    apiMocks.get.mockReturnValueOnce(new Promise((resolve) => { resolveProviders = resolve; }));
    const request = listProviders();

    setContext("workspace-b", 21);
    replaceVisibleProviders([provider("provider-b")]);
    setContext("workspace-a", 22);
    replaceVisibleProviders([provider("provider-current-a")]);
    resolveProviders({ data: [provider("provider-stale-a")] });

    await expect(request).rejects.toMatchObject({ message: "workspace switched while loading providers" });
    expect(() => assertWorkflowProvidersAvailable({ provider_id: "provider-stale-a" }))
      .toThrow(ProviderUnavailableError);
    expect(() => assertWorkflowProvidersAvailable({ provider_id: "provider-current-a" }))
      .not.toThrow();
  });

  it("clears the previous generation before caching one provider detail", async () => {
    replaceVisibleProviders([{ ...provider("system-a"), scope: "system" }]);
    setContext("workspace-b", 40);
    apiMocks.get.mockResolvedValueOnce({ data: provider("workspace-b-provider") });
    apiMocks.put.mockResolvedValueOnce({ data: provider("system-a") });

    await getProvider("workspace-b-provider");
    await updateProvider("system-a", { name: "Workspace-local reuse" });

    expect(apiMocks.put).toHaveBeenCalledWith("/providers/system-a", {
      name: "Workspace-local reuse",
    });
  });
});
