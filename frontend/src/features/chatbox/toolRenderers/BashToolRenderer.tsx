import { useTranslation } from "react-i18next";

import { ToolCard } from "@/features/chatbox/toolRenderers/ToolCard";
import { TruncationTags } from "@/features/chatbox/toolRenderers/TruncationTags";
import {
  argString,
  payloadText,
  type ToolRendererProps
} from "@/features/chatbox/toolRenderers/types";

const MAX_COMMAND_TITLE_LENGTH = 60;

function commandTitle(command: string): string {
  const normalized = command.replace(/\s+/g, " ").trim();
  return normalized.length > MAX_COMMAND_TITLE_LENGTH
    ? `${normalized.slice(0, MAX_COMMAND_TITLE_LENGTH)}...`
    : normalized;
}

export function BashToolRenderer({ exec, forceExpand }: ToolRendererProps) {
  const { t } = useTranslation("chatbox");
  const command = commandTitle(argString(exec.args, "command"));
  const live = payloadText(exec.partial);
  const finalText = payloadText(exec.result);
  return (
    <ToolCard
      forceExpand={forceExpand}
      meta={<TruncationTags exec={exec} />}
      status={exec.status}
      title={command ? `${t("tools.bash")} ${command}` : t("tools.bash")}
    >
      {exec.status === "pending" ? (
        live ? <pre className="chatbox-tool-output" data-testid="chatbox-bash-live">{live}</pre> : null
      ) : (
        <pre className="chatbox-tool-output" data-testid="chatbox-bash-output">{finalText || live}</pre>
      )}
    </ToolCard>
  );
}
