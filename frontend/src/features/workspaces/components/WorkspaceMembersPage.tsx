import { useEffect, useState } from "react";
import { Alert, Button, Empty, Input, message, Select } from "antd";
import { QuestionCircleOutlined, SearchOutlined, UserAddOutlined } from "@ant-design/icons";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { CapabilityMatrixDrawer } from "@/components/Permissions/CapabilityMatrixDrawer";
import { PermissionButton } from "@/components/Permissions/PermissionButton";
import { usePermission } from "@/hooks/usePermission";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { InviteWorkspaceMemberRequest, WorkspaceMember, WorkspaceRole } from "@/types/workspace";
import { useWorkspaceMembers } from "../hooks/useWorkspaceMembers";

import { AddWorkspaceMemberDialog } from "./AddWorkspaceMemberDialog";
import { ChangeWorkspaceRoleDialog } from "./ChangeWorkspaceRoleDialog";
import { RemoveWorkspaceMemberDialog } from "./RemoveWorkspaceMemberDialog";
import { WorkspaceMembersTable } from "./WorkspaceMembersTable";

export default function WorkspaceMembersPage() {
  const { t } = useTranslation(["common", "workspaces"]);
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const { members, total, loading, error, inviteMember, changeRole, removeMember, refresh } = useWorkspaceMembers(
    currentWorkspace?.id || ""
  );
  const { can, explain } = usePermission();
  const [searchParams, setSearchParams] = useSearchParams();

  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<WorkspaceRole | "all">("all");
  const [matrixOpen, setMatrixOpen] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [submittingInvite, setSubmittingInvite] = useState(false);
  const [changingMember, setChangingMember] = useState<WorkspaceMember | null>(null);
  const [submittingChange, setSubmittingChange] = useState(false);
  const [removingMember, setRemovingMember] = useState<WorkspaceMember | null>(null);
  const [submittingRemove, setSubmittingRemove] = useState(false);

  const canInvite = can("members.invite");
  const canChangeRole = can("members.update_role");
  const canRemove = can("members.remove");
  const inviteReason = canInvite ? undefined : explain("members.invite").reason;
  const inviteRequested = searchParams.get("action") === "invite";

  useEffect(() => {
    if (!inviteRequested) return;

    if (canInvite) setInviteOpen(true);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.delete("action");
    setSearchParams(nextParams, { replace: true });
  }, [canInvite, inviteRequested, searchParams, setSearchParams]);

  const filteredMembers = members.filter((member) => {
    const searchable = `${member.email} ${member.name || ""}`.toLowerCase();
    const matchesSearch = searchable.includes(search.trim().toLowerCase());
    const matchesRole = roleFilter === "all" || member.role === roleFilter;
    return matchesSearch && matchesRole;
  });

  const handleInvite = async (payload: InviteWorkspaceMemberRequest) => {
    try {
      setSubmittingInvite(true);
      await inviteMember(payload);
      message.success(t("workspaces:invited"));
      setInviteOpen(false);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : t("workspaces:inviteFailed"));
    } finally {
      setSubmittingInvite(false);
    }
  };

  const handleChangeRole = async (role: WorkspaceRole) => {
    if (!changingMember) return;
    try {
      setSubmittingChange(true);
      await changeRole(changingMember.userId, role);
      message.success(t("workspaces:roleUpdated"));
      setChangingMember(null);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : t("workspaces:roleChangeFailed"));
    } finally {
      setSubmittingChange(false);
    }
  };

  const handleRemove = async () => {
    if (!removingMember) return;
    try {
      setSubmittingRemove(true);
      await removeMember(removingMember.userId);
      message.success(t("workspaces:memberRemoved"));
      setRemovingMember(null);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : t("workspaces:removeFailed"));
    } finally {
      setSubmittingRemove(false);
    }
  };

  if (!currentWorkspace) return null;

  return (
    <div className="workspace-page-stack workspace-members-page">
      <section className="workspace-panel" aria-labelledby="workspace-members-title">
        <div className="workspace-panel-head workspace-members-heading">
          <div>
            <div className="workspace-title-with-count">
              <h2 id="workspace-members-title">{t("workspaces:membersRolesTitle")}</h2>
              <span>{total}</span>
            </div>
            <p>{t("workspaces:membersDescription")}</p>
          </div>
          <div className="workspace-members-heading-actions">
            <Button icon={<QuestionCircleOutlined />} onClick={() => setMatrixOpen(true)}>
              {t("workspaces:rolesPermissions")}
            </Button>
            <PermissionButton
              capability="members.invite"
              icon={<UserAddOutlined />}
              onClick={() => setInviteOpen(true)}
              type="primary"
            >
              {t("workspaces:inviteMember")}
            </PermissionButton>
          </div>
        </div>

        <div className="workspace-members-toolbar">
          <Input
            allowClear
            aria-label={t("workspaces:searchMembers")}
            placeholder={t("workspaces:searchMembers")}
            prefix={<SearchOutlined />}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <Select
            aria-label={t("workspaces:filterRole")}
            data-testid="member-role-filter"
            value={roleFilter}
            onChange={setRoleFilter}
            options={[
              { value: "all", label: t("workspaces:allRoles") },
              { value: "owner", label: t("workspaces:owner") },
              { value: "admin", label: t("workspaces:admin") },
              { value: "editor", label: t("workspaces:editor") },
              { value: "runner", label: t("workspaces:runner") },
              { value: "viewer", label: t("workspaces:viewer") },
            ]}
          />
        </div>

        {!canInvite && inviteReason ? (
          <p className="workspace-permission-note">{t("workspaces:invitePermission", { reason: inviteReason })}</p>
        ) : null}

        <div className="workspace-members-body">
          {error ? (
            <Alert
              action={<Button onClick={() => void refresh()}>{t("common:retry")}</Button>}
              data-testid="workspace-members-error"
              description={error}
              message={t("workspaces:couldNotLoadMembers")}
              showIcon
              type="warning"
            />
          ) : !loading && members.length === 0 ? (
            <Empty
              data-testid="workspace-members-empty"
              description={t("workspaces:noMembers")}
            />
          ) : !loading && filteredMembers.length === 0 ? (
            <Empty
              data-testid="workspace-members-no-results"
              description={t("workspaces:noMemberMatches")}
            />
          ) : (
            <WorkspaceMembersTable
              canChangeRole={canChangeRole}
              canRemove={canRemove}
              loading={loading}
              members={filteredMembers}
              onChangeRole={setChangingMember}
              onRemoveMember={setRemovingMember}
            />
          )}
        </div>
      </section>

      <AddWorkspaceMemberDialog
        onCancel={() => setInviteOpen(false)}
        onSubmit={handleInvite}
        open={inviteOpen}
        submitting={submittingInvite}
      />
      <ChangeWorkspaceRoleDialog
        member={changingMember}
        onCancel={() => setChangingMember(null)}
        onSubmit={handleChangeRole}
        open={!!changingMember}
        submitting={submittingChange}
      />
      <RemoveWorkspaceMemberDialog
        member={removingMember}
        onCancel={() => setRemovingMember(null)}
        onConfirm={handleRemove}
        open={!!removingMember}
        submitting={submittingRemove}
      />
      <CapabilityMatrixDrawer onClose={() => setMatrixOpen(false)} open={matrixOpen} />
    </div>
  );
}
