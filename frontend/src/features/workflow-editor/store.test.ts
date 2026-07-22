import { act, renderHook } from "@testing-library/react";

import type { NodeRegistryResponse } from "@/types/node-registry";
import type { WorkflowNode } from "@/types/workflow";

import { useWorkflowStore } from "./store";

// Mock node registry data
const mockNodeRegistry: Pick<NodeRegistryResponse, "nodes" | "connection_rules"> = {
  nodes: [
    {
      node_type: "input/file",
      display_name: "File Input",
      category: "input",
      config_schema: { type: "object", properties: {} },
      input_types: [],
      output_types: ["file"]
    },
    {
      node_type: "engine/ocr",
      display_name: "OCR Engine",
      category: "engine",
      config_schema: {
        type: "object",
        properties: {
          language: { type: "string", default: "ch" }
        }
      },
      input_types: ["file"],
      output_types: ["text"]
    },
    {
      node_type: "output/markdown",
      display_name: "Markdown Output",
      category: "output",
      config_schema: { type: "object", properties: {} },
      input_types: ["text"],
      output_types: []
    },
    {
      node_type: "end/final",
      display_name: "Workflow End",
      category: "end",
      config_schema: { type: "object", properties: {} },
      input_types: ["text"],
      output_types: [],
      max_inputs: -1,
      max_outputs: 0
    }
  ],
  connection_rules: []
};

