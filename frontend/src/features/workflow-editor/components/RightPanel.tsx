import { Tabs } from "antd";
import { lazy, Suspense, useEffect } from "react";
import { useTranslation } from "react-i18next";

import ConfigPanel from "@/features/workflow-editor/components/ConfigPanel";
import { useWorkflowPersistence } from "@/features/workflow-editor/hooks/useWorkflowPersistence";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { isEndNodeType } from "@/features/workflow-editor/utils/endNodeRepair";
import { useUIStore } from "@/stores/uiStore";

const RunPanel = lazy(() => import("@/features/workflow-editor/components/RunPanel"));
const ComparePanel = lazy(() => import("@/features/workflow-editor/components/ComparePanel"));
const HistoryPanel = lazy(() => import("@/features/workflow-editor/components/HistoryPanel"));

interface RightPanelProps {
  onCancelTask?: () => Promise<void>;
}

function PanelTabLoadingFallback() {
  const { t } = useTranslation("workflows");
  return (
    <div
      aria-live="polite"
      className="right-panel-tab-loading"
      data-testid="right-panel-tab-loading"
      style={{ minHeight: 200, display: "grid", placeItems: "center" }}
    >
      <span>{t("editorText.loadingPanel")}</span>
    </div>
  );
}

export default function RightPanel({ onCancelTask }: RightPanelProps) {
  const { t } = useTranslation("workflows");
  const selectedNodeId = useWorkflowStore((state) => state.selectedNodeId);
  const selectedNodeType = useWorkflowStore(
    (state) => state.nodes.find((node) => node.id === state.selectedNodeId)?.type ?? null
  );
  const rightPanelTab = useUIStore((state) => state.rightPanelTab);
  const setRightPanelTab = useUIStore((state) => state.setRightPanelTab);
  const { restoreVersion } = useWorkflowPersistence();
  const panelCopy = {
    config: ["editorText.inspector", "editorText.nodeConfiguration", "editorText.nodeConfigurationDescription"],
    result: ["result", "editorText.nodeResult", "editorText.nodeResultDescription"],
    run: ["editorText.monitor", "editorText.executionRunbook", "editorText.executionRunbookDescription"],
    compare: ["editorText.review", "editorText.resultCompare", "editorText.resultCompareDescription"],
    history: ["editorText.timeline", "editorText.runHistory", "editorText.historyDescription"]
  }[rightPanelTab];

  useEffect(() => {
    if (!selectedNodeId) {
      return;
    }
    setRightPanelTab(selectedNodeType && isEndNodeType(selectedNodeType) ? "compare" : "config");
  }, [selectedNodeId, selectedNodeType, setRightPanelTab]);

  return (
    <div className="right-panel-shell">
      <div className="right-panel-shell-header">
        <span className="right-panel-shell-eyebrow">{t(panelCopy[0])}</span>
        <div className="right-panel-shell-title">{t(panelCopy[1])}</div>
        <div className="right-panel-shell-description">{t(panelCopy[2])}</div>
      </div>

      <Tabs
        activeKey={rightPanelTab}
        className="workflow-right-panel-tabs"
        data-testid="right-panel-tabs"
        items={[
          {
            key: "config",
            label: t("configuration"),
            children: <ConfigPanel />
          },
          {
            key: "run",
            label: t("run"),
            children: (
              <Suspense fallback={<PanelTabLoadingFallback />}>
                <RunPanel onCancelTask={onCancelTask} />
              </Suspense>
            )
          },
          {
            key: "compare",
            label: t("compare"),
            children: (
              <Suspense fallback={<PanelTabLoadingFallback />}>
                <ComparePanel />
              </Suspense>
            )
          },
          {
            key: "history",
            label: t("history"),
            children: (
              <Suspense fallback={<PanelTabLoadingFallback />}>
                <HistoryPanel onRestoreVersion={restoreVersion} />
              </Suspense>
            )
          }
        ]}
        onChange={(key) => setRightPanelTab(key as "config" | "result" | "run" | "compare" | "history")}
      />
    </div>
  );
}
