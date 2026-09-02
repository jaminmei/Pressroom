const CHATBOX_SESSION_STORAGE_PREFIX = "dc.experimental-chatbox.session";

export function chatboxSessionStorageKey(userId: string, workspaceId: string): string {
  return `${CHATBOX_SESSION_STORAGE_PREFIX}:${userId}:${workspaceId}`;
}

export function readStoredChatboxSession(
  userId: string | null,
  workspaceId: string | null,
): string | null {
  if (userId === null || workspaceId === null) return null;
  try {
    return window.sessionStorage.getItem(chatboxSessionStorageKey(userId, workspaceId));
  } catch {
    return null;
  }
}

export function storeChatboxSession(
  userId: string | null,
  workspaceId: string | null,
  sessionId: string,
): void {
  if (userId === null || workspaceId === null) return;
  try {
    window.sessionStorage.setItem(chatboxSessionStorageKey(userId, workspaceId), sessionId);
  } catch {
    // Session storage is an optional reload optimization.
  }
}

export function clearStoredChatboxSession(
  userId: string | null,
  workspaceId: string | null,
): void {
  if (userId === null || workspaceId === null) return;
  try {
    window.sessionStorage.removeItem(chatboxSessionStorageKey(userId, workspaceId));
  } catch {
    // Session storage may be unavailable in hardened browser contexts.
  }
}
