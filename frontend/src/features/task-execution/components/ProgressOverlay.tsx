import { Button, Progress, Space, Typography } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useTaskExecutionStore } from "@/features/task-execution/store";

interface ProgressOverlayProps {
  onCancel: () => void;
}

function formatElapsed(seconds: number): string {
  const mins = Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0");
  const secs = Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0");
  return `${mins}:${secs}`;
}

export default function ProgressOverlay({ onCancel }: ProgressOverlayProps) {
  const { t } = useTranslation("workflows");
  const taskStatus = useTaskExecutionStore((state) => state.taskStatus);
  const progress = useTaskExecutionStore((state) => state.progress);
  const currentTaskId = useTaskExecutionStore((state) => state.currentTaskId);
  const executionStartedAt = useTaskExecutionStore((state) => state.executionStartedAt);

  const [clockTick, setClockTick] = useState(() => Date.now());

  useEffect(() => {
    if (taskStatus !== "pending" && taskStatus !== "running") {
      return;
    }

    const timer = window.setInterval(() => {
      setClockTick(Date.now());
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, [taskStatus]);

  if (taskStatus !== "pending" && taskStatus !== "running") {
    return null;
  }

  const percentage = progress?.percentage ?? 0;
  const totalNodes = progress?.total_nodes ?? 0;
  const completedNodes = progress?.completed_nodes ?? 0;
  const elapsedSeconds = executionStartedAt
    ? Math.max(Math.floor((clockTick - executionStartedAt) / 1000), 0)
    : 0;

  return (
    <div className="progress-overlay" data-testid="progress-overlay">
      <Space direction="vertical" size={8} style={{ width: "100%" }}>
        <Typography.Text strong>{taskStatus === "running" ? t("editorText.taskRunning") : t("editorText.taskPreparing")}</Typography.Text>
        <Typography.Text type="secondary">{t("editorText.taskId")}: {currentTaskId ?? "-"}</Typography.Text>
        <Typography.Text>{`${completedNodes} / ${totalNodes}`}</Typography.Text>
        <Progress percent={percentage} size="small" />
        <Typography.Text type="secondary">
          {progress?.current_node ? t("editorText.currentNode", { node: progress.current_node }) : t("editorText.waitingForNode")}
        </Typography.Text>
        <Typography.Text data-testid="progress-elapsed" type="secondary">
          {t("editorText.elapsed", { elapsed: formatElapsed(elapsedSeconds) })}
        </Typography.Text>
        <Button danger onClick={onCancel} size="small">
          {t("editorText.cancelTask")}
        </Button>
      </Space>
    </div>
  );
}
