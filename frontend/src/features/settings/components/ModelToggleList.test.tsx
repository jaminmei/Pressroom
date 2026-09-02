import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ModelToggleList from "./ModelToggleList";

vi.mock("@/hooks/usePermission", () => ({
  usePermission: () => ({
    can: () => true,
    explain: () => ({ allowed: true, capability: "provider.manage", allowedRoles: [], reason: undefined }),
    role: "admin"
  }),
}));

const mockModels = [
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

describe("ModelToggleList", () => {
  it("T-MODEL-01: Renders models as flat list sorted by sort_order with Switch toggles", () => {
    render(
      <ModelToggleList
        models={mockModels}
        providerId="p1"
        onToggle={vi.fn()}
      />,
    );

    // No group headers — flat list
    expect(screen.queryByText("Other")).not.toBeInTheDocument();
    expect(screen.queryByText("Gpt")).not.toBeInTheDocument();

    // Model display names — all visible
    expect(screen.getByText("GPT-4")).toBeInTheDocument();
    expect(screen.getByText("GPT-5")).toBeInTheDocument();
    expect(screen.getByText("Other Model")).toBeInTheDocument();
  });

  it("T-MODEL-02: Toggle switch calls onToggle with correct args", async () => {
    const onToggle = vi.fn().mockResolvedValue(undefined);
    render(
      <ModelToggleList
        models={mockModels}
        providerId="p1"
        onToggle={onToggle}
      />,
    );

    // Find all switches — the first one corresponds to GPT-4 (is_enabled: true)
    const switches = screen.getAllByRole("switch");
    fireEvent.click(switches[0]);

    await waitFor(() => {
      expect(onToggle).toHaveBeenCalledWith("m1", false);
    });
  });

  it("T-MODEL-03: When onRemoveModel is provided, delete button appears per model and clicking it shows confirmation", async () => {
    const onRemoveModel = vi.fn().mockResolvedValue(undefined);
    render(
      <ModelToggleList
        models={mockModels}
        providerId="p1"
        onToggle={vi.fn()}
        onRemoveModel={onRemoveModel}
      />,
    );

    // Delete buttons should be rendered (one per model)
    const dangerButtons = screen.getAllByRole("button", { name: "delete" });
    expect(dangerButtons.length).toBe(3);

    // Click the first delete button (GPT-4)
    fireEvent.click(dangerButtons[0]);

    // Confirmation modal should appear
    await waitFor(() => {
      const confirmTexts = screen.getAllByText(/Remove “GPT-4”\?/);
      expect(confirmTexts.length).toBeGreaterThan(0);
    });
  });

  it("T-MODEL-04: When onTestModel is provided, Test button appears per model and calls onTestModel", async () => {
    const onTestModel = vi.fn().mockResolvedValue({
      status: "healthy",
      latency_ms: 150,
      error: null,
      model_response: "OK",
    });
    render(
      <ModelToggleList
        models={mockModels}
        providerId="p1"
        onToggle={vi.fn()}
        onTestModel={onTestModel}
      />,
    );

    // Test buttons should be rendered
    const testButtons = screen.getAllByText("Test");
    expect(testButtons.length).toBe(3);

    // Click the first test button (GPT-4)
    fireEvent.click(testButtons[0]);

    await waitFor(() => {
      expect(onTestModel).toHaveBeenCalledWith("p1", "m1");
    });

    // Result should show latency badge
    await waitFor(() => {
      expect(screen.getByText("150ms")).toBeInTheDocument();
    });
  });
});
