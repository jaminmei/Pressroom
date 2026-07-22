import { Collapse, Tag, Typography } from "antd";
import { createElement, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { getCategoryIcon } from "@/components/Icons";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

interface ConfigValueProps {
  value: unknown;
  depth?: number;
}

function ConfigValue({ value, depth = 0 }: ConfigValueProps) {
  if (value === null || value === undefined) {
    return <Typography.Text type="secondary">—</Typography.Text>;
  }

  if (typeof value === "boolean") {
    return <Tag color={value ? "green" : "default"}>{value ? "true" : "false"}</Tag>;
  }

  if (typeof value === "number") {
    return <Typography.Text code>{value}</Typography.Text>;
  }

  if (typeof value === "string") {
    if (value.length > 60) {
      return (
        <Typography.Text code ellipsis={{ tooltip: value }}>
          {value}
        </Typography.Text>
      );
    }
    return <Typography.Text code>{value}</Typography.Text>;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <Typography.Text type="secondary">[]</Typography.Text>;
    }
    return (
      <div className="end-config-array" style={{ marginLeft: depth > 0 ? 12 : 0 }}>
        {value.map((item, index) => (
          <div key={index} className="end-config-array-item">
            <ConfigValue value={item} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) {
      return <Typography.Text type="secondary">{"{}"}</Typography.Text>;
    }
    return (
      <div className="end-config-object" style={{ marginLeft: depth > 0 ? 12 : 0 }}>
        {entries.map(([key, val]) => (
          <div key={key} className="end-config-entry">
            <span className="end-config-key">{key}:</span>
            <ConfigValue value={val} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }

  return <Typography.Text>{String(value)}</Typography.Text>;
}

function getCategoryColor(nodeType: string): string {
  if (nodeType.startsWith("input/")) return "blue";
  if (nodeType.startsWith("processor/")) return "purple";
  if (nodeType.startsWith("engine/")) return "orange";
  return "default";
}

function renderNodeIcon(nodeType: string) {
  const category = nodeType.split("/")[0];
  return createElement(getCategoryIcon(category), { size: 18 });
}

/**
 * Get all upstream nodes in topological order (from source to end)
 */
function getUpstreamNodes(endNodeId: string, nodes: WorkflowNode[], edges: WorkflowEdge[]): WorkflowNode[] {
  const nodeMap = new Map(nodes.map((n) => [n.id, n]));
  const visited = new Set<string>();
  const result: WorkflowNode[] = [];

  // Build reverse adjacency (target -> sources)
  const reverseAdj = new Map<string, string[]>();
  edges.forEach((edge) => {
    const sources = reverseAdj.get(edge.target) ?? [];
    sources.push(edge.source);
    reverseAdj.set(edge.target, sources);
  });

  // DFS to collect upstream nodes
  function dfs(nodeId: string) {
    if (visited.has(nodeId)) return;
    visited.add(nodeId);

    const sources = reverseAdj.get(nodeId) ?? [];
    for (const sourceId of sources) {
      dfs(sourceId);
    }

    const node = nodeMap.get(nodeId);
    if (node && nodeId !== endNodeId) {
      result.push(node);
    }
  }

  dfs(endNodeId);
  return result;
}

export default function EndNodeConfigTab() {
  const { t } = useTranslation("workflows");
  const nodes = useWorkflowStore((state) => state.nodes);
  const edges = useWorkflowStore((state) => state.edges);
  const selectedNodeId = useWorkflowStore((state) => state.selectedNodeId);
  const nodeConfigs = useWorkflowStore((state) => state.nodeConfigs);

  const upstreamNodes = useMemo(() => {
    if (!selectedNodeId) return [];
    return getUpstreamNodes(selectedNodeId, nodes, edges);
  }, [selectedNodeId, nodes, edges]);

  if (upstreamNodes.length === 0) {
    return (
      <div className="end-config-empty">
        <Typography.Text type="secondary">{t("editorText.noUpstream")}</Typography.Text>
      </div>
    );
  }

  const collapseItems = upstreamNodes.map((node) => {
    const config = nodeConfigs[node.id] ?? node.data.config ?? {};
    const hasConfig = Object.keys(config).length > 0;

    return {
      key: node.id,
      label: (
        <div className="end-config-node-header-inline">
          <span className="end-config-node-icon">{renderNodeIcon(node.type)}</span>
          <span className="end-config-node-name">{node.data?.label ?? node.id}</span>
          <Tag color={getCategoryColor(node.type)} style={{ marginLeft: 8 }}>
            {node.type.split("/")[0]}
          </Tag>
        </div>
      ),
      children: hasConfig ? (
        <div className="end-config-node-body">
          <ConfigValue value={config} />
        </div>
      ) : (
        <Typography.Text type="secondary">{t("editorText.noConfiguration")}</Typography.Text>
      )
    };
  });

  return (
    <div className="end-config-tab" data-testid="end-node-config-tab">
      <div className="end-config-header">
        <Typography.Text strong>{t("editorText.pipelineOverview")}</Typography.Text>
        <Typography.Text type="secondary">{upstreamNodes.length} nodes</Typography.Text>
      </div>
      <Collapse
        defaultActiveKey={upstreamNodes.slice(0, 3).map((n) => n.id)}
        items={collapseItems}
        size="small"
      />
    </div>
  );
}
