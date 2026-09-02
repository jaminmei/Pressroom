import axios from "axios";

import { apiClient } from "@/services/api";
import type {
  Provider,
  ProviderDefault,
  ProviderModel,
  ProviderModelCreate,
  CreateProviderRequest,
  DiscoverResponse,
  UpdateProviderRequest,
  ReadinessTestResponse,
  TestConnectionResponse,
  TestModelResponse,
} from "@/types/provider";
import {
  captureWorkspaceContext,
  isWorkspaceContextCurrent,
} from "@/stores/workspaceStore";

const providersById = new Map<string, Provider>();
let providerScopeLoaded = false;
let providerContextGeneration: number | null = null;

export class ProviderUnavailableError extends Error {
  constructor() {
    super("Provider unavailable in the current workspace");
    this.name = "ProviderUnavailableError";
  }
}

export class ProviderReadOnlyError extends Error {
  constructor() {
    super("System managed providers are read-only");
    this.name = "ProviderReadOnlyError";
  }
}

function rememberProviders(providers: readonly Provider[], token = captureWorkspaceContext()): void {
  if (!isWorkspaceContextCurrent(token)) return;
  const contextGeneration = token.generation;
  if (providerContextGeneration !== contextGeneration) {
    providersById.clear();
    providerContextGeneration = contextGeneration;
  }
  providerScopeLoaded = true;
  for (const provider of providers) {
    providersById.set(provider.id, provider);
  }
}

function rememberProvider(provider: Provider, token: ReturnType<typeof captureWorkspaceContext>): void {
  if (!isWorkspaceContextCurrent(token)) return;
  if (providerContextGeneration !== token.generation) {
    providersById.clear();
    providerScopeLoaded = false;
    providerContextGeneration = token.generation;
  }
  providersById.set(provider.id, provider);
}

function assertProviderMutable(id: string): void {
  if (providersById.get(id)?.scope === "system") {
    throw new ProviderReadOnlyError();
  }
}

function hasUnavailableProvider(
  value: unknown,
  visibleProviderIds: ReadonlySet<string>,
  scopeLoaded: boolean,
): boolean {
  if (Array.isArray(value)) {
    return value.some((child) => hasUnavailableProvider(child, visibleProviderIds, scopeLoaded));
  }
  if (typeof value !== "object" || value === null) {
    return false;
  }
  return Object.entries(value).some(([key, child]) =>
    key === "provider_id" && typeof child === "string"
      ? scopeLoaded && !visibleProviderIds.has(child)
      : hasUnavailableProvider(child, visibleProviderIds, scopeLoaded),
  );
}

export function resetProviderScopeState(): void {
  providersById.clear();
  providerScopeLoaded = false;
  providerContextGeneration = null;
}

export function replaceVisibleProviders(providers: readonly Provider[]): void {
  rememberProviders(providers);
}

export function assertWorkflowProvidersAvailable(payload: unknown): void {
  if (hasUnavailableProvider(payload, new Set(providersById.keys()), providerScopeLoaded)) {
    throw new ProviderUnavailableError();
  }
}

apiClient.interceptors?.request.use(async (config) => {
  const guarded = ["/workflows/save", "/workflows/publish", "/workflows/publish-as", "/tasks"]
    .some((path) => config.url === path || config.url?.startsWith(`${path}/`));
  if (!guarded) {
    return config;
  }
  const token = captureWorkspaceContext();
  if (!token.workspaceId) {
    throw new axios.Cancel("workspace context unavailable");
  }
  config.headers = config.headers ?? {};
  config.headers["X-Workspace-Id"] = token.workspaceId;
  const response = await apiClient.get<Provider[]>("/providers", {
    headers: { "X-Workspace-Id": token.workspaceId },
  });
  if (!isWorkspaceContextCurrent(token)) {
    throw new axios.Cancel("workspace switched mid-request");
  }
  const visibleProviderIds = new Set(response.data.map((provider) => provider.id));
  let payload: unknown = config.data;
  if (config.data instanceof FormData) {
    const workflow = config.data.get("workflow");
    if (typeof workflow === "string") {
      payload = JSON.parse(workflow);
    }
  }
  if (hasUnavailableProvider(payload, visibleProviderIds, true)) {
    throw new ProviderUnavailableError();
  }
  rememberProviders(response.data, token);
  return config;
});

