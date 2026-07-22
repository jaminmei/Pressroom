import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ImportExportBar from "@/features/template-center/components/ImportExportBar";

describe("ImportExportBar", () => {
  it("triggers import callback with selected file", () => {
    const onImport = vi.fn();
    render(<ImportExportBar onClearRecent={vi.fn()} onImport={onImport} />);

    expect(screen.getByText("Import from JSON")).toBeInTheDocument();

    const file = new File(["{}"], "workflow.json", { type: "application/json" });
    const input = screen.getByTestId("import-json-input") as HTMLInputElement;

    fireEvent.change(input, { target: { files: [file] } });

    expect(onImport).toHaveBeenCalledWith(file);
  });

  it("clears recent records", () => {
    const onClearRecent = vi.fn();
    render(<ImportExportBar onClearRecent={onClearRecent} onImport={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Clear recent usage" }));

    expect(onClearRecent).toHaveBeenCalledTimes(1);
  });
});
