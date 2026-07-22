import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  FileTextOutlined,
  HomeOutlined,
  PlayCircleOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";

export type ProjectWorkspaceSection =
  | "overview"
  | "documents"
  | "runs"
  | "ground-truth"
  | "settings";

export interface ProjectWorkspaceNavigationState {
  activeRunId?: string;
  activeSection?: ProjectWorkspaceSection;
}

interface SectionDef {
  key: ProjectWorkspaceSection;
  labelKey: string;
  icon: React.ReactNode;
  dataTestId: string;
}

const SECTIONS: SectionDef[] = [
  { key: "overview", labelKey: "overview", icon: <HomeOutlined />, dataTestId: "ws-nav-overview" },
  { key: "documents", labelKey: "documents", icon: <FileTextOutlined />, dataTestId: "ws-nav-documents" },
  { key: "runs", labelKey: "runs", icon: <PlayCircleOutlined />, dataTestId: "ws-nav-runs" },
  { key: "ground-truth", labelKey: "groundTruth", icon: <CheckCircleOutlined />, dataTestId: "ws-nav-ground-truth" },
  { key: "settings", labelKey: "settings", icon: <SettingOutlined />, dataTestId: "ws-nav-settings" },
];

interface ProjectWorkspaceShellProps {
  activeSection: ProjectWorkspaceSection;
  availableSections?: ReadonlySet<ProjectWorkspaceSection>;
  breadcrumbTail?: string;
  children: React.ReactNode;
  onBackToList: () => void;
  onNavigateSection: (section: ProjectWorkspaceSection) => void;
  onProjectClick?: () => void;
  projectName: string;
}

export default function ProjectWorkspaceShell({
  activeSection,
  availableSections,
  breadcrumbTail,
  children,
  onBackToList,
  onNavigateSection,
  onProjectClick,
  projectName,
}: ProjectWorkspaceShellProps) {
  const { t } = useTranslation(["common", "projects"]);
  const handleProjectClick = onProjectClick ?? (() => onNavigateSection("overview"));

  return (
    <div className="project-workspace" data-testid="project-workspace">
      <nav
        aria-label={t("projects:navigation")}
        className="project-workspace-sidebar"
        data-testid="workspace-sidebar"
      >
        <div className="project-workspace-sidebar-top">
          <button
            className="project-workspace-nav-item"
            data-testid="ws-nav-back"
            onClick={onBackToList}
            type="button"
          >
            <span aria-hidden className="project-workspace-nav-item-icon">
              <ArrowLeftOutlined />
            </span>
            <span className="project-workspace-nav-item-label">{t("common:back")}</span>
          </button>
        </div>
        <div className="project-workspace-divider" />
        {SECTIONS.filter((section) => availableSections?.has(section.key) ?? true).map((section) => (
          <button
            aria-current={activeSection === section.key ? "page" : undefined}
            className={`project-workspace-nav-item ${activeSection === section.key ? "is-active" : ""}`.trim()}
            data-testid={section.dataTestId}
            key={section.key}
            onClick={() => onNavigateSection(section.key)}
            type="button"
          >
            <span aria-hidden className="project-workspace-nav-item-icon">
              {section.icon}
            </span>
            <span className="project-workspace-nav-item-label">{t(`projects:${section.labelKey}`)}</span>
          </button>
        ))}
      </nav>

      <div className="project-workspace-canvas" data-testid="workspace-canvas">
        <div
          aria-label={t("projects:breadcrumb")}
          className="project-workspace-breadcrumb"
          data-testid="workspace-breadcrumb"
        >
          <button
            className="project-workspace-breadcrumb-link"
            data-testid="breadcrumb-projects"
            onClick={onBackToList}
            type="button"
          >
            {t("projects:databases")}
          </button>
          <span className="project-workspace-breadcrumb-separator">/</span>
          {breadcrumbTail ? (
            <>
              <button
                className="project-workspace-breadcrumb-link project-workspace-breadcrumb-project"
                data-testid="breadcrumb-project-name"
                onClick={handleProjectClick}
                type="button"
              >
                {projectName}
              </button>
              <span className="project-workspace-breadcrumb-separator">/</span>
              <span
                aria-current="page"
                className="project-workspace-breadcrumb-current"
                data-testid="breadcrumb-tail"
              >
                {breadcrumbTail}
              </span>
            </>
          ) : (
            <span
              aria-current="page"
              className="project-workspace-breadcrumb-current"
              data-testid="breadcrumb-project-name"
            >
              {projectName}
            </span>
          )}
        </div>

        {children}
      </div>
    </div>
  );
}
