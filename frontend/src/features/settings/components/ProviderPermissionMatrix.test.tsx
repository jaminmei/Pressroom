import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Provider } from "@/types/provider";
import type { EngineWithProviders } from "@/types/engine";
import type { WorkspaceCapability, WorkspaceRole } from "@/types/workspace";

let currentRole: WorkspaceRole = "owner";

vi.mock("@/hooks/usePermission", () => ({
  usePermission: () => ({
    can: (capability: WorkspaceCapability) =>
      capability === "provider.manage" && (currentRole === "owner" || currentRole === "admin"),
    explain: (capability: WorkspaceCapability) => ({
      allowed: capability === "provider.manage" && (currentRole === "owner" || currentRole === "admin"),
      capability,
      currentRole,
      allowedRoles: ["owner", "admin"],
      reason: "Requires owner, admin.",
    }),
    role: currentRole,
  }),
}));

vi.mock("@/services/providerApi", () => ({
  getProvider: vi.fn(),
  listProviders: vi.fn(),
  deleteProvider: vi.fn(),
  testConnection: vi.fn(),
  addModel: vi.fn(),
  removeModel: vi.fn(),
  toggleModel: vi.fn(),
  testModel: vi.fn(),
}));

import EngineSection from "./EngineSection";
import ModelToggleList from "./ModelToggleList";
import ProviderCard from "./ProviderCard";
import { testConnection } from "@/services/providerApi";

const provider: Provider = {
  id: "provider-1",
  name: "Workspace Provider",
  provider_type: "openai_compatible",
  api_style: "openai",
  api_version: null,
  scope: "workspace",
  workspace_id: "workspace-1",
  engine_category: "vlm",
  base_url: "https://provider.example",
  has_api_key: false,
  auth_config_public: null,
  env_config: null,
  auth_type: "none",
  is_enabled: true,
  is_default: false,
  config_schema: null,
  parameter_schema: null,
  extra_config: null,
  models: [],
  created_at: "2026-07-15T00:00:00Z",
  updated_at: "2026-07-15T00:00:00Z",
  health_url: null,
};

const engine: EngineWithProviders = {
  category: "ocr",
  display_name: "OCR",
  icon: "ocr",
  description: "OCR engine",
  default_provider_type: "engine_service",
  supported_input_types: [],
  response_formats: [],
  allow_multiple_models: false,
  provider_count: 0,
  enabled_summary: null,
};

const roles: readonly WorkspaceRole[] = ["owner", "admin", "editor", "runner", "viewer"];

afterEach(cleanup);

describe("Provider permission matrix", () => {
  it.each(roles)("gates Provider and model actions for %s", async (role) => {
    currentRole = role;
    const onTestConnection = vi.fn();
    const onToggle = vi.fn().mockResolvedValue(undefined);
    const onTestModel = vi.fn().mockResolvedValue({ status: "healthy", latency_ms: 1, error: null, model_response: null });

    render(
      <>
        <ProviderCard
          provider={provider}
          category="vlm"
          onEdit={vi.fn()}
          onDelete={vi.fn()}
          onSetDefault={vi.fn()}
          onTestConnection={onTestConnection}
          onAddModel={vi.fn().mockResolvedValue(undefined)}
          onRemoveModel={vi.fn().mockResolvedValue(undefined)}
          onToggleModel={vi.fn().mockResolvedValue(undefined)}
          onTestModel={onTestModel}
          isTesting={false}
          connectionResult={null}
        />
        <ModelToggleList
          models={[{ id: "model-1", provider_id: provider.id, model_id: "model-1", display_name: "Model 1", is_enabled: true, capabilities: null, default_config: null, model_group: null, sort_order: 0 }]}
          providerId={provider.id}
          onToggle={onToggle}
          onRemoveModel={vi.fn().mockResolvedValue(undefined)}
          onTestModel={onTestModel}
        />
      </>,
    );

    const isManager = role === "owner" || role === "admin";
    const connectionButton = screen.getByRole("button", { name: /Test Connection/ });
    const modelTestButton = screen
      .getAllByRole("button")
      .find((element) => element.textContent === "Test");
    const modelSwitch = screen.getByRole("switch");

    expect((connectionButton as HTMLButtonElement).disabled).toBe(!isManager);
    expect((modelTestButton as HTMLButtonElement | undefined)?.disabled).toBe(!isManager);
    expect(modelSwitch).toHaveProperty("disabled", !isManager);

    fireEvent.click(connectionButton);
    if (modelTestButton) fireEvent.click(modelTestButton);
    fireEvent.click(modelSwitch);

    await waitFor(() => {
      expect(onTestConnection).toHaveBeenCalledTimes(isManager ? 1 : 0);
      expect(onTestModel).toHaveBeenCalledTimes(isManager ? 1 : 0);
      expect(onToggle).toHaveBeenCalledTimes(isManager ? 1 : 0);
    });
  });

  it.each(roles)("gates Engine health checks for %s", (role) => {
    currentRole = role;
    vi.mocked(testConnection).mockResolvedValue({ status: "healthy", latency_ms: 1, error: null, details: null, model_results: null });

    render(<EngineSection engine={engine} />);

    const checkHealth = screen
      .getAllByRole("button", { name: /Check Health/ })
      .find((element) => element.tagName === "BUTTON");
    const isManager = role === "owner" || role === "admin";
    expect(checkHealth).toBeDefined();
    expect((checkHealth as HTMLButtonElement | undefined)?.disabled).toBe(!isManager);
  });
});