describe("useWorkflowStore", () => {
  // Reset store before each test
  beforeEach(() => {
    act(() => {
      useWorkflowStore.getState().clearCanvas();
      useWorkflowStore.getState().setNodeRegistry(mockNodeRegistry);
    });
  });

  describe("initial state", () => {
    it("should have empty initial state", () => {
      const { result } = renderHook(() => useWorkflowStore());

      expect(result.current.nodes).toEqual([]);
      expect(result.current.edges).toEqual([]);
      expect(result.current.nodeConfigs).toEqual({});
      expect(result.current.uploadedFiles).toEqual({});
      expect(result.current.selectedNodeId).toBeNull();
    });
  });

  describe("addNode", () => {
    it("should add a node with correct type and position", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("input/file", { x: 100, y: 200 });
      });

      expect(result.current.nodes).toHaveLength(1);
      expect(result.current.nodes[0].type).toBe("input/file");
      expect(result.current.nodes[0].position).toEqual({ x: 100, y: 200 });
    });

    it("should use display_name from registry as label", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("input/file", { x: 0, y: 0 });
      });

      expect(result.current.nodes[0].data.label).toBe("File Input");
    });

    it("should initialize nodeConfigs for new node", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("input/file", { x: 0, y: 0 });
      });

      const nodeId = result.current.nodes[0].id;
      expect(result.current.nodeConfigs[nodeId]).toEqual({});
    });

    it("should generate unique node IDs", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("input/file", { x: 0, y: 0 });
        result.current.addNode("input/file", { x: 100, y: 100 });
      });

      expect(result.current.nodes).toHaveLength(2);
    });

    it("should populate config with default values from schema", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("engine/ocr", { x: 200, y: 0 });
      });

      const node = result.current.nodes[0];
      expect(node.data.config).toEqual({ language: "ch" });
      expect(result.current.nodeConfigs[node.id]).toEqual({ language: "ch" });
    });

    it("should use empty config for nodes with no schema defaults", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("input/file", { x: 0, y: 0 });
      });

      const node = result.current.nodes[0];
      expect(node.data.config).toEqual({});
      expect(result.current.nodeConfigs[node.id]).toEqual({});
    });

    it("requires the end node to be added explicitly", () => {
      const { result } = renderHook(() => useWorkflowStore());
      const endNodeRegistry: Pick<NodeRegistryResponse, "nodes" | "connection_rules"> = {
        nodes: [
          ...mockNodeRegistry.nodes,
          {
            node_type: "end/final",
            display_name: "Workflow End",
            category: "end",
            config_schema: { type: "object", properties: {} },
            input_types: ["text"],
            output_types: []
          }
        ],
        connection_rules: [
          { from_category: "input", to_categories: ["engine"] },
          { from_category: "engine", to_categories: ["output"] },
          { from_category: "output", to_categories: ["end"] }
        ]
      };

      act(() => {
        result.current.setNodeRegistry(endNodeRegistry);
        result.current.addNode("output/markdown", { x: 420, y: 0 });
        result.current.addNode("end/final", { x: 720, y: 0 });
      });

      expect(result.current.nodes.filter((node) => node.type.startsWith("output/"))).toHaveLength(0);
      expect(result.current.nodes.filter((node) => node.type === "end/final")).toHaveLength(1);
    });
  });

  describe("removeNode", () => {
    it("should remove node from nodes array", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("input/file", { x: 0, y: 0 });
      });
      const nodeId = result.current.nodes[0].id;

      act(() => {
        result.current.removeNode(nodeId);
      });

      expect(result.current.nodes).toHaveLength(0);
    });

    it("should remove node from nodeConfigs", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("input/file", { x: 0, y: 0 });
      });
      const nodeId = result.current.nodes[0].id;

      act(() => {
        result.current.removeNode(nodeId);
      });

      expect(result.current.nodeConfigs[nodeId]).toBeUndefined();
    });

    it("should remove connected edges", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("input/file", { x: 0, y: 0 });
        result.current.addNode("engine/ocr", { x: 200, y: 0 });
      });

      const sourceId = result.current.nodes[0].id;
      const targetId = result.current.nodes[1].id;

      act(() => {
        result.current.addEdge({ id: "edge-1", source: sourceId, target: targetId });
      });

      expect(result.current.edges).toHaveLength(1);

      act(() => {
        result.current.removeNode(sourceId);
      });

      expect(result.current.edges).toHaveLength(0);
    });

    it("should clear selectedNodeId if removed node was selected", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("input/file", { x: 0, y: 0 });
      });
      const nodeId = result.current.nodes[0].id;

      act(() => {
        result.current.selectNode(nodeId);
      });
      expect(result.current.selectedNodeId).toBe(nodeId);

      act(() => {
        result.current.removeNode(nodeId);
      });
      expect(result.current.selectedNodeId).toBeNull();
    });
  });

  describe("removeNodes", () => {
    it("should remove multiple nodes and linked edges in one action", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("input/file", { x: 0, y: 0 });
        result.current.addNode("engine/ocr", { x: 220, y: 0 });
        result.current.addNode("end/final", { x: 440, y: 0 });
      });

      const inputId = result.current.nodes[0].id;
      const engineId = result.current.nodes[1].id;
      const endId = result.current.nodes[2].id;

      act(() => {
        result.current.addEdge({ id: "edge-1", source: inputId, target: engineId });
        result.current.addEdge({ id: "edge-2", source: engineId, target: endId });
      });

      act(() => {
        result.current.removeNodes([inputId, engineId]);
      });

      expect(result.current.nodes.map((node) => node.id)).toEqual([endId]);
      expect(result.current.edges).toEqual([]);
      expect(result.current.nodeConfigs[inputId]).toBeUndefined();
      expect(result.current.nodeConfigs[engineId]).toBeUndefined();
      expect(result.current.nodeConfigs[endId]).toEqual({});
    });
  });

  describe("addEdge", () => {
    it("should add edge to edges array", () => {
      const { result } = renderHook(() => useWorkflowStore());

      const edge = { id: "edge-1", source: "node-1", target: "node-2" };

      act(() => {
        result.current.addEdge(edge);
      });

      expect(result.current.edges).toHaveLength(1);
      expect(result.current.edges[0]).toEqual(edge);
    });
  });

  describe("duplicateNodes", () => {
    it("duplicates selected nodes with (50, 50) offset and keeps internal edges", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("input/file", { x: 10, y: 20 });
        result.current.addNode("engine/ocr", { x: 260, y: 120 });
        result.current.addNode("end/final", { x: 520, y: 160 });
      });

      const inputId = result.current.nodes[0].id;
      const engineId = result.current.nodes[1].id;
      const endId = result.current.nodes[2].id;

      act(() => {
        result.current.addEdge({ id: "edge-1", source: inputId, target: engineId });
        result.current.addEdge({ id: "edge-2", source: engineId, target: endId });
      });

      let duplicatedIds: string[] = [];
      act(() => {
        duplicatedIds = result.current.duplicateNodes([inputId, engineId]);
      });

      expect(duplicatedIds).toHaveLength(2);
      expect(result.current.nodes).toHaveLength(5);
      expect(result.current.nodes.filter((node) => node.type === "end/final")).toHaveLength(1);
      expect(result.current.selectedNodeId).toBe(duplicatedIds[0]);

      const duplicatedInput = result.current.nodes.find((node) => node.id === duplicatedIds[0]);
      const duplicatedEngine = result.current.nodes.find((node) => node.id === duplicatedIds[1]);

      expect(duplicatedInput?.position).toEqual({ x: 60, y: 70 });
      expect(duplicatedEngine?.position).toEqual({ x: 310, y: 170 });
      expect(result.current.edges.some((edge) => edge.source === duplicatedIds[0] && edge.target === duplicatedIds[1])).toBe(
        true
      );
      expect(result.current.edges.some((edge) => edge.source === engineId && edge.target === endId)).toBe(true);
      expect(result.current.edges.some((edge) => edge.source === duplicatedIds[1] && edge.target === endId)).toBe(false);
    });

    it("does not duplicate legacy output nodes removed during normalization", () => {
      const { result } = renderHook(() => useWorkflowStore());
      const endNodeRegistry: Pick<NodeRegistryResponse, "nodes" | "connection_rules"> = {
        nodes: [
          ...mockNodeRegistry.nodes,
          {
            node_type: "end/final",
            display_name: "Workflow End",
            category: "end",
            config_schema: { type: "object", properties: {} },
            input_types: ["text"],
            output_types: []
          }
        ],
        connection_rules: [
          { from_category: "input", to_categories: ["engine"] },
          { from_category: "engine", to_categories: ["output"] },
          { from_category: "output", to_categories: ["end"] }
        ]
      };

      act(() => {
        result.current.setNodeRegistry(endNodeRegistry);
        result.current.addNode("output/markdown", { x: 520, y: 160 });
      });

      const outputId = "output_markdown_1";
      expect(result.current.nodes.find((node) => node.type === "output/markdown")).toBeUndefined();

      let duplicatedIds: string[] = [];
      act(() => {
        duplicatedIds = result.current.duplicateNodes([outputId]);
      });

      expect(duplicatedIds).toHaveLength(0);
      expect(result.current.nodes).toHaveLength(0);
    });
  });

  describe("alignNodes", () => {
    it("aligns horizontal and vertical with first selected node as anchor", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("input/file", { x: 40, y: 60 });
        result.current.addNode("engine/ocr", { x: 220, y: 180 });
        result.current.addNode("end/final", { x: 420, y: 260 });
      });

      const firstId = result.current.nodes[0].id;
      const secondId = result.current.nodes[1].id;
      const thirdId = result.current.nodes[2].id;

      act(() => {
        result.current.alignNodes([firstId, secondId, thirdId], "horizontal");
      });
      expect(result.current.nodes.find((node) => node.id === secondId)?.position?.y).toBe(60);
      expect(result.current.nodes.find((node) => node.id === thirdId)?.position?.y).toBe(60);

      act(() => {
        result.current.alignNodes([firstId, secondId, thirdId], "vertical");
      });
      expect(result.current.nodes.find((node) => node.id === secondId)?.position?.x).toBe(40);
      expect(result.current.nodes.find((node) => node.id === thirdId)?.position?.x).toBe(40);
    });
  });

  describe("insertNodeBetweenEdge", () => {
    it("inserts a node and splits target edge into two edges", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("input/file", { x: 0, y: 0 });
        result.current.addNode("end/final", { x: 300, y: 0 });
      });
      const sourceId = result.current.nodes[0].id;
      const targetId = result.current.nodes[1].id;

      act(() => {
        result.current.addEdge({ id: "edge-main", source: sourceId, target: targetId });
      });

      let insertedId: string | null = null;
      act(() => {
        insertedId = result.current.insertNodeBetweenEdge(
          "edge-main",
          "engine/ocr",
          { x: 150, y: 0 }
        );
      });

      expect(insertedId).toBeTruthy();
      expect(result.current.nodes.some((node) => node.id === insertedId)).toBe(true);
      expect(result.current.edges.some((edge) => edge.id === "edge-main")).toBe(false);
      expect(
        result.current.edges.some((edge) => edge.source === sourceId && edge.target === insertedId)
      ).toBe(true);
      expect(
        result.current.edges.some((edge) => edge.source === insertedId && edge.target === targetId)
      ).toBe(true);
      expect(result.current.nodeConfigs[insertedId!]).toEqual({ language: "ch" });
    });

    it("returns null when target edge does not exist", () => {
      const { result } = renderHook(() => useWorkflowStore());

      let insertedId: string | null = "init";
      act(() => {
        insertedId = result.current.insertNodeBetweenEdge("missing-edge", "engine/ocr");
      });

      expect(insertedId).toBeNull();
      expect(result.current.nodes).toHaveLength(0);
      expect(result.current.edges).toHaveLength(0);
    });
  });

  describe("duplicateNode", () => {
    it("duplicates a single node with +32 offset and same config", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("engine/ocr", { x: 120, y: 80 });
      });
      const sourceId = result.current.nodes[0].id;

      act(() => {
        result.current.updateNodeConfig(sourceId, { language: "en" });
      });

      let duplicatedId: string | null = null;
      act(() => {
        duplicatedId = result.current.duplicateNode(sourceId);
      });

      expect(duplicatedId).toBeTruthy();
      expect(result.current.nodes).toHaveLength(2);
      const duplicated = result.current.nodes.find((node) => node.id === duplicatedId);
      expect(duplicated?.position).toEqual({ x: 152, y: 112 });
      expect(result.current.nodeConfigs[duplicatedId!]).toEqual({ language: "en" });
    });

    it("returns null when a legacy output node was normalized away", () => {
      const { result } = renderHook(() => useWorkflowStore());
      const endNodeRegistry: Pick<NodeRegistryResponse, "nodes" | "connection_rules"> = {
        nodes: [
          ...mockNodeRegistry.nodes,
          {
            node_type: "end/final",
            display_name: "Workflow End",
            category: "end",
            config_schema: { type: "object", properties: {} },
            input_types: ["text"],
            output_types: []
          }
        ],
        connection_rules: [
          { from_category: "input", to_categories: ["engine"] },
          { from_category: "engine", to_categories: ["output"] },
          { from_category: "output", to_categories: ["end"] }
        ]
      };

      act(() => {
        result.current.setNodeRegistry(endNodeRegistry);
        result.current.addNode("output/markdown", { x: 520, y: 160 });
      });

      const outputId = "output_markdown_1";
      expect(result.current.nodes.find((node) => node.type === "output/markdown")).toBeUndefined();

      let duplicatedId: string | null = null;
      act(() => {
        duplicatedId = result.current.duplicateNode(outputId);
      });

      expect(duplicatedId).toBeNull();
      expect(result.current.nodes).toHaveLength(0);
    });

    it("returns null when source node does not exist", () => {
      const { result } = renderHook(() => useWorkflowStore());

      let duplicatedId: string | null = "init";
      act(() => {
        duplicatedId = result.current.duplicateNode("missing-node");
      });

      expect(duplicatedId).toBeNull();
      expect(result.current.nodes).toHaveLength(0);
    });
  });

  describe("updateNodeConfig", () => {
    it("should update nodeConfigs", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("engine/ocr", { x: 0, y: 0 });
      });
      const nodeId = result.current.nodes[0].id;

      act(() => {
        result.current.updateNodeConfig(nodeId, { language: "en" });
      });

      expect(result.current.nodeConfigs[nodeId]).toEqual({ language: "en" });
    });

    it("should sync config to node.data.config", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("engine/ocr", { x: 0, y: 0 });
      });
      const nodeId = result.current.nodes[0].id;

      act(() => {
        result.current.updateNodeConfig(nodeId, { language: "en" });
      });

      const node = result.current.nodes.find((n) => n.id === nodeId);
      expect(node?.data.config).toEqual({ language: "en" });
    });

    it("should merge with existing config", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("engine/ocr", { x: 0, y: 0 });
      });
      const nodeId = result.current.nodes[0].id;

      act(() => {
        result.current.updateNodeConfig(nodeId, { language: "en" });
        result.current.updateNodeConfig(nodeId, { use_angle_cls: true });
      });

      expect(result.current.nodeConfigs[nodeId]).toEqual({
        language: "en",
        use_angle_cls: true
      });
    });

    it("should filter undefined values from config", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.addNode("engine/ocr", { x: 0, y: 0 });
      });
      const nodeId = result.current.nodes[0].id;

      act(() => {
        result.current.updateNodeConfig(nodeId, { language: "en", temp: undefined });
      });

      expect(result.current.nodeConfigs[nodeId]).toEqual({ language: "en" });
      expect("temp" in result.current.nodeConfigs[nodeId]).toBe(false);
    });
  });

  describe("setNodes", () => {
    it("should replace nodes array", () => {
      const { result } = renderHook(() => useWorkflowStore());

      const newNodes: WorkflowNode[] = [
        {
          id: "custom-1",
          type: "input/file",
          data: {
            label: "Custom Node",
            config: { path: "/test" },
            configSchema: { type: "object" as const, properties: {} }
          },
          position: { x: 0, y: 0 }
        }
      ];

      act(() => {
        result.current.setNodes(newNodes);
      });

      expect(result.current.nodes).toEqual(newNodes);
    });

    it("should sync nodeConfigs from nodes", () => {
      const { result } = renderHook(() => useWorkflowStore());

      const newNodes: WorkflowNode[] = [
        {
          id: "custom-1",
          type: "input/file",
          data: {
            label: "Custom Node",
            config: { path: "/test" },
            configSchema: { type: "object" as const, properties: {} }
          },
          position: { x: 0, y: 0 }
        }
      ];

      act(() => {
        result.current.setNodes(newNodes);
      });

      expect(result.current.nodeConfigs["custom-1"]).toEqual({ path: "/test" });
    });
  });

  describe("setEdges", () => {
    it("should replace edges array", () => {
      const { result } = renderHook(() => useWorkflowStore());

      const newEdges = [
        { id: "edge-1", source: "node-1", target: "node-2" },
        { id: "edge-2", source: "node-2", target: "node-3" }
      ];

      act(() => {
        result.current.setEdges(newEdges);
      });

      expect(result.current.edges).toEqual(newEdges);
    });
  });

  describe("selectNode", () => {
    it("should set selectedNodeId", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.selectNode("node-1");
      });

      expect(result.current.selectedNodeId).toBe("node-1");
    });

    it("should clear selectedNodeId when passed null", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.selectNode("node-1");
      });
      expect(result.current.selectedNodeId).toBe("node-1");

      act(() => {
        result.current.selectNode(null);
      });
      expect(result.current.selectedNodeId).toBeNull();
    });
  });

  describe("setUploadedFile / removeUploadedFile", () => {
    it("should store uploaded file", () => {
      const { result } = renderHook(() => useWorkflowStore());
      const mockFile = new File(["test"], "test.pdf", { type: "application/pdf" });

      act(() => {
        result.current.setUploadedFile("node-1", mockFile);
      });

      expect(result.current.uploadedFiles["node-1"]).toBe(mockFile);
    });

    it("should remove uploaded file", () => {
      const { result } = renderHook(() => useWorkflowStore());
      const mockFile = new File(["test"], "test.pdf", { type: "application/pdf" });

      act(() => {
        result.current.setUploadedFile("node-1", mockFile);
      });
      expect(result.current.uploadedFiles["node-1"]).toBe(mockFile);

      act(() => {
        result.current.removeUploadedFile("node-1");
      });
      expect(result.current.uploadedFiles["node-1"]).toBeUndefined();
    });
  });

  describe("clearCanvas", () => {
    it("should reset all state to initial", () => {
      const { result } = renderHook(() => useWorkflowStore());
      const mockFile = new File(["test"], "test.pdf", { type: "application/pdf" });

      // Add some data
      act(() => {
        result.current.addNode("input/file", { x: 0, y: 0 });
        result.current.addNode("engine/ocr", { x: 200, y: 0 });
      });

      const firstNodeId = result.current.nodes[0].id;
      const secondNodeId = result.current.nodes[1].id;

      act(() => {
        result.current.addEdge({ id: "edge-1", source: firstNodeId, target: secondNodeId });
        result.current.selectNode(firstNodeId);
        result.current.setUploadedFile(firstNodeId, mockFile);
        result.current.updateNodeConfig(firstNodeId, { test: true });
      });

      // Clear
      act(() => {
        result.current.clearCanvas();
      });

      expect(result.current.nodes).toEqual([]);
      expect(result.current.edges).toEqual([]);
      expect(result.current.nodeConfigs).toEqual({});
      expect(result.current.uploadedFiles).toEqual({});
      expect(result.current.selectedNodeId).toBeNull();
    });

    it("should preserve nodeRegistry after clear", () => {
      const { result } = renderHook(() => useWorkflowStore());

      act(() => {
        result.current.clearCanvas();
      });

      expect(result.current.nodeRegistry).toEqual(mockNodeRegistry);
    });
  });

  describe("setNodeRegistry", () => {
    it("should update nodeRegistry", () => {
      const { result } = renderHook(() => useWorkflowStore());

      const newRegistry: Pick<NodeRegistryResponse, "nodes" | "connection_rules"> = {
        nodes: [
          {
            node_type: "input/url",
            display_name: "URL Input",
            category: "input",
            config_schema: { type: "object", properties: {} },
            input_types: [],
            output_types: ["url"]
          }
        ],
        connection_rules: []
      };

      act(() => {
        result.current.setNodeRegistry(newRegistry);
      });

      expect(result.current.nodeRegistry).toEqual(newRegistry);
    });
  });
});
