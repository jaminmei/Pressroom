import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EngineConfigPanel from "./EngineConfigPanel";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import type { NodeConfigSchema } from "@/types/node-registry";
import type { Provider, ProviderModel } from "@/types/provider";

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

const mockModels: ProviderModel[] = [
  {
    id: "m1",
    provider_id: "p1",
    model_id: "gpt-4",
    display_name: "GPT-4",
    is_enabled: true,
    capabilities: null,
    default_config: null,
    model_group: "gpt_regular",
    sort_order: 0,
  },
  {
    id: "m2",
    provider_id: "p1",
    model_id: "gpt-5",
    display_name: "GPT-5",
    is_enabled: true,
    capabilities: null,
    default_config: null,
    model_group: "gpt_inference",
    sort_order: 1,
  },
];

const openaiProvider: Provider = {
  id: "p1",
  scope: "workspace",
  workspace_id: "workspace-test",
  name: "Vision Provider",
  provider_type: "openai_compatible",
  api_style: "openai",
  api_version: null,
  engine_category: "vlm",
  base_url: "http://vlm:8080",
  has_api_key: false,
  auth_type: "api_key",
  auth_config_public: null,
  env_config: null,
  is_enabled: true,
  is_default: true,
  config_schema: null,
  parameter_schema: null,
  extra_config: null,
  models: mockModels,
  created_at: "2026-01-01",
  updated_at: "2026-01-01",
  health_url: null,
};

const engineServiceProvider: Provider = {
  ...openaiProvider,
  id: "p2",
  name: "OCR Local",
  provider_type: "engine_service",
  api_style: null,
  api_version: null,
  config_schema: {
    type: "object",
    properties: {
      dpi: { type: "integer", default: 300, minimum: 72, maximum: 600, title: "DPI" },
      language: { type: "string", enum: ["eng", "chi_sim"], title: "Language" },
    },
    required: ["language"],
  } as unknown as Provider["config_schema"],
  models: [],
};

const engineServiceProviderNoSchema: Provider = {
  ...engineServiceProvider,
  id: "p3",
  name: "EasyOCR",
  config_schema: null,
  parameter_schema: null,
};

const engineSchema: NodeConfigSchema = {
  type: "object",
  properties: {
    model: {
      type: "string",
      enum: ["gpt-4", "gpt-5"],
      enum_metadata: {
        "gpt-4": { group: "gpt_regular", display_name: "GPT-4" },
        "gpt-5": { group: "gpt_inference", display_name: "GPT-5" },
      },
    },
    temperature: { type: "number", default: 0.7, minimum: 0, maximum: 2 },
    prompt: { type: "string", applicable_groups: ["gpt_inference"] },
  },
  required: ["model"],
  model_groups: {
    gpt_regular: { display_name: "Regular" },
    gpt_inference: { display_name: "Inference" },
  },
};

vi.mock("@/features/workflow-editor/hooks/useProviders", () => ({
  useProviders: vi.fn(),
}));

vi.mock("@/services/providerApi", () => ({
  getDefaultProvider: vi.fn(),
  replaceVisibleProviders: vi.fn(),
  resetProviderScopeState: vi.fn(),
}));

import { useProviders } from "@/features/workflow-editor/hooks/useProviders";
import { getDefaultProvider } from "@/services/providerApi";

function renderWithRouter(ui: React.ReactElement) {
  return render(<BrowserRouter>{ui}</BrowserRouter>);
}

function setupStore(nodeType: string, config: Record<string, unknown> = {}) {
  useWorkflowStore.setState({
    nodes: [
      {
        id: "engine_1",
        type: nodeType,
        data: {
          label: "VLM Engine",
          config,
          configSchema: engineSchema,
          inputTypes: ["image/*"],
          outputTypes: ["text/raw"],
        },
        position: { x: 100, y: 100 },
      },
    ],
    nodeConfigs: { engine_1: config },
    edges: [],
    uploadedFiles: {},
    selectedNodeId: "engine_1",
    nodeRegistry: {
      nodes: [],
      connection_rules: [],
    },
  });
}

