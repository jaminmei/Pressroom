import { useRef, useState } from "react";
import {
  ApiOutlined,
  DownOutlined,
  ExclamationCircleOutlined,
  HistoryOutlined,
  LoadingOutlined,
  PlusOutlined,
  SettingOutlined,
  TeamOutlined,
  UpOutlined,
} from "@ant-design/icons";
import { Alert, Button, Dropdown, Modal, Tooltip } from "antd";
import type { MenuProps } from "antd";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { RoleBadge } from "@/components/Permissions/RoleBadge";
import { useWorkflowPersistence } from "@/features/workflow-editor/hooks/useWorkflowPersistence";
import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";
import { usePermission } from "@/hooks/usePermission";
import { canAuthenticatedGlobal } from "@/services/workspaceApi";
import {
  useWorkspaceStore,
  WorkspaceSwitchBlockedError,
  type WorkspaceSwitchBlockedReason
} from "@/stores/workspaceStore";
import {
  WORKSPACE_ROLES,
  type WorkspaceCapability,
  type WorkspaceMembership,
  type WorkspaceRole,
  type WorkspaceSummary,
} from "@/types/workspace";

export interface WorkspaceSwitcherProps {
  currentWorkspace: WorkspaceSummary | null;
  memberships: WorkspaceMembership[];
  loading?: boolean;
  switching?: boolean;
  error?: string | null;
  onSwitchWorkspace: (workspaceId: string) => void | Promise<void>;
  onRetry?: () => void | Promise<void>;
  onOpenMembers: () => void;
  onOpenProviders: () => void;
  onOpenAudit: () => void;
  onOpenSettings: () => void;
  onCreateWorkspace: () => void;
}

function getWorkspaceInitials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length > 1) {
    return words.slice(0, 2).map((word) => word[0]).join("").toUpperCase();
  }
  return (words[0] || "?").slice(0, 2).toUpperCase();
}

function getRoleLabel(role: WorkspaceRole, t: TFunction): string {
  return t(`workspaces:${role}`, {
    defaultValue: WORKSPACE_ROLES.find((descriptor) => descriptor.role === role)?.label ?? role
  });
}

function getWorkspaceMeta(workspace: WorkspaceSummary, t: TFunction): string {
  return t("layout:workspaceMenu.roleAccess", { role: getRoleLabel(workspace.role, t) });
}

const workspaceSettingsCapabilities: Readonly<Record<string, WorkspaceCapability>> = {
  members: "members.view",
  providers: "provider.view",
  audit: "audit.view",
  general: "workspace.update",
};

export function resolveWorkspaceSwitchPath(
  pathname: string,
  capabilities: readonly WorkspaceCapability[],
): string | null {
  if (/^\/(?:workflows\/[^/]+(?:\/api-access)?|tasks\/[^/]+\/results)\/?$/.test(pathname)) {
    return "/studio";
  }
  if (/^\/(?:database|projects)\/[^/]+(?:\/run)?\/?$/.test(pathname)) {
    return "/database";
  }
  const settingsSubpage = pathname.match(/^\/settings\/workspace\/([^/]+)\/?$/)?.[1];
  const requiredCapability = settingsSubpage ? workspaceSettingsCapabilities[settingsSubpage] : undefined;
  return requiredCapability && !capabilities.includes(requiredCapability) ? "/settings/workspace" : null;
}

