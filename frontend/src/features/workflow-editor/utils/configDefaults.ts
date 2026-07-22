import type { NodeConfigSchema } from "@/types/node-registry";

/**
 * Build a config object containing the default values defined in a schema.
 * Only properties with an explicit `default` field are included.
 */
export function buildDefaultValues(schema: NodeConfigSchema): Record<string, unknown> {
  return Object.entries(schema.properties).reduce<Record<string, unknown>>((acc, [fieldName, definition]) => {
    if (definition.default !== undefined) {
      acc[fieldName] = definition.default;
    }

    return acc;
  }, {});
}
