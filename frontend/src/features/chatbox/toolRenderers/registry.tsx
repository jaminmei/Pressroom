import type { ComponentType } from "react";

import { BashToolRenderer } from "@/features/chatbox/toolRenderers/BashToolRenderer";
import { EditToolRenderer, ReadToolRenderer, WriteToolRenderer } from "@/features/chatbox/toolRenderers/FileToolRenderers";
import { FindToolRenderer, GrepToolRenderer, LsToolRenderer } from "@/features/chatbox/toolRenderers/QueryToolRenderers";
import { PressroomToolRenderer } from "@/features/chatbox/toolRenderers/PressroomToolRenderer";
import { UnknownToolRenderer } from "@/features/chatbox/toolRenderers/UnknownToolRenderer";
import type { ToolRendererProps } from "@/features/chatbox/toolRenderers/types";

export const toolRendererRegistry: Readonly<Record<string, ComponentType<ToolRendererProps>>> = {
  read: ReadToolRenderer,
  bash: BashToolRenderer,
  edit: EditToolRenderer,
  write: WriteToolRenderer,
  grep: GrepToolRenderer,
  find: FindToolRenderer,
  ls: LsToolRenderer
};

export function getToolRenderer(toolName: string): ComponentType<ToolRendererProps> {
  if (toolName.startsWith("workflow_")) return PressroomToolRenderer;
  return toolRendererRegistry[toolName] ?? UnknownToolRenderer;
}
