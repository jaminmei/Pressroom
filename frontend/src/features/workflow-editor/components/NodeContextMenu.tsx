import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { useTaskExecutionStore } from "@/features/task-execution/store";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { workflowUnchangedSinceLastRun } from "@/utils/dagFingerprint";

interface NodeContextMenuProps {
  nodeId: string;
  x: number;
  y: number;
  onClose: () => void;
}

const activeStatuses = new Set(["pending", "running"]);

export default function NodeContextMenu({ nodeId, x, y, onClose }: NodeContextMenuProps) {
  const { t } = useTranslation(["workflows", "common"]);
  const removeNode = useWorkflowStore((state) => state.removeNode);
  const duplicateNode = useWorkflowStore((state) => state.duplicateNode);
  const nodes = useWorkflowStore((state) => state.nodes);
  const currentTaskId = useTaskExecutionStore((state) => state.currentTaskId);
  const taskStatus = useTaskExecutionStore((state) => state.taskStatus);
  const nodeStatuses = useTaskExecutionStore((state) => state.nodeStatuses);
  const lastRunDagFingerprint = useTaskExecutionStore((state) => state.lastRunDagFingerprint);
  const lastRunInputFiles = useTaskExecutionStore((state) => state.lastRunInputFiles);
  const edges = useWorkflowStore((state) => state.edges);
  const nodeConfigs = useWorkflowStore((state) => state.nodeConfigs);
  const uploadedFiles = useWorkflowStore((state) => state.uploadedFiles);
  const nodeType = nodes.find((n) => n.id === nodeId)?.type;
  const nodeRanInLastTask = nodeId in nodeStatuses;

  useEffect(() => {
    const onKeydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeydown);
    return () => window.removeEventListener("keydown", onKeydown);
  }, [onClose]);

  const runNode = () => {
    window.dispatchEvent(
      new CustomEvent("workflow:node-run-request", {
        detail: { nodeId }
      })
    );
    onClose();
  };

  const rerunNodeAction = () => {
    window.dispatchEvent(
      new CustomEvent("workflow:node-rerun-request", {
        detail: { nodeId }
      })
    );
    onClose();
  };

  const showRerun =
    currentTaskId != null &&
    !activeStatuses.has(taskStatus) &&
    nodeType != null &&
    !nodeType.startsWith("input/") &&
    nodeType !== "end/final" &&
    workflowUnchangedSinceLastRun(nodes, edges, nodeConfigs, uploadedFiles, lastRunDagFingerprint, lastRunInputFiles);

  const duplicate = () => {
    duplicateNode(nodeId);
    onClose();
  };

  const remove = () => {
    removeNode(nodeId);
    onClose();
  };

  return (
    <div
      className="node-context-menu"
      data-testid="node-context-menu"
      onMouseLeave={onClose}
      style={{ left: x, top: y }}
    >
      <button onClick={runNode} type="button">
        {t("workflows:run")}
      </button>
      {showRerun ? (
        <button
          onClick={nodeRanInLastTask ? rerunNodeAction : undefined}
          disabled={!nodeRanInLastTask}
          title={nodeRanInLastTask ? undefined : t("workflows:editorText.rerunUnavailable")}
          type="button"
        >
          {t("workflows:editorText.rerun")}
        </button>
      ) : null}
      <button onClick={duplicate} type="button">
        {t("workflows:editorText.duplicate")}
      </button>
      <button onClick={remove} type="button">
        {t("common:delete")}
      </button>
    </div>
  );
}
