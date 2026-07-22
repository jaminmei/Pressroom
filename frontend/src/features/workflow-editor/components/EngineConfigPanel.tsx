import { Typography } from "antd";
import { useEffect, useMemo, useRef } from "react";

import DynamicForm from "./DynamicForm";
import ModelSelector from "./ModelSelector";
import ProviderSelector from "./ProviderSelector";
import { useProviders } from "../hooks/useProviders";
import { useWorkflowStore } from "../store";
import { buildDefaultValues } from "../utils/configDefaults";
import { getDefaultProvider } from "@/services/providerApi";
import type { NodeConfigSchema } from "@/types/node-registry";
import type { Provider, ProviderModel } from "@/types/provider";

export const ENGINE_CATEGORY_MAP: Record<string, string> = {
  "engine/model": "vlm",
  "engine/ocr": "ocr",
  "engine/text": "text",
  "engine/markitdown": "markitdown",
  "engine/docling": "docling",
  "processor/layout_detection": "layout_detection",
  "processor/image_enhance": "image_enhancement",
  "processor/rotate": "image_rotation",
};

function buildParamSchema(originalSchema: NodeConfigSchema): NodeConfigSchema {
  const entries = Object.entries(originalSchema.properties)
    .filter(([key]) => key !== "model")
    .map(([key, def]) => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { applicable_groups, ...rest } = def;
      return [key, rest];
    });

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { model_groups, ...schemaRest } = originalSchema;
  return {
    ...schemaRest,
    properties: Object.fromEntries(entries) as NodeConfigSchema["properties"],
  };
}

/** Build param schema for a given provider (used outside React render cycle). */
function getParamSchemaForProvider(
  provider: Provider,
  configSchema: NodeConfigSchema | undefined,
): NodeConfigSchema {
  if (!configSchema) return { type: "object" as const, properties: {} };
  if (provider.provider_type === "openai_compatible") return buildParamSchema(configSchema);
  const schema = provider.config_schema ?? provider.parameter_schema;
  if (provider.provider_type === "engine_service" && schema) {
    return schema as unknown as NodeConfigSchema;
  }
  return { type: "object" as const, properties: {} };
}

function clearSchemaDefaults(schema: NodeConfigSchema): Record<string, undefined> {
  return Object.fromEntries(Object.keys(schema.properties).map((key) => [key, undefined]));
}


