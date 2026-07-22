import {
  ArrowLeftOutlined,
  PlayCircleOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Checkbox,
  Input,
  message,
  Select,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { PermissionButton } from "@/components/Permissions/PermissionButton";
import DocumentThumbnail from "@/features/projects/components/DocumentThumbnail";
import ProjectWorkspaceShell, {
  type ProjectWorkspaceNavigationState,
  type ProjectWorkspaceSection,
} from "@/features/projects/components/ProjectWorkspaceShell";
import { useProjectDocuments } from "@/features/projects/hooks/useProjectDocuments";
import { useRunWorkflowConfig } from "@/features/projects/hooks/useRunWorkflowConfig";
import { getDatabaseBasePath } from "@/features/projects/utils/databaseBasePath";
import { usePermission } from "@/hooks/usePermission";
import { getProject } from "@/services/projectApi";
import type { ProjectDocument } from "@/types/project";

const { Text, Title } = Typography;

interface RunWorkflowNavigationState extends ProjectWorkspaceNavigationState {
  selectedDocIds?: string[];
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

function formatDocumentType(document: ProjectDocument): string {
  const mime = document.type.toLowerCase();
  if (mime === "application/pdf") return "PDF";
  if (mime === "image/jpeg") return "JPG";
  if (mime === "image/png") return "PNG";
  if (mime === "image/webp") return "WEBP";
  const extension = document.filename.split(".").pop()?.toUpperCase();
  return extension || document.type;
}

export default function RunWorkflowPage() {
  const { t } = useTranslation(["common", "projects"]);
  const { projectId = "" } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { can } = usePermission();
  const canViewDatabase = can("database.view");
  const canCreateRun = can("run.create");
  const basePath = getDatabaseBasePath(location.pathname);
  const projectPath = `${basePath}/${projectId}`;
  const navigationState = location.state as RunWorkflowNavigationState | null;
  const preSelectedDocIds = useMemo(
    () => navigationState?.selectedDocIds ?? [],
    [navigationState?.selectedDocIds],
  );

  const {
    workflows,
    loading: workflowsLoading,
    error: workflowsError,
    startRun,
  } = useRunWorkflowConfig(projectId);
  const {
    documents,
    loading: documentsLoading,
    error: documentsError,
  } = useProjectDocuments(projectId);

  const [projectName, setProjectName] = useState(() => t("projects:database"));
  const [projectLoading, setProjectLoading] = useState(Boolean(projectId));
  const [projectError, setProjectError] = useState<string | null>(null);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);
  const [runName, setRunName] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>(
    () => preSelectedDocIds,
  );
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!projectId || !canViewDatabase) {
      setProjectLoading(false);
      return undefined;
    }

    setProjectLoading(true);
    setProjectError(null);
    void getProject(projectId)
      .then((project) => {
        if (!cancelled) setProjectName(project.name);
      })
      .catch(() => {
        if (!cancelled) setProjectError(t("projects:databaseUnavailable"));
      })
      .finally(() => {
        if (!cancelled) setProjectLoading(false);
      });

    return () => { cancelled = true; };
  }, [canViewDatabase, projectId, t]);

  useEffect(() => {
    setSelectedDocIds(preSelectedDocIds);
  }, [location.key, preSelectedDocIds, projectId]);

  const availableDocumentIds = useMemo(
    () => new Set(documents.map((document) => document.id)),
    [documents],
  );
  const validSelectedDocIds = useMemo(
    () => selectedDocIds.filter((id) => availableDocumentIds.has(id)),
    [availableDocumentIds, selectedDocIds],
  );
  const selectedDocumentIdSet = useMemo(
    () => new Set(validSelectedDocIds),
    [validSelectedDocIds],
  );
  const selectedWorkflow = useMemo(
    () => workflows.find((workflow) => workflow.id === selectedWorkflowId) ?? null,
    [selectedWorkflowId, workflows],
  );
  const filteredDocuments = useMemo(() => {
    const query = searchQuery.trim().toLocaleLowerCase();
    if (!query) return documents;
    return documents.filter((document) => document.filename.toLocaleLowerCase().includes(query));
  }, [documents, searchQuery]);
  const filteredDocumentIds = useMemo(
    () => filteredDocuments.map((document) => document.id),
    [filteredDocuments],
  );
  const selectedVisibleCount = filteredDocumentIds.filter(
    (id) => selectedDocumentIdSet.has(id),
  ).length;
  const allVisibleSelected = filteredDocumentIds.length > 0
    && selectedVisibleCount === filteredDocumentIds.length;
  const someVisibleSelected = selectedVisibleCount > 0 && !allVisibleSelected;

  const navigateToSection = useCallback((section: ProjectWorkspaceSection) => {
    navigate(projectPath, { state: { activeSection: section } satisfies ProjectWorkspaceNavigationState });
  }, [navigate, projectPath]);

  const handleBackToList = useCallback(() => {
    navigate(basePath);
  }, [basePath, navigate]);

  const handleBackToDocuments = useCallback(() => {
    navigateToSection("documents");
  }, [navigateToSection]);

  const handleToggleDocument = useCallback((documentId: string) => {
    setSelectedDocIds((current) => {
      const validCurrent = current.filter((id) => availableDocumentIds.has(id));
      return validCurrent.includes(documentId)
        ? validCurrent.filter((id) => id !== documentId)
        : [...validCurrent, documentId];
    });
  }, [availableDocumentIds]);

  const handleToggleVisible = useCallback(() => {
    setSelectedDocIds((current) => {
      const validCurrent = current.filter((id) => availableDocumentIds.has(id));
      if (allVisibleSelected) {
        const visibleIds = new Set(filteredDocumentIds);
        return validCurrent.filter((id) => !visibleIds.has(id));
      }
      return [...new Set([...validCurrent, ...filteredDocumentIds])];
    });
  }, [allVisibleSelected, availableDocumentIds, filteredDocumentIds]);

  const handleStartRun = useCallback(async () => {
    if (!selectedWorkflowId || validSelectedDocIds.length === 0 || submitting) return;
    setSubmitting(true);
    try {
      const activeRunId = await startRun(
        selectedWorkflowId,
        validSelectedDocIds,
        runName.trim() || undefined,
      );
      navigate(projectPath, { state: { activeRunId } satisfies ProjectWorkspaceNavigationState });
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : t("projects:startRunFailed");
      void message.error(errorMessage);
      setSubmitting(false);
    }
  }, [navigate, projectPath, runName, selectedWorkflowId, startRun, submitting, t, validSelectedDocIds]);

  const disabledReason = !selectedWorkflowId && validSelectedDocIds.length === 0
    ? t("projects:selectWorkflowDocuments")
    : !selectedWorkflowId
      ? t("projects:selectWorkflowOnly")
      : validSelectedDocIds.length === 0
        ? t("projects:selectDocumentOnly")
        : undefined;
  const formDisabled = !canCreateRun || submitting;
  const canStart = canCreateRun
    && selectedWorkflowId !== null
    && validSelectedDocIds.length > 0
    && !submitting;
  const documentCountLabel = t("projects:documentCount", { count: validSelectedDocIds.length });

  return (
    <ProjectWorkspaceShell
      activeSection="runs"
      breadcrumbTail={t("projects:runWorkflow")}
      onBackToList={handleBackToList}
      onNavigateSection={navigateToSection}
      onProjectClick={handleBackToDocuments}
      projectName={projectName}
    >
      <div className="rwp-page" data-testid="run-workflow-page">
        <div className="rwp-page-heading">
          <Button
            className="rwp-back-to-documents"
            data-testid="rwp-back-button"
            icon={<ArrowLeftOutlined />}
            onClick={handleBackToDocuments}
            type="text"
          >
            {t("projects:backToDocuments")}
          </Button>
          <Title className="rwp-title" level={2}>{t("projects:runWorkflow")}</Title>
          <Text className="rwp-page-description" type="secondary">
            {t("projects:runPageDescription")}
          </Text>
        </div>

        {!canViewDatabase ? (
          <Alert
            data-testid="rwp-forbidden"
            message={t("projects:projectViewDenied")}
            showIcon
            type="warning"
          />
        ) : projectLoading ? (
          <div className="rwp-loading" data-testid="rwp-loading"><Spin size="large" /></div>
        ) : projectError ? (
          <Alert
            action={<Button onClick={handleBackToList}>{t("projects:backToDatabases")}</Button>}
            data-testid="rwp-project-error"
            description={projectError}
            message={t("projects:databaseUnavailable")}
            showIcon
            type="error"
          />
        ) : (
          <>
            <div className="rwp-config-grid" data-testid="rwp-config-phase">
              <section className="rwp-card rwp-config-card" aria-labelledby="rwp-config-title">
                <div className="rwp-card-header">
                  <div>
                    <h2 id="rwp-config-title" className="rwp-card-title">{t("projects:runConfiguration")}</h2>
                    <p className="rwp-card-description">{t("projects:runConfigurationDescription")}</p>
                  </div>
                </div>

                <div className="rwp-config-fields">
                  <div className="rwp-form-group">
                    <Text strong>{t("projects:workflow")}</Text>
                    <Select
                      aria-label={t("projects:workflow")}
                      className="rwp-workflow-select"
                      data-testid="rwp-workflow-select"
                      disabled={formDisabled}
                      loading={workflowsLoading}
                      notFoundContent={workflowsLoading ? <Spin size="small" /> : t("projects:noWorkflows")}
                      onChange={setSelectedWorkflowId}
                      optionFilterProp="label"
                      options={workflows.map((workflow) => ({
                        label: workflow.name,
                        title: workflow.description,
                        value: workflow.id,
                      }))}
                      placeholder={t("projects:selectWorkflow")}
                      showSearch
                      value={selectedWorkflowId}
                    />
                    {workflowsError ? (
                      <Alert
                        data-testid="rwp-workflows-error"
                        message={t("projects:loadWorkflowsFailed")}
                        showIcon
                        type="error"
                      />
                    ) : null}
                    {!workflowsLoading && !workflowsError && workflows.length === 0 ? (
                      <div className="rwp-inline-empty" data-testid="rwp-workflows-empty">
                        <Text type="secondary">{t("projects:createWorkflowFirst")}</Text>
                        <Button onClick={() => navigate("/")} size="small">{t("projects:createWorkflow")}</Button>
                      </div>
                    ) : null}
                  </div>

                  <div className="rwp-form-group">
                    <Text strong>{t("projects:runName")} <Text type="secondary">({t("common:optional")})</Text></Text>
                    <Input
                      aria-label={t("projects:runName")}
                      data-testid="rwp-run-name-input"
                      disabled={formDisabled}
                      onChange={(event) => setRunName(event.target.value)}
                      placeholder={t("projects:runNamePlaceholder")}
                      value={runName}
                    />
                  </div>

                  <div className="rwp-workflow-description" data-testid="rwp-workflow-description">
                    <Text className="rwp-workflow-description-label">{t("projects:workflowSummary")}</Text>
                    <Text type="secondary">
                      {selectedWorkflow
                        ? selectedWorkflow.description || t("projects:noWorkflowDescription")
                        : t("projects:selectWorkflowDescription")}
                    </Text>
                  </div>
                </div>
              </section>

              <section className="rwp-card rwp-documents-card" aria-labelledby="rwp-documents-title">
                <div className="rwp-card-header">
                  <div>
                    <h2 id="rwp-documents-title" className="rwp-card-title">{t("projects:chooseDocuments")}</h2>
                    <p className="rwp-card-description">{t("projects:chooseDocumentsDescription")}</p>
                  </div>
                  <Tag className="rwp-selected-count" color="purple" data-testid="rwp-selected-count">
                    {t("projects:selected", { count: validSelectedDocIds.length })}
                  </Tag>
                </div>

                <div className="rwp-doc-toolbar">
                  <Input
                    allowClear
                    className="rwp-doc-search"
                    data-testid="rwp-document-search"
                    onChange={(event) => setSearchQuery(event.target.value)}
                    placeholder={t("projects:searchDocuments")}
                    prefix={<SearchOutlined />}
                    value={searchQuery}
                  />
                  <div className="rwp-doc-selection-actions">
                    <Checkbox
                      checked={allVisibleSelected}
                      data-testid="rwp-select-all-visible"
                      disabled={formDisabled || filteredDocumentIds.length === 0}
                      indeterminate={someVisibleSelected}
                      onChange={handleToggleVisible}
                    >
                      {t("projects:selectAllVisible")}
                    </Checkbox>
                    <Button
                      data-testid="rwp-clear-selection"
                      disabled={formDisabled || validSelectedDocIds.length === 0}
                      onClick={() => setSelectedDocIds([])}
                      size="small"
                      type="link"
                    >
                      {t("projects:clear")}
                    </Button>
                  </div>
                </div>

                <div className="rwp-doc-list-region">
                  {documentsLoading ? (
                    <div className="rwp-doc-list-state" data-testid="rwp-documents-loading">
                      <Spin />
                    </div>
                  ) : documentsError ? (
                    <Alert
                      action={<Button onClick={handleBackToDocuments} size="small">{t("projects:backToDocuments")}</Button>}
                      data-testid="rwp-documents-error"
                      description={documentsError}
                      message={t("projects:loadDocumentsFailed")}
                      showIcon
                      type="error"
                    />
                  ) : documents.length === 0 ? (
                    <div className="rwp-doc-list-state" data-testid="rwp-documents-empty">
                      <Text strong>{t("projects:noDocumentsAvailable")}</Text>
                      <Text type="secondary">{t("projects:uploadDocumentsFirst")}</Text>
                      <Button onClick={handleBackToDocuments}>{t("projects:backToDocuments")}</Button>
                    </div>
                  ) : filteredDocuments.length === 0 ? (
                    <div className="rwp-doc-list-state" data-testid="rwp-documents-no-results">
                      <Text strong>{t("projects:noMatchingDocuments")}</Text>
                      <Text type="secondary">{t("projects:tryFilename")}</Text>
                    </div>
                  ) : (
                    <div className="rwp-doc-select-list" data-testid="rwp-doc-select-list">
                      {filteredDocuments.map((document) => {
                        const selected = selectedDocumentIdSet.has(document.id);
                        return (
                          <label
                            className={`rwp-doc-select-item${selected ? " is-selected" : ""}`}
                            data-testid={`rwp-doc-row-${document.id}`}
                            key={document.id}
                          >
                            <Checkbox
                              checked={selected}
                              data-testid={`rwp-doc-checkbox-${document.id}`}
                              disabled={formDisabled}
                              onChange={() => handleToggleDocument(document.id)}
                            />
                            <DocumentThumbnail
                              documentId={document.id}
                              filename={document.filename}
                              mimeType={document.type}
                              testSetId={projectId}
                            />
                            <span className="rwp-doc-select-name" title={document.filename}>
                              {document.filename}
                            </span>
                            <span className="rwp-doc-select-meta">
                              <span className="rwp-doc-type-label">{formatDocumentType(document)}</span>
                              <span className="rwp-doc-select-size">{formatFileSize(document.size)}</span>
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  )}
                </div>
              </section>
            </div>

            <div className="rwp-action-bar" data-testid="rwp-action-bar">
              <div className="rwp-run-summary">
                <Text strong>{selectedWorkflow?.name || t("projects:noWorkflowSelected")}</Text>
                <Text type="secondary">{t("projects:selected", { count: validSelectedDocIds.length })}</Text>
                {disabledReason ? <Text className="rwp-disabled-reason">{disabledReason}</Text> : null}
              </div>
              <div className="rwp-action-buttons">
                <Button disabled={submitting} onClick={handleBackToDocuments}>{t("common:cancel")}</Button>
                <PermissionButton
                  capability="run.create"
                  className="rwp-start-button"
                  data-testid="rwp-start-run-button"
                  disabled={!canStart}
                  disabledReason={disabledReason}
                  icon={<PlayCircleOutlined />}
                  loading={submitting}
                  onClick={() => { void handleStartRun(); }}
                  size="large"
                  type="primary"
                >
                  {t("projects:runDocuments", { documents: documentCountLabel })}
                </PermissionButton>
              </div>
            </div>
          </>
        )}
      </div>
    </ProjectWorkspaceShell>
  );
}
