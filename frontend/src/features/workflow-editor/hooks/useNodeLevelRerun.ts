import { message } from "antd";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { useResultStore } from "@/features/result/store";
import {
  beginTaskOperation,
  finishTaskOperation,
  isTaskOperationCurrent,
  useTaskExecutionStore,
  type TaskNodeVisualStatus
} from "@/features/task-execution/store";
import { getTaskResults, getTaskStatus, rerunNode } from "@/services/taskApi";
import { mapNodeVisualStatus } from "@/utils/nodeStatus";

import type { TaskStatus } from "@/types/task";
import { captureWorkspaceContext, isWorkspaceContextCurrent } from "@/stores/workspaceStore";

interface UseNodeLevelRerunResult {
  rerunNodeById: (nodeId: string) => Promise<void>;
}

const terminalStatuses = new Set<TaskStatus>(["completed", "failed", "cancelled"]);

export function useNodeLevelRerun(): UseNodeLevelRerunResult {
  const { t } = useTranslation(["workflows", "common"]);
  const appendEventLog = useTaskExecutionStore((state) => state.appendEventLog);
  const setTaskStatus = useTaskExecutionStore((state) => state.setTaskStatus);
  const setTaskResults = useResultStore((state) => state.setTaskResults);

  const rerunNodeById = useCallback(
    async (nodeId: string) => {
      const currentTaskId = useTaskExecutionStore.getState().currentTaskId;
      if (!currentTaskId) return;
      const workspaceToken = captureWorkspaceContext();
      const operationId = beginTaskOperation();
      const isCurrentOperation = () =>
        isWorkspaceContextCurrent(workspaceToken) &&
        isTaskOperationCurrent(operationId) &&
        useTaskExecutionStore.getState().currentTaskId === currentTaskId;

      try {
        const result = await rerunNode(currentTaskId, nodeId);
        if (!isCurrentOperation()) return;
        appendEventLog(
          t("editorText.nodeRerunning", { nodeId, nodes: result.rerun_nodes.join(", ") })
        );

        for (let i = 0; i < 30; i++) {
          await new Promise((r) => setTimeout(r, 1000));
          if (!isCurrentOperation()) return;
          const snapshot = await getTaskStatus(currentTaskId);
          if (!isCurrentOperation()) return;

          if (snapshot.progress) {
            useTaskExecutionStore.getState().setProgress(snapshot.progress);
          }
          const nodeStatuses = Array.isArray(snapshot.node_status)
            ? snapshot.node_status
            : snapshot.node_states
              ? Object.values(snapshot.node_states)
              : [];
          if (nodeStatuses.length > 0) {
            const statusPatch: Record<string, TaskNodeVisualStatus> = {};
            nodeStatuses.forEach((node) => {
              const mapped = mapNodeVisualStatus(node.status);
              if (mapped) {
                statusPatch[node.node_id] = mapped;
              }
            });
            useTaskExecutionStore.getState().batchUpdateNodeStatuses(statusPatch);
          }

          if (terminalStatuses.has(snapshot.status as TaskStatus)) {
            setTaskStatus(snapshot.status);
            appendEventLog(
              t("editorText.nodeRerunFinished", { taskId: currentTaskId, status: t(`common:statuses.${snapshot.status}`, { defaultValue: snapshot.status }) }),
              snapshot.status === "failed" ? "error" : "info"
            );
            if (snapshot.status === "completed") {
              try {
                const results = await getTaskResults(currentTaskId);
                if (!isCurrentOperation() || results.task_id !== currentTaskId) return;
                setTaskResults(results.task_id, results.results);
                appendEventLog(t("editorText.resultLoaded"));
              } catch {
                appendEventLog(t("editorText.resultLoadFailed"), "error");
              }
            }
            finishTaskOperation(operationId);
            break;
          }
        }
        if (isCurrentOperation()) finishTaskOperation(operationId);
      } catch {
        if (isCurrentOperation()) {
          finishTaskOperation(operationId);
          message.error(t("editorText.nodeRerunFailed"));
        }
      }
    },
    [appendEventLog, setTaskStatus, setTaskResults, t]
  );

  return { rerunNodeById };
}