export async function listProviders(params?: {
  category?: string;
  provider_type?: string;
  enabled_only?: boolean;
}): Promise<Provider[]> {
  const token = captureWorkspaceContext();
  const response = await apiClient.get<Provider[]>("/providers", {
    params: params ?? undefined,
    ...(token.workspaceId ? { headers: { "X-Workspace-Id": token.workspaceId } } : {}),
  });
  if (!isWorkspaceContextCurrent(token)) {
    throw new axios.Cancel("workspace switched while loading providers");
  }
  rememberProviders(response.data, token);
  return response.data;
}

export async function getDefaultProvider(category: string): Promise<ProviderDefault> {
  const response = await apiClient.get<ProviderDefault>("/providers/default", {
    params: { category },
  });
  return response.data;
}

export async function getProvider(id: string): Promise<Provider> {
  const token = captureWorkspaceContext();
  const response = await apiClient.get<Provider>(`/providers/${id}`, token.workspaceId
    ? { headers: { "X-Workspace-Id": token.workspaceId } }
    : undefined);
  if (!isWorkspaceContextCurrent(token)) {
    throw new axios.Cancel("workspace switched while loading provider");
  }
  rememberProvider(response.data, token);
  return response.data;
}

export async function createProvider(data: CreateProviderRequest): Promise<Provider> {
  const response = await apiClient.post<Provider>("/providers", data);
  return response.data;
}

export async function updateProvider(id: string, data: UpdateProviderRequest): Promise<Provider> {
  assertProviderMutable(id);
  const response = await apiClient.put<Provider>(`/providers/${id}`, data);
  return response.data;
}

export async function deleteProvider(id: string): Promise<void> {
  assertProviderMutable(id);
  await apiClient.delete(`/providers/${id}`);
}

export async function setDefaultProvider(id: string): Promise<Provider> {
  assertProviderMutable(id);
  const token = captureWorkspaceContext();
  const response = await apiClient.put<Provider>(`/providers/${id}/default`);
  rememberProvider(response.data, token);
  return response.data;
}

export async function testConnection(id: string): Promise<TestConnectionResponse> {
  const response = await apiClient.post<TestConnectionResponse>(`/providers/${id}/test`);
  return response.data;
}

export async function discoverModels(id: string): Promise<DiscoverResponse> {
  assertProviderMutable(id);
  const response = await apiClient.post<DiscoverResponse>(`/providers/${id}/discover`);
  return response.data;
}

export async function addModel(
  providerId: string,
  data: ProviderModelCreate,
): Promise<ProviderModel> {
  assertProviderMutable(providerId);
  const response = await apiClient.post<ProviderModel>(
    `/providers/${providerId}/models`,
    data,
  );
  return response.data;
}

export async function removeModel(
  providerId: string,
  modelId: string,
): Promise<void> {
  assertProviderMutable(providerId);
  await apiClient.delete(`/providers/${providerId}/models/${modelId}`);
}

export async function toggleModel(
  providerId: string,
  modelId: string,
  isEnabled: boolean,
): Promise<ProviderModel> {
  assertProviderMutable(providerId);
  const response = await apiClient.patch<ProviderModel>(
    `/providers/${providerId}/models/${modelId}`,
    { is_enabled: isEnabled },
  );
  return response.data;
}

export async function testModel(
  providerId: string,
  modelId: string,
): Promise<TestModelResponse> {
  const response = await apiClient.post<TestModelResponse>(
    `/providers/${providerId}/models/${modelId}/test`,
  );
  return response.data;
}

export async function runReadinessTest(providerId: string): Promise<ReadinessTestResponse> {
  const response = await apiClient.post<ReadinessTestResponse>(
    `/providers/${providerId}/readiness-test`,
  );
  return response.data;
}