describe("EngineConfigPanel", () => {
  beforeEach(() => {
    vi.mocked(getDefaultProvider).mockResolvedValue(null);
  });

  it("T-ENG-01: shows ProviderSelector + ModelSelector for openai_compatible", async () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: [openaiProvider],
      loading: false,
      error: null,
      refetch: vi.fn(),
    });
    setupStore("engine/model", { provider_id: "p1", model: "gpt-4" });

    renderWithRouter(<EngineConfigPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("engine-config-panel")).toBeInTheDocument();
    });

    // ProviderSelector renders as a combobox
    expect(screen.getAllByRole("combobox").length).toBeGreaterThanOrEqual(1);

    // ModelSelector should be rendered (openai_compatible has it)
    expect(screen.getByTestId("model-selector-area")).toBeInTheDocument();
  });

  it("T-ENG-02: shows ProviderSelector but no ModelSelector for engine_service", async () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: [engineServiceProvider],
      loading: false,
      error: null,
      refetch: vi.fn(),
    });
    setupStore("engine/ocr", { provider_id: "p2" });

    renderWithRouter(<EngineConfigPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("engine-config-panel")).toBeInTheDocument();
    });

    // ModelSelector should NOT be rendered for engine_service
    expect(screen.queryByTestId("model-selector-area")).not.toBeInTheDocument();
  });

  it("T-ENG-03: engine_service renders config_schema dynamic form", async () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: [engineServiceProvider],
      loading: false,
      error: null,
      refetch: vi.fn(),
    });
    setupStore("engine/ocr", { provider_id: "p2" });

    renderWithRouter(<EngineConfigPanel />);

    await waitFor(() => {
      // DPI field from engine_service config_schema
      expect(screen.getByText("DPI")).toBeInTheDocument();
    });
    expect(screen.getByText("Language")).toBeInTheDocument();
  });

  it("T-ENG-03b: engine_service without config_schema renders no params", async () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: [engineServiceProviderNoSchema],
      loading: false,
      error: null,
      refetch: vi.fn(),
    });
    setupStore("engine/ocr", { provider_id: "p3" });

    renderWithRouter(<EngineConfigPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("engine-config-panel")).toBeInTheDocument();
    });
    expect(screen.queryByText("DPI")).not.toBeInTheDocument();
    expect(screen.queryByText("Language")).not.toBeInTheDocument();
  });

  it("T-ENG-03c: provider change clears old provider params", async () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: [engineServiceProvider, engineServiceProviderNoSchema],
      loading: false,
      error: null,
      refetch: vi.fn(),
    });
    setupStore("engine/ocr", { provider_id: "p2", dpi: 300, language: "eng" });

    renderWithRouter(<EngineConfigPanel />);

    fireEvent.mouseDown(screen.getAllByRole("combobox")[0]);
    await waitFor(() => {
      fireEvent.click(screen.getByText("EasyOCR"));
    });

    const state = useWorkflowStore.getState();
    expect(state.nodeConfigs.engine_1.provider_id).toBe("p3");
    expect(state.nodeConfigs.engine_1.dpi).toBeUndefined();
    expect(state.nodeConfigs.engine_1.language).toBeUndefined();
  });

  it("T-ENG-04: provider change updates provider_id in store", async () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: [openaiProvider, engineServiceProvider],
      loading: false,
      error: null,
      refetch: vi.fn(),
    });
    setupStore("engine/model", {});

    renderWithRouter(<EngineConfigPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("engine-config-panel")).toBeInTheDocument();
    });

    // Open the provider dropdown and select the vision provider.
    fireEvent.mouseDown(screen.getAllByRole("combobox")[0]);

    await waitFor(() => {
      const options = screen.getAllByText(/Vision Provider/);
      fireEvent.click(options[0]);
    });

    const state = useWorkflowStore.getState();
    expect(state.nodeConfigs.engine_1.provider_id).toBe("p1");
  });

  it("T-ENG-05: model change updates model in store", async () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: [openaiProvider],
      loading: false,
      error: null,
      refetch: vi.fn(),
    });
    setupStore("engine/model", { provider_id: "p1" });

    renderWithRouter(<EngineConfigPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("engine-config-panel")).toBeInTheDocument();
    });

    // Open model dropdown
    const modelSelect = screen.getAllByRole("combobox")[1];
    fireEvent.mouseDown(modelSelect);

    await waitFor(() => {
      const options = screen.getAllByText("GPT-4");
      fireEvent.click(options[0]);
    });

    const state = useWorkflowStore.getState();
    expect(state.nodeConfigs.engine_1.model).toBe("gpt-4");
  });

  it("T-ENG-06: edit mode pre-selects provider + model from existing config", async () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: [openaiProvider],
      loading: false,
      error: null,
      refetch: vi.fn(),
    });
    setupStore("engine/model", { provider_id: "p1", model: "gpt-5" });

    renderWithRouter(<EngineConfigPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("engine-config-panel")).toBeInTheDocument();
    });

    // Provider and model should be pre-selected
    const state = useWorkflowStore.getState();
    expect(state.nodeConfigs.engine_1.provider_id).toBe("p1");
    expect(state.nodeConfigs.engine_1.model).toBe("gpt-5");
  });

  it("T-ENG-07: auto-fills default provider for old workflow without provider_id", async () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: [],
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    const singleModelProvider: Provider = {
      ...openaiProvider,
      models: [mockModels[0]],
    };
    vi.mocked(getDefaultProvider).mockResolvedValue(singleModelProvider);

    setupStore("engine/model", { model: "legacy-default" });

    renderWithRouter(<EngineConfigPanel />);

    await waitFor(() => {
      const state = useWorkflowStore.getState();
      expect(state.nodeConfigs.engine_1.provider_id).toBe("p1");
      expect(state.nodeConfigs.engine_1.model).toBe("gpt-4");
    });
  });

  it("clears a stale model when default-provider selection is ambiguous", async () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: [],
      loading: false,
      error: null,
      refetch: vi.fn(),
    });
    vi.mocked(getDefaultProvider).mockResolvedValue(openaiProvider);
    setupStore("engine/model", { model: "gpt-4.1" });

    renderWithRouter(<EngineConfigPanel />);

    await waitFor(() => {
      const state = useWorkflowStore.getState();
      expect(state.nodeConfigs.engine_1.provider_id).toBe("p1");
      expect(state.nodeConfigs.engine_1.model).toBeUndefined();
    });
  });
});
