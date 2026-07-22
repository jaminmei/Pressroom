import { Button, Empty, List, Space, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useResultStore } from "@/features/result/store";
import { type TaskNodeVisualStatus } from "@/features/task-execution/store";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { getTaskHistory, getTaskResults, getTaskStatus } from "@/services/taskApi";
import { useUIStore } from "@/stores/uiStore";
import type { TaskHistoryItem, TaskNodeStatus } from "@/types/task";
import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { computeDagFingerprint } from "@/utils/dagFingerprint";
import { captureWorkspaceContext, isWorkspaceContextCurrent } from "@/stores/workspaceStore";
import { formatDateTime } from "@/i18n/format";
import { useLanguage } from "@/i18n/useLanguage";

interface HistoryPanelProps {
  onRestoreVersion?: (version: number) => Promise<boolean>;
}

const HISTORY_PREVIEW_MAX_LENGTH = 500;
const HISTORY_STATUS_BADGE_CLASS_MAP: Partial<Record<TaskHistoryItem["status"], string>> = {
  completed: "history-panel-item-status--completed",
  failed: "history-panel-item-status--failed",
  running: "history-panel-item-status--running",
  cancelled: "history-panel-item-status--cancelled"
};

function getHistoryPreviewText(resultPreview: string | undefined, fallback: string): string {
  if (!resultPreview?.trim()) {
    return fallback;
  }

  if (resultPreview.length <= HISTORY_PREVIEW_MAX_LENGTH) {
    return resultPreview;
  }

  return `${resultPreview.slice(0, HISTORY_PREVIEW_MAX_LENGTH - 1)}…`;
}

function mapNodeVisualStatus(status: TaskNodeStatus["status"] | undefined): TaskNodeVisualStatus | null {
  if (status === "awaiting_input" || status === "awaiting_user_input") {
    return "awaiting_input";
  }
  if (
    status === "pending" ||
    status === "running" ||
    status === "completed" ||
    status === "failed" ||
    status === "cancelled" ||
    status === "skipped"
  ) {
    return status;
  }
  return null;
}

function getHistoryStatusBadgeClass(status: TaskHistoryItem["status"]): string {
  return HISTORY_STATUS_BADGE_CLASS_MAP[status] ?? "history-panel-item-status--default";
}

