import capabilityFixture from "@/contracts/workspace-permission-v1.json";
import { apiClient } from "@/services/api";
import { getPreferredWorkspaceId } from "@/services/workspaceTransport";
import { ALL_CAPABILITIES } from "@/types/workspace";
import type {
  WorkspaceSession,
  WorkspaceSummary,
  WorkspaceMembership,
  WorkspaceMember,
  ListWorkspaceMembersResponse,
  ListWorkspaceAuditEventsResponse,
  CreateWorkspaceRequest,
  UpdateWorkspaceRequest,
  SwitchWorkspaceRequest,
  TransferWorkspaceOwnerRequest,
  InviteWorkspaceMemberRequest,
  ChangeWorkspaceMemberRoleRequest,
  WorkspaceRole,
  WorkspaceCapability,
  WorkspaceMemberStatus,
  WorkspaceAuditEventType,
  WorkspaceAuditEvent,
} from "@/types/workspace";

interface BackendWorkspaceSummary {
  id: string;
  name: string;
  description?: string | null;
  is_default: boolean;
  role: string;
  capabilities: string[];
  member_count?: number;
  workflow_count?: number;
  database_count?: number;
  provider_count?: number;
  created_at?: string | null;
  updated_at?: string | null;
}

interface BackendWorkspaceMembership {
  workspace: BackendWorkspaceSummary;
  role: string;
  capabilities: string[];
  joined_at?: string | null;
}

interface BackendWorkspaceSession {
  current_workspace: BackendWorkspaceSummary | null;
  memberships: BackendWorkspaceMembership[];
  capabilities: string[];
}

interface BackendWorkspaceMember {
  user_id: string;
  email: string;
  name?: string | null;
  role: string;
  status: string;
  joined_at?: string | null;
  invited_at?: string | null;
  last_active_at?: string | null;
  is_current_user?: boolean;
}

interface BackendWorkspaceAuditEvent {
  id: string;
  type: string;
  actor?: {
    user_id: string;
    email: string;
    name?: string | null;
  } | null;
  target?: {
    type: string;
    id: string;
    label?: string | null;
  } | null;
  message: string;
  created_at: string;
}

export interface WorkspaceDeletionImpact {
  canDelete: boolean;
  counts: {
    membersExcludingOwner: number;
    workflows: number;
    databases: number;
    evaluationRuns: number;
    taskRuns: number;
    workspaceProviders: number;
  };
}

const SAME_NAME_CAPABILITIES = new Set(capabilityFixture.same_name);
const CAPABILITY_DERIVATIONS: Readonly<Record<string, readonly string[]>> =
  capabilityFixture.derivations;

export function canAuthenticatedGlobal(capability: WorkspaceCapability): boolean {
  return capabilityFixture.authenticated_global.includes(capability);
}

export function adaptCapabilities(backendCaps: string[]): WorkspaceCapability[] {
  const capabilities = new Set<WorkspaceCapability>();
  for (const backendCapability of backendCaps) {
    const sameNameCapability = ALL_CAPABILITIES.find(
      (capability) => capability === backendCapability && SAME_NAME_CAPABILITIES.has(capability),
    );
    if (sameNameCapability !== undefined) capabilities.add(sameNameCapability);

    const derivedCapabilities = Object.prototype.hasOwnProperty.call(CAPABILITY_DERIVATIONS, backendCapability)
      ? CAPABILITY_DERIVATIONS[backendCapability as keyof typeof CAPABILITY_DERIVATIONS]
      : undefined;
    for (const derivedCapability of derivedCapabilities ?? []) {
      const capability = ALL_CAPABILITIES.find((approved) => approved === derivedCapability);
      if (capability !== undefined) capabilities.add(capability);
    }
  }
  return [...capabilities];
}

export function describeCapabilityDrift(backendCaps: string[]): string[] {
  return [...new Set(backendCaps.filter(
    (capability) => ![...SAME_NAME_CAPABILITIES].some((approved) => approved === capability)
      && !Object.prototype.hasOwnProperty.call(CAPABILITY_DERIVATIONS, capability),
  ))];
}

function mapWorkspaceSummary(b: BackendWorkspaceSummary): WorkspaceSummary {
  return {
    id: b.id,
    name: b.name,
    description: b.description,
    isDefault: b.is_default,
    role: b.role as WorkspaceRole,
    capabilities: adaptCapabilities(b.capabilities),
    memberCount: b.member_count,
    workflowCount: b.workflow_count,
    databaseCount: b.database_count,
    providerCount: b.provider_count,
    createdAt: b.created_at,
    updatedAt: b.updated_at,
  };
}

function mapWorkspaceMembership(b: BackendWorkspaceMembership): WorkspaceMembership {
  return {
    workspace: mapWorkspaceSummary(b.workspace),
    role: b.role as WorkspaceRole,
    capabilities: adaptCapabilities(b.capabilities),
    joinedAt: b.joined_at,
  };
}

function mapWorkspaceSession(b: BackendWorkspaceSession): WorkspaceSession {
  return {
    currentWorkspace: b.current_workspace ? mapWorkspaceSummary(b.current_workspace) : null,
    memberships: b.memberships.map(mapWorkspaceMembership),
    capabilities: adaptCapabilities(b.capabilities),
  };
}

function mapWorkspaceMember(b: BackendWorkspaceMember): WorkspaceMember {
  return {
    userId: b.user_id,
    email: b.email,
    name: b.name,
    role: b.role as WorkspaceRole,
    status: b.status as WorkspaceMemberStatus,
    joinedAt: b.joined_at,
    invitedAt: b.invited_at,
    lastActiveAt: b.last_active_at,
    isCurrentUser: b.is_current_user,
  };
}

