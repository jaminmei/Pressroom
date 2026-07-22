import { createElement } from "react";

import { getCategoryIcon } from "@/components/Icons";
import {
  CategoryNodeBase,
  type WorkflowNodeComponentProps
} from "@/features/workflow-editor/nodes/CategoryNodeBase";

export default function InputNode(props: WorkflowNodeComponentProps) {
  return <CategoryNodeBase {...props} className="workflow-node-input" icon={createElement(getCategoryIcon("input"), { size: 24 })} titleColor="#2ba471" />;
}
