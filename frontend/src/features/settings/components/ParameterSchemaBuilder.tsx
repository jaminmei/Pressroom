import { useCallback, useMemo } from "react";
import { Button, Card, Checkbox, Col, Form, Input, InputNumber, Row, Select, Space, Typography } from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";

export interface ParamEntry {
  key: string;
  type: "string" | "number" | "integer" | "boolean" | "array";
  title: string;
  description: string;
  default_val: string; // stored as string, parsed on build
  enum_vals: string[]; // individual enum values for string type
  items_enum_vals: string[]; // enum choices for array items
  minimum: number | null;
  maximum: number | null;
  required: boolean;
  items_type: string; // for array type: "string", "number", etc.
  _rowId?: number; // internal stable key for React list rendering (not serialized)
}

export interface ParameterSchemaBuilderProps {
  value: ParamEntry[];
  onChange: (value: ParamEntry[]) => void;
}

/** Validate a single entry, returning an error message or empty string. */
export function validateEntry(entry: ParamEntry): string {
  if (!entry.key.trim()) return i18n.t("settings:schema.keyRequired");

  const { type, default_val, minimum, maximum, enum_vals } = entry;

  if (default_val === "") return ""; // no default → nothing to validate

  if (type === "number") {
    const n = Number(default_val);
    if (isNaN(n)) return i18n.t("settings:schema.invalidNumber");
    if (minimum !== null && n < minimum) return i18n.t("settings:schema.minimumValue", { value: minimum });
    if (maximum !== null && n > maximum) return i18n.t("settings:schema.maximumValue", { value: maximum });
  }

  if (type === "integer") {
    const n = Number(default_val);
    if (!Number.isInteger(n)) return i18n.t("settings:schema.invalidInteger");
    if (minimum !== null && n < minimum) return i18n.t("settings:schema.minimumValue", { value: minimum });
    if (maximum !== null && n > maximum) return i18n.t("settings:schema.maximumValue", { value: maximum });
  }

  if (type === "boolean" && default_val !== "true" && default_val !== "false") {
    return i18n.t("settings:schema.invalidBoolean");
  }

  if (type === "string" && enum_vals.length > 0) {
    if (!enum_vals.includes(default_val)) {
      return i18n.t("settings:schema.oneOf", { values: enum_vals.join(", ") });
    }
  }

  if (type === "array" && entry.items_enum_vals.length > 0 && default_val) {
    try {
      const parsed = JSON.parse(default_val);
      if (Array.isArray(parsed)) {
        const invalid = parsed.filter((v: string) => !entry.items_enum_vals.includes(v));
        if (invalid.length > 0) {
          return i18n.t("settings:schema.invalidValues", { values: invalid.join(", ") });
        }
      }
    } catch {
      return i18n.t("settings:schema.invalidArray");
    }
  }

  return "";
}

