import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useWorkflowValidation } from "@/features/workflow-editor/hooks/useWorkflowValidation";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { initialUIState, useUIStore } from "@/stores/uiStore";

describe("useWorkflowValidation", () => {
  beforeEach(() => {
    useUIStore.setState(initialUIState);
    useWorkflowStore.setState({
      nodes: [
        {
          id: "input_1",
          type: "input/pdf",
          data: {
            label: "Input",
            config: {},
            configSchema: {
              type: "object",
              properties: {
                file: { type: "file" }
              },
              required: ["file"]
            }
          }
        },
        {
          id: "engine_1",
          type: "engine/ocr",
          data: {
            label: "Engine",
            config: { model: "paddleocr", provider_id: "provider-1" },
            configSchema: {
              type: "object",
              properties: {
                model: { type: "string" }
              },
              required: ["model"]
            }
          }
        },
        {
          id: "output_1",
          type: "output/markdown",
          data: {
            label: "Output",
            config: {},
            configSchema: {
              type: "object",
              properties: {}
            }
          }
        },
        {
          id: "end_1",
          type: "end/final",
          data: {
            label: "End",
            config: {},
            configSchema: {
              type: "object",
              properties: {}
            }
          }
        }
      ],
      edges: [
        { id: "e1", source: "input_1", target: "engine_1" },
        { id: "e2", source: "engine_1", target: "output_1" },
        { id: "e3", source: "output_1", target: "end_1" }
      ],
      nodeConfigs: {
        input_1: {},
        engine_1: { model: "paddleocr", provider_id: "provider-1" },
        output_1: {},
        end_1: {}
      },
      uploadedFiles: {},
      nodeRegistry: {
        nodes: [],
        connection_rules: []
      },
      selectedNodeId: null
    });
  });

  it("reports blocking errors and disables execution", async () => {
    const { result } = renderHook(() => useWorkflowValidation());

    await waitFor(() => {
      expect(result.current.blockingErrors.some((issue) => issue.code === "MISSING_REQUIRED_CONFIG")).toBe(true);
      expect(result.current.isExecutable).toBe(false);
    });
  });

  it("reports warning-only result as executable", async () => {
    useWorkflowStore.setState({
      uploadedFiles: {
        input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" })
      }
    });

    const { result } = renderHook(() => useWorkflowValidation());

    await waitFor(() => {
      expect(result.current.blockingErrors).toHaveLength(0);
      expect(result.current.isExecutable).toBe(true);
    });
  });

  it("uses engine health state to produce engine unavailable warning", async () => {
    useWorkflowStore.setState({
      uploadedFiles: {
        input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" })
      }
    });
    useUIStore.setState({
      engineStatuses: {
        ocr: "unavailable"
      }
    });

    const { result } = renderHook(() => useWorkflowValidation());

    await waitFor(() => {
      expect(result.current.warnings.some((issue) => issue.code === "ENGINE_UNAVAILABLE")).toBe(true);
    });
  });

  it("builds errorCountByNode map (blocking only)", async () => {
    const { result } = renderHook(() => useWorkflowValidation());

    await waitFor(() => {
      expect(result.current.errorCountByNode.input_1).toBeGreaterThan(0);
    });
  });

  it("builds warningCountByNode map", async () => {
    useWorkflowStore.setState({
      uploadedFiles: {
        input_1: new File(["pdf"], "doc.pdf", { type: "application/pdf" })
      }
    });

    const { result } = renderHook(() => useWorkflowValidation());

    await waitFor(() => {
      expect(result.current.warningCountByNode).toBeDefined();
      expect(typeof result.current.warningCountByNode).toBe("object");
    });
  });
});
