import {
  FileImageOutlined,
  FilePdfOutlined,
  FileUnknownOutlined,
} from "@ant-design/icons";
import { Popover, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getDocumentThumbnailUrl } from "@/services/testSetApi";

interface DocumentThumbnailProps {
  testSetId: string;
  documentId: string;
  filename: string;
  mimeType?: string;
  onPreview?: () => void;
}

const HOVER_PREVIEW_DELAY_MS = 300;

function fileKind(filename: string, mimeType?: string): "image" | "pdf" | "unknown" {
  const normalizedMime = mimeType?.toLowerCase() ?? "";
  const extension = filename.split(".").pop()?.toLowerCase();
  if (normalizedMime === "application/pdf" || extension === "pdf") return "pdf";
  if (
    normalizedMime.startsWith("image/")
    || extension === "jpg"
    || extension === "jpeg"
    || extension === "png"
    || extension === "webp"
  ) {
    return "image";
  }
  return "unknown";
}

function hoverPreviewSupported(): boolean {
  return window.matchMedia?.("(hover: hover) and (pointer: fine)").matches ?? false;
}

export default function DocumentThumbnail({
  testSetId,
  documentId,
  filename,
  mimeType,
  onPreview,
}: DocumentThumbnailProps) {
  const { t } = useTranslation("projects");
  const kind = fileKind(filename, mimeType);
  const supported = kind !== "unknown";
  const [listLoading, setListLoading] = useState(supported);
  const [listError, setListError] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(true);
  const [previewError, setPreviewError] = useState(false);
  const [canHover, setCanHover] = useState(hoverPreviewSupported);
  const openTimerRef = useRef<number | null>(null);

  const clearOpenTimer = useCallback(() => {
    if (openTimerRef.current !== null) {
      window.clearTimeout(openTimerRef.current);
      openTimerRef.current = null;
    }
  }, []);

  const closePreview = useCallback(() => {
    clearOpenTimer();
    setPreviewOpen(false);
  }, [clearOpenTimer]);

  const schedulePreview = useCallback(() => {
    if (!onPreview || !canHover || !supported) return;
    clearOpenTimer();
    openTimerRef.current = window.setTimeout(() => {
      setPreviewLoading(true);
      setPreviewError(false);
      setPreviewOpen(true);
      openTimerRef.current = null;
    }, HOVER_PREVIEW_DELAY_MS);
  }, [canHover, clearOpenTimer, onPreview, supported]);

  useEffect(() => {
    const mediaQuery = window.matchMedia?.("(hover: hover) and (pointer: fine)");
    if (!mediaQuery) return undefined;
    const handleChange = (event: MediaQueryListEvent) => {
      setCanHover(event.matches);
      if (!event.matches) closePreview();
    };
    mediaQuery.addEventListener?.("change", handleChange);
    return () => {
      clearOpenTimer();
      mediaQuery.removeEventListener?.("change", handleChange);
    };
  }, [clearOpenTimer, closePreview]);

  const listUrl = supported
    ? getDocumentThumbnailUrl(testSetId, documentId, 96)
    : undefined;
  const previewUrl = onPreview && previewOpen
    ? getDocumentThumbnailUrl(testSetId, documentId, 640)
    : undefined;
  const FallbackIcon = kind === "pdf"
    ? FilePdfOutlined
    : kind === "image"
      ? FileImageOutlined
      : FileUnknownOutlined;

  const frame = (
    <span
      className={`document-thumbnail-frame${listLoading ? " document-thumbnail-frame--loading" : ""}${listError ? " document-thumbnail-frame--error" : ""}`}
    >
      {listLoading && !listError ? (
        <span aria-hidden="true" className="document-thumbnail-skeleton" />
      ) : null}
      {listUrl && !listError ? (
        <img
          alt=""
          className="document-thumbnail-image"
          decoding="async"
          loading="lazy"
          onError={() => {
            setListLoading(false);
            setListError(true);
          }}
          onLoad={() => setListLoading(false)}
          src={listUrl}
        />
      ) : (
        <FallbackIcon aria-hidden="true" className="document-thumbnail-fallback-icon" />
      )}
      {kind === "pdf" ? <span className="document-thumbnail-pdf-badge">PDF</span> : null}
    </span>
  );

  if (!onPreview) {
    return (
      <span
        className="document-thumbnail-static"
        data-testid={`document-thumbnail-${documentId}`}
        title={listError ? t("previewUnavailable") : undefined}
      >
        {frame}
      </span>
    );
  }

  const button = (
    <button
      aria-expanded={canHover && supported ? previewOpen : undefined}
      aria-label={t("previewFile", { filename })}
      className="document-thumbnail-button"
      data-testid={`document-thumbnail-${documentId}`}
      onBlur={closePreview}
      onClick={(event) => {
        event.stopPropagation();
        closePreview();
        onPreview();
      }}
      onFocus={schedulePreview}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          closePreview();
        }
      }}
      onMouseEnter={schedulePreview}
      onMouseLeave={closePreview}
      title={listError ? t("previewUnavailable") : undefined}
      type="button"
    >
      {frame}
    </button>
  );

  if (!canHover || !supported) return button;

  return (
    <Popover
      arrow
      autoAdjustOverflow
      content={previewOpen ? (
        <div className="document-thumbnail-popover-content" data-testid="document-thumbnail-popover">
          {previewLoading && !previewError ? (
            <span aria-hidden="true" className="document-thumbnail-popover-skeleton" />
          ) : null}
          {previewUrl && !previewError ? (
            <img
              alt={t("previewImageAlt", { filename })}
              className="document-thumbnail-popover-image"
              onError={() => {
                setPreviewLoading(false);
                setPreviewError(true);
              }}
              onLoad={() => setPreviewLoading(false)}
              src={previewUrl}
            />
          ) : null}
          {previewError ? (
            <div className="document-thumbnail-popover-error">
              <FallbackIcon aria-hidden="true" />
              <Typography.Text type="secondary">{t("previewUnavailable")}</Typography.Text>
            </div>
          ) : null}
        </div>
      ) : null}
      destroyOnHidden
      open={previewOpen}
      overlayClassName="document-thumbnail-popover"
      placement="rightTop"
      trigger={[]}
    >
      {button}
    </Popover>
  );
}
