const STORAGE_PREFIX = "dc.workspace.active-id:";

let activeUserId: string | null = null;
let activeWorkspaceId: string | null = null;

export class MissingWorkspaceContextError extends Error {
  constructor() {
    super("A validated workspace is required for this URL");
    this.name = "MissingWorkspaceContextError";
  }
}

function storageKey(userId: string): string {
  return `${STORAGE_PREFIX}${userId}`;
}

export function activateWorkspaceUser(userId: string): string | null {
  if (activeUserId !== userId) activeWorkspaceId = null;
  activeUserId = userId;
  return sessionStorage.getItem(storageKey(userId));
}

export function clearWorkspaceUser(userId: string): void {
  sessionStorage.removeItem(storageKey(userId));
  if (activeUserId === userId) {
    activeUserId = null;
    activeWorkspaceId = null;
  }
}

export function setValidatedActiveWorkspaceId(workspaceId: string | null): void {
  activeWorkspaceId = workspaceId;
  if (activeUserId === null) return;
  if (workspaceId === null) sessionStorage.removeItem(storageKey(activeUserId));
  else sessionStorage.setItem(storageKey(activeUserId), workspaceId);
}

export function clearActiveWorkspaceId(): void {
  activeWorkspaceId = null;
}

export function getActiveWorkspaceId(): string | null {
  return activeWorkspaceId;
}

export function getPreferredWorkspaceId(): string | null {
  return activeUserId === null ? null : sessionStorage.getItem(storageKey(activeUserId));
}

export function buildWorkspaceScopedUrl(
  path: string,
  extraParams?: Readonly<Record<string, string>>
): string {
  if (path === "") return path;
  const url = new URL(path, window.location.origin);
  if (url.protocol === "data:" || url.protocol === "blob:") return path;
  if (url.origin !== window.location.origin) return path;
  if (activeWorkspaceId === null) throw new MissingWorkspaceContextError();
  for (const [key, value] of Object.entries(extraParams ?? {})) url.searchParams.set(key, value);
  url.searchParams.set("workspace_id", activeWorkspaceId);
  return `${url.pathname}${url.search}${url.hash}`;
}
