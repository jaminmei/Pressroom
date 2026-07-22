import { Alert, Button, Card, Empty, List, Select, Space, Spin, Table, Typography, Upload } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { UploadFile, UploadProps } from "antd/es/upload/interface";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { useDocAnnotationData } from "@/features/doc-annotation/hooks/useDocAnnotationData";
import { useDocAnnotationRunData } from "@/features/doc-annotation/hooks/useDocAnnotationRunData";
import { EvaluationStatusBadge } from "@/features/projects/components/EvaluationStatusBadge";
import { getOriginalDocumentDownloadUrl } from "@/services/testSetApi";
import type { TestDocument } from "@/types/testSet";
import type { EvaluationRunResultListItem } from "@/services/evaluationRunApi";

const getUploadColumns = (t: TFunction): ColumnsType<TestDocument> => [
  {
    title: t("legacy.filename"),
    dataIndex: "filename",
    key: "filename"
  },
  {
    title: t("legacy.type"),
    dataIndex: "mime_type",
    key: "mime_type"
  },
  {
    title: t("legacy.action"),
    key: "action",
    render: (_, document) => (
      <a href={getOriginalDocumentDownloadUrl(document.test_set_id, document.id)}>
        {t("legacy.downloadOriginal")}
      </a>
    )
  }
];

function getQueuedFileUid(file: File, index: number): string {
  return `${file.name}-${file.size}-${file.lastModified}-${index}`;
}

const getResultColumns = (t: TFunction): ColumnsType<EvaluationRunResultListItem> => [
  {
    title: t("legacy.filename"),
    dataIndex: "filename",
    key: "filename"
  },
  {
    title: t("legacy.status"),
    dataIndex: "status",
    key: "status",
    render: (status: string) => <EvaluationStatusBadge status={status} />
  },
  {
    title: t("legacy.action"),
    key: "action",
    render: (_, __, index) => (
      <Button data-testid={`result-detail-${index}`} size="small" type="link">
        {t("legacy.viewResultDetail")}
      </Button>
    )
  }
];

