import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  CloseOutlined,
  FilterOutlined,
  LoadingOutlined,
  MinusCircleOutlined,
  PlayCircleOutlined,
  SortAscendingOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import type { TableColumnsType } from "antd";
import { Alert, Button, Flex, message, Modal, Progress, Spin, Table, Tabs, Tag, Tooltip, Typography } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, type NavigateFunction } from "react-router-dom";
import { useTranslation } from "react-i18next";

import CompareView from "@/features/projects/components/CompareView";
import DocumentGroundTruthPanel from "@/features/projects/components/DocumentGroundTruthPanel";
import DocumentPreview from "@/features/projects/components/DocumentPreview";
import DocumentThumbnail from "@/features/projects/components/DocumentThumbnail";
import { EvaluationStatusBadge } from "@/features/projects/components/EvaluationStatusBadge";
import type { RunStatus } from "@/features/projects/hooks/useActiveRun";
import { useDocumentRunHistory } from "@/features/projects/hooks/useDocumentRunHistory";
import { useProjectDocuments } from "@/features/projects/hooks/useProjectDocuments";
import { getDatabaseBasePath } from "@/features/projects/utils/databaseBasePath";
import type { ProjectDocument, RunProgressItem, RunResult } from "@/types/project";
import { formatRelativeTime } from "@/utils/dateFormat";
import { PermissionButton } from "@/components/Permissions/PermissionButton";

