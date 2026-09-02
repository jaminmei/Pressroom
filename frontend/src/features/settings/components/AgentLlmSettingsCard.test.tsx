import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import type { Provider } from "@/types/provider";

const listProviders = vi.fn();

vi.mock("@/services/providerApi", () => ({
  listProviders: (...args: readonly unknown[]) => listProviders(...args),
}));

vi.mock("@/stores/workspaceStore", () => ({
  useWorkspaceStore: Object.assign(
    (selector: (state: { contextGeneration: number }) => unknown) =>
      selector({ contextGeneration: 1 }),
    { getState: () => ({ contextGeneration: 1 }) },
  ),
}));

vi.mock("@/components/Permissions/PermissionButton", () => ({
  PermissionButton: ({ children, onClick }: { readonly children: ReactNode; readonly onClick: () => void }) => (
    <button onClick={onClick} type="button">{children}</button>
  ),
}));

vi.mock("./AddProviderDialog", () => ({
  default: ({ open, defaultCategory, defaultProviderType, defaultChatbotDefault }: {
    readonly open: boolean;
    readonly defaultCategory?: string;
    readonly defaultProviderType?: string;
    readonly defaultChatbotDefault?: boolean;
  }) => open ? (
    <div data-testid="agent-llm-dialog">
      {defaultCategory}:{defaultProviderType}:{String(defaultChatbotDefault)}
    </div>
  ) : null,
}));

import AgentLlmSettingsCard from "./AgentLlmSettingsCard";

const defaultProvider: Provider = {
  id: "agent-provider",
  name: "Workspace Agent",
  provider_type: "llm_api",
  api_style: null,
  api_version: null,
  api_protocol: "openai_responses",
  model_id: "gpt-agent",
  model_display_name: "GPT Agent",
  is_chatbot_default: true,
  chatbot_ready: true,
  scope: "workspace",
  workspace_id: "workspace-1",
  engine_category: "llm",
  base_url: "https://api.example/v1",
  has_api_key: true,
  auth_config_public: null,
  env_config: null,
  auth_type: "api_key",
  is_enabled: true,
  is_default: false,
  config_schema: null,
  parameter_schema: null,
  extra_config: null,
  models: [],
  created_at: "2026-08-18T00:00:00Z",
  updated_at: "2026-08-18T00:00:00Z",
  health_url: null,
};

describe("AgentLlmSettingsCard", () => {
  beforeEach(() => {
    listProviders.mockReset();
  });

  it("shows a dedicated empty configuration entry and opens the llm_api dialog", async () => {
    listProviders.mockResolvedValue([]);

    render(<AgentLlmSettingsCard />);

    expect(await screen.findByRole("heading", { name: /Agent \/ Chatbox LLM/ })).toBeInTheDocument();
    expect(screen.getByText("No Agent LLM configured")).toBeInTheDocument();
    expect(listProviders).toHaveBeenCalledWith({ provider_type: "llm_api" });

    fireEvent.click(screen.getByRole("button", { name: "Configure Agent LLM" }));
    expect(screen.getByTestId("agent-llm-dialog")).toHaveTextContent("llm:llm_api:true");
  });

  it("shows the workspace default model", async () => {
    listProviders.mockResolvedValue([defaultProvider]);

    render(<AgentLlmSettingsCard />);

    await waitFor(() => expect(screen.getByText("Workspace Agent")).toBeInTheDocument());
    expect(screen.getByText(/GPT Agent \(gpt-agent\)/)).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("shows the provider loading error details", async () => {
    listProviders.mockRejectedValue(new Error("workspace provider request failed"));

    render(<AgentLlmSettingsCard />);

    expect(await screen.findByText("Failed to load Agent LLM providers")).toBeInTheDocument();
    expect(screen.getByText("workspace provider request failed")).toBeInTheDocument();
  });
});
