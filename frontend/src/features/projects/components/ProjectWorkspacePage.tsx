import {
  Alert,
  Flex,
  Spin,
} from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import DocumentsView from "@/features/projects/components/DocumentsView";
import { EvaluationStatusBadge } from "@/features/projects/components/EvaluationStatusBadge";
import GroundTruthView from "@/features/projects/components/GroundTruthView";
import ProjectWorkspaceShell, {
  type ProjectWorkspaceNavigationState,
  type ProjectWorkspaceSection,
} from "@/features/projects/components/ProjectWorkspaceShell";
import RunsView from "@/features/projects/components/RunsView";
import SettingsView from "@/features/projects/components/SettingsView";
import { useActiveRun } from "@/features/projects/hooks/useActiveRun";
import { useProjectDetail } from "@/features/projects/hooks/useProjectDetail";
import { getDatabaseBasePath } from "@/features/projects/utils/databaseBasePath";
import type { RunResult } from "@/types/project";
import { formatRelativeTime } from "@/utils/dateFormat";
import { usePermission } from "@/hooks/usePermission";
import { formatDateTime } from "@/i18n/format";
import { useLanguage } from "@/i18n/useLanguage";
import { isEvaluationRunTerminalStatus } from "@/services/evaluationRunApi";

function formatDate(timestamp: string, language: "en" | "zh-TW"): string {
  return formatDateTime(timestamp, language, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function ProjectWorkspacePage() {
  const { t } = useTranslation(["common", "projects"]);
  const { language } = useLanguage();
  const { can } = usePermission();
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [activeSection, setActiveSection] = useState<ProjectWorkspaceSection>("overview");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [documentMonitoringRunId, setDocumentMonitoringRunId] = useState<string | null>(null);
  const [selectedRunDocument, setSelectedRunDocument] = useState<RunResult | null>(null);
  const canViewRuns = can("run.view");
  const canViewGroundTruth = can("ground_truth.view");
  const availableSections = new Set<ProjectWorkspaceSection>([
    "overview",
    "documents",
    ...(canViewRuns ? (["runs"] as const) : []),
    ...(canViewGroundTruth ? (["ground-truth"] as const) : []),
    "settings",
  ]);

  const { project, recentRuns, activity, loading, error } = useProjectDetail(
    projectId ?? "",
  );

  const {
    activeRunId,
    error: runError,
    runStatus,
    runProgress,
    results: runResults,
    acceptAsGT,
    rejectResult,
    startMonitoring,
    updateResultComparison,
  } = useActiveRun(projectId ?? "");

  useEffect(() => {
    if (canViewRuns) return;
    setDocumentMonitoringRunId(null);
    setSelectedRunId(null);
    setSelectedRunDocument(null);
  }, [canViewRuns]);

  // A router navigation entry is transient. Handle it once even if hook callback
  // identities or surrounding workspace state change during the run lifecycle.
  const handledRunNavigationRef = useRef<string | null>(null);

  useEffect(() => {
    const navState = location.state as ProjectWorkspaceNavigationState | null;
    const navigationRunKey = navState?.activeRunId
      ? `${location.key}:${navState.activeRunId}`
      : null;
    if (
      navState?.activeRunId &&
      navigationRunKey !== handledRunNavigationRef.current
    ) {
      if (!canViewRuns) {
        setActiveSection("runs");
        return;
      }
      handledRunNavigationRef.current = navigationRunKey;
      setDocumentMonitoringRunId(navState.activeRunId);
      setActiveSection("documents");
      startMonitoring(navState.activeRunId);
      return;
    }
    if (navState?.activeSection) setActiveSection(navState.activeSection);
  }, [canViewRuns, location.key, location.state, startMonitoring]);

  useEffect(() => {
    if (
      activeSection !== "documents" &&
      documentMonitoringRunId === activeRunId &&
      runStatus !== "idle" &&
      isEvaluationRunTerminalStatus(runStatus)
    ) {
      setDocumentMonitoringRunId(null);
    }
  }, [activeRunId, activeSection, documentMonitoringRunId, runStatus]);

  const handleBackToList = useCallback(() => {
    navigate(getDatabaseBasePath(location.pathname));
  }, [navigate, location.pathname]);

  const handleSelectRunDocument = useCallback((result: RunResult) => {
    setSelectedRunDocument(result);
  }, []);

  const handleCloseRunDocument = useCallback(() => {
    setSelectedRunDocument(null);
  }, []);

  const handleViewFullRun = useCallback((runId: string) => {
    if (!canViewRuns) {
      setActiveSection("runs");
      return;
    }
    setDocumentMonitoringRunId(null);
    setSelectedRunId(runId);
    setSelectedRunDocument(null);
    setActiveSection("runs");
    if (runId !== activeRunId || runResults.length === 0 || runError) {
      startMonitoring(runId);
    }
  }, [activeRunId, canViewRuns, runError, runResults.length, startMonitoring]);

  const handleOpenRun = useCallback((runId: string) => {
    setDocumentMonitoringRunId(null);
    startMonitoring(runId);
  }, [startMonitoring]);

  if (loading) {
    return (
      <Flex
        align="center"
        data-testid="project-workspace-loading"
        justify="center"
        style={{ height: "100%" }}
        vertical
      >
        <Spin size="large" />
      </Flex>
    );
  }

  if (error) {
    return (
      <Flex align="center" justify="center" style={{ height: "100%" }} vertical>
        <Alert
          data-testid="project-workspace-error"
          message={t("settings:error", { ns: "settings" })}
          showIcon
          type="error"
          description={error}
        />
      </Flex>
    );
  }

  if (!project) {
    return (
      <Flex align="center" justify="center" style={{ height: "100%" }} vertical>
        <Alert
          data-testid="project-workspace-not-found"
          message={t("projects:notFound")}
          showIcon
          type="warning"
          description={t("projects:projectNotFound")}
        />
      </Flex>
    );
  }

  if (!can("database.view")) {
    return <Alert data-testid="project-workspace-forbidden" message={t("projects:projectViewDenied")} showIcon type="warning" />;
  }

  return (
    <ProjectWorkspaceShell
      activeSection={activeSection}
      availableSections={availableSections}
      onBackToList={handleBackToList}
      onNavigateSection={setActiveSection}
      projectName={project.name}
    >
        {/* Overview View */}
        {activeSection === "overview" && (
          <div className="overview-content" data-testid="overview-content">
            {/* Header */}
            <div className="overview-header">
              <div className="overview-header-row">
                <h1 className="overview-header-name">{project.name}</h1>
                <span className="overview-header-version">
                  v{project.version}
                </span>
              </div>
              <div className="overview-meta-grid">
                <span className="overview-meta-item">
                  <span>{t("projects:documents")}</span> {project.documentCount}
                </span>
                <span className="overview-meta-item">
                  <span>{t("projects:lastUpdated")}</span>{" "}
                  {formatDate(project.lastUpdated, language)}
                </span>
                <span className="overview-meta-item">
                  <span>{t("projects:created")}</span> {formatDate(project.createdAt, language)}
                </span>
              </div>
            </div>

            {canViewRuns && (
              <>
                {/* Run History Summary */}
                <div className="overview-section">
                  <h2 className="overview-section-title">{t("projects:recentRuns")}</h2>
                  <div className="overview-run-history">
                    {recentRuns.length === 0 ? (
                      <div className="overview-empty-state" data-testid="overview-recent-runs-empty">
                        {t("projects:noRecentRuns")}
                      </div>
                    ) : (
                      recentRuns.map((run) => (
                        <div
                          className="overview-run-row"
                          data-testid={`run-row-${run.id}`}
                          key={run.id}
                          onClick={() => handleViewFullRun(run.id)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ")
                              handleViewFullRun(run.id);
                          }}
                          role="button"
                          tabIndex={0}
                        >
                          <span className="overview-run-row-name">
                            {run.name}
                          </span>
                          <span className={`overview-run-row-status overview-run-row-status--${run.status}`}>
                            <EvaluationStatusBadge status={run.status} />
                          </span>
                          <span className="overview-run-row-date">
                            {formatRelativeTime(run.date)}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* Recent Activity Feed */}
                <div className="overview-section">
                  <h2 className="overview-section-title">{t("projects:recentActivity")}</h2>
                  <div className="overview-activity-feed">
                    {activity.length === 0 ? (
                      <div className="overview-empty-state" data-testid="overview-recent-activity-empty">
                        {t("projects:noRecentActivity")}
                      </div>
                    ) : (
                      activity.map((item) => (
                        <div
                          className="overview-activity-item"
                          data-testid={`activity-${item.id}`}
                          key={item.id}
                        >
                          <div className="overview-activity-dot" />
                          <div className="overview-activity-body">
                            <div className="overview-activity-action">
                              {item.action}
                            </div>
                            <div className="overview-activity-detail">
                              {item.detail}
                            </div>
                          </div>
                          <div className="overview-activity-time">
                            {formatRelativeTime(item.timestamp)}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* Project document and run views */}
        {activeSection === "documents" && (
          <DocumentsView
            activeRunId={activeRunId}
            monitoredRunId={documentMonitoringRunId}
            navigate={navigate}
            onViewFullRun={handleViewFullRun}
            projectId={projectId ?? ""}
            runProgress={runProgress}
            runResults={runResults}
            runStatus={runStatus}
          />
        )}

        {activeSection === "runs" && canViewRuns && (
          <RunsView
            activeRunId={activeRunId}
            navigate={navigate}
            onAcceptAsGT={acceptAsGT}
            onCloseRunDocument={handleCloseRunDocument}
            onOpenRun={handleOpenRun}
            onRejectResult={rejectResult}
            onResultComparison={updateResultComparison}
            onSelectRunId={setSelectedRunId}
            onSelectRunDocument={handleSelectRunDocument}
            projectId={projectId ?? ""}
            runError={runError}
            runResults={runResults}
            runStatus={runStatus}
            selectedRunId={selectedRunId}
            selectedRunDocument={selectedRunDocument}
          />
        )}

        {activeSection === "runs" && !canViewRuns && (
          <Alert
            data-testid="project-section-forbidden"
            message={t("projects:sectionViewDenied")}
            showIcon
            type="warning"
          />
        )}

        {activeSection === "ground-truth" && canViewGroundTruth && (
          <GroundTruthView
            projectId={projectId ?? ""}
            runResults={runResults}
          />
        )}

        {activeSection === "ground-truth" && !canViewGroundTruth && (
          <Alert
            data-testid="project-section-forbidden"
            message={t("projects:sectionViewDenied")}
            showIcon
            type="warning"
          />
        )}

        {activeSection === "settings" && (
          <SettingsView
            projectDescription={project.description}
            projectId={projectId ?? ""}
            projectName={project.name}
          />
        )}
    </ProjectWorkspaceShell>
  );
}