function ParamEntryRow({
  entry,
  index,
  onChange,
  onRemove,
}: {
  entry: ParamEntry;
  index: number;
  onChange: (index: number, updated: ParamEntry) => void;
  onRemove: (index: number) => void;
}) {
  const { t } = useTranslation(["common", "settings"]);
  const typeOptions = (["string", "number", "integer", "boolean", "array"] as const).map((type) => ({
    value: type,
    label: t(`settings:schema.${type}`)
  }));
  const itemsTypeOptions = (["string", "number", "integer"] as const).map((type) => ({
    value: type,
    label: t(`settings:schema.${type}`)
  }));
  const handleChange = (field: keyof ParamEntry, value: unknown) => {
    onChange(index, { ...entry, [field]: value });
  };

  const error = validateEntry(entry);

  return (
    <Card
      size="small"
      style={{ marginBottom: 8, borderLeft: entry.required ? "3px solid #7132f5" : undefined }}
      title={
        <Space>
          <span>{t("settings:schema.parameter", { count: index + 1 })}</span>
          {entry.key && <Typography.Text code style={{ fontSize: 11 }}>{entry.key}</Typography.Text>}
          {entry.required && <Typography.Text type="secondary" style={{ fontSize: 11 }}>*</Typography.Text>}
        </Space>
      }
      extra={
        <Button
          danger
          icon={<DeleteOutlined />}
          onClick={() => onRemove(index)}
          size="small"
          type="text"
        />
      }
    >
      <Row gutter={8} align="middle">
        <Col span={7}>
          <Form.Item label={t("settings:schema.key")} style={{ marginBottom: 4 }}>
            <Input
              value={entry.key}
              onChange={(e) => handleChange("key", e.target.value)}
              placeholder="param_name"
              size="small"
              status={entry.key.trim() ? undefined : entry.key === "" ? undefined : "error"}
            />
          </Form.Item>
        </Col>
        <Col span={5}>
          <Form.Item label={t("settings:schema.type")} style={{ marginBottom: 4 }}>
            <Select
              value={entry.type}
              onChange={(v) => handleChange("type", v)}
              options={typeOptions}
              size="small"
            />
          </Form.Item>
        </Col>
        <Col span={9}>
          <Form.Item label={t("settings:schema.title")} style={{ marginBottom: 4 }}>
            <Input
              value={entry.title}
              onChange={(e) => handleChange("title", e.target.value)}
              placeholder={t("settings:schema.displayName")}
              size="small"
            />
          </Form.Item>
        </Col>
        <Col span={3}>
          <Form.Item label={t("common:required")} style={{ marginBottom: 4 }}>
            <Checkbox
              checked={entry.required}
              onChange={(e) => handleChange("required", e.target.checked)}
            />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={8}>
        <Col span={24}>
          <Form.Item label={t("settings:schema.description")} style={{ marginBottom: 4 }}>
            <Input
              value={entry.description}
              onChange={(e) => handleChange("description", e.target.value)}
              placeholder={t("settings:schema.parameterDescription")}
              size="small"
            />
          </Form.Item>
        </Col>
      </Row>
      {/* Non-array: type-specific controls + default on one row */}
      {entry.type !== "array" && (
        <Row gutter={8}>
          <Col span={6}>
            <Form.Item
              label={t("settings:schema.default")}
              style={{ marginBottom: error ? 0 : 4 }}
              validateStatus={error ? "error" : undefined}
              help={error || undefined}
            >
              {entry.type === "boolean" ? (
                <Select
                  value={entry.default_val || undefined}
                  onChange={(v) => handleChange("default_val", v ?? "")}
                  placeholder={t("common:none")}
                  size="small"
                  allowClear
                  options={[
                    { value: "true", label: t("settings:schema.true") },
                    { value: "false", label: t("settings:schema.false") },
                  ]}
                />
              ) : entry.type === "string" && entry.enum_vals.length > 0 ? (
                <Select
                  value={entry.default_val || undefined}
                  onChange={(v) => handleChange("default_val", v ?? "")}
                  placeholder={t("common:none")}
                  size="small"
                  allowClear
                  options={entry.enum_vals.map((v) => ({ value: v, label: v }))}
                />
              ) : (
                <Input
                  value={entry.default_val}
                  onChange={(e) => handleChange("default_val", e.target.value)}
                  placeholder={t("common:none")}
                  size="small"
                />
              )}
            </Form.Item>
          </Col>
          {entry.type === "string" && (
            <Col span={12}>
              <Form.Item label={t("settings:schema.enumOptions")} style={{ marginBottom: 4 }} extra={t("settings:schema.addOptionHelp")}>
                <Select
                  mode="tags"
                  value={entry.enum_vals}
                  onChange={(v) => handleChange("enum_vals", v)}
                  placeholder={t("settings:schema.optionPlaceholder")}
                  size="small"
                  tokenSeparators={[","]}
                  open={false}
                  style={{ width: "100%" }}
                />
              </Form.Item>
            </Col>
          )}
          {(entry.type === "number" || entry.type === "integer") && (
            <>
              <Col span={6}>
                <Form.Item label={t("settings:schema.minimum")} style={{ marginBottom: 4 }}>
                  <InputNumber
                    value={entry.minimum}
                    onChange={(v) => handleChange("minimum", v)}
                    size="small"
                    style={{ width: "100%" }}
                  />
                </Form.Item>
              </Col>
              <Col span={6}>
                <Form.Item label={t("settings:schema.maximum")} style={{ marginBottom: 4 }}>
                  <InputNumber
                    value={entry.maximum}
                    onChange={(v) => handleChange("maximum", v)}
                    size="small"
                    style={{ width: "100%" }}
                  />
                </Form.Item>
              </Col>
            </>
          )}
        </Row>
      )}
      {/* Array: Item type → Item choices → Default (separate rows for clarity) */}
      {entry.type === "array" && (
        <>
          <Row gutter={8}>
            <Col span={4}>
              <Form.Item label={t("settings:schema.itemType")} style={{ marginBottom: 4 }}>
                <Select
                  value={entry.items_type}
                  onChange={(v) => handleChange("items_type", v)}
                  options={itemsTypeOptions}
                  size="small"
                />
              </Form.Item>
            </Col>
            <Col span={16}>
              <Form.Item label={t("settings:schema.itemChoices")} style={{ marginBottom: 4 }} extra={t("settings:schema.addOptionHelp")}>
                <Select
                  mode="tags"
                  value={entry.items_enum_vals}
                  onChange={(v) => {
                    // Validate each value against items_type
                    const validated = v.filter((item) => {
                      if (entry.items_type === "number") return !isNaN(Number(item));
                      if (entry.items_type === "integer") return Number.isInteger(Number(item));
                      return true; // string: no validation
                    });
                    handleChange("items_enum_vals", validated);
                  }}
                  placeholder={t("settings:schema.optionPlaceholder")}
                  size="small"
                  tokenSeparators={[","]}
                  open={false}
                  style={{ width: "100%" }}
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={8}>
            <Col span={24}>
              <Form.Item
                label={t("settings:schema.default")}
                style={{ marginBottom: error ? 0 : 4 }}
                validateStatus={error ? "error" : undefined}
                help={error || undefined}
              >
                {entry.items_enum_vals.length > 0 ? (
                  <Space wrap>
                    <Checkbox.Group
                      options={entry.items_enum_vals.map((v) => ({ value: v, label: v }))}
                      value={(() => {
                        try {
                          return JSON.parse(entry.default_val || "[]");
                        } catch {
                          return [];
                        }
                      })()}
                      onChange={(checked) => handleChange("default_val", JSON.stringify(checked))}
                    />
                    <Button
                      type="link"
                      size="small"
                      style={{ padding: 0, fontSize: 12 }}
                      onClick={() => {
                        const current = (() => {
                          try { return JSON.parse(entry.default_val || "[]") as string[]; }
                          catch { return []; }
                        })();
                        const allSelected = current.length === entry.items_enum_vals.length;
                        handleChange("default_val", JSON.stringify(allSelected ? [] : [...entry.items_enum_vals]));
                      }}
                    >
                      {(() => {
                        try {
                          const current = JSON.parse(entry.default_val || "[]") as string[];
                          return current.length === entry.items_enum_vals.length ? t("settings:schema.deselectAll") : t("settings:schema.selectAll");
                        } catch { return t("settings:schema.selectAll"); }
                      })()}
                    </Button>
                  </Space>
                ) : (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {t("settings:schema.addChoicesFirst")}
                  </Typography.Text>
                )}
              </Form.Item>
            </Col>
          </Row>
        </>
      )}
    </Card>
  );
}

