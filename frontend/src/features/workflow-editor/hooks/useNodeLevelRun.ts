import { message } from "antd";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { useResultStore } from "@/features/result/store";
import {
  beginTaskOperation,
  finishTaskOperation,
  isTaskOperationCurrent,
  useTaskExecutionStore
} from "@/features/task-execution/store";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { buildWorkflowExecutionPayload, getDirectPredecessors } from "@/features/workflow-editor/utils/workflowBuilder";
import { getTaskResults } from "@/services/taskApi";
import { buildNodeRunTaskFormData, createNodeRunTask } from "@/services/workflowApi";
import { useUIStore } from "@/stores/uiStore";
import type { TaskStatus } from "@/types/task";
import { captureWorkspaceContext, isWorkspaceContextCurrent } from "@/stores/workspaceStore";

interface UseNodeLevelRunResult {
  runNode: (nodeId: string) => Promise<boolean>;
}

const terminalStatuses = new Set<TaskStatus>(["completed", "failed", "cancelled"]);

export function useNodeLevelRun(): UseNodeLevelRunResult {
  const { t } = useTranslation(["workflows", "common"]);
  const nodes = useWorkflowStore((state) => state.nodes);
  const edges = useWorkflowStore((state) => state.edges);
  const nodeConfigs = useWorkflowStore((state) => state.nodeConfigs);
  const uploadedFiles = useWorkflowStore((state) => state.uploadedFiles);

  const setTaskId = useTaskExecutionStore((state) => state.setTaskId);
  const setTaskStatus = useTaskExecutionStore((state) => state.setTaskStatus);
  const setProgress = useTaskExecutionStore((state) => state.setProgress);
  const updateNodeStatus = useTaskExecutionStore((state) => state.updateNodeStatus);
  const clearEventLogs = useTaskExecutionStore((state) => state.clearEventLogs);
  const appendEventLog = useTaskExecutionStore((state) => state.appendEventLog);
  const setTaskResults = useResultStore((state) => state.setTaskResults);
  const setRightPanelTab = useUIStore((state) => state.setRightPanelTab);

  const runNode = useCallback(
    async (nodeId: string) => {
      const node = nodes.find((item) => item.id === nodeId);
      if (!node) {
        return false;
      }

      // end/final nodes cannot be run individually
      if (node.type === "end/final") {
        message.warning(t("editorText.endNodeRunUnsupported"));
        return false;
      }
      if (node.type.startsWith("output/")) {
        message.warning(t("editorText.outputNodeRunUnsupported"));
        return false;
      }

      // Check if all predecessors are completed (for non-input nodes)
      const predecessorIds = getDirectPredecessors(nodeId, edges);
      if (predecessorIds.length > 0) {
        const nodeStatuses = useTaskExecutionStore.getState().nodeStatuses;
        const allPredecessorsCompleted = predecessorIds.every(
          (predId) => nodeStatuses[predId] === "completed"
        );
        if (!allPredecessorsCompleted) {
          message.warning(t("editorText.predecessorsIncomplete"));
          return false;
        }
      }

      const { workflow, orderedFiles } = buildWorkflowExecutionPayload({
        nodes,
        edges,
        nodeConfigs,
        uploadedFiles
      });

      // All nodes need at least one file to run
      if (orderedFiles.length === 0) {
        message.warning(t("editorText.uploadBeforeNodeRun"));
        return false;
      }

      const formData = buildNodeRunTaskFormData(workflow, nodeId, orderedFiles, "markdown");
      const workspaceToken = captureWorkspaceContext();
      const operationId = beginTaskOperation();
      const isCurrentOperation = () =>
        isWorkspaceContextCurrent(workspaceToken) && isTaskOperationCurrent(operationId);
      setRightPanelTab("run");
      clearEventLogs();
      appendEventLog(t("editorText.nodeRunStarted", { nodeId }));
      setTaskStatus("pending");
      setProgress({
        total_nodes: 1,
        completed_nodes: 0,
        failed_nodes: 0,
        pending_nodes: 1,
        current_node: nodeId,
        percentage: 0
      });
      updateNodeStatus(nodeId, "pending");

      try {
        const response = await createNodeRunTask(formData);
        if (!isCurrentOperation()) return false;
        setTaskId(response.task_id);
        setTaskStatus(response.status as TaskStatus);
        appendEventLog(t("editorText.nodeTaskCreated", { taskId: response.task_id, status: t(`common:statuses.${response.status}`, { defaultValue: response.status }) }));

        if (terminalStatuses.has(response.status as TaskStatus)) {
          try {
            const taskResults = await getTaskResults(response.task_id);
            if (
              !isCurrentOperation() ||
              useTaskExecutionStore.getState().currentTaskId !== response.task_id
            ) return false;
            if (taskResults?.task_id === response.task_id) {
              setTaskResults(taskResults.task_id, taskResults.results);
            } else {
              appendEventLog(t("editorText.nodeResultTaskMismatch"), "error");
            }
          } catch {
            if (isCurrentOperation()) appendEventLog(t("editorText.nodeResultLoadFailed"), "error");
          } finally {
            if (isCurrentOperation()) finishTaskOperation(operationId);
          }
        }
        return true;
      } catch {
        if (!isCurrentOperation()) return false;
        setTaskStatus("failed");
        updateNodeStatus(nodeId, "failed", t("editorText.nodeRunFailedRetry"));
        appendEventLog(t("editorText.nodeRunFailed"), "error");
        message.error(t("editorText.nodeRunFailed"));
        finishTaskOperation(operationId);
        return false;
      }
    },
    [
      clearEventLogs,
      edges,
      nodeConfigs,
      nodes,
      appendEventLog,
      setProgress,
      setRightPanelTab,
      setTaskId,
      setTaskResults,
      setTaskStatus,
      updateNodeStatus,
      uploadedFiles,
      t
    ]
  );

  return { runNode };
}
