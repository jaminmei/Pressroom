import type { ReactNode } from "react";
import type { TFunction } from "i18next";
import type { WorkspaceCapability } from "@/types/workspace";

export type CommandCategory = "navigation" | "action" | "template" | "task" | "project";

export interface CommandDefinition {
  id: string;
  label: string;
  category: CommandCategory;
  keywords: string[];
  action: () => void;
  shortcut?: string;
  capability?: WorkspaceCapability;
}

export interface RecentWorkflowCommand {
  id: string;
  label: string;
  workflowId: string;
  lastSavedAt: string | null;
  keywords: string[];
  action: () => void;
}

export interface NodeCommandDefinition {
  id: string;
  nodeType: string;
  label: string;
  category: string;
  description?: string;
  keywords: string[];
  icon: ReactNode;
  capability?: WorkspaceCapability;
}

export interface TemplateCommandSource {
  id: string;
  name: string;
  description?: string;
  tags: string[];
}

interface BuildDefaultCommandsOptions {
  t: TFunction;
  executeWorkflow: () => void;
  saveDraft: () => void;
  publishWorkflow: () => void;
  togglePalette: () => void;
  navigateToEditor: () => void;
  navigateToTemplateCenter: () => void;
  openRecentRuns: () => void;
  clearCanvas: () => void;
  templates: TemplateCommandSource[];
  applyTemplate: (templateId: string) => void;
  openHistory: () => void;
  navigateToProjects: () => void;
  createProject: () => void;
}

function toTemplateCommandLabel(name: string, t: TFunction): string {
  return t("workflows:commands.applyTemplate", { name: name.replace(/\bMarkdown\b/gi, "MD") });
}

export function buildDefaultCommands(options: BuildDefaultCommandsOptions): CommandDefinition[] {
  const { t } = options;
  const templateCommands: CommandDefinition[] = options.templates.map((template) => ({
    id: `template-apply-${template.id}`,
    label: toTemplateCommandLabel(template.name, t),
    category: "template",
    keywords: [
      "apply",
      "template",
      "套用",
      "模板",
      template.id,
      template.name,
      ...(template.tags ?? []),
      ...(template.description ? [template.description] : [])
    ],
    action: () => options.applyTemplate(template.id),
    capability: "workflow.edit_draft"
  }));

  return [
    {
      id: "navigation-go-editor",
      label: t("workflows:commands.goEditor"),
      category: "navigation",
      keywords: ["editor", "home", "workflow", "編輯器", "首頁"],
      action: options.navigateToEditor
    },
    {
      id: "navigation-go-template-center",
      label: t("workflows:commands.goTemplates"),
      category: "navigation",
      keywords: ["template", "center", "templates", "模板", "範本"],
      action: options.navigateToTemplateCenter
    },
    {
      id: "navigation-toggle-palette",
      label: t("workflows:commands.togglePalette"),
      category: "navigation",
      keywords: ["command", "palette", "toggle", "快捷鍵"],
      action: options.togglePalette
    },
    {
      id: "action-execute-workflow",
      label: t("workflows:commands.execute"),
      category: "action",
      keywords: ["run", "execute", "start", "執行", "工作流"],
      action: options.executeWorkflow,
      capability: "workflow.run"
    },
    {
      id: "action-save-draft",
      label: t("workflows:commands.saveDraft"),
      category: "action",
      keywords: ["save", "draft", "儲存", "草稿"],
      capability: "workflow.edit_draft",
      action: options.saveDraft
    },
    {
      id: "action-publish-workflow",
      label: t("workflows:commands.publish"),
      category: "action",
      keywords: ["publish", "release", "發佈", "發布"],
      action: options.publishWorkflow,
      capability: "workflow.publish"
    },
    {
      id: "action-clear-canvas",
      label: t("workflows:commands.clearCanvas"),
      category: "action",
      keywords: ["clear", "canvas", "reset", "清空", "畫布"],
      action: options.clearCanvas,
      capability: "workflow.edit_draft"
    },
    ...templateCommands,
    {
      id: "task-open-recent-runs",
      label: t("workflows:commands.openRecentRuns"),
      category: "task",
      keywords: ["recent", "runs", "history", "drawer", "最近執行", "紀錄"],
      action: options.openRecentRuns
    },
    {
      id: "task-open-history",
      label: t("workflows:commands.openHistory"),
      category: "task",
      keywords: ["history", "recent", "runs", "歷史", "紀錄"],
      action: options.openHistory
    },
    {
      id: "navigation-go-projects",
      label: t("workflows:commands.goDatabases"),
      category: "project",
      keywords: ["databases", "database", "projects", "list", "project", "專案", "項目", "資料庫"],
      action: options.navigateToProjects
    },
    {
      id: "project-create-project",
      label: t("workflows:commands.createDatabase"),
      category: "project",
      keywords: ["create", "new", "database", "project", "建立", "新增", "專案", "資料庫"],
      action: options.createProject,
      capability: "database.create"
    }
  ];
}
