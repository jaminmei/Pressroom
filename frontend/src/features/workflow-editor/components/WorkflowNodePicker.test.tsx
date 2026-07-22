import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import WorkflowNodePicker from "@/features/workflow-editor/components/WorkflowNodePicker";
import type { NodeRegistryNode } from "@/types/node-registry";

const nodeOptions: NodeRegistryNode[] = [
  {
    node_type: "engine/ocr",
    display_name: "OCR Engine",
    category: "engine",
    description: "擷取文件中的文字內容",
    config_schema: { type: "object", properties: {} },
    input_types: ["application/pdf"],
    output_types: ["text/raw"]
  },
  {
    node_type: "engine/model",
    display_name: "Model Engine",
    category: "engine",
    description: "處理複雜版面與圖文混排",
    config_schema: { type: "object", properties: {} },
    input_types: ["application/pdf"],
    output_types: ["text/raw"]
  }
];

describe("WorkflowNodePicker", () => {
  it("renders richer node metadata for each compatible option", () => {
    render(<WorkflowNodePicker hint="點擊新增節點" nodes={nodeOptions} onSelect={vi.fn()} />);

    expect(screen.getAllByText("ENGINE")).toHaveLength(2);
    expect(screen.getByText("擷取文件中的文字內容")).toBeInTheDocument();
    expect(screen.getByText("處理複雜版面與圖文混排")).toBeInTheDocument();
  });

  it("filters compatible options by search keyword", () => {
    render(<WorkflowNodePicker hint="點擊新增節點" nodes={nodeOptions} onSelect={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText("Search available nodes"), {
      target: { value: "model" }
    });

    expect(screen.getByRole("button", { name: /Model Engine/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /OCR Engine/ })).not.toBeInTheDocument();
  });
});
