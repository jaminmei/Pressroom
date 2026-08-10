import { describe, expect, it, vi } from "vitest";

import { getNodeRegistry } from "@/services/nodeRegistryApi";
import { apiClient } from "@/services/api";

vi.mock("@/services/api", () => ({
  apiClient: {
    get: vi.fn()
  }
}));

const mockedGet = vi.mocked(apiClient.get);

describe("getNodeRegistry", () => {
  it("fetches /nodes/registry and returns response payload", async () => {
    const responseData = {
      version: "1.0.0",
      categories: [{ category_id: "input", display_name: "輸入源" }],
      nodes: [
        {
          node_type: "processor/adaptor",
          display_name: "Adaptor",
          category: "processor",
          config_schema: {
            type: "object",
            properties: {
              code: { type: "string" },
              input_mode: { type: "string", enum: ["all_upstream", "custom_bindings"] },
              input_bindings: {
                type: "array",
                items: {
                  type: "object",
                  properties: {
                    name: { type: "string", minLength: 1 },
                    selector: { type: "array", items: { type: "string" }, minItems: 2 }
                  },
                  required: ["name", "selector"]
                }
              }
            },
            required: ["code"]
          },
          input_ports: [{ name: "input", accepted_types: ["*/*"], required: true, max_connections: -1 }],
          output_types: ["application/x-adaptor-output"],
          max_inputs: -1,
          max_outputs: -1
        },
        {
          node_type: "processor/iteration",
          display_name: "Iteration",
          category: "processor",
          config_schema: {
            type: "object",
            properties: {
              engine_node_type: { type: "string" },
              engine_config: { type: "object", properties: {} },
              iterate_over: { type: "string" },
              item_input_port: { type: "string" },
              mode: { type: "string" },
              max_concurrency: { type: "integer", minimum: 1, maximum: 10 },
              error_handling: { type: "string" }
            },
            required: [
              "engine_node_type",
              "engine_config",
              "iterate_over",
              "item_input_port",
              "mode",
              "max_concurrency",
              "error_handling"
            ]
          },
          input_ports: [{ name: "input", accepted_types: ["*/*"], required: true, max_connections: 1 }],
          output_types: ["application/x-iteration-output"],
          max_inputs: 1,
          max_outputs: -1
        }
      ],
      connection_rules: []
    };

    mockedGet.mockResolvedValue({ data: responseData });

    await expect(getNodeRegistry()).resolves.toEqual(responseData);
    expect(mockedGet).toHaveBeenCalledWith("/nodes/registry");
  });
});
