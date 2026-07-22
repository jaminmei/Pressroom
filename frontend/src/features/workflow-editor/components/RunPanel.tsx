import { PauseOutlined, PlayCircleOutlined, RedoOutlined } from "@ant-design/icons";
import { Alert, Button, Progress, Space, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  beginTaskOperation,
  finishTaskOperation,
  isTaskOperationCurrent,
  useTaskExecutionStore,
  type TaskNodeVisualStatus
} from "@/features/task-execution/store";
import { useResultStore } from "@/features/result/store";
import { retryWorkflow, getTaskStatus, getTaskResults } from "@/services/taskApi";
import { mapNodeVisualStatus } from "@/utils/nodeStatus";
import { captureWorkspaceContext, isWorkspaceContextCurrent } from "@/stores/workspaceStore";
import { formatDateTime } from "@/i18n/format";
import { useLanguage } from "@/i18n/useLanguage";

interface RunPanelProps {
  onCancelTask?: () => Promise<void>;
}

const STATUS_COLOR: Record<string, string> = {
  idle: "default",
  pending: "processing",
  running: "processing",
  completed: "success",
  failed: "error",
  cancelled: "default"
};

export default function RunPanel({ onCancelTask }: RunPanelProps) {
  const { t } = useTranslation(["workflows", "common"]);
  const { language } = useLanguage();
  const currentTaskId = useTaskExecutionStore((state) => state.currentTaskId);
  const taskStatus = useTaskExecutionStore((state) => state.taskStatus);
  const progress = useTaskExecutionStore((state) => state.progress);
  const nodeStatuses = useTaskExecutionStore((state) => state.nodeStatuses);
  const nodeErrors = useTaskExecutionStore((state) => state.nodeErrors);
  const wsWarning = useTaskExecutionStore((state) => state.wsWarning);
  const eventLogs = useTaskExecutionStore((state) => state.eventLogs);
  const workflowPaused = useTaskExecutionStore((state) => state.workflowPaused);
  const sendCommandFn = useTaskExecutionStore((state) => state.sendCommandFn);
  const setTaskStatus = useTaskExecutionStore((state) => state.setTaskStatus);
  const appendEventLog = useTaskExecutionStore((state) => state.appendEventLog);
  const logContainerRef = useRef<HTMLDivElement | null>(null);
  const [workflowRetrying, setWorkflowRetrying] = useState(false);

  const handleWorkflowRetry = useCallback(async () => {
    if (!currentTaskId) return;
    const workspaceToken = captureWorkspaceContext();
    const operationId = beginTaskOperation();
    const isCurrentOperation = () =>
      isWorkspaceContextCurrent(workspaceToken) &&
      isTaskOperationCurrent(operationId) &&
      useTaskExecutionStore.getState().currentTaskId === currentTaskId;
    setWorkflowRetrying(true);
    try {
      const result = await retryWorkflow(currentTaskId);
      if (!isCurrentOperation()) return;
      appendEventLog(t("editorText.retryingNodes", { nodes: result.failed_nodes.join(", ") }));
      // Poll until terminal state
      for (let i = 0; i < 30; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        if (!isCurrentOperation()) return;
        const snapshot = await getTaskStatus(currentTaskId);
        if (!isCurrentOperation()) return;

        if (snapshot.progress) {
          useTaskExecutionStore.getState().setProgress(snapshot.progress);
        }
        const nodeStatuses = Array.isArray(snapshot.node_status)
          ? snapshot.node_status
          : snapshot.node_states
            ? Object.values(snapshot.node_states)
            : [];
        if (nodeStatuses.length > 0) {
          const statusPatch: Record<string, TaskNodeVisualStatus> = {};
          nodeStatuses.forEach((node) => {
            const mapped = mapNodeVisualStatus(node.status);
            if (mapped) {
              statusPatch[node.node_id] = mapped;
            }
          });
          useTaskExecutionStore.getState().batchUpdateNodeStatuses(statusPatch);
        }

        if (snapshot.status === "completed" || snapshot.status === "failed" || snapshot.status === "cancelled") {
          setTaskStatus(snapshot.status);
          appendEventLog(
            t("editorText.retryFinished", {
              taskId: currentTaskId,
              status: t(`common:status.${snapshot.status}`, { defaultValue: snapshot.status })
            }),
            snapshot.status === "failed" ? "error" : "info"
          );
          if (snapshot.status === "completed") {
            try {
              const results = await getTaskResults(currentTaskId);
              if (!isCurrentOperation() || results.task_id !== currentTaskId) return;
              useResultStore.getState().setTaskResults(results.task_id, results.results);
              appendEventLog(t("editorText.resultLoaded"));
            } catch {
              appendEventLog(t("editorText.resultLoadFailed"), "error");
            }
          }
          finishTaskOperation(operationId);
          break;
        }
      }
      if (isCurrentOperation()) finishTaskOperation(operationId);
    } catch {
      if (isCurrentOperation()) {
        finishTaskOperation(operationId);
        message.error(t("editorText.retryFailed"));
      }
    } finally {
      if (isWorkspaceContextCurrent(workspaceToken)) setWorkflowRetrying(false);
    }
  }, [appendEventLog, currentTaskId, setTaskStatus, t]);
  useEffect(() => {
    const container = logContainerRef.current;
    if (!container) {
      return;
    }
    container.scrollTop = container.scrollHeight;
  }, [eventLogs.length]);

  const orderedLogs = useMemo(() => eventLogs.slice(-100), [eventLogs]);
  const progressPercentage = progress?.percentage ?? 0;

  return (
    <div className="panel-shell run-panel-shell">
      <div className="panel-shell-header">
        <span className="panel-shell-eyebrow">{t("editorText.monitor")}</span>
        <Typography.Title level={5} style={{ margin: 0 }}>
          {t("editorText.executionMonitor")}
        </Typography.Title>
        <Typography.Text type="secondary">{t("editorText.monitorDescription")}</Typography.Text>
      </div>

      <Space className="panel-surface-card" direction="vertical" size={14} style={{ width: "100%" }}>
        <Space align="center" style={{ justifyContent: "space-between", width: "100%" }}>
          <Typography.Text strong>{t("editorText.executionStatus")}</Typography.Text>
          <Tag color={STATUS_COLOR[taskStatus] ?? "default"}>{t(`common:status.${taskStatus}`, { defaultValue: taskStatus })}</Tag>
        </Space>

        <div className="run-panel-summary-grid">
          <div className="panel-meta-card">
            <Typography.Text type="secondary">{t("editorText.taskId")}</Typography.Text>
            <Typography.Text strong>{currentTaskId ?? t("editorText.notStarted")}</Typography.Text>
          </div>
          <div className="panel-meta-card">
            <Typography.Text type="secondary">{t("editorText.progress")}</Typography.Text>
            <Typography.Text strong>{progressPercentage}%</Typography.Text>
          </div>
        </div>

        <Progress percent={progressPercentage} size="small" status={taskStatus === "failed" && !workflowRetrying ? "exception" : "active"} />

        {wsWarning ? <Alert message={wsWarning} type="warning" showIcon /> : null}

        <div className="panel-subsection">
          <div className="panel-subsection-header">
            <Typography.Text strong>{t("editorText.nodeTimeline")}</Typography.Text>
            <Typography.Text type="secondary">{t("editorText.nodeCount", { count: Object.keys(nodeStatuses).length })}</Typography.Text>
          </div>
          <Space direction="vertical" size={6} style={{ width: "100%" }}>
            {Object.keys(nodeStatuses).length === 0 ? (
              <Typography.Text type="secondary">{t("editorText.noExecutionRecords")}</Typography.Text>
            ) : (
              Object.entries(nodeStatuses).map(([nodeId, status]) => (
                <div className="run-panel-node-item" key={nodeId}>
                  <Space align="center" style={{ justifyContent: "space-between", width: "100%" }}>
                    <Typography.Text>{nodeId}</Typography.Text>
                    <Space align="center" size={4}>
                      <Tag color={STATUS_COLOR[status] ?? "default"}>{t(`common:status.${status}`, { defaultValue: status })}</Tag>
                    </Space>
                  </Space>
                  {nodeErrors[nodeId] ? (
                    <Typography.Text type="danger">{nodeErrors[nodeId]}</Typography.Text>
                  ) : null}
                </div>
              ))
            )}
          </Space>
        </div>

        <div className="panel-subsection">
          <div className="panel-subsection-header">
            <Typography.Text strong>{t("editorText.sseLog")}</Typography.Text>
            <Typography.Text type="secondary">{t("editorText.eventCount", { count: orderedLogs.length })}</Typography.Text>
          </div>
          <div className="run-panel-log" ref={logContainerRef}>
            {orderedLogs.length === 0 ? (
              <Typography.Text type="secondary">{t("editorText.noEvents")}</Typography.Text>
            ) : (
              orderedLogs.map((entry) => (
                <div className={`run-panel-log-line level-${entry.level}`} key={entry.id}>
                  <span className="run-panel-log-time">{formatDateTime(entry.timestamp, language, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
                  <span>{entry.message}</span>
                </div>
              ))
            )}
          </div>
        </div>

        <Space style={{ width: "100%" }} direction="vertical" size={8}>
          <Space style={{ width: "100%", justifyContent: "center" }} size={8}>
            {taskStatus === "running" && !workflowPaused && sendCommandFn ? (
              <Button
                icon={<PauseOutlined />}
                onClick={() => sendCommandFn("pause")}
              >
                {t("editorText.pause")}
              </Button>
            ) : null}
            {workflowPaused && sendCommandFn ? (
              <Button
                icon={<PlayCircleOutlined />}
                type="primary"
                onClick={() => sendCommandFn("resume")}
              >
                {t("editorText.resume")}
              </Button>
            ) : null}
            <Button
              disabled={taskStatus !== "pending" && taskStatus !== "running"}
              onClick={() => {
                void onCancelTask?.();
              }}
            >
              {t("common:cancel")}
            </Button>
            {taskStatus === "failed" && currentTaskId ? (
              <Button
                icon={<RedoOutlined />}
                loading={workflowRetrying}
                type="primary"
                onClick={() => void handleWorkflowRetry()}
              >
                {t("common:retry")}
              </Button>
            ) : null}
          </Space>
        </Space>
      </Space>
    </div>
  );
}
