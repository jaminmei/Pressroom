import { createElement } from "react";

import { getCategoryIcon } from "@/components/Icons";
import {
  CategoryNodeBase,
  type WorkflowNodeComponentProps
} from "@/features/workflow-editor/nodes/CategoryNodeBase";

export default function EngineNode(props: WorkflowNodeComponentProps) {
  return <CategoryNodeBase {...props} className="workflow-node-engine" icon={createElement(getCategoryIcon("engine"), { size: 24 })} titleColor="#296dff" />;
}
