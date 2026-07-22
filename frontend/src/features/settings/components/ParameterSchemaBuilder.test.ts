import { describe, expect, it } from "vitest";

import {
  buildSchemaFromEntries,
  parseSchemaToEntries,
  validateEntry,
  validateAllEntries,
  type ParamEntry,
} from "./ParameterSchemaBuilder";

function makeEntry(overrides: Partial<ParamEntry> = {}): ParamEntry {
  return {
    key: "",
    type: "string",
    title: "",
    description: "",
    default_val: "",
    enum_vals: [],
    items_enum_vals: [],
    minimum: null,
    maximum: null,
    required: false,
    items_type: "string",
    ...overrides,
  };
}

describe("ParameterSchemaBuilder utilities", () => {
  describe("buildSchemaFromEntries", () => {
    it("returns null for empty entries", () => {
      expect(buildSchemaFromEntries([])).toBeNull();
    });

    it("returns null when all keys are empty", () => {
      expect(buildSchemaFromEntries([makeEntry({ key: "" })])).toBeNull();
    });

    it("builds a simple string parameter with enum", () => {
      const entries: ParamEntry[] = [
        makeEntry({
          key: "language",
          type: "string",
          title: "Language",
          description: "OCR language",
          default_val: "ch",
          enum_vals: ["ch", "en", "korean"],
        }),
      ];
      const schema = buildSchemaFromEntries(entries);
      expect(schema).toEqual({
        type: "object",
        properties: {
          language: {
            type: "string",
            title: "Language",
            description: "OCR language",
            default: "ch",
            enum: ["ch", "en", "korean"],
          },
        },
        required: [],
      });
    });

    it("builds a number parameter with min/max", () => {
      const entries: ParamEntry[] = [
        makeEntry({
          key: "threshold",
          type: "number",
          title: "Threshold",
          default_val: "0.3",
          minimum: 0.1,
          maximum: 0.9,
        }),
      ];
      const schema = buildSchemaFromEntries(entries);
      expect(schema).toEqual({
        type: "object",
        properties: {
          threshold: {
            type: "number",
            title: "Threshold",
            default: 0.3,
            minimum: 0.1,
            maximum: 0.9,
          },
        },
        required: [],
      });
    });

    it("builds a boolean parameter", () => {
      const entries: ParamEntry[] = [
        makeEntry({
          key: "use_angle_cls",
          type: "boolean",
          title: "Angle Cls",
          default_val: "true",
        }),
      ];
      const schema = buildSchemaFromEntries(entries);
      expect(schema?.properties).toEqual({
        use_angle_cls: {
          type: "boolean",
          title: "Angle Cls",
          default: true,
        },
      });
    });

    it("builds an integer parameter", () => {
      const entries: ParamEntry[] = [
        makeEntry({
          key: "quality",
          type: "integer",
          title: "Quality",
          default_val: "95",
          minimum: 1,
          maximum: 100,
        }),
      ];
      const schema = buildSchemaFromEntries(entries);
      expect(schema?.properties).toEqual({
        quality: {
          type: "integer",
          title: "Quality",
          default: 95,
          minimum: 1,
          maximum: 100,
        },
      });
    });

    it("handles empty default gracefully", () => {
      const entries: ParamEntry[] = [
        makeEntry({ key: "name", type: "string", title: "Name" }),
      ];
      const schema = buildSchemaFromEntries(entries);
      expect(schema?.properties).toEqual({
        name: {
          type: "string",
          title: "Name",
        },
      });
    });

    it("builds an array parameter with items type", () => {
      const entries: ParamEntry[] = [
        makeEntry({
          key: "selected_types",
          type: "array",
          title: "Selected Types",
          items_type: "string",
        }),
      ];
      const schema = buildSchemaFromEntries(entries);
      expect(schema?.properties).toEqual({
        selected_types: {
          type: "array",
          title: "Selected Types",
          items: { type: "string" },
        },
      });
    });

    it("collects required keys", () => {
      const entries: ParamEntry[] = [
        makeEntry({ key: "lang", type: "string", required: true }),
        makeEntry({ key: "opt", type: "string", required: false }),
        makeEntry({ key: "mode", type: "string", required: true }),
      ];
      const schema = buildSchemaFromEntries(entries);
      expect(schema?.required).toEqual(["lang", "mode"]);
    });
  });

  describe("parseSchemaToEntries", () => {
    it("returns empty for null schema", () => {
      expect(parseSchemaToEntries(null)).toEqual([]);
    });

    it("parses a schema with multiple types", () => {
      const schema = {
        type: "object",
        properties: {
          language: { type: "string", default: "ch", enum: ["ch", "en"], title: "Language" },
          threshold: { type: "number", default: 0.3, minimum: 0.1, maximum: 0.9, title: "Threshold" },
          enabled: { type: "boolean", default: true, title: "Enabled" },
        },
        required: ["language"],
      };

      const entries = parseSchemaToEntries(schema);
      expect(entries).toHaveLength(3);
      expect(entries[0]).toEqual({
        key: "language",
        type: "string",
        title: "Language",
        description: "",
        default_val: "ch",
        enum_vals: ["ch", "en"],
        items_enum_vals: [],
        minimum: null,
        maximum: null,
        required: true,
        items_type: "string",
      });
      expect(entries[1]).toEqual({
        key: "threshold",
        type: "number",
        title: "Threshold",
        description: "",
        default_val: "0.3",
        enum_vals: [],
        items_enum_vals: [],
        minimum: 0.1,
        maximum: 0.9,
        required: false,
        items_type: "string",
      });
      expect(entries[2]).toEqual({
        key: "enabled",
        type: "boolean",
        title: "Enabled",
        description: "",
        default_val: "true",
        enum_vals: [],
        items_enum_vals: [],
        minimum: null,
        maximum: null,
        required: false,
        items_type: "string",
      });
    });

    it("parses array with items type", () => {
      const schema = {
        type: "object",
        properties: {
          tags: { type: "array", items: { type: "string" }, title: "Tags" },
        },
        required: [],
      };
      const entries = parseSchemaToEntries(schema);
      expect(entries[0]).toEqual({
        key: "tags",
        type: "array",
        title: "Tags",
        description: "",
        default_val: "",
        enum_vals: [],
        items_enum_vals: [],
        minimum: null,
        maximum: null,
        required: false,
        items_type: "string",
      });
    });

    it("round-trips: build → parse → build produces same schema", () => {
      const entries: ParamEntry[] = [
        makeEntry({
          key: "language",
          type: "string",
          title: "Language",
          description: "OCR language",
          default_val: "ch",
          enum_vals: ["ch", "en"],
          required: true,
        }),
        makeEntry({
          key: "threshold",
          type: "number",
          title: "Threshold",
          default_val: "0.3",
          minimum: 0.1,
          maximum: 0.9,
        }),
      ];
      const schema = buildSchemaFromEntries(entries)!;
      const parsed = parseSchemaToEntries(schema);
      const rebuilt = buildSchemaFromEntries(parsed)!;

      expect(rebuilt).toEqual(schema);
    });
  });

  describe("validateEntry", () => {
    it("returns error for empty key", () => {
      expect(validateEntry(makeEntry({ key: " " }))).toBe("Key is required");
    });

    it("returns empty string for valid entry", () => {
      expect(validateEntry(makeEntry({ key: "name", type: "string", default_val: "hello" }))).toBe("");
    });

    it("returns empty string when no default is set", () => {
      expect(validateEntry(makeEntry({ key: "x", type: "number", default_val: "" }))).toBe("");
    });

    it("validates number type", () => {
      expect(validateEntry(makeEntry({ key: "x", type: "number", default_val: "abc" }))).toBe(
        "Default is not a valid number",
      );
    });

    it("validates number min range", () => {
      expect(validateEntry(makeEntry({ key: "x", type: "number", default_val: "0.05", minimum: 0.1 }))).toBe(
        "Default must be ≥ 0.1",
      );
    });

    it("validates number max range", () => {
      expect(validateEntry(makeEntry({ key: "x", type: "number", default_val: "1.5", maximum: 0.9 }))).toBe(
        "Default must be ≤ 0.9",
      );
    });

    it("validates integer type", () => {
      expect(validateEntry(makeEntry({ key: "x", type: "integer", default_val: "3.5" }))).toBe(
        "Default is not a valid integer",
      );
    });

    it("validates integer min range", () => {
      expect(validateEntry(makeEntry({ key: "x", type: "integer", default_val: "0", minimum: 1 }))).toBe(
        "Default must be ≥ 1",
      );
    });

    it("validates boolean type", () => {
      expect(validateEntry(makeEntry({ key: "x", type: "boolean", default_val: "yes" }))).toBe(
        "Default must be true or false",
      );
    });

    it("accepts boolean true", () => {
      expect(validateEntry(makeEntry({ key: "x", type: "boolean", default_val: "true" }))).toBe("");
    });

    it("accepts boolean false", () => {
      expect(validateEntry(makeEntry({ key: "x", type: "boolean", default_val: "false" }))).toBe("");
    });

    it("validates enum membership for string type", () => {
      expect(
        validateEntry(
          makeEntry({ key: "x", type: "string", default_val: "fr", enum_vals: ["ch", "en"] }),
        ),
      ).toBe("Default must be one of: ch, en");
    });

    it("accepts valid enum value", () => {
      expect(
        validateEntry(
          makeEntry({ key: "x", type: "string", default_val: "ch", enum_vals: ["ch", "en"] }),
        ),
      ).toBe("");
    });
  });

  describe("validateAllEntries", () => {
    it("returns empty map for all valid entries", () => {
      const entries = [
        makeEntry({ key: "a", type: "string" }),
        makeEntry({ key: "b", type: "number", default_val: "1" }),
      ];
      expect(validateAllEntries(entries).size).toBe(0);
    });

    it("returns map of index to error message", () => {
      const entries = [
        makeEntry({ key: "a", type: "number", default_val: "abc" }),
        makeEntry({ key: "b", type: "boolean", default_val: "yes" }),
        makeEntry({ key: "c", type: "string" }),
      ];
      const errors = validateAllEntries(entries);
      expect(errors.size).toBe(2);
      expect(errors.get(0)).toBe("Default is not a valid number");
      expect(errors.get(1)).toBe("Default must be true or false");
    });
  });

  describe("array enum support", () => {
    it("builds array parameter with items enum", () => {
      const entries: ParamEntry[] = [
        makeEntry({
          key: "selected_types",
          type: "array",
          title: "Selected Types",
          items_type: "string",
          items_enum_vals: ["Text", "Title", "Table", "Figure"],
          default_val: '["Text","Title"]',
        }),
      ];
      const schema = buildSchemaFromEntries(entries);
      expect(schema?.properties).toEqual({
        selected_types: {
          type: "array",
          title: "Selected Types",
          default: ["Text", "Title"],
          items: { type: "string", enum: ["Text", "Title", "Table", "Figure"] },
        },
      });
    });

    it("builds array without items enum when items_enum_vals is empty", () => {
      const entries: ParamEntry[] = [
        makeEntry({
          key: "tags",
          type: "array",
          title: "Tags",
          items_type: "string",
          items_enum_vals: [],
        }),
      ];
      const schema = buildSchemaFromEntries(entries);
      expect(schema?.properties).toEqual({
        tags: {
          type: "array",
          title: "Tags",
          items: { type: "string" },
        },
      });
    });

    it("parses schema with items enum into items_enum_vals", () => {
      const schema = {
        type: "object",
        properties: {
          selected_types: {
            type: "array",
            title: "Selected Types",
            items: { type: "string", enum: ["Text", "Title", "Table"] },
            default: ["Text"],
          },
        },
        required: [],
      };
      const entries = parseSchemaToEntries(schema);
      expect(entries[0]).toEqual({
        key: "selected_types",
        type: "array",
        title: "Selected Types",
        description: "",
        default_val: '["Text"]',
        enum_vals: [],
        items_enum_vals: ["Text", "Title", "Table"],
        minimum: null,
        maximum: null,
        required: false,
        items_type: "string",
      });
    });

    it("round-trips array with items enum", () => {
      const entries: ParamEntry[] = [
        makeEntry({
          key: "types",
          type: "array",
          title: "Types",
          items_type: "string",
          items_enum_vals: ["Text", "Title", "Table"],
          default_val: '["Text"]',
        }),
      ];
      const schema = buildSchemaFromEntries(entries)!;
      const parsed = parseSchemaToEntries(schema);
      const rebuilt = buildSchemaFromEntries(parsed)!;

      expect(rebuilt).toEqual(schema);
      expect(parsed[0].items_enum_vals).toEqual(["Text", "Title", "Table"]);
    });

    it("validates array default against items enum", () => {
      expect(
        validateEntry(
          makeEntry({
            key: "types",
            type: "array",
            items_enum_vals: ["Text", "Title"],
            default_val: '["Text","Unknown"]',
          }),
        ),
      ).toBe("Default contains invalid values: Unknown");
    });

    it("accepts valid array default within items enum", () => {
      expect(
        validateEntry(
          makeEntry({
            key: "types",
            type: "array",
            items_enum_vals: ["Text", "Title"],
            default_val: '["Text"]',
          }),
        ),
      ).toBe("");
    });

    it("accepts empty array default with items enum", () => {
      expect(
        validateEntry(
          makeEntry({
            key: "types",
            type: "array",
            items_enum_vals: ["Text", "Title"],
            default_val: "[]",
          }),
        ),
      ).toBe("");
    });

    it("validates array default must be valid JSON", () => {
      expect(
        validateEntry(
          makeEntry({
            key: "types",
            type: "array",
            items_enum_vals: ["Text"],
            default_val: "not-json",
          }),
        ),
      ).toBe("Default must be a valid JSON array");
    });

    it("accepts array default without items enum", () => {
      expect(
        validateEntry(
          makeEntry({
            key: "tags",
            type: "array",
            items_enum_vals: [],
            default_val: '["anything"]',
          }),
        ),
      ).toBe("");
    });
  });
});
