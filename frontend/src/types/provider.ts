// === Enums ===

export type ProviderType = 'openai_compatible' | 'engine_service';

export type ApiStyle = 'openai' | 'azure_openai';

export type ProviderScope = 'system' | 'workspace';

export type ProviderDefault = Provider | null;

export type AuthType = 'none' | 'api_key' | (string & {});

// === Model Types ===

export interface ProviderModel {
  id: string;
  provider_id: string;
  model_id: string;
  display_name: string;
  is_enabled: boolean;
  capabilities: string | null;
  default_config: string | null;
  model_group: string | null;
  sort_order: number;
}

export interface ProviderModelCreate {
  model_id: string;
  display_name: string;
}



// === Provider ===

export interface Provider {
  id: string;
  name: string;
  provider_type: ProviderType;
  scope?: ProviderScope;
  workspace_id?: string | null;
  engine_category: string;
  base_url: string;
  api_style: ApiStyle | null;
  api_version: string | null;
  has_api_key: boolean;
  auth_type: AuthType;
  auth_config_public: Record<string, string> | null; // non-secret auth config fields (e.g. client_id)
  env_config: Record<string, string> | null; // read-only env-sourced config for display
  is_enabled: boolean;
  is_default: boolean;
  config_schema: Record<string, unknown> | null;
  parameter_schema: Record<string, unknown> | null;
  extra_config: Record<string, unknown> | null;
  models: ProviderModel[];
  created_at: string;
  updated_at: string;
  health_url: string | null;
}

// === Request Types ===

export interface CreateProviderRequest {
  name: string;
  provider_type: ProviderType;
  engine_category: string;
  base_url: string;
  api_style?: ApiStyle | null;
  api_version?: string | null;
  api_key?: string | null;
  auth_type?: AuthType;
  auth_config?: Record<string, string> | null;
  health_url?: string | null;
}

export interface UpdateProviderRequest {
  name?: string | null;
  base_url?: string | null;
  api_style?: ApiStyle | null;
  api_version?: string | null;
  api_key?: string | null;
  auth_type?: AuthType | null;
  auth_config?: Record<string, string> | null;
  health_url?: string | null;
}

// === Response Types ===

export interface ModelTestResult {
  model_id: string;
  display_name: string | null;
  status: 'ok' | 'failed';
  latency_ms: number | null;
  error: string | null;
}

export interface TestConnectionResponse {
  status: 'healthy' | 'unhealthy' | 'no_health_url' | 'no_models';
  latency_ms: number | null;
  error: string | null;
  details: Record<string, unknown> | null;
  model_results: ModelTestResult[] | null;
}

export interface TestModelResponse {
  status: 'ok' | 'failed';
  latency_ms: number | null;
  error: string | null;
  model_response: string | null;
}

export interface DiscoverResponse {
  discovered: Array<Record<string, unknown>>;
  added: number;
  skipped: number;
  config_schema: Record<string, unknown> | null;
  schema_discovered: boolean;
  discovery_supported: boolean;
  message: string | null;
}
