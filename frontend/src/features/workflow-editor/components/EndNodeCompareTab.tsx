import { Button, Empty, Select, Space, Typography } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useResultStore } from "@/features/result/store";
import { usePermission } from "@/hooks/usePermission";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { type DiffLine, type DiffLineType, useDiffHighlight } from "@/features/workflow-editor/hooks/useDiffHighlight";
import { useSyncScroll } from "@/features/workflow-editor/hooks/useSyncScroll";
import { getTaskHistory, getTaskResults } from "@/services/taskApi";
import type { TaskHistoryItem, TaskResult } from "@/types/task";
import { useUIStore } from "@/stores/uiStore";
import { formatRelativeTime } from "@/utils/dateFormat";
import { inputFilesMatch } from "@/utils/inputFileIdentity";
import { buildWorkspaceScopedUrl } from "@/services/workspaceTransport";
import { captureWorkspaceContext, isWorkspaceContextCurrent } from "@/stores/workspaceStore";

const LINE_TYPE_CLASS: Record<DiffLineType, string> = {
  same: "",
  added: "compare-line-added",
  removed: "compare-line-removed",
  modified: "compare-line-modified"
};

const MAX_COMPARE_RUNS = 4;

const toPlainLines = (content: string): DiffLine[] =>
  content.split("\n").map((line) => ({
    content: line,
    type: "same",
    isPlaceholder: false
  }));

