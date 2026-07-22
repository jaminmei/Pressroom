import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import DynamicForm from "@/features/workflow-editor/components/DynamicForm";
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
});
