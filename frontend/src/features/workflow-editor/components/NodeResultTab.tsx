import { ReloadOutlined } from "@ant-design/icons";
import { Button, Empty, Image, Spin, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import BinaryImagePreview from "./BinaryImagePreview";
import LayoutDetectionResultView from "@/features/workflow-editor/components/LayoutDetectionResultView";
import { useTaskExecutionStore, type TaskNodeVisualStatus } from "@/features/task-execution/store";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { getNodeResult, getNodeImageUrl, type NodeOutput, type NodeResultResponse } from "@/services/taskApi";
import { buildWorkspaceScopedUrl } from "@/services/workspaceTransport";
import type { Block } from "@/types/block";
import { usePermission } from "@/hooks/usePermission";
import { captureWorkspaceContext, isWorkspaceContextCurrent } from "@/stores/workspaceStore";
import { formatNumber } from "@/i18n/format";
import { useLanguage } from "@/i18n/useLanguage";

interface NodeResultTabProps {
  nodeId: string;
}

type ResultViewMode = "rendered" | "raw";

function EmptyResultView({ status }: { status: TaskNodeVisualStatus | "idle" }) {
  const { t } = useTranslation(["workflows", "common"]);

  return (
    <div className="node-result-empty" data-testid="node-result-empty">
      <Typography.Text type="secondary">
        {t(`common:status.${status}`, { defaultValue: t("editorText.noResultYet") })}
      </Typography.Text>
    </div>
  );
}

function TextResultView({ content, format, hideToggle }: { content: string; format?: string; hideToggle?: boolean }) {
  const { t } = useTranslation("workflows");
  const { language } = useLanguage();
  const [viewMode, setViewMode] = useState<ResultViewMode>("rendered");
  const charCount = content.length;
  const wordCount = content.split(/\s+/).filter(Boolean).length;

  return (
    <div className="node-result-text" data-testid="node-result-text">
      {!hideToggle && (
        <div className="node-result-text-toolbar">
          <div className="node-result-format-switcher">
            <button
              className={viewMode === "rendered" ? "active" : ""}
              onClick={() => setViewMode("rendered")}
              type="button"
            >
              {t("editorText.rendered")}
            </button>
            <button
              className={viewMode === "raw" ? "active" : ""}
              onClick={() => setViewMode("raw")}
              type="button"
            >
              {t("editorText.raw")}
            </button>
          </div>
          {format ? <Tag>{format}</Tag> : null}
        </div>
      )}

      <div className="node-result-text-content">
        {viewMode === "rendered" || hideToggle ? (
          <div
            className="node-result-rendered"
            dangerouslySetInnerHTML={{ __html: simpleMarkdownToHtml(content) }}
          />
        ) : (
          <pre className="node-result-raw">{content}</pre>
        )}
      </div>

      <div className="node-result-meta">
        <span>{t("editorText.charCount", { count: formatNumber(charCount, language) })}</span>
        <span>{t("editorText.wordCount", { count: formatNumber(wordCount, language) })}</span>
      </div>
    </div>
  );
}

function ImageResultView({
  imageUrl,
  outputImage,
  operations
}: {
  imageUrl: string;
  outputImage?: { width?: number; height?: number } | null;
  operations?: string[];
}) {
  const { t } = useTranslation("workflows");
  return (
    <div className="node-result-image" data-testid="node-result-image">
      <div className="node-result-image-container">
        <Image
          alt={t("editorText.processedOutput")}
          src={imageUrl}
          style={{ maxWidth: "100%", height: "auto", borderRadius: 8 }}
        />
      </div>
      <div className="node-result-meta">
        {outputImage?.width && outputImage?.height ? (
          <span>{outputImage.width} x {outputImage.height}</span>
        ) : null}
        {operations && operations.length > 0 ? (
          <span>{operations.join(", ")}</span>
        ) : null}
      </div>
    </div>
  );
}

function ErrorResultView({ error }: { error: string | Record<string, unknown> }) {
  const { t } = useTranslation("workflows");
  const errorText = typeof error === "string" ? error : JSON.stringify(error, null, 2);

  return (
    <div className="node-result-error" data-testid="node-result-error">
      <Typography.Text type="danger">{t("editorText.error")}</Typography.Text>
      <pre className="node-result-error-content">{errorText}</pre>
    </div>
  );
}

function TraceInputMetadataView({ metadata }: { metadata: Record<string, unknown> | null }) {
  const { t } = useTranslation("workflows");
  const file = metadata?.file;
  const entries = file && typeof file === "object"
    ? Object.entries(file as Record<string, unknown>)
    : Object.entries(metadata ?? {});

  return (
    <div className="node-result-section" data-testid="trace-input-metadata">
      <Typography.Text strong>{t("editorText.inputMetadata")}</Typography.Text>
      <Typography.Text type="secondary">
        {t("editorText.traceFilesNotRendered")}
      </Typography.Text>
      {entries.length === 0 ? (
        <Empty description={t("editorText.noInputMetadata")} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div className="trace-input-metadata-list">
          {entries.map(([key, value]) => (
            <div className="trace-input-metadata-row" key={key}>
              <span>{key}</span>
              <code>{String(value ?? "—")}</code>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MetadataView({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata).filter(([, v]) => v != null);
  if (entries.length === 0) {
    return null;
  }

  return (
    <div className="node-result-meta" data-testid="node-result-metadata">
      {entries.map(([key, value]) => (
        <span key={key}>
          {key}: {typeof value === "number" && key.includes("time") ? `${(value as number / 1000).toFixed(1)}s` : String(value)}
        </span>
      ))}
    </div>
  );
}

/**
 * Render the new NodeOutput format.
 * - Image input: shows image preview via /nodes/{id}/image endpoint, with Raw toggle.
 * - Engine/other: shows raw JSON output only (no rendered/raw toggle).
 */
function summarizeBinaryForJson(binary: NodeOutput["binary"]): NodeOutput["binary"] {
  return binary.map((entry) => {
    if (entry.data) {
      const { data, ...rest } = entry;
      return { ...rest, data: `<base64, ${data.length} chars>` };
    }
    return entry;
  });
}

function NewOutputView({
  output,
  taskId,
  nodeId,
  nodeType
}: {
  output: NodeOutput;
  taskId: string;
  nodeId: string;
  nodeType?: string;
}) {
  const { t } = useTranslation("workflows");
  const [viewMode, setViewMode] = useState<ResultViewMode>("rendered");
  const isImageInput = nodeType === "input/image";
  const isPdfInput = nodeType === "input/pdf";
  const isImageProducer = nodeType === "processor/document_to_image";
  const hasVisualPreview = isImageInput || isPdfInput || isImageProducer;
  const structured = output.structured as { kind?: string; elements?: Array<{ type?: string }> } | null;
  const hasBinaryPreview = output.binary.length > 0;
  const isLayoutDetection = structured?.kind === "layout_regions" || (Array.isArray(structured?.elements) && nodeType === "layout_detection");
  const labels = isLayoutDetection && Array.isArray(structured?.elements)
    ? structured.elements.map((element) => element.type ?? "")
    : undefined;

  // Raw mode for visual nodes: show full JSON dump
  if (viewMode === "raw" && hasVisualPreview) {
    return (
      <div className="node-result-section">
        <div className="node-result-text-toolbar">
          <div className="node-result-format-switcher">
            <button
              className=""
              onClick={() => setViewMode("rendered")}
              type="button"
            >
              {t("editorText.image")}
            </button>
            <button className="active" type="button">{t("editorText.raw")}</button>
          </div>
        </div>
        <pre className="node-result-raw">{JSON.stringify(output, null, 2)}</pre>
      </div>
    );
  }

  // Rendered mode for image-producing nodes: show image via the dedicated image endpoint
  if (isImageInput || isImageProducer) {
    const imageUrl = getNodeImageUrl(taskId, nodeId);
    return (
      <div className="node-result-section">
        <div className="node-result-text-toolbar">
          <div className="node-result-format-switcher">
            <button className="active" type="button">{t("editorText.image")}</button>
            <button className="" onClick={() => setViewMode("raw")} type="button">{t("editorText.raw")}</button>
          </div>
        </div>
        <ImageResultView imageUrl={imageUrl} />
        {output.metadata && Object.keys(output.metadata).length > 0 ? (
          <MetadataView metadata={output.metadata} />
        ) : null}
      </div>
    );
  }

  // Rendered mode for PDF input: show PDF preview via the image endpoint
  if (isPdfInput) {
    const pdfUrl = getNodeImageUrl(taskId, nodeId);
    return (
      <div className="node-result-section">
        <div className="node-result-text-toolbar">
          <div className="node-result-format-switcher">
            <button className="active" type="button">{t("editorText.preview")}</button>
            <button className="" onClick={() => setViewMode("raw")} type="button">{t("editorText.raw")}</button>
          </div>
        </div>
        <iframe
          src={pdfUrl}
          style={{ width: "100%", height: "500px", border: "none", borderRadius: 8 }}
          title={t("editorText.pdfPreview")}
        />
        {output.metadata && Object.keys(output.metadata).length > 0 ? (
          <MetadataView metadata={output.metadata} />
        ) : null}
      </div>
    );
  }

  // Engine/output nodes: raw JSON only, no toggle
  return (
    <div className="node-result-section">
      <pre className="node-result-raw">{
        JSON.stringify(
          output.structured ?? { ...output, binary: summarizeBinaryForJson(output.binary) },
          null,
          2
        )
      }</pre>
      {output.metadata && Object.keys(output.metadata).length > 0 ? (
        <MetadataView metadata={output.metadata} />
      ) : null}
      {hasBinaryPreview ? (
        <BinaryImagePreview binary={output.binary} labels={labels} nodeId={nodeId} taskId={taskId} />
      ) : null}
    </div>
  );
}

/**
 * Minimal markdown→HTML for displaying engine output in the Result Tab.
 *
 * SAFETY: HTML entity escaping (`&`, `<`, `>`) MUST run first, before any
 * regex that produces HTML tags. The subsequent regexes only match markdown
 * syntax characters (`#`, `*`, `` ` ``) which are NOT affected by the entity
 * escaping, so captured content is already entity-escaped and safe to embed
 * inside the generated tags.
 *
 * This is used with `dangerouslySetInnerHTML` — do NOT reorder the steps or
 * add patterns that could introduce unescaped user content into tag attributes.
 */
function simpleMarkdownToHtml(markdown: string): string {
  // Step 1: Entity-escape all HTML-significant characters FIRST
  let html = markdown
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

  // Step 2: Convert markdown syntax to HTML tags.
  // All content captured by (.*?) is already entity-escaped from Step 1.
  html = html
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br />");

  return html;
}

export default function NodeResultTab({ nodeId }: NodeResultTabProps) {
  const { t } = useTranslation(["workflows", "common"]);
  const { language } = useLanguage();
  const { can } = usePermission();
  const currentTaskId = useTaskExecutionStore((state) => state.currentTaskId);
  const traceMode = useTaskExecutionStore((state) => state.traceMode);
  const traceInputMetadata = useTaskExecutionStore((state) => state.traceInputMetadata);
  const selectedNodeType = useWorkflowStore((state) => state.nodes.find((node) => node.id === nodeId)?.type ?? null);
  const nodeStatus = useTaskExecutionStore(
    (state) => state.nodeStatuses[nodeId] ?? "idle"
  );
  const [result, setResult] = useState<NodeResultResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchResult = useCallback(async () => {
    if (!can("run.view") || !currentTaskId) {
      return;
    }

    setLoading(true);
    setError(null);
    const workspaceToken = captureWorkspaceContext();
    try {
      const data = await getNodeResult(currentTaskId, nodeId);
      if (
        !isWorkspaceContextCurrent(workspaceToken) ||
        useTaskExecutionStore.getState().currentTaskId !== currentTaskId
      ) return;
      setResult(data);
    } catch (err) {
      if (
        !isWorkspaceContextCurrent(workspaceToken) ||
        useTaskExecutionStore.getState().currentTaskId !== currentTaskId
      ) return;
      const message = err instanceof Error ? err.message : t("common:loadFailed");
      setError(message);
    } finally {
      if (
        isWorkspaceContextCurrent(workspaceToken) &&
        useTaskExecutionStore.getState().currentTaskId === currentTaskId
      ) setLoading(false);
    }
  }, [can, currentTaskId, nodeId, t]);

  // Auto-fetch when node completes
  useEffect(() => {
    if (nodeStatus === "completed" || nodeStatus === "failed") {
      void fetchResult();
    }
  }, [nodeStatus, fetchResult]);

  // Reset when node changes
  useEffect(() => {
    setResult(null);
    setError(null);
  }, [nodeId]);

  if (!can("run.view") || !currentTaskId) {
    return <EmptyResultView status="idle" />;
  }

  if (traceMode && selectedNodeType?.startsWith("input/")) {
    return <TraceInputMetadataView metadata={traceInputMetadata} />;
  }

  if (nodeStatus !== "completed" && nodeStatus !== "failed") {
    return <EmptyResultView status={nodeStatus} />;
  }

  if (loading) {
    return (
      <div className="node-result-loading">
        <Spin size="small" />
        <Typography.Text type="secondary">{t("editorText.loadingResult")}</Typography.Text>
      </div>
    );
  }

  if (error) {
    return (
      <div className="node-result-error">
        <Typography.Text type="danger">{error}</Typography.Text>
        <Button icon={<ReloadOutlined />} onClick={() => void fetchResult()} size="small">
          {t("common:retry")}
        </Button>
      </div>
    );
  }

  if (!result) {
    return <EmptyResultView status={nodeStatus} />;
  }

  // Render by result status
  if (result.status === "failed" && result.error) {
    return <ErrorResultView error={result.error as string | Record<string, unknown>} />;
  }

  // ── New format: result.output exists ──
  if (result.output) {
    return (
      <NewOutputView
        output={result.output}
        taskId={currentTaskId}
        nodeId={nodeId}
        nodeType={result.node_type}
      />
    );
  }

  // ── Legacy fallback: output_type / data ──
  if (!result.output_type) {
    return <EmptyResultView status={nodeStatus} />;
  }

  const data = result.data as Record<string, unknown> | null;

  // Route by output_type
  switch (result.output_type) {
    case "doctags": {
      const content = (data?.content as string) ?? "";
      const engineChain = (data?.engine_chain as string[]) ?? [];
      return (
        <div className="node-result-section">
          {engineChain.length > 0 ? (
            <div className="node-result-meta">
              <span>Engine: {engineChain.join(" → ")}</span>
            </div>
          ) : null}
          <TextResultView content={content} />
        </div>
      );
    }

    case "layout_detection": {
      // Backend get_node_image already handles layout detection nodes by
      // walking upstream connections to serve the source image — use self URL directly.
      const imageUrl = currentTaskId ? getNodeImageUrl(currentTaskId, nodeId) : "";
      const blocks = (data?.children as Block[]) ?? [];
      const blockCount = (data?.block_count as number) ?? blocks.length;
      return (
        <LayoutDetectionResultView
          blockCount={blockCount}
          blocks={blocks}
          imageUrl={imageUrl}
          nodeId={nodeId}
        />
      );
    }

    case "formatted_text": {
      const content = (data?.content as string) ?? "";
      const format = (data?.format as string) ?? undefined;
      const metadata = data?.metadata as Record<string, number> | undefined;
      return (
        <div className="node-result-section">
          <TextResultView content={content} format={format} />
          {metadata ? (
            <div className="node-result-meta">
              {metadata.processing_time_ms ? (
                <span>{(metadata.processing_time_ms / 1000).toFixed(1)}s</span>
              ) : null}
              {metadata.page_count ? <span>{t("editorText.pageCount", { count: formatNumber(metadata.page_count, language) })}</span> : null}
            </div>
          ) : null}
        </div>
      );
    }

    case "processed_image": {
      if (!currentTaskId) {
        return <EmptyResultView status="idle" />;
      }
      const imageUrl = getNodeImageUrl(currentTaskId, nodeId);
      const outputImage = data?.output_image as { width?: number; height?: number; url?: string } | null;
      const operations = (data?.operations as string[]) ?? [];
      return (
        <div className="node-result-section">
          <ImageResultView
            imageUrl={buildWorkspaceScopedUrl(outputImage?.url ?? imageUrl)}
            operations={operations}
            outputImage={outputImage}
          />
        </div>
      );
    }

    case "image_input": {
      const imageUrl = buildWorkspaceScopedUrl(
        (data?.image_url as string) ?? (currentTaskId ? getNodeImageUrl(currentTaskId, nodeId) : "")
      );
      const sizeBytes = data?.size_bytes as number | undefined;
      return (
        <div className="node-result-section">
          {imageUrl ? (
            <ImageResultView
              imageUrl={imageUrl}
              outputImage={data?.width && data?.height ? { width: data.width as number, height: data.height as number } : undefined}
            />
          ) : null}
          <div className="node-result-meta">
            <span>{t("editorText.formatLabel", { format: (data?.format as string) ?? "image" })}</span>
            {data?.width && data?.height ? (
              <span>{data.width as number} x {data.height as number}</span>
            ) : null}
            {sizeBytes ? (
              <span>{sizeBytes >= 1024 * 1024 ? (sizeBytes / (1024 * 1024)).toFixed(1) + " MB" : (sizeBytes / 1024).toFixed(1) + " KB"}</span>
            ) : null}
          </div>
        </div>
      );
    }

    case "text_input": {
      const content = (data?.content as string) ?? "";
      const charCount = data?.char_count as number | undefined;
      const lineCount = data?.line_count as number | undefined;
      return (
        <div className="node-result-section">
          <TextResultView content={content} />
          <div className="node-result-meta">
            {charCount !== undefined ? <span>{t("editorText.charCount", { count: formatNumber(charCount, language) })}</span> : null}
            {lineCount !== undefined ? <span>{t("editorText.lineCount", { count: formatNumber(lineCount, language) })}</span> : null}
          </div>
        </div>
      );
    }

    case "summary": {
      return (
        <div className="node-result-section">
          <pre className="node-result-raw">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      );
    }

    default: {
      return (
        <div className="node-result-section">
          <Typography.Text type="secondary">
            {t("editorText.outputType", { type: result.output_type })}
          </Typography.Text>
          <pre className="node-result-raw">
            {typeof data === "string" ? data : JSON.stringify(data, null, 2)}
          </pre>
        </div>
      );
    }
  }
}
