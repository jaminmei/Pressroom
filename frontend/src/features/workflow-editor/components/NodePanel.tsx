import { CloseOutlined } from "@ant-design/icons";
import { Tabs } from "antd";
import { useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";

import ConfigPanel from "@/features/workflow-editor/components/ConfigPanel";
import EndNodeCompareTab from "@/features/workflow-editor/components/EndNodeCompareTab";
import EndNodeConfigTab from "@/features/workflow-editor/components/EndNodeConfigTab";
import EndNodeHistoryTab from "@/features/workflow-editor/components/EndNodeHistoryTab";
import EndNodeRunTab from "@/features/workflow-editor/components/EndNodeRunTab";
import NodeResultTab from "@/features/workflow-editor/components/NodeResultTab";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { isEndNodeType } from "@/features/workflow-editor/utils/endNodeRepair";
import { useUIStore } from "@/stores/uiStore";

interface NodePanelProps {
  onCancelTask?: () => Promise<void>;
  readOnlyTrace?: boolean;
}

export default function NodePanel({ onCancelTask, readOnlyTrace = false }: NodePanelProps) {
  const { t } = useTranslation("workflows");
  const nodePanelVisible = useUIStore((state) => state.nodePanelVisible);
  const closeNodePanel = useUIStore((state) => state.closeNodePanel);
  const rightPanelTab = useUIStore((state) => state.rightPanelTab);
  const setRightPanelTab = useUIStore((state) => state.setRightPanelTab);

  const selectedNodeId = useWorkflowStore((state) => state.selectedNodeId);
  const selectedNode = useWorkflowStore(
    (state) => state.nodes.find((node) => node.id === state.selectedNodeId) ?? null
  );
  const selectedNodeType = selectedNode?.type ?? null;

  const isEndNode = selectedNodeType ? isEndNodeType(selectedNodeType) : false;

  // Auto-switch tab when selecting a node
  useEffect(() => {
    if (!selectedNodeId) {
      return;
    }
    setRightPanelTab(readOnlyTrace ? "result" : isEndNode ? "compare" : "config");
  }, [selectedNodeId, isEndNode, readOnlyTrace, setRightPanelTab]);

  // Close panel on Esc
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === "Escape" && nodePanelVisible) {
        // If antd Image preview is open, let antd handle Escape first
        if (document.querySelector(".ant-image-preview-wrap")) {
          return;
        }
        closeNodePanel();
      }
    },
    [nodePanelVisible, closeNodePanel]
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  if (!nodePanelVisible || !selectedNodeId || !selectedNode) {
    return null;
  }

  const nodeLabel = selectedNode.data?.label ?? selectedNodeType ?? t("editorText.node");

  const buildTabItems = () => {
    const resultTab = {
      key: "result",
      label: t("result"),
      children: <NodeResultTab nodeId={selectedNodeId} />
    };

    if (readOnlyTrace) {
      if (isEndNode) {
        return [
          resultTab,
          {
            key: "compare",
            label: t("compare"),
            children: <EndNodeCompareTab />
          },
          {
            key: "history",
            label: t("history"),
            children: <EndNodeHistoryTab />
          }
        ];
      }

      return [resultTab];
    }

    // Regular node tabs
    const configTab = {
      key: "config",
      label: t("configuration"),
      children: <ConfigPanel />
    };

    // End Node has 4 specialized tabs
    if (isEndNode) {
      return [
        {
          key: "config",
          label: t("configuration"),
          children: <EndNodeConfigTab />
        },
        {
          key: "run",
          label: t("run"),
          children: <EndNodeRunTab onCancelTask={onCancelTask} />
        },
        {
          key: "compare",
          label: t("compare"),
          children: <EndNodeCompareTab />
        },
        {
          key: "history",
          label: t("history"),
          children: <EndNodeHistoryTab />
        }
      ];
    }

    return [configTab, resultTab];
  };

  return (
    <div className="node-panel-floating" data-testid="node-panel-floating">
      <div className="node-panel-header">
        <div className="node-panel-header-info">
          <span className="node-panel-header-label">{nodeLabel}</span>
          {selectedNodeType && (
            <span className="node-panel-header-type">{selectedNodeType}</span>
          )}
        </div>
        <button
          aria-label={t("editorText.closePanel")}
          className="node-panel-close"
          data-testid="node-panel-close"
          onClick={closeNodePanel}
          type="button"
        >
          <CloseOutlined />
        </button>
      </div>

      <div className="node-panel-body">
        <Tabs
          activeKey={rightPanelTab}
          className="node-panel-tabs"
          data-testid="node-panel-tabs"
          items={buildTabItems()}
          onChange={(key) => setRightPanelTab(key as "config" | "result" | "run" | "compare" | "history")}
        />
      </div>
    </div>
  );
}
