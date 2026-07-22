import type { AxiosError } from "axios";
import { Input, Modal, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import WorkflowStudioList from "@/features/workflow-studio/components/WorkflowStudioList";
import WorkflowStudioToolbar from "@/features/workflow-studio/components/WorkflowStudioToolbar";
import { useResultStore } from "@/features/result/store";
import type { WorkflowListItem } from "@/services/workflowApi";
import { deleteWorkflow, updateWorkflowMetadata } from "@/services/workflowApi";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { useWorkflowStudioList } from "@/features/workflow-studio/hooks/useWorkflowStudioList";
import { usePermission } from "@/hooks/usePermission";
import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { initialUIState, useUIStore } from "@/stores/uiStore";

interface WorkflowApiErrorResponse {
  error_code?: string;
  message?: string;
}

function resolveDeleteErrorMessage(error: unknown, missing: string, fallback: string): string {
  const response = (error as AxiosError<WorkflowApiErrorResponse> | undefined)?.response;
  if (response?.data?.error_code === "WORKFLOW_NOT_FOUND") {
    return missing;
  }

  if (typeof response?.data?.message === "string" && response.data.message.trim().length > 0) {
    return response.data.message;
  }

  return fallback;
}

function resolveRenameErrorMessage(error: unknown, missing: string, fallback: string): string {
  const response = (error as AxiosError<WorkflowApiErrorResponse> | undefined)?.response;
  if (response?.data?.error_code === "WORKFLOW_NOT_FOUND") {
    return missing;
  }

  if (typeof response?.data?.message === "string" && response.data.message.trim().length > 0) {
    return response.data.message;
  }

  return fallback;
}

function detachDeletedWorkflow(workflowId: string) {
  const persistenceState = useWorkflowPersistenceStore.getState();
  if (persistenceState.workflowId !== workflowId) {
    return;
  }

  if (persistenceState.isDirty) {
    useWorkflowPersistenceStore.setState({
      workflowId: null,
      publishedVersion: null,
      latestVersion: 0,
      versions: [],
      lastSavedAt: null,
      isDirty: true
    });
    return;
  }

  useWorkflowStore.getState().clearCanvas();
  persistenceState.reset();
}

function resetEditorForBlankWorkflow() {
  useWorkflowStore.getState().clearCanvas();
  useWorkflowPersistenceStore.getState().reset();
  useTaskExecutionStore.getState().reset();
  useResultStore.getState().reset();
  useUIStore.setState((state) => ({
    ...state,
    selectedNodeId: initialUIState.selectedNodeId,
    rightPanelTab: initialUIState.rightPanelTab,
    commandPaletteOpen: initialUIState.commandPaletteOpen,
    recentRunsDrawerOpen: initialUIState.recentRunsDrawerOpen
  }));
}

export default function WorkflowStudioPage() {
  const { t } = useTranslation(["common", "workflows"]);
  const navigate = useNavigate();
  const { can, role } = usePermission();
  const allowed = useCallback((capability: "workflow.create" | "workflow.edit_draft" | "workflow.delete" | "api_key.view") => {
    return role === null || can(capability);
  }, [can, role]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<WorkflowListItem | null>(null);
  const [renameName, setRenameName] = useState("");
  const [renameDescription, setRenameDescription] = useState("");
  const [renaming, setRenaming] = useState(false);
  const currentWorkflowId = useWorkflowPersistenceStore((state) => state.workflowId);
  const currentWorkflowBaseVersion = useWorkflowPersistenceStore((state) => state.baseVersion);
  const isDirty = useWorkflowPersistenceStore((state) => state.isDirty);
  const { items, loading, loadingMore, error, hasMore, meta, query, setQuery, clearQuery, refresh, fetchMore } =
    useWorkflowStudioList();

  const startFreshWorkflow = useCallback(() => {
    resetEditorForBlankWorkflow();
    navigate("/");
  }, [navigate]);

  const handleCreateNewWorkflow = useCallback(() => {
    if (!allowed("workflow.create")) return;
    if (!isDirty) {
      startFreshWorkflow();
      return;
    }

    Modal.confirm({
      title: t("workflows:studioText.newDirtyTitle"),
      content: t("workflows:studioText.newDirtyDescription"),
      okText: t("workflows:studioText.continueCreate"),
      cancelText: t("common:cancel"),
      okButtonProps: { autoInsertSpace: false },
      cancelButtonProps: { autoInsertSpace: false },
      onOk: startFreshWorkflow
    });
  }, [allowed, isDirty, startFreshWorkflow, t]);

  const closeRenameModal = useCallback(() => {
    if (renaming) {
      return;
    }
    setRenameTarget(null);
    setRenameName("");
    setRenameDescription("");
  }, [renaming]);

  const handleOpenWorkflow = useCallback(
    (workflow: WorkflowListItem) => {
      const openWorkflow = () => {
        navigate(`/workflows/${workflow.id}`);
      };

      if (!isDirty) {
        openWorkflow();
        return;
      }

      Modal.confirm({
        title: t("workflows:studioText.openDirtyTitle"),
        content:
          currentWorkflowId && currentWorkflowId === workflow.id
            ? t("workflows:studioText.reloadDirtyDescription")
            : t("workflows:studioText.switchDirtyDescription"),
        okText: t("workflows:studioText.continueOpen"),
        cancelText: t("common:cancel"),
        okButtonProps: { autoInsertSpace: false },
        cancelButtonProps: { autoInsertSpace: false },
        onOk: openWorkflow
      });
    },
    [currentWorkflowId, isDirty, navigate, t]
  );

  const handleOpenApiAccess = useCallback(
    (workflow: WorkflowListItem) => {
      if (!allowed("api_key.view")) return;
      navigate(`/workflows/${workflow.id}/api-access`);
    },
    [allowed, navigate]
  );

  const handleDeleteWorkflow = useCallback(
    (workflow: WorkflowListItem) => {
      if (!allowed("workflow.delete")) return;
      Modal.confirm({
        title: t("workflows:studioText.deleteConfirmTitle"),
        content: t("workflows:studioText.deleteConfirm", { name: workflow.name?.trim() || workflow.id }),
        okText: t("workflows:studioText.confirmDelete"),
        cancelText: t("common:cancel"),
        okButtonProps: {
          danger: true,
          autoInsertSpace: false
        },
        cancelButtonProps: {
          autoInsertSpace: false
        },
        onOk: async () => {
          setDeletingId(workflow.id);
          try {
            await deleteWorkflow(workflow.id);
            detachDeletedWorkflow(workflow.id);
            message.success(t("workflows:studioText.deleteSuccess"));
            await refresh();
          } catch (error) {
            const errorMessage = resolveDeleteErrorMessage(
              error,
              t("workflows:studioText.missing"),
              t("workflows:studioText.deleteFailed")
            );
            message.error(errorMessage);
            if (
              (error as AxiosError<WorkflowApiErrorResponse> | undefined)?.response?.data?.error_code ===
              "WORKFLOW_NOT_FOUND"
            ) {
              detachDeletedWorkflow(workflow.id);
              await refresh();
            }
          } finally {
            setDeletingId(null);
          }
        }
      });
    },
    [allowed, refresh, t]
  );

  const handleRenameWorkflow = useCallback((workflow: WorkflowListItem) => {
    if (!allowed("workflow.edit_draft")) return;
    setRenameTarget(workflow);
    setRenameName(workflow.name?.trim() ?? "");
    setRenameDescription(workflow.description ?? "");
  }, [allowed]);

  const submitRenameWorkflow = useCallback(async () => {
    if (!allowed("workflow.edit_draft")) return;
    if (!renameTarget) {
      return;
    }

    const normalizedName = renameName.trim();
    if (!normalizedName) {
      message.error(t("workflows:studioText.nameRequired"));
      return;
    }

    setRenaming(true);
    try {
      await updateWorkflowMetadata(renameTarget.id, {
        name: normalizedName,
        description: renameDescription.trim()
      });
      message.success(t("workflows:studioText.renameSuccess"));
      setRenameTarget(null);
      setRenameName("");
      setRenameDescription("");
      await refresh();
    } catch (error) {
      message.error(resolveRenameErrorMessage(
        error,
        t("workflows:studioText.missing"),
        t("workflows:studioText.renameFailed")
      ));
      if (
        (error as AxiosError<WorkflowApiErrorResponse> | undefined)?.response?.data?.error_code ===
        "WORKFLOW_NOT_FOUND"
      ) {
        setRenameTarget(null);
        setRenameName("");
        setRenameDescription("");
        await refresh();
      }
    } finally {
      setRenaming(false);
    }
  }, [allowed, refresh, renameDescription, renameName, renameTarget, t]);

  useEffect(() => {
    const onFocus = () => {
      void refresh();
    };

    window.addEventListener("focus", onFocus);
    return () => {
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  return (
    <section className="workflow-studio-page" data-testid="workflow-studio-page">
      <WorkflowStudioToolbar
        loading={loading && items.length === 0}
        onCreateNew={handleCreateNewWorkflow}
        onQueryChange={setQuery}
        query={query}
        total={meta.total}
      />

      <WorkflowStudioList
        deletingId={deletingId}
        error={error}
        hasMore={hasMore}
        items={items}
        loading={loading}
        loadingMore={loadingMore}
        onClearQuery={clearQuery}
        onCreateNew={handleCreateNewWorkflow}
        onDelete={handleDeleteWorkflow}
        onLoadMore={() => void fetchMore()}
        newerVersionWorkflowId={
          currentWorkflowId && currentWorkflowBaseVersion
            ? items.find((item) => item.id === currentWorkflowId && (item.latest_version ?? 0) > currentWorkflowBaseVersion)?.id ?? null
            : null
        }
        onOpen={handleOpenWorkflow}
        onOpenApiAccess={handleOpenApiAccess}
        onRename={handleRenameWorkflow}
        onRetry={() => void refresh()}
        query={query}
        total={meta.total}
      />

      <Modal
        cancelText={t("common:cancel")}
        confirmLoading={renaming}
        destroyOnHidden
        okButtonProps={{ autoInsertSpace: false, disabled: renameName.trim().length === 0 }}
        okText={t("common:save")}
        onCancel={closeRenameModal}
        onOk={() => void submitRenameWorkflow()}
        open={renameTarget !== null}
        title={t("workflows:studioText.updateName")}
        >
        <div style={{ display: "grid", gap: 12 }}>
          <label>
            <div style={{ marginBottom: 4 }}>{t("workflows:studioText.workflowName")}</div>
            <Input
              autoFocus
              data-testid="workflow-studio-rename-name"
              maxLength={120}
              onChange={(event) => setRenameName(event.target.value)}
              placeholder={t("workflows:studioText.enterName")}
              value={renameName}
            />
          </label>
          <label>
            <div style={{ marginBottom: 4 }}>{t("common:description")} ({t("common:optional")})</div>
            <Input.TextArea
              autoSize={{ minRows: 3, maxRows: 5 }}
              data-testid="workflow-studio-rename-description"
              maxLength={300}
              onChange={(event) => setRenameDescription(event.target.value)}
              placeholder={t("workflows:studioText.descriptionPlaceholder")}
              value={renameDescription}
            />
          </label>
        </div>
      </Modal>
    </section>
  );
}
