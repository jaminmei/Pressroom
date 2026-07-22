import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import TemplateCard from "@/features/template-center/components/TemplateCard";
import type { WorkflowTemplate } from "@/features/workflow-editor/templates/types";

const template: WorkflowTemplate = {
  id: "tpl-ocr-basic",
  name: "PDF → OCR → Markdown",
  description: "desc",
  icon: "tpl-ocr-basic",
  category: "basic",
  tags: ["ocr"],
  supported_input_types: ["application/pdf"],
  default_output_format: "markdown",
  nodes: [],
  connections: []
};

describe("TemplateCard", () => {
  it("renders template details with richer launch metadata", () => {
    render(
      <TemplateCard
        description="Quick path for standard files"
        onApply={vi.fn()}
        onExport={vi.fn()}
        template={template}
        title="Quick Convert"
        topology="quick-convert"
      />
    );

    expect(screen.getByText("Starter")).toBeInTheDocument();
    expect(screen.getByText("Quick Convert")).toBeInTheDocument();
    expect(screen.getByText("Quick path for standard files")).toBeInTheDocument();
    expect(screen.getByText("ocr")).toBeInTheDocument();
    expect(screen.getByText("Input")).toBeInTheDocument();
    expect(screen.getByText("pdf")).toBeInTheDocument();
    expect(screen.getByText("Output")).toBeInTheDocument();
    expect(screen.getByText("MARKDOWN")).toBeInTheDocument();
    expect(screen.getByText("After applying, you will enter the Editor and can adjust the starter structure.")).toBeInTheDocument();
    expect(screen.getByTestId("template-topology-quick-convert")).toBeInTheDocument();
  });

  it("triggers apply and export actions", () => {
    const onApply = vi.fn();
    const onExport = vi.fn();
    render(<TemplateCard onApply={onApply} onExport={onExport} template={template} />);

    fireEvent.click(screen.getByRole("button", { name: "Apply now" }));
    fireEvent.click(screen.getByRole("button", { name: "Export" }));

    expect(onApply).toHaveBeenCalledWith(template);
    expect(onExport).toHaveBeenCalledWith(template);
  });
});
