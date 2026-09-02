import { useTranslation } from "react-i18next";

import { ToolCard } from "@/features/chatbox/toolRenderers/ToolCard";
import { TruncationTags } from "@/features/chatbox/toolRenderers/TruncationTags";
import {
  argString,
  payloadText,
  truncateToolPreview,
  type ToolRendererProps
} from "@/features/chatbox/toolRenderers/types";

export function QueryToolRenderer({ exec, forceExpand, toolLabel }: ToolRendererProps & { readonly toolLabel: string }) {
  const { t } = useTranslation("chatbox");
  const query = argString(exec.args, "pattern") || argString(exec.args, "path");
  const output = truncateToolPreview(payloadText(exec.result) || payloadText(exec.partial));
  return (
    <ToolCard
      forceExpand={forceExpand}
      meta={<TruncationTags exec={exec} />}
      status={exec.status}
      title={query ? `${toolLabel} ${query}` : toolLabel}
    >
      <pre className="chatbox-tool-output">
        {output.text}
        {output.omittedCharacters > 0
          ? `\n${t("previewTruncated", { count: output.omittedCharacters })}`
          : ""}
      </pre>
    </ToolCard>
  );
}

export function GrepToolRenderer(props: ToolRendererProps) {
  const { t } = useTranslation("chatbox");
  return <QueryToolRenderer {...props} toolLabel={t("tools.grep")} />;
}

export function FindToolRenderer(props: ToolRendererProps) {
  const { t } = useTranslation("chatbox");
  return <QueryToolRenderer {...props} toolLabel={t("tools.find")} />;
}

export function LsToolRenderer(props: ToolRendererProps) {
  const { t } = useTranslation("chatbox");
  return <QueryToolRenderer {...props} toolLabel={t("tools.ls")} />;
}
