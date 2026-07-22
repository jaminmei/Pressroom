import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ModelSelector from "./ModelSelector";

import type { Provider, ProviderModel } from "@/types/provider";

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
  {
    id: "m3",
    provider_id: "p1",
    model_id: "other",
    display_name: "Other Model",
    is_enabled: true,
    capabilities: null,
    default_config: null,
    model_group: null,
    sort_order: 2,
  },
];

const mockProvider: Provider = {
  id: "p1",
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

describe("ModelSelector", () => {
  it("T-MOD-01: renders models grouped by model_group", () => {
    render(
      <ModelSelector
        provider={mockProvider}
        onChange={vi.fn()}
      />,
    );

    // Open dropdown
    fireEvent.mouseDown(screen.getByRole("combobox"));

    // Group headers should be visible
    expect(screen.getByTitle("gpt_regular")).toBeInTheDocument();
    expect(screen.getByTitle("gpt_inference")).toBeInTheDocument();
    expect(screen.getByTitle("Other")).toBeInTheDocument();
  });

  it("T-MOD-02: models without model_group appear in Other group", () => {
    render(
      <ModelSelector
        provider={mockProvider}
        onChange={vi.fn()}
      />,
    );

    fireEvent.mouseDown(screen.getByRole("combobox"));

    // "Other Model" should be visible
    expect(screen.getByText("Other Model")).toBeInTheDocument();
  });

  it("T-MOD-03: selecting a model calls onChange with model object", async () => {
    const onChange = vi.fn();
    render(
      <ModelSelector
        provider={mockProvider}
        onChange={onChange}
      />,
    );

    fireEvent.mouseDown(screen.getByRole("combobox"));

    await waitFor(() => {
      const options = screen.getAllByText("GPT-4");
      fireEvent.click(options[0]);
    });

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ id: "m1", display_name: "GPT-4" }),
    );
  });

  it("T-MOD-04: single enabled model auto-selects", async () => {
    const singleModelProvider: Provider = {
      ...mockProvider,
      models: [mockModels[0]], // Only one model
    };

    const onChange = vi.fn();
    render(
      <ModelSelector
        provider={singleModelProvider}
        onChange={onChange}
      />,
    );

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ id: "m1" }),
      );
    });
  });

  it("re-evaluates the unique model when the provider changes", async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <ModelSelector
        provider={{ ...mockProvider, models: [mockModels[0]] }}
        onChange={onChange}
      />,
    );
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(mockModels[0]));

    onChange.mockClear();
    rerender(
      <ModelSelector
        provider={{ ...mockProvider, id: "p2", models: [mockModels[1]] }}
        onChange={onChange}
      />,
    );

    await waitFor(() => expect(onChange).toHaveBeenCalledWith(mockModels[1]));
  });

  it.each([
    ["no enabled models", mockModels.map((item) => ({ ...item, is_enabled: false }))],
    ["multiple enabled models", mockModels],
  ])("does not auto-select when there are %s", async (_label, models) => {
    const onChange = vi.fn();
    render(
      <ModelSelector
        provider={{ ...mockProvider, models }}
        onChange={onChange}
      />,
    );

    await waitFor(() => {
      expect(onChange).not.toHaveBeenCalled();
    });
    expect(screen.getByRole("combobox")).toHaveAttribute("aria-expanded", "false");
  });
});
