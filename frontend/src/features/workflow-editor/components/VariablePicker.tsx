import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Input, Select, Space, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useWorkflowStore } from "@/features/workflow-editor/store";
import type { InputBinding } from "@/features/workflow-editor/types/inputBindings";
import type { WorkflowNode } from "@/types/workflow";

const TOP_LEVEL_OPTIONS = [
  { value: "text", labelKey: "editorText.bindingPathText" },
  { value: "binary", labelKey: "editorText.bindingPathBinary" },
  { value: "structured", labelKey: "editorText.bindingPathStructured" },
  { value: "metadata", labelKey: "editorText.bindingPathMetadata" }
] as const;

const DEFAULT_BINDING: InputBinding = {
  name: "",
  selector: []
};

interface VariablePickerProps {
  nodeId: string;
  bindings: InputBinding[];
  onChange: (next: InputBinding[]) => void;
}

function selectorToOutputPath(selector: string[] | undefined): string | undefined {
  if (!selector || selector.length < 3) {
    return undefined;
  }

  return selector.slice(2).join(".");
}

function updateBinding(bindings: InputBinding[], index: number, nextBinding: InputBinding): InputBinding[] {
  return bindings.map((binding, bindingIndex) => (bindingIndex === index ? nextBinding : binding));
}

function normalizePathSegments(rawValue: string): string[] {
  return rawValue
    .split(".")
    .map((segment) => segment.trim())
    .filter((segment) => segment.length > 0);
}

function isUnsafePathSegment(segment: string): boolean {
  return segment.length === 0
    || /^\d+$/.test(segment)
    || segment === "item"
    || segment === "index"
    || /[.[\]]/.test(segment);
}

function validateNestedPath(rawValue: string): boolean {
  if (!rawValue.trim()) {
    return true;
  }

  const rawSegments = rawValue.split(".").map((segment) => segment.trim());
  if (rawSegments.some((segment) => segment.length === 0)) {
    return false;
  }

  return rawSegments.every((segment) => !isUnsafePathSegment(segment));
}

function buildSelector(nodeId: string | undefined, topLevel: string | undefined, nestedPath: string | undefined): string[] {
  if (!nodeId || !topLevel) {
    return [];
  }

  if (topLevel === "text" || topLevel === "binary") {
    return [nodeId, topLevel];
  }

  const segments = nestedPath ? normalizePathSegments(nestedPath) : [];
  return [nodeId, topLevel, ...segments];
}

function collectAncestorNodes(nodeId: string, nodes: WorkflowNode[], edges: Array<{ source: string; target: string }>): WorkflowNode[] {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const incoming = new Map<string, string[]>();

  for (const edge of edges) {
    incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge.source]);
  }

  const visited = new Set<string>();
  const order: string[] = [];

  const visit = (currentId: string) => {
    for (const sourceId of incoming.get(currentId) ?? []) {
      if (visited.has(sourceId)) {
        continue;
      }
      visited.add(sourceId);
      visit(sourceId);
      order.push(sourceId);
    }
  };

  visit(nodeId);
  return order
    .map((ancestorId) => nodesById.get(ancestorId))
    .filter((node): node is WorkflowNode => node != null)
    .sort((left, right) => left.id.localeCompare(right.id));
}

