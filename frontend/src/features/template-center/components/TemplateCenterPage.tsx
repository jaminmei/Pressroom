import { Alert, message } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import ImportExportBar from "@/features/template-center/components/ImportExportBar";
import TemplateCard from "@/features/template-center/components/TemplateCard";
import type { TemplateTopologyVariant } from "@/features/template-center/components/TemplateTopologyPreview";
import { applyTemplateToWorkflowStore } from "@/features/workflow-editor/templates/applyTemplate";
import { BUILTIN_TEMPLATES } from "@/features/workflow-editor/templates/builtinTemplates";
import type { WorkflowTemplate } from "@/features/workflow-editor/templates/types";
import { localizeWorkflowTemplate } from "@/features/workflow-editor/templates/localizeTemplate";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import {
  ensureSingleEndNodeGraph,
  resolvePreferredEditableNodeId
} from "@/features/workflow-editor/utils/endNodeRepair";
import { useUIStore } from "@/stores/uiStore";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";
import { formatDateTime } from "@/i18n/format";
import { useLanguage } from "@/i18n/useLanguage";

interface RecentTemplateUsage {
  templateId: string;
  usedAt: string;
}

interface GoldenPathMeta {
  title: string;
  description: string;
  topology: TemplateTopologyVariant;
}

interface RecentTemplateEntry {
  name: string;
  usedAt: string;
}

const RECENT_TEMPLATE_KEY = "template_recent_used";
const MAX_RECENT_USAGE = 5;
const goldenPathMetaByTemplateId: Record<string, GoldenPathMeta> = {
  "tpl-ocr-basic": {
    title: "Quick Convert",
    description: "以最少設定快速完成單一路徑轉換，適合標準文件批次處理。",
    topology: "quick-convert"
  },
  "tpl-vlm-basic": {
    title: "Custom Workflow",
    description: "保留可擴充的節點骨架，方便依文件類型與規則做客製流程調整。",
    topology: "custom-workflow"
  },
  "tpl-compare-ocr-vlm": {
    title: "Multi-Engine Compare",
    description: "同時跑多引擎並對照結果，快速比較品質與成本表現。",
    topology: "multi-engine-compare"
  }
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function getGoldenPathMeta(template: WorkflowTemplate): GoldenPathMeta {
  return (
    goldenPathMetaByTemplateId[template.id] ?? {
      title: template.name,
      description: template.description,
      topology: "quick-convert"
    }
  );
}

function resolveImportErrorMessage(code: string, t: TFunction): string {
  if (code === "JSON_PARSE_ERROR") return t("templates:invalidJson");
  if (code === "WORKFLOW_EMPTY_NODES") return t("templates:emptyNodes");
  return t("templates:invalidSchema");
}

function formatRecentUsageDate(usedAt: string, language: "en" | "zh-TW"): string {
  const parsed = new Date(usedAt);
  if (Number.isNaN(parsed.getTime())) {
    return usedAt;
  }

  return formatDateTime(parsed, language, {
    month: "short",
    day: "numeric"
  });
}

function readRecentTemplateUsage(): RecentTemplateUsage[] {
  try {
    const raw = window.localStorage.getItem(RECENT_TEMPLATE_KEY);
    if (!raw) {
      return [];
    }

    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed
      .filter((item): item is RecentTemplateUsage => {
        return typeof item?.templateId === "string" && typeof item?.usedAt === "string";
      })
      .slice(0, MAX_RECENT_USAGE);
  } catch {
    return [];
  }
}

function saveRecentTemplateUsage(items: RecentTemplateUsage[]) {
  window.localStorage.setItem(RECENT_TEMPLATE_KEY, JSON.stringify(items.slice(0, MAX_RECENT_USAGE)));
}

function mapImportedNodes(nodes: Array<Record<string, unknown>>): WorkflowNode[] {
  return nodes.map((node, index) => {
    const nodeId = typeof node.id === "string" ? node.id : `node_${index + 1}`;
    const nodeType = typeof node.type === "string" ? node.type : "processor/custom";
    const position =
      typeof node.position === "object" && node.position !== null
        ? {
            x: Number((node.position as { x?: unknown }).x ?? 120 + index * 140),
            y: Number((node.position as { y?: unknown }).y ?? 180)
          }
        : { x: 120 + index * 140, y: 180 };

    return {
      id: nodeId,
      type: nodeType,
      position,
      data: {
        label: typeof node.label === "string" ? node.label : nodeType,
        config: typeof node.config === "object" && node.config !== null ? (node.config as Record<string, unknown>) : {},
        configSchema: {
          type: "object",
          properties: {}
        }
      }
    };
  });
}

function mapImportedEdges(connections: Array<Record<string, unknown>>): WorkflowEdge[] {
  return connections
    .map((connection, index) => {
      const source = typeof connection.source === "string" ? connection.source : "";
      const target = typeof connection.target === "string" ? connection.target : "";
      if (!source || !target) {
        return null;
      }

      return {
        id: typeof connection.id === "string" ? connection.id : `edge_${index + 1}`,
        source,
        target
      };
    })
    .filter((edge): edge is WorkflowEdge => Boolean(edge));
}

function resolveWorkflowDefinition(payload: unknown): {
  nodes: Array<Record<string, unknown>>;
  connections: Array<Record<string, unknown>>;
} {
  if (!isRecord(payload)) {
    throw new Error("WORKFLOW_SCHEMA_INVALID");
  }

  const candidates: Array<Record<string, unknown>> = [payload];
  if (isRecord(payload.definition)) {
    candidates.push(payload.definition);
  }
  if (isRecord(payload.workflow)) {
    candidates.push(payload.workflow);
    if (isRecord(payload.workflow.definition)) {
      candidates.push(payload.workflow.definition);
    }
  }

  for (const candidate of candidates) {
    if (!("nodes" in candidate) || !("connections" in candidate)) {
      continue;
    }

    if (!Array.isArray(candidate.nodes) || !Array.isArray(candidate.connections)) {
      throw new Error("WORKFLOW_SCHEMA_INVALID");
    }

    if (!candidate.nodes.every((node) => isRecord(node)) || !candidate.connections.every((edge) => isRecord(edge))) {
      throw new Error("WORKFLOW_SCHEMA_INVALID");
    }

    if (candidate.nodes.length === 0) {
      throw new Error("WORKFLOW_EMPTY_NODES");
    }

    return {
      nodes: candidate.nodes as Array<Record<string, unknown>>,
      connections: candidate.connections as Array<Record<string, unknown>>
    };
  }

  throw new Error("WORKFLOW_SCHEMA_INVALID");
}

function readFileAsText(file: File): Promise<string> {
  const maybeText = (file as File & { text?: () => Promise<string> }).text;
  if (typeof maybeText === "function") {
    return maybeText.call(file);
  }

  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      resolve(typeof reader.result === "string" ? reader.result : "");
    };
    reader.onerror = () => {
      reject(new Error("JSON_PARSE_ERROR"));
    };
    reader.readAsText(file);
  });
}

