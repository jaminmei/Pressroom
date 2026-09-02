import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Form, Input, message } from "antd";
import { MemoryRouter } from "react-router-dom";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { Provider } from "@/types/provider";
import { authTypeRegistry } from "@/types/authTypeRegistry";

// --- Mocks ---

vi.mock("@/services/providerApi", () => ({
  createProvider: vi.fn(),
  updateProvider: vi.fn(),
  runReadinessTest: vi.fn(),
}));

vi.mock("@/hooks/usePermission", () => ({
  usePermission: () => ({ can: () => true, explain: vi.fn(), role: "admin" }),
}));

// Mock antd message to avoid DOM side effects
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
  };
});

// --- Import after mocks ---

import AddProviderDialog from "./AddProviderDialog";
import { createProvider, runReadinessTest, updateProvider } from "@/services/providerApi";

// --- Mock data ---

const mockProvider: Provider = {
  id: "p1",
  name: "Test Provider",
  provider_type: "openai_compatible",
  api_style: "openai",
  api_version: null,
  api_protocol: null,
  model_id: null,
  model_display_name: null,
  engine_category: "vlm",
  base_url: "http://test:8000",
  has_api_key: true,
  auth_config_public: null,
  env_config: null,
  auth_type: "api_key",
  is_enabled: true,
  is_default: false,
  is_chatbot_default: false,
  config_schema: null,
  parameter_schema: null,
  extra_config: null,
  models: [],
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
  health_url: null,
};

const CUSTOM_AUTH_TYPE = "signed_request";

function SignedRequestAuthForm() {
  return (
    <>
      <Form.Item name="signed_client_id" label="Client ID">
        <Input />
      </Form.Item>
      <Form.Item name="signed_client_secret" label="Client Secret">
        <Input.Password />
      </Form.Item>
    </>
  );
}

beforeAll(() => {
  authTypeRegistry.register({
    id: CUSTOM_AUTH_TYPE,
    label: "Signed Request",
    FormComponent: SignedRequestAuthForm,
    DisplayComponent: null,
    hydrateFormValues: (provider) => ({
      signed_client_id: provider.auth_config_public?.client_id,
      signed_client_secret: undefined,
    }),
    extractAuthConfig: (values) => {
      const config: Record<string, string> = {};
      if (typeof values.signed_client_id === "string" && values.signed_client_id.trim()) {
        config.client_id = values.signed_client_id.trim();
      }
      if (
        typeof values.signed_client_secret === "string"
        && values.signed_client_secret.trim()
      ) {
        config.client_secret = values.signed_client_secret;
      }
      return config;
    },
  });
});

afterAll(() => {
  authTypeRegistry.unregister(CUSTOM_AUTH_TYPE);
});

const defaultProps: {
  open: boolean;
  provider: Provider | null;
  onCancel: ReturnType<typeof vi.fn>;
  onSuccess: ReturnType<typeof vi.fn>;
  defaultCategory?: string;
  defaultProviderType?: "openai_compatible" | "engine_service" | "llm_api";
  defaultChatbotDefault?: boolean;
} = {
  open: true,
  provider: null,
  onCancel: vi.fn(),
  onSuccess: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(createProvider).mockResolvedValue({} as Provider);
  vi.mocked(updateProvider).mockResolvedValue({} as Provider);
});

// Helper: wrap component in MemoryRouter
function renderDialog(overrides: Partial<typeof defaultProps> = {}) {
  const props = { ...defaultProps, ...overrides };
  return render(
    <MemoryRouter>
      <AddProviderDialog {...props} />
    </MemoryRouter>,
  );
}