export default function VariablePicker({ nodeId, bindings, onChange }: VariablePickerProps) {
  const { t } = useTranslation("workflows");
  const nodes = useWorkflowStore((state) => state.nodes);
  const edges = useWorkflowStore((state) => state.edges);
  const [pathDrafts, setPathDrafts] = useState<Record<number, string>>({});
  const [pathErrors, setPathErrors] = useState<Record<number, boolean>>({});

  const ancestorNodes = useMemo(() => collectAncestorNodes(nodeId, nodes, edges), [nodeId, nodes, edges]);

  const ancestorOptions = ancestorNodes.map((node) => ({
    label: `${node.data.label} (${node.id})`,
    value: node.id
  }));

  const normalizedBindings = bindings;

  useEffect(() => {
    setPathDrafts(
      Object.fromEntries(
        normalizedBindings.map((binding, index) => [index, selectorToOutputPath(binding.selector) ?? ""])
      )
    );
    setPathErrors({});
  }, [normalizedBindings]);

  return (
    <div data-testid="variable-picker" style={{ marginBottom: 16 }}>
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <div>
          <Typography.Text strong>{t("editorText.namedInputBindings")}</Typography.Text>
          <div>
            <Typography.Text type="secondary">
              {t("editorText.namedInputBindingsDescription")}
            </Typography.Text>
          </div>
        </div>

        {normalizedBindings.map((binding, index) => {
          const selectedNodeId = binding.selector[0];
          const selectedTopLevel = binding.selector[1];
          const selectedOutputPath = selectorToOutputPath(binding.selector);
          const supportsNestedPath = selectedTopLevel === "structured" || selectedTopLevel === "metadata";

          return (
            <div
              data-testid={`binding-row-${index}`}
              key={`binding-${index}`}
              style={{
                border: "1px solid #f0f0f0",
                borderRadius: 8,
                padding: 12
              }}
            >
              <Space direction="vertical" size={12} style={{ width: "100%" }}>
                <Input
                  data-testid={`binding-name-${index}`}
                  onChange={(event) => {
                    onChange(
                      updateBinding(normalizedBindings, index, {
                        ...binding,
                        name: event.target.value
                      })
                    );
                  }}
                  placeholder={t("editorText.bindingNamePlaceholder")}
                  value={binding.name}
                />

                <Select
                  allowClear
                  data-testid={`binding-ancestor-${index}`}
                  onChange={(value) => {
                    onChange(
                      updateBinding(normalizedBindings, index, {
                        ...binding,
                        selector: value
                          ? [value, ...(binding.selector.length > 1 ? binding.selector.slice(1) : [])]
                          : []
                      })
                    );
                  }}
                  options={ancestorOptions}
                  placeholder={t("editorText.bindingAncestorPlaceholder")}
                  value={selectedNodeId || undefined}
                  virtual={false}
                />

                <Select
                  allowClear
                  data-testid={`binding-output-root-${index}`}
                  onChange={(value) => {
                    onChange(
                      updateBinding(normalizedBindings, index, {
                        ...binding,
                        selector: buildSelector(binding.selector[0], value, undefined)
                      })
                    );
                  }}
                  options={TOP_LEVEL_OPTIONS.map((option) => ({
                    label: t(option.labelKey),
                    value: option.value
                  }))}
                  placeholder={t("editorText.bindingOutputPathPlaceholder")}
                  value={selectedTopLevel}
                  virtual={false}
                />

                <Input
                  data-testid={`binding-path-input-${index}`}
                  disabled={!supportsNestedPath}
                  onChange={(event) => {
                    const nextValue = event.target.value;
                    setPathDrafts((current) => ({ ...current, [index]: nextValue }));
                    if (!supportsNestedPath) {
                      setPathErrors((current) => ({ ...current, [index]: false }));
                      return;
                    }
                    const isValid = validateNestedPath(nextValue);
                    setPathErrors((current) => ({ ...current, [index]: !isValid }));
                    if (!isValid) {
                      return;
                    }
                    onChange(
                      updateBinding(normalizedBindings, index, {
                        ...binding,
                        selector: buildSelector(binding.selector[0], selectedTopLevel, nextValue)
                      })
                    );
                  }}
                  placeholder={t("editorText.bindingNestedPathPlaceholder")}
                  value={pathDrafts[index] ?? selectedOutputPath ?? ""}
                />
                {pathErrors[index] ? (
                  <Typography.Text type="danger">
                    {t("editorText.bindingNestedPathValidation")}
                  </Typography.Text>
                ) : null}

                <div>
                  <Button
                    data-testid={`binding-remove-${index}`}
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => onChange(normalizedBindings.filter((_, bindingIndex) => bindingIndex !== index))}
                    size="small"
                    type="text"
                  >
                    {t("editorText.removeBinding")}
                  </Button>
                </div>
              </Space>
            </div>
          );
        })}

        <Button
          data-testid="add-binding"
          icon={<PlusOutlined />}
          onClick={() => onChange([...normalizedBindings, { ...DEFAULT_BINDING }])}
        >
          {t("editorText.addBinding")}
        </Button>
      </Space>
    </div>
  );
}
