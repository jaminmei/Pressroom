import { createElement } from "react";

import { getCategoryIcon } from "@/components/Icons";
import {
  CategoryNodeBase,
  type WorkflowNodeComponentProps
} from "@/features/workflow-editor/nodes/CategoryNodeBase";

export default function EndNode(props: WorkflowNodeComponentProps) {
  return <CategoryNodeBase {...props} className="workflow-node-end" icon={createElement(getCategoryIcon("output"), { size: 24 })} titleColor="#0d9488" />;
}
