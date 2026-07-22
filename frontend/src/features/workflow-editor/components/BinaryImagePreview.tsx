import { Image, Typography } from "antd";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { getNodeImageUrl } from "@/services/taskApi";
import type { NodeOutput } from "@/services/taskApi";

interface BinaryImagePreviewProps {
  binary: NodeOutput["binary"];
  taskId: string;
  nodeId: string;
  labels?: string[];
}

const imageStyle = { maxWidth: "100%", height: "auto", borderRadius: 8 } as const;
const gridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
  gap: 12
} as const;
const stackStyle = { display: "grid", gap: 12 } as const;
const cardStyle = {
  border: "1px solid rgba(5, 5, 5, 0.06)",
  borderRadius: 8,
  padding: 12,
  background: "#ffffff"
} as const;
const placeholderStyle = {
  ...cardStyle,
  minHeight: 140,
  display: "flex",
  alignItems: "center",
  justifyContent: "center"
} as const;

function formatBytes(sizeBytes: number): string {
  if (sizeBytes >= 1024 * 1024) {
    return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (sizeBytes >= 1024) {
    return `${(sizeBytes / 1024).toFixed(1)} KB`;
  }
  return `${sizeBytes} B`;
}

function getImageLabel(index: number, t: TFunction, labels?: string[]): string {
  const regionLabel = t("workflows:editorText.region", { count: index + 1 });
  const typeLabel = labels?.[index];
  return typeLabel ? `${regionLabel} · ${typeLabel}` : regionLabel;
}

export default function BinaryImagePreview({
  binary,
  taskId,
  nodeId,
  labels
}: BinaryImagePreviewProps) {
  const { t } = useTranslation("workflows");
  const imageEntries = binary.filter((entry) => entry.mime_type.startsWith("image/"));
  const isGridLayout = imageEntries.length > 1;

  return (
    <div className="binary-image-preview" data-testid="binary-image-preview" style={stackStyle}>
      {isGridLayout ? (
        <Typography.Text type="secondary">{t("editorText.imageCount", { count: imageEntries.length })}</Typography.Text>
      ) : null}

      <div
        className="binary-image-preview-content"
        data-testid={isGridLayout ? "binary-image-preview-grid" : "binary-image-preview-stack"}
        style={isGridLayout ? gridStyle : stackStyle}
      >
        {binary.map((entry, index) => {
          const hasData = Boolean(entry.data);
          const hasRef = Boolean(entry.ref);
          const hasSource = hasData || hasRef;

          if (!hasSource) {
            return (
              <div
                className="binary-image-preview-placeholder"
                data-testid={`binary-preview-placeholder-${index}`}
                key={`placeholder-${index}`}
                style={placeholderStyle}
              >
                <Typography.Text type="secondary">{t("editorText.imageUnavailable")}</Typography.Text>
              </div>
            );
          }

          if (!entry.mime_type.startsWith("image/")) {
            return (
              <div
                className="binary-image-preview-file"
                data-testid={`binary-preview-file-${index}`}
                key={`file-${index}`}
                style={cardStyle}
              >
                <Typography.Text strong style={{ display: "block", marginBottom: 4 }}>
                  {entry.ref || t("editorText.inlineData")}
                </Typography.Text>
                <Typography.Text type="secondary" style={{ display: "block" }}>
                  {entry.mime_type}
                </Typography.Text>
                <Typography.Text type="secondary" style={{ display: "block" }}>
                  {formatBytes(entry.size_bytes)}
                </Typography.Text>
              </div>
            );
          }

          const src = hasData
            ? `data:${entry.mime_type};base64,${entry.data}`
      : getNodeImageUrl(taskId, nodeId, { index: String(index) });

          return (
            <div
              className="binary-image-preview-item"
              data-testid={`binary-preview-image-${index}`}
              key={`image-${index}`}
              style={stackStyle}
            >
              <Typography.Text type="secondary">{getImageLabel(index, t, labels)}</Typography.Text>
              <Image alt={getImageLabel(index, t, labels)} src={src} style={imageStyle} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