export default function DocAnnotationPage() {
  const { t } = useTranslation(["projects", "common"]);
  const uploadColumns = useMemo(() => getUploadColumns(t), [t]);
  const resultColumns = useMemo(() => getResultColumns(t), [t]);
  const {
    testSets,
    selectedTestSetId,
    selectedTestSet,
    documents,
    testSetsError,
    documentsError,
    loadingTestSets,
    loadingDocuments,
    uploadPending,
    queuedFiles,
    uploadErrors,
    uploadedCount,
    setSelectedTestSetId,
    setQueuedFiles,
    appendQueuedFiles,
    uploadDocuments
  } = useDocAnnotationData();
  const {
    workflows,
    selectedWorkflowId,
    selectedWorkflow,
    workflowsLoading,
    workflowsError,
    createRunPending,
    activeRun,
    runResults,
    runSummary,
    detailLoading,
    activeResultDetail,
    pollWarning,
    hasInProgressRun,
    setSelectedWorkflowId,
    startRun,
    retryPolling,
    openResultDetail
  } = useDocAnnotationRunData({
    selectedTestSetId,
    documentCount: documents.length
  });

  const uploadFileList = useMemo<UploadFile[]>(
    () =>
      queuedFiles.map((file, index) => ({
        uid: getQueuedFileUid(file, index),
        name: file.name,
        status: "done"
      })),
    [queuedFiles]
  );

  const uploadProps: UploadProps = {
    beforeUpload: (file) => {
      appendQueuedFiles([file as File]);
      return false;
    },
    multiple: true,
    fileList: uploadFileList,
    onRemove: (file) => {
      const nextFiles = queuedFiles.filter(
        (queuedFile, index) => getQueuedFileUid(queuedFile, index) !== file.uid
      );
      setQueuedFiles(nextFiles);
      return true;
    }
  };

  return (
    <section data-testid="doc-annotation-page" style={{ width: "100%", maxWidth: 1120 }}>
      <Space direction="vertical" size={20} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          banner
          message={t("legacy.replaced")}
          description={<span>{t("legacy.useNewPrefix")} <Link to="/projects">{t("title")}</Link> {t("legacy.useNewSuffix")}</span>}
        />
        <header>
          <Typography.Text type="secondary">{t("legacy.evaluation")}</Typography.Text>
          <Typography.Title level={2} style={{ margin: "8px 0 4px" }}>
            {t("legacy.docAnnotation")}
          </Typography.Title>
          <Typography.Paragraph style={{ marginBottom: 0 }}>
            {t("legacy.pageDescription")}
          </Typography.Paragraph>
        </header>

        <Card title={t("legacy.testSet")}>
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Select
              aria-label={t("legacy.testSetSelector")}
              disabled={hasInProgressRun}
              loading={loadingTestSets}
              options={testSets.map((testSet) => ({
                label: testSet.name,
                value: testSet.id
              }))}
              placeholder={t("legacy.selectTestSet")}
              value={selectedTestSetId ?? undefined}
              onChange={(value) => setSelectedTestSetId(value)}
            />
            {selectedTestSet ? (
              <Typography.Text type="secondary">
                {selectedTestSet.description ?? t("legacy.noDescription")} · {t("documentCount", { count: selectedTestSet.document_count })}
              </Typography.Text>
            ) : (
              <Empty description={t("legacy.selectTestSetFirst")} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
            {testSetsError ? <Typography.Text type="danger">{testSetsError}</Typography.Text> : null}
          </Space>
        </Card>

        <Card title={t("legacy.uploadDocuments")}>
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Typography.Text type="secondary">{t("legacy.uploadAfterSelection")}</Typography.Text>
            <Upload {...uploadProps} disabled={!selectedTestSetId}>
              <Button disabled={!selectedTestSetId}>{t("legacy.chooseFiles")}</Button>
            </Upload>
            <Button
              disabled={!selectedTestSetId || queuedFiles.length === 0}
              loading={uploadPending}
              onClick={() => {
                void uploadDocuments();
              }}
              type="primary"
            >
              {t("legacy.uploadDocuments")}
            </Button>
            {!selectedTestSetId ? (
              <Typography.Text type="secondary">{t("legacy.selectTestSetFirst")}</Typography.Text>
            ) : null}
            {uploadedCount > 0 ? (
              <Typography.Text type="success">{t("legacy.uploadedCount", { count: uploadedCount })}</Typography.Text>
            ) : null}
            {uploadErrors.length > 0 ? (
              <List
                bordered
                dataSource={uploadErrors}
                renderItem={(error) => (
                  <List.Item>
                    <Space direction="vertical" size={0}>
                      <Typography.Text strong>{error.filename}</Typography.Text>
                      <Typography.Text type="danger">{error.error}</Typography.Text>
                    </Space>
                  </List.Item>
                )}
                size="small"
              />
            ) : null}
            {documentsError ? <Typography.Text type="danger">{documentsError}</Typography.Text> : null}
          </Space>
        </Card>

        <Card title={t("legacy.workflow")}>
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Select
              aria-label={t("legacy.workflowSelector")}
              disabled={!selectedTestSetId || documents.length === 0 || hasInProgressRun}
              loading={workflowsLoading}
              options={workflows.map((workflow) => ({
                label: workflow.name,
                value: workflow.id
              }))}
              placeholder={t("legacy.chooseWorkflow")}
              value={selectedWorkflowId ?? undefined}
              onChange={(value) => setSelectedWorkflowId(value)}
            />
            {!selectedTestSetId ? (
              <Typography.Text type="secondary">{t("legacy.selectTestSetFirst")}</Typography.Text>
            ) : documents.length === 0 ? (
              <Typography.Text type="secondary">{t("legacy.uploadToEnableRuns")}</Typography.Text>
            ) : workflows.length > 0 ? (
              <Typography.Text type="secondary">{t("legacy.availableWorkflow", { name: workflows[0]?.name })}</Typography.Text>
            ) : (
              <Empty description={t("legacy.chooseWorkflowAfterDocuments")} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
            {selectedWorkflow ? (
              <Typography.Text type="secondary">
                {t("legacy.version", { version: selectedWorkflow.published_version ?? selectedWorkflow.latest_version ?? "-" })}
              </Typography.Text>
            ) : null}
            {workflowsError ? <Typography.Text type="danger">{workflowsError}</Typography.Text> : null}
          </Space>
        </Card>

        <Card title={t("legacy.runStatus")}>
          {!activeRun ? !selectedTestSetId ? (
            <Empty description={t("legacy.uploadToEnableBatch")} image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : loadingDocuments ? (
            <Typography.Text type="secondary">{t("legacy.loadingDocuments")}</Typography.Text>
          ) : documents.length === 0 ? (
            <Empty description={t("legacy.noDocuments") } image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Table
              columns={uploadColumns}
              dataSource={documents}
              loading={loadingDocuments}
              pagination={false}
              rowKey="id"
            />
          ) : (
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <Space align="center">
                <Typography.Text strong>{t("legacy.runStatus")}:</Typography.Text>
                <EvaluationStatusBadge status={activeRun.status} />
              </Space>
              <Typography.Text>{t("legacy.completedProgress", { completed: activeRun.completed_count, total: activeRun.total_documents })}</Typography.Text>
              <Typography.Text>{t("legacy.failedCount", { count: activeRun.failed_count })}</Typography.Text>
              {pollWarning ? (
                <Alert
                  action={<Button onClick={() => void retryPolling()} size="small" type="primary">{t("common:retry")}</Button>}
                  message={pollWarning}
                  showIcon
                  type="warning"
                />
              ) : null}
            </Space>
          )}
        </Card>

        <Card title={t("legacy.results")}>
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Button
              disabled={
                !selectedTestSetId ||
                documents.length === 0 ||
                !selectedWorkflowId ||
                hasInProgressRun
              }
              loading={createRunPending}
              onClick={() => {
                void startRun();
              }}
              type="primary"
            >
              {t("legacy.startBatchRun")}
            </Button>
            {runSummary ? (
              <Typography.Text type="secondary">
                {t("legacy.summary", { completed: runSummary.completed, total: runSummary.total, failed: runSummary.failed })}
              </Typography.Text>
            ) : (
              <Typography.Text type="secondary">{t("legacy.resultsAfterRun")}</Typography.Text>
            )}
            {runResults.length > 0 ? (
              <Table
                columns={resultColumns.map((column) =>
                  column.key === "action"
                    ? {
                        ...column,
                        render: (_: unknown, result: EvaluationRunResultListItem) => {
                          const resultId = result.id;

                          return (
                            <Button
                              size="small"
                              type="link"
                              onClick={() => {
                                void openResultDetail(resultId);
                              }}
                            >
                              {t("legacy.viewResultDetail")}
                            </Button>
                          );
                        }
                      }
                    : column
                )}
                dataSource={runResults}
                pagination={false}
                rowKey="id"
              />
            ) : null}
            {detailLoading ? (
              <Spin>
                <div style={{ minHeight: 48 }}>
                  <Typography.Text type="secondary">{t("legacy.loadingResultDetail")}</Typography.Text>
                </div>
              </Spin>
            ) : null}
            {activeResultDetail ? (
              <Card size="small" title={activeResultDetail.filename ?? t("legacy.resultDetail")}>
                <Space direction="vertical" size={8} style={{ width: "100%" }}>
                  <Typography.Text type="secondary">
                    {t("legacy.outputFormat", { format: activeResultDetail.output_format ?? "-" })}
                  </Typography.Text>
                  <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                    {activeResultDetail.output_content ?? activeResultDetail.error ?? t("legacy.noOutput")}
                  </pre>
                </Space>
              </Card>
            ) : null}
          </Space>
        </Card>
      </Space>
    </section>
  );
}