describe("AddProviderDialog", () => {
  // ---------------------------------------------------------------
  // T-DIALOG-01: Create mode renders the expected fields and
  // does NOT render removed fields (Engine Category,
  // Response Format, Extra Config, Provider Type).
  // ---------------------------------------------------------------
  it("T-DIALOG-01: Create mode renders API Style and the core provider fields", () => {
    renderDialog();

    expect(screen.getByText("Add Model Provider")).toBeInTheDocument();

    // Fields that SHOULD be present
    expect(screen.getByLabelText("Name")).toBeInTheDocument();
    expect(screen.getByLabelText("API Style")).toBeInTheDocument();
    expect(screen.getByLabelText("Auth Type")).toBeInTheDocument();

    // Default auth_type is api_key, so Base URL and API Key should be visible
    expect(screen.getByLabelText("Base URL")).toBeInTheDocument();
    expect(screen.getByLabelText("API Key")).toBeInTheDocument();

    // Fields that were REMOVED — should NOT be present
    expect(screen.queryByText("Engine Category")).not.toBeInTheDocument();
    expect(screen.queryByText("Response Format")).not.toBeInTheDocument();
    expect(screen.queryByText("Extra Config")).not.toBeInTheDocument();
    // Provider Type selector replaces the removed full form schema (vlm create mode)
    expect(screen.getByLabelText("Provider Type")).toBeInTheDocument();

    // Health URL should NOT be present for openai_compatible (VLM) providers
    expect(screen.queryByLabelText("Health URL")).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------
  // T-DIALOG-02: Edit mode renders "Edit Model Provider" title
  // and pre-fills name and base_url from the provider prop.
  // ---------------------------------------------------------------
  it("T-DIALOG-02: Edit mode renders 'Edit Model Provider' title and pre-fills name + base_url", () => {
    renderDialog({ provider: mockProvider });

    expect(screen.getByText("Edit Model Provider")).toBeInTheDocument();

    const nameInput = screen.getByLabelText("Name") as HTMLInputElement;
    expect(nameInput.value).toBe("Test Provider");

    // api_key auth type: Base URL should be rendered and pre-filled
    const baseUrlInput = screen.getByLabelText("Base URL") as HTMLInputElement;
    expect(baseUrlInput.value).toBe("http://test:8000");
  });

  // ---------------------------------------------------------------
  // T-DIALOG-03: Submit in create mode calls createProvider()
  // with name, base_url, provider_type: "openai_compatible",
  // engine_category: "vlm", auth_type: "api_key".
  // ---------------------------------------------------------------
  it("T-DIALOG-03: Submit create calls createProvider with base_url for api_key auth", async () => {
    renderDialog();

    const nameInput = screen.getByLabelText("Name");
    fireEvent.change(nameInput, { target: { value: "New Provider" } });

    const baseUrlInput = screen.getByLabelText("Base URL");
    fireEvent.change(baseUrlInput, { target: { value: "https://api.example.com" } });

    // Auth Type defaults to api_key — no need to change it

    const submitBtn = screen.getByRole("button", { name: "Create" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(createProvider).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "New Provider",
          provider_type: "openai_compatible",
          engine_category: "vlm",
          api_style: "openai",
          api_version: null,
          auth_type: "api_key",
          base_url: "https://api.example.com",
        }),
      );
    });
  });

  // ---------------------------------------------------------------
  // T-DIALOG-04: Submit in edit mode calls updateProvider()
  // with the provider id and base_url for api_key auth.
  // ---------------------------------------------------------------
  it("T-DIALOG-04: Submit edit calls updateProvider with provider id and base_url", async () => {
    renderDialog({ provider: mockProvider });

    const submitBtn = screen.getByRole("button", { name: "Save" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(updateProvider).toHaveBeenCalledWith("p1", expect.objectContaining({
        name: "Test Provider",
        api_style: "openai",
        api_version: null,
        auth_type: "api_key",
        base_url: "http://test:8000",
      }));
    });
  });

  it("requires and submits an API version for Azure OpenAI", async () => {
    renderDialog();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Azure Provider" } });
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "https://example-resource.openai.azure.com" },
    });
    fireEvent.mouseDown(screen.getByLabelText("API Style"));
    fireEvent.click(screen.getByText("Azure OpenAI"));

    const versionInput = screen.getByLabelText("Azure API Version");
    fireEvent.change(versionInput, { target: { value: " 2025-04-01-preview " } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(createProvider).toHaveBeenCalledWith(expect.objectContaining({
        api_style: "azure_openai",
        api_version: "2025-04-01-preview",
      }));
    });
  });

  it("hides protocol fields and sends null protocol metadata for engine services", async () => {
    renderDialog({ defaultProviderType: "engine_service", defaultCategory: "ocr" });

    expect(screen.queryByLabelText("API Style")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Azure API Version")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "OCR Service" } });
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "http://ocr-engine:8080" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(createProvider).toHaveBeenCalledWith(expect.objectContaining({
        provider_type: "engine_service",
        engine_category: "ocr",
        api_style: null,
        api_version: null,
      }));
    });
  });

  it("submits llm_api required fields", async () => {
    renderDialog({ defaultProviderType: "llm_api" });

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Chat" } });
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "https://api.example/v1" } });
    fireEvent.mouseDown(screen.getByLabelText("API Protocol"));
    fireEvent.click(screen.getByText("OpenAI Responses"));
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "secret" } });
    fireEvent.change(screen.getByLabelText("Model ID"), { target: { value: "gpt-test" } });
    fireEvent.change(screen.getByLabelText("Context Window (tokens)"), {
      target: { value: "200000" },
    });
    fireEvent.change(screen.getByLabelText("Maximum Output Tokens"), {
      target: { value: "8192" },
    });
    fireEvent.click(screen.getByLabelText("Model supports reasoning / thinking"));
    fireEvent.click(screen.getByLabelText("Make workspace chatbot default"));
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(createProvider).toHaveBeenCalledWith(expect.objectContaining({
        provider_type: "llm_api",
        engine_category: "llm",
        api_protocol: "openai_responses",
        model_id: "gpt-test",
        model_context_window: 200000,
        model_max_tokens: 8192,
        model_reasoning: true,
        is_chatbot_default: true,
      }));
    });
    expect(screen.getByText(/Changes apply to new sessions or after Refresh/)).toBeInTheDocument();
  });

  it("rejects maximum output tokens above the context window", async () => {
    renderDialog({ defaultProviderType: "llm_api" });

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Chat" } });
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "https://api.example/v1" },
    });
    fireEvent.mouseDown(screen.getByLabelText("API Protocol"));
    fireEvent.click(screen.getByText("OpenAI Chat Completions"));
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "secret" } });
    fireEvent.change(screen.getByLabelText("Model ID"), { target: { value: "gpt-test" } });
    fireEvent.change(screen.getByLabelText("Context Window (tokens)"), {
      target: { value: "2048" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText("Maximum output tokens cannot exceed the context window"),
    ).toBeInTheDocument();
    expect(createProvider).not.toHaveBeenCalled();
  });

  it("reaches the llm_api branch through the Provider Type selector", async () => {
    renderDialog();

    expect(screen.queryByLabelText("API Protocol")).not.toBeInTheDocument();
    expect(screen.getByLabelText("API Style")).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByLabelText("Provider Type"));
    fireEvent.click(screen.getByText("LLM API (chatbot)"));

    await waitFor(() => {
      expect(screen.getByLabelText("API Protocol")).toBeInTheDocument();
    });
    expect(screen.queryByLabelText("API Style")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Chat" } });
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "https://api.example/v1" } });
    fireEvent.mouseDown(screen.getByLabelText("API Protocol"));
    fireEvent.click(screen.getByText("OpenAI Chat Completions"));
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "secret" } });
    fireEvent.change(screen.getByLabelText("Model ID"), { target: { value: "gpt-test" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(createProvider).toHaveBeenCalledWith(expect.objectContaining({
        provider_type: "llm_api",
        engine_category: "llm",
        api_protocol: "openai_chat_completions",
        model_id: "gpt-test",
      }));
    });
  });

  it("clears endpoint credentials when the Provider Type changes", async () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "https://vlm.example/v1" },
    });
    fireEvent.change(screen.getByLabelText("API Key"), {
      target: { value: "vlm-secret" },
    });

    fireEvent.mouseDown(screen.getByLabelText("Provider Type"));
    fireEvent.click(screen.getByText("LLM API (chatbot)"));

    await waitFor(() => expect(screen.getByLabelText("API Protocol")).toBeInTheDocument());
    expect(screen.getByLabelText("Base URL")).toHaveValue("");
    expect(screen.getByLabelText("API Key")).toHaveValue("");
  });

  it("restores the requested chatbot default when switching back to llm_api", async () => {
    renderDialog({ defaultChatbotDefault: true });

    fireEvent.mouseDown(screen.getByLabelText("Provider Type"));
    fireEvent.click(screen.getByText("LLM API (chatbot)"));

    await waitFor(() => {
      expect(screen.getByLabelText("Make workspace chatbot default")).toBeChecked();
    });

    fireEvent.mouseDown(screen.getByLabelText("Provider Type"));
    fireEvent.click(screen.getByText("OpenAI-compatible"));
    await waitFor(() => {
      expect(screen.queryByLabelText("Make workspace chatbot default")).not.toBeInTheDocument();
    });

    fireEvent.mouseDown(screen.getByLabelText("Provider Type"));
    fireEvent.click(screen.getByText("LLM API (chatbot)"));
    await waitFor(() => {
      expect(screen.getByLabelText("Make workspace chatbot default")).toBeChecked();
    });
  });

  it("creates a custom-auth provider with an explicit base URL and plugin config", async () => {
    renderDialog();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Signed Provider" } });
    fireEvent.mouseDown(screen.getByLabelText("Auth Type"));
    fireEvent.click(screen.getByText("Signed Request"));

    const baseUrl = await screen.findByLabelText("Base URL");
    fireEvent.change(baseUrl, { target: { value: " https://signed.example/v1 " } });
    fireEvent.change(await screen.findByLabelText("Client ID"), {
      target: { value: "client-new" },
    });
    fireEvent.change(screen.getByLabelText("Client Secret"), {
      target: { value: "secret-new" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(createProvider).toHaveBeenCalledWith(expect.objectContaining({
        name: "Signed Provider",
        auth_type: CUSTOM_AUTH_TYPE,
        base_url: "https://signed.example/v1",
        auth_config: {
          client_id: "client-new",
          client_secret: "secret-new",
        },
      }));
    });
  });

  it("hydrates custom-auth edits and omits an unchanged secret", async () => {
    const customProvider: Provider = {
      ...mockProvider,
      auth_type: CUSTOM_AUTH_TYPE,
      auth_config_public: { client_id: "client-existing" },
      base_url: "https://signed.example/v1",
    };
    renderDialog({ provider: customProvider });

    const clientId = await screen.findByLabelText("Client ID") as HTMLInputElement;
    expect(clientId.value).toBe("client-existing");
    expect((screen.getByLabelText("Client Secret") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Base URL") as HTMLInputElement).value).toBe(
      "https://signed.example/v1",
    );

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateProvider).toHaveBeenCalledTimes(1));
    const [, payload] = vi.mocked(updateProvider).mock.calls[0];
    expect(payload).toEqual(expect.objectContaining({
      auth_type: CUSTOM_AUTH_TYPE,
      base_url: "https://signed.example/v1",
      auth_config: { client_id: "client-existing" },
    }));
    expect(payload.auth_config).not.toHaveProperty("client_secret");
    expect(payload).not.toHaveProperty("api_key");
  });

  it("runs readiness test and renders success state", async () => {
    const llmProvider: Provider = {
      ...mockProvider,
      provider_type: "llm_api",
      base_url: "https://api.example/v1",
      api_protocol: "openai_chat_completions",
      model_id: "gpt-test",
      model_display_name: null,
      is_chatbot_default: false,
      chatbot_ready: false,
    };
    renderDialog({ provider: llmProvider });

    vi.mocked(runReadinessTest).mockResolvedValue({
      provider_id: "p1",
      chatbot_ready: true,
      steps: [
        { name: "non_streaming_text", status: "pass", detail: null },
        { name: "streaming_text", status: "pass", detail: null },
        { name: "tool_call", status: "pass", detail: null },
        { name: "tool_result", status: "pass", detail: null },
        { name: "store_false", status: "skipped", detail: "chat completions" },
        { name: "cancellation_settle", status: "skipped", detail: "pi lifecycle" },
      ],
    });

    fireEvent.click(screen.getByText("Run Readiness Test"));

    await waitFor(() => {
      expect(screen.getByText("Ready")).toBeInTheDocument();
    });
    expect(screen.getAllByText("PASS").length).toBe(4);
  });

  it("does not test stale saved configuration after the form becomes dirty", () => {
    const llmProvider: Provider = {
      ...mockProvider,
      provider_type: "llm_api",
      base_url: "https://api.example/v1",
      api_protocol: "openai_chat_completions",
      model_id: "gpt-test",
      model_display_name: null,
      is_chatbot_default: false,
      chatbot_ready: false,
    };
    renderDialog({ provider: llmProvider });

    fireEvent.change(screen.getByLabelText("Model ID"), {
      target: { value: "unsaved-model" },
    });
    fireEvent.click(screen.getByText("Run Readiness Test"));

    expect(runReadinessTest).not.toHaveBeenCalled();
    expect(message.warning).toHaveBeenCalledWith(
      "Save your changes before running the readiness test.",
    );
  });

  it("allows readiness testing after dirty LLM settings are saved", async () => {
    const llmProvider: Provider = {
      ...mockProvider,
      provider_type: "llm_api",
      base_url: "https://api.example/v1",
      api_protocol: "openai_chat_completions",
      model_id: "gpt-test",
      model_display_name: null,
      is_chatbot_default: false,
      chatbot_ready: false,
    };
    vi.mocked(runReadinessTest).mockResolvedValue({
      provider_id: "p1",
      chatbot_ready: true,
      steps: [{ name: "non_streaming_text", status: "pass", detail: null }],
    });
    renderDialog({ provider: llmProvider });

    fireEvent.change(screen.getByLabelText("Model ID"), {
      target: { value: "saved-model" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateProvider).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByText("Run Readiness Test"));

    await waitFor(() => expect(runReadinessTest).toHaveBeenCalledWith("p1"));
    expect(message.warning).not.toHaveBeenCalledWith(
      "Save your changes before running the readiness test.",
    );
  });

  it("runs readiness test and renders failing step", async () => {
    const llmProvider: Provider = {
      ...mockProvider,
      provider_type: "llm_api",
      base_url: "https://api.example/v1",
      api_protocol: "openai_responses",
      model_id: "gpt-test",
      model_display_name: null,
      is_chatbot_default: false,
      chatbot_ready: false,
    };
    renderDialog({ provider: llmProvider });

    vi.mocked(runReadinessTest).mockResolvedValue({
      provider_id: "p1",
      chatbot_ready: false,
      steps: [
        { name: "non_streaming_text", status: "pass", detail: null },
        { name: "streaming_text", status: "fail", detail: "Stream closed without a terminal event" },
      ],
    });

    fireEvent.click(screen.getByText("Run Readiness Test"));

    await waitFor(() => {
      expect(screen.getByText("Not Ready")).toBeInTheDocument();
    });
    expect(screen.getByText("streaming_text")).toBeInTheDocument();
    expect(screen.getByText("FAIL")).toBeInTheDocument();
  });

  it("clears readiness results when the edited provider changes", async () => {
    const firstProvider: Provider = {
      ...mockProvider,
      provider_type: "llm_api",
      api_style: null,
      api_protocol: "openai_chat_completions",
      model_id: "model-one",
    };
    const secondProvider: Provider = {
      ...firstProvider,
      id: "p2",
      name: "Second Provider",
      model_id: "model-two",
    };
    vi.mocked(runReadinessTest).mockResolvedValue({
      provider_id: firstProvider.id,
      chatbot_ready: true,
      steps: [{ name: "non_streaming_text", status: "pass", detail: null }],
    });
    const view = renderDialog({ provider: firstProvider });

    fireEvent.click(screen.getByText("Run Readiness Test"));
    await waitFor(() => expect(screen.getByText("Ready")).toBeInTheDocument());

    view.rerender(
      <MemoryRouter>
        <AddProviderDialog {...defaultProps} provider={secondProvider} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.queryByText("Ready")).not.toBeInTheDocument());
  });

});
