import { Input } from "antd";
import { createElement, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { getCategoryIcon } from "@/components/Icons";
import type { NodeRegistryNode } from "@/types/node-registry";

interface WorkflowNodePickerProps {
  nodes: NodeRegistryNode[];
  hint: string;
  onSelect: (nodeType: string) => void;
  emptyText?: string;
  searchPlaceholder?: string;
  title?: string;
}

function normalizeKeyword(keyword: string): string {
  return keyword.trim().toLowerCase();
}

function resolveCategoryLabel(category: string): string {
  switch (category) {
    case "input":
      return "INPUT";
    case "processor":
      return "PROCESS";
    case "engine":
      return "ENGINE";
    case "end":
      return "END";
    default:
      return category.toUpperCase();
  }
}

export default function WorkflowNodePicker({
  nodes,
  hint,
  onSelect,
  emptyText,
  searchPlaceholder,
  title
}: WorkflowNodePickerProps) {
  const { t } = useTranslation("workflows");
  const resolvedEmptyText = emptyText ?? t("editorText.noCompatibleNodes");
  const resolvedSearchPlaceholder = searchPlaceholder ?? t("editorText.searchNodes");
  const resolvedTitle = title ?? t("editorText.compatibleNodes");
  const [searchKeyword, setSearchKeyword] = useState("");

  const filteredNodes = useMemo(() => {
    const keyword = normalizeKeyword(searchKeyword);
    if (!keyword) {
      return nodes;
    }

    return nodes.filter((node) => {
      const displayName = node.display_name.toLowerCase();
      const nodeTypeName = node.node_type.toLowerCase();
      return displayName.includes(keyword) || nodeTypeName.includes(keyword);
    });
  }, [nodes, searchKeyword]);

  return (
    <div
      className="workflow-node-endpoint-menu nodrag nopan"
      onMouseDown={(event) => event.stopPropagation()}
    >
      <div className="workflow-node-endpoint-menu-header">
        <div className="workflow-node-endpoint-menu-title">{resolvedTitle}</div>
        <div className="workflow-node-endpoint-menu-hint">{hint}</div>
      </div>
      <Input
        autoFocus
        placeholder={resolvedSearchPlaceholder}
        size="small"
        value={searchKeyword}
        onChange={(event) => setSearchKeyword(event.target.value)}
        onKeyDown={(event) => event.stopPropagation()}
      />
      <div className="workflow-node-endpoint-menu-list">
        {filteredNodes.length === 0 ? (
          <div className="workflow-node-endpoint-menu-empty">{resolvedEmptyText}</div>
        ) : (
          filteredNodes.map((node) => (
            <button
              className="workflow-node-endpoint-menu-item"
              key={node.node_type}
              onClick={() => onSelect(node.node_type)}
              type="button"
            >
              <div className="workflow-node-endpoint-menu-item-topline">
                <span className={`workflow-node-endpoint-menu-item-category is-${node.category}`}>
                  {resolveCategoryLabel(node.category)}
                </span>
                <code>{node.node_type}</code>
              </div>
              <div className="workflow-node-endpoint-menu-item-name">
                <span aria-hidden className="workflow-node-endpoint-menu-item-icon">
                  {createElement(getCategoryIcon(node.category), { size: 22 })}
                </span>
                <span>{node.display_name}</span>
              </div>
              <div className="workflow-node-endpoint-menu-item-description">
                {node.description ?? t("editorText.addNodeFallback")}
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
