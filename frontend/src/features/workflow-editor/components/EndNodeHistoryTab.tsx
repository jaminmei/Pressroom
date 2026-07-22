import { Button, Empty, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useTaskExecutionStore } from "@/features/task-execution/store";
import type { TaskNodeVisualStatus } from "@/features/task-execution/store";
import { useLiveStatusStore } from "@/features/task-execution/liveStatusStore";
import { useUIStore } from "@/stores/uiStore";
import { getTaskHistory, getTaskResults, getTaskStatus } from "@/services/taskApi";
import type { TaskHistoryItem } from "@/types/task";
import { useResultStore } from "@/features/result/store";
import { formatRelativeTime } from "@/utils/dateFormat";
import { mapNodeVisualStatus } from "@/utils/nodeStatus";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { computeDagFingerprint } from "@/utils/dagFingerprint";
import { captureWorkspaceContext, isWorkspaceContextCurrent } from "@/stores/workspaceStore";

const STATUS_COLORS: Record<string, string> = {
  completed: "#389e0d",
  failed: "#cf1322",
  running: "#7132f5",
  cancelled: "#8c8c8c",
  pending: "#7132f5"
};

interface EndNodeHistoryTabProps {
  isActive?: boolean;
  onViewRun?: (taskId: string) => void;
}

