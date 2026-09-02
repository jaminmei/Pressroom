import type { AuthStatus } from "@/stores/authStore";

export function shouldRenderChatbox(status: AuthStatus, workspaceId: string | null): boolean {
  return status === "authenticated" && workspaceId !== null;
}
