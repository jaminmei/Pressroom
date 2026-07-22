import {
  ApiOutlined,
  AppstoreOutlined,
  EditOutlined,
  FolderOpenOutlined,
  HistoryOutlined,
  HomeOutlined,
  KeyOutlined,
  LeftOutlined,
  ProjectOutlined,
  RightOutlined,
  SettingOutlined,
  TeamOutlined
} from "@ant-design/icons";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";

import SidebarItem from "@/components/Layout/SidebarItem";
import { getWorkflowDetail } from "@/services/workflowApi";
import { useUIStore } from "@/stores/uiStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { WorkspaceCapability } from "@/types/workspace";

interface SidebarProps {
  onOpenRecentRuns: () => void;
}

export default function Sidebar({ onOpenRecentRuns }: SidebarProps) {
  const { t } = useTranslation("layout");
  const location = useLocation();
  const navigate = useNavigate();
  const sidebarCollapsed = useUIStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useUIStore((state) => state.toggleSidebar);
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const can = useWorkspaceStore((state) => state.can);
  const explain = useWorkspaceStore((state) => state.explain);

  const isProjectsDomain = location.pathname.startsWith("/projects") || location.pathname.startsWith("/database");
  const isWorkspaceSettingsRoute = location.pathname.startsWith("/settings/workspace");
  const workflowIdMatch = location.pathname.match(/^\/workflows\/([^/]+)/);
  const currentWorkflowId = workflowIdMatch ? workflowIdMatch[1] : null;
  const isApiAccessRoute = currentWorkflowId !== null && location.pathname.endsWith("/api-access");
  const isEditorRoute = location.pathname === "/" || (location.pathname.startsWith("/workflows/") && !isApiAccessRoute);
  const isStudioRoute = location.pathname === "/studio";
  const isTemplateRoute = location.pathname === "/templates";
  const isSettingsRoute = location.pathname.startsWith("/settings");
  const isWorkflowContext = currentWorkflowId !== null;

  // This duplicates the API-access page fetch; lift it into shared state if
  // profiling shows the extra request is material.
  const [publishedVersion, setPublishedVersion] = useState<number | null | undefined>(undefined);
  useEffect(() => {
    if (!currentWorkflowId || !can("api_key.view")) {
      setPublishedVersion(undefined);
      return;
    }
    let cancelled = false;
    getWorkflowDetail(currentWorkflowId)
      .then((wf) => { if (!cancelled) setPublishedVersion(wf.published_version ?? null); })
      .catch(() => { if (!cancelled) setPublishedVersion(undefined); });
    return () => { cancelled = true; };
  }, [can, currentWorkflowId]);

  const apiForwardBadge = !currentWorkflowId ? undefined :
    publishedVersion === undefined ? undefined :
    publishedVersion ? <span className="sidebar-nav-pill ready">{t("sidebar.published")}</span> :
    <span className="sidebar-nav-pill">{t("sidebar.notPublished")}</span>;

  const permissionState = (capability: WorkspaceCapability) => {
    const allowed = can(capability);
    return {
      disabled: !allowed,
      disabledReason: allowed ? undefined : explain(capability).reason
    };
  };

  return (
    <aside
      className={`app-sidebar ${sidebarCollapsed ? "is-collapsed" : ""}`.trim()}
      data-collapsed={sidebarCollapsed ? "true" : "false"}
      data-testid="sidebar"
    >
      <div className="sidebar-surface">
        <div className="sidebar-header">
          {!sidebarCollapsed ? (
            <>
              <span className="sidebar-section-label">
                {isProjectsDomain ? t("sidebar.database") : t("sidebar.workspace")}
              </span>
              <span className="sidebar-section-copy">
                {isProjectsDomain
                  ? t("sidebar.databaseDescription")
                  : isWorkspaceSettingsRoute
                    ? t("sidebar.workspaceSettingsDescription")
                  : isWorkflowContext
                    ? t("sidebar.workflowContextDescription")
                    : t("sidebar.workflowDescription")}
              </span>
            </>
          ) : (
            <span className="sidebar-collapsed-mark">DC</span>
          )}
        </div>

        <div className="sidebar-items">
          {isWorkspaceSettingsRoute ? (
            <>
              <SidebarItem
                active={location.pathname === "/settings/workspace" || location.pathname === "/settings/workspace/"}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-workspace-overview"
                icon={<HomeOutlined />}
                label={t("sidebar.overview")}
                onClick={() => navigate("/settings/workspace")}
                {...permissionState("workspace.view")}
              />
              <SidebarItem
                active={location.pathname.startsWith("/settings/workspace/members")}
                badge={<span className="sidebar-nav-count">{currentWorkspace?.memberCount ?? "—"}</span>}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-workspace-members"
                icon={<TeamOutlined />}
                label={t("sidebar.membersRoles")}
                onClick={() => navigate("/settings/workspace/members")}
                {...permissionState("members.view")}
              />
              <SidebarItem
                active={location.pathname.startsWith("/settings/workspace/providers")}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-workspace-providers"
                icon={<KeyOutlined />}
                label={t("sidebar.providers")}
                onClick={() => navigate("/settings/workspace/providers")}
                {...permissionState("provider.view")}
              />
              <SidebarItem
                active={location.pathname.startsWith("/settings/workspace/audit")}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-workspace-audit"
                icon={<HistoryOutlined />}
                label={t("sidebar.audit")}
                onClick={() => navigate("/settings/workspace/audit")}
                {...permissionState("audit.view")}
              />
              <SidebarItem
                active={location.pathname.startsWith("/settings/workspace/general")}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-workspace-general"
                icon={<SettingOutlined />}
                label={t("sidebar.general")}
                onClick={() => navigate("/settings/workspace/general")}
                {...permissionState("workspace.view")}
              />
            </>
          ) : isProjectsDomain ? (
            <SidebarItem
              active={location.pathname === "/projects" || location.pathname === "/database"}
              collapsed={sidebarCollapsed}
              dataTestId="sidebar-item-projects"
              icon={<ProjectOutlined />}
              label={t("sidebar.allDatabases")}
              onClick={() => navigate("/database")}
            />
          ) : isWorkflowContext ? (
            <>
              {!sidebarCollapsed && <div className="sidebar-group-label">{t("sidebar.workflowLibrary")}</div>}
              <SidebarItem
                active={isStudioRoute}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-studio"
                icon={<FolderOpenOutlined />}
                label={t("sidebar.studio")}
                onClick={() => navigate("/studio")}
              />
              {!sidebarCollapsed && <div className="sidebar-group-label">{t("sidebar.currentWorkflow")}</div>}
              {!sidebarCollapsed && (
                <div className="sidebar-workflow-context">
                  <div className="sidebar-workflow-context-title">{t("sidebar.workflow")}</div>
                  <div className="sidebar-workflow-context-subtitle">ID: {currentWorkflowId}</div>
                </div>
              )}
              <SidebarItem
                active={isEditorRoute}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-editor"
                icon={<EditOutlined />}
                label={t("sidebar.editor")}
                onClick={() => navigate(`/workflows/${currentWorkflowId}`)}
              />
              <SidebarItem
                active={isApiAccessRoute}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-api-forward"
                icon={<ApiOutlined />}
                label={t("sidebar.apiForward")}
                badge={apiForwardBadge}
                onClick={() => navigate(`/workflows/${currentWorkflowId}/api-access`)}
                {...permissionState("api_key.view")}
              />
              <SidebarItem
                active={false}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-runs"
                icon={<HistoryOutlined />}
                label={t("sidebar.recentRuns")}
                onClick={onOpenRecentRuns}
              />
              {!sidebarCollapsed && <div className="sidebar-group-label">{t("sidebar.workspaceTools")}</div>}
              <SidebarItem
                active={isTemplateRoute}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-templates"
                icon={<AppstoreOutlined />}
                label={t("sidebar.templates")}
                onClick={() => navigate("/templates")}
              />
              <SidebarItem
                active={isSettingsRoute}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-settings"
                icon={<SettingOutlined />}
                label={t("sidebar.settings")}
                onClick={() => navigate("/settings")}
              />
            </>
          ) : (
            <>
              <SidebarItem
                active={isEditorRoute}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-editor"
                icon={<EditOutlined />}
                label={t("sidebar.editor")}
                onClick={() => navigate("/")}
              />
              <SidebarItem
                active={isStudioRoute}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-studio"
                icon={<FolderOpenOutlined />}
                label={t("sidebar.studio")}
                onClick={() => navigate("/studio")}
              />
              <SidebarItem
                active={false}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-runs"
                icon={<HistoryOutlined />}
                label={t("sidebar.recentRuns")}
                onClick={onOpenRecentRuns}
              />
              <SidebarItem
                active={isTemplateRoute}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-templates"
                icon={<AppstoreOutlined />}
                label={t("sidebar.templates")}
                onClick={() => navigate("/templates")}
              />
              <SidebarItem
                active={isSettingsRoute}
                collapsed={sidebarCollapsed}
                dataTestId="sidebar-item-settings"
                icon={<SettingOutlined />}
                label={t("sidebar.settings")}
                onClick={() => navigate("/settings")}
              />
            </>
          )}
        </div>

        <div className="sidebar-footer">
          <button
            className="sidebar-collapse-trigger"
            data-testid="sidebar-collapse-trigger"
            onClick={toggleSidebar}
            type="button"
          >
            {sidebarCollapsed ? <RightOutlined /> : <LeftOutlined />}
            {!sidebarCollapsed ? <span>{t("sidebar.collapse")}</span> : null}
          </button>
        </div>
      </div>
    </aside>
  );
}
