import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";

import type { Provider, TestConnectionResponse } from "@/types/provider";

// --- Mock child components and services ---

vi.mock("./ConnectionStatusBadge", () => ({
  default: ({
    result,
  }: {
    result: { status: string; latency_ms: number | null } | null;
  }) => (result ? <div data-testid="connection-badge">{result.status}</div> : null),
}));

vi.mock("./ModelToggleList", () => ({
  default: () => <div data-testid="model-toggle-list" />,
}));

vi.mock("@/components/Permissions/PermissionButton", () => ({
  PermissionButton: ({ children, ...props }: ComponentProps<"button">) => (
    <button type="button" {...props}>{children}</button>
  ),
}));

vi.mock("@/services/providerApi", () => ({
  getProvider: vi.fn(),
}));

// --- Import after mocks ---

import ProviderCard from "./ProviderCard";
import { getProvider } from "@/services/providerApi";

// --- Mock data ---

const mockProvider: Provider = {
  id: "p1",
  name: "Test Provider",
  provider_type: "openai_compatible",
  api_style: "openai",
  api_version: null,
  engine_category: "vlm",
  base_url: "http://test:8000",
  has_api_key: false,
  auth_config_public: null,
  env_config: null,
  auth_type: "api_key",
  is_enabled: true,
  is_default: false,
  config_schema: null,
  parameter_schema: null,
  extra_config: null,
  models: [
    {
      id: "m1",
      provider_id: "p1",
      model_id: "gpt-4",
      display_name: "GPT-4",
      is_enabled: true,
      capabilities: null,
      default_config: null,
      model_group: null,
      sort_order: 0,
    },
    {
      id: "m2",
      provider_id: "p1",
      model_id: "gpt-5",
      display_name: "GPT-5",
      is_enabled: false,
      capabilities: null,
      default_config: null,
      model_group: null,
      sort_order: 1,
    },
  ],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  health_url: null,
};

const defaultProps = {
  provider: mockProvider,
  category: "vlm",
  onEdit: vi.fn(),
  onDelete: vi.fn(),
  onSetDefault: vi.fn(),
  onTestConnection: vi.fn(),
  onAddModel: vi.fn().mockResolvedValue(undefined),
  onRemoveModel: vi.fn().mockResolvedValue(undefined),
  onToggleModel: vi.fn().mockResolvedValue(undefined),
  onTestModel: vi.fn().mockResolvedValue({ status: "ok", latency_ms: 100, error: null, model_response: "OK" }),
  isTesting: false,
  connectionResult: null as TestConnectionResponse | null,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getProvider).mockResolvedValue(mockProvider);
});

describe("ProviderCard", () => {
  it("T-CARD-01: Renders provider name, model count, and auth type tag", () => {
    render(<ProviderCard {...defaultProps} />);

    expect(screen.getByText("Test Provider")).toBeInTheDocument();
    expect(screen.getByText("2 models")).toBeInTheDocument();
    expect(screen.getByText("API Key")).toBeInTheDocument();
  });

  it("T-CARD-02: Edit button calls onEdit", () => {
    render(<ProviderCard {...defaultProps} />);

    fireEvent.click(screen.getByText("Edit"));

    expect(defaultProps.onEdit).toHaveBeenCalledWith(mockProvider);
  });

  it("T-CARD-03: Test Connection button calls onTestConnection", () => {
    render(<ProviderCard {...defaultProps} />);

    fireEvent.click(screen.getByText("Test Connection"));

    expect(defaultProps.onTestConnection).toHaveBeenCalledWith(mockProvider);
  });

  it("T-CARD-04: Delete button shows confirmation modal", async () => {
    render(<ProviderCard {...defaultProps} />);

    fireEvent.click(screen.getByText("Delete"));

    await waitFor(() => {
      const matches = screen.getAllByText("Delete Test Provider?");
      expect(matches.length).toBeGreaterThan(0);
    });
  });

  it("T-CARD-05: Show Models button expands and shows ModelToggleList", async () => {
    render(<ProviderCard {...defaultProps} />);

    // Not expanded yet
    expect(screen.queryByTestId("model-toggle-list")).not.toBeInTheDocument();

    // Click Show Models
    fireEvent.click(screen.getByText("Show Models"));

    // Wait for getProvider to resolve and ModelToggleList to appear
    await waitFor(() => {
      expect(getProvider).toHaveBeenCalledWith("p1");
    });
    await waitFor(() => {
      expect(screen.getByTestId("model-toggle-list")).toBeInTheDocument();
    });

    // Button text should change
    expect(screen.getByText("Hide Models")).toBeInTheDocument();
  });

  it("T-CARD-06: Add Model button opens modal with input", async () => {
    render(<ProviderCard {...defaultProps} />);

    // Expand first to reveal the Add Model button
    fireEvent.click(screen.getByText("Show Models"));

    await waitFor(() => {
      expect(screen.getByTestId("model-toggle-list")).toBeInTheDocument();
    });

    // Click Add Model
    const addButtons = screen.getAllByText("Add Model");
    fireEvent.click(addButtons[0]);

    // Modal should open with title and input
    await waitFor(() => {
      expect(screen.getByText("Enter the deployment name (model ID) for this model service.")).toBeInTheDocument();
    });
    expect(screen.getByPlaceholderText("e.g. vision-model")).toBeInTheDocument();
  });

  it("T-CARD-07: No Refresh Models button present", () => {
    render(<ProviderCard {...defaultProps} />);

    expect(screen.queryByText("Refresh Models")).not.toBeInTheDocument();
  });

  it("T-CARD-08: Set Default button calls onSetDefault", () => {
    render(<ProviderCard {...defaultProps} />);

    fireEvent.click(screen.getByText("Set Default"));

    expect(defaultProps.onSetDefault).toHaveBeenCalledWith(mockProvider);
  });

  it("T-CARD-09: Shows effective default tag for system providers without mutation action", () => {
    render(
      <ProviderCard
        {...defaultProps}
        provider={{ ...mockProvider, scope: "system" }}
        isDefault
      />,
    );

    expect(screen.getByText("Default")).toBeInTheDocument();
    expect(screen.queryByText("Set Default")).not.toBeInTheDocument();
  });
});
