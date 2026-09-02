// === Enums ===

export type ProviderType = 'openai_compatible' | 'engine_service' | 'llm_api';

export type ApiStyle = 'openai' | 'azure_openai';

export type ApiProtocol = 'openai_chat_completions' | 'openai_responses' | 'anthropic_messages';

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
  api_protocol?: ApiProtocol | null;
  model_id?: string | null;
  model_display_name?: string | null;
  model_context_window?: number | null;
  model_max_tokens?: number | null;
  model_reasoning?: boolean | null;
  has_api_key: boolean;
  auth_type: AuthType;
  auth_config_public: Record<string, string> | null; // non-secret auth config fields (e.g. client_id)
  env_config: Record<string, string> | null; // read-only env-sourced config for display
  is_enabled: boolean;
  is_default: boolean;
  is_chatbot_default?: boolean;
  chatbot_ready?: boolean;
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
  api_protocol?: ApiProtocol | null;
  api_key?: string | null;
  model_id?: string | null;
  model_display_name?: string | null;
  model_context_window?: number;
  model_max_tokens?: number;
  model_reasoning?: boolean;
  is_chatbot_default?: boolean;
  auth_type?: AuthType;
  auth_config?: Record<string, string> | null;
  health_url?: string | null;
}

export interface UpdateProviderRequest {
  name?: string | null;
  base_url?: string | null;
  api_style?: ApiStyle | null;
  api_version?: string | null;
  api_protocol?: ApiProtocol | null;
  api_key?: string | null;
  model_id?: string | null;
  model_display_name?: string | null;
  model_context_window?: number | null;
  model_max_tokens?: number | null;
  model_reasoning?: boolean | null;
  is_chatbot_default?: boolean | null;
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
  operation?: 'provider.test' | 'provider.health';
  target_type?: 'provider';
  target_id?: string;
  target_name?: string | null;
  status: 'healthy' | 'unhealthy' | 'unavailable';
  latency_ms: number | null;
  error_code?: string | null;
  error: string | null;
  checked_at?: string;
  details: Record<string, unknown> | null;
  model_results: ModelTestResult[] | null;
  provider_id?: string;
  provider_name?: string;
}

export interface TestModelResponse {
  operation?: 'provider.model.test';
  target_type?: 'model';
  target_id?: string;
  target_name?: string | null;
  status: 'healthy' | 'unhealthy' | 'unavailable';
  latency_ms: number | null;
  error_code?: string | null;
  error: string | null;
  checked_at?: string;
  model_response: string | null;
  provider_id?: string;
  provider_name?: string;
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

export interface ReadinessStepResult {
  name: string;
  status: 'pass' | 'fail' | 'skipped';
  detail: string | null;
}

export interface ReadinessTestResponse {
  provider_id: string;
  chatbot_ready: boolean;
  steps: ReadinessStepResult[];
}