export function WorkspaceSwitcher({
  currentWorkspace,
  memberships,
  loading = false,
  switching = false,
  error,
  onSwitchWorkspace,
  onRetry,
  onOpenMembers,
  onOpenProviders,
  onOpenAudit,
  onOpenSettings,
  onCreateWorkspace,
}: WorkspaceSwitcherProps) {
  const { t } = useTranslation(["common", "layout", "workflows", "workspaces"]);
  const navigate = useNavigate();
  const { explain } = usePermission();
  const resetWorkflowPersistence = useWorkflowPersistenceStore((state) => state.reset);
  const { saveDraft } = useWorkflowPersistence();
  const triggerRef = useRef<HTMLButtonElement>(null);

  const [open, setOpen] = useState(false);
  const [blockedTargetId, setBlockedTargetId] = useState<string | null>(null);
  const [blockedReason, setBlockedReason] = useState<WorkspaceSwitchBlockedReason | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [failedTargetId, setFailedTargetId] = useState<string | null>(null);

  const navigateAfterSwitch = () => {
    const nextPath = resolveWorkspaceSwitchPath(
      window.location.pathname,
      useWorkspaceStore.getState().capabilities,
    );
    if (nextPath) navigate(nextPath);
  };

  const restoreTriggerFocus = () => {
    window.setTimeout(() => triggerRef.current?.focus(), 0);
  };

  const closeMenu = (restoreFocus = false) => {
    setOpen(false);
    if (restoreFocus) restoreTriggerFocus();
  };

  const handleSwitch = async (workspaceId: string) => {
    if (workspaceId === currentWorkspace?.id) return;

    closeMenu();
    try {
      setSwitchError(null);
      setFailedTargetId(null);
      await onSwitchWorkspace(workspaceId);
      navigateAfterSwitch();
    } catch (errorObj: unknown) {
      if (
        errorObj instanceof WorkspaceSwitchBlockedError ||
        (errorObj instanceof Error && errorObj.name === "WorkspaceSwitchBlockedError")
      ) {
        setBlockedTargetId(workspaceId);
        setBlockedReason(
          errorObj instanceof WorkspaceSwitchBlockedError ? errorObj.reason : "unsaved_changes"
        );
      } else {
        setSwitchError(errorObj instanceof Error ? errorObj.message : t("layout:workspaceMenu.switchFailed"));
        setFailedTargetId(workspaceId);
        setOpen(true);
      }
    }
  };

  const handleDiscardAndSwitch = async () => {
    if (!blockedTargetId) return;
    const previousPersistenceState = useWorkflowPersistenceStore.getState();
    resetWorkflowPersistence();
    const target = blockedTargetId;
    setBlockedTargetId(null);
    setBlockedReason(null);
    setSaveError(null);
    try {
      await onSwitchWorkspace(target);
      navigateAfterSwitch();
    } catch (errorObj: unknown) {
      useWorkflowPersistenceStore.setState(previousPersistenceState, true);
      if (
        errorObj instanceof WorkspaceSwitchBlockedError ||
        (errorObj instanceof Error && errorObj.name === "WorkspaceSwitchBlockedError")
      ) {
        setBlockedTargetId(target);
        setBlockedReason(
          errorObj instanceof WorkspaceSwitchBlockedError ? errorObj.reason : "unsaved_changes"
        );
      } else {
        setSwitchError(errorObj instanceof Error ? errorObj.message : t("layout:workspaceMenu.switchFailed"));
        setFailedTargetId(target);
        setOpen(true);
      }
    }
  };

  const handleSaveAndSwitch = async () => {
    if (!blockedTargetId) return;
    const target = blockedTargetId;

    try {
      const success = await saveDraft();
      if (!success) {
        setSaveError(t("layout:workspaceMenu.saveDraftFailed"));
        return;
      }
    } catch {
      setSaveError(t("layout:workspaceMenu.saveDraftError"));
      return;
    }

    setBlockedTargetId(null);
    setBlockedReason(null);
    setSaveError(null);
    try {
      await onSwitchWorkspace(target);
      navigateAfterSwitch();
    } catch (errorObj: unknown) {
      if (
        errorObj instanceof WorkspaceSwitchBlockedError ||
        (errorObj instanceof Error && errorObj.name === "WorkspaceSwitchBlockedError")
      ) {
        setBlockedTargetId(target);
        setBlockedReason(
          errorObj instanceof WorkspaceSwitchBlockedError ? errorObj.reason : "unsaved_changes"
        );
        setSaveError(t("layout:workspaceMenu.stillUnsaved"));
      } else {
        setSwitchError(errorObj instanceof Error ? errorObj.message : t("layout:workspaceMenu.switchFailed"));
        setFailedTargetId(target);
        setOpen(true);
      }
    }
  };

  const handleCancelBlock = () => {
    setBlockedTargetId(null);
    setBlockedReason(null);
    setSaveError(null);
    restoreTriggerFocus();
  };

  const handleRetry = async () => {
    if (failedTargetId) {
      await handleSwitch(failedTargetId);
      return;
    }
    setSwitchError(null);
    await onRetry?.();
  };

  const isEmpty = memberships.length === 0;
  const isRevoked = !currentWorkspace && !isEmpty;
  const displayError = switchError || error;

  const permissionFor = (capability: WorkspaceCapability) => {
    if (isRevoked) {
      return { allowed: false, reason: t("layout:workspaceMenu.selectFirst") };
    }
    return explain(capability);
  };

  const renderManageItem = (
    key: string,
    title: string,
    description: string,
    icon: React.ReactNode,
    capability: WorkspaceCapability,
    onClick: () => void,
    trailing?: React.ReactNode,
  ) => {
    const decision = permissionFor(capability);
    const reason = decision.allowed ? undefined : decision.reason || t("layout:workspaceMenu.noPermission");
    return {
      key,
      disabled: !decision.allowed,
      onClick: decision.allowed
        ? () => {
            closeMenu();
            onClick();
          }
        : undefined,
      label: (
        <Tooltip title={reason} placement="right">
          <div className="workspace-menu-row" data-disabled-reason={reason}>
            <span className="workspace-menu-icon" aria-hidden="true">{icon}</span>
            <span className="workspace-menu-copy">
              <span className="workspace-menu-title">{title}</span>
              <span className="workspace-menu-meta">{reason || description}</span>
            </span>
            {trailing}
          </div>
        </Tooltip>
      ),
    };
  };

  const workspaceItems = memberships.map((membership) => {
    const workspace = membership.workspace;
    const role = membership.role || workspace.role;
    const isCurrent = workspace.id === currentWorkspace?.id;
    return {
      key: `ws-${workspace.id}`,
      className: isCurrent ? "workspace-menu-item-current" : undefined,
      onClick: isCurrent ? undefined : () => void handleSwitch(workspace.id),
      label: (
        <div
          className="workspace-menu-row"
          aria-current={isCurrent ? "true" : undefined}
          data-testid={`workspace-option-${workspace.id}`}
        >
          <span className="workspace-menu-icon workspace-menu-initials" aria-hidden="true">
            {getWorkspaceInitials(workspace.name)}
          </span>
          <span className="workspace-menu-copy">
            <span className="workspace-menu-title">{workspace.name}</span>
            <span className="workspace-menu-meta">
              {isCurrent ? t("layout:workspaceMenu.currentWorkspace") : getWorkspaceMeta({ ...workspace, role }, t)}
            </span>
          </span>
          <RoleBadge role={role} size="sm" />
        </div>
      ),
    };
  });

  if (isEmpty) {
    workspaceItems.push({
      key: "workspace-empty",
      className: "workspace-menu-empty-item",
      onClick: undefined,
      label: (
        <div className="workspace-menu-empty">
          <strong>{t("layout:workspaceMenu.noWorkspaces")}</strong>
          <span>{t("layout:workspaceMenu.noWorkspacesDescription")}</span>
        </div>
      ),
    } as (typeof workspaceItems)[number]);
  }

  const manageItems = [
    renderManageItem(
      "members",
      t("layout:workspaceMenu.membersRoles"),
      t("layout:workspaceMenu.membersDescription"),
      <TeamOutlined />,
      "members.view",
      onOpenMembers,
      <span className="workspace-menu-count" aria-label={t("layout:workspaceMenu.memberCount", { count: currentWorkspace?.memberCount ?? 0 })}>
        {currentWorkspace?.memberCount ?? "—"}
      </span>,
    ),
    renderManageItem(
      "providers",
      t("layout:workspaceMenu.providers"),
      t("layout:workspaceMenu.providersDescription"),
      <ApiOutlined />,
      "provider.view",
      onOpenProviders,
    ),
    renderManageItem(
      "audit",
      t("layout:workspaceMenu.audit"),
      t("layout:workspaceMenu.auditDescription"),
      <HistoryOutlined />,
      "audit.view",
      onOpenAudit,
    ),
  ];

  const menuItems: MenuProps["items"] = [
    {
      type: "group",
      key: "workspace-section",
      label: <span className="workspace-menu-section-title">{t("layout:workspaceMenu.switchWorkspace")}</span>,
      children: workspaceItems,
    },
    { type: "divider" },
    {
      type: "group",
      key: "manage-section",
      label: <span className="workspace-menu-section-title">{t("layout:workspaceMenu.manageCurrent")}</span>,
      children: manageItems,
    },
  ];

  const createDecision = canAuthenticatedGlobal("workspace.create")
    ? { allowed: true, reason: undefined }
    : permissionFor("workspace.create");
  const settingsDecision = permissionFor("workspace.view");

  const triggerName = loading
    ? t("layout:workspaceMenu.loadingWorkspaces")
    : currentWorkspace
      ? currentWorkspace.name
      : isRevoked
        ? t("layout:workspaceMenu.accessChanged")
        : t("layout:workspaceMenu.noWorkspacesShort");
  const triggerMeta = loading
    ? t("layout:workspaceMenu.loadingAccess")
    : switching
      ? t("layout:workspaceMenu.switching")
      : currentWorkspace
        ? getWorkspaceMeta(currentWorkspace, t)
        : isRevoked
          ? t("layout:workspaceMenu.selectAnother")
          : t("layout:workspaceMenu.createFirst");

  return (
    <div
      className={`workspace-switcher-root${open ? " is-open" : ""}${displayError ? " has-error" : ""}`}
      data-testid="workspace-switcher"
    >
      {displayError ? <span className="workspace-visually-hidden" role="status">{displayError}</span> : null}
      <Dropdown
        disabled={loading || switching}
        menu={{ items: menuItems, selectable: true, selectedKeys: currentWorkspace ? [`ws-${currentWorkspace.id}`] : [] }}
        onOpenChange={(nextOpen) => {
          setOpen(nextOpen);
          if (!nextOpen && open) restoreTriggerFocus();
        }}
        open={open}
        overlayClassName="workspace-switcher-overlay"
        popupRender={(menu) => (
          <div className="workspace-menu-surface" aria-label={t("layout:workspaceMenu.menu")}>
            {displayError ? (
              <Alert
                action={<Button onClick={() => void handleRetry()} size="small">{t("common:retry")}</Button>}
                className="workspace-menu-error"
                message={displayError}
                showIcon
                type="error"
              />
            ) : null}
            {menu}
            <div className="workspace-menu-footer">
              <Tooltip title={createDecision.allowed ? undefined : createDecision.reason}>
                <span>
                  <Button
                    block
                    className="workspace-menu-create"
                    disabled={!createDecision.allowed}
                    icon={<PlusOutlined />}
                    onClick={() => {
                      closeMenu();
                      onCreateWorkspace();
                    }}
                    type="primary"
                  >
                    {t("layout:workspaceMenu.newWorkspace")}
                  </Button>
                </span>
              </Tooltip>
              <Tooltip title={settingsDecision.allowed ? undefined : settingsDecision.reason}>
                <span>
                  <Button
                    block
                    disabled={!settingsDecision.allowed}
                    icon={<SettingOutlined />}
                    onClick={() => {
                      closeMenu();
                      onOpenSettings();
                    }}
                  >
                    {t("layout:workspaceMenu.settings")}
                  </Button>
                </span>
              </Tooltip>
            </div>
          </div>
        )}
        trigger={["click"]}
      >
        <button
          aria-busy={loading || switching}
          aria-expanded={open}
          aria-haspopup="menu"
          aria-label={t("layout:workspaceMenu.openFor", { name: triggerName })}
          className="workspace-switcher-trigger"
          data-testid="workspace-switcher-trigger"
          disabled={loading || switching}
          ref={triggerRef}
          type="button"
        >
          <span className="workspace-switcher-mark" aria-hidden="true">
            {loading ? <LoadingOutlined spin /> : currentWorkspace ? getWorkspaceInitials(currentWorkspace.name) : isRevoked ? "!" : "+"}
          </span>
          <span className="workspace-switcher-copy">
            <span className="workspace-switcher-name">{triggerName}</span>
            <span className="workspace-switcher-meta">{triggerMeta}</span>
          </span>
          {currentWorkspace ? <RoleBadge role={currentWorkspace.role} size="sm" /> : null}
          <span className="workspace-switcher-caret" aria-hidden="true">
            {displayError ? <ExclamationCircleOutlined /> : open ? <UpOutlined /> : switching ? <LoadingOutlined spin /> : <DownOutlined />}
          </span>
        </button>
      </Dropdown>

      <Modal
        destroyOnHidden
        footer={blockedReason === "active_execution"
          ? [
              <Button key="stay" type="primary" onClick={handleCancelBlock}>
                {t("layout:workspaceMenu.stay")}
              </Button>
            ]
          : [
              <Button key="cancel" onClick={handleCancelBlock}>
                {t("common:cancel")}
              </Button>,
              <Button key="discard" danger onClick={() => void handleDiscardAndSwitch()}>
                {t("layout:workspaceMenu.discardSwitch")}
              </Button>,
              <Button key="save" type="primary" onClick={() => void handleSaveAndSwitch()}>
                {t("layout:workspaceMenu.saveSwitch")}
              </Button>,
            ]}
        onCancel={handleCancelBlock}
        open={!!blockedTargetId}
        title={blockedReason === "active_execution" ? t("layout:workspaceMenu.activeTask") : t("layout:workspaceMenu.unsavedChanges")}
        data-testid="workspace-switch-blocked-modal"
      >
        {blockedReason === "active_execution" ? (
          <p>{t("layout:workspaceMenu.waitForTask")}</p>
        ) : (
          <>
            <p>{t("layout:workspaceMenu.unsavedDescription")}</p>
            {saveError ? <Alert message={saveError} showIcon type="error" /> : null}
          </>
        )}
      </Modal>

      <Modal
        closable={false}
        data-testid="workspace-revoked-modal"
        footer={null}
        maskClosable={false}
        open={isRevoked}
        title={t("layout:workspaceMenu.accessChanged")}
      >
        <p>{t("layout:workspaceMenu.revokedDescription")}</p>
        {displayError ? (
          <Alert
            action={<Button onClick={() => void handleRetry()} size="small">{t("common:retry")}</Button>}
            message={displayError}
            showIcon
            type="error"
          />
        ) : null}
        <div className="workspace-revoked-options">
          {memberships.map((membership) => (
            <Button
              aria-label={t("layout:workspaceMenu.switchTo", {
                name: membership.workspace.name,
                role: getRoleLabel(membership.role, t)
              })}
              key={membership.workspace.id}
              onClick={() => void handleSwitch(membership.workspace.id)}
            >
              <span>{getWorkspaceInitials(membership.workspace.name)}</span>
              <span>{membership.workspace.name}</span>
              <RoleBadge role={membership.role} size="sm" />
            </Button>
          ))}
        </div>
      </Modal>
    </div>
  );
}
