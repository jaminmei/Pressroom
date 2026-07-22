import { useCallback, useState } from "react";

function toUniqueIds(nodeIds: string[]): string[] {
  return Array.from(new Set(nodeIds));
}

function mergeSelectionOrder(previousIds: string[], nextIds: string[]): string[] {
  const nextIdSet = new Set(nextIds);
  const kept = previousIds.filter((id) => nextIdSet.has(id));
  const keptSet = new Set(kept);
  const appended = nextIds.filter((id) => !keptSet.has(id));
  return [...kept, ...appended];
}

function isSameSelection(leftIds: string[], rightIds: string[]): boolean {
  if (leftIds.length !== rightIds.length) {
    return false;
  }
  return leftIds.every((id, index) => id === rightIds[index]);
}

export interface UseMultiSelectResult {
  selectedNodeIds: string[];
  hasSelection: boolean;
  primarySelectedNodeId: string | null;
  syncSelection: (nodeIds: string[]) => void;
  replaceSelection: (nodeIds: string[]) => void;
  toggleSelection: (nodeId: string) => void;
  clearSelection: () => void;
}

export function useMultiSelect(initialSelection: string[] = []): UseMultiSelectResult {
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>(toUniqueIds(initialSelection));

  const syncSelection = useCallback((nodeIds: string[]) => {
    const normalizedIds = toUniqueIds(nodeIds);
    setSelectedNodeIds((previousIds) => {
      const mergedIds = mergeSelectionOrder(previousIds, normalizedIds);
      return isSameSelection(previousIds, mergedIds) ? previousIds : mergedIds;
    });
  }, []);

  const replaceSelection = useCallback((nodeIds: string[]) => {
    const normalizedIds = toUniqueIds(nodeIds);
    setSelectedNodeIds((previousIds) =>
      isSameSelection(previousIds, normalizedIds) ? previousIds : normalizedIds
    );
  }, []);

  const toggleSelection = useCallback((nodeId: string) => {
    setSelectedNodeIds((previousIds) => {
      if (previousIds.includes(nodeId)) {
        return previousIds.filter((id) => id !== nodeId);
      }
      return [...previousIds, nodeId];
    });
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedNodeIds((previousIds) => (previousIds.length === 0 ? previousIds : []));
  }, []);

  return {
    selectedNodeIds,
    hasSelection: selectedNodeIds.length > 0,
    primarySelectedNodeId: selectedNodeIds[0] ?? null,
    syncSelection,
    replaceSelection,
    toggleSelection,
    clearSelection
  } satisfies UseMultiSelectResult;
}