let _nextRowId = 0;

function createEmptyEntry(): ParamEntry {
  return {
    _rowId: ++_nextRowId,
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
  };
}

export function buildSchemaFromEntries(entries: ParamEntry[]): Record<string, unknown> | null {
  if (entries.length === 0) return null;

  const properties: Record<string, unknown> = {};
  const requiredKeys: string[] = [];

  for (const entry of entries) {
    if (!entry.key.trim()) continue;

    const prop: Record<string, unknown> = { type: entry.type };
    if (entry.title) prop.title = entry.title;
    if (entry.description) prop.description = entry.description;

    // Parse default
    if (entry.default_val !== "") {
      if (entry.type === "boolean") {
        prop.default = entry.default_val === "true";
      } else if (entry.type === "number") {
        const n = Number(entry.default_val);
        if (!isNaN(n)) prop.default = n;
      } else if (entry.type === "integer") {
        const n = parseInt(entry.default_val, 10);
        if (!isNaN(n)) prop.default = n;
      } else if (entry.type === "array") {
        try {
          prop.default = JSON.parse(entry.default_val);
        } catch {
          // Keep as string if not valid JSON
        }
      } else {
        prop.default = entry.default_val;
      }
    }

    // Parse enum (string type)
    if (entry.type === "string" && entry.enum_vals.length > 0) {
      prop.enum = [...entry.enum_vals];
    }

    // Parse min/max (number/integer type)
    if ((entry.type === "number" || entry.type === "integer") && entry.minimum !== null) {
      prop.minimum = entry.minimum;
    }
    if ((entry.type === "number" || entry.type === "integer") && entry.maximum !== null) {
      prop.maximum = entry.maximum;
    }

    // Parse items type (array type)
    if (entry.type === "array" && entry.items_type) {
      prop.items = { type: entry.items_type };
      if (entry.items_enum_vals.length > 0) {
        (prop.items as Record<string, unknown>).enum = [...entry.items_enum_vals];
      }
    }

    properties[entry.key.trim()] = prop;

    if (entry.required) {
      requiredKeys.push(entry.key.trim());
    }
  }

  if (Object.keys(properties).length === 0) return null;

  return {
    type: "object",
    properties,
    required: requiredKeys,
  };
}