function mapWorkspaceAuditEvent(b: BackendWorkspaceAuditEvent): WorkspaceAuditEvent {
  return {
    id: b.id,
    type: b.type as WorkspaceAuditEventType,
    actor: b.actor
      ? {
          userId: b.actor.user_id,
          email: b.actor.email,
          name: b.actor.name,
        }
      : null,
    target: b.target
      ? {
          type: b.target.type as "workspace" | "member" | "provider" | "api_key" | "workflow" | "database",
          id: b.target.id,
          label: b.target.label,
        }
      : null,
    message: b.message,
    createdAt: b.created_at,
  };
}

export async function getWorkspaceSession(): Promise<WorkspaceSession> {
  const workspaceId = getPreferredWorkspaceId();
  const response = workspaceId === null
    ? await apiClient.get<BackendWorkspaceSession>("/workspaces/session")
    : await apiClient.get<BackendWorkspaceSession>("/workspaces/session", {
        params: { workspace_id: workspaceId }
      });
  return mapWorkspaceSession(response.data);
}

export async function listWorkspaces(): Promise<WorkspaceSummary[]> {
  const response = await apiClient.get<{ items: BackendWorkspaceSummary[]; total?: number }>("/workspaces");
  return response.data.items.map(mapWorkspaceSummary);
}

export async function switchWorkspace(payload: SwitchWorkspaceRequest): Promise<WorkspaceSession> {
  const response = await apiClient.post<BackendWorkspaceSession>(`/workspaces/${payload.workspaceId}/switch`);
  return mapWorkspaceSession(response.data);
}

export async function createWorkspace(payload: CreateWorkspaceRequest): Promise<WorkspaceSummary> {
  const response = await apiClient.post<BackendWorkspaceSummary>("/workspaces", {
    name: payload.name,
    description: payload.description ?? null,
  });
  return mapWorkspaceSummary(response.data);
}

export async function updateWorkspace(workspaceId: string, payload: UpdateWorkspaceRequest): Promise<WorkspaceSummary> {
  const body: Record<string, unknown> = {};
  if (payload.name !== undefined) body.name = payload.name;
  if (payload.description !== undefined) body.description = payload.description;
  if (payload.isDefault !== undefined) body.is_default = payload.isDefault;

  const response = await apiClient.patch<BackendWorkspaceSummary>(`/workspaces/${workspaceId}`, body);
  return mapWorkspaceSummary(response.data);
}

export async function deleteWorkspace(workspaceId: string): Promise<void> {
  await apiClient.delete(`/workspaces/${workspaceId}`);
}

export async function getWorkspaceDeletionImpact(workspaceId: string): Promise<WorkspaceDeletionImpact> {
  const response = await apiClient.get<{
    can_delete: boolean;
    counts: {
      members_excluding_owner: number;
      workflows: number;
      databases: number;
      evaluation_runs: number;
      task_runs: number;
      workspace_providers: number;
    };
  }>(`/workspaces/${workspaceId}/deletion-impact`);
  return {
    canDelete: response.data.can_delete,
    counts: {
      membersExcludingOwner: response.data.counts.members_excluding_owner,
      workflows: response.data.counts.workflows,
      databases: response.data.counts.databases,
      evaluationRuns: response.data.counts.evaluation_runs,
      taskRuns: response.data.counts.task_runs,
      workspaceProviders: response.data.counts.workspace_providers,
    },
  };
}

export async function transferWorkspaceOwner(workspaceId: string, payload: TransferWorkspaceOwnerRequest): Promise<WorkspaceSummary> {
  const response = await apiClient.post<BackendWorkspaceSummary>(`/workspaces/${workspaceId}/transfer-owner`, {
    new_owner_user_id: payload.newOwnerUserId,
  });
  return mapWorkspaceSummary(response.data);
}

export async function listWorkspaceMembers(workspaceId: string): Promise<ListWorkspaceMembersResponse> {
  const response = await apiClient.get<{ items: BackendWorkspaceMember[]; total: number }>(`/workspaces/${workspaceId}/members`);
  return {
    items: response.data.items.map(mapWorkspaceMember),
    total: response.data.total,
  };
}

export async function inviteWorkspaceMember(workspaceId: string, payload: InviteWorkspaceMemberRequest): Promise<WorkspaceMember> {
  const response = await apiClient.post<BackendWorkspaceMember>(`/workspaces/${workspaceId}/members`, {
    email: payload.email,
    role: payload.role,
  });
  return mapWorkspaceMember(response.data);
}

export async function changeWorkspaceMemberRole(workspaceId: string, userId: string, payload: ChangeWorkspaceMemberRoleRequest): Promise<WorkspaceMember> {
  const response = await apiClient.patch<BackendWorkspaceMember>(`/workspaces/${workspaceId}/members/${userId}`, {
    role: payload.role,
  });
  return mapWorkspaceMember(response.data);
}

export async function removeWorkspaceMember(workspaceId: string, userId: string): Promise<void> {
  await apiClient.delete(`/workspaces/${workspaceId}/members/${userId}`);
}

export async function listWorkspaceAuditEvents(workspaceId: string, params?: { limit?: number; cursor?: string }): Promise<ListWorkspaceAuditEventsResponse> {
  const response = await apiClient.get<{ items: BackendWorkspaceAuditEvent[]; total: number }>(`/workspaces/${workspaceId}/audit-events`, { params });
  return {
    items: response.data.items.map(mapWorkspaceAuditEvent),
    total: response.data.total,
  };
}
