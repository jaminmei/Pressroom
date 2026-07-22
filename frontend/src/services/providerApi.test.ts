import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/services/api";
import {
  addModel,
  createProvider,
  deleteProvider,
  discoverModels,
  listProviders,
  removeModel,
  testConnection,
  testModel,
  toggleModel,
  updateProvider,
} from "@/services/providerApi";

vi.mock("@/services/api", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    patch: vi.fn(),
  },
}));

const mockProvider = {
  id: "provider-1",
  name: "Test Provider",
  provider_type: "openai_compatible" as const,
  api_style: "openai" as const,
  api_version: null,
  engine_category: "vlm",
  base_url: "http://test:8000",
  has_api_key: false,
  auth_config_public: null,
  env_config: null,
  auth_type: "api_key" as const,
  is_enabled: true,
  is_default: false,
  config_schema: null,
  extra_config: null,
  models: [],
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
};

const mockModel = {
  id: "model-1",
  provider_id: "provider-1",
  model_id: "gpt-4",
  display_name: "GPT-4",
  is_enabled: true,
  capabilities: null,
  default_config: null,
  model_group: null,
  sort_order: 0,
};

describe("providerApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("T-API-01: listProviders() calls GET /providers and returns providers array", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: [mockProvider],
    } as never);

    const result = await listProviders();

    expect(apiClient.get).toHaveBeenCalledWith("/providers", {
      params: undefined,
    });
    expect(result).toEqual([mockProvider]);
    expect(result).toHaveLength(1);
  });

  it("T-API-02: listProviders({ category: 'vlm' }) passes query param", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: [mockProvider],
    } as never);

    await listProviders({ category: "vlm" });

    expect(apiClient.get).toHaveBeenCalledWith("/providers", {
      params: { category: "vlm" },
    });
  });

  it("T-API-03: createProvider(data) calls POST /providers and returns created provider", async () => {
    const createData = {
      name: "New Provider",
      provider_type: "openai_compatible" as const,
      engine_category: "vlm",
      base_url: "https://provider.example/v1",
      api_style: "openai" as const,
      api_version: null,
    };

    vi.mocked(apiClient.post).mockResolvedValue({
      data: mockProvider,
    } as never);

    const result = await createProvider(createData);

    expect(apiClient.post).toHaveBeenCalledWith("/providers", createData);
    expect(result).toEqual(mockProvider);
  });

  it("T-API-04: updateProvider(id, data) calls PUT /providers/{id} and returns updated provider", async () => {
    const updateData = { name: "Updated Provider" };
    const updatedProvider = { ...mockProvider, name: "Updated Provider" };

    vi.mocked(apiClient.put).mockResolvedValue({
      data: updatedProvider,
    } as never);

    const result = await updateProvider("test-id", updateData);

    expect(apiClient.put).toHaveBeenCalledWith("/providers/test-id", updateData);
    expect(result).toEqual(updatedProvider);
  });

  it("T-API-05: deleteProvider(id) calls DELETE /providers/{id} and resolves", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue({} as never);

    await deleteProvider("test-id");

    expect(apiClient.delete).toHaveBeenCalledWith("/providers/test-id");
  });

  it("T-API-06: testConnection(id) calls POST /providers/{id}/test and returns status + latency", async () => {
    const testResponse = {
      status: "healthy" as const,
      latency_ms: 45,
      error: null,
      details: null,
      model_results: null,
    };

    vi.mocked(apiClient.post).mockResolvedValue({
      data: testResponse,
    } as never);

    const result = await testConnection("test-id");

    expect(apiClient.post).toHaveBeenCalledWith("/providers/test-id/test");
    expect(result.status).toBe("healthy");
    expect(result.latency_ms).toBe(45);
    expect(result.error).toBeNull();
  });

  it("T-API-07: addModel(providerId, data) calls POST /providers/{id}/models and returns created model", async () => {
    const createData = { model_id: "gpt-4", display_name: "GPT-4" };

    vi.mocked(apiClient.post).mockResolvedValue({
      data: mockModel,
    } as never);

    const result = await addModel("provider-1", createData);

    expect(apiClient.post).toHaveBeenCalledWith("/providers/provider-1/models", createData);
    expect(result).toEqual(mockModel);
  });

  it("forwards discovery support metadata from the Provider API", async () => {
    const response = {
      discovered: [],
      added: 0,
      skipped: 0,
      config_schema: null,
      schema_discovered: false,
      discovery_supported: false,
      message: "Azure OpenAI deployments must be added manually.",
    };
    vi.mocked(apiClient.post).mockResolvedValue({ data: response } as never);

    await expect(discoverModels("provider-1")).resolves.toEqual(response);
    expect(apiClient.post).toHaveBeenCalledWith("/providers/provider-1/discover");
  });

  it("T-API-08: removeModel(providerId, modelId) calls DELETE /providers/{id}/models/{modelId}", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue({} as never);

    await removeModel("provider-1", "model-1");

    expect(apiClient.delete).toHaveBeenCalledWith("/providers/provider-1/models/model-1");
  });

  it("T-API-09: toggleModel(providerId, modelId, isEnabled) calls PATCH /providers/{id}/models/{modelId}", async () => {
    const toggledModel = { ...mockModel, is_enabled: false };

    vi.mocked(apiClient.patch).mockResolvedValue({
      data: toggledModel,
    } as never);

    const result = await toggleModel("provider-1", "model-1", false);

    expect(apiClient.patch).toHaveBeenCalledWith("/providers/provider-1/models/model-1", {
      is_enabled: false,
    });
    expect(result.is_enabled).toBe(false);
  });

  it("T-API-10: testModel(providerId, modelId) calls POST /providers/{id}/models/{modelId}/test", async () => {
    const testResponse = {
      status: "ok" as const,
      latency_ms: 150,
      error: null,
      model_response: "OK",
    };

    vi.mocked(apiClient.post).mockResolvedValue({
      data: testResponse,
    } as never);

    const result = await testModel("provider-1", "model-1");

    expect(apiClient.post).toHaveBeenCalledWith("/providers/provider-1/models/model-1/test");
    expect(result.status).toBe("ok");
    expect(result.latency_ms).toBe(150);
    expect(result.model_response).toBe("OK");
  });
});
