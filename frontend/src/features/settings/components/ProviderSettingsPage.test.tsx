import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Provider } from "@/types/provider";

let currentCaps: string[] = ["provider.manage"];

vi.mock("@/hooks/usePermission", () => ({
  usePermission: () => ({
    can: (cap: string) => currentCaps.includes(cap),
    explain: () => "mock reason",
    role: "Admin"
  })
}));

// --- Mock child components ---

vi.mock("./ProviderCard", () => ({
  default: ({
    provider,
    onEdit,
    onDelete,
    onSetDefault,
    onAddModel,
    onRemoveModel,
    onToggleModel,
    isDefault,
  }: {
    provider: Provider;
    onEdit: (p: Provider) => void;
    onDelete: (p: Provider) => void;
    onSetDefault: (p: Provider) => void;
    onTestConnection: (p: Provider) => void;
    onAddModel: (providerId: string, data: unknown) => Promise<void>;
    onRemoveModel: (providerId: string, modelId: string) => Promise<void>;
    onToggleModel: (providerId: string, modelId: string, isEnabled: boolean) => Promise<void>;
    isDefault?: boolean;
    isTesting: boolean;
    connectionResult: unknown;
  }) => (
    <div data-testid={`provider-card-${provider.id}`}>
      <span>{provider.name}</span>
      {provider.scope === "system" ? <span>System managed</span> : null}
      {isDefault ? <span>Effective default</span> : null}
      <button type="button" onClick={() => onEdit(provider)}>edit</button>
      <button type="button" onClick={() => onDelete(provider)}>delete</button>
      <button type="button" onClick={() => onSetDefault(provider)}>set default</button>
      <button type="button" onClick={() => void onAddModel(provider.id, {})}>add model</button>
      <button type="button" onClick={() => void onRemoveModel(provider.id, "model")}>remove model</button>
      <button type="button" onClick={() => void onToggleModel(provider.id, "model", false)}>toggle model</button>
    </div>
  ),
}));

vi.mock("./AddProviderDialog", () => ({
  default: ({ open }: { open: boolean }) =>
    open ? <div data-testid="add-dialog">Dialog Open</div> : null,
}));

// --- Mock provider API ---

vi.mock("@/services/providerApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/providerApi")>()),
  listProviders: vi.fn(),
  deleteProvider: vi.fn(),
  testConnection: vi.fn(),
  addModel: vi.fn(),
  removeModel: vi.fn(),
  toggleModel: vi.fn(),
  testModel: vi.fn(),
  setDefaultProvider: vi.fn(),
  getDefaultProvider: vi.fn(),
}));

vi.mock("@/features/workflow-editor/hooks/useProviders", () => ({
  useProviders: vi.fn(),
}));

// Mock antd message/notification to avoid DOM side effects
vi.mock("antd", async () => {
  const actual = await vi.importActual("antd");
  return {
    ...actual,
    message: {
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
      info: vi.fn(),
    },
    notification: {
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
      info: vi.fn(),
    },
  };
});

// --- Import after mocks ---

import ProviderSettingsPage, { ProviderSettingsContent } from "./ProviderSettingsPage";
import ProviderSelector from "@/features/workflow-editor/components/ProviderSelector";
import { useProviders } from "@/features/workflow-editor/hooks/useProviders";
import {
  addModel,
  assertWorkflowProvidersAvailable,
  deleteProvider,
  listProviders,
  removeModel,
  replaceVisibleProviders,
  toggleModel,
  setDefaultProvider,
  getDefaultProvider,
} from "@/services/providerApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

// --- Mock data ---

