export type WorkspaceRole = "owner" | "admin" | "editor" | "runner" | "viewer";

export interface WorkspaceRoleDescriptor {
  role: WorkspaceRole;
  label: string;
  summary: string;
  can: string[];
  cannot: string[];
  isDangerousToAssign?: boolean;
}

export type WorkspaceCapability =
  | "workspace.view"
  | "workspace.create"
  | "workspace.update"
  | "workspace.delete"
  | "workspace.transfer_owner"
  | "members.view"
  | "members.invite"
  | "members.update_role"
  | "members.remove"
  | "workflow.view"
  | "workflow.create"
  | "workflow.edit_draft"
  | "workflow.import"
  | "workflow.delete"
  | "workflow.publish"
  | "workflow.restore"
  | "workflow.run"
  | "file.view"
  | "file.upload"
  | "file.delete"
  | "database.view"
  | "database.create"
  | "database.update"
  | "database.delete"
  | "document.upload"
  | "document.delete"
  | "ground_truth.view"
  | "ground_truth.edit"
  | "ground_truth.accept_reject"
  | "run.view"
  | "run.create"
  | "run.cancel"
  | "run.rerun"
  | "comparison.refresh"
  | "provider.view"
  | "provider.use"
  | "provider.manage"
  | "api_key.view"
  | "api_key.manage"
  | "api_usage.view"
  | "audit.view";

export interface CapabilityDescriptor {
  capability: WorkspaceCapability;
  label: string;
  description: string;
  allowedRoles: WorkspaceRole[];
}

