import { apiClient } from "@/services/api";

export interface AdaptorWorkbenchOutput {
  text: string | null;
  binary: Array<{
    data?: string | null;
    mime_type: string;
    size_bytes: number;
    dimensions?: Record<string, unknown> | null;
  }>;
  structured: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
}

export async function executeAdaptorWorkbench(
  code: string,
  inputs: Record<string, unknown>,
): Promise<AdaptorWorkbenchOutput> {
  const response = await apiClient.post<{
    success: boolean;
    data: { output: AdaptorWorkbenchOutput };
  }>("/adaptor-workbench/execute", { code, inputs });
  return response.data.data.output;
}
