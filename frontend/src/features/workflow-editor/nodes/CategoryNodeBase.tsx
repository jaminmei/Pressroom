import { Handle, Position } from "@xyflow/react";
import { Tooltip } from "antd";
import { createElement, type ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { ACTION_ICONS } from "@/components/Icons";

import { ENGINE_CATEGORY_MAP } from "@/features/workflow-editor/components/EngineConfigPanel";
import NodeStatusBadge from "@/features/task-execution/components/NodeStatusBadge";
import type { TaskNodeVisualStatus } from "@/features/task-execution/store";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import NodeEndpointAddControl from "@/features/workflow-editor/components/NodeEndpointAddControl";
import { useWorkflowValidation } from "@/features/workflow-editor/hooks/useWorkflowValidation";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import {
  HANDLE_ID_CONTEXT,
  HANDLE_ID_PRIMARY,
  isMultiInputNode
} from "@/features/workflow-editor/utils/handleRouting";
import type { WorkflowValidationIssue } from "@/features/workflow-editor/utils/workflowValidator";
import { workflowUnchangedSinceLastRun } from "@/utils/dagFingerprint";

interface CategoryNodeBaseProps extends WorkflowNodeComponentProps {
  icon: ReactNode;
  titleColor: string;
  className: string;
}

export interface WorkflowCanvasNodeData {
  id?: string;
  label: string;
  config: Record<string, unknown>;
  nodeType?: string;
  status?: TaskNodeVisualStatus;
  maxInputs?: number;
}

export interface WorkflowNodeComponentProps {
  id?: string;
  type?: string;
  data: WorkflowCanvasNodeData;
  isConnectable?: boolean;
  [key: string]: unknown;
}

export interface ConfigEntry {
  key: string;
  value: string;
  rawValue: unknown;
}

export function formatConfigValue(value: unknown, t?: TFunction): string {
  if (value === null || value === undefined) return "\u2014";
  if (typeof value === "boolean") return value ? (t?.("common:yes") ?? "Yes") : (t?.("common:no") ?? "No");
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) {
    if (value.length === 0) return t?.("workflows:editorText.arrayItems", { count: 0 }) ?? "[0 items]";
    if (value.length <= 3 && value.every((v) => typeof v === "string"))
      return value.join(", ");
    return t?.("workflows:editorText.arrayItems", { count: value.length }) ?? `[${value.length} items]`;
  }
  if (typeof value === "object") return t?.("workflows:editorText.objectKeys", { count: Object.keys(value as object).length }) ?? `{${Object.keys(value as object).length} keys}`;
  return String(value);
}

export function summarizeConfig(config: Record<string, unknown>, t?: TFunction): ConfigEntry[] {
  const entries = Object.entries(config).filter(
    ([, value]) => value !== undefined
  );

  if (entries.length === 0) {
    return [{ key: "", value: t?.("workflows:editorText.noConfig") ?? "No config", rawValue: null }];
  }

  return entries.map(([key, value]) => ({
    key,
    value: formatConfigValue(value, t),
    rawValue: value
  }));
}

/**
 * Build a display-friendly summary for engine nodes.
 * Shows provider/model names instead of IDs, and hides internal fields.
 * Returns empty array if no provider is selected yet.
 */
function summarizeEngineConfig(config: Record<string, unknown>, t: TFunction): ConfigEntry[] {
  // No provider selected yet — show nothing
  if (!config.provider_id) {
    return [];
  }

  const INTERNAL_KEYS = new Set([
    "provider_id", "provider_name",
    "model", "model_group", "applicable_groups", "file",
  ]);

  const result: ConfigEntry[] = [];

  // Show provider name
  if (config.provider_name) {
    result.push({ key: t("workflows:editorText.provider"), value: String(config.provider_name), rawValue: config.provider_name });
  }

  // Show model name
  if (config.model) {
    result.push({ key: t("workflows:editorText.model"), value: String(config.model), rawValue: config.model });
  }

  // Show remaining user-configured params (skip internal fields)
  Object.entries(config).forEach(([key, value]) => {
    if (value === undefined || INTERNAL_KEYS.has(key)) return;
    result.push({ key, value: formatConfigValue(value, t), rawValue: value });
  });

  return result;
}

