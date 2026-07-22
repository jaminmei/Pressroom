import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, beforeEach } from "vitest";

import { useWorkflowStore } from "@/features/workflow-editor/store";
import type { DynamicWarning } from "@/features/workflow-editor/store";

function makeWarning(overrides: Partial<DynamicWarning> = {}): DynamicWarning {
  return {
    code: "MODEL_NO_VISION",
    severity: "warning",
    node_id: "engine_1",
    message: "Model does not support vision",
    model: null,
    edge_ids: [],
    ...overrides,
  };
}

describe("store dynamic validation", () => {
  beforeEach(() => {
    act(() => {
      useWorkflowStore.getState().clearCanvas();
      useWorkflowStore.getState().clearDynamicWarnings();
    });
  });

  it("initial dynamicValidation state", () => {
    const { result } = renderHook(() => useWorkflowStore());

    expect(result.current.dynamicValidation).toEqual({
      warnings: [],
      isValidating: false,
      lastValidatedAt: null,
    });
  });

  it("setDynamicWarnings updates warnings and lastValidatedAt", () => {
    const { result } = renderHook(() => useWorkflowStore());
    const warnings = [makeWarning()];

    const beforeTimestamp = Date.now();

    act(() => {
      result.current.setDynamicWarnings(warnings);
    });

    const afterTimestamp = Date.now();

    expect(result.current.dynamicValidation.warnings).toEqual(warnings);
    expect(result.current.dynamicValidation.isValidating).toBe(false);
    expect(result.current.dynamicValidation.lastValidatedAt).toBeGreaterThanOrEqual(beforeTimestamp);
    expect(result.current.dynamicValidation.lastValidatedAt).toBeLessThanOrEqual(afterTimestamp);
  });

  it("clearDynamicWarnings resets to initial", () => {
    const { result } = renderHook(() => useWorkflowStore());

    act(() => {
      result.current.setDynamicWarnings([makeWarning()]);
    });
    expect(result.current.dynamicValidation.warnings).toHaveLength(1);
    expect(result.current.dynamicValidation.lastValidatedAt).not.toBeNull();

    act(() => {
      result.current.clearDynamicWarnings();
    });

    expect(result.current.dynamicValidation).toEqual({
      warnings: [],
      isValidating: false,
      lastValidatedAt: null,
    });
  });

  it("hasDynamicBlockers returns true when severity=warning present", () => {
    const { result } = renderHook(() => useWorkflowStore());

    act(() => {
      result.current.setDynamicWarnings([
        makeWarning({ severity: "warning" }),
      ]);
    });

    expect(result.current.hasDynamicBlockers()).toBe(true);
  });

  it("hasDynamicBlockers returns false when only severity=info", () => {
    const { result } = renderHook(() => useWorkflowStore());

    act(() => {
      result.current.setDynamicWarnings([
        makeWarning({ severity: "info", code: "MODEL_NOT_SELECTED" }),
      ]);
    });

    expect(result.current.hasDynamicBlockers()).toBe(false);
  });

  it("getDynamicWarningsForNode filters by node_id", () => {
    const { result } = renderHook(() => useWorkflowStore());

    const warningA = makeWarning({ node_id: "a", message: "warning for a" });
    const warningB = makeWarning({ node_id: "b", message: "warning for b" });

    act(() => {
      result.current.setDynamicWarnings([warningA, warningB]);
    });

    const nodeAWarnings = result.current.getDynamicWarningsForNode("a");
    expect(nodeAWarnings).toHaveLength(1);
    expect(nodeAWarnings[0].node_id).toBe("a");
    expect(nodeAWarnings[0].message).toBe("warning for a");
  });

  it("getDynamicWarningsForNode returns empty for unknown node", () => {
    const { result } = renderHook(() => useWorkflowStore());

    act(() => {
      result.current.setDynamicWarnings([makeWarning({ node_id: "known" })]);
    });

    expect(result.current.getDynamicWarningsForNode("unknown")).toEqual([]);
  });

  it("setIsValidating sets isValidating without clearing warnings", () => {
    const { result } = renderHook(() => useWorkflowStore());

    const warnings = [makeWarning()];

    act(() => {
      result.current.setDynamicWarnings(warnings);
    });

    expect(result.current.dynamicValidation.warnings).toHaveLength(1);

    act(() => {
      result.current.setIsValidating(true);
    });

    expect(result.current.dynamicValidation.isValidating).toBe(true);
    expect(result.current.dynamicValidation.warnings).toEqual(warnings);
  });

  it("hasDynamicBlockers returns false for empty warnings", () => {
    const { result } = renderHook(() => useWorkflowStore());

    expect(result.current.hasDynamicBlockers()).toBe(false);
  });

  it("hasDynamicBlockers returns true for mixed severities", () => {
    const { result } = renderHook(() => useWorkflowStore());

    act(() => {
      result.current.setDynamicWarnings([
        makeWarning({ severity: "warning", code: "MODEL_NO_VISION" }),
        makeWarning({ severity: "info", code: "MODEL_NOT_SELECTED", node_id: "engine_2" }),
      ]);
    });

    expect(result.current.hasDynamicBlockers()).toBe(true);
  });
});
