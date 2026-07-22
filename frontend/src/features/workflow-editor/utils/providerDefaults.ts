import type { NodeConfigSchema } from "@/types/node-registry";
import type { Provider } from "@/types/provider";
import { buildDefaultValues } from "@/features/workflow-editor/utils/configDefaults";

/**
 * Extract parameter defaults from a provider's config_schema / parameter_schema.
 * Used during auto-fill when creating engine-category nodes (template/drag-drop).
 *
 * For openai_compatible providers, schema comes from the node registry (passed in).
 * For engine_service providers, schema comes from provider.config_schema.
 */
export function getProviderParamDefaults(
  provider: Provider,
  nodeConfigSchema?: NodeConfigSchema,
  currentConfig?: Record<string, unknown>,
): Record<string, unknown> {
  let schema: NodeConfigSchema | null = null;

  if (provider.provider_type === "engine_service") {
    const raw = provider.config_schema ?? provider.parameter_schema;
    if (raw && typeof raw === "object" && "properties" in raw) {
      schema = raw as unknown as NodeConfigSchema;
    }
  } else if (nodeConfigSchema && Object.keys(nodeConfigSchema.properties).length > 0) {
    // openai_compatible: use node registry schema minus model field
    const entries = Object.entries(nodeConfigSchema.properties)
      .filter(([key]) => key !== "model");
    schema = { ...nodeConfigSchema, properties: Object.fromEntries(entries) as NodeConfigSchema["properties"] };
  }

  if (!schema) return {};

  const defaults = buildDefaultValues(schema);
  // Only fill keys not already set
  if (currentConfig) {
    return Object.fromEntries(
      Object.entries(defaults).filter(([key]) => currentConfig[key] === undefined),
    );
  }
  return defaults;
}
