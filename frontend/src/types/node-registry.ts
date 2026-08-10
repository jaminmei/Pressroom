export interface NodeConfigSchemaBase {
  description?: string;
  default?: unknown;
  title?: string;
  applicable_groups?: string[];
}

export interface EnumMetadataItem {
  group?: string;
  display_name: string;
  [key: string]: unknown;  // Allow additional metadata like parent_model
}

export interface CascadeMetadata {
  depends_on: string | string[];  // Field(s) this property depends on
  filter_by?: string;  // Property in enum_metadata to filter by (for single dependency)
  mapping?: Record<string, unknown>;  // Direct mapping for complex dependencies
}

export interface NodeConfigSchemaString extends NodeConfigSchemaBase {
  type: "string";
  enum?: string[];
  enum_metadata?: Record<string, EnumMetadataItem>;
  minLength?: number;
  pattern?: string;
  schema_type?: "text" | "json";
  cascade_metadata?: CascadeMetadata;
}

export interface NodeConfigSchemaInteger extends NodeConfigSchemaBase {
  type: "integer" | "number";
  minimum?: number;
  maximum?: number;
}

export interface NodeConfigSchemaBoolean extends NodeConfigSchemaBase {
  type: "boolean";
}

export interface NodeConfigSchemaFile extends NodeConfigSchemaBase {
  type: "file";
  accept?: string[];
  max_size_mb?: number;
}

export interface NodeConfigSchemaArrayStringItems {
  type: "string";
  enum?: string[];
  enum_metadata?: Record<string, EnumMetadataItem>;
  minLength?: number;
}

export interface NodeConfigSchemaObject extends NodeConfigSchemaBase {
  type: "object";
  properties?: Record<string, NodeConfigSchemaProperty>;
  required?: string[];
}

export interface NodeConfigSchemaArrayObjectItems {
  type: "object";
  properties?: Record<string, NodeConfigSchemaProperty>;
  required?: string[];
}

export type NodeConfigSchemaArrayItems =
  | NodeConfigSchemaArrayStringItems
  | NodeConfigSchemaArrayObjectItems;

export interface NodeConfigSchemaArray extends NodeConfigSchemaBase {
  type: "array";
  items?: NodeConfigSchemaArrayItems;
  minItems?: number;
  cascade_metadata?: CascadeMetadata;
}

export type NodeConfigSchemaProperty =
  | NodeConfigSchemaString
  | NodeConfigSchemaInteger
  | NodeConfigSchemaBoolean
  | NodeConfigSchemaFile
  | NodeConfigSchemaArray
  | NodeConfigSchemaObject;

export interface ModelGroupInfo {
  display_name: string;
  description?: string;
}

export interface NodeConfigSchema {
  type: "object";
  properties: Record<string, NodeConfigSchemaProperty>;
  required?: string[];
  model_groups?: Record<string, ModelGroupInfo>;
}

export interface NodeRegistryCategory {
  category_id: string;
  display_name: string;
  description?: string;
}

export interface InputPortDef {
  name: string;
  accepted_types: string[];
  required: boolean;
  max_connections: number;
}

export interface NodeRegistryNode {
  node_type: string;
  display_name: string;
  category: string;
  description?: string;
  keywords?: string[];
  config_schema: NodeConfigSchema;
  input_types?: string[];
  output_types?: string[];
  input_ports?: InputPortDef[];
  max_inputs?: number;
  max_outputs?: number;
  pipeline_restriction?: "none" | "simple_only";
}

/**
 * @deprecated Category-based connection rules are no longer enforced.
 * Connection validity is determined by port-type (MIME) compatibility.
 * Kept for API backward compatibility (server returns empty array).
 */
export interface NodeRegistryConnectionRule {
  from_category: string;
  to_categories: string[];
}

export interface NodeRegistryResponse {
  version: string;
  categories: NodeRegistryCategory[];
  nodes: NodeRegistryNode[];
  connection_rules: NodeRegistryConnectionRule[];
}
