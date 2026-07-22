import { Card, Empty, Segmented, Space, Spin, Statistic, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import DownloadButton from "@/features/result/components/DownloadButton";
import MarkdownViewer from "@/features/result/components/MarkdownViewer";
import { useResultStore } from "@/features/result/store";
import { getTaskResults } from "@/services/taskApi";
import { captureWorkspaceContext, isWorkspaceContextCurrent } from "@/stores/workspaceStore";

export default function ResultPage() {
  const { t } = useTranslation(["common", "workflows"]);
  const { taskId: routeTaskId } = useParams<{ taskId: string }>();
  const [isLoading, setIsLoading] = useState(false);
  const taskId = routeTaskId ?? null;
  const storeTaskId = useResultStore((state) => state.taskId);
  const results = useResultStore((state) => state.results);
  const displayMode = useResultStore((state) => state.displayMode);
  const setDisplayMode = useResultStore((state) => state.setDisplayMode);
  const setTaskResults = useResultStore((state) => state.setTaskResults);

  useEffect(() => {
    if (!taskId || useResultStore.getState().taskId === taskId) {
      return;
    }

    let isUnmounted = false;
    const workspaceToken = captureWorkspaceContext();
    setIsLoading(true);

    void getTaskResults(taskId)
      .then((response) => {
        if (
          isUnmounted ||
          !isWorkspaceContextCurrent(workspaceToken) ||
          response.task_id !== taskId
        ) {
          return;
        }
        setTaskResults(response.task_id, response.results);
      })
      .catch(() => {
        if (!isUnmounted && isWorkspaceContextCurrent(workspaceToken)) {
          message.error(t("workflows:resultText.loadFailed"));
        }
      })
      .finally(() => {
        if (!isUnmounted && isWorkspaceContextCurrent(workspaceToken)) {
          setIsLoading(false);
        }
      });

    return () => {
      isUnmounted = true;
    };
  }, [setTaskResults, t, taskId]);

  if (isLoading) {
    return <Spin tip={t("workflows:resultText.loading")} />;
  }

  const activeResult = storeTaskId === taskId ? results[0] : null;

  if (!activeResult) {
    return <Empty description={t("workflows:resultText.unavailable")} />;
  }

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Typography.Title level={2} style={{ margin: 0 }}>
        {t("workflows:resultText.title")}
      </Typography.Title>

      <Typography.Text type="secondary">{t("workflows:resultText.taskId", { id: taskId ?? t("common:notAvailable") })}</Typography.Text>

      <Space size={12} wrap>
        <Segmented
          onChange={(value) => setDisplayMode(value as "rendered" | "raw")}
          options={[
            { label: t("workflows:resultText.rendered"), value: "rendered" },
            { label: t("workflows:resultText.raw"), value: "raw" }
          ]}
          value={displayMode}
        />
        <DownloadButton content={activeResult.content} filename={activeResult.file.filename} />
      </Space>

      <Space size={16} wrap>
        <Card>
          <Statistic title={t("workflows:resultText.pages")} value={activeResult.metadata.page_count} />
        </Card>
        <Card>
          <Statistic title={t("workflows:resultText.chars")} value={activeResult.metadata.char_count} />
        </Card>
        <Card>
          <Statistic title={t("workflows:resultText.words")} value={activeResult.metadata.word_count} />
        </Card>
        <Card>
          <Statistic
            suffix="ms"
            title={t("workflows:resultText.processingTime")}
            value={activeResult.metadata.processing_time_ms}
          />
        </Card>
      </Space>

      <Card>
        {displayMode === "rendered" ? (
          <MarkdownViewer content={activeResult.content} />
        ) : (
          <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {activeResult.content}
          </pre>
        )}
      </Card>
    </Space>
  );
}
