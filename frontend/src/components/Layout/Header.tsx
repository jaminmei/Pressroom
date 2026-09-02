import { useState } from "react";
import { SearchOutlined, UserOutlined } from "@ant-design/icons";
import { App as AntApp, Avatar, Button, Dropdown, Switch, theme } from "antd";
import type { MenuProps } from "antd";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";

import CorgiLogo from "@/components/Icons/CorgiLogo";
import {
  useChatboxPreferenceStore,
  useExperimentalChatboxEnabled,
} from "@/features/chatbox/chatboxPreferenceStore";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { NewWorkspaceDialog } from "@/features/workspaces/components/NewWorkspaceDialog";
import { useAuthStore } from "@/stores/authStore";
import { useUIStore } from "@/stores/uiStore";
import type { CreateWorkspaceRequest } from "@/types/workspace";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";
import { useWorkspace } from "@/hooks/useWorkspace";
import { useLanguage } from "@/i18n/useLanguage";

export default function Header() {
  const { t } = useTranslation(["common", "layout"]);
  const { language, setLanguage } = useLanguage();
  const location = useLocation();
  const navigate = useNavigate();
  const { message } = AntApp.useApp();
  const [newWorkspaceOpen, setNewWorkspaceOpen] = useState(false);
  const [creatingWorkspace, setCreatingWorkspace] = useState(false);
  const setRightPanelTab = useUIStore((state) => state.setRightPanelTab);
  const setCommandPaletteOpen = useUIStore((state) => state.setCommandPaletteOpen);
  const lastWorkflowsRoute = useUIStore((state) => state.lastWorkflowsRoute);
  const lastDatabaseRoute = useUIStore((state) => state.lastDatabaseRoute);
  const resetTaskExecution = useTaskExecutionStore((state) => state.reset);
  const currentUser = useAuthStore((state) => state.currentUser);
  const logout = useAuthStore((state) => state.logout);
  const currentUserId = currentUser?.id ?? null;
  const chatboxEnabled = useExperimentalChatboxEnabled(currentUserId);
  const setChatboxEnabled = useChatboxPreferenceStore((state) => state.setEnabled);

  const {
    currentWorkspace,
    memberships,
    status,
    isSwitching,
    error,
    switchWorkspace,
    createWorkspace,
    refresh,
  } = useWorkspace();

  const isProjectsDomain = location.pathname.startsWith("/projects") || location.pathname.startsWith("/database");
  const isSettingsDomain = location.pathname.startsWith("/settings");
  const isWorkflowsDomain = !isProjectsDomain && !isSettingsDomain;
  const { token } = theme.useToken();

  const handleCreateWorkspace = async (payload: CreateWorkspaceRequest) => {
    setCreatingWorkspace(true);
    try {
      const created = await createWorkspace(payload);
      setNewWorkspaceOpen(false);
      void message.success(t("layout:workspaceCreated", { name: created.name }));
    } catch (errorObj: unknown) {
      void message.error(errorObj instanceof Error ? errorObj.message : t("layout:workspaceCreateFailed"));
    } finally {
      setCreatingWorkspace(false);
    }
  };

  const displayName = currentUser?.name?.trim() || currentUser?.email || t("layout:authenticatedUser");

  const initials = (() => {
    const name = currentUser?.name?.trim();
    if (name) {
      const parts = name.split(/\s+/);
      if (parts.length >= 2) {
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
      }
      return name[0].toUpperCase();
    }
    const email = currentUser?.email;
    if (email) {
      return email[0].toUpperCase();
    }
    return "?";
  })();

  const userMenuItems: MenuProps["items"] = [
    {
      key: "user-info",
      label: displayName,
      disabled: true,
    },
    { type: "divider" },
    {
      key: "experimental-chatbox",
      onClick: ({ domEvent }) => {
        domEvent.stopPropagation();
        if (currentUserId !== null) setChatboxEnabled(currentUserId, !chatboxEnabled);
      },
      label: (
        <span
          className="app-user-menu-toggle"
          onClick={(event) => {
            event.stopPropagation();
            if (currentUserId !== null) setChatboxEnabled(currentUserId, !chatboxEnabled);
          }}
        >
          <span>{t("layout:experimentalChatbox")}</span>
          <Switch
            checked={chatboxEnabled}
            data-testid="experimental-chatbox-toggle"
            disabled={currentUserId === null}
            onClick={(checked, event) => {
              event.stopPropagation();
              if (currentUserId !== null) setChatboxEnabled(currentUserId, checked);
            }}
            size="small"
          />
        </span>
      ),
    },
    { type: "divider" },
    {
      key: "language-group",
      type: "group",
      label: t("common:language"),
      children: [
        {
          key: "language-zh-TW",
          label: t("common:traditionalChinese"),
          "data-testid": "language-option-zh-TW",
          onClick: () => void setLanguage("zh-TW")
        },
        {
          key: "language-en",
          label: t("common:english"),
          "data-testid": "language-option-en",
          onClick: () => void setLanguage("en")
        }
      ]
    },
    { type: "divider" },
    {
      key: "logout",
      label: t("layout:logout"),
      "data-testid": "auth-logout-button",
      onClick: () => {
        void logout().then(() => {
          navigate("/login", { replace: true });
        });
      },
    },
  ];

  return (
    <>
      <header className="app-header" data-testid="app-header">
        <div className="app-header-brand-group">
          <button
            aria-label="PressRoom"
            className="app-brand"
            data-testid="app-brand"
            onClick={() => {
              setRightPanelTab("config");
              resetTaskExecution();
              navigate("/");
            }}
            type="button"
          >
            <CorgiLogo size={36} />
            <span className="app-brand-copy">
              <span className="app-brand-eyebrow">{t("layout:eyebrow")}</span>
              <span className="app-brand-title">PressRoom</span>
            </span>
          </button>

          <nav className="domain-tabs" data-testid="domain-tabs">
            <button
              aria-current={isWorkflowsDomain ? "page" : undefined}
              className={`domain-tab ${isWorkflowsDomain ? "is-active" : ""}`}
              data-testid="domain-tab-workflows"
              onClick={() => navigate(lastWorkflowsRoute)}
              type="button"
            >
              {t("layout:workflows")}
            </button>
            <button
              aria-current={isProjectsDomain ? "page" : undefined}
              className={`domain-tab ${isProjectsDomain ? "is-active" : ""}`}
              data-testid="domain-tab-database"
              onClick={() => navigate(lastDatabaseRoute)}
              type="button"
            >
              {t("layout:database")}
            </button>
          </nav>
        </div>

        <div className="app-header-actions">
          <WorkspaceSwitcher
            currentWorkspace={currentWorkspace}
            memberships={memberships}
            loading={status === "loading"}
            switching={isSwitching}
            error={error}
            onSwitchWorkspace={switchWorkspace}
            onRetry={refresh}
            onOpenMembers={() => navigate("/settings/workspace/members")}
            onOpenProviders={() => navigate("/settings/workspace/providers")}
            onOpenAudit={() => navigate("/settings/workspace/audit")}
            onOpenSettings={() => navigate("/settings/workspace")}
            onCreateWorkspace={() => setNewWorkspaceOpen(true)}
          />
          <Button
            className="app-header-command-btn"
            data-testid="command-palette-trigger"
            icon={<SearchOutlined />}
            onClick={() => setCommandPaletteOpen(true)}
            title={t("layout:searchShortcut")}
          >
            <span className="app-header-command-label">{t("common:search")}</span>
          </Button>
          <div className="app-header-user-menu">
            <Dropdown
              menu={{
                items: userMenuItems,
                selectable: true,
                selectedKeys: [`language-${language}`]
              }}
              trigger={["click"]}
            >
              <Avatar
                aria-label={t("layout:openUserMenu", { name: displayName })}
                data-testid="auth-current-user"
                icon={initials === "?" ? <UserOutlined /> : undefined}
                size="small"
                style={{ cursor: "pointer", backgroundColor: token.colorPrimary }}
              >
                {initials !== "?" ? initials : null}
              </Avatar>
            </Dropdown>
          </div>
        </div>
      </header>
      {newWorkspaceOpen ? (
        <NewWorkspaceDialog
          onCancel={() => setNewWorkspaceOpen(false)}
          onSubmit={handleCreateWorkspace}
          open
          submitting={creatingWorkspace}
        />
      ) : null}
    </>
  );
}
