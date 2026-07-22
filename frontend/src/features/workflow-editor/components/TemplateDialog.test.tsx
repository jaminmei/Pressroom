import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import TemplateDialog from "@/features/workflow-editor/components/TemplateDialog";
import { BUILTIN_TEMPLATES } from "@/features/workflow-editor/templates/builtinTemplates";

describe("TemplateDialog", () => {
  it("renders template list when open", () => {
    render(<TemplateDialog onApply={vi.fn()} onCancel={vi.fn()} open />);

    expect(screen.getByText("Select a Workflow Template")).toBeInTheDocument();
    expect(screen.getByText("Quick Convert")).toBeInTheDocument();
    expect(screen.getByText("Custom Workflow")).toBeInTheDocument();
    expect(screen.getByText("Multi-Engine Compare")).toBeInTheDocument();
  });

  it("calls onApply with selected template", () => {
    const onApply = vi.fn();
    render(<TemplateDialog onApply={onApply} onCancel={vi.fn()} open />);

    fireEvent.click(screen.getAllByRole("button", { name: "Apply this template" })[0]);

    expect(onApply).toHaveBeenCalledWith(BUILTIN_TEMPLATES[0]);
  });
});
