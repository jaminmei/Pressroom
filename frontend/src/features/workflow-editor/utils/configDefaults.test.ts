import { describe, expect, it } from "vitest";

import { buildDefaultValues } from "@/features/workflow-editor/utils/configDefaults";
import type { NodeConfigSchema } from "@/types/node-registry";

describe("buildDefaultValues", () => {
  it("returns empty object when schema has no properties with defaults", () => {
    const schema: NodeConfigSchema = {
      type: "object",
      properties: {
        name: { type: "string", title: "Name" },
        count: { type: "number", title: "Count" }
      }
    };
    expect(buildDefaultValues(schema)).toEqual({});
  });

  it("extracts defaults from properties that define them", () => {
    const schema: NodeConfigSchema = {
      type: "object",
      properties: {
        language: { type: "string", title: "Language", default: "auto" },
        threshold: { type: "number", title: "Threshold", default: 0.5 },
        debug: { type: "boolean", title: "Debug", default: false }
      }
    };
    expect(buildDefaultValues(schema)).toEqual({
      language: "auto",
      threshold: 0.5,
      debug: false
    });
  });

  it("ignores properties without default field", () => {
    const schema: NodeConfigSchema = {
      type: "object",
      properties: {
        language: { type: "string", title: "Language", default: "en" },
        model: { type: "string", title: "Model" }
      }
    };
    expect(buildDefaultValues(schema)).toEqual({ language: "en" });
  });

  it("handles empty schema properties", () => {
    const schema: NodeConfigSchema = {
      type: "object",
      properties: {}
    };
    expect(buildDefaultValues(schema)).toEqual({});
  });

  it("preserves default values of various types", () => {
    const schema: NodeConfigSchema = {
      type: "object",
      properties: {
        str_val: { type: "string", title: "S", default: "hello" },
        num_val: { type: "number", title: "N", default: 42 },
        bool_val: { type: "boolean", title: "B", default: true },
        arr_val: { type: "array", title: "A", default: [1, 2, 3] },
        null_val: { type: "string", title: "NV", default: null }
      }
    };
    expect(buildDefaultValues(schema)).toEqual({
      str_val: "hello",
      num_val: 42,
      bool_val: true,
      arr_val: [1, 2, 3],
      null_val: null
    });
  });
});