function formatFullValue(value: unknown): string {
  if (value === null || value === undefined) return "\u2014";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean")
    return String(value);
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function useIsTextTruncated(
  ref: React.RefObject<HTMLElement | null>,
  text?: string
): boolean {
  const [truncated, setTruncated] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setTruncated(el.scrollWidth > el.clientWidth);
  }, [ref, text]);
  return truncated;
}

export function CategoryNodeBase({
  id,
  data,
  icon,
  titleColor,
  className,
  isConnectable
}: CategoryNodeBaseProps) {
  const { t } = useTranslation(["workflows", "common"]);
  const removeNode = useWorkflowStore((state) => state.removeNode);
  const duplicateNode = useWorkflowStore((state) => state.duplicateNode);
  const wfNodes = useWorkflowStore((state) => state.nodes);
  const wfEdges = useWorkflowStore((state) => state.edges);
  const wfNodeConfigs = useWorkflowStore((state) => state.nodeConfigs);
  const wfUploadedFiles = useWorkflowStore((state) => state.uploadedFiles);
  const nodeErrors = useTaskExecutionStore((state) => state.nodeErrors);
  const currentTaskId = useTaskExecutionStore((state) => state.currentTaskId);
  const taskStatus = useTaskExecutionStore((state) => state.taskStatus);
  const nodeStatuses = useTaskExecutionStore((state) => state.nodeStatuses);
  const lastRunDagFingerprint = useTaskExecutionStore((state) => state.lastRunDagFingerprint);
  const lastRunInputFiles = useTaskExecutionStore((state) => state.lastRunInputFiles);

  const { blockingErrors, warnings } = useWorkflowValidation();
  const nodeId = typeof data.id === "string" ? data.id : id;
  const nodeType = typeof data.nodeType === "string" ? data.nodeType : undefined;
  const nodeError = nodeId ? nodeErrors[nodeId] : undefined;
  const nodeValidationIssues = nodeId
    ? [...blockingErrors, ...warnings].filter((issue: WorkflowValidationIssue) => issue.nodeId === nodeId)
    : [];
  const errorCount = nodeValidationIssues.filter((i: WorkflowValidationIssue) => i.severity === "blocking").length;
  const warningCount = nodeValidationIssues.filter((i: WorkflowValidationIssue) => i.severity === "warning").length;
  const validationClass = errorCount > 0 ? "validation-error" : warningCount > 0 ? "validation-warning" : "";
  const titleRef = useRef<HTMLSpanElement>(null);
  const isTitleTruncated = useIsTextTruncated(titleRef, data.label);
  const hasMultiInput = isMultiInputNode(data.maxInputs);

  const validationTooltip = nodeValidationIssues.length > 0
    ? nodeValidationIssues.map((i: WorkflowValidationIssue) => i.message).join("\n")
    : undefined;

  return (
    <div className={`workflow-node-card ${className} ${validationClass}`} data-testid="workflow-node-card">
      {nodeValidationIssues.length > 0 && (
        <Tooltip title={validationTooltip} placement="topRight">
          <span
            className={`workflow-node-validation-badge ${errorCount > 0 ? "workflow-node-validation-badge-error" : "workflow-node-validation-badge-warn"}`}
            data-testid="workflow-node-validation-badge"
          >
            {nodeValidationIssues.length}
          </span>
        </Tooltip>
      )}
      {nodeId ? (
        <NodeEndpointAddControl
          direction="upstream"
          handleId={hasMultiInput ? HANDLE_ID_PRIMARY : undefined}
          isConnectable={isConnectable}
          nodeId={nodeId}
          nodeType={nodeType}
        />
      ) : (
        <Handle
          id={hasMultiInput ? HANDLE_ID_PRIMARY : undefined}
          isConnectable={isConnectable}
          position={Position.Left}
          type="target"
        />
      )}
      {hasMultiInput && (
        <Handle
          className="workflow-node-context-handle-invisible nodrag nopan"
          data-testid="workflow-node-context-handle"
          id={HANDLE_ID_CONTEXT}
          isConnectable={isConnectable}
          position={Position.Top}
          type="target"
        />
      )}
      <div className="workflow-node-title" data-testid="workflow-node-title" style={{ backgroundColor: titleColor }}>
        <span className="workflow-node-icon">{icon}</span>
        <Tooltip title={isTitleTruncated ? data.label : undefined}>
          <span ref={titleRef} className="workflow-node-title-text">{data.label}</span>
        </Tooltip>
        <NodeStatusBadge errorMessage={nodeError} status={data.status ?? "idle"} />
      </div>
      <div className="workflow-node-summary">
        {(data.nodeType && data.nodeType in ENGINE_CATEGORY_MAP
          ? summarizeEngineConfig(data.config, t)
          : summarizeConfig(data.config, t)
        ).map((entry, i) => (
          <Tooltip
            key={i}
            title={entry.rawValue === null ? undefined : `${entry.key}: ${formatFullValue(entry.rawValue)}`}
            placement="top"
            mouseEnterDelay={0.3}
          >
            <div className="workflow-node-summary-item">
              {entry.rawValue === null ? entry.value : `${entry.key}: ${entry.value}`}
            </div>
          </Tooltip>
        ))}
      </div>
      {nodeId ? (
        <div className="workflow-node-actions" data-testid="workflow-node-actions">
          <button
            aria-label={t("editorText.runNode")}
            onClick={() => {
              window.dispatchEvent(
                new CustomEvent("workflow:node-run-request", {
                  detail: { nodeId }
                })
              );
            }}
            title={t("run")}
            type="button"
          >
            <span aria-hidden className="workflow-node-actions-icon">
              {createElement(ACTION_ICONS.run, { size: 18 })}
            </span>
          </button>
          {nodeType && !nodeType.startsWith("input/") && nodeType !== "end/final" && currentTaskId && taskStatus !== "pending" && taskStatus !== "running" && workflowUnchangedSinceLastRun(wfNodes, wfEdges, wfNodeConfigs, wfUploadedFiles, lastRunDagFingerprint, lastRunInputFiles) ? (
            <Tooltip title={nodeId && nodeStatuses[nodeId] ? t("editorText.rerun") : t("editorText.rerunUnavailable")}>
              <button
                aria-label={t("editorText.rerunNode")}
                disabled={!(nodeId && nodeStatuses[nodeId])}
                onClick={() => {
                  window.dispatchEvent(
                    new CustomEvent("workflow:node-rerun-request", {
                      detail: { nodeId }
                    })
                  );
                }}
                title={t("editorText.rerun")}
                type="button"
              >
                <span aria-hidden className="workflow-node-actions-icon">
                  {createElement(ACTION_ICONS.rerun, { size: 18 })}
                </span>
              </button>
            </Tooltip>
          ) : null}
          <button
            aria-label={t("editorText.copyNode")}
            onClick={() => {
              duplicateNode(nodeId);
            }}
            title={t("common:copy")}
            type="button"
          >
            <span aria-hidden className="workflow-node-actions-icon">
              {createElement(ACTION_ICONS.copy, { size: 18 })}
            </span>
          </button>
          <button
            aria-label={t("editorText.deleteNode")}
            onClick={() => {
              removeNode(nodeId);
            }}
            title={t("common:delete")}
            type="button"
          >
            <span aria-hidden className="workflow-node-actions-icon">
              {createElement(ACTION_ICONS.delete, { size: 18 })}
            </span>
          </button>
        </div>
      ) : null}
      {nodeId ? (
        <NodeEndpointAddControl
          direction="downstream"
          isConnectable={isConnectable}
          nodeId={nodeId}
          nodeType={nodeType}
        />
      ) : (
        <Handle isConnectable={isConnectable} position={Position.Right} type="source" />
      )}
    </div>
  );
}