function exportTemplateAsJson(template: WorkflowTemplate) {
  const content = JSON.stringify(
    {
      name: template.name,
      nodes: template.nodes,
      connections: template.connections
    },
    null,
    2
  );
  const blob = new Blob([content], { type: "application/json" });
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${template.name}.json`;
  anchor.click();
  window.URL.revokeObjectURL(url);
}

export default function TemplateCenterPage() {
  const { t } = useTranslation("templates");
  const { language } = useLanguage();
  const navigate = useNavigate();
  const setRightPanelTab = useUIStore((state) => state.setRightPanelTab);
  const nodeRegistry = useWorkflowStore((state) => state.nodeRegistry);
  const [recentUsage, setRecentUsage] = useState<RecentTemplateUsage[]>([]);
  const [importError, setImportError] = useState<string | null>(null);
  const localizedMeta = useCallback((template: WorkflowTemplate): GoldenPathMeta => {
    const meta = getGoldenPathMeta(template);
    const key = template.id === "tpl-ocr-basic" ? "ocr" : template.id === "tpl-vlm-basic" ? "vlm" : "compare";
    return {
      ...meta,
      title: t(`meta.${key}.title`, { defaultValue: meta.title }),
      description: t(`meta.${key}.description`, { defaultValue: meta.description })
    };
  }, [t]);

  useEffect(() => {
    setRecentUsage(readRecentTemplateUsage());
  }, []);

  const recentUsageEntries = useMemo<RecentTemplateEntry[]>(() => {
    return recentUsage
      .map((item) => {
        const template = BUILTIN_TEMPLATES.find((entry) => entry.id === item.templateId);
        if (!template) {
          return null;
        }

        return {
          name: localizedMeta(template).title,
          usedAt: formatRecentUsageDate(item.usedAt, language)
        };
      })
      .filter((item): item is RecentTemplateEntry => Boolean(item));
  }, [language, localizedMeta, recentUsage]);

  const heroHighlights = useMemo(
    () => [
      {
        label: t("starters"),
        value: String(BUILTIN_TEMPLATES.length)
      },
      {
        label: t("inputTypes"),
        value: String(new Set(BUILTIN_TEMPLATES.flatMap((template) => template.supported_input_types)).size)
      },
      {
        label: t("compareReady"),
        value: String(BUILTIN_TEMPLATES.filter((template) => template.category === "comparison").length)
      }
    ],
    [t]
  );

  const handleApplyTemplate = (template: WorkflowTemplate) => {
    const goldenPathMeta = localizedMeta(template);
    applyTemplateToWorkflowStore(localizeWorkflowTemplate(template, t));
    const nextUsage = [{ templateId: template.id, usedAt: new Date().toISOString() }, ...recentUsage].filter(
      (item, index, array) => array.findIndex((entry) => entry.templateId === item.templateId) === index
    );
    saveRecentTemplateUsage(nextUsage);
    setRecentUsage(nextUsage.slice(0, MAX_RECENT_USAGE));

    message.success(t("templateApplied", { name: goldenPathMeta.title }));
    setRightPanelTab("config");
    navigate("/");
  };

  const handleImport = async (file: File) => {
    setImportError(null);

    try {
      const text = await readFileAsText(file);
      let parsed: unknown;
      try {
        parsed = JSON.parse(text);
      } catch {
        throw new Error("JSON_PARSE_ERROR");
      }

      const definition = resolveWorkflowDefinition(parsed);
      const repairedGraph = ensureSingleEndNodeGraph({
        nodes: mapImportedNodes(definition.nodes),
        edges: mapImportedEdges(definition.connections),
        registry: nodeRegistry
      });
      const selectedNodeId = resolvePreferredEditableNodeId(repairedGraph.nodes);
      useWorkflowStore.setState({
        nodes: repairedGraph.nodes,
        edges: repairedGraph.edges,
        nodeConfigs: Object.fromEntries(repairedGraph.nodes.map((node) => [node.id, node.data.config ?? {}])),
        uploadedFiles: {},
        selectedNodeId
      });
      setRightPanelTab("config");
      navigate("/");
      message.success(t("importSuccess"));
    } catch (error) {
      const code = error instanceof Error ? error.message : "WORKFLOW_SCHEMA_INVALID";
      const errorMessage = resolveImportErrorMessage(code, t);
      setImportError(errorMessage);
      message.error(errorMessage);
    }
  };

  return (
    <section className="template-center-page" data-testid="template-center-page">
      <header className="template-center-header">
        <div className="template-center-header-copy">
          <span className="template-center-kicker">{t("curatedStarters")}</span>
          <h2>{t("title")}</h2>
          <p>
            {t("pageDescription")}
          </p>
        </div>
        <div className="template-center-hero-panel">
          <div className="template-center-hero-panel-copy">
            <span className="template-center-hero-panel-kicker">{t("launchpad")}</span>
            <strong>{t("heroTitle")}</strong>
            <p>{t("heroDescription")}</p>
          </div>
          <div className="template-center-highlight-grid">
            {heroHighlights.map((item) => (
              <div className="template-center-highlight-card" key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </div>
            ))}
          </div>
          <ImportExportBar
            onClearRecent={() => {
              window.localStorage.removeItem(RECENT_TEMPLATE_KEY);
              setRecentUsage([]);
            }}
            onImport={(file) => void handleImport(file)}
          />
        </div>
      </header>

      {importError ? <Alert message={importError} type="error" /> : null}

      <div className="template-center-section-heading">
        <div>
          <span className="template-center-section-kicker">{t("launchBaseline")}</span>
          <h3>{t("productionStarters")}</h3>
        </div>
        <p>{t("sectionDescription")}</p>
      </div>

      <div className="template-center-grid">
        {BUILTIN_TEMPLATES.map((template) => {
          const meta = localizedMeta(template);
          return (
            <div data-testid={`template-card-${template.id}`} key={template.id}>
              <TemplateCard
                description={meta.description}
                onApply={handleApplyTemplate}
                onExport={exportTemplateAsJson}
                template={template}
                title={meta.title}
                topology={meta.topology}
              />
            </div>
          );
        })}
      </div>

      <section className="template-center-recent">
        <div className="template-center-recent-header">
          <span className="template-center-recent-kicker">{t("lastLaunch")}</span>
          <h3>{t("recentlyUsed")}</h3>
        </div>
        {recentUsageEntries.length === 0 ? <p>{t("noRecent")}</p> : null}
        {recentUsageEntries.length > 0 ? (
          <div className="template-center-recent-list">
            {recentUsageEntries.map((entry, index) => (
              <div className="template-center-recent-item" key={`${entry.name}-${index}`}>
                <strong>{entry.name}</strong>
                <span>{entry.usedAt}</span>
              </div>
            ))}
          </div>
        ) : null}
      </section>
    </section>
  );
}
