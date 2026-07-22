import { Button, Empty, Segmented, Space, Typography } from "antd";
import { useCallback, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { useTranslation } from "react-i18next";

import { useResultStore } from "@/features/result/store";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { type DiffLine, type DiffLineType, useDiffHighlight } from "@/features/workflow-editor/hooks/useDiffHighlight";
import { useSyncScroll } from "@/features/workflow-editor/hooks/useSyncScroll";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { usePermission } from "@/hooks/usePermission";
import { isEndNodeType } from "@/features/workflow-editor/utils/endNodeRepair";
import type { TaskResult, TaskResultDownloadFormat } from "@/types/task";
import { buildWorkspaceScopedUrl } from "@/services/workspaceTransport";
import { formatNumber } from "@/i18n/format";
import { useLanguage } from "@/i18n/useLanguage";

type ViewMode = "raw" | "rendered";

const LINE_TYPE_CLASS: Record<DiffLineType, string> = {
  same: "",
  added: "compare-line-added",
  removed: "compare-line-removed",
  modified: "compare-line-modified"
};

const VIRTUAL_SCROLL_CHAR_THRESHOLD = 10_000;
const VIRTUAL_LINE_HEIGHT_PX = 20;
const VIRTUAL_OVERSCAN_LINES = 24;
const DEFAULT_VIRTUAL_VIEWPORT_HEIGHT_PX = 240;
const PRIMARY_COMPARE_PAIR_COUNT = 2;

interface PaneScrollMeta {
  scrollTop: number;
  clientHeight: number;
}

interface VirtualWindow {
  start: number;
  end: number;
  paddingTop: number;
  paddingBottom: number;
}

const toPlainLines = (content: string): DiffLine[] =>
  content.split("\n").map((line) => ({
    content: line,
    type: "same",
    isPlaceholder: false
  }));

function resolveDurationMs(result: TaskResult): number | null {
  if (typeof result.execution_time_ms === "number") {
    return result.execution_time_ms;
  }
  if (typeof result.metadata.processing_time_ms === "number") {
    return result.metadata.processing_time_ms;
  }
  return null;
}

function resolveCharCount(result: TaskResult): number {
  if (typeof result.char_count === "number") {
    return result.char_count;
  }
  if (typeof result.metadata.char_count === "number") {
    return result.metadata.char_count;
  }
  return result.content.length;
}

function formatDuration(durationMs: number | null): string {
  if (durationMs === null) {
    return "N/A";
  }
  if (durationMs < 1000) {
    return `${durationMs}ms`;
  }
  return `${(durationMs / 1000).toFixed(1)}s`;
}

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

function getVirtualWindow(
  totalLines: number,
  scrollTop: number,
  clientHeight: number
): VirtualWindow {
  if (totalLines <= 0) {
    return {
      start: 0,
      end: 0,
      paddingTop: 0,
      paddingBottom: 0
    };
  }

  const safeClientHeight = clientHeight > 0 ? clientHeight : DEFAULT_VIRTUAL_VIEWPORT_HEIGHT_PX;
  const visibleLineCount = Math.max(
    Math.ceil(safeClientHeight / VIRTUAL_LINE_HEIGHT_PX),
    1
  );

  const start = Math.max(
    Math.floor(scrollTop / VIRTUAL_LINE_HEIGHT_PX) - VIRTUAL_OVERSCAN_LINES,
    0
  );
  const end = Math.min(
    start + visibleLineCount + VIRTUAL_OVERSCAN_LINES * 2,
    totalLines
  );

  return {
    start,
    end,
    paddingTop: start * VIRTUAL_LINE_HEIGHT_PX,
    paddingBottom: Math.max((totalLines - end) * VIRTUAL_LINE_HEIGHT_PX, 0)
  };
}

export default function ComparePanel() {
  const { t } = useTranslation("workflows");
  const { language } = useLanguage();
  const { can } = usePermission();
  const storeTaskId = useResultStore((state) => state.taskId);
  const results = useResultStore((state) => state.results);
  const currentTaskId = useTaskExecutionStore((state) => state.currentTaskId);
  const taskStatus = useTaskExecutionStore((state) => state.taskStatus);
  const selectedNodeType = useWorkflowStore(
    (state) => state.nodes.find((node) => node.id === state.selectedNodeId)?.type ?? null
  );
  const [viewMode, setViewMode] = useState<ViewMode>("rendered");
  const [downloadFormat, setDownloadFormat] = useState<TaskResultDownloadFormat>("markdown");
  const [isDiffModeEnabled, setIsDiffModeEnabled] = useState(false);
  const [isScrollSyncEnabled, setIsScrollSyncEnabled] = useState(true);
  const leftContentRef = useRef<HTMLPreElement | null>(null);
  const rightContentRef = useRef<HTMLPreElement | null>(null);
  const paneRefs = useRef<Record<number, HTMLPreElement | null>>({});
  const [paneScrollMeta, setPaneScrollMeta] = useState<Record<number, PaneScrollMeta>>({});

  const isCurrentTaskResults = storeTaskId === currentTaskId;
  const displayResults = can("run.view") && isCurrentTaskResults ? results : [];

  const leftText = displayResults[0]?.content ?? "";
  const rightText = displayResults[1]?.content ?? leftText;
  const { leftLines, rightLines, hasDiff } = useDiffHighlight(leftText, rightText);
  const { handleLeftScroll, handleRightScroll } = useSyncScroll({
    leftRef: leftContentRef,
    rightRef: rightContentRef,
    enabled: isScrollSyncEnabled
  });
  const isMultiPaneMode = displayResults.length > PRIMARY_COMPARE_PAIR_COUNT;
  const isEndNodeSelected = selectedNodeType ? isEndNodeType(selectedNodeType) : false;

  const updatePaneScrollMeta = useCallback(
    (index: number, element: HTMLPreElement | null) => {
      if (!element) {
        return;
      }

      const nextMeta: PaneScrollMeta = {
        scrollTop: element.scrollTop,
        clientHeight:
          element.clientHeight > 0
            ? element.clientHeight
            : DEFAULT_VIRTUAL_VIEWPORT_HEIGHT_PX
      };

      setPaneScrollMeta((prev) => {
        const current = prev[index];
        if (
          current &&
          Math.abs(current.scrollTop - nextMeta.scrollTop) < 0.5 &&
          current.clientHeight === nextMeta.clientHeight
        ) {
          return prev;
        }

        return {
          ...prev,
          [index]: nextMeta
        };
      });
    },
    []
  );

  const handlePaneScroll = useCallback(
    (index: number, syncHandler?: () => void) => {
      syncHandler?.();
      updatePaneScrollMeta(index, paneRefs.current[index]);
    },
    [updatePaneScrollMeta]
  );

  if (displayResults.length === 0) {
    if (taskStatus === "running" || taskStatus === "pending") {
      return <Empty description={t("editorText.taskInProgress")} image={Empty.PRESENTED_IMAGE_SIMPLE} />;
    }
    const emptyDescription = isEndNodeSelected ? t("editorText.finalResultHere") : t("editorText.noCompareResults");
    return (
      <div className="panel-shell compare-panel-shell">
        <div className="panel-shell-header">
          <span className="panel-shell-eyebrow">{t("editorText.review")}</span>
          <Typography.Title level={5} style={{ margin: 0 }}>
            {t("editorText.resultCompare")}
          </Typography.Title>
          <Typography.Text type="secondary">
            {isEndNodeSelected
              ? t("editorText.finalResultDescription")
              : t("editorText.compareDescription")}
          </Typography.Text>
        </div>
        <div
          className="panel-surface-card panel-empty-state"
          data-testid={isEndNodeSelected ? "compare-panel-end-node-empty-state" : "compare-panel-empty-state"}
        >
          <Empty description={emptyDescription} image={Empty.PRESENTED_IMAGE_SIMPLE} />
        </div>
      </div>
    );
  }

  const getDisplayLines = (index: number, content: string): DiffLine[] => {
    if (!isDiffModeEnabled || displayResults.length < PRIMARY_COMPARE_PAIR_COUNT) {
      return toPlainLines(content);
    }

    if (index === 0) {
      return leftLines;
    }
    if (index === 1) {
      return rightLines;
    }

    return toPlainLines(content);
  };

  const handleSingleDownload = (result: TaskResult) => {
    const url = result.formats?.[downloadFormat]
      ?? `${result.file.download_url}${result.file.download_url.includes("?") ? "&" : "?"}format=${downloadFormat}`;
    const extension = downloadFormat === "markdown" ? "md" : downloadFormat === "text" ? "txt" : "yaml";
    const filename = result.file.filename.replace(/\.[^.]+$/, `.${extension}`);
    triggerDownload(url, filename);
  };

  const handleFormatDownload = (result: TaskResult, format: TaskResultDownloadFormat) => {
    const url = result.formats?.[format]
      ?? `${result.file.download_url}${result.file.download_url.includes("?") ? "&" : "?"}format=${format}`;
    const extension = format === "markdown" ? "md" : format === "text" ? "txt" : "yaml";
    triggerDownload(url, result.file.filename.replace(/\.[^.]+$/, `.${extension}`));
  };

  const handleDownloadAll = () => {
    displayResults.forEach((result) => {
      handleSingleDownload(result);
    });
  };

  return (
    <div className="panel-shell compare-panel-shell">
      <div className="panel-shell-header">
        <span className="panel-shell-eyebrow">{t("editorText.review")}</span>
        <Typography.Title level={5} style={{ margin: 0 }}>
          {t("editorText.resultCompare")}
        </Typography.Title>
        <Typography.Text type="secondary">{t("editorText.compareDescription")}</Typography.Text>
      </div>

      <Space className="panel-surface-card" direction="vertical" size={12} style={{ width: "100%" }}>
        <div className="compare-panel-toolbar">
          <Segmented<ViewMode>
            onChange={(value) => setViewMode(value)}
            options={[
              { label: t("editorText.rendered"), value: "rendered" },
              { label: t("editorText.raw"), value: "raw" }
            ]}
            value={viewMode}
          />
          <Segmented<TaskResultDownloadFormat>
            onChange={setDownloadFormat}
            options={[
              { label: "MD", value: "markdown" },
              { label: "TXT", value: "text" },
              { label: "YAML", value: "yaml" },
            ]}
            value={downloadFormat}
          />
          <div className="compare-panel-toolbar-actions">
            <Button
              aria-pressed={isDiffModeEnabled}
              data-has-diff={hasDiff ? "true" : "false"}
              onClick={() => setIsDiffModeEnabled((enabled) => !enabled)}
              type={isDiffModeEnabled ? "primary" : "default"}
            >
              Diff
            </Button>
            <Button
              aria-pressed={isScrollSyncEnabled}
              onClick={() => setIsScrollSyncEnabled((enabled) => !enabled)}
              type={isScrollSyncEnabled ? "primary" : "default"}
            >
              {isScrollSyncEnabled ? t("editorText.disableSync") : t("editorText.syncScroll")}
            </Button>
            <Button onClick={handleDownloadAll}>{t("editorText.downloadAll")}</Button>
          </div>
        </div>
        {isDiffModeEnabled && displayResults.length >= 2 && !hasDiff ? (
          <Typography.Text type="secondary">{t("editorText.identical")}</Typography.Text>
        ) : null}
        {isMultiPaneMode ? (
          <Typography.Text type="secondary">
            {t("editorText.multiPaneNotice")}
          </Typography.Text>
        ) : null}

        <div className="compare-panel-grid">
        {displayResults.map((result, resultIndex) => {
          const isVirtualized = result.content.length > VIRTUAL_SCROLL_CHAR_THRESHOLD;
          const paneMeta = paneScrollMeta[resultIndex] ?? {
            scrollTop: 0,
            clientHeight: DEFAULT_VIRTUAL_VIEWPORT_HEIGHT_PX
          };
          const syncHandler =
            resultIndex === 0
              ? handleLeftScroll
              : resultIndex === 1
                ? handleRightScroll
                : undefined;

          return (
            <section className="compare-panel-card" key={result.result_id}>
              <Space align="center" style={{ justifyContent: "space-between", width: "100%" }}>
                <Space direction="vertical" size={2}>
                  <Typography.Text strong>{result.file.filename}</Typography.Text>
                  <Typography.Text className="compare-panel-stats" type="secondary">
                    {formatDuration(resolveDurationMs(result))} | {t("editorText.charCount", { count: formatNumber(resolveCharCount(result), language) })}
                  </Typography.Text>
                </Space>
                <Button onClick={() => handleSingleDownload(result)} size="small">
                  {t("common:download", { ns: "common" })}
                </Button>
                <Button onClick={() => handleFormatDownload(result, "text")} size="small">
                  TXT
                </Button>
              </Space>
              {viewMode === "rendered" && !isDiffModeEnabled ? (
                <div className="compare-panel-rendered">
                  <ReactMarkdown>{result.content}</ReactMarkdown>
                </div>
              ) : (
                <ComparePaneRaw
                  result={result}
                  resultIndex={resultIndex}
                  displayLines={getDisplayLines(resultIndex, result.content)}
                  isVirtualized={isVirtualized}
                  paneMeta={paneMeta}
                  isDiffModeEnabled={isDiffModeEnabled}
                  syncHandler={syncHandler}
                  paneRefs={paneRefs}
                  leftContentRef={leftContentRef}
                  rightContentRef={rightContentRef}
                  onPaneScroll={handlePaneScroll}
                  updatePaneScrollMeta={updatePaneScrollMeta}
                />
              )}
            </section>
          );
        })}
        </div>
      </Space>
    </div>
  );
}

function ComparePaneRaw({
  result,
  resultIndex,
  displayLines,
  isVirtualized,
  paneMeta,
  isDiffModeEnabled,
  syncHandler,
  paneRefs,
  leftContentRef,
  rightContentRef,
  onPaneScroll,
  updatePaneScrollMeta,
}: {
  result: TaskResult;
  resultIndex: number;
  displayLines: DiffLine[];
  isVirtualized: boolean;
  paneMeta: PaneScrollMeta;
  isDiffModeEnabled: boolean;
  syncHandler?: () => void;
  paneRefs: React.MutableRefObject<Record<number, HTMLPreElement | null>>;
  leftContentRef: React.MutableRefObject<HTMLPreElement | null>;
  rightContentRef: React.MutableRefObject<HTMLPreElement | null>;
  onPaneScroll: (index: number, syncHandler?: () => void) => void;
  updatePaneScrollMeta: (index: number, element: HTMLPreElement | null) => void;
}) {
  const virtualWindow = isVirtualized
    ? getVirtualWindow(displayLines.length, paneMeta.scrollTop, paneMeta.clientHeight)
    : { start: 0, end: displayLines.length, paddingTop: 0, paddingBottom: 0 };
  const visibleLines = displayLines.slice(virtualWindow.start, virtualWindow.end);

  return (
    <pre
      className="compare-panel-content"
      data-testid={`compare-panel-content-${resultIndex}`}
      data-diff-scope={resultIndex < PRIMARY_COMPARE_PAIR_COUNT ? "paired" : "independent"}
      data-sync-scope={resultIndex < PRIMARY_COMPARE_PAIR_COUNT ? "paired" : "independent"}
      data-virtualized={isVirtualized ? "true" : "false"}
      onScroll={() => {
        onPaneScroll(resultIndex, syncHandler);
      }}
      ref={(element) => {
        paneRefs.current[resultIndex] = element;
        if (resultIndex === 0) {
          leftContentRef.current = element;
        } else if (resultIndex === 1) {
          rightContentRef.current = element;
        }
        updatePaneScrollMeta(resultIndex, element);
      }}
    >
      {isVirtualized && virtualWindow.paddingTop > 0 ? (
        <span
          aria-hidden
          className="compare-virtual-spacer"
          style={{ height: `${virtualWindow.paddingTop}px` }}
        />
      ) : null}
      {visibleLines.map((line, lineIndex) => {
        const absoluteLineIndex = virtualWindow.start + lineIndex;
        const lineTypeClass = isDiffModeEnabled ? LINE_TYPE_CLASS[line.type] : "";
        const className = [
          "compare-line",
          lineTypeClass,
          line.isPlaceholder ? "compare-line-placeholder" : ""
        ]
          .filter(Boolean)
          .join(" ");

        return (
          <span className={className} key={`${result.result_id}_${absoluteLineIndex}`}>
            {line.content || (line.isPlaceholder ? " " : "")}
            {"\n"}
          </span>
        );
      })}
      {isVirtualized && virtualWindow.paddingBottom > 0 ? (
        <span
          aria-hidden
          className="compare-virtual-spacer"
          style={{ height: `${virtualWindow.paddingBottom}px` }}
        />
      ) : null}
    </pre>
  );
}
