import { Alert, Button, Progress, Space, Tag, Typography } from "antd";
import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import { useTaskExecutionStore } from "@/features/task-execution/store";
import { formatDateTime } from "@/i18n/format";
import { useLanguage } from "@/i18n/useLanguage";

interface EndNodeRunTabProps {
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

export default function EndNodeRunTab({ onCancelTask }: EndNodeRunTabProps) {
  const { t } = useTranslation(["workflows", "common"]);
  const { language } = useLanguage();
  const currentTaskId = useTaskExecutionStore((state) => state.currentTaskId);
  const taskStatus = useTaskExecutionStore((state) => state.taskStatus);
  const progress = useTaskExecutionStore((state) => state.progress);
  const nodeStatuses = useTaskExecutionStore((state) => state.nodeStatuses);
  const nodeErrors = useTaskExecutionStore((state) => state.nodeErrors);
  const wsWarning = useTaskExecutionStore((state) => state.wsWarning);
  const eventLogs = useTaskExecutionStore((state) => state.eventLogs);
  const logContainerRef = useRef<HTMLDivElement | null>(null);

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
    <div className="end-run-tab" data-testid="end-node-run-tab">
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Space align="center" style={{ justifyContent: "space-between", width: "100%" }}>
          <Typography.Text strong>{t("editorText.executionStatus")}</Typography.Text>
          <Tag color={STATUS_COLOR[taskStatus] ?? "default"}>{t(`common:statuses.${taskStatus}`, { defaultValue: taskStatus })}</Tag>
        </Space>

        <div className="run-panel-summary-grid">
          <div className="panel-meta-card">
            <Typography.Text type="secondary">{t("editorText.taskId")}</Typography.Text>
            <Typography.Text strong ellipsis style={{ maxWidth: 120 }}>
              {currentTaskId ?? t("editorText.notStarted")}
            </Typography.Text>
          </div>
          <div className="panel-meta-card">
            <Typography.Text type="secondary">{t("editorText.progress")}</Typography.Text>
            <Typography.Text strong>{progressPercentage}%</Typography.Text>
          </div>
        </div>

        <Progress
          percent={progressPercentage}
          size="small"
          status={taskStatus === "failed" ? "exception" : "active"}
        />

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
                    <Tag color={STATUS_COLOR[status] ?? "default"}>{t(`common:statuses.${status}`, { defaultValue: status })}</Tag>
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
            <Typography.Text strong>{t("editorText.executionLog")}</Typography.Text>
            <Typography.Text type="secondary">{t("editorText.eventCount", { count: orderedLogs.length })}</Typography.Text>
          </div>
          <div className="run-panel-log" ref={logContainerRef}>
            {orderedLogs.length === 0 ? (
              <Typography.Text type="secondary">{t("editorText.noEvents")}</Typography.Text>
            ) : (
              orderedLogs.map((entry) => (
                <div className={`run-panel-log-line level-${entry.level}`} key={entry.id}>
                  <span className="run-panel-log-time">
                    {formatDateTime(entry.timestamp, language, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                  </span>
                  <span>{entry.message}</span>
                </div>
              ))
            )}
          </div>
        </div>

        <Button
          disabled={taskStatus !== "pending" && taskStatus !== "running"}
          onClick={() => {
            void onCancelTask?.();
          }}
          block
        >
          {t("editorText.cancelTask")}
        </Button>
      </Space>
    </div>
  );
}