function triggerDownload(downloadUrl: string, filename: string): void {
  if (typeof document === "undefined") {
    return;
  }
  const link = document.createElement("a");
  link.href = buildWorkspaceScopedUrl(downloadUrl);
  link.download = filename;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

interface RunResult {
  taskId: string;
  taskName: string;
  results: TaskResult[];
  timestamp: string;
}

export default function EndNodeCompareTab() {
  const { t } = useTranslation("workflows");
  const { can } = usePermission();
  const currentTaskId = useTaskExecutionStore((state) => state.currentTaskId);
  const lastRunInputFiles = useTaskExecutionStore((state) => state.lastRunInputFiles);
  const storeTaskId = useResultStore((state) => state.taskId);
  const storeResults = useResultStore((state) => state.results);
  const [isDiffModeEnabled, setIsDiffModeEnabled] = useState(false);
  const [isScrollSyncEnabled, setIsScrollSyncEnabled] = useState(true);
  const leftContentRef = useRef<HTMLPreElement | null>(null);
  const rightContentRef = useRef<HTMLPreElement | null>(null);

  // Run selector state
  const [recentRuns, setRecentRuns] = useState<TaskHistoryItem[]>([]);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [loadedRuns, setLoadedRuns] = useState<Map<string, RunResult>>(new Map());
  const [loadingRuns, setLoadingRuns] = useState<Set<string>>(new Set());

  // Re-fetch runs whenever this tab becomes active or a run finishes
  const rightPanelTab = useUIStore((state) => state.rightPanelTab);
  const taskStatus = useTaskExecutionStore((state) => state.taskStatus);
  useEffect(() => {
    if (!can("run.view") || rightPanelTab !== "compare") return;
    let mounted = true;
    void getTaskHistory({ limit: 20 }).then((response) => {
      if (!mounted) return;
      setRecentRuns(response.items);
    });
    return () => { mounted = false; };
  }, [can, rightPanelTab, taskStatus]);

  // Filter to only runs with the same input files as the current task
  const filteredRuns = useMemo(() => {
    if (!lastRunInputFiles || lastRunInputFiles.length === 0) {
      return recentRuns;
    }
    return recentRuns.filter((run) => inputFilesMatch(run.input_files, lastRunInputFiles));
  }, [recentRuns, lastRunInputFiles]);

  // Auto-select current task on mount (only when a task has been executed)
  useEffect(() => {
    if (currentTaskId && selectedRunIds[0] !== currentTaskId) {
      setSelectedRunIds([currentTaskId]);
    }
  }, [currentTaskId, selectedRunIds]);

  // Load current task results into loadedRuns if available
  useEffect(() => {
    if (
      currentTaskId &&
      storeTaskId === currentTaskId &&
      storeResults.length > 0
    ) {
      setLoadedRuns(
        (prev) =>
          new Map([
            ...prev,
            [
              currentTaskId,
              {
                taskId: currentTaskId,
                taskName: (() => { const r = filteredRuns.find((r) => r.task_id === currentTaskId); return r?.run_name ? `${r.run_name} · ${r.task_id}` : r?.workflow_name ?? r?.task_id ?? currentTaskId; })(),
                results: storeResults,
                timestamp: new Date().toISOString()
              }
            ]
          ])
      );
    }
  }, [currentTaskId, storeTaskId, storeResults, filteredRuns]);

  // Load run results when selected
  const loadRunResults = useCallback(async (taskId: string) => {
    if (!can("run.view") || loadedRuns.has(taskId) || loadingRuns.has(taskId)) {
      return;
    }

    const workspaceToken = captureWorkspaceContext();
    setLoadingRuns((prev) => new Set([...prev, taskId]));
    try {
      const response = await getTaskResults(taskId);
      if (!isWorkspaceContextCurrent(workspaceToken) || response.task_id !== taskId) return;
      const historyItem = filteredRuns.find((r) => r.task_id === taskId);
      setLoadedRuns(
        (prev) =>
          new Map([
            ...prev,
            [
              taskId,
              {
                taskId,
                taskName: historyItem?.run_name ? `${historyItem.run_name} · ${taskId}` : historyItem?.workflow_name ?? taskId,
                results: response.results,
                timestamp: historyItem?.started_at ?? new Date().toISOString()
              }
            ]
          ])
      );
    } catch {
      if (!isWorkspaceContextCurrent(workspaceToken)) return;
      // Keep the existing comparison without writing request details to the console.
    } finally {
      if (isWorkspaceContextCurrent(workspaceToken)) {
        setLoadingRuns((prev) => {
          const next = new Set(prev);
          next.delete(taskId);
          return next;
        });
      }
    }
  }, [can, loadedRuns, loadingRuns, filteredRuns]);

  // Auto-load results for any selected run not yet in loadedRuns
  useEffect(() => {
    selectedRunIds.forEach((id) => {
      if (!loadedRuns.has(id) && !loadingRuns.has(id)) {
        void loadRunResults(id);
      }
    });
  }, [selectedRunIds, loadedRuns, loadingRuns, loadRunResults]);

  // Handle run selection change
  const handleRunSelectionChange = useCallback(
    (newSelectedIds: string[]) => {
      if (newSelectedIds.length > MAX_COMPARE_RUNS) {
        return;
      }
      setSelectedRunIds(newSelectedIds);
      newSelectedIds.forEach((id) => {
        void loadRunResults(id);
      });
    },
    [loadRunResults]
  );

  // Collect all results from selected runs
  const allResults = useMemo(() => {
    const results: Array<RunResult & { result: TaskResult; resultIndex: number }> = [];
    selectedRunIds.forEach((runId) => {
      const run = loadedRuns.get(runId);
      if (!run) return;
      run.results.forEach((result, idx) => {
        results.push({ ...run, result, resultIndex: idx });
      });
    });
    return results;
  }, [selectedRunIds, loadedRuns]);

  const leftText = allResults[0]?.result.content ?? "";
  const rightText = allResults[1]?.result.content ?? leftText;
  const { leftLines, rightLines, hasDiff } = useDiffHighlight(leftText, rightText);
  const { handleLeftScroll, handleRightScroll } = useSyncScroll({
    leftRef: leftContentRef,
    rightRef: rightContentRef,
    enabled: isScrollSyncEnabled
  });

  const handleSingleDownload = (result: TaskResult) => {
    const downloadUrl = result.file.download_url;
    triggerDownload(downloadUrl, result.file.filename);
  };

  const handleDownloadAll = () => {
    allResults.forEach((r) => {
      handleSingleDownload(r.result);
    });
  };

  const getDisplayLines = (index: number, content: string): DiffLine[] => {
    if (!isDiffModeEnabled || allResults.length < 2) {
      return toPlainLines(content);
    }
    if (index === 0) return leftLines;
    if (index === 1) return rightLines;
    return toPlainLines(content);
  };

  if (!can("run.view") || allResults.length === 0) {
    return (
      <div className="end-compare-tab">
        <div className="compare-run-selector">
          <Typography.Text type="secondary">{t("editorText.selectRuns")}</Typography.Text>
          <Select
            mode="multiple"
            placeholder={t("editorText.selectRunsPlaceholder")}
            value={selectedRunIds}
            onChange={handleRunSelectionChange}
            style={{ minWidth: 200 }}
            maxCount={MAX_COMPARE_RUNS}
            loading={filteredRuns.length === 0 && recentRuns.length === 0}
          >
            {filteredRuns.map((run) => (
              <Select.Option key={run.task_id} value={run.task_id}>
                <Space>
                  <span>{run.run_name ?? run.workflow_name ?? run.task_id.slice(5, 13)}</span>
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                    {run.run_name ? `${run.task_id.slice(5, 13)} · ` : ""}{formatRelativeTime(run.started_at)}
                  </Typography.Text>
                </Space>
              </Select.Option>
            ))}
          </Select>
        </div>
        <Empty description={t("editorText.selectRunsEmpty")} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    );
  }

  return (
    <div className="end-compare-tab" data-testid="end-node-compare-tab">
      <div className="compare-run-selector">
        <Typography.Text type="secondary">{t("editorText.compareRuns")}</Typography.Text>
        <Select
          mode="multiple"
          placeholder={t("editorText.selectRunsPlaceholder")}
          value={selectedRunIds}
          onChange={handleRunSelectionChange}
          style={{ minWidth: 200 }}
          maxCount={MAX_COMPARE_RUNS}
        >
          {filteredRuns.map((run) => (
            <Select.Option key={run.task_id} value={run.task_id}>
              <Space>
                <span>{run.run_name ?? run.workflow_name ?? run.task_id.slice(5, 13)}</span>
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  {formatRelativeTime(run.started_at)}
                </Typography.Text>
              </Space>
            </Select.Option>
          ))}
        </Select>
      </div>

      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <div className="compare-panel-toolbar">
          <div className="compare-panel-toolbar-actions">
            <Button
              size="small"
              type={isDiffModeEnabled ? "primary" : "default"}
              onClick={() => setIsDiffModeEnabled((enabled) => !enabled)}
              disabled={allResults.length < 2}
            >
              Diff
            </Button>
            <Button
              size="small"
              type={isScrollSyncEnabled ? "primary" : "default"}
              onClick={() => setIsScrollSyncEnabled((enabled) => !enabled)}
            >
              Sync
            </Button>
            <Button size="small" onClick={handleDownloadAll}>
              Download
            </Button>
          </div>
        </div>

        {isDiffModeEnabled && allResults.length >= 2 && !hasDiff ? (
          <Typography.Text type="secondary">{t("editorText.identical")}</Typography.Text>
        ) : null}

        <div className="compare-panel-grid">
          {allResults.map((item, index) => (
            <section className="compare-panel-card" key={`${item.taskId}-${item.resultIndex}`}>
              <Space align="center" style={{ justifyContent: "space-between", width: "100%" }}>
                <Space direction="vertical" size={2}>
                  <Typography.Text strong>{item.result.file.filename}</Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                    {item.taskName}
                  </Typography.Text>
                </Space>
                <Button
                  size="small"
                  onClick={() => handleSingleDownload(item.result)}
                >
                  Download
                </Button>
              </Space>
              <pre
                className="compare-panel-content"
                data-testid={`end-compare-content-${index}`}
                onScroll={index === 0 ? handleLeftScroll : index === 1 ? handleRightScroll : undefined}
                ref={(el) => {
                  if (index === 0) leftContentRef.current = el;
                  else if (index === 1) rightContentRef.current = el;
                }}
              >
                {getDisplayLines(index, item.result.content).map((line, lineIndex) => {
                  const lineTypeClass = isDiffModeEnabled ? LINE_TYPE_CLASS[line.type] : "";
                  return (
                    <span className={`compare-line ${lineTypeClass}`} key={lineIndex}>
                      {line.content || " "}
                      {"\n"}
                    </span>
                  );
                })}
              </pre>
            </section>
          ))}
        </div>
      </Space>
    </div>
  );
}