const mockProviders: Provider[] = [
  {
    id: "p1",
    name: "OpenAI Provider",
    provider_type: "openai_compatible",
    api_style: "openai",
    api_version: null,
    scope: "workspace",
    workspace_id: "workspace-a",
    engine_category: "vlm",
    base_url: "http://openai:8000",
    has_api_key: true,
    auth_config_public: null,
  env_config: null,
    auth_type: "api_key",
    is_enabled: true,
    is_default: true,
    config_schema: null,
    parameter_schema: null,
    extra_config: null,
    models: [],
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
    health_url: null,
  },
  {
    id: "p3",
    name: "Shared System Provider",
    provider_type: "openai_compatible",
    api_style: "openai",
    api_version: null,
    scope: "system",
    workspace_id: null,
    engine_category: "vlm",
    base_url: "http://system:8000",
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
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
    health_url: null,
  },
  {
    id: "p2",
    name: "OCR Engine",
    provider_type: "engine_service",
    api_style: null,
    api_version: null,
    scope: "system",
    workspace_id: null,
    engine_category: "ocr",
    base_url: "http://ocr:9000",
    has_api_key: false,
    auth_config_public: null,
  env_config: null,
    auth_type: "api_key",
    is_enabled: true,
    is_default: false,
    config_schema: null,
    parameter_schema: null,
    extra_config: null,
    models: [],
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
    health_url: null,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getDefaultProvider).mockResolvedValue(
    mockProviders.find((provider) => provider.id === "p1") ?? null,
  );
});

// Helper: wrap component in MemoryRouter
function renderPage() {
  return render(
    <MemoryRouter>
      <ProviderSettingsPage />
    </MemoryRouter>,
  );
}

