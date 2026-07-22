import type { NodePosition, WorkflowNodeData } from "@/types/workflow";

export type TemplateCategory = "basic" | "comparison";
export type TemplateOutputFormat = "markdown" | "text" | "yaml";

export interface TemplateNode {
  id: string;
  type: string;
  position: NodePosition;
  data: Pick<WorkflowNodeData, "label" | "config">;
}

export interface TemplateConnection {
  id: string;
  source: string;
  target: string;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  icon: string;
  category: TemplateCategory;
  tags: string[];
  supported_input_types: string[];
  default_output_format: TemplateOutputFormat;
  nodes: TemplateNode[];
  connections: TemplateConnection[];
}
