import { Input, Spin, Typography } from "antd";
import { createElement, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getCategoryIcon } from "@/components/Icons";
import { getNodeRegistry } from "@/services/nodeRegistryApi";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { isSystemManagedNodeType } from "@/features/workflow-editor/utils/endNodeRepair";
import { useUIStore } from "@/stores/uiStore";
import type { NodeRegistryCategory, NodeRegistryNode, NodeRegistryResponse } from "@/types/node-registry";

interface CanvasEntryToolbarProps {
  className?: string;
  label?: string;
}

function resolveCategoryLabel(categoryId: string): string {
  switch (categoryId) {
    case "input":
      return "INPUT";
    case "processor":
      return "PROCESS";
    case "engine":
      return "ENGINE";
    case "end":
      return "END";
    default:
      return categoryId.toUpperCase();
  }
}

function toCategoryGroups(
  categories: NodeRegistryCategory[],
  nodes: NodeRegistryNode[],
  keyword: string
): Array<{ category: NodeRegistryCategory; nodes: NodeRegistryNode[] }> {
  const normalizedKeyword = keyword.trim().toLowerCase();

  return categories
    .map((category) => ({
      category,
      nodes: nodes.filter((node) => {
        if (isSystemManagedNodeType(node.node_type)) {
          return false;
        }

        if (node.category !== category.category_id) {
          return false;
        }

        if (!normalizedKeyword) {
          return true;
        }

        return (
          node.display_name.toLowerCase().includes(normalizedKeyword) ||
          node.node_type.toLowerCase().includes(normalizedKeyword)
        );
      })
    }))
    .filter((group) => group.nodes.length > 0);
}

function nodeItemTestId(nodeType: string): string {
  return `canvas-entry-node-${nodeType.replace(/[\\/]/g, "_")}`;
}

function resolveCanvasEntryPosition(nodeCount: number): { x: number; y: number } {
  const shell = document.querySelector<HTMLElement>(".react-flow-shell");
  const width = shell?.clientWidth ?? 720;
  const height = shell?.clientHeight ?? 520;
  const offset = Math.min(nodeCount * 20, 120);

  return {
    x: Math.max(width / 2 - 100 + offset, 40),
    y: Math.max(height / 2 - 40 + offset / 2, 40)
  };
}

export default function CanvasEntryToolbar({ className, label }: CanvasEntryToolbarProps) {
  const { t } = useTranslation(["common", "workflows"]);
  const addNode = useWorkflowStore((state) => state.addNode);
  const nodes = useWorkflowStore((state) => state.nodes);
  const selectNode = useWorkflowStore((state) => state.selectNode);
  const setNodeRegistry = useWorkflowStore((state) => state.setNodeRegistry);
  const uiSelectNode = useUIStore((state) => state.selectNode);
  const [registry, setRegistry] = useState<NodeRegistryResponse | null>(null);
  const [searchKeyword, setSearchKeyword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function loadRegistry() {
      setIsLoading(true);
      setLoadFailed(false);
      try {
        const nextRegistry = await getNodeRegistry();
        if (!isMounted) {
          return;
        }

        setRegistry(nextRegistry);
        if (useWorkflowStore.getState().nodeRegistry.nodes.length === 0) {
          setNodeRegistry({
            nodes: nextRegistry.nodes,
            connection_rules: nextRegistry.connection_rules
          });
        }
      } catch {
        if (!isMounted) {
          return;
        }

        setRegistry({ version: "", categories: [], nodes: [], connection_rules: [] });
        setLoadFailed(true);
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    void loadRegistry();

    return () => {
      isMounted = false;
    };
  }, [setNodeRegistry]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (rootRef.current?.contains(event.target as Node)) {
        return;
      }
      setOpen(false);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const groups = useMemo(() => {
    if (!registry) {
      return [];
    }

    return toCategoryGroups(registry.categories, registry.nodes, searchKeyword);
  }, [registry, searchKeyword]);

  const handleAddNode = (nodeType: string) => {
    const createdNodeId = addNode(nodeType, resolveCanvasEntryPosition(nodes.length));
    selectNode(createdNodeId);
    uiSelectNode(createdNodeId);
    setOpen(false);
    setSearchKeyword("");
  };

  const handleRetry = async () => {
    setIsLoading(true);
    setLoadFailed(false);
    try {
      const nextRegistry = await getNodeRegistry();
      setRegistry(nextRegistry);
      if (useWorkflowStore.getState().nodeRegistry.nodes.length === 0) {
        setNodeRegistry({
          nodes: nextRegistry.nodes,
          connection_rules: nextRegistry.connection_rules
        });
      }
    } catch {
      setLoadFailed(true);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      className={className ? `canvas-entry-toolbar ${className}` : "canvas-entry-toolbar"}
      data-testid="canvas-entry-toolbar"
      ref={rootRef}
    >
      <button
        aria-expanded={open}
        aria-label={open ? t("workflows:editorText.closeAddNode") : t("workflows:editorText.openAddNode")}
        className="canvas-entry-toolbar-trigger"
        data-testid="canvas-entry-toolbar-trigger"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <span aria-hidden className="canvas-entry-toolbar-trigger-symbol">
          +
        </span>
        {label ? <span className="canvas-entry-toolbar-trigger-label">{label}</span> : null}
      </button>

      {open ? (
        <section className="canvas-entry-toolbar-panel" data-testid="canvas-entry-toolbar-panel">
          <div className="canvas-entry-toolbar-panel-header">
            <Typography.Text strong>{t("workflows:editorText.addNode")}</Typography.Text>
            <Typography.Text type="secondary">{t("workflows:editorText.addNodeDescription")}</Typography.Text>
          </div>
          <Input
            autoFocus
            placeholder={t("workflows:editorText.searchNodes")}
            value={searchKeyword}
            onChange={(event) => setSearchKeyword(event.target.value)}
          />

          {isLoading ? <Spin size="small" /> : null}

          {loadFailed ? (
            <div className="canvas-entry-toolbar-error">
              <Typography.Text type="danger">{t("workflows:editorText.registryFailed")}</Typography.Text>
              <button onClick={() => void handleRetry()} type="button">
                {t("common:retry")}
              </button>
            </div>
          ) : null}

          <div className="canvas-entry-toolbar-groups">
            {groups.map((group) => (
              <section className="canvas-entry-toolbar-group" key={group.category.category_id}>
                <Typography.Text strong>{group.category.display_name}</Typography.Text>
                <div className="canvas-entry-toolbar-items">
                  {group.nodes.map((node) => (
                    <button
                      className="canvas-entry-toolbar-item"
                      data-testid={nodeItemTestId(node.node_type)}
                      key={node.node_type}
                      onClick={() => handleAddNode(node.node_type)}
                      type="button"
                    >
                      <div className="canvas-entry-toolbar-item-main">
                        <div className="canvas-entry-toolbar-item-topline">
                          <span className={`canvas-entry-toolbar-item-category is-${group.category.category_id}`}>
                            {resolveCategoryLabel(group.category.category_id)}
                          </span>
                          <code>{node.node_type}</code>
                        </div>
                        <div className="canvas-entry-toolbar-item-name">
                          <span aria-hidden className="canvas-entry-toolbar-item-icon">
                            {createElement(getCategoryIcon(group.category.category_id), { size: 22 })}
                          </span>
                          <span>{node.display_name}</span>
                        </div>
                        <div className="canvas-entry-toolbar-item-description">
                          {node.description ?? group.category.description ?? t("workflows:editorText.addNodeFallback")}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
