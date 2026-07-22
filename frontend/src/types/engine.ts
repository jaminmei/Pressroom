// === Engine Types ===

export interface EngineTypeMeta {
  category: string;
  display_name: string;
  icon: string;
  description: string;
  default_provider_type: 'openai_compatible' | 'engine_service';
  supported_input_types: string[];
  response_formats: string[];
  allow_multiple_models: boolean;
}

export interface EnabledSummary {
  enabled: number;
  total: number;
}

export interface EngineWithProviders extends EngineTypeMeta {
  provider_count: number;
  enabled_summary: EnabledSummary | null;
}

export interface ProviderBrief {
  id: string;
  name: string;
  is_enabled: boolean;
  is_default: boolean;
  config_schema: Record<string, unknown> | null;
  parameter_schema: Record<string, unknown> | null;
}

export interface EngineDetail extends EngineTypeMeta {
  provider_count: number;
  enabled_summary: EnabledSummary | null;
  providers: ProviderBrief[];
}

export interface EngineListResponse {
  engines: EngineWithProviders[];
}

export interface ProviderHealthResult {
  provider_id: string;
  provider_name: string;
  status: 'healthy' | 'unhealthy' | 'unknown';
  latency_ms: number | null;
  error: string | null;
  checked_at: string;
}

export interface EngineHealthResponse {
  category: string;
  providers: ProviderHealthResult[];
  healthy_count: number;
  total_count: number;
}
