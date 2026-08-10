import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import VariablePicker from "@/features/workflow-editor/components/VariablePicker";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import type { InputBinding } from "@/features/workflow-editor/types/inputBindings";

describe("VariablePicker", () => {
  beforeEach(() => {
    act(() => {
      useWorkflowStore.setState({
        nodes: [
          {
            id: "layout_2",
            type: "processor/layout_detection",
            data: {
              label: "Layout Two",
              config: {},
              configSchema: { type: "object", properties: {} }
            }
          },
          {
            id: "layout_1",
            type: "processor/layout_detection",
            data: {
              label: "Layout One",
              config: {},
              configSchema: { type: "object", properties: {} }
            }
          },
          {
            id: "source_z",
            type: "input/text",
            data: {
              label: "Source Z",
              config: {},
              configSchema: { type: "object", properties: {} }
            }
          },
          {
            id: "adaptor_1",
            type: "processor/adaptor",
            data: {
              label: "Adaptor",
              config: {},
              configSchema: { type: "object", properties: {} }
            }
          }
        ],
        edges: [
          { id: "e-3", source: "source_z", target: "layout_2" },
          { id: "e-1", source: "layout_2", target: "adaptor_1" },
          { id: "e-2", source: "layout_1", target: "adaptor_1" }
        ],
        nodeConfigs: {},
        uploadedFiles: {},
        selectedNodeId: "adaptor_1",
        nodeRegistry: { nodes: [], connection_rules: [] }
      });
    });
  });

  function renderPicker(bindings: InputBinding[], onChange = vi.fn()) {
    render(<VariablePicker bindings={bindings} nodeId="adaptor_1" onChange={onChange} />);
    return onChange;
  }

  function StatefulPicker({ initialBindings, onChange }: { initialBindings: InputBinding[]; onChange?: (next: InputBinding[]) => void }) {
    const [bindings, setBindings] = useState<InputBinding[]>(initialBindings);

    return (
      <VariablePicker
        bindings={bindings}
        nodeId="adaptor_1"
        onChange={(next) => {
          setBindings(next);
          onChange?.(next);
        }}
      />
    );
  }

  it("sorts canonical ancestor options by node id regardless of edge insertion order", async () => {
    renderPicker([{ name: "doc", selector: [] }]);

    fireEvent.mouseDown(screen.getByTestId("binding-ancestor-0").querySelector(".ant-select-selector") as Element);

    await waitFor(() => {
      const options = screen.getAllByRole("option").map((option) => option.textContent);
      expect(options).toEqual([
        "Layout One (layout_1)",
        "Layout Two (layout_2)",
        "Source Z (source_z)"
      ]);
    });
  });

  it("adds edits and removes binding rows while preserving exact selector segment arrays", async () => {
    const onChange = vi.fn();
    const { rerender } = render(<VariablePicker bindings={[]} nodeId="adaptor_1" onChange={onChange} />);

    fireEvent.click(screen.getByTestId("add-binding"));
    expect(onChange).toHaveBeenLastCalledWith([{ name: "", selector: [] }]);

    const rerendered = vi.fn();
    rerender(<VariablePicker bindings={[{ name: "", selector: [] }]} nodeId="adaptor_1" onChange={rerendered} />);

    fireEvent.change(screen.getByTestId("binding-name-0"), { target: { value: "hero" } });
    expect(rerendered).toHaveBeenLastCalledWith([{ name: "hero", selector: [] }]);

    fireEvent.click(screen.getByTestId("binding-remove-0"));
    expect(rerendered).toHaveBeenLastCalledWith([]);
  });

  it("round-trips arbitrary valid nested structured and metadata selectors", async () => {
    const onChange = renderPicker([
      { name: "hero", selector: ["layout_1", "structured", "elements", "hero"] },
      { name: "page", selector: ["layout_1", "metadata", "page"] }
    ]);

    expect(screen.getByTestId("binding-name-0")).toHaveValue("hero");
    expect(screen.getByTestId("binding-name-1")).toHaveValue("page");
    expect(screen.getByTestId("binding-path-input-0")).toHaveValue("elements.hero");
    expect(screen.getByTestId("binding-path-input-1")).toHaveValue("page");

    render(
      <StatefulPicker
        initialBindings={[
          { name: "hero", selector: ["layout_1", "structured", "elements", "hero"] },
          { name: "page", selector: ["layout_1", "metadata", "page"] }
        ]}
        onChange={onChange}
      />
    );

    fireEvent.change(screen.getAllByTestId("binding-path-input-0")[1], { target: { value: "elements.cover" } });
    expect(onChange).toHaveBeenLastCalledWith([
      { name: "hero", selector: ["layout_1", "structured", "elements", "cover"] },
      { name: "page", selector: ["layout_1", "metadata", "page"] }
    ]);

    fireEvent.change(screen.getAllByTestId("binding-path-input-1")[1], { target: { value: "page" } });
    expect(onChange).toHaveBeenLastCalledWith([
      { name: "hero", selector: ["layout_1", "structured", "elements", "cover"] },
      { name: "page", selector: ["layout_1", "metadata", "page"] }
    ]);
  });

  it("rejects unsafe nested selector segments in the UI", async () => {
    const onChange = renderPicker([{ name: "bad", selector: ["layout_1", "structured"] }]);

    fireEvent.change(screen.getByTestId("binding-path-input-0"), { target: { value: "item" } });

    expect(await screen.findByText("Path segments cannot be empty, numeric, reserved, or contain dots/brackets."))
      .toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalledWith([
      { name: "bad", selector: ["layout_1", "structured", "item"] }
    ]);
  });
});
