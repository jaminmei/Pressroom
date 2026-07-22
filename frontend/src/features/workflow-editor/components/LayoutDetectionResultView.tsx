import { ExpandOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Image, Typography } from "antd";
import type { Block } from "@/types/block";

const BLOCK_TYPE_COLOR_MAP: Record<string, string> = {
  text: "#7132f5",
  title: "#00c853",
  figure: "#ff6d00",
  figure_caption: "#ff9100",
  table: "#aa00ff",
  table_caption: "#7c4dff",
  header: "#ffd600",
  footer: "#8d6e63",
  reference: "#00bfa5",
  equation: "#e040fb",
  list: "#00bfa5",
  caption: "#78909c",
  default: "#bdbdbd"
};

function getBlockColor(type: string): string {
  const normalizedType = type.toLowerCase();
  return BLOCK_TYPE_COLOR_MAP[normalizedType] ?? BLOCK_TYPE_COLOR_MAP.default;
}

interface BBoxOverlayCanvasProps {
  imageUrl: string;
  blocks: Block[];
  highlightedBlockId: string | null;
  onBlockHover: (blockId: string | null) => void;
  onBlockClick: (blockId: string) => void;
}

function BBoxOverlayCanvas({
  imageUrl,
  blocks,
  highlightedBlockId,
  onBlockHover,
  onBlockClick
}: BBoxOverlayCanvasProps) {
  const { t } = useTranslation("workflows");
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [naturalSize, setNaturalSize] = useState({ width: 0, height: 0 });
  const [previewVisible, setPreviewVisible] = useState(false);
  const [annotatedSrc, setAnnotatedSrc] = useState<string | null>(null);

  // Generate annotated preview image with bbox overlays drawn via canvas
  useEffect(() => {
    if (!imageLoaded || !imgRef.current || naturalSize.width === 0) {
      return;
    }
    if (blocks.length === 0) {
      setAnnotatedSrc(null);
      return;
    }

    const canvas = document.createElement("canvas");
    canvas.width = naturalSize.width;
    canvas.height = naturalSize.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    ctx.drawImage(imgRef.current, 0, 0);
    for (const block of blocks) {
      const color = getBlockColor(block.type);
      const { x, y, width, height } = block.bbox;
      // Semi-transparent fill
      ctx.fillStyle = color + "33";
      ctx.fillRect(x, y, width, height);
      // Stroke
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, width, height);
      // Label background
      ctx.font = "bold 14px sans-serif";
      const tw = ctx.measureText(block.type).width;
      ctx.fillStyle = color;
      ctx.fillRect(x, y, tw + 8, 20);
      // Label text
      ctx.fillStyle = "#fff";
      ctx.fillText(block.type, x + 4, y + 15);
    }
    setAnnotatedSrc(canvas.toDataURL("image/png"));
  }, [imageLoaded, blocks, naturalSize]);

  const handleImageLoad = useCallback(() => {
    if (!imgRef.current) {
      return;
    }
    setNaturalSize({
      width: imgRef.current.naturalWidth,
      height: imgRef.current.naturalHeight
    });
    setImageLoaded(true);
  }, []);

  const handleBlockMouseEnter = useCallback(
    (blockId: string) => () => {
      onBlockHover(blockId);
    },
    [onBlockHover]
  );

  const handleBlockMouseLeave = useCallback(() => {
    onBlockHover(null);
  }, [onBlockHover]);

  const handleBlockClick = useCallback(
    (blockId: string) => () => {
      onBlockClick(blockId);
    },
    [onBlockClick]
  );

  return (
    <div ref={containerRef} className="bbox-canvas-container">
      <button
        className="bbox-preview-button"
        onClick={() => setPreviewVisible(true)}
        title={t("editorText.previewFullImage")}
        type="button"
      >
        <ExpandOutlined />
      </button>
      <Image
        preview={{
          visible: previewVisible,
          onVisibleChange: setPreviewVisible,
        }}
        src={annotatedSrc ?? imageUrl}
        style={{ display: "none" }}
      />
      <img
        ref={imgRef}
        alt={t("editorText.layoutSource")}
        className="bbox-canvas-image"
        onLoad={handleImageLoad}
        src={imageUrl}
      />
      {imageLoaded && naturalSize.width > 0 ? (
        <svg
          className="bbox-canvas-overlay"
          viewBox={`0 0 ${naturalSize.width} ${naturalSize.height}`}
        >
          {blocks.map((block) => {
            const isHighlighted = highlightedBlockId === block.id;
            const color = getBlockColor(block.type);
            const { x, y, width, height } = block.bbox;

            return (
              <g key={block.id}>
                <rect
                  className={`bbox-rect ${isHighlighted ? "is-highlighted" : ""}`}
                  fill={isHighlighted ? `${color}22` : `${color}11`}
                  height={height}
                  onClick={handleBlockClick(block.id)}
                  onMouseEnter={handleBlockMouseEnter(block.id)}
                  onMouseLeave={handleBlockMouseLeave}
                  stroke={color}
                  strokeWidth={isHighlighted ? 3 : 1.5}
                  width={width}
                  x={x}
                  y={y}
                />
                <text
                  className="bbox-label"
                  fill="#ffffff"
                  fontSize={12}
                  fontWeight="bold"
                  x={x + 4}
                  y={y + 14}
                >
                  {block.type}
                </text>
              </g>
            );
          })}
        </svg>
      ) : null}
    </div>
  );
}