export interface WorkspaceSummary {
  id: string;
  name: string;
  description?: string | null;
  isDefault: boolean;
  role: WorkspaceRole;
  capabilities: WorkspaceCapability[];
  memberCount?: number;
  workflowCount?: number;
  databaseCount?: number;
  providerCount?: number;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface WorkspaceMembership {
  workspace: WorkspaceSummary;
  role: WorkspaceRole;
  capabilities: WorkspaceCapability[];
  joinedAt?: string | null;
}

export interface WorkspaceSession {
  currentWorkspace: WorkspaceSummary | null;
  memberships: WorkspaceMembership[];
  capabilities: WorkspaceCapability[];
}

export type WorkspaceMemberStatus = "active" | "pending" | "disabled";

export interface WorkspaceMember {
  userId: string;
  email: string;
  name?: string | null;
  role: WorkspaceRole;
  status: WorkspaceMemberStatus;
  joinedAt?: string | null;
  invitedAt?: string | null;
  lastActiveAt?: string | null;
  isCurrentUser?: boolean;
}

export interface ListWorkspaceMembersResponse {
  items: WorkspaceMember[];
  total: number;
}

export interface InviteWorkspaceMemberRequest {
  email: string;
  role: WorkspaceRole;
}

export interface ChangeWorkspaceMemberRoleRequest {
  role: WorkspaceRole;
}

export interface RemoveWorkspaceMemberRequest {
  userId: string;
}

export interface CreateWorkspaceRequest {
  name: string;
  description?: string | null;
}

export interface UpdateWorkspaceRequest {
  name?: string;
  description?: string | null;
  isDefault?: boolean;
}

export interface SwitchWorkspaceRequest {
  workspaceId: string;
}

export interface TransferWorkspaceOwnerRequest {
  newOwnerUserId: string;
}

export type WorkspaceAuditEventType =
  | "workspace.created"
  | "workspace.updated"
  | "workspace.deleted"
  | "member.invited"
  | "member.role_changed"
  | "member.removed"
  | "provider.created"
  | "provider.updated"
  | "provider.deleted"
  | "api_key.issued"
  | "api_key.revoked";

export interface WorkspaceAuditEvent {
  id: string;
  type: WorkspaceAuditEventType;
  actor?: {
    userId: string;
    email: string;
    name?: string | null;
  } | null;
  target?: {
    type: "workspace" | "member" | "provider" | "api_key" | "workflow" | "database";
    id: string;
    label?: string | null;
  } | null;
  message: string;
  createdAt: string;
}

export interface ListWorkspaceAuditEventsResponse {
  items: WorkspaceAuditEvent[];
  total: number;
}

export interface PermissionRequirement {
  capability: WorkspaceCapability;
  allowedRoles: WorkspaceRole[];
  label: string;
}

export interface PermissionDecision {
  allowed: boolean;
  capability: WorkspaceCapability;
  currentRole?: WorkspaceRole | null;
  allowedRoles: WorkspaceRole[];
  reason?: string;
}

export const WORKSPACE_ROLES: WorkspaceRoleDescriptor[] = [
  {
    role: "owner",
    label: "Owner",
    summary: "Final owner. Can transfer ownership, delete workspace, and manage all settings.",
    can: ["manage all settings", "transfer ownership", "delete workspace"],
    cannot: []
  },
  {
    role: "admin",
    label: "Admin",
    summary: "Daily admin. Can manage members, providers, publishing, and API keys.",
    can: ["manage members", "manage providers", "manage api keys", "publish workflows"],
    cannot: ["transfer ownership", "delete workspace"]
  },
  {
    role: "editor",
    label: "Editor",
    summary: "Builder. Can edit workflows, databases, documents, GT, and run evaluations.",
    can: ["edit workflows", "edit databases", "edit documents", "run evaluations"],
    cannot: ["manage members", "manage providers", "manage api keys", "delete workspace"]
  },
  {
    role: "runner",
    label: "Runner",
    summary: "Operator. Can run workflows/evaluations and view results, but cannot edit resources.",
    can: ["run workflows", "run evaluations", "view results"],
    cannot: ["edit resources", "manage members", "manage providers"]
  },
  {
    role: "viewer",
    label: "Viewer",
    summary: "Read-only member. Can view resources and results, but cannot run or mutate.",
    can: ["view resources", "view results"],
    cannot: ["run workflows", "edit resources", "manage members", "manage providers"]
  }
];

export const CAPABILITY_MATRIX: Record<WorkspaceCapability, WorkspaceRole[]> = {
  "workspace.view": ["owner", "admin", "editor", "runner", "viewer"],
  "workspace.create": ["owner", "admin", "editor", "runner", "viewer"],
  "workspace.update": ["owner", "admin"],
  "workspace.delete": ["owner"],
  "workspace.transfer_owner": ["owner"],
  "members.view": ["owner", "admin", "editor", "runner", "viewer"],
  "members.invite": ["owner", "admin"],
  "members.update_role": ["owner", "admin"],
  "members.remove": ["owner", "admin"],
  "workflow.view": ["owner", "admin", "editor", "runner", "viewer"],
  "workflow.create": ["owner", "admin", "editor"],
  "workflow.edit_draft": ["owner", "admin", "editor"],
  "workflow.import": ["owner", "admin", "editor"],
  "workflow.delete": ["owner", "admin"],
  "workflow.publish": ["owner", "admin"],
  "workflow.restore": ["owner", "admin"],
  "workflow.run": ["owner", "admin", "editor", "runner"],
  "file.view": ["owner", "admin", "editor", "runner", "viewer"],
  "file.upload": ["owner", "admin", "editor", "runner"],
  "file.delete": ["owner", "admin", "editor"],
  "database.view": ["owner", "admin", "editor", "runner", "viewer"],
  "database.create": ["owner", "admin", "editor"],
  "database.update": ["owner", "admin", "editor"],
  "database.delete": ["owner", "admin", "editor"],
  "document.upload": ["owner", "admin", "editor"],
  "document.delete": ["owner", "admin", "editor"],
  "ground_truth.view": ["owner", "admin", "editor", "runner", "viewer"],
  "ground_truth.edit": ["owner", "admin", "editor"],
  "ground_truth.accept_reject": ["owner", "admin", "editor"],
  "run.view": ["owner", "admin", "editor", "runner", "viewer"],
  "run.create": ["owner", "admin", "editor", "runner"],
  "run.cancel": ["owner", "admin", "editor", "runner"],
  "run.rerun": ["owner", "admin", "editor", "runner"],
  "comparison.refresh": ["owner", "admin", "editor", "runner"],
  "provider.view": ["owner", "admin", "editor", "runner", "viewer"],
  "provider.use": ["owner", "admin", "editor", "runner"],
  "provider.manage": ["owner", "admin"],
  "api_key.view": ["owner", "admin"],
  "api_key.manage": ["owner", "admin"],
  "api_usage.view": ["owner", "admin"],
  "audit.view": ["owner", "admin"]
};

export const ALL_CAPABILITIES: readonly WorkspaceCapability[] = [
  "workspace.view",
  "workspace.create",
  "workspace.update",
  "workspace.delete",
  "workspace.transfer_owner",
  "members.view",
  "members.invite",
  "members.update_role",
  "members.remove",
  "workflow.view",
  "workflow.create",
  "workflow.edit_draft",
  "workflow.import",
  "workflow.delete",
  "workflow.publish",
  "workflow.restore",
  "workflow.run",
  "file.view",
  "file.upload",
  "file.delete",
  "database.view",
  "database.create",
  "database.update",
  "database.delete",
  "document.upload",
  "document.delete",
  "ground_truth.view",
  "ground_truth.edit",
  "ground_truth.accept_reject",
  "run.view",
  "run.create",
  "run.cancel",
  "run.rerun",
  "comparison.refresh",
  "provider.view",
  "provider.use",
  "provider.manage",
  "api_key.view",
  "api_key.manage",
  "api_usage.view",
  "audit.view"
];
