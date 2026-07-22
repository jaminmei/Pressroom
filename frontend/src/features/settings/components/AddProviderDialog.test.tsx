import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Form, Input } from "antd";
import { MemoryRouter } from "react-router-dom";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { Provider } from "@/types/provider";
import { authTypeRegistry } from "@/types/authTypeRegistry";

// --- Mocks ---

vi.mock("@/services/providerApi", () => ({
  createProvider: vi.fn(),
  updateProvider: vi.fn(),
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
import { createProvider, updateProvider } from "@/services/providerApi";

// --- Mock data ---

const mockProvider: Provider = {
  id: "p1",
  name: "Test Provider",
  provider_type: "openai_compatible",
  api_style: "openai",
  api_version: null,
  engine_category: "vlm",
  base_url: "http://test:8000",
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
  defaultProviderType?: "openai_compatible" | "engine_service";
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
    expect(screen.queryByText("Provider Type")).not.toBeInTheDocument();

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

});
