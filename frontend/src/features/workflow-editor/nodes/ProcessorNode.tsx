import { createElement } from "react";

import { getCategoryIcon } from "@/components/Icons";
import {
  CategoryNodeBase,
  type WorkflowNodeComponentProps
} from "@/features/workflow-editor/nodes/CategoryNodeBase";

export default function ProcessorNode(props: WorkflowNodeComponentProps) {
  return <CategoryNodeBase {...props} className="workflow-node-processor" icon={createElement(getCategoryIcon("processor"), { size: 24 })} titleColor="#6d5efa" />;
}
