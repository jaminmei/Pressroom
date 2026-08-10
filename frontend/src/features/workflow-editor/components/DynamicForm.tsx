import { Alert, Button, Checkbox, Form, Input, InputNumber, Select, Space, Switch, Typography } from "antd";
import { CodeOutlined, ExperimentOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import AdaptorTestWorkbench from "@/features/workflow-editor/components/AdaptorTestWorkbench";
import FileUploadField from "@/features/workflow-editor/components/FileUploadField";
import VariablePicker from "@/features/workflow-editor/components/VariablePicker";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import type { InputBinding } from "@/features/workflow-editor/types/inputBindings";
import SchemaEditorModal from "@/features/workflow-editor/components/SchemaEditorModal";
import { buildDefaultValues } from "@/features/workflow-editor/utils/configDefaults";
import { apiClient } from "@/services/api";
import type {
  CascadeMetadata,
  NodeConfigSchema,
  NodeConfigSchemaProperty,
  NodeConfigSchemaString
} from "@/types/node-registry";

const { Text } = Typography;

export interface DynamicFormProps {
  nodeId: string;
  nodeType?: string;
  schema: NodeConfigSchema;
  value: Record<string, unknown>;
  onChange: (nextValue: Record<string, unknown>) => void;
  onFileChange: (fieldName: string, file: File | null) => void;
}

function toFieldLabel(fieldName: string): string {
  return fieldName
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}


/**
 * Get the model group for a selected model value
 */
function getModelGroup(
  modelValue: string | undefined,
  schema: NodeConfigSchema
): string | null {
  if (!modelValue) return null;

  const modelProperty = schema.properties.model;
  if (!modelProperty || modelProperty.type !== "string") return null;

  const enumMetadata = modelProperty.enum_metadata;
  if (!enumMetadata || !enumMetadata[modelValue]) return null;

  return enumMetadata[modelValue].group ?? null;
}

/**
 * Check if a property should be visible based on the current model group and output_type
 */
function isPropertyVisible(
  fieldName: string,
  definition: NodeConfigSchemaProperty,
  currentModelGroup: string | null,
  currentOutputType: string | undefined
): boolean {
  // Always show the model selector itself
  if (fieldName === "model") return true;

  // Handle output_schema visibility based on output_type
  if (fieldName === "output_schema") {
    // Show output_schema only when output_type is "json_schema"
    return currentOutputType === "json_schema";
  }

  // Handle schema_template visibility based on output_type
  if (fieldName === "schema_template") {
    // Show schema_template only when output_type is "json_schema"
    return currentOutputType === "json_schema";
  }

  // Always show properties without applicable_groups restriction
  if (!definition.applicable_groups || definition.applicable_groups.length === 0) {
    return true;
  }

  // Show property only if current model group is in applicable_groups
  if (currentModelGroup === null) return false;
  return definition.applicable_groups.includes(currentModelGroup);
}

/**
 * Filter enum options based on cascade metadata
 */
function filterEnumByCascade(
  definition: NodeConfigSchemaProperty,
  formValues: Record<string, unknown>,
  allEnums: string[]
): string[] {
  // Get cascade_metadata from definition
  let cascadeMeta: CascadeMetadata | undefined;
  if ("cascade_metadata" in definition && definition.cascade_metadata) {
    cascadeMeta = definition.cascade_metadata;
  }

  if (!cascadeMeta) {
    return allEnums;
  }

  const { depends_on, filter_by, mapping } = cascadeMeta;

  // For array types, enum_metadata is in items
  const stringArrayItems = definition.type === "array" && definition.items?.type === "string"
    ? definition.items
    : undefined;
  const enumMetadata = stringArrayItems?.enum_metadata
    ?? (definition.type === "string" ? definition.enum_metadata : undefined);

  // Single dependency (e.g., model_file depends on model)
  if (typeof depends_on === "string") {
    const parentValue = formValues[depends_on] as string | undefined;
    if (!parentValue) return [];

    // Use filter_by to filter by metadata property
    if (filter_by && enumMetadata) {
      return allEnums.filter((enumValue) => {
        const metadata = enumMetadata[enumValue];
        return metadata?.[filter_by as keyof typeof metadata] === parentValue;
      });
    }

    // Use mapping to filter
    if (mapping && typeof mapping === "object" && parentValue in mapping) {
      const mappingEntry = mapping[parentValue as keyof typeof mapping];
      if (mappingEntry && typeof mappingEntry === "object" && "supported" in mappingEntry) {
        const supportedValues = (mappingEntry as { supported: string[] }).supported;
        return allEnums.filter((v) => supportedValues.includes(v));
      }
    }

    return allEnums;
  }

  // Multiple dependencies (e.g., selected_types depends on model and model_file)
  if (Array.isArray(depends_on) && mapping) {
    const depValues = depends_on.map((dep) => formValues[dep] as string | undefined);

    // All dependencies must have values
    if (depValues.some((v) => v === undefined || v === null || v === "")) {
      return [];
    }

    // Navigate the mapping structure
    let currentMapping: unknown = mapping;
    for (const depValue of depValues) {
      if (typeof currentMapping !== "object" || currentMapping === null) {
        return [];
      }
      currentMapping = (currentMapping as Record<string, unknown>)[depValue as string];
    }

    // Final value should be an array of supported options
    if (Array.isArray(currentMapping)) {
      return currentMapping;
    }

    return [];
  }

  return allEnums;
}

/**
 * Check if a field should be visible based on cascade dependencies
 */
function shouldShowCascadeField(
  definition: NodeConfigSchemaProperty,
  formValues: Record<string, unknown>
): boolean {
  if (!("cascade_metadata" in definition) || !definition.cascade_metadata) {
    return true;
  }

  const { depends_on } = definition.cascade_metadata;
  const deps = Array.isArray(depends_on) ? depends_on : [depends_on];

  // All dependencies must have values
  return deps.every((dep) => {
    const value = formValues[dep];
    return value !== undefined && value !== null && value !== "";
  });
}

function renderSchemaField(
  fieldName: string,
  definition: NodeConfigSchemaProperty,
  required: boolean,
  currentValue: unknown,
  onFileChange: (field: string, file: File | null) => void,
  schema: NodeConfigSchema,
  formValues: Record<string, unknown>,
  onOpenSchemaEditor?: (fieldName: string, currentValue?: string) => void,
  form?: ReturnType<typeof Form.useForm<Record<string, unknown>>>[0],
  onChange?: (nextValue: Record<string, unknown>) => void,
  isAdaptorNode = false
) {
  const fieldLabel = definition.title ?? definition.description ?? toFieldLabel(fieldName);

  if (definition.type === "file") {
    const fileValue = currentValue instanceof File ? currentValue : null;

    return (
      <div data-testid={`dynamic-field-${fieldName}`} key={fieldName}>
        <Form.Item label={fieldLabel} required={required}>
          <FileUploadField
            accept={definition.accept}
            file={fileValue}
            maxSizeMb={definition.max_size_mb}
            onFileChange={(file) => onFileChange(fieldName, file)}
          />
        </Form.Item>
      </div>
    );
  }

  if (definition.type === "string" && definition.enum) {
    // Apply cascade filtering
    const filteredEnums = filterEnumByCascade(
      definition,
      formValues,
      definition.enum
    );

    // Check if this is the model selector with enum_metadata
    const hasMetadata = definition.enum_metadata && Object.keys(definition.enum_metadata).length > 0;

    const options = hasMetadata
      ? filteredEnums.map((option) => ({
          value: option,
          label: definition.enum_metadata![option]?.display_name ?? option
        }))
      : filteredEnums.map((option) => ({ value: option, label: option }));

    // Group options by their group for better UX
    let selectOptions: Array<
      { value: string; label: string } | { label: string; options: Array<{ value: string; label: string }> }
    > = options;
    if (hasMetadata && schema.model_groups) {
      const groups: Record<string, typeof options> = {};

      filteredEnums.forEach((option) => {
        const metadata = definition.enum_metadata![option];
        const groupName = (metadata?.group as string | undefined) ?? "Other";
        const groupLabel = schema.model_groups?.[groupName]?.display_name ?? groupName;

        if (!groups[groupLabel]) {
          groups[groupLabel] = [];
        }
        groups[groupLabel].push({
          value: option,
          label: metadata?.display_name ?? option
        });
      });

      // Convert to option groups format for Select
      selectOptions = Object.entries(groups).map(([groupLabel, opts]) => ({
        label: groupLabel,
        options: opts
      }));
    }

    return (
      <div data-testid={`dynamic-field-${fieldName}`} key={fieldName}>
        <Form.Item label={fieldLabel} name={fieldName} required={required}>
          <Select
            options={selectOptions}
            showSearch
            optionFilterProp="label"
            placeholder={`Select ${fieldLabel.toLowerCase()}`}
            disabled={filteredEnums.length === 0}
          />
        </Form.Item>
      </div>
    );
  }

  if (definition.type === "string") {
    // Check if this is a JSON schema field
    const stringDefinition = definition as NodeConfigSchemaString;
    if (stringDefinition.schema_type === "json") {
      const currentSchemaValue = currentValue as string | undefined;

      return (
        <div data-testid={`dynamic-field-${fieldName}`} key={fieldName}>
          <Form.Item label={fieldLabel} required={required}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button
                icon={<CodeOutlined />}
                onClick={() => onOpenSchemaEditor?.(fieldName, currentSchemaValue)}
              >
                {currentSchemaValue ? 'Edit Schema' : 'Add Schema'}
              </Button>
              {currentSchemaValue && (
                <div style={{
                  maxHeight: 100,
                  overflow: 'auto',
                  background: '#f5f5f5',
                  padding: 8,
                  borderRadius: 4,
                  fontSize: 12
                }}>
                  <pre>{currentSchemaValue}</pre>
                </div>
              )}
            </Space>
          </Form.Item>
        </div>
      );
    }

    return (
      <div data-testid={`dynamic-field-${fieldName}`} key={fieldName}>
        <Form.Item label={fieldLabel} name={fieldName} required={required}>
          <Input.TextArea
            className={fieldName === "code" && isAdaptorNode ? "adaptor-processing-code" : undefined}
            data-testid={fieldName === "code" && isAdaptorNode ? "adaptor-processing-code" : undefined}
            placeholder={definition.description}
            rows={fieldName === "code" && isAdaptorNode ? 14 : fieldName === "prompt" ? 4 : 1}
            style={fieldName === "code" && isAdaptorNode ? {
              background: "#111827",
              borderColor: "#374151",
              color: "#e5e7eb",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              fontSize: 13,
              lineHeight: 1.6,
            } : undefined}
          />
        </Form.Item>
      </div>
    );
  }

  if (definition.type === "integer" || definition.type === "number") {
    const hasMin = definition.minimum != null;
    const hasMax = definition.maximum != null;
    const numVal = currentValue as number | undefined;
    const isOutOfRange = numVal != null
      && ((hasMin && numVal < definition.minimum!) || (hasMax && numVal > definition.maximum!));

    const handleBlur = () => {
      if (numVal == null || !form || !onChange) return;
      let clamped = numVal;
      if (hasMin && clamped < definition.minimum!) clamped = definition.minimum!;
      if (hasMax && clamped > definition.maximum!) clamped = definition.maximum!;
      if (clamped !== numVal) {
        form.setFieldsValue(
          { [fieldName]: clamped } as Parameters<typeof form.setFieldsValue>[0]
        );
        onChange({ ...formValues, [fieldName]: clamped });
      }
    };

    return (
      <div data-testid={`dynamic-field-${fieldName}`} key={fieldName}>
        <Form.Item
          label={fieldLabel}
          name={fieldName}
          required={required}
          extra={definition.description || undefined}
          validateStatus={isOutOfRange ? "error" : undefined}
          help={isOutOfRange ? `Value must be between ${definition.minimum ?? "-∞"} and ${definition.maximum ?? "∞"}` : undefined}
        >
          <InputNumber
            style={{ width: "100%" }}
            onBlur={handleBlur}
          />
        </Form.Item>
      </div>
    );
  }

  if (definition.type === "boolean") {
    return (
      <div data-testid={`dynamic-field-${fieldName}`} key={fieldName}>
        <Form.Item
          label={fieldLabel}
          name={fieldName}
          required={required}
          valuePropName="checked"
          extra={definition.description}
        >
          <Switch />
        </Form.Item>
      </div>
    );
  }

  if (definition.type === "array") {
    const stringItems = definition.items?.type === "string" ? definition.items : undefined;
    const objectItems = definition.items?.type === "object" ? definition.items : undefined;

    if (objectItems) {
      return (
        <div data-testid={`dynamic-field-${fieldName}`} key={fieldName}>
          <Form.Item
            label={fieldLabel}
            required={required}
            extra={definition.description}
          >
            <Input.TextArea
              value="This field is configured in the dedicated Adaptor editor in a later migration phase."
              disabled
              rows={2}
              aria-label={`${fieldLabel} deferred editor notice`}
            />
          </Form.Item>
        </div>
      );
    }

    // Apply cascade filtering
    const allEnums = stringItems?.enum ?? [];
    const filteredEnums = filterEnumByCascade(
      definition,
      formValues,
      allEnums
    );

    const itemEnumMetadata = stringItems?.enum_metadata;
    const hasItemMetadata = itemEnumMetadata != null && Object.keys(itemEnumMetadata).length > 0;

    const checkboxOptions = filteredEnums.map((option: string) => ({
      value: option,
      label: hasItemMetadata && itemEnumMetadata?.[option]
        ? itemEnumMetadata[option]?.display_name ?? option
        : option
    }));

    return (
      <div data-testid={`dynamic-field-${fieldName}`} key={fieldName}>
        <Form.Item
          label={fieldLabel}
          name={fieldName}
          required={required}
          extra={definition.description}
        >
          <Checkbox.Group
            options={checkboxOptions}
          />
        </Form.Item>
      </div>
    );
  }

  return null;
}

export default function DynamicForm({
  nodeId,
  nodeType,
  schema,
  value,
  onChange,
  onFileChange
}: DynamicFormProps) {
  const { t } = useTranslation("workflows");
  const [form] = Form.useForm<Record<string, unknown>>();
  type FormFieldValues = Parameters<typeof form.setFieldsValue>[0];
  const defaultValues = useMemo(() => buildDefaultValues(schema), [schema]);
  const mergedValue = useMemo(() => ({ ...defaultValues, ...value }), [defaultValues, value]);

  // Dynamic validation trigger for model changes
  const setDynamicWarnings = useWorkflowStore((s) => s.setDynamicWarnings);
  const setIsValidating = useWorkflowStore((s) => s.setIsValidating);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup debounce timer on unmount
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  const triggerDynamicValidation = useCallback(() => {
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }
    debounceTimerRef.current = setTimeout(async () => {
      try {
        setIsValidating(true);
        const { nodes, edges, nodeConfigs } = useWorkflowStore.getState();
        const definition = {
          nodes: nodes.map((n) => ({
            id: n.id,
            type: n.type,
            config: nodeConfigs[n.id] ?? n.data?.config ?? {},
          })),
          connections: edges.map((e) => ({
            source: e.source,
            target: e.target,
          })),
        };
        const response = await apiClient.post("/workflows/validate", definition);
        setDynamicWarnings(response.data?.dynamic?.warnings ?? []);
      } catch {
        // Dynamic validation failed — non-critical, silently ignore
      } finally {
        setIsValidating(false);
      }
    }, 300);
  }, [setDynamicWarnings, setIsValidating]);

  // Schema Editor Modal state
  const [schemaModalOpen, setSchemaModalOpen] = useState(false);
  const [editingSchemaField, setEditingSchemaField] = useState<string | null>(null);
  const [workbenchOpen, setWorkbenchOpen] = useState(false);

  // Handle opening schema editor
  const handleOpenSchemaEditor = (fieldName: string) => {
    setEditingSchemaField(fieldName);
    setSchemaModalOpen(true);
  };

  // Handle saving schema from modal
  const handleSchemaSave = (schemaValue: string) => {
    if (editingSchemaField) {
      const newValue = { ...mergedValue, [editingSchemaField]: schemaValue };
      form.setFieldsValue({ [editingSchemaField]: schemaValue } as FormFieldValues);
      onChange(newValue);
    }
    setSchemaModalOpen(false);
    setEditingSchemaField(null);
  };

  // Handle cancel from modal
  const handleSchemaCancel = () => {
    setSchemaModalOpen(false);
    setEditingSchemaField(null);
  };

  // Get current model group for filtering parameters
  const currentModelGroup = useMemo(() => {
    return getModelGroup(mergedValue.model as string | undefined, schema);
  }, [mergedValue.model, schema]);

  // Get current output type
  const currentOutputType = mergedValue.output_type as string | undefined;

  // Filter visible properties based on current model group, output_type, and cascade dependencies
  const resolvedNodeType = useMemo(() => {
    if (nodeType) {
      return nodeType;
    }
    return useWorkflowStore.getState().nodes.find((node) => node.id === nodeId)?.type;
  }, [nodeId, nodeType]);
  const isAdaptorNode = resolvedNodeType === "processor/adaptor";
  const edges = useWorkflowStore((state) => state.edges);
  const inputMode = (mergedValue.input_mode as string | undefined)
    ?? (Array.isArray(mergedValue.input_bindings) && mergedValue.input_bindings.length > 0 ? "custom_bindings" : "all_upstream");
  const inputBindings = useMemo(() => {
    const candidate = mergedValue.input_bindings;
    return Array.isArray(candidate) ? candidate as InputBinding[] : [];
  }, [mergedValue.input_bindings]);
  const showBindings = isAdaptorNode && inputMode === "custom_bindings";
  const hasDirectInputEdges = useMemo(
    () => edges.some((edge) => edge.target === nodeId && (edge.targetHandle == null || edge.targetHandle === "input")),
    [edges, nodeId]
  );

  const visibleProperties = useMemo(() => {
    return Object.entries(schema.properties).filter(([fieldName, definition]) => {
      if (isAdaptorNode && (fieldName === "input_mode" || fieldName === "input_bindings")) {
        return false;
      }
      const cascadeVisible = shouldShowCascadeField(definition, mergedValue);
      const isVisible = isPropertyVisible(fieldName, definition, currentModelGroup, currentOutputType) && cascadeVisible;
      return isVisible;
    });
  }, [schema.properties, currentModelGroup, currentOutputType, mergedValue, isAdaptorNode]);

  // Get model group info for display
  const currentModelGroupInfo = useMemo(() => {
    if (!currentModelGroup || !schema.model_groups) return null;
    return schema.model_groups[currentModelGroup];
  }, [currentModelGroup, schema.model_groups]);

  useEffect(() => {
    form.setFieldsValue(mergedValue as FormFieldValues);
  }, [form, mergedValue]);

  // Handle model change - reset parameters that don't apply to new model
  const handleValuesChange = (changedValues: Partial<Record<string, unknown>>, allValues: Record<string, unknown>) => {
    if (changedValues.input_mode !== undefined && isAdaptorNode) {
      const nextInputMode = changedValues.input_mode as string;
      const finalValues = {
        ...allValues,
        ...(nextInputMode === "all_upstream" ? { input_bindings: [] } : {})
      };
      form.setFieldsValue(finalValues as FormFieldValues);
      onChange(finalValues);
      return;
    }

    // If output_type changed away from "json_schema", clear the output_schema
    if (changedValues.output_type !== undefined) {
      if (changedValues.output_type !== "json_schema") {
        const resetValues: Record<string, unknown> = {
          output_schema: "",
          schema_template: ""
        };
        const finalValues = { ...allValues, ...resetValues };
        form.setFieldsValue(finalValues as FormFieldValues);
        onChange(finalValues);
        return;
      }
    }

    // If model changed, we might need to reset some parameters
    if (changedValues.model !== undefined) {
      const newModelGroup = getModelGroup(changedValues.model as string, schema);
      const resetValues: Record<string, unknown> = {};

      // Check each property and reset if it doesn't apply to new model group
      Object.entries(schema.properties).forEach(([fieldName, definition]) => {
        if (fieldName === "model") return;

        if (definition.applicable_groups && definition.applicable_groups.length > 0) {
          if (!newModelGroup || !definition.applicable_groups.includes(newModelGroup)) {
            // Reset to default value
            if (definition.default !== undefined) {
              resetValues[fieldName] = definition.default;
            } else {
              resetValues[fieldName] = undefined;
            }
          }
        }
      });

      // Merge reset values with all values
      const finalValues = { ...allValues, ...resetValues };
      form.setFieldsValue(finalValues as FormFieldValues);
      onChange(finalValues);
      triggerDynamicValidation();
      return;
    }

    // Generic cascade reset: when any field changes, reset dependent fields to defaults
    const changedFieldNames = Object.keys(changedValues);
    const cascadeResets: Record<string, unknown> = {};

    Object.entries(schema.properties).forEach(([fieldName, definition]) => {
      if (changedFieldNames.includes(fieldName)) return;
      const cascadeMeta = "cascade_metadata" in definition ? definition.cascade_metadata : undefined;
      if (!cascadeMeta?.depends_on) return;
      const deps = Array.isArray(cascadeMeta.depends_on)
        ? cascadeMeta.depends_on
        : [cascadeMeta.depends_on];
      if (deps.some((dep) => changedFieldNames.includes(dep))) {
        cascadeResets[fieldName] = definition.default ?? undefined;
      }
    });

    if (Object.keys(cascadeResets).length > 0) {
      const finalValues = { ...allValues, ...cascadeResets };
      form.setFieldsValue(finalValues as FormFieldValues);
      onChange(finalValues);
      return;
    }

    onChange(allValues);
  };

  return (
    <Form
      form={form}
      layout="vertical"
      onValuesChange={handleValuesChange}
    >
      {isAdaptorNode ? (
        <>
          <Form.Item label={t("editorText.inputMode")} name="input_mode">
            <Select
              options={[
                { label: t("editorText.inputModeAllUpstream"), value: "all_upstream" },
                { label: t("editorText.inputModeCustomBindings"), value: "custom_bindings" }
              ]}
              value={inputMode}
            />
          </Form.Item>

          {showBindings ? (
            <VariablePicker
              bindings={inputBindings}
              nodeId={nodeId}
              onChange={(nextBindings) => onChange({ ...mergedValue, input_mode: "custom_bindings", input_bindings: nextBindings })}
            />
          ) : null}

          {showBindings && inputBindings.length > 0 && hasDirectInputEdges ? (
            <Alert
              data-testid="adaptor-binding-edge-warning"
              description={t("editorText.adaptorBindingsDirectEdgeWarningDescription")}
              message={t("editorText.adaptorBindingsDirectEdgeWarning")}
              showIcon
              style={{ marginBottom: 16 }}
              type="warning"
            />
          ) : null}
        </>
      ) : null}

      {/* Show current model group info */}
      {currentModelGroupInfo && (
        <div style={{ marginBottom: 16, padding: '8px 12px', background: '#f5f5f5', borderRadius: 6 }}>
          <Text type="secondary">
            {currentModelGroupInfo.description}
          </Text>
        </div>
      )}

      {visibleProperties.map(([fieldName, definition]) =>
        renderSchemaField(
          fieldName,
          definition,
          schema.required?.includes(fieldName) ?? false,
          mergedValue[fieldName],
          onFileChange,
          schema,
          mergedValue,
          handleOpenSchemaEditor,
          form,
          onChange,
          isAdaptorNode
        )
      )}

      {isAdaptorNode ? (
        <>
          <Button icon={<ExperimentOutlined />} onClick={() => setWorkbenchOpen(true)} style={{ marginTop: 12 }}>
            Open Test Workbench
          </Button>
          <Typography.Text type="secondary" style={{ display: "block", marginTop: 4 }}>
            Load upstream scope, inspect outputs, test adaptor code, then apply the verified draft.
          </Typography.Text>
          <AdaptorTestWorkbench nodeId={nodeId} open={workbenchOpen} onClose={() => setWorkbenchOpen(false)} />
        </>
      ) : null}

      {/* Schema Editor Modal */}
      <SchemaEditorModal
        open={schemaModalOpen}
        initialValue={editingSchemaField ? (mergedValue[editingSchemaField] as string | undefined) : undefined}
        onSave={handleSchemaSave}
        onCancel={handleSchemaCancel}
      />
    </Form>
  );
}
