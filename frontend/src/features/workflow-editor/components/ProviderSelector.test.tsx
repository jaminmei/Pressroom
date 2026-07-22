import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import ProviderSelector from "./ProviderSelector";

// Mock useProviders
const mockOnChange = vi.fn();

vi.mock("@/features/workflow-editor/hooks/useProviders", () => ({
  useProviders: vi.fn(),
}));

import { useProviders } from "@/features/workflow-editor/hooks/useProviders";

const mockProviders: import("@/types/provider").Provider[] = [
  {
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
    models: [],
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
    health_url: null,
  },
  {
    id: "p2",
    scope: "workspace",
    workspace_id: "workspace-test",
    name: "Local Ollama",
    provider_type: "openai_compatible",
    api_style: "openai",
    api_version: null,
    engine_category: "vlm",
    base_url: "http://ollama:11434",
    has_api_key: false,
    auth_type: "api_key",
    auth_config_public: null,
    env_config: null,
    is_enabled: true,
    is_default: false,
    config_schema: null,
    parameter_schema: null,
    extra_config: null,
    models: [],
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
    health_url: null,
  },
];

function renderWithRouter(ui: React.ReactElement) {
  return render(<BrowserRouter>{ui}</BrowserRouter>);
}

describe("ProviderSelector", () => {
  it("T-PROV-01: renders providers filtered by engine_category", () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: mockProviders,
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    renderWithRouter(
      <ProviderSelector
        engineCategory="vlm"
        onChange={mockOnChange}
      />,
    );

    // The select should be rendered
    const select = screen.getByRole("combobox");
    expect(select).toBeInTheDocument();
  });

  it("T-PROV-02: selecting a provider calls onChange with provider object", async () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: mockProviders,
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    renderWithRouter(
      <ProviderSelector
        engineCategory="vlm"
        onChange={mockOnChange}
      />,
    );

    // Open dropdown
    fireEvent.mouseDown(screen.getByRole("combobox"));

    await waitFor(() => {
      // Click the first option.
      const options = screen.getAllByText(/Vision Provider/);
      fireEvent.click(options[0]);
    });

    expect(mockOnChange).toHaveBeenCalledWith(
      expect.objectContaining({ id: "p1", name: "Vision Provider" }),
    );
  });

  it("T-PROV-03: empty state shows no providers message", () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: [],
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    renderWithRouter(
      <ProviderSelector
        engineCategory="vlm"
        onChange={mockOnChange}
      />,
    );

    // Open dropdown to see empty state
    fireEvent.mouseDown(screen.getByRole("combobox"));

    expect(screen.getByText(/No providers available/)).toBeInTheDocument();
  });

  it("T-PROV-04: default provider marked with star", async () => {
    vi.mocked(useProviders).mockReturnValue({
      providers: mockProviders,
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    renderWithRouter(
      <ProviderSelector
        engineCategory="vlm"
        onChange={mockOnChange}
      />,
    );

    // Open dropdown
    fireEvent.mouseDown(screen.getByRole("combobox"));

    await waitFor(() => {
      // Default provider has ⭐
      const starElements = screen.getAllByText("⭐");
      expect(starElements.length).toBeGreaterThan(0);
    });
  });
});
