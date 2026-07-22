import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useMultiSelect } from "@/features/workflow-editor/hooks/useMultiSelect";

describe("useMultiSelect", () => {
  it("supports replace/toggle/clear selection", () => {
    const { result } = renderHook(() => useMultiSelect());

    act(() => {
      result.current.replaceSelection(["node-a"]);
    });
    expect(result.current.selectedNodeIds).toEqual(["node-a"]);
    expect(result.current.primarySelectedNodeId).toBe("node-a");

    act(() => {
      result.current.toggleSelection("node-b");
    });
    expect(result.current.selectedNodeIds).toEqual(["node-a", "node-b"]);

    act(() => {
      result.current.toggleSelection("node-a");
    });
    expect(result.current.selectedNodeIds).toEqual(["node-b"]);

    act(() => {
      result.current.clearSelection();
    });
    expect(result.current.selectedNodeIds).toEqual([]);
    expect(result.current.primarySelectedNodeId).toBeNull();
  });

  it("keeps original selection order when syncing from canvas selection events", () => {
    const { result } = renderHook(() => useMultiSelect(["node-a", "node-b"]));

    act(() => {
      result.current.syncSelection(["node-c", "node-a", "node-b"]);
    });
    expect(result.current.selectedNodeIds).toEqual(["node-a", "node-b", "node-c"]);

    act(() => {
      result.current.syncSelection(["node-c", "node-b"]);
    });
    expect(result.current.selectedNodeIds).toEqual(["node-b", "node-c"]);
    expect(result.current.primarySelectedNodeId).toBe("node-b");
  });
});
