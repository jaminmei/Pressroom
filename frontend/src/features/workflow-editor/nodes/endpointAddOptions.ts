import { isSystemManagedNodeType } from "@/features/workflow-editor/utils/endNodeRepair";
import type { NodeRegistryNode, NodeRegistryResponse } from "@/types/node-registry";
import type { NodePosition } from "@/types/workflow";

export type EndpointAddDirection = "upstream" | "downstream";

export const ENDPOINT_NODE_HORIZONTAL_OFFSET = 280;
const ENDPOINT_NODE_VERTICAL_GAP = 96;

function resolveCategoryFromType(nodeType: string): string {
  return nodeType.split("/")[0] ?? "";
}

function resolveNodeCategory(node: Pick<NodeRegistryNode, "node_type" | "category">): string {
  return node.category || resolveCategoryFromType(node.node_type);
}

function sortByDisplayName(a: NodeRegistryNode, b: NodeRegistryNode): number {
  if (a.display_name === b.display_name) {
    return a.node_type.localeCompare(b.node_type);
  }

  return a.display_name.localeCompare(b.display_name);
}

interface ResolveCompatibleNodeOptionsInput {
  anchorNodeType: string;
  direction: EndpointAddDirection;
  registry: Pick<NodeRegistryResponse, "nodes" | "connection_rules">;
}

export function resolveCompatibleNodeOptions({
  anchorNodeType,
  direction,
  registry
}: ResolveCompatibleNodeOptionsInput): NodeRegistryNode[] {
  if (!anchorNodeType || registry.nodes.length === 0) {
    return [];
  }

  if (registry.connection_rules.length === 0) {
    return registry.nodes
      .filter((node) => !isSystemManagedNodeType(node.node_type))
      .sort(sortByDisplayName);
  }

  const anchorMetadata = registry.nodes.find((node) => node.node_type === anchorNodeType);
  const anchorCategory = anchorMetadata
    ? resolveNodeCategory(anchorMetadata)
    : resolveCategoryFromType(anchorNodeType);

  const compatibleCategories = new Set<string>();
  if (direction === "downstream") {
    const categoryRule = registry.connection_rules.find((rule) => rule.from_category === anchorCategory);
    (categoryRule?.to_categories ?? []).forEach((category) => compatibleCategories.add(category));
  } else {
    registry.connection_rules.forEach((rule) => {
      if (rule.to_categories.includes(anchorCategory)) {
        compatibleCategories.add(rule.from_category);
      }
    });
  }

  if (compatibleCategories.size === 0) {
    return [];
  }

  return registry.nodes
    .filter((node) => !isSystemManagedNodeType(node.node_type))
    .filter((node) => compatibleCategories.has(resolveNodeCategory(node)))
    .sort(sortByDisplayName);
}

export function buildEndpointConnection(
  anchorNodeId: string,
  createdNodeId: string,
  direction: EndpointAddDirection
): { source: string; target: string } {
  if (direction === "downstream") {
    return { source: anchorNodeId, target: createdNodeId };
  }

  return { source: createdNodeId, target: anchorNodeId };
}

export function resolveEndpointNodePosition(
  anchorPosition: NodePosition | undefined,
  direction: EndpointAddDirection,
  siblingCount: number
): NodePosition {
  const basePosition = anchorPosition ?? { x: 120, y: 120 };
  const normalizedSiblingCount = Math.max(0, siblingCount);

  return {
    x:
      direction === "downstream"
        ? basePosition.x + ENDPOINT_NODE_HORIZONTAL_OFFSET
        : basePosition.x - ENDPOINT_NODE_HORIZONTAL_OFFSET,
    y: basePosition.y + normalizedSiblingCount * ENDPOINT_NODE_VERTICAL_GAP
  };
}
