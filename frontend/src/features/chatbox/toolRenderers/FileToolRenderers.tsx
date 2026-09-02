import { useTranslation } from "react-i18next";

import { ToolCard } from "@/features/chatbox/toolRenderers/ToolCard";
import { OutputImage } from "@/features/chatbox/toolRenderers/OutputImage";
import { TruncationTags } from "@/features/chatbox/toolRenderers/TruncationTags";
import {
  argNumber,
  argString,
  payloadDiff,
  payloadText,
  truncateToolPreview,
  type ToolRendererProps
} from "@/features/chatbox/toolRenderers/types";

function diffLineClass(line: string): "add" | "del" | "ctx" {
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  return "ctx";
}

export function ReadToolRenderer({ exec, forceExpand }: ToolRendererProps) {
  const { t } = useTranslation("chatbox");
  const path = argString(exec.args, "path");
  const offset = argNumber(exec.args, "offset");
  const limit = argNumber(exec.args, "limit");
  const range = [
    offset === null ? null : t("readOffset", { value: offset }),
    limit === null ? null : t("readLimit", { value: limit }),
  ].filter((part): part is string => part !== null).join(" · ");
  return (
    <ToolCard
      forceExpand={forceExpand}
      meta={<TruncationTags exec={exec} />}
      status={exec.status}
      title={`${t("tools.read")} ${path}${range ? ` (${range})` : ""}`}
    >
      <OutputImage exec={exec} />
      <pre className="chatbox-tool-output">{payloadText(exec.result) || payloadText(exec.partial)}</pre>
    </ToolCard>
  );
}

export function WriteToolRenderer({ exec, forceExpand }: ToolRendererProps) {
  const { t } = useTranslation("chatbox");
  const path = argString(exec.args, "path");
  const rawContent = exec.args?.content;
  const fullContent = typeof rawContent === "string" ? rawContent : payloadText(exec.result);
  const content = truncateToolPreview(fullContent);
  return (
    <ToolCard forceExpand={forceExpand} meta={<TruncationTags exec={exec} />} status={exec.status} title={`${t("tools.write")} ${path}`}>
      <pre className="chatbox-tool-output">
        {content.text}
        {content.omittedCharacters > 0
          ? `\n${t("previewTruncated", { count: content.omittedCharacters })}`
          : ""}
      </pre>
    </ToolCard>
  );
}

export function EditToolRenderer({ exec, forceExpand }: ToolRendererProps) {
  const { t } = useTranslation("chatbox");
  const path = argString(exec.args, "path");
  const diff = payloadDiff(exec.result);
  const diffPreview = truncateToolPreview(diff);
  return (
    <ToolCard forceExpand={forceExpand} status={exec.status} title={`${t("tools.edit")} ${path}`}>
      {diff ? (
        <pre className="chatbox-tool-diff" data-testid="chatbox-edit-diff">
          {diffPreview.text.split("\n").map((line, index) => (
            <span className={`chatbox-diff-line chatbox-diff-${diffLineClass(line)}`} key={index}>
              {line}
            </span>
          ))}
          {diffPreview.omittedCharacters > 0 ? (
            <span className="chatbox-diff-line chatbox-diff-ctx">
              {t("previewTruncated", { count: diffPreview.omittedCharacters })}
            </span>
          ) : null}
        </pre>
      ) : (
        <pre className="chatbox-tool-output">{payloadText(exec.result)}</pre>
      )}
    </ToolCard>
  );
}
