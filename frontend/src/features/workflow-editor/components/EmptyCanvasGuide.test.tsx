import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import EmptyCanvasGuide from "@/features/workflow-editor/components/EmptyCanvasGuide";
import { BUILTIN_TEMPLATES } from "@/features/workflow-editor/templates/builtinTemplates";

describe("EmptyCanvasGuide", () => {
  it("renders all builtin template cards with the current quick-start entry composition", () => {
    render(
      <EmptyCanvasGuide
        entryToolbar={<button type="button">Add the first node</button>}
        onApplyTemplate={vi.fn()}
      />
    );

    expect(screen.getAllByText("Quick Start")).toHaveLength(2);
    expect(screen.getByText("Quick Convert")).toBeInTheDocument();
    expect(screen.getByText("Custom Workflow")).toBeInTheDocument();
    expect(screen.getByText("Multi-Engine Compare")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add the first node" })).toBeInTheDocument();
    expect(screen.getByText(/Choose a template to build a starter structure quickly/)).toBeInTheDocument();
  });

  it("calls onApplyTemplate when clicking quick apply", () => {
    const onApplyTemplate = vi.fn();
    render(<EmptyCanvasGuide onApplyTemplate={onApplyTemplate} />);

    const applyButtons = screen.getAllByRole("button", { name: "Apply" });
    fireEvent.click(applyButtons[0]);

    expect(onApplyTemplate).toHaveBeenCalledWith(BUILTIN_TEMPLATES[0]);
  });
});
