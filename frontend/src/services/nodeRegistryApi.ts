import { apiClient } from "@/services/api";
import type { NodeRegistryResponse } from "@/types/node-registry";

export async function getNodeRegistry(): Promise<NodeRegistryResponse> {
  const response = await apiClient.get<NodeRegistryResponse>("/nodes/registry");
  return response.data;
}
