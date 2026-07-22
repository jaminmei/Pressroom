import {
  HistoryOutlined,
  HomeOutlined,
  KeyOutlined,
  SettingOutlined,
  TeamOutlined
} from "@ant-design/icons";
import type { ReactNode } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { WorkspaceCapability } from "@/types/workspace";

interface WorkspaceNavItem {
  key: string;
  labelKey: string;
  path: string;
  capability: WorkspaceCapability;
  icon: ReactNode;
}

const WORKSPACE_NAV_ITEMS: WorkspaceNavItem[] = [
  {
    key: "overview",
    labelKey: "overview",
    path: "/settings/workspace",
    capability: "workspace.view",
    icon: <HomeOutlined />
  },
  {
    key: "members",
    labelKey: "membersRolesTitle",
    path: "/settings/workspace/members",
    capability: "members.view",
    icon: <TeamOutlined />
  },
  {
    key: "providers",
    labelKey: "providers",
    path: "/settings/workspace/providers",
    capability: "provider.view",
    icon: <KeyOutlined />
  },
  {
    key: "audit",
    labelKey: "auditLog",
    path: "/settings/workspace/audit",
    capability: "audit.view",
    icon: <HistoryOutlined />
  },
  {
    key: "general",
    labelKey: "general",
    path: "/settings/workspace/general",
    capability: "workspace.view",
    icon: <SettingOutlined />
  }
];

function isActivePath(pathname: string, item: WorkspaceNavItem): boolean {
  if (item.key === "overview") {
    return pathname === item.path || pathname === `${item.path}/`;
  }
  return pathname.startsWith(item.path);
}

export default function WorkspaceSettingsPage() {
  const { t } = useTranslation("workspaces");
  const location = useLocation();
  const navigate = useNavigate();
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const can = useWorkspaceStore((state) => state.can);
  const explain = useWorkspaceStore((state) => state.explain);

  return (
    <div className="workspace-settings-page" data-testid="workspace-settings-page">
      <header className="workspace-settings-heading">
        <div>
          <p className="workspace-settings-eyebrow">{t("workspace")}</p>
          <h1>{t("workspaceSettings")}</h1>
          <p>
            {t("manageWorkspace", { name: currentWorkspace?.name ?? t("thisWorkspace") })}
          </p>
        </div>
      </header>

      <nav className="workspace-settings-mobile-nav" aria-label={t("workspaceSettings")}>
        {WORKSPACE_NAV_ITEMS.map((item) => {
          const allowed = can(item.capability);
          const active = isActivePath(location.pathname, item);
          const reason = allowed ? undefined : explain(item.capability).reason;

          return (
            <button
              aria-current={active ? "page" : undefined}
              className={active ? "is-active" : undefined}
              data-testid={`workspace-mobile-nav-${item.key}`}
              disabled={!allowed}
              key={item.key}
              onClick={() => navigate(item.path)}
              title={reason}
              type="button"
            >
              <span aria-hidden>{item.icon}</span>
              <span>{t(item.labelKey)}</span>
              {item.key === "members" ? (
                <span className="workspace-settings-nav-count">
                  {currentWorkspace?.memberCount ?? "—"}
                </span>
              ) : null}
            </button>
          );
        })}
      </nav>

      <main className="workspace-settings-content">
        <Outlet />
      </main>
    </div>
  );
}
