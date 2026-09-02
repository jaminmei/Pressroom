import { API_BASE_PATH, apiClient } from "@/services/api";

import type { CompactionNote, PiMessage, ToolExecution } from "@/features/chatbox/piEventAssembler";

export type ChatboxLifecycleState = "active" | "idle" | "dead";
export type AgentSessionState = "draft" | "active" | "paused" | "archived";
export type AgentRuntimeState = "stopped" | "starting" | "idle" | "running" | "failed";

export interface ChatboxSession {
  readonly session_id: string;
  readonly state: ChatboxLifecycleState;
  readonly provider_id: string;
  readonly model_id: string;
  readonly messages: readonly PiMessage[];
  readonly tool_executions: Readonly<Record<string, ToolExecution>>;
  readonly compaction_notes: readonly CompactionNote[];
  readonly live_message_id: string | null;
  readonly snapshot_revision: number;
  readonly session_state: AgentSessionState;
  readonly runtime_state: AgentRuntimeState;
  readonly runtime_generation: number;
  readonly title: string | null;
  readonly preview: string | null;
  readonly first_settled_at: string | null;
  readonly last_activity_at: string;
  readonly archived_at: string | null;
  readonly is_current: boolean;
}

export interface ChatboxSessionList {
  readonly items: readonly ChatboxSession[];
  readonly total: number;
  readonly current_session_id: string | null;
}

export interface ToolApproval {
  readonly id: string;
  readonly operation: string;
  readonly argument_summary: string;
  readonly expires_at: string;
}

export const CHATBOX_SESSIONS_API_PATH = "/chatbox/sessions";

export function chatboxSessionApiPath(sessionId: string): string {
  return `${CHATBOX_SESSIONS_API_PATH}/${sessionId}`;
}

export function chatboxSessionWebSocketPath(sessionId: string): string {
  return `${API_BASE_PATH}${chatboxSessionApiPath(sessionId)}`;
}

export async function createChatboxSession(): Promise<ChatboxSession> {
  const response = await apiClient.post<ChatboxSession>(CHATBOX_SESSIONS_API_PATH);
  return response.data;
}

export async function getChatboxSession(sessionId: string): Promise<ChatboxSession> {
  const response = await apiClient.get<ChatboxSession>(chatboxSessionApiPath(sessionId));
  return response.data;
}

export async function listChatboxSessions(
  view: "conversations" | "archived" = "conversations",
): Promise<ChatboxSessionList> {
  const response = await apiClient.get<ChatboxSessionList>(CHATBOX_SESSIONS_API_PATH, {
    params: { view },
  });
  return response.data;
}

export async function getCurrentChatboxSession(): Promise<ChatboxSession | null> {
  const response = await apiClient.get<ChatboxSession | null>(`${CHATBOX_SESSIONS_API_PATH}/current`);
  return response.data;
}

export async function activateChatboxSession(sessionId: string): Promise<ChatboxSession> {
  const response = await apiClient.post<ChatboxSession>(`${chatboxSessionApiPath(sessionId)}/activate`);
  return response.data;
}

export async function archiveChatboxSession(sessionId: string): Promise<ChatboxSession> {
  const response = await apiClient.post<ChatboxSession>(`${chatboxSessionApiPath(sessionId)}/archive`);
  return response.data;
}

export async function unarchiveChatboxSession(
  sessionId: string,
  activate = false,
): Promise<ChatboxSession> {
  const response = await apiClient.post<ChatboxSession>(
    `${chatboxSessionApiPath(sessionId)}/unarchive`,
    undefined,
    { params: { activate } },
  );
  return response.data;
}

export async function deleteArchivedChatboxSession(
  sessionId: string,
): Promise<{ success: boolean }> {
  const response = await apiClient.delete<{ success: boolean }>(chatboxSessionApiPath(sessionId));
  return response.data;
}

export async function pauseChatboxSession(sessionId: string): Promise<ChatboxSession> {
  const response = await apiClient.post<ChatboxSession>(`${chatboxSessionApiPath(sessionId)}/pause`);
  return response.data;
}

export async function suspendChatboxSession(sessionId: string, workspaceId: string): Promise<ChatboxSession> {
  const response = await apiClient.post<ChatboxSession>(
    `${chatboxSessionApiPath(sessionId)}/suspend`,
    undefined,
    { params: { workspace_id: workspaceId } },
  );
  return response.data;
}

export async function listToolApprovals(sessionId: string): Promise<readonly ToolApproval[]> {
  const response = await apiClient.get<{ readonly items: readonly ToolApproval[] }>(
    `${chatboxSessionApiPath(sessionId)}/approvals`,
  );
  return response.data.items;
}

export async function decideToolApproval(
  sessionId: string,
  approvalId: string,
  approved: boolean,
): Promise<ToolApproval> {
  const action = approved ? "approve" : "reject";
  const response = await apiClient.post<ToolApproval>(
    `${chatboxSessionApiPath(sessionId)}/approvals/${approvalId}/${action}`,
  );
  return response.data;
}

export async function restartChatboxSession(sessionId: string): Promise<ChatboxSession> {
  const response = await apiClient.post<ChatboxSession>(`${chatboxSessionApiPath(sessionId)}/restart`);
  return response.data;
}
