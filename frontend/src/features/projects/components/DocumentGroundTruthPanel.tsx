import { FileTextOutlined } from "@ant-design/icons";
import { Alert, Button, Empty, Flex, Skeleton, Tag, Typography } from "antd";
import type { TFunction } from "i18next";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { useDocumentGroundTruth } from "@/features/projects/hooks/useDocumentGroundTruth";
import { formatDateTime } from "@/i18n/format";
import { useLanguage } from "@/i18n/useLanguage";

interface DocumentGroundTruthPanelProps {
  projectId: string;
  documentId: string;
}

function formatContent(content: string, format: string): string {
  if (!format.toLowerCase().includes("json")) return content;
  try {
    return JSON.stringify(JSON.parse(content), null, 2);
  } catch {
    return content;
  }
}

function formatSource(source: string, t: TFunction): string {
  const normalized = source.toLowerCase();
  if (normalized === "manual" || normalized === "manual_edit") {
    return t("projects:manualUpload");
  }
  if (
    normalized === "accepted_run" ||
    normalized === "inference_apply" ||
    normalized === "review_accept"
  ) {
    return t("projects:acceptedFromRun");
  }
  return source.replace(/_/g, " ");
}

export default function DocumentGroundTruthPanel({
  projectId,
  documentId,
}: DocumentGroundTruthPanelProps) {
  const { t } = useTranslation(["common", "projects"]);
  const { language } = useLanguage();
  const groundTruth = useDocumentGroundTruth(projectId, documentId);
  const selectedSummary = groundTruth.versions.find(
    (item) => item.version === groundTruth.selectedVersion,
  ) ?? null;
  const displayMetadata = groundTruth.selectedGroundTruth ?? selectedSummary;
  const displayContent = useMemo(
    () => groundTruth.selectedGroundTruth
      ? formatContent(
          groundTruth.selectedGroundTruth.content,
          groundTruth.selectedGroundTruth.format,
        )
      : "",
    [groundTruth.selectedGroundTruth],
  );

  if (groundTruth.loading) {
    return (
      <div className="right-panel-tab-content document-gt-panel" data-testid="document-gt-loading">
        <Skeleton active paragraph={{ rows: 8 }} title />
      </div>
    );
  }

  if (groundTruth.error) {
    return (
      <div className="right-panel-tab-content document-gt-panel">
        <Alert
          action={<Button onClick={groundTruth.retry} size="small">{t("common:retry")}</Button>}
          data-testid="document-gt-error"
          description={groundTruth.error}
          message={t("projects:gtLoadFailed")}
          showIcon
          type="error"
        />
      </div>
    );
  }

  if (groundTruth.versions.length === 0) {
    return (
      <div className="right-panel-tab-content document-gt-panel" data-testid="document-gt-empty">
        <Empty
          description={(
            <Flex gap={4} vertical>
              <Typography.Text strong>{t("projects:noGroundTruth")}</Typography.Text>
              <Typography.Text type="secondary">{t("projects:noGroundTruthDescription")}</Typography.Text>
            </Flex>
          )}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      </div>
    );
  }

  return (
    <div className="right-panel-tab-content document-gt-panel" data-testid="document-gt-panel">
      {displayMetadata ? (
        <section className="document-gt-summary" data-testid="document-gt-summary">
          <Flex align="center" gap={8} justify="space-between" wrap>
            <Flex align="center" gap={8} wrap>
              <FileTextOutlined className="document-gt-summary-icon" />
              <Typography.Text strong>
                {t("projects:gtVersion", { version: displayMetadata.version })}
              </Typography.Text>
              <Tag color={displayMetadata.version === groundTruth.currentVersion ? "purple" : "default"}>
                {displayMetadata.version === groundTruth.currentVersion
                  ? t("projects:currentGt")
                  : t("projects:historicalGt")}
              </Tag>
            </Flex>
            <Tag>{displayMetadata.format.toUpperCase()}</Tag>
          </Flex>

          <div className="document-gt-metadata">
            <span>{formatSource(displayMetadata.source, t)}</span>
            <span>
              {formatDateTime(displayMetadata.createdAt, language, {
                dateStyle: "medium",
                timeStyle: "short",
              })}
            </span>
          </div>
          {displayMetadata.notes ? (
            <Typography.Paragraph className="document-gt-notes" type="secondary">
              {displayMetadata.notes}
            </Typography.Paragraph>
          ) : null}
        </section>
      ) : null}

      <section className="document-gt-content-section">
        <Typography.Text strong>{t("projects:groundTruthContent")}</Typography.Text>
        {groundTruth.detailLoading ? (
          <Skeleton active data-testid="document-gt-detail-loading" paragraph={{ rows: 6 }} title={false} />
        ) : groundTruth.detailError ? (
          <Alert
            action={(
              <Button onClick={groundTruth.retrySelectedVersion} size="small">
                {t("common:retry")}
              </Button>
            )}
            data-testid="document-gt-detail-error"
            description={groundTruth.detailError}
            message={t("projects:gtVersionLoadFailed")}
            showIcon
            type="error"
          />
        ) : (
          <pre className="document-gt-content" data-testid="document-gt-content">
            {displayContent}
          </pre>
        )}
      </section>

      <section className="document-gt-history" data-testid="document-gt-history">
        <Typography.Text strong>{t("projects:gtVersionHistory")}</Typography.Text>
        <div className="document-gt-version-list">
          {groundTruth.versions.map((version) => {
            const isSelected = version.version === groundTruth.selectedVersion;
            const isCurrent = version.version === groundTruth.currentVersion;
            return (
              <button
                aria-pressed={isSelected}
                className={`document-gt-version-item${isSelected ? " is-selected" : ""}`}
                data-testid={`document-gt-version-${version.version}`}
                key={version.id}
                onClick={() => groundTruth.selectVersion(version.version)}
                type="button"
              >
                <span className="document-gt-version-marker" aria-hidden />
                <span className="document-gt-version-body">
                  <span className="document-gt-version-title">
                    <strong>{t("projects:gtVersion", { version: version.version })}</strong>
                    {isCurrent ? <Tag color="purple">{t("projects:currentGt")}</Tag> : null}
                  </span>
                  <span className="document-gt-version-meta">
                    {formatSource(version.source, t)} · {formatDateTime(version.createdAt, language, {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })}
                  </span>
                  {version.notes ? <span className="document-gt-version-notes">{version.notes}</span> : null}
                </span>
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}
