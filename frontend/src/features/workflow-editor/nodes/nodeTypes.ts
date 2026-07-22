import type { NodeTypes } from "@xyflow/react";

import type { WorkflowCanvasNodeData } from "@/features/workflow-editor/nodes/CategoryNodeBase";
import EngineNode from "@/features/workflow-editor/nodes/EngineNode";
import EndNode from "@/features/workflow-editor/nodes/EndNode";
import InputNode from "@/features/workflow-editor/nodes/InputNode";
import ProcessorNode from "@/features/workflow-editor/nodes/ProcessorNode";

export const workflowNodeTypes = {
  inputNode: InputNode,
  processorNode: ProcessorNode,
  engineNode: EngineNode,
  endNode: EndNode
} as NodeTypes;

export type WorkflowNodeComponentType = keyof typeof workflowNodeTypes;

export function resolveWorkflowNodeComponentType(nodeType: string): WorkflowNodeComponentType {
  const category = nodeType.split("/")[0];

  if (category === "input") {
    return "inputNode";
  }

  if (category === "processor") {
    return "processorNode";
  }

  if (category === "engine") {
    return "engineNode";
  }

  if (category === "end") {
    return "endNode";
  }

  return "processorNode";
}

export type { WorkflowCanvasNodeData };
