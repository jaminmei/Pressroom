import { apiClient } from "@/services/api";
import type {
  EngineListResponse,
  EngineDetail,
  EngineHealthResponse,
  ProviderHealthResult,
} from "@/types/engine";
import type { Provider } from "@/types/provider";
import { getProvider, ProviderReadOnlyError } from "@/services/providerApi";

export async function getEngines(): Promise<EngineListResponse> {
  const response = await apiClient.get<EngineListResponse>("/engines");
  return response.data;
}

export async function getEngine(category: string): Promise<EngineDetail> {
  const response = await apiClient.get<EngineDetail>(`/engines/${category}`);
  return response.data;
}

export async function getEngineHealth(category: string): Promise<EngineHealthResponse> {
  const response = await apiClient.get<EngineHealthResponse>(`/engines/${category}/health`);
  return response.data;
}

export async function checkProviderHealth(providerId: string): Promise<ProviderHealthResult> {
  const response = await apiClient.post<ProviderHealthResult>(
    `/providers/${providerId}/health-check`,
  );
  return response.data;
}

export async function updateParameterSchema(
  providerId: string,
  schema: Record<string, unknown>,
): Promise<Provider> {
  const provider = await getProvider(providerId);
  if (provider.scope === "system") {
    throw new ProviderReadOnlyError();
  }
  const response = await apiClient.put<Provider>(
    `/providers/${providerId}/parameter-schema`,
    { schema },
  );
  return response.data;
}