interface BBoxBlockListProps {
  blocks: Block[];
  selectedBlockId: string | null;
  hoveredBlockId: string | null;
  onBlockHover: (blockId: string | null) => void;
  onBlockClick: (blockId: string) => void;
}

function BBoxBlockList({
  blocks,
  selectedBlockId,
  hoveredBlockId,
  onBlockHover,
  onBlockClick
}: BBoxBlockListProps) {
  const { t } = useTranslation("workflows");
  return (
    <div className="bbox-block-list">
      <div className="bbox-block-list-header">
        <Typography.Text strong>{t("editorText.detectedBlocks")}</Typography.Text>
        <Typography.Text type="secondary">({blocks.length})</Typography.Text>
      </div>
      <div className="bbox-block-list-items">
        {blocks.length === 0 ? (
          <div className="bbox-block-list-empty">
            <Typography.Text type="secondary">{t("editorText.noBlocks")}</Typography.Text>
          </div>
        ) : (
          blocks.map((block) => {
            const isSelected = selectedBlockId === block.id;
            const isHovered = hoveredBlockId === block.id;
            const color = getBlockColor(block.type);

            return (
              <div
                className={`bbox-block-item ${isSelected ? "is-selected" : ""} ${isHovered ? "is-hovered" : ""}`}
                key={block.id}
                onClick={() => onBlockClick(block.id)}
                onMouseEnter={() => onBlockHover(block.id)}
                onMouseLeave={() => onBlockHover(null)}
              >
                <div
                  className="bbox-block-type-badge"
                  style={{ backgroundColor: color }}
                >
                  {block.type}
                </div>
                <div className="bbox-block-info">
                  <span className="bbox-block-confidence">
                    {(block.confidence * 100).toFixed(1)}%
                  </span>
                  <span className="bbox-block-coords">
                    ({block.bbox.x}, {block.bbox.y}) {block.bbox.width}x{block.bbox.height}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

interface LayoutDetectionResultViewProps {
  nodeId: string;
  blocks: Block[];
  imageUrl: string;
  blockCount: number;
}

export default function LayoutDetectionResultView({
  blocks,
  imageUrl,
  blockCount
}: LayoutDetectionResultViewProps) {
  const { t } = useTranslation("workflows");
  const [viewMode, setViewMode] = useState<"rendered" | "raw">("rendered");
  const [hoveredBlockId, setHoveredBlockId] = useState<string | null>(null);
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);

  const handleBlockHover = useCallback((blockId: string | null) => {
    setHoveredBlockId(blockId);
  }, []);

  const handleBlockClick = useCallback((blockId: string) => {
    setSelectedBlockId((prev) => (prev === blockId ? null : blockId));
  }, []);

  return (
    <div className="layout-detection-result" data-testid="layout-detection-result">
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
        <span className="layout-detection-block-count">{t("editorText.blockCount", { count: blockCount })}</span>
      </div>

      {viewMode === "rendered" ? (
        <div className="layout-detection-content">
          <div className="layout-detection-canvas-panel">
            <BBoxOverlayCanvas
              blocks={blocks}
              highlightedBlockId={hoveredBlockId}
              imageUrl={imageUrl}
              onBlockClick={handleBlockClick}
              onBlockHover={handleBlockHover}
            />
          </div>
          <div className="layout-detection-list-panel">
            <BBoxBlockList
              blocks={blocks}
              hoveredBlockId={hoveredBlockId}
              onBlockClick={handleBlockClick}
              onBlockHover={handleBlockHover}
              selectedBlockId={selectedBlockId}
            />
          </div>
        </div>
      ) : (
        <div className="node-result-text-content">
          {blocks.length === 0 ? (
            <div className="node-result-empty">
              <Typography.Text type="secondary">{t("editorText.noBlocks")}</Typography.Text>
            </div>
          ) : (
            <pre className="node-result-raw">{JSON.stringify(blocks, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  );
}
