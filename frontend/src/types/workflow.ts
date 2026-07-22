import type { InputPortDef, NodeConfigSchema } from "@/types/node-registry";
import type { CSSProperties } from "react";

export interface NodePosition {
  x: number;
  y: number;
}

export interface WorkflowEdgeData extends Record<string, unknown> {
  isTypeWarning?: boolean;
  warningCode?: string;
  executionStatus?: string;
  hideAddControl?: boolean;
}

export interface WorkflowNodeData {
  label: string;
  config: Record<string, unknown>;
  configSchema: NodeConfigSchema;
  inputTypes?: string[];
  outputTypes?: string[];
  maxInputs?: number;
  inputPorts?: InputPortDef[];
}

export interface WorkflowNode {
  id: string;
  type: string;
  data: WorkflowNodeData;
  position?: NodePosition;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
  style?: CSSProperties;
  data?: WorkflowEdgeData;
}
