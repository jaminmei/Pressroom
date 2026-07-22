import { beforeEach, describe, expect, it, vi } from "vitest";

import { BUILTIN_TEMPLATES } from "@/features/workflow-editor/templates/builtinTemplates";
import { applyTemplateToWorkflowStore } from "@/features/workflow-editor/templates/applyTemplate";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { getDefaultProvider } from "@/services/providerApi";
import type { NodeRegistryResponse } from "@/types/node-registry";
import type { Provider, ProviderModel } from "@/types/provider";

vi.mock("@/services/providerApi", () => ({
  getDefaultProvider: vi.fn(),
}));

const registry: Pick<NodeRegistryResponse, "nodes" | "connection_rules"> = {
  nodes: [
    {
      node_type: "input/pdf",
      display_name: "PDF 輸入",
      category: "input",
      config_schema: {
        type: "object",
        properties: {
          file: { type: "file" }
        }
      },
      output_types: ["application/pdf"],
      max_inputs: 0,
      max_outputs: -1
    },
    {
      node_type: "engine/ocr",
      display_name: "OCR Engine",
      category: "engine",
      config_schema: {
        type: "object",
        properties: {
          model: { type: "string" }
        }
      },
      input_types: ["application/pdf"],
      output_types: ["text/raw"],
      max_inputs: 1,
      max_outputs: -1
    },
    {
      node_type: "engine/model",
      display_name: "Model Engine",
      category: "engine",
      config_schema: {
        type: "object",
        properties: {
          model: { type: "string" }
        }
      },
      input_types: ["application/pdf"],
      output_types: ["text/raw"],
      max_inputs: 1,
      max_outputs: -1
    },
    {
      node_type: "output/markdown",
      display_name: "Markdown 輸出",
      category: "output",
      config_schema: {
        type: "object",
        properties: {
          include_metadata: { type: "boolean" }
        }
      },
      input_types: ["text/raw"],
      output_types: ["text/markdown"],
      max_inputs: 1,
      max_outputs: 0
    },
    {
      node_type: "end/final",
      display_name: "Workflow End",
      category: "end",
      config_schema: {
        type: "object",
        properties: {}
      },
      input_types: ["text/markdown"],
      output_types: [],
      max_inputs: -1,
      max_outputs: 0
    }
  ],
  connection_rules: []
};

function model(id: string, isEnabled = true): ProviderModel {
  return {
    id: `row-${id}`,
    provider_id: "provider-1",
    model_id: id,
    display_name: id,
    is_enabled: isEnabled,
    capabilities: null,
    default_config: null,
    model_group: null,
    sort_order: 0,
  };
}

function provider(models: ProviderModel[]): Provider {
  return {
    id: "provider-1",
    name: "Public model provider",
    provider_type: "openai_compatible",
    api_style: "openai",
    api_version: null,
    engine_category: "vlm",
    base_url: "https://api.example.test/v1",
    has_api_key: true,
    auth_type: "api_key",
    auth_config_public: null,
    env_config: null,
    is_enabled: true,
    is_default: true,
    config_schema: null,
    parameter_schema: null,
    extra_config: null,
    models,
    created_at: "2026-07-21T00:00:00Z",
    updated_at: "2026-07-21T00:00:00Z",
    health_url: null,
  };
}

describe("applyTemplateToWorkflowStore", () => {
  beforeEach(() => {
    vi.mocked(getDefaultProvider).mockResolvedValue(null);
    useWorkflowStore.setState({
      nodes: [
        {
          id: "legacy_node",
          type: "input/pdf",
          data: {
            label: "Legacy",
            config: { file: "legacy.pdf" },
            configSchema: {
              type: "object",
              properties: {}
            }
          }
        }
      ],
      edges: [{ id: "legacy_edge", source: "legacy_node", target: "legacy_node" }],
      nodeConfigs: {
        legacy_node: { file: "legacy.pdf" }
      },
      uploadedFiles: {
        legacy_node: new File(["legacy"], "legacy.pdf", { type: "application/pdf" })
      },
      nodeRegistry: registry,
      selectedNodeId: "legacy_node"
    });
  });

  it("replaces canvas with template nodes and edges", () => {
    applyTemplateToWorkflowStore(BUILTIN_TEMPLATES[0]);

    const state = useWorkflowStore.getState();
    expect(state.nodes).toHaveLength(4);
    expect(state.edges).toHaveLength(3);
    expect(state.nodes.map((node) => node.id)).toEqual(["input_1", "processor_1", "engine_1", "end_1"]);
    expect(state.selectedNodeId).toBe("input_1");
    expect(state.uploadedFiles).toEqual({});
  });

  it("keeps template config values without hardcoding a model", () => {
    applyTemplateToWorkflowStore(BUILTIN_TEMPLATES[1]);

    const state = useWorkflowStore.getState();
    expect(state.nodeConfigs.input_1).toMatchObject({ file: "$file_0" });
    expect(state.nodeConfigs.processor_1).toMatchObject({ pages: "1" });
    expect(state.nodeConfigs.engine_1.model).toBeUndefined();
    expect(state.nodeConfigs.engine_1.prompt).toEqual(expect.any(String));
    expect(state.nodeConfigs.output_1).toBeUndefined();
  });

  it("selects the only enabled model from the default provider", async () => {
    vi.mocked(getDefaultProvider).mockResolvedValue(provider([model("only-model")]));

    applyTemplateToWorkflowStore(BUILTIN_TEMPLATES[1]);

    await vi.waitFor(() => {
      expect(useWorkflowStore.getState().nodeConfigs.engine_1).toMatchObject({
        provider_id: "provider-1",
        model: "only-model",
      });
    });
  });

  it.each([
    ["no enabled models", [model("disabled", false)]],
    ["multiple enabled models", [model("first"), model("second")]],
  ])("requires an explicit selection when the provider has %s", async (_label, models) => {
    vi.mocked(getDefaultProvider).mockResolvedValue(provider(models));

    applyTemplateToWorkflowStore(BUILTIN_TEMPLATES[1]);

    await vi.waitFor(() => {
      const config = useWorkflowStore.getState().nodeConfigs.engine_1;
      expect(config.provider_id).toBe("provider-1");
      expect(config.model).toBeUndefined();
    });
  });

  it("repairs template graphs with a single end node and keeps focus on the input node", () => {
    applyTemplateToWorkflowStore(BUILTIN_TEMPLATES[0]);

    const state = useWorkflowStore.getState();
    expect(state.nodes.map((node) => node.id)).toEqual(["input_1", "processor_1", "engine_1", "end_1"]);
    expect(state.nodes.find((node) => node.id === "end_1")?.type).toBe("end/final");
    expect(
      state.edges.some((edge) => edge.source === "engine_1" && edge.target === "end_1")
    ).toBe(true);
    expect(state.selectedNodeId).toBe("input_1");
  });
});
