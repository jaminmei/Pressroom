import axios, { AxiosError } from "axios";

import {
  clearActiveWorkspaceId,
  getActiveWorkspaceId as getTransportWorkspaceId,
  setValidatedActiveWorkspaceId
} from "@/services/workspaceTransport";

interface ApiErrorEnvelope {
  error_code?: string;
  message?: string;
  error?: {
    code?: string;
    message?: string;
  };
}

type UnauthorizedCode = "AUTH_REQUIRED" | "AUTH_SESSION_EXPIRED";
type UnauthorizedHandler = (code: UnauthorizedCode, error: AxiosError<ApiErrorEnvelope>) => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

export function setActiveWorkspaceId(id: string | null): void {
  setValidatedActiveWorkspaceId(id);
}

export { clearActiveWorkspaceId };

export function getActiveWorkspaceId(): string | null {
  return getTransportWorkspaceId();
}

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (!axios.isAxiosError<ApiErrorEnvelope>(error)) {
    return fallback;
  }

  const responseBody = error.response?.data;
  const code = responseBody?.error?.code ?? responseBody?.error_code;
  const message = responseBody?.error?.message ?? responseBody?.message;
  if (code && message) {
    return `${code}: ${message}`;
  }
  return message ?? code ?? fallback;
}

export const apiClient = axios.create({
  baseURL: "/api",
  timeout: 30000,
  withCredentials: true
});

apiClient.interceptors.request.use((config) => {
  const requestWorkspaceId = getTransportWorkspaceId();
  const existingWorkspaceId =
    typeof config.headers?.get === "function"
      ? config.headers.get("X-Workspace-Id")
      : config.headers?.["X-Workspace-Id"];
  if (requestWorkspaceId !== null && existingWorkspaceId == null) {
    config.headers = config.headers ?? {};
    config.headers["X-Workspace-Id"] = requestWorkspaceId;
  }
  return config;
}, undefined, { synchronous: true });

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorEnvelope>) => {
    const code = error.response?.data?.error_code;
    if ((code === "AUTH_REQUIRED" || code === "AUTH_SESSION_EXPIRED") && unauthorizedHandler) {
      unauthorizedHandler(code, error);
    }
    return Promise.reject(error);
  }
);