export default function EndNodeHistoryTab({ onViewRun }: EndNodeHistoryTabProps) {
  const { t } = useTranslation("workflows");
  const [runs, setRuns] = useState<TaskHistoryItem[]>([]);
  const [hydratingTaskId, setHydratingTaskId] = useState<string | null>(null);
  const setRightPanelTab = useUIStore((state) => state.setRightPanelTab);
  const setTaskResults = useResultStore((state) => state.setTaskResults);

  // Get task execution store actions
  const setTaskId = useTaskExecutionStore((state) => state.setTaskId);
  const setTaskStatus = useTaskExecutionStore((state) => state.setTaskStatus);
  const setProgress = useTaskExecutionStore((state) => state.setProgress);
  const batchUpdateNodeStatuses = useTaskExecutionStore((state) => state.batchUpdateNodeStatuses);
  const setLastRunMeta = useTaskExecutionStore((state) => state.setLastRunMeta);

  // Re-fetch whenever the History tab becomes active
  const rightPanelTab = useUIStore((state) => state.rightPanelTab);
  useEffect(() => {
    if (rightPanelTab !== "history") return;
    let mounted = true;
    const workspaceToken = captureWorkspaceContext();
    void getTaskHistory({ page: 1, limit: 20 }).then((response) => {
      if (!mounted || !isWorkspaceContextCurrent(workspaceToken)) return;
      setRuns(response.items);
    });
    return () => { mounted = false; };
  }, [rightPanelTab]);

  // Patch items in-place on live WebSocket status updates
  const liveUpdates = useLiveStatusStore((state) => state.updates);
  useEffect(() => {
    if (Object.keys(liveUpdates).length === 0) return;
    setRuns((prev) => {
      let changed = false;
      const next = prev.map((item) => {
        const liveStatus = liveUpdates[item.task_id];
        if (liveStatus && liveStatus !== item.status) {
          changed = true;
          return { ...item, status: liveStatus };
        }
        return item;
      });
      return changed ? next : prev;
    });
  }, [liveUpdates]);

  const hydrateTaskContext = useCallback(
    async (taskId: string) => {
      const workspaceToken = captureWorkspaceContext();
      setHydratingTaskId(taskId);
      try {
        const [statusResponse, resultsResponse] = await Promise.all([
          getTaskStatus(taskId),
          getTaskResults(taskId)
        ]);
        if (
          !isWorkspaceContextCurrent(workspaceToken) ||
          statusResponse.task_id !== taskId ||
          resultsResponse.task_id !== taskId
        ) return;

        const nodeStates = Array.isArray(statusResponse.node_status)
          ? statusResponse.node_status
          : statusResponse.node_states
            ? Object.values(statusResponse.node_states)
            : [];

        const statusPatch: Record<string, TaskNodeVisualStatus> = {};
        nodeStates.forEach((node) => {
          const mappedStatus = mapNodeVisualStatus(node.status);
          if (!mappedStatus) return;
          statusPatch[node.node_id] = mappedStatus;
        });

        useTaskExecutionStore.setState((state) => ({
          ...state,
          nodeStatuses: {},
          nodeProgress: {},
          nodeErrors: {}
        }));

        setTaskId(statusResponse.task_id);
        setTaskStatus(statusResponse.status);
        setProgress(statusResponse.progress ?? null);
        batchUpdateNodeStatuses(statusPatch);

        // Restore workflow definition into editor if available
        const wf = statusResponse.workflow;
        if (wf && wf.nodes && wf.connections) {
          const { nodeRegistry } = useWorkflowStore.getState();
          const restoredNodes = wf.nodes.map((n: Record<string, unknown>) => {
            const nodeType = String(n.type ?? "");
            const parts = nodeType.split("/");
            const metadata = nodeRegistry.nodes.find((rn) => rn.node_type === nodeType);
            const defaultLabel = (parts[parts.length - 1] ?? nodeType).toUpperCase();
            const pos = n.position as { x?: number; y?: number } | undefined;
            return {
              id: String(n.id),
              type: nodeType,
              data: {
                label: metadata?.display_name ?? defaultLabel,
                config: (n.config as Record<string, unknown>) ?? {},
                configSchema: metadata?.config_schema ?? { type: "object", properties: {} },
                inputTypes: metadata?.input_types,
                outputTypes: metadata?.output_types,
                maxInputs: metadata?.max_inputs,
                inputPorts: metadata?.input_ports,
              },
              position: pos && typeof pos.x === "number" && typeof pos.y === "number"
                ? { x: pos.x, y: pos.y }
                : undefined,
            };
          });
          const restoredEdges = wf.connections.map((c: Record<string, unknown>) => ({
            id: `e-${c.source}-${c.target}`,
            source: String(c.source),
            target: String(c.target),
            sourceHandle: c.source_port ? `output-${c.source_port}` : undefined,
            targetHandle: c.target_port ? `input-${c.target_port}` : undefined,
          }));
          const restoredConfigs: Record<string, Record<string, unknown>> = {};
          wf.nodes.forEach((n: Record<string, unknown>) => {
            restoredConfigs[String(n.id)] = (n.config as Record<string, unknown>) ?? {};
          });

          // Atomically increment canvas key and set new data
          // React Flow sees new key → remounts → receives fresh nodes/edges
          useWorkflowStore.setState((s) => ({
            canvasResetKey: s.canvasResetKey + 1,
            nodes: restoredNodes,
            edges: restoredEdges,
            nodeConfigs: restoredConfigs,
            uploadedFiles: {},
          }));

          const dagFp = computeDagFingerprint(
            restoredNodes.map((n) => ({ id: n.id, type: n.type })),
            restoredEdges.map((e) => ({ source: e.source, target: e.target, sourceHandle: e.sourceHandle, targetHandle: e.targetHandle })),
            restoredConfigs
          );
          setLastRunMeta(dagFp, statusResponse.input_files ?? null);
        }

        setTaskResults(resultsResponse.task_id, resultsResponse.results);

        // Switch to compare tab after loading
        setRightPanelTab("compare");
        onViewRun?.(taskId);
      } catch {
        // Preserve the current view without writing request details to the console.
      } finally {
        if (isWorkspaceContextCurrent(workspaceToken)) {
          setHydratingTaskId((current) => (current === taskId ? null : current));
        }
      }
    },
    [batchUpdateNodeStatuses, setLastRunMeta, setProgress, setRightPanelTab, setTaskId, setTaskResults, setTaskStatus, onViewRun]
  );

  return (
    <div className="end-history-tab" data-testid="end-node-history-tab">
      <div className="end-history-header">
        <Typography.Text strong>{t("editorText.recentRuns")}</Typography.Text>
        <Typography.Text type="secondary">{runs.length} runs</Typography.Text>
      </div>

      <div className="end-history-list">
        {runs.length === 0 ? (
          <Empty description={t("noRecentRuns")} image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          runs.map((run) => {
            const statusColor = STATUS_COLORS[run.status] ?? STATUS_COLORS.pending;
            const displayName = run.run_name ?? run.workflow_name ?? run.task_id.slice(5, 13);
                const secondaryInfo = run.run_name ? run.task_id.slice(5, 13) : "";

                return (
              <div
                className={`end-history-item ${hydratingTaskId === run.task_id ? "is-loading" : ""}`}
                key={run.task_id}
              >
                <div className="end-history-item-left">
                  <span
                    className="end-history-status"
                    style={{ backgroundColor: statusColor }}
                    title={run.status}
                  />
                  <span className="end-history-name">{displayName}</span>
                </div>
                <div className="end-history-item-right">
                  <span className="end-history-time">{secondaryInfo ? `${secondaryInfo} · ` : ""}{formatRelativeTime(run.started_at)}</span>
                  <Button
                    size="small"
                    loading={hydratingTaskId === run.task_id}
                    onClick={() => {
                      void hydrateTaskContext(run.task_id);
                    }}
                  >
                    View
                  </Button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
