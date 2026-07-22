import {
  ArrowLeftOutlined,
  CloseOutlined,
  FilterOutlined,
  PlayCircleOutlined,
} from "@ant-design/icons";
import type { TableColumnsType } from "antd";
import { Alert, Button, Flex, Space, Spin, Table, Tag, Typography } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, type NavigateFunction } from "react-router-dom";
import { useTranslation } from "react-i18next";

import CompareView from "@/features/projects/components/CompareView";
import DocumentPreview from "@/features/projects/components/DocumentPreview";
import { EvaluationStatusBadge } from "@/features/projects/components/EvaluationStatusBadge";
import { diffToFieldDiff } from "@/features/projects/components/utils";
import { useProjectRuns } from "@/features/projects/hooks/useProjectRuns";
import type { RunStatus } from "@/features/projects/hooks/useActiveRun";
import { getDatabaseBasePath } from "@/features/projects/utils/databaseBasePath";
import type { FieldDiff } from "@/features/projects/types";
import { PermissionButton } from "@/components/Permissions/PermissionButton";
import { usePermission } from "@/hooks/usePermission";
import { compareResult, type CompareResponse } from "@/services/projectApi";
import type { ProjectRun, RunResult } from "@/types/project";
import { formatRelativeTime } from "@/utils/dateFormat";

interface RunsViewProps {
  projectId: string;
  navigate: NavigateFunction;
  activeRunId: string | null;
  runError: string | null;
  runResults: RunResult[];
  runStatus: RunStatus;
  selectedRunId: string | null;
  selectedRunDocument: RunResult | null;
  onOpenRun: (runId: string) => void;
  onSelectRunId: (runId: string | null) => void;
  onSelectRunDocument: (result: RunResult) => void;
  onCloseRunDocument: () => void;
  onAcceptAsGT: (docId: string) => void;
  onRejectResult: (docId: string) => void;
  onResultComparison: (resultId: string, comparisonStatus: string) => void;
}

const RESULT_STATUS_CONFIG: Record<string, { color: string; labelKey: string }> = {
  pass: { color: "green", labelKey: "projects:pass" },
  differs: { color: "gold", labelKey: "projects:differs" },
  error: { color: "red", labelKey: "settings:error" },
  failed: { color: "red", labelKey: "common:statuses.failed" },
  running: { color: "blue", labelKey: "common:statuses.running" },
  no_gt: { color: "default", labelKey: "projects:noGt" },
  unknown: { color: "default", labelKey: "common:unknown" },
};

const EVALUATION_RESULT_STATUSES = new Set([
  "queued",
  "running",
  "completed",
  "failed",
  "skipped",
]);

function formatDuration(seconds: number | undefined): string {
  if (seconds == null) return "-";
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
}