interface DocumentsViewProps {
  projectId: string;
  navigate: NavigateFunction;
  activeRunId: string | null;
  monitoredRunId: string | null;
  runStatus: RunStatus;
  runProgress: RunProgressItem[];
  runResults?: RunResult[];
  onViewFullRun: (runId: string) => void;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const GT_STATUS_CONFIG: Record<string, { color: string; labelKey: string }> = {
  approved: { color: "green", labelKey: "approved" },
  pending: { color: "gold", labelKey: "pending" },
  none: { color: "default", labelKey: "common:none" },
};

const PROGRESS_STATUS_TO_EVALUATION_STATUS: Record<RunProgressItem["status"], string> = {
  pending: "queued",
  processing: "running",
  complete: "completed",
  failed: "failed",
  skipped: "skipped",
};

function formatMilliseconds(milliseconds: number | undefined): string {
  if (milliseconds == null) return "-";
  if (milliseconds < 1000) return `${milliseconds} ms`;
  if (milliseconds < 60000) return `${(milliseconds / 1000).toFixed(1)}s`;
  const minutes = Math.floor(milliseconds / 60000);
  const seconds = Math.round((milliseconds % 60000) / 1000);
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

function getLiveResultStatus(result: RunResult): string {
  return result.executionStatus;
}

export default function DocumentsView({
  projectId,
  navigate,
  activeRunId,
  monitoredRunId,
  runStatus,
  runProgress,
  runResults,
  onViewFullRun,
}: DocumentsViewProps) {
  const { t } = useTranslation(["common", "projects", "settings"]);
  const location = useLocation();
  const { documents, loading, error, uploadDocuments, deleteDocument } =
    useProjectDocuments(projectId);

  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<ProjectDocument | null>(null);
  const [rightPanelWidth, setRightPanelWidth] = useState(50);
  const [activeTab, setActiveTab] = useState("docs");
  const isRunMonitoringVisible =
    monitoredRunId !== null &&
    monitoredRunId === activeRunId &&
    runStatus !== "idle";

  const historyRefreshKey = activeRunId
    ? `${activeRunId}:${runStatus === "completed" || runStatus === "failed" ? runStatus : "active"}`
    : "";
  const documentRunHistory = useDocumentRunHistory(
    projectId,
    selectedDocument?.id ?? null,
    historyRefreshKey,
  );

  const displayedDocumentRuns = useMemo(() => {
    if (!selectedDocument || !activeRunId) return documentRunHistory.items;
    const liveResult = runResults?.find(
      (result) => result.documentId === selectedDocument.id && result.runId === activeRunId,
    );
    if (!liveResult) return documentRunHistory.items;

    return documentRunHistory.items.map((item) => {
      if (item.runId !== activeRunId) return item;
      return {
        ...item,
        runStatus: runStatus === "idle" ? item.runStatus : runStatus,
        resultStatus: getLiveResultStatus(liveResult),
        comparisonStatus:
          liveResult.status === "pass"
            ? "matched"
            : liveResult.status === "differs"
              ? "mismatched"
              : item.comparisonStatus,
        reviewStatus: liveResult.acceptedAsGT
          ? "accepted"
          : liveResult.rejected
            ? "rejected"
            : item.reviewStatus,
      };
    });
  }, [activeRunId, documentRunHistory.items, runResults, runStatus, selectedDocument]);

  const isDragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number>(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ---- Drag-to-resize ----
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!isDragging.current || !containerRef.current) return;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        if (!containerRef.current) return;
        const rect = containerRef.current.getBoundingClientRect();
        const pct = ((e.clientX - rect.left) / rect.width) * 100;
        const clamped = Math.min(Math.max(pct, 20), 80);
        setRightPanelWidth(100 - clamped);
      });
    };

    const onMouseUp = () => {
      if (isDragging.current) {
        isDragging.current = false;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  useEffect(() => {
    if (isRunMonitoringVisible) {
      setActiveTab("run");
    }
  }, [isRunMonitoringVisible]);

  // ---- Handlers ----
  const handleUpload = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (!files || files.length === 0) return;
      try {
        await uploadDocuments(Array.from(files));
        void message.success(t("projects:filesUploaded", { count: files.length }));
      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : t("projects:uploadFailed");
        void message.error(errorMsg);
      } finally {
        // Reset input so same file can be re-selected
        e.target.value = "";
      }
    },
    [t, uploadDocuments],
  );

  const handleDelete = useCallback(
    (id: string) => {
      Modal.confirm({
        title: t("projects:deleteDocument"),
        content: t("workspaces:actionCannotUndo", { ns: "workspaces" }),
        okButtonProps: { danger: true },
        onOk: () => deleteDocument(id),
      });
    },
    [deleteDocument, t],
  );

  const handleRowClick = useCallback((record: ProjectDocument) => {
    setSelectedDocument(record);
    setActiveTab("docs");
  }, []);

  const handleCloseRightPanel = useCallback(() => {
    setSelectedDocument(null);
  }, []);

  const handleRunWorkflow = useCallback(() => {
    const basePath = getDatabaseBasePath(location.pathname);
    navigate(`${basePath}/${projectId}/run`, {
      state: { selectedDocIds: selectedRowKeys.map(String) },
    });
  }, [navigate, projectId, selectedRowKeys, location.pathname]);

  // ---- Table columns ----
  const columns: TableColumnsType<ProjectDocument> = [
    {
      title: t("projects:fileName"),
      dataIndex: "filename",
      key: "filename",
      width: 380,
      sorter: (a, b) => a.filename.localeCompare(b.filename),
      render: (name: string, record: ProjectDocument) => (
        <div className="document-filename-cell">
          <DocumentThumbnail
            documentId={record.id}
            filename={name}
            mimeType={record.type}
            onPreview={() => handleRowClick(record)}
            testSetId={projectId}
          />
          <Tooltip placement="topLeft" title={name}>
            <Typography.Text className="document-filename-text" strong>
              {name}
            </Typography.Text>
          </Tooltip>
        </div>
      ),
    },
    {
      title: t("projects:fileType"),
      dataIndex: "type",
      key: "type",
      width: 80,
      render: (type: string) => <Tag>{type}</Tag>,
    },
    {
      title: t("projects:fileSize"),
      dataIndex: "size",
      key: "size",
      width: 100,
      sorter: (a, b) => a.size - b.size,
      render: (s: number) => formatFileSize(s),
    },
    {
      title: t("projects:uploaded"),
      dataIndex: "uploadedAt",
      key: "uploadedAt",
      width: 140,
      sorter: (a, b) =>
        new Date(a.uploadedAt).getTime() - new Date(b.uploadedAt).getTime(),
      render: (d: string) => formatRelativeTime(d),
    },
    {
      title: t("projects:gtStatus"),
      dataIndex: "gtStatus",
      key: "gtStatus",
      width: 120,
      render: (status: string, record: ProjectDocument) => {
        const accepted = runResults?.find(
          (r) => r.documentId === record.id && r.acceptedAsGT,
        );
        if (accepted) {
          return <Tag color="green">{t("projects:approved")}</Tag>;
        }
        const cfg = GT_STATUS_CONFIG[status] ?? GT_STATUS_CONFIG.none;
        return <Tag color={cfg.color}>{t(cfg.labelKey)}</Tag>;
      },
    },
    {
      title: t("common:actions"),
      key: "actions",
      width: 80,
      render: (_: unknown, record: ProjectDocument) => (
        <PermissionButton
          capability="document.delete"
          danger
          data-testid={`delete-doc-${record.id}`}
          onClick={(e) => {
            e.stopPropagation();
            handleDelete(record.id);
          }}
          size="small"
          type="link"
        >
          {t("common:delete")}
        </PermissionButton>
      ),
    },
  ];

  // ---- Loading / Error states ----
  if (loading) {
    return (
      <Flex align="center" data-testid="documents-loading" justify="center" style={{ flex: 1 }}>
        <Spin size="large" />
      </Flex>
    );
  }

  if (error) {
    return (
      <Flex align="center" data-testid="documents-error" justify="center" style={{ flex: 1 }}>
        <Alert message={t("settings:error")} showIcon type="error" description={error} />
      </Flex>
    );
  }

  // ---- Toolbar ----
  const toolbar = (
    <Flex className="documents-toolbar" data-testid="documents-toolbar" gap={8}>
      <PermissionButton capability="document.upload" data-testid="btn-upload" icon={<UploadOutlined />} onClick={handleUpload} type="primary">
        {t("common:upload")}
      </PermissionButton>
      <Button data-testid="btn-filter" icon={<FilterOutlined />}>{t("projects:filter")}</Button>
      <Button data-testid="btn-sort" icon={<SortAscendingOutlined />}>{t("projects:sort")}</Button>
    </Flex>
  );

  // ---- Bulk selection bar ----
  const bulkBar =
    selectedRowKeys.length > 0 ? (
      <div className="documents-bulk-bar" data-testid="documents-bulk-bar">
        <span className="documents-bulk-bar-count">{t("projects:selected", { count: selectedRowKeys.length })}</span>
        <PermissionButton
          capability="run.create"
          data-testid="btn-run-workflow"
          icon={<PlayCircleOutlined />}          onClick={handleRunWorkflow}
          type="primary"
        >
          {t("projects:runWorkflow")}
        </PermissionButton>
      </div>
    ) : null;

  // ---- Document table ----
  const docTable = (
    <Table
      className="documents-table"
      columns={columns}
      data-testid="documents-table"
      dataSource={documents}
      locale={{ emptyText: t("projects:noDocuments") }}
      onRow={(record) => ({
        onClick: () => handleRowClick(record),
        className: selectedDocument?.id === record.id ? "documents-table-row--selected" : "",
        "data-testid": `doc-row-${record.id}`,
      })}
      pagination={false}
      rowKey="id"
      rowSelection={{
        selectedRowKeys,
        onChange: (keys) => setSelectedRowKeys(keys),
      }}
      size="middle"
      scroll={{ x: 920 }}
    />
  );

  // ---- Run monitoring derived state ----
  const showRightPanel = selectedDocument !== null || isRunMonitoringVisible;
  const completedCount = runProgress.filter((p) => p.status === "complete").length;
  const failedCount = runProgress.filter((p) => p.status === "failed").length;
  const skippedCount = runProgress.filter((p) => p.status === "skipped").length;
  const processedCount = completedCount + failedCount + skippedCount;
  const overallPercent = runProgress.length > 0 ? Math.round((processedCount / runProgress.length) * 100) : 0;

  const runProgressList = (
    <div className="rwp-doc-progress-list">
      {runProgress.map((item) => (
        <div
          key={item.documentId}
          className={`rwp-doc-progress-item${
            item.status === "processing" ? " rwp-doc-progress-processing" : ""
          }${item.status === "complete" ? " rwp-doc-progress-complete" : ""}`}
          data-testid={`run-progress-${item.documentId}`}
        >
          <span className="rwp-doc-progress-icon">
            {item.status === "pending" && <ClockCircleOutlined style={{ color: "#8c8c8c" }} />}
            {item.status === "processing" && <LoadingOutlined style={{ color: "#7132f5" }} />}
            {item.status === "complete" && <CheckCircleOutlined style={{ color: "#149e61" }} />}
            {item.status === "failed" && <CloseCircleOutlined style={{ color: "#d9363e" }} />}
            {item.status === "skipped" && <MinusCircleOutlined style={{ color: "#8c8c8c" }} />}
          </span>
          <span className="rwp-doc-progress-name">{item.documentName}</span>
          <EvaluationStatusBadge status={PROGRESS_STATUS_TO_EVALUATION_STATUS[item.status]} />
        </div>
      ))}
    </div>
  );

  const batchRunTabContent = (() => {
    if (runStatus === "pending" || runStatus === "running") {
      return (
        <div className="right-panel-tab-content" data-testid="tab-run-content">
          <Flex vertical gap={16}>
            <div>
              <Typography.Text strong>{t("projects:processingDocuments")}</Typography.Text>
              <Progress
                percent={overallPercent}
                status="active"
                strokeColor={{ from: "#7132f5", to: "#149e61" }}
              />
              <Typography.Text type="secondary">
                {t("projects:documentsProcessed", { processed: processedCount, total: runProgress.length })}
              </Typography.Text>
            </div>
            {runProgressList}
          </Flex>
        </div>
      );
    }

    if (runStatus === "completed") {
      return (
        <div className="right-panel-tab-content" data-testid="tab-run-content">
          <Flex vertical gap={16}>
            <Alert
              type="success"
              showIcon
              message={t("projects:runComplete")}
              description={t("projects:allProcessed", { count: runProgress.length })}
            />
            {runProgressList}
          </Flex>
        </div>
      );
    }

    if (runStatus === "partial_completed") {
      return (
        <div className="right-panel-tab-content" data-testid="tab-run-content">
          <Flex vertical gap={16}>
            <Alert
              type="warning"
              showIcon
              message={t("projects:runPartiallyComplete")}
              description={t("projects:partialSummary", { completed: completedCount, failed: failedCount, skipped: skippedCount })}
            />
            {runProgressList}
          </Flex>
        </div>
      );
    }

    if (runStatus === "failed") {
      return (
        <div className="right-panel-tab-content" data-testid="tab-run-content">
          <Flex vertical gap={16}>
            <Alert
              type="error"
              showIcon
              message={t("projects:runFailed")}
              description={t("projects:failedSummary", { completed: completedCount, failed: failedCount, skipped: skippedCount })}
            />
            {runProgressList}
          </Flex>
        </div>
      );
    }

    if (runStatus === "cancelled") {
      return (
        <div className="right-panel-tab-content" data-testid="tab-run-content">
          <Flex vertical gap={16}>
            <Alert
              type="warning"
              showIcon
              message={t("projects:runCancelled")}
              description={t("projects:cancelledSummary", { completed: completedCount, skipped: skippedCount })}
            />
            {runProgressList}
          </Flex>
        </div>
      );
    }

    return (
      <div className="right-panel-tab-content" data-testid="tab-run-content">
        <Flex align="center" justify="center" style={{ padding: "32px 0" }} vertical gap={8}>
          <PlayCircleOutlined style={{ fontSize: 32, color: "#8c8c8c" }} />
          <Typography.Text type="secondary">
            {t("projects:noActiveRun")}
          </Typography.Text>
        </Flex>
      </div>
    );
  })();

  const documentRunTabContent = (() => {
    if (documentRunHistory.loading) {
      return (
        <Flex
          align="center"
          className="right-panel-tab-content"
          data-testid="document-run-history-loading"
          justify="center"
          style={{ minHeight: 160 }}
        >
          <Spin />
        </Flex>
      );
    }

    if (documentRunHistory.error) {
      return (
        <div className="right-panel-tab-content">
          <Alert
            action={<Button onClick={documentRunHistory.retry} size="small">{t("common:retry")}</Button>}
            data-testid="document-run-history-error"
            description={documentRunHistory.error}
            message={t("projects:runHistoryFailed")}
            showIcon
            type="error"
          />
        </div>
      );
    }

    if (displayedDocumentRuns.length === 0) {
      return (
        <Flex
          align="center"
          className="right-panel-tab-content"
          data-testid="document-run-history-empty"
          justify="center"
          style={{ minHeight: 160, textAlign: "center" }}
        >
          <Typography.Text type="secondary">
            {t("projects:notProcessed")}
          </Typography.Text>
        </Flex>
      );
    }

    return (
      <div className="right-panel-tab-content document-run-history" data-testid="document-run-history">
        {displayedDocumentRuns.map((item, index) => (
          <div
            className="document-run-history-card"
            data-testid={`document-run-history-item-${item.runId}`}
            key={item.resultId}
          >
            <Flex align="flex-start" justify="space-between" gap={12}>
              <div className="document-run-history-heading">
                <Flex align="center" gap={6} wrap>
                  <Typography.Text strong>
                    {item.workflowName || item.workflowId}
                  </Typography.Text>
                  {index === 0 ? <Tag color="purple">{t("projects:latestRun")}</Tag> : null}
                </Flex>
                {item.runName ? (
                  <Typography.Text type="secondary">{item.runName}</Typography.Text>
                ) : null}
              </div>
              <EvaluationStatusBadge status={item.resultStatus} />
            </Flex>

            <div className="document-run-history-meta">
              <span>{formatRelativeTime(item.createdAt)}</span>
              <span>{t("projects:documentDuration", { duration: formatMilliseconds(item.processingTimeMs) })}</span>
              <span>{t("projects:fullRunDuration", { duration: formatMilliseconds(item.runDurationMs) })}</span>
            </div>

            <Flex align="center" gap={6} wrap>
              <Typography.Text type="secondary">{t("workflows:run", { ns: "workflows" })}</Typography.Text>
              <EvaluationStatusBadge status={item.runStatus} />
              {item.reviewStatus === "accepted" ? <Tag color="green">{t("projects:acceptedAsGt")}</Tag> : null}
              {item.reviewStatus === "rejected" ? <Tag color="red">{t("common:statuses.rejected")}</Tag> : null}
              {item.comparisonStatus === "matched" ? <Tag color="green">{t("common:statuses.matched")}</Tag> : null}
              {item.comparisonStatus === "mismatched" ? <Tag color="gold">{t("projects:differs")}</Tag> : null}
            </Flex>

            {item.error ? (
              <Alert
                className="document-run-history-error-summary"
                data-testid={`document-run-history-error-${item.runId}`}
                message={item.error}
                showIcon
                type="error"
              />
            ) : null}

            <Button
              data-testid={`view-full-run-${item.runId}`}
              onClick={() => onViewFullRun(item.runId)}
              size="small"
              type="link"
            >
              {t("projects:viewFullRun")}
            </Button>
          </div>
        ))}
      </div>
    );
  })();

  // ---- RightPanel ----
  const panelTitle = selectedDocument ? selectedDocument.filename : t("projects:runMonitoring");

  const rightPanel = showRightPanel ? (
    <div
      className="right-panel"
      data-testid="right-panel"
      style={{ width: `${rightPanelWidth}%`, minWidth: 250 }}
    >
      <div className="right-panel-header">
        <span className="right-panel-header-title">{panelTitle}</span>
        {selectedDocument && (
          <button
            aria-label={t("projects:closePanel")}
            className="right-panel-close-btn"
            data-testid="close-right-panel"
            onClick={handleCloseRightPanel}
            type="button"
          >
            <CloseOutlined />
          </button>
        )}
      </div>
      <Tabs
        activeKey={activeTab}
        className="right-panel-tabs"
        data-testid="right-panel-tabs"
        items={[
          {
            key: "docs",
            label: t("projects:docs"),
            children: selectedDocument ? (
              <div className="right-panel-tab-content" data-testid="tab-docs-content">
                <Flex vertical gap={12}>
                  <div>
                    <Typography.Text type="secondary">{t("projects:fileName")}</Typography.Text>
                    <div className="right-panel-value">{selectedDocument.filename}</div>
                  </div>
                  <div>
                    <Typography.Text type="secondary">{t("projects:fileType")}</Typography.Text>
                    <div className="right-panel-value">{selectedDocument.type}</div>
                  </div>
                  <div>
                    <Typography.Text type="secondary">{t("projects:fileSize")}</Typography.Text>
                    <div className="right-panel-value">{formatFileSize(selectedDocument.size)}</div>
                  </div>
                  <div>
                    <Typography.Text type="secondary">{t("projects:uploaded")}</Typography.Text>
                    <div className="right-panel-value">{formatRelativeTime(selectedDocument.uploadedAt)}</div>
                  </div>
                  <div>
                    <Typography.Text type="secondary">{t("projects:gtStatus")}</Typography.Text>
                    <Tag color={GT_STATUS_CONFIG[selectedDocument.gtStatus].color}>
                      {t(GT_STATUS_CONFIG[selectedDocument.gtStatus].labelKey)}
                    </Tag>
                  </div>
                </Flex>
              </div>
            ) : (
              <div className="right-panel-tab-content" data-testid="tab-docs-content">
                <Flex align="center" justify="center" style={{ padding: "32px 0" }} vertical>
                  <Typography.Text type="secondary">{t("projects:selectDocumentDetails")}</Typography.Text>
                </Flex>
              </div>
            ),
          },
          {
            key: "run",
            label: selectedDocument ? `${t("projects:runs")} (${documentRunHistory.total})` : t("workflows:run", { ns: "workflows" }),
            children: selectedDocument ? documentRunTabContent : batchRunTabContent,
          },
          {
            key: "compare",
            label: t("projects:compare"),
            children: (
              <div className="right-panel-tab-content" data-testid="tab-compare-content">
                {selectedDocument ? (
                  <CompareView
                    documentId={selectedDocument.id}
                    expectedContent=""
                    actualContent=""
                    differences={[]}
                  />
                ) : (
                  <Flex align="center" justify="center" style={{ padding: "32px 0" }} vertical>
                    <Typography.Text type="secondary">{t("projects:selectDocumentCompare")}</Typography.Text>
                  </Flex>
                )}
              </div>
            ),
          },
          {
            key: "gt",
            label: "GT",
            children: selectedDocument ? (
              <DocumentGroundTruthPanel
                documentId={selectedDocument.id}
                projectId={projectId}
              />
            ) : (
              <Flex
                align="center"
                className="right-panel-tab-content"
                data-testid="tab-gt-content"
                justify="center"
                style={{ minHeight: 160 }}
              >
                <Typography.Text type="secondary">
                  {t("projects:selectDocumentGt")}
                </Typography.Text>
              </Flex>
            ),
          },
          {
            key: "history",
            label: t("workflows:history", { ns: "workflows" }),
            children: (
              <div className="right-panel-tab-content" data-testid="tab-history-content">
                <Alert message={t("projects:historyLater")} type="info" />
              </div>
            ),
          },
        ]}
        onChange={setActiveTab}
      />
    </div>
  ) : null;

  return (
    <div className="documents-container" data-testid="documents-container" style={{ flex: 1, display: "flex", flexDirection: "column" }}>
      <input
        ref={fileInputRef}
        type="file"
        multiple
        style={{ display: "none" }}
        onChange={handleFileChange}
        data-testid="documents-file-input"
      />
      {toolbar}
      {bulkBar}
      <div
        ref={containerRef}
        className={`documents-body ${showRightPanel ? "documents-body--split" : ""}`}
        data-testid="documents-body"
      >
        <div
          className="documents-preview"
          data-testid="documents-preview"
          style={{ width: showRightPanel ? `${100 - rightPanelWidth}%` : "100%", minWidth: showRightPanel ? 250 : undefined }}
        >
          {selectedDocument ? (
            <div className="documents-preview-detail">
              <Button
                className="documents-preview-back-btn"
                data-testid="btn-back-to-documents"
                icon={<ArrowLeftOutlined />}
                onClick={handleCloseRightPanel}
                type="text"
              >
                {t("projects:backToDocuments")}
              </Button>
              <div className="documents-preview-detail-content">
                <DocumentPreview
                  testSetId={projectId}
                  documentId={selectedDocument.id}
                  filename={selectedDocument.filename}
                  mimeType={selectedDocument.type}
                />
              </div>
            </div>
          ) : (
            docTable
          )}
        </div>

        {showRightPanel && (
          <div
            className="documents-divider"
            data-testid="documents-divider"
            onMouseDown={handleMouseDown}
          >
            <div className="documents-divider-handle" />
          </div>
        )}

        {rightPanel}
      </div>
    </div>
  );
}