describe("ProviderSettingsPage", () => {
  beforeEach(() => {
    currentCaps = ["provider.manage"];
  });

  it("T-PAGE-01: Groups visible providers by workspace ownership", async () => {
    vi.mocked(listProviders).mockResolvedValue(mockProviders);

    renderPage();

    // Initially shows loading spinner
    expect(document.querySelector(".ant-spin")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("provider-card-p1")).toBeInTheDocument();
    });

    // The card shows the provider name
    expect(screen.getByText("OpenAI Provider")).toBeInTheDocument();
    expect(screen.getByTestId("provider-card-p2")).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "Workspace Providers" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "System Providers" })).toBeInTheDocument();

    // Loading spinner gone
    expect(document.querySelector(".ant-spin")).not.toBeInTheDocument();
  });

  it("T-PAGE-02: Add Provider button opens AddProviderDialog", async () => {
    vi.mocked(listProviders).mockResolvedValue(mockProviders);

    renderPage();

    // Wait for providers to load
    await waitFor(() => {
      expect(screen.getByTestId("provider-card-p1")).toBeInTheDocument();
    });

    // Dialog should not be open initially
    expect(screen.queryByTestId("add-dialog")).not.toBeInTheDocument();

    // Click "Add Provider" button
    fireEvent.click(screen.getByRole("button", { name: /Add Provider/i }));

    // Dialog should now be visible
    expect(screen.getByTestId("add-dialog")).toBeInTheDocument();
  });

  it("T-PAGE-03: Engine service providers render instead of producing an empty state", async () => {
    const engineOnly = mockProviders.filter(p => p.provider_type === "engine_service");
    vi.mocked(listProviders).mockResolvedValue(engineOnly);

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("provider-card-p2")).toBeInTheDocument();
    });

    expect(document.querySelector(".ant-empty")).not.toBeInTheDocument();

    // Loading spinner gone
    expect(document.querySelector(".ant-spin")).not.toBeInTheDocument();
  });

  it("T-PAGE-04: Error state shows error Result", async () => {
    vi.mocked(listProviders).mockRejectedValue(new Error("Network error"));

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Failed to load providers")).toBeInTheDocument();
    });

    // Error subtitle shows the error message
    expect(screen.getByText("Network error")).toBeInTheDocument();

    // Retry button is available
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("T-PAGE-05: engine_service providers render in the System Providers section", async () => {
    vi.mocked(listProviders).mockResolvedValue(mockProviders);
    vi.mocked(getDefaultProvider).mockResolvedValue(
      mockProviders.find((provider) => provider.id === "p2") ?? null,
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("provider-card-p1")).toBeInTheDocument();
    });

    expect(screen.getByTestId("provider-card-p2")).toBeInTheDocument();
    expect(screen.getByText("OCR Engine")).toBeInTheDocument();
    expect(screen.getAllByText("Effective default").length).toBeGreaterThan(0);
  });

  it("T-PAGE-06: Page title is 'Model Providers'", async () => {
    vi.mocked(listProviders).mockResolvedValue(mockProviders);

    renderPage();

    // Title is rendered immediately, no need to wait for loading
    expect(screen.getByText("Model Providers")).toBeInTheDocument();
    expect(screen.getByTestId("provider-private-network-warning")).toHaveTextContent(
      "PROVIDER_ALLOW_PRIVATE_HOSTS=false",
    );
    await waitFor(() => {
      expect(screen.getByTestId("provider-card-p1")).toBeInTheDocument();
    });
  });

  it("T-PAGE-05: Disables Add Provider button when provider.manage capability is absent", async () => {
    currentCaps = [];
    vi.mocked(listProviders).mockResolvedValue([]);

    renderPage();

    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /add provider/i });
      expect(btn).toBeDisabled();
    });
  });

  it("renders the real provider manager as workspace-embedded content", async () => {
    vi.mocked(listProviders).mockResolvedValue([]);

    render(
      <MemoryRouter>
        <ProviderSettingsContent
          embedded
          title="Providers"
          description="Workspace-scoped provider configuration"
        />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("workspace-provider-settings")).toHaveClass("is-embedded");
    expect(screen.getByRole("heading", { name: "Providers" })).toBeInTheDocument();
    expect(screen.getByText("Workspace-scoped provider configuration")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/No providers configured for this workspace/i)).toBeInTheDocument();
    });
  });

  it("blocks every System Provider mutation", async () => {
    vi.mocked(listProviders).mockResolvedValue(mockProviders);

    renderPage();
    const card = await screen.findByTestId("provider-card-p3");
    for (const label of ["edit", "delete", "set default", "add model", "remove model", "toggle model"]) {
      fireEvent.click(card.querySelector(`button:nth-of-type(${["edit", "delete", "set default", "add model", "remove model", "toggle model"].indexOf(label) + 1})`) as HTMLButtonElement);
    }

    expect(card).toHaveTextContent("System managed");
    expect(deleteProvider).not.toHaveBeenCalled();
    expect(addModel).not.toHaveBeenCalled();
    expect(removeModel).not.toHaveBeenCalled();
    expect(toggleModel).not.toHaveBeenCalled();
    expect(setDefaultProvider).not.toHaveBeenCalled();
    expect(screen.queryByTestId("add-dialog")).not.toBeInTheDocument();
  });

  it("renders a foreign saved Provider as unavailable and blocks save/run payloads", async () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: mockProviders.filter((provider) => provider.provider_type === "openai_compatible"),
      loading: false,
      error: null,
      refetch: vi.fn(),
    });
    replaceVisibleProviders(mockProviders);

    render(
      <MemoryRouter>
        <ProviderSelector engineCategory="vlm" value="foreign-provider" onChange={vi.fn()} />
      </MemoryRouter>,
    );

    expect((await screen.findAllByText("Provider unavailable")).length).toBeGreaterThan(0);
    expect(screen.queryByText("foreign-provider")).not.toBeInTheDocument();
    expect(() => assertWorkflowProvidersAvailable({
      definition: { nodes: [{ config: { provider_id: "foreign-provider" } }] },
    })).toThrow("Provider unavailable");
    expect(() => assertWorkflowProvidersAvailable({
      workflow: { nodes: [{ config: { provider_id: "foreign-provider" } }] },
    })).toThrow("Provider unavailable");
  });

  it("clears provider state immediately when the workspace changes", async () => {
    let finishReload: ((providers: Provider[]) => void) | undefined;
    vi.mocked(listProviders)
      .mockResolvedValueOnce(mockProviders)
      .mockImplementationOnce(() => new Promise((resolve) => { finishReload = resolve; }));

    renderPage();
    expect(await screen.findByTestId("provider-card-p1")).toBeInTheDocument();

    act(() => {
      useWorkspaceStore.setState((state) => ({ contextGeneration: state.contextGeneration + 1 }));
    });

    await waitFor(() => {
      expect(screen.queryByTestId("provider-card-p1")).not.toBeInTheDocument();
      expect(screen.getByTestId("provider-settings-loading")).toBeInTheDocument();
    });
    await act(async () => {
      finishReload?.([]);
    });
  });
});
