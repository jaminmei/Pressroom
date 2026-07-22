import { describe, expect, it } from "vitest";

import { formatConfigValue, summarizeConfig } from "@/features/workflow-editor/nodes/CategoryNodeBase";

describe("formatConfigValue", () => {
  it("T-01: formats string value", () => {
    expect(formatConfigValue("pdf")).toBe("pdf");
  });

  it("T-02: formats number value", () => {
    expect(formatConfigValue(300)).toBe("300");
  });

  it("T-03: formats boolean true as Yes", () => {
    expect(formatConfigValue(true)).toBe("Yes");
  });

  it("T-04: formats boolean false as No", () => {
    expect(formatConfigValue(false)).toBe("No");
  });

  it("T-05: formats null as em dash", () => {
    expect(formatConfigValue(null)).toBe("\u2014");
  });

  it("T-06: formats undefined as em dash", () => {
    expect(formatConfigValue(undefined)).toBe("\u2014");
  });

  it("T-07: formats short string array as comma-separated", () => {
    expect(formatConfigValue(["a", "b", "c"])).toBe("a, b, c");
  });

  it("T-08: formats long array as item count", () => {
    expect(formatConfigValue([1, 2, 3, 4, 5])).toBe("[5 items]");
  });

  it("T-09: formats empty array as item count", () => {
    expect(formatConfigValue([])).toBe("[0 items]");
  });

  it("T-10: formats object as key count", () => {
    expect(formatConfigValue({ a: 1, b: 2 })).toBe("{2 keys}");
  });

  it("T-11: formats empty object as key count", () => {
    expect(formatConfigValue({})).toBe("{0 keys}");
  });

  it("T-12: formats mixed array as item count", () => {
    expect(formatConfigValue(["a", 1, true])).toBe("[3 items]");
  });
});

describe("summarizeConfig", () => {
  it("T-13: returns fallback for empty config", () => {
    const result = summarizeConfig({});
    expect(result).toEqual([{ key: "", value: "No config", rawValue: null }]);
  });

  it("T-14: returns single entry", () => {
    const result = summarizeConfig({ format: "pdf" });
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({ key: "format", value: "pdf", rawValue: "pdf" });
  });

  it("T-15: returns all entries without truncation", () => {
    const result = summarizeConfig({ a: "1", b: 2, c: true, d: null });
    expect(result).toHaveLength(4);
    expect(result.map((e) => e.key)).toEqual(["a", "b", "c", "d"]);
  });

  it("T-16: formats array entry", () => {
    const result = summarizeConfig({ pages: ["1", "2", "3"] });
    expect(result[0].value).toBe("1, 2, 3");
  });

  it("T-17: formats object entry", () => {
    const result = summarizeConfig({ opts: { x: 1 } });
    expect(result[0].value).toBe("{1 keys}");
  });

  it("T-18: formats boolean entry", () => {
    const result = summarizeConfig({ grayscale: true });
    expect(result[0].value).toBe("Yes");
  });

  it("filters out undefined values", () => {
    const result = summarizeConfig({ a: "ok", b: undefined });
    expect(result).toHaveLength(1);
    expect(result[0].key).toBe("a");
  });

  it("preserves rawValue in each entry", () => {
    const result = summarizeConfig({ items: [1, 2, 3, 4, 5] });
    expect(result[0].rawValue).toEqual([1, 2, 3, 4, 5]);
    expect(result[0].value).toBe("[5 items]");
  });
});
