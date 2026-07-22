import {
  AppstoreOutlined,
  CheckCircleOutlined,
  CloudUploadOutlined,
  CopyOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  RollbackOutlined
} from "@ant-design/icons";
import { Button, Input, Modal, Select, Space, Tooltip, Typography, message } from "antd";
import { createElement, type ReactNode, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { LatestVersionIcon } from "@/components/Icons";
import { PermissionButton } from "@/components/Permissions/PermissionButton";
import { useResultStore } from "@/features/result/store";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import RunNameDialog from "@/features/workflow-editor/components/RunNameDialog";
import TemplateDialog from "@/features/workflow-editor/components/TemplateDialog";
import ValidationPanel from "@/features/workflow-editor/components/ValidationPanel";
import { useWorkflowPersistence } from "@/features/workflow-editor/hooks/useWorkflowPersistence";
import { useWorkflowValidation } from "@/features/workflow-editor/hooks/useWorkflowValidation";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { applyTemplateToWorkflowStore } from "@/features/workflow-editor/templates/applyTemplate";
import { BUILTIN_TEMPLATES } from "@/features/workflow-editor/templates/builtinTemplates";
import type { WorkflowTemplate } from "@/features/workflow-editor/templates/types";
import { localizeWorkflowTemplate } from "@/features/workflow-editor/templates/localizeTemplate";
import type { WorkflowValidationIssue } from "@/features/workflow-editor/utils/workflowValidator";
import type { ExecuteWorkflowResult } from "@/hooks/useTaskOrchestration";
import { usePermission } from "@/hooks/usePermission";
import { resetTask } from "@/services/taskApi";
import { useUIStore } from "@/stores/uiStore";
import type { TaskStatus } from "@/types/task";

interface CanvasFloatingToolbarProps {
  onExecuteWorkflow: (options?: { runName?: string }) => Promise<ExecuteWorkflowResult>;
  taskStatus: TaskStatus | "idle";
  runOnly?: boolean;
}

interface ToolbarButtonConfig {
  key: string;
  icon: ReactNode;
  tooltip: string;
  testId: string;
  disabled?: boolean;
  primary?: boolean;
  capability?: "workflow.edit_draft" | "workflow.publish" | "workflow.restore" | "workflow.run";
  onClick: () => void;
}

interface ApplyTemplateRequestEventDetail {
  templateId?: string;
}

export default function CanvasFloatingToolbar({
  onExecuteWorkflow,
  taskStatus,
  runOnly = false
}: CanvasFloatingToolbarProps) {
  const { t } = useTranslation(["workflows", "common", "templates"]);
  /* ── Dialog state ── */
  const [isTemplateDialogOpen, setIsTemplateDialogOpen] = useState(false);
  const [isRunNameDialogOpen, setIsRunNameDialogOpen] = useState(false);
  const [validationPanelOpen, setValidationPanelOpen] = useState(false);
  const [backendValidationIssues, setBackendValidationIssues] = useState<WorkflowValidationIssue[]>([]);
  const { can, role } = usePermission();
  const allowed = useCallback(
    (capability: "workflow.edit_draft" | "workflow.publish" | "workflow.restore" | "workflow.run") =>
      role === null || can(capability),
    [can, role],
  );

  /* ── Name dialog state (supports Publish & Publish As) ── */
  const [nameDialogOpen, setNameDialogOpen] = useState(false);
  const [nameDialogMode, setNameDialogMode] = useState<"publishNew" | "publishExisting" | "publishAs" | null>(null);
  const [nameDialogValue, setNameDialogValue] = useState("");
  const [descDialogValue, setDescDialogValue] = useState("");
  const [nameDialogSubmitting, setNameDialogSubmitting] = useState(false);

  /* ── Store selectors ── */
  const nodes = useWorkflowStore((state) => state.nodes);
  const clearCanvas = useWorkflowStore((state) => state.clearCanvas);
  const selectNode = useWorkflowStore((state) => state.selectNode);
  const clearResults = useResultStore((state) => state.clearResults);
  const resetTaskExecution = useTaskExecutionStore((state) => state.reset);
  const currentTaskId = useTaskExecutionStore((state) => state.currentTaskId);
  const uiSelectNode = useUIStore((state) => state.selectNode);
  const setRightPanelTab = useUIStore((state) => state.setRightPanelTab);

  /* ── Hooks ── */
  const localValidation = useWorkflowValidation();
  const {
    workflowId,
    workflowName,
    publishUnified,
    publishAsWorkflow,
    loadVersion,
    latestVersion,
    baseVersion,
    restoreVersion,
    versions
  } = useWorkflowPersistence();

  /* ── Derived state ── */
  const isRunning = taskStatus === "pending" || taskStatus === "running";

  const mergedBlockingErrors = [
    ...localValidation.blockingErrors,
    ...backendValidationIssues.filter((issue) => issue.severity === "blocking")
  ];
  const mergedWarnings = [
    ...localValidation.warnings,
    ...backendValidationIssues.filter((issue) => issue.severity === "warning")
  ];
  const isExecutable = mergedBlockingErrors.length === 0;

  const executeTooltip =
    taskStatus === "completed" ||
    taskStatus === "failed" ||
    taskStatus === "cancelled"
      ? t("editorText.rerun")
      : t("run");

  /* ── Name dialog reset ── */
  useEffect(() => {
    if (!nameDialogOpen) {
      setNameDialogValue(workflowName?.trim() || "");
      setDescDialogValue("");
    }
  }, [nameDialogOpen, workflowName]);

  /* ── Template apply ── */
  const applyTemplate = useCallback((template: WorkflowTemplate) => {
    const localizedTemplate = localizeWorkflowTemplate(template, t);
    applyTemplateToWorkflowStore(localizedTemplate);
    message.success(t("editorText.templateApplied", { name: localizedTemplate.name }));
    setBackendValidationIssues([]);
    setIsTemplateDialogOpen(false);
  }, [t]);

  const handleTemplateApply = useCallback(
    (template: WorkflowTemplate) => {
      if (!allowed("workflow.edit_draft")) return;
      if (nodes.length === 0) {
        applyTemplate(template);
        return;
      }
      Modal.confirm({
        title: t("editorText.templateReplaceConfirm"),
        okText: t("editorText.confirm"),
        cancelText: t("common:cancel"),
        okButtonProps: { autoInsertSpace: false },
        cancelButtonProps: { autoInsertSpace: false },
        onOk: () => applyTemplate(template)
      });
    },
    [allowed, applyTemplate, nodes.length, t]
  );

  /* ── Clear ── */
  const handleClear = useCallback(() => {
    if (!allowed("workflow.edit_draft")) return;
    Modal.confirm({
      title: t("editorText.clearConfirmTitle"),
      content: t("editorText.clearConfirmDescription"),
      okText: t("editorText.confirm"),
      cancelText: t("common:cancel"),
      okButtonProps: { autoInsertSpace: false },
      cancelButtonProps: { autoInsertSpace: false },
      onOk: async () => {
        // Reset backend context if task is in terminal state
        if (currentTaskId && (taskStatus === "completed" || taskStatus === "failed" || taskStatus === "cancelled")) {
          try {
            await resetTask(currentTaskId);
          } catch {
            // Backend reset best-effort; frontend state still clears
          }
        }
        clearCanvas();
        clearResults();
        resetTaskExecution();
        setRightPanelTab("config");
        setBackendValidationIssues([]);
        setValidationPanelOpen(false);
      }
    });
  }, [allowed, clearCanvas, clearResults, currentTaskId, resetTaskExecution, setRightPanelTab, taskStatus, t]);

  /* ── Execute ── */
  const handleExecuteRequest = useCallback(async () => {
    if (!allowed("workflow.run")) return;
    if (!isExecutable) {
      setValidationPanelOpen(true);
      return;
    }

    setIsRunNameDialogOpen(true);
  }, [allowed, isExecutable]);

  const handleConfirmRun = useCallback(
    async (runName: string) => {
      if (!allowed("workflow.run")) return;
      setIsRunNameDialogOpen(false);
      const result = await onExecuteWorkflow({ runName: runName || undefined });
      if (!result.ok) {
        const backendIssues: WorkflowValidationIssue[] = result.errors.map((error) => ({
          code: "MISSING_REQUIRED_CONFIG",
          severity: "blocking",
          nodeId: error.nodeId,
          message: error.message
        }));
        setBackendValidationIssues(backendIssues);
        setValidationPanelOpen(backendIssues.length > 0);

        const firstErrorNodeId = result.errorNodeId ?? result.errors.find((error) => error.nodeId)?.nodeId;
        const errorText =
          result.errorMessage ??
          (result.errors.length > 0
            ? t("editorText.validationFailedCount", { count: result.errors.length })
            : t("runFailed"));
        message.error(errorText);
        if (firstErrorNodeId) {
          selectNode(firstErrorNodeId);
          uiSelectNode(firstErrorNodeId);
        }
        return;
      }

      setBackendValidationIssues([]);
      setValidationPanelOpen(false);
      setRightPanelTab("run");
    },
    [allowed, onExecuteWorkflow, selectNode, setRightPanelTab, t, uiSelectNode]
  );

  const handleCancelRun = useCallback(() => {
    setIsRunNameDialogOpen(false);
  }, []);

  /* ── Validation panel: focus node ── */
  const focusIssueNode = (issue: WorkflowValidationIssue) => {
    if (!issue.nodeId) {
      return;
    }
    selectNode(issue.nodeId);
    uiSelectNode(issue.nodeId);
  };

  /* ── CustomEvent listeners (migrated from Toolbar) ── */
  useEffect(() => {
    const onExecuteRequest = () => {
      void handleExecuteRequest();
    };
    const onClearRequest = () => {
      if (!isRunning) {
        handleClear();
      }
    };
    const onApplyTemplateRequest = (event: Event) => {
      const { templateId } = (event as CustomEvent<ApplyTemplateRequestEventDetail>).detail ?? {};
      if (!templateId) {
        return;
      }
      const template = BUILTIN_TEMPLATES.find((item) => item.id === templateId);
      if (!template) {
        message.error(t("editorText.templateNotFound"));
        return;
      }
      handleTemplateApply(template);
    };

    const onOpenPublishAs = () => {
      if (workflowId && allowed("workflow.publish")) {
        setNameDialogMode("publishAs");
        setNameDialogOpen(true);
      }
    };

    window.addEventListener("workflow:execute-request", onExecuteRequest);
    window.addEventListener("workflow:clear-request", onClearRequest);
    window.addEventListener("workflow:apply-template-request", onApplyTemplateRequest);
    window.addEventListener("workflow:open-publish-as", onOpenPublishAs);

    return () => {
      window.removeEventListener("workflow:execute-request", onExecuteRequest);
      window.removeEventListener("workflow:clear-request", onClearRequest);
      window.removeEventListener("workflow:apply-template-request", onApplyTemplateRequest);
      window.removeEventListener("workflow:open-publish-as", onOpenPublishAs);
    };
  }, [allowed, handleClear, handleExecuteRequest, handleTemplateApply, isRunning, t, workflowId]);

  /* ── Button configs ── */
  const executionButtons: ToolbarButtonConfig[] = [
    {
      key: "run",
      icon: <PlayCircleOutlined />,
      tooltip: executeTooltip,
      testId: "floating-btn-run",
      disabled: isRunning,
      primary: true,
      capability: "workflow.run",
      onClick: () => {
        void handleExecuteRequest();
      }
    },
    {
      key: "validate",
      icon: <CheckCircleOutlined />,
      tooltip: t("editorText.validation"),
      testId: "floating-btn-validate",
      onClick: () => setValidationPanelOpen((current) => !current)
    },
    {
      key: "clear",
      icon: <DeleteOutlined />,
      tooltip: t("editorText.clearCanvas"),
      testId: "floating-btn-clear",
      disabled: isRunning,
      capability: "workflow.edit_draft",
      onClick: handleClear
    },
    {
      key: "template",
      icon: <AppstoreOutlined />,
      tooltip: t("editorText.templates"),
      testId: "floating-btn-template",
      onClick: () => setIsTemplateDialogOpen(true),
      capability: "workflow.edit_draft"
    }
  ];

  const persistenceButtons: ToolbarButtonConfig[] = [
    {
      key: "publishAs",
      icon: <CopyOutlined />,
      tooltip: t("publishAs"),
      testId: "floating-btn-publish-as",
      disabled: !workflowId,
      capability: "workflow.publish",
      onClick: () => {
        setNameDialogMode("publishAs");
        setNameDialogOpen(true);
      }
    },
    {
      key: "publish",
      icon: <CloudUploadOutlined />,
      tooltip: t("publish"),
      testId: "floating-btn-publish",
      primary: true,
      capability: "workflow.publish",
      onClick: () => {
        if (workflowId) {
          setNameDialogMode("publishExisting");
          setNameDialogOpen(true);
        } else {
          setNameDialogMode("publishNew");
          setNameDialogOpen(true);
        }
      }
    },
    {
      key: "restore",
      icon: <RollbackOutlined />,
      tooltip: t("editorText.restore"),
      testId: "floating-btn-restore",
      disabled: versions.length === 0,
      capability: "workflow.restore",
      onClick: () => {
        const last = versions[versions.length - 1];
        if (!last) {
          return;
        }
        void restoreVersion(last.version);
      }
    }
  ];

  const renderButton = (config: ToolbarButtonConfig) => (
    <Tooltip key={config.key} title={config.tooltip}>
      {role === null ? (
        <Button
          data-testid={config.testId}
          disabled={config.disabled}
          icon={config.icon}
          onClick={config.onClick}
          shape="circle"
          size="small"
          type={config.primary ? "primary" : "default"}
        />
      ) : (
        <PermissionButton
          capability={config.capability ?? "workflow.edit_draft"}
          data-testid={config.testId}
          disabled={config.disabled}
          icon={config.icon}
          onClick={config.onClick}
          shape="circle"
          size="small"
          type={config.primary ? "primary" : "default"}
        />
      )}
    </Tooltip>
  );

  return (
    <div className="canvas-floating-toolbar-container">

      {/* Template Dialog */}
      <TemplateDialog
        onApply={handleTemplateApply}
        onCancel={() => setIsTemplateDialogOpen(false)}
        open={isTemplateDialogOpen}
      />

      {/* Run Name Dialog */}
      <RunNameDialog
        open={isRunNameDialogOpen}
        onConfirm={handleConfirmRun}
        onCancel={handleCancelRun}
      />

      {/* Name Dialog (Publish / Publish As) */}
      <Modal
        cancelText={t("common:cancel")}
        destroyOnHidden
        okButtonProps={{ autoInsertSpace: false, disabled: nameDialogMode !== "publishExisting" && nameDialogValue.trim().length === 0 }}
        okText={nameDialogMode === "publishAs" ? t("publishAs") : t("publish")}
        onCancel={() => setNameDialogOpen(false)}
        onOk={() => {
          if (!allowed("workflow.publish")) return;
          void (async () => {
            setNameDialogSubmitting(true);
            let ok = false;
            const desc = descDialogValue.trim() || undefined;
            if (nameDialogMode === "publishNew") {
              ok = await publishUnified({ name: nameDialogValue.trim(), description: desc });
            } else if (nameDialogMode === "publishExisting") {
              ok = await publishUnified({ description: desc });
            } else if (nameDialogMode === "publishAs") {
              ok = await publishAsWorkflow(nameDialogValue.trim(), desc);
            }
            setNameDialogSubmitting(false);
            if (ok) {
              setNameDialogOpen(false);
            }
          })();
        }}
        open={nameDialogOpen}
        title={
          nameDialogMode === "publishNew" ? t("editorText.publishWorkflow")
            : nameDialogMode === "publishExisting" ? t("editorText.publishNewVersion")
            : t("editorText.publishAsNew")
        }
        confirmLoading={nameDialogSubmitting}
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          {nameDialogMode === "publishExisting" ? (
            <Typography.Text type="secondary">
              {t("editorText.versionDescriptionOptional")}
            </Typography.Text>
          ) : (
            <>
              <Typography.Text>
                {nameDialogMode === "publishNew"
                  ? t("editorText.publishNewName")
                  : t("editorText.publishDerivedName")}
              </Typography.Text>
              <Input
                autoFocus
                data-testid="workflow-name-dialog-input"
                maxLength={120}
                onChange={(event) => setNameDialogValue(event.target.value)}
                placeholder={t("editorText.workflowNamePlaceholder")}
                value={nameDialogValue}
              />
            </>
          )}
          <Input.TextArea
            autoFocus={nameDialogMode === "publishExisting"}
            data-testid="workflow-desc-dialog-input"
            maxLength={500}
            onChange={(event) => setDescDialogValue(event.target.value)}
            placeholder={t("editorText.descriptionOptional")}
            rows={2}
            showCount
            value={descDialogValue}
          />
        </Space>
      </Modal>
      <div className="canvas-floating-toolbar" data-testid="canvas-floating-toolbar">
        <div className="canvas-floating-toolbar-group" data-testid="canvas-floating-toolbar-execution">
          {executionButtons.filter((button) => !runOnly || button.key === "run").map(renderButton)}
        </div>
        {!runOnly ? <div className="canvas-floating-toolbar-divider" /> : null}
        {!runOnly && workflowId && versions.length > 0 && (
          <Select
            data-testid="version-selector"
            size="small"
            style={{ width: 100 }}
            value={baseVersion ?? latestVersion}
            onChange={(version: number) => { void loadVersion(version); }}
            options={versions.map((v, i) => ({
              value: v.version,
              label: i === 0 ? <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>v{v.version} {createElement(LatestVersionIcon, { size: 12 })}</span> : `v${v.version}`,
            }))}
          />
        )}
        {!runOnly ? (
          <div className="canvas-floating-toolbar-group" data-testid="canvas-floating-toolbar-persistence">
            {persistenceButtons.map(renderButton)}
          </div>
        ) : null}
      </div>
      <ValidationPanel
        blockingErrors={mergedBlockingErrors}
        isOpen={validationPanelOpen}
        onClose={() => setValidationPanelOpen(false)}
        onSelectIssue={(issue) => {
          focusIssueNode(issue);
        }}
        warnings={mergedWarnings}
      />

    </div>
  );
}
