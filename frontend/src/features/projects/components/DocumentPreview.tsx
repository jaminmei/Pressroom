import { DownloadOutlined, FileTextOutlined, ReloadOutlined } from "@ant-design/icons";
import { Button, Flex, Image, Spin, Typography } from "antd";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { getDocumentPreviewUrl, getOriginalDocumentDownloadUrl } from "@/services/testSetApi";

interface DocumentPreviewProps {
  testSetId: string;
  documentId: string;
  filename: string;
  mimeType?: string;
}

function getMimeTypeFromFilename(filename: string): string | undefined {
  const ext = filename.split(".").pop()?.toLowerCase();
  switch (ext) {
    case "pdf":
      return "application/pdf";
    case "png":
      return "image/png";
    case "jpg":
    case "jpeg":
      return "image/jpeg";
    case "webp":
      return "image/webp";
    default:
      return undefined;
  }
}

function isImageMimeType(mime: string): boolean {
  return mime.startsWith("image/");
}

export default function DocumentPreview({ testSetId, documentId, filename, mimeType }: DocumentPreviewProps) {
  const { t } = useTranslation(["common", "projects"]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);

  const resolvedMimeType = mimeType ?? getMimeTypeFromFilename(filename);
  const previewUrl = getDocumentPreviewUrl(testSetId, documentId);
  const downloadUrl = getOriginalDocumentDownloadUrl(testSetId, documentId);

  const handleRetry = useCallback(() => {
    setError(false);
    setLoading(true);
    setRetryKey((k) => k + 1);
  }, []);

  if (!resolvedMimeType || (!resolvedMimeType.includes("pdf") && !isImageMimeType(resolvedMimeType))) {
    return (
      <Flex align="center" className="document-preview-fallback" data-testid="preview-fallback" justify="center" vertical>
        <FileTextOutlined className="document-preview-fallback-icon" />
        <Typography.Text strong>{filename}</Typography.Text>
        <Typography.Text type="secondary" style={{ marginBottom: 12 }}>
          {t("projects:previewFileTypeUnavailable")}
        </Typography.Text>
        <Button aria-label={t("common:download")} href={downloadUrl} icon={<DownloadOutlined />} type="primary">
          {t("common:download")}
        </Button>
      </Flex>
    );
  }

  if (error) {
    return (
      <Flex align="center" className="document-preview-error" data-testid="preview-error" justify="center" vertical>
        <FileTextOutlined className="document-preview-fallback-icon" />
        <Typography.Text strong>{filename}</Typography.Text>
        <Typography.Text type="secondary" style={{ marginBottom: 12 }}>
          {t("projects:previewDocumentFailed")}
        </Typography.Text>
        <Button icon={<ReloadOutlined />} onClick={handleRetry}>
          {t("common:retry")}
        </Button>
      </Flex>
    );
  }

  if (resolvedMimeType === "application/pdf") {
    return (
      <div className="document-preview-container" data-testid="preview-pdf">
        {loading && (
          <Flex align="center" className="document-preview-loading" justify="center">
            <Spin size="large" />
          </Flex>
        )}
        <iframe
          key={retryKey}
          className="document-preview-iframe"
          src={previewUrl}
          title={filename}
          onLoad={() => setLoading(false)}
          onError={() => { setLoading(false); setError(true); }}
        />
      </div>
    );
  }

  return (
    <div className="document-preview-container" data-testid="preview-image">
      {loading && (
        <Flex align="center" className="document-preview-loading" justify="center">
          <Spin size="large" />
        </Flex>
      )}
      <div className="document-preview-image-wrapper">
        <Image
          key={retryKey}
          alt={filename}
          src={previewUrl}
          style={{ maxWidth: "100%", height: "auto" }}
          onLoad={() => setLoading(false)}
          onError={() => { setLoading(false); setError(true); }}
        />
      </div>
    </div>
  );
}
