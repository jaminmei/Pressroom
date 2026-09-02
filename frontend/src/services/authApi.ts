import { apiClient } from "@/services/api";
import type {
  AuthEnvelope,
  LoginRequest,
  RegisterRequest
} from "@/types/auth";

export async function registerWithPassword(payload: RegisterRequest): Promise<AuthEnvelope> {
  const response = await apiClient.post<AuthEnvelope>("/auth/register", payload);
  return response.data;
}

export async function loginWithPassword(payload: LoginRequest): Promise<AuthEnvelope> {
  const response = await apiClient.post<AuthEnvelope>("/auth/login", payload);
  return response.data;
}

export async function logoutCurrentSession(): Promise<{ success: boolean }> {
  const response = await apiClient.post<{ success: boolean }>("/auth/logout");
  return response.data;
}

export async function getCurrentSession(): Promise<AuthEnvelope> {
  const response = await apiClient.get<AuthEnvelope>("/auth/me");
  return response.data;
}