export default function RunsView({
  projectId,
  navigate,
  activeRunId,
  runError,
  runResults,
  runStatus,
  selectedRunId,
  selectedRunDocument,
  onOpenRun,
  onSelectRunId,
  onSelectRunDocument,
  onCloseRunDocument,
  onAcceptAsGT,
  onRejectResult,
  onResultComparison,
}: RunsViewProps) {
  const { t } = useTranslation(["common", "projects", "settings"]);
  const location = useLocation();
  const { can } = usePermission();
  const canViewRuns = can("run.view");
  const { items, loading, error } = useProjectRuns(projectId);

  const [comparePanelWidth, setComparePanelWidth] = useState(50);
  const [compareData, setCompareData] = useState<CompareResponse | null>(null);

  const isDragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number>(0);
  const selectedRun = useMemo(
    () => items.find((item) => item.id === selectedRunId) ?? null,
    [items, selectedRunId],
  );

  const handleNewRun = useCallback(() => {
    const basePath = getDatabaseBasePath(location.pathname);
    navigate(`${basePath}/${projectId}/run`);
  }, [navigate, projectId, location.pathname]);

  useEffect(() => {
    if (!canViewRuns || !selectedRunDocument || !activeRunId) {
      return;
    }
    let cancelled = false;
    setCompareData(null);
    void (async () => {
      try {
        const data = await compareResult(activeRunId, selectedRunDocument.id);
        if (!cancelled) {
          setCompareData(data);
          onResultComparison(data.result_id, data.comparison_status);
        }
      } catch {
        if (!cancelled) setCompareData(null);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedRunDocument, activeRunId, canViewRuns, onResultComparison]);

  const handleRunRowClick = useCallback(
    (record: ProjectRun) => {
      onSelectRunId(record.id);
      onCloseRunDocument();
      if (record.id !== activeRunId || runResults.length === 0 || runError) {
        onOpenRun(record.id);
      }
    },
    [activeRunId, onCloseRunDocument, onOpenRun, onSelectRunId, runError, runResults.length],
  );

  const handleBackToList = useCallback(() => {
    onSelectRunId(null);
    onCloseRunDocument();
  }, [onCloseRunDocument, onSelectRunId]);

  const handleResultRowClick = useCallback(
    (result: RunResult) => {
      onSelectRunDocument(result);
    },
    [onSelectRunDocument],
  );

  const handleCloseCompare = useCallback(() => {
    onCloseRunDocument();
  }, [onCloseRunDocument]);

  const handleRetryResults = useCallback(() => {
    if (selectedRun) onOpenRun(selectedRun.id);
  }, [onOpenRun, selectedRun]);

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
        setComparePanelWidth(100 - clamped);
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

  // Hooks must be called unconditionally (before early returns)
  const isActiveRun = selectedRun != null && selectedRun.id === activeRunId;
  const effectiveResults = isActiveRun ? runResults : [];
  const isLoadingSelectedRun = selectedRun != null && (
    !isActiveRun || (runStatus === "running" && runResults.length === 0)
  );
  const selectedRunError = isActiveRun ? runError : null;

  const currentResult = selectedRunDocument
    ? (isActiveRun
        ? runResults.find((r) => r.id === selectedRunDocument.id) ??
          selectedRunDocument
        : selectedRunDocument)
    : null;

  const showAcceptReject =
    isActiveRun &&
    currentResult != null &&
    !currentResult.acceptedAsGT &&
    !currentResult.rejected;

  const compareDifferences: FieldDiff[] = useMemo(() => {
    if (!compareData) return currentResult?.diff ? diffToFieldDiff(currentResult.diff) : [];
    if (compareData.comparison_status === "matched") return [];
    if (!compareData.expected_content && !compareData.actual_content) return [];
    return [
      {
        fieldName: t("projects:content"),
        expected: compareData.expected_content ?? "",
        actual: compareData.actual_content ?? "",
        status: compareData.comparison_status === "matched" ? "match" : "mismatch",
      },
    ];
  }, [compareData, currentResult, t]);

  const runColumns: TableColumnsType<ProjectRun> = [
    {
      title: t("projects:runId"),
      dataIndex: "id",
      key: "id",
      width: 100,
      render: (id: string) => (
        <Typography.Text code>{id}</Typography.Text>
      ),
    },
    {
      title: t("projects:workflow"),
      dataIndex: "workflowName",
      key: "workflowName",
      sorter: (a, b) => a.workflowName.localeCompare(b.workflowName),
    },
    {
      title: t("projects:started"),
      dataIndex: "startedAt",
      key: "startedAt",
      width: 140,
      sorter: (a, b) =>
        new Date(a.startedAt).getTime() - new Date(b.startedAt).getTime(),
      render: (d: string) => formatRelativeTime(d),
    },
    {
      title: t("projects:duration"),
      dataIndex: "duration",
      key: "duration",
      width: 90,
      sorter: (a, b) => (a.duration ?? 0) - (b.duration ?? 0),
      render: (d: number | undefined) => formatDuration(d),
    },
    {
      title: t("common:status"),
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (status: string) => <EvaluationStatusBadge status={status} />,
    },
    {
      title: t("projects:documents"),
      dataIndex: "documentCount",
      key: "documentCount",
      width: 100,
      align: "center",
    },
    {
      title: t("projects:passRate"),
      dataIndex: "passRate",
      key: "passRate",
      width: 100,
      align: "center",
      sorter: (a, b) => (a.passRate ?? 0) - (b.passRate ?? 0),
      render: (rate: number | undefined) =>
        rate != null ? (
          <Typography.Text
            strong
            type={rate >= 90 ? "success" : rate >= 70 ? "warning" : "danger"}
          >
            {rate}%
          </Typography.Text>
        ) : (
          "-"
        ),
    },
  ];

  const resultColumns: TableColumnsType<RunResult> = [
    {
      title: t("projects:documents"),
      dataIndex: "documentName",
      key: "documentName",
      render: (name: string) => (
        <Typography.Text strong>{name}</Typography.Text>
      ),
    },
    {
      title: t("common:status"),
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (status: string) => {
        if (EVALUATION_RESULT_STATUSES.has(status)) {
          return <EvaluationStatusBadge status={status} />;
        }
        const cfg = RESULT_STATUS_CONFIG[status];
        return <Tag color={cfg?.color ?? "default"}>{cfg ? t(cfg.labelKey) : status}</Tag>;
      },
    },
    {
      title: t("projects:groundTruth"),
      key: "groundTruth",
      width: 125,
      render: (_: unknown, record: RunResult) =>
        record.hasGroundTruth ? (
          <Tag color="green">{t("projects:available")}</Tag>
        ) : (
          <Tag>{t("projects:missing")}</Tag>
        ),
    },
    {
      title: t("projects:review"),
      key: "review",
      width: 120,
      render: (_: unknown, record: RunResult) =>
        record.acceptedAsGT ? (
          <Tag color="green">{t("common:statuses.accepted")}</Tag>
        ) : record.rejected ? (
          <Tag color="red">{t("common:statuses.rejected")}</Tag>
        ) : (
          <Tag>{t("projects:unreviewed")}</Tag>
        ),
    },
    {
      title: t("projects:differences"),
      dataIndex: "diff",
      key: "diff",
      width: 100,
      align: "center",
      render: (diff: string[] | undefined) => diff && diff.length > 0 ? diff.length : "-",
    },
  ];

  if (loading) {
    return (
      <Flex
        align="center"
        data-testid="runs-loading"
        justify="center"
        style={{ flex: 1 }}
      >
        <Spin size="large" />
      </Flex>
    );
  }

  if (error) {
    return (
      <Flex align="center" justify="center" style={{ flex: 1 }}>
        <Alert
          data-testid="runs-error"
          message={t("settings:error")}
          showIcon
          type="error"
          description={error}
        />
      </Flex>
    );
  }

  const toolbar = (
    <Flex
      className="runs-toolbar"
      data-testid="runs-toolbar"
      gap={8}
    >
      <PermissionButton
        capability="run.create"
        data-testid="btn-new-run"
        icon={<PlayCircleOutlined />}
        onClick={handleNewRun}
        type="primary"
      >
        {t("projects:newRun")}
      </PermissionButton>
      <Button data-testid="btn-filter-runs" icon={<FilterOutlined />}>
        {t("projects:filter")}
      </Button>
    </Flex>
  );

  const compareTab =
    canViewRuns && currentResult ? (
      <div className="runs-compare" data-testid="runs-compare">
        <Typography.Text
          strong
          style={{ display: "block", marginBottom: 12 }}
        >
          {currentResult.documentName}
        </Typography.Text>
        <CompareView
          documentId={currentResult.documentId}
          expectedContent={compareData?.expected_content ?? ""}
          actualContent={compareData?.actual_content ?? ""}
          differences={compareDifferences}
          {...(showAcceptReject
            ? {
                onAcceptAsGT: () =>
                  onAcceptAsGT(currentResult.documentId),
                onReject: () =>
                  onRejectResult(currentResult.documentId),
              }
            : {})}
        />
      </div>
    ) : null;

  const runDetail = selectedRun ? (
    <div className="runs-detail" data-testid="runs-detail">
      <div className="runs-detail-header">
        <button
          className="runs-detail-back-btn"
          data-testid="btn-back-to-runs"
          onClick={handleBackToList}
          type="button"
        >
          <ArrowLeftOutlined /> {t("projects:backToRuns")}
        </button>
        <div className="runs-detail-title-row">
          <Typography.Title
            data-testid="run-detail-name"
            level={4}
            style={{ margin: 0 }}
          >
            {selectedRun.name ?? selectedRun.id}
          </Typography.Title>
          <EvaluationStatusBadge status={selectedRun.status} />
        </div>
      </div>

      {!isLoadingSelectedRun && !selectedRunError ? (
        <div className="runs-detail-summary" data-testid="run-detail-summary">
          <Space size={24} wrap>
            <div className="runs-detail-stat">
              <span className="runs-detail-stat-label">{t("projects:total")}</span>
              <span className="runs-detail-stat-value">
                {effectiveResults.length}
              </span>
            </div>
            <div className="runs-detail-stat">
              <span className="runs-detail-stat-label">{t("projects:pass")}</span>
              <span className="runs-detail-stat-value runs-detail-stat-value--pass">
                {effectiveResults.filter((r) => r.status === "pass").length}
              </span>
            </div>
            <div className="runs-detail-stat">
              <span className="runs-detail-stat-label">{t("projects:differs")}</span>
              <span className="runs-detail-stat-value runs-detail-stat-value--differs">
                {effectiveResults.filter((r) => r.status === "differs").length}
              </span>
            </div>
            <div className="runs-detail-stat">
              <span className="runs-detail-stat-label">{t("projects:errors")}</span>
              <span className="runs-detail-stat-value runs-detail-stat-value--error">
                {effectiveResults.filter((r) => r.status === "error" || r.status === "failed").length}
              </span>
            </div>
            <div className="runs-detail-stat">
              <span className="runs-detail-stat-label">{t("projects:noGt")}</span>
              <span className="runs-detail-stat-value">
                {effectiveResults.filter((r) => r.status === "no_gt").length}
              </span>
            </div>
            <div className="runs-detail-stat">
              <span className="runs-detail-stat-label">{t("projects:acceptedAsGt")}</span>
              <span className="runs-detail-stat-value runs-detail-stat-value--gt">
                {effectiveResults.filter((r) => r.acceptedAsGT).length}
              </span>
            </div>
          </Space>
        </div>
      ) : null}

      {isLoadingSelectedRun ? (
        <Flex
          align="center"
          data-testid="run-results-loading"
          justify="center"
          style={{ minHeight: 180 }}
        >
          <Spin />
        </Flex>
      ) : selectedRunError ? (
        <Alert
          action={(
            <Button onClick={handleRetryResults} size="small">
              {t("common:retry")}
            </Button>
          )}
          data-testid="run-results-error"
          description={selectedRunError}
          message={t("projects:runResultsFailed")}
          showIcon
          type="error"
        />
      ) : selectedRunDocument ? (
        <div
          ref={containerRef}
          className="runs-compare-split"
          data-testid="runs-compare-split"
        >
          <div
            className="runs-compare-preview"
            data-testid="runs-compare-preview"
            style={{
              width: `${100 - comparePanelWidth}%`,
              minWidth: 250,
            }}
          >
            <DocumentPreview
              testSetId={projectId}
              documentId={selectedRunDocument.documentId}
              filename={selectedRunDocument.documentName}
            />
          </div>

          <div
            className="runs-compare-divider"
            data-testid="runs-compare-divider"
            onMouseDown={handleMouseDown}
          >
            <div className="runs-compare-divider-handle" />
          </div>

          <div
            className="runs-compare-right"
            data-testid="runs-compare-right"
            style={{
              width: `${comparePanelWidth}%`,
              minWidth: 250,
            }}
          >
            <div className="runs-compare-right-header">
              <span className="runs-compare-right-title">{t("projects:compare")}</span>
              <button
                aria-label={t("projects:closePanel")}
                className="runs-compare-close-btn"
                data-testid="btn-close-compare"
                onClick={handleCloseCompare}
                type="button"
              >
                <CloseOutlined />
              </button>
            </div>
            <div className="runs-compare-right-body">
              {compareTab}
            </div>
          </div>
        </div>
      ) : (
        <div className="runs-detail-results" data-testid="run-detail-results">
          <Typography.Text strong style={{ marginBottom: 8, display: "block" }}>
            {t("projects:perDocumentResults")}
          </Typography.Text>
          <Table
            columns={resultColumns}
            data-testid="run-results-table"
            dataSource={effectiveResults}
            locale={{ emptyText: t("projects:noRunResults") }}
            onRow={(record) => ({
              onClick: () => handleResultRowClick(record),
              "data-testid": `result-row-${record.id}`,
            })}
            pagination={false}
            rowKey="id"
            size="small"
          />
        </div>
      )}
    </div>
  ) : (
    <div className="runs-view" data-testid="runs-view" style={{ flex: 1, display: "flex", flexDirection: "column" }}>
      {toolbar}
      <Table
        className="runs-table"
        columns={runColumns}
        data-testid="runs-table"
        dataSource={items}
        locale={{ emptyText: t("projects:noRuns") }}
        onRow={(record) => ({
          onClick: () => handleRunRowClick(record),
          "data-testid": `run-row-${record.id}`,
        })}
        pagination={false}
        rowKey="id"
        size="middle"
      />
    </div>
  );

  return (
    <div data-testid="runs-container" style={{ flex: 1, display: "flex", flexDirection: "column" }}>
      {runDetail}
    </div>
  );
}
