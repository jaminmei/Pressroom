import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DynamicForm from "@/features/workflow-editor/components/DynamicForm";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import type { NodeConfigSchema } from "@/types/node-registry";

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn()
  }))
});

describe("DynamicForm", () => {
  beforeEach(() => {
    act(() => {
      useWorkflowStore.setState({
        nodes: [],
        edges: [],
        nodeConfigs: {},
        uploadedFiles: {},
        selectedNodeId: null,
        nodeRegistry: { nodes: [], connection_rules: [] },
        dynamicValidation: {
          warnings: [],
          lastValidatedAt: null,
          isValidating: false
        }
      });
    });
  });

  it("renders schema fields for enum/string/integer/boolean/file/array", () => {
    const schema: NodeConfigSchema = {
      type: "object",
      properties: {
        model: {
          type: "string",
          enum: ["paddleocr", "tesseract"]
        },
        prompt: {
          type: "string"
        },
        dpi: {
          type: "integer",
          minimum: 72,
          maximum: 600
        },
        keep_layout: {
          type: "boolean"
        },
        file: {
          type: "file",
          accept: ["application/pdf"],
          max_size_mb: 10
        },
        auto_select_types: {
          type: "array",
          items: {
            type: "string",
            enum: ["title", "paragraph"]
          }
        }
      }
    };

    render(
      <DynamicForm
        nodeId="node_1"
        schema={schema}
        value={{}}
        onChange={vi.fn()}
        onFileChange={vi.fn()}
      />
    );

    expect(screen.getByTestId("dynamic-field-model")).toBeInTheDocument();
    expect(screen.getByTestId("dynamic-field-prompt")).toBeInTheDocument();
    expect(screen.getByTestId("dynamic-field-dpi")).toBeInTheDocument();
    expect(screen.getByTestId("dynamic-field-keep_layout")).toBeInTheDocument();
    expect(screen.getByTestId("dynamic-field-file")).toBeInTheDocument();
    expect(screen.getByTestId("dynamic-field-auto_select_types")).toBeInTheDocument();
  });

  it("renders named binding controls for adaptor nodes and clears bindings when switching back to all_upstream", async () => {
    const schema: NodeConfigSchema = {
      type: "object",
      properties: {
        code: {
          type: "string"
        },
        input_mode: {
          type: "string",
          enum: ["all_upstream", "custom_bindings"]
        },
        input_bindings: {
          type: "array",
          items: {
            type: "object",
            properties: {
              name: { type: "string", minLength: 1 },
              selector: {
                type: "array",
                items: { type: "string" },
                minItems: 2
              }
            },
            required: ["name", "selector"]
          }
        }
      },
      required: ["code"]
    };

    const onChange = vi.fn();

    act(() => {
      useWorkflowStore.setState({
        nodes: [
          {
            id: "input_1",
            type: "input/text",
            data: {
              label: "Input One",
              config: {},
              configSchema: { type: "object", properties: {} },
              outputTypes: ["text/plain"]
            }
          },
          {
            id: "adaptor_1",
            type: "processor/adaptor",
            data: {
              label: "Adaptor",
              config: {},
              configSchema: schema,
              outputTypes: ["application/x-adaptor-output"]
            }
          }
        ],
        edges: [{ id: "e-1", source: "input_1", target: "adaptor_1", targetHandle: "input" }],
        nodeConfigs: {
          adaptor_1: {
            input_mode: "custom_bindings",
            input_bindings: [{ name: "document", selector: ["input_1", "text"] }]
          }
        }
      });
    });

    render(
      <DynamicForm
        nodeId="adaptor_1"
        schema={schema}
        value={{
          code: "def main(inputs): return inputs",
          input_mode: "custom_bindings",
          input_bindings: [{ name: "document", selector: ["input_1", "text"] }]
        }}
        onChange={onChange}
        onFileChange={vi.fn()}
      />
    );

    expect(screen.getByText("Named Input Bindings")).toBeInTheDocument();
    expect(screen.getByDisplayValue("document")).toBeInTheDocument();
    expect(screen.getByText("Named input bindings will override direct input edges")).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByRole("combobox", { name: /input mode/i }));

    await waitFor(() => {
      fireEvent.click(screen.getByText("All upstream outputs (by node ID)"));
    });

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        input_mode: "all_upstream",
        input_bindings: []
      })
    );
  });

  it("shows inline adaptor warning only when custom_bindings has at least one binding and a direct incoming edge", () => {
    const schema: NodeConfigSchema = {
      type: "object",
      properties: {
        code: { type: "string" },
        input_mode: { type: "string", enum: ["all_upstream", "custom_bindings"] },
        input_bindings: {
          type: "array",
          items: {
            type: "object",
            properties: {
              name: { type: "string" },
              selector: { type: "array", items: { type: "string" } }
            }
          }
        }
      }
    };

    act(() => {
      useWorkflowStore.setState({
        nodes: [
          {
            id: "layout_1",
            type: "processor/layout_detection",
            data: { label: "Layout", config: {}, configSchema: { type: "object", properties: {} } }
          },
          {
            id: "adaptor_1",
            type: "processor/adaptor",
            data: { label: "Adaptor", config: {}, configSchema: schema }
          }
        ],
        edges: [{ id: "e-1", source: "layout_1", target: "adaptor_1", targetHandle: "input" }]
      });
    });

    const { rerender } = render(
      <DynamicForm
        nodeId="adaptor_1"
        nodeType="processor/adaptor"
        schema={schema}
        value={{ input_mode: "custom_bindings", input_bindings: [{ name: "page", selector: ["layout_1", "structured"] }] }}
        onChange={vi.fn()}
        onFileChange={vi.fn()}
      />
    );

    expect(screen.getByText("Named input bindings will override direct input edges")).toBeInTheDocument();

    rerender(
      <DynamicForm
        nodeId="adaptor_1"
        nodeType="processor/adaptor"
        schema={schema}
        value={{ input_mode: "all_upstream", input_bindings: [{ name: "page", selector: ["layout_1", "structured"] }] }}
        onChange={vi.fn()}
        onFileChange={vi.fn()}
      />
    );
    expect(screen.queryByText("Named input bindings will override direct input edges")).not.toBeInTheDocument();

    rerender(
      <DynamicForm
        nodeId="adaptor_1"
        nodeType="processor/adaptor"
        schema={schema}
        value={{ input_mode: "custom_bindings", input_bindings: [] }}
        onChange={vi.fn()}
        onFileChange={vi.fn()}
      />
    );
    expect(screen.queryByText("Named input bindings will override direct input edges")).not.toBeInTheDocument();

    act(() => {
      useWorkflowStore.setState({ edges: [] });
    });
    rerender(
      <DynamicForm
        nodeId="adaptor_1"
        nodeType="processor/adaptor"
        schema={schema}
        value={{ input_mode: "custom_bindings", input_bindings: [{ name: "page", selector: ["layout_1", "structured"] }] }}
        onChange={vi.fn()}
        onFileChange={vi.fn()}
      />
    );
    expect(screen.queryByText("Named input bindings will override direct input edges")).not.toBeInTheDocument();
  });

  it("does not render named binding controls for non-adaptor object-array fields", () => {
    const schema: NodeConfigSchema = {
      type: "object",
      properties: {
        steps: {
          type: "array",
          items: {
            type: "object",
            properties: {
              name: { type: "string" }
            },
            required: ["name"]
          }
        }
      }
    };

    render(
      <DynamicForm
        nodeId="processor_1"
        schema={schema}
        value={{ steps: [] }}
        onChange={vi.fn()}
        onFileChange={vi.fn()}
      />
    );

    expect(screen.queryByText("Named Input Bindings")).not.toBeInTheDocument();
    expect(screen.getByTestId("dynamic-field-steps")).toBeInTheDocument();
  });
});