export function parseSchemaToEntries(schema: Record<string, unknown> | null): ParamEntry[] {
  if (!schema || !schema.properties || typeof schema.properties !== "object") return [];

  const requiredList = Array.isArray(schema.required) ? schema.required as string[] : [];

  return Object.entries(schema.properties as Record<string, Record<string, unknown>>).map(
    ([key, def]) => {
      const defaultVal = def.default;
      let defaultStr = "";
      if (defaultVal !== undefined) {
        if (typeof defaultVal === "boolean") {
          defaultStr = String(defaultVal);
        } else if (Array.isArray(defaultVal)) {
          defaultStr = JSON.stringify(defaultVal);
        } else {
          defaultStr = String(defaultVal);
        }
      }

      const enumArr = Array.isArray(def.enum) ? def.enum as string[] : [];

      const itemsType = def.items && typeof def.items === "object"
        ? (def.items as Record<string, unknown>).type as string ?? "string"
        : "string";

      const itemsEnumVals = def.items && typeof def.items === "object"
        && Array.isArray((def.items as Record<string, unknown>).enum)
        ? (def.items as Record<string, unknown>).enum as string[]
        : [];

      return {
        key,
        type: (def.type as ParamEntry["type"]) || "string",
        title: (def.title as string) || "",
        description: (def.description as string) || "",
        default_val: defaultStr,
        enum_vals: enumArr,
        items_enum_vals: itemsEnumVals,
        minimum: def.minimum != null ? Number(def.minimum) : null,
        maximum: def.maximum != null ? Number(def.maximum) : null,
        required: requiredList.includes(key),
        items_type: itemsType,
      };
    },
  );
}

/** Validate all entries, returning a map of index → error message. */
export function validateAllEntries(entries: ParamEntry[]): Map<number, string> {
  const errors = new Map<number, string>();
  entries.forEach((entry, i) => {
    const err = validateEntry(entry);
    if (err) errors.set(i, err);
  });
  return errors;
}

export default function ParameterSchemaBuilder({
  value,
  onChange,
}: ParameterSchemaBuilderProps) {
  const { t } = useTranslation("settings");
  // Ensure every entry has a stable _rowId for React list rendering
  const stableValue = useMemo(() => {
    let changed = false;
    const patched = value.map((entry) => {
      if (entry._rowId === undefined) {
        changed = true;
        return { ...entry, _rowId: ++_nextRowId };
      }
      return entry;
    });
    if (changed) {
      // Fire once to update parent with stable IDs
      setTimeout(() => onChange(patched), 0);
    }
    return patched;
  }, [value, onChange]);

  const handleAdd = useCallback(() => {
    onChange([...stableValue, createEmptyEntry()]);
  }, [stableValue, onChange]);

  const handleChange = useCallback(
    (index: number, updated: ParamEntry) => {
      const next = [...stableValue];
      next[index] = updated;
      onChange(next);
    },
    [stableValue, onChange],
  );

  const handleRemove = useCallback(
    (index: number) => {
      onChange(stableValue.filter((_, i) => i !== index));
    },
    [stableValue, onChange],
  );

  return (
    <div>
      <Typography.Text
        type="secondary"
        style={{ display: "block", marginBottom: 8, fontSize: 12 }}
      >
        {t("schema.builderDescription")}
      </Typography.Text>

      {stableValue.map((entry, index) => (
        <ParamEntryRow
          key={entry._rowId ?? index}
          entry={entry}
          index={index}
          onChange={handleChange}
          onRemove={handleRemove}
        />
      ))}

      <Button
        type="dashed"
        onClick={handleAdd}
        icon={<PlusOutlined />}
        style={{ width: "100%" }}
        size="small"
      >
        {t("schema.addParameter")}
      </Button>
    </div>
  );
}
