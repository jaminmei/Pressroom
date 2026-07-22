import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useDiffHighlight } from "@/features/workflow-editor/hooks/useDiffHighlight";

describe("useDiffHighlight", () => {
  it("returns same lines and hasDiff false for identical text", () => {
    const text = ["line 1", "line 2", "line 3"].join("\n");

    const { result } = renderHook(() => useDiffHighlight(text, text));

    expect(result.current.hasDiff).toBe(false);
    expect(result.current.leftLines).toHaveLength(3);
    expect(result.current.rightLines).toHaveLength(3);
    expect(result.current.leftLines.every((line) => line.type === "same")).toBe(true);
    expect(result.current.rightLines.every((line) => line.type === "same")).toBe(true);
  });

  it("marks right-only inserted lines as added", () => {
    const { result } = renderHook(() =>
      useDiffHighlight("line 1\nline 2", "line 1\nline 2\nline 3")
    );

    expect(result.current.hasDiff).toBe(true);
    expect(result.current.leftLines).toHaveLength(3);
    expect(result.current.rightLines).toHaveLength(3);
    expect(result.current.leftLines[2]).toEqual({
      content: "",
      type: "added",
      isPlaceholder: true
    });
    expect(result.current.rightLines[2]).toEqual({
      content: "line 3",
      type: "added",
      isPlaceholder: false
    });
  });

  it("marks removed lines with right-side placeholders", () => {
    const { result } = renderHook(() =>
      useDiffHighlight("line 1\nline 2\nline 3", "line 1\nline 3")
    );

    expect(result.current.hasDiff).toBe(true);
    expect(result.current.leftLines).toHaveLength(3);
    expect(result.current.rightLines).toHaveLength(3);
    expect(result.current.leftLines[1]).toEqual({
      content: "line 2",
      type: "removed",
      isPlaceholder: false
    });
    expect(result.current.rightLines[1]).toEqual({
      content: "",
      type: "removed",
      isPlaceholder: true
    });
  });

  it("marks replaced lines as modified on both sides", () => {
    const { result } = renderHook(() =>
      useDiffHighlight("line 1\nline 2\nline 3", "line 1\nline X\nline 3")
    );

    expect(result.current.hasDiff).toBe(true);
    expect(result.current.leftLines[1]).toEqual({
      content: "line 2",
      type: "modified",
      isPlaceholder: false
    });
    expect(result.current.rightLines[1]).toEqual({
      content: "line X",
      type: "modified",
      isPlaceholder: false
    });
    expect(result.current.leftLines).toHaveLength(result.current.rightLines.length);
  });

  it("scales to large documents without quadratic slowdown", () => {
    const lineCount = 5000;
    const left = Array.from({ length: lineCount }, (_, index) => `line ${index}`).join("\n");
    const right = [
      ...Array.from({ length: lineCount }, (_, index) => `line ${index}`),
      "extra line"
    ].join("\n");
    const start = performance.now();

    const { result } = renderHook(() => useDiffHighlight(left, right));
    const durationMs = performance.now() - start;

    expect(durationMs).toBeLessThan(250);
    expect(result.current.hasDiff).toBe(true);
    expect(result.current.leftLines).toHaveLength(lineCount + 1);
    expect(result.current.rightLines).toHaveLength(lineCount + 1);
    expect(result.current.leftLines[result.current.leftLines.length - 1]).toEqual({
      content: "",
      type: "added",
      isPlaceholder: true
    });
    expect(result.current.rightLines[result.current.rightLines.length - 1]).toEqual({
      content: "extra line",
      type: "added",
      isPlaceholder: false
    });
  });
});