export default function HistoryPanel({ onRestoreVersion }: HistoryPanelProps) {
  const { t } = useTranslation(["workflows", "common"]);
  const { language } = useLanguage();
  const [historyItems, setHistoryItems] = useState<TaskHistoryItem[]>([]);
  const [hydratingTaskId, setHydratingTaskId] = useState<string | null>(null);
  const versions = useWorkflowPersistenceStore((state) => state.versions);
  const setTaskResults = useResultStore((state) => state.setTaskResults);
  const setTaskId = useTaskExecutionStore((state) => state.setTaskId);
  const setTaskStatus = useTaskExecutionStore((state) => state.setTaskStatus);
  const setProgress = useTaskExecutionStore((state) => state.setProgress);
  const batchUpdateNodeStatuses = useTaskExecutionStore((state) => state.batchUpdateNodeStatuses);
  const setRightPanelTab = useUIStore((state) => state.setRightPanelTab);
  const setLastRunMeta = useTaskExecutionStore((state) => state.setLastRunMeta);

  // Re-fetch on mount
  useEffect(() => {
    let mounted = true;
    const workspaceToken = captureWorkspaceContext();
    void getTaskHistory({ page: 1, limit: 20 }).then((response) => {
      if (!mounted || !isWorkspaceContextCurrent(workspaceToken)) return;
      setHistoryItems(response.items);
    });
    return () => { mounted = false; };
  }, []);

  const hydrateTaskContext = useCallback(
    async (taskId: string, targetTab: "run" | "compare") => {
      const workspaceToken = captureWorkspaceContext();
      setHydratingTaskId(taskId);
      try {
        const [statusResponse, resultsResponse] = await Promise.all([
          getTaskStatus(taskId),
          getTaskResults(taskId)
        ]);
        if (
          !isWorkspaceContextCurrent(workspaceToken) ||
          statusResponse.task_id !== taskId ||
          resultsResponse.task_id !== taskId
        ) return;
        const nodeStates = Array.isArray(statusResponse.node_status)
          ? statusResponse.node_status
          : statusResponse.node_states
            ? Object.values(statusResponse.node_states)
            : [];

        const statusPatch: Record<string, TaskNodeVisualStatus> = {};
        nodeStates.forEach((node) => {
          const mappedStatus = mapNodeVisualStatus(node.status);
          if (!mappedStatus) {
            return;
          }
          statusPatch[node.node_id] = mappedStatus;
        });

        useTaskExecutionStore.setState((state) => ({
          ...state,
          nodeStatuses: {},
          nodeProgress: {},
          nodeErrors: {}
        }));
        setTaskId(statusResponse.task_id);
        setTaskStatus(statusResponse.status);
        setProgress(statusResponse.progress ?? null);
        batchUpdateNodeStatuses(statusPatch);

        // Restore workflow definition into editor if available
        const wf = statusResponse.workflow;
        if (wf && wf.nodes && wf.connections) {
          const { nodeRegistry } = useWorkflowStore.getState();
          const restoredNodes = wf.nodes.map((n) => {
            const parts = n.type.split("/");
            const metadata = nodeRegistry.nodes.find((rn) => rn.node_type === n.type);
            const defaultLabel = (parts[parts.length - 1] ?? n.type).toUpperCase();
            const pos = n.position as { x?: number; y?: number } | undefined;
            return {
              id: n.id,
              type: n.type,
              data: {
                label: metadata?.display_name ?? defaultLabel,
                config: n.config ?? {},
                configSchema: metadata?.config_schema ?? { type: "object", properties: {} },
                inputTypes: metadata?.input_types,
                outputTypes: metadata?.output_types,
                maxInputs: metadata?.max_inputs,
                inputPorts: metadata?.input_ports,
              },
              position: pos && typeof pos.x === "number" && typeof pos.y === "number"
                ? { x: pos.x, y: pos.y }
                : undefined,
            };
          });
          const restoredEdges = wf.connections.map((c) => ({
            id: `e-${c.source}-${c.target}`,
            source: c.source,
            target: c.target,
            sourceHandle: c.source_port ? `output-${c.source_port}` : undefined,
            targetHandle: c.target_port ? `input-${c.target_port}` : undefined,
          }));
          const restoredConfigs: Record<string, Record<string, unknown>> = {};
          wf.nodes.forEach((n) => {
            restoredConfigs[n.id] = n.config ?? {};
          });
          useWorkflowStore.setState((s) => ({
            canvasResetKey: s.canvasResetKey + 1,
            nodes: restoredNodes,
            edges: restoredEdges,
            nodeConfigs: restoredConfigs,
            uploadedFiles: {},
          }));
        }

        // Restore dag fingerprint and input files for rerun/compare gating
        const currentState = useWorkflowStore.getState();
        const dagFp = currentState.nodes.length > 0
          ? computeDagFingerprint(
              currentState.nodes.map((n) => ({ id: n.id, type: n.type })),
              currentState.edges.map((e) => ({ source: e.source, target: e.target, sourceHandle: e.sourceHandle, targetHandle: e.targetHandle })),
              currentState.nodeConfigs
            )
          : null;
        setLastRunMeta(dagFp, statusResponse.input_files ?? null);

        setTaskResults(resultsResponse.task_id, resultsResponse.results);
        setRightPanelTab(targetTab);
        message.success(t("editorText.historyLoaded", {
          taskId,
          panel: targetTab === "run" ? t("run") : t("compare")
        }));
      } catch {
        if (isWorkspaceContextCurrent(workspaceToken)) {
          message.error(t("editorText.historyLoadFailed"));
        }
      } finally {
        if (isWorkspaceContextCurrent(workspaceToken)) {
          setHydratingTaskId((current) => (current === taskId ? null : current));
        }
      }
    },
    [batchUpdateNodeStatuses, setLastRunMeta, setProgress, setRightPanelTab, setTaskId, setTaskResults, setTaskStatus, t]
  );

  return (
    <div className="panel-shell history-panel-shell">
      <div className="panel-shell-header">
        <span className="panel-shell-eyebrow">{t("editorText.timeline")}</span>
        <Typography.Title level={5} style={{ margin: 0 }}>
          {t("editorText.runHistory")}
        </Typography.Title>
        <Typography.Text type="secondary">{t("editorText.historyDescription")}</Typography.Text>
      </div>

      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <section className="panel-surface-card">
          <div className="panel-subsection-header">
            <Typography.Text strong>{t("editorText.recentRuns")}</Typography.Text>
            <Typography.Text type="secondary">{t("editorText.taskCount", { count: historyItems.length })}</Typography.Text>
          </div>
          {historyItems.length === 0 ? (
            <Empty description={t("editorText.noRunHistory")} image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <List
              dataSource={historyItems}
              renderItem={(item) => {
                const previewText = getHistoryPreviewText(item.result_preview, t("editorText.noResultPreview"));

                return (
                  <List.Item>
                    <Space direction="vertical" size={8} style={{ minWidth: 0, width: "100%" }}>
                      <div className="history-panel-item-header">
                        <Space className="history-panel-item-text" direction="vertical" size={2}>
                          <Typography.Text
                            className="history-panel-item-title"
                            ellipsis={{ tooltip: item.run_name ?? item.workflow_name ?? item.task_id }}
                          >
                            {item.run_name ?? item.workflow_name ?? item.task_id}
                          </Typography.Text>
                          <Typography.Text className="history-panel-item-time" type="secondary">
                            {!item.run_name ? "" : `${item.task_id.slice(5, 13)} · `}
                            {formatDateTime(item.started_at, language)}
                            {item.completed_at ? ` → ${formatDateTime(item.completed_at, language)}` : ""}
                          </Typography.Text>
                        </Space>
                        <Tag
                          className={`history-panel-item-status ${getHistoryStatusBadgeClass(item.status)}`}
                          data-testid={`history-status-badge-${item.status}`}
                        >
                          {t(`common:status.${item.status}`, { defaultValue: item.status })}
                        </Tag>
                      </div>
                      <Typography.Paragraph style={{ margin: 0, whiteSpace: "pre-wrap" }} type="secondary">
                        {previewText}
                      </Typography.Paragraph>
                      <Space size={4} wrap>
                        <Button
                          key={`hydrate_run_${item.task_id}`}
                          loading={hydratingTaskId === item.task_id}
                          onClick={() => {
                            void hydrateTaskContext(item.task_id, "run");
                          }}
                          size="small"
                          type="text"
                        >
                          {t("editorText.openRun")}
                        </Button>
                        <Button
                          key={`hydrate_compare_${item.task_id}`}
                          loading={hydratingTaskId === item.task_id}
                          onClick={() => {
                            void hydrateTaskContext(item.task_id, "compare");
                          }}
                          size="small"
                          type="text"
                        >
                          {t("editorText.review")}
                        </Button>
                      </Space>
                    </Space>
                  </List.Item>
                );
              }}
              size="small"
            />
          )}
        </section>

        <section className="panel-surface-card">
          <div className="panel-subsection-header">
            <Typography.Text strong>{t("editorText.versionHistory")}</Typography.Text>
            <Typography.Text type="secondary">{t("editorText.versionCount", { count: versions.length })}</Typography.Text>
          </div>
          {versions.length === 0 ? (
            <Empty description={t("editorText.noPublishedVersions")} image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <List
              dataSource={versions}
              renderItem={(item) => (
                <List.Item>
                  <div className="history-panel-item-header">
                    <Space className="history-panel-item-text" direction="vertical" size={2}>
                      <Typography.Text className="history-panel-item-title">
                        {item.status.toUpperCase()} v{item.version}
                      </Typography.Text>
                      <Typography.Text className="history-panel-item-time" type="secondary">
                        {formatDateTime(item.created_at, language)}
                      </Typography.Text>
                    </Space>
                    <Button
                      className="history-panel-item-cta"
                      key={`restore_${item.version}`}
                      onClick={() => {
                        void onRestoreVersion?.(item.version);
                      }}
                      size="small"
                    >
                      {t("editorText.restoreVersion", { version: item.version })}
                    </Button>
                  </div>
                </List.Item>
              )}
              size="small"
            />
          )}
        </section>
      </Space>
    </div>
  );
}