export default function EngineConfigPanel() {
  const selectedNodeId = useWorkflowStore((s) => s.selectedNodeId);
  const nodes = useWorkflowStore((s) => s.nodes);
  const nodeConfigs = useWorkflowStore((s) => s.nodeConfigs);
  const uploadedFiles = useWorkflowStore((s) => s.uploadedFiles);
  const updateNodeConfig = useWorkflowStore((s) => s.updateNodeConfig);
  const setUploadedFile = useWorkflowStore((s) => s.setUploadedFile);
  const removeUploadedFile = useWorkflowStore((s) => s.removeUploadedFile);

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId],
  );

  const nodeType = selectedNode?.type ?? "";
  const engineCategory = ENGINE_CATEGORY_MAP[nodeType] ?? "";

  const { providers, loading } = useProviders(engineCategory);

  const nodeConfig = selectedNode
    ? (nodeConfigs[selectedNode.id] ?? selectedNode.data.config ?? {})
    : {};

  const providerId = nodeConfig.provider_id as string | undefined;

  const selectedProvider = useMemo(
    () => providers.find((p) => p.id === providerId) ?? null,
    [providers, providerId],
  );

  // Backward compat: auto-fill default provider when none selected
  const autofillAttempted = useRef(false);
  useEffect(() => {
    if (!selectedNode || !engineCategory || providerId || loading || autofillAttempted.current) {
      return;
    }

    autofillAttempted.current = true;
    getDefaultProvider(engineCategory)
      .then((defaultProvider) => {
        if (!defaultProvider) return;
        const patch: Record<string, unknown> = {
          provider_id: defaultProvider.id,
          provider_name: defaultProvider.name,
        };
        if (defaultProvider.provider_type === "openai_compatible") {
          const enabled = defaultProvider.models.filter((m) => m.is_enabled);
          patch.model = enabled.length === 1 ? enabled[0].model_id : undefined;
        }
        // Fill in param defaults from the provider's schema (not node registry)
        const providerSchema = getParamSchemaForProvider(
          defaultProvider,
          selectedNode.data.configSchema as NodeConfigSchema | undefined,
        );
        const paramDefaults = buildDefaultValues(providerSchema);
        Object.assign(patch, paramDefaults);
        updateNodeConfig(selectedNode.id, patch);
      })
      .catch(() => {
        // No default provider available — silently ignore
      });
  }, [selectedNode, engineCategory, providerId, loading, updateNodeConfig]);

  // Reset autofill flag when node changes
  useEffect(() => {
    autofillAttempted.current = false;
  }, [selectedNodeId]);

  // Build param schema based on provider type
  const paramSchema = useMemo(() => {
    if (!selectedProvider) return { type: "object" as const, properties: {} };
    return getParamSchemaForProvider(
      selectedProvider,
      selectedNode?.data.configSchema as NodeConfigSchema | undefined,
    );
  }, [selectedNode?.data.configSchema, selectedProvider]);

  const handleProviderChange = (provider: Provider) => {
    if (!selectedNode) return;
    const previousSchema = selectedProvider
      ? getParamSchemaForProvider(
          selectedProvider,
          selectedNode.data.configSchema as NodeConfigSchema | undefined,
        )
      : ({ type: "object", properties: {} } as NodeConfigSchema);
    const schema = getParamSchemaForProvider(
      provider,
      selectedNode.data.configSchema as NodeConfigSchema | undefined,
    );
    const paramDefaults = buildDefaultValues(schema);
    updateNodeConfig(selectedNode.id, {
      ...clearSchemaDefaults(previousSchema),
      provider_id: provider.id,
      provider_name: provider.name,
      model: undefined,
      ...paramDefaults,
    });
  };

  const handleModelChange = (model: ProviderModel) => {
    if (!selectedNode) return;
    updateNodeConfig(selectedNode.id, {
      model: model.model_id,
    });
  };

  if (!selectedNode) return null;

  return (
    <div data-testid="engine-config-panel">
      <ProviderSelector
        engineCategory={engineCategory}
        value={providerId}
        onChange={handleProviderChange}
      />

      {selectedProvider?.provider_type === "openai_compatible" && (
        <div data-testid="model-selector-area" style={{ marginTop: 12 }}>
          <ModelSelector
            provider={selectedProvider}
            value={nodeConfig.model as string | undefined}
            onChange={handleModelChange}
          />
        </div>
      )}

      {selectedProvider && Object.keys(paramSchema.properties).length > 0 && (
        <div style={{ marginTop: 12 }}>
          <DynamicForm
            nodeId={selectedNode.id}
            schema={paramSchema}
            value={{
              ...nodeConfig,
              ...(uploadedFiles[selectedNode.id]
                ? { file: uploadedFiles[selectedNode.id] }
                : {}),
            }}
            onChange={(nextConfig) => updateNodeConfig(selectedNode.id, nextConfig)}
            onFileChange={(fieldName, file) => {
              if (file) {
                setUploadedFile(selectedNode.id, file);
                updateNodeConfig(selectedNode.id, { [fieldName]: file.name });
                return;
              }
              removeUploadedFile(selectedNode.id);
              updateNodeConfig(selectedNode.id, { [fieldName]: undefined });
            }}
          />
        </div>
      )}

      {!selectedProvider && !loading && providers.length > 0 && (
        <Typography.Text
          type="secondary"
          style={{ display: "block", marginTop: 12 }}
        >
          Please select a provider to configure parameters.
        </Typography.Text>
      )}
    </div>
  );
}
