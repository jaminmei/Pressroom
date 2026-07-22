import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { getCategoryIcon } from "@/components/Icons";
import CommandItem from "@/components/CommandPalette/CommandItem";

describe("CommandItem", () => {
  it("renders label, description and meta", () => {
    render(
      <CommandItem
        badge="engine"
        description="engine/ocr"
        icon={createElement(getCategoryIcon("engine"), { size: 16 })}
        index={0}
        label="OCR Engine"
        onSelect={vi.fn()}
        selected={false}
        shortcut="Ctrl+R"
      />
    );

    expect(screen.getByText("OCR Engine")).toBeInTheDocument();
    expect(screen.getByText("engine/ocr")).toBeInTheDocument();
    expect(screen.getByText("engine")).toBeInTheDocument();
    expect(screen.getByText("Ctrl+R")).toBeInTheDocument();
  });

  it("calls onSelect when clicked", () => {
    const onSelect = vi.fn();
    render(
      <CommandItem
        index={0}
        label="Run Workflow"
        onSelect={onSelect}
        selected={false}
      />
    );

    fireEvent.click(screen.getByTestId("command-item-0"));

    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});
