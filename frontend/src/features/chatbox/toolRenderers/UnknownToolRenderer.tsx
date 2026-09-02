import { useTranslation } from "react-i18next";

import { ToolCard } from "@/features/chatbox/toolRenderers/ToolCard";
import { OutputImage } from "@/features/chatbox/toolRenderers/OutputImage";
import {
  payloadText,
  truncateToolPreview,
  type ToolRendererProps
} from "@/features/chatbox/toolRenderers/types";

function serializeArguments(args: Record<string, unknown>): string | null {
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return null;
  }
}

function previewText(text: string, truncationNotice: (count: number) => string): string {
  const preview = truncateToolPreview(text);
  return preview.omittedCharacters > 0
    ? `${preview.text}\n${truncationNotice(preview.omittedCharacters)}`
    : preview.text;
}

export function UnknownToolRenderer({ exec, forceExpand }: ToolRendererProps) {
  const { t } = useTranslation("chatbox");
  const serializedArguments = exec.args === null ? null : serializeArguments(exec.args);
  let argumentText: string;
  if (exec.args === null) argumentText = t("noArguments");
  else if (serializedArguments === null) argumentText = t("argumentsUnavailable");
  else argumentText = previewText(
    serializedArguments,
    (count) => t("previewTruncated", { count }),
  );
  const resultText = previewText(
    payloadText(exec.result) || payloadText(exec.partial),
    (count) => t("previewTruncated", { count }),
  );
  return (
    <ToolCard forceExpand={forceExpand} status={exec.status} title={`${t("tools.unknown")} ${exec.toolName}`}>
      <pre className="chatbox-tool-output" data-testid="chatbox-unknown-args">
        {argumentText}
      </pre>
      <pre className="chatbox-tool-output" data-testid="chatbox-unknown-result">{resultText}</pre>
      <OutputImage exec={exec} />
    </ToolCard>
  );
}
