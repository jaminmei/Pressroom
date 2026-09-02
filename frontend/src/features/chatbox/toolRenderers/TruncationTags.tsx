import { Tag } from "antd";
import { useTranslation } from "react-i18next";

import {
  payloadFullOutputPath,
  payloadResultLimitReached,
  payloadTruncation,
  type ToolRendererProps,
} from "@/features/chatbox/toolRenderers/types";

export function TruncationTags({ exec }: { readonly exec: ToolRendererProps["exec"] }) {
  const { t } = useTranslation("chatbox");
  const truncation = payloadTruncation(exec.result) ?? payloadTruncation(exec.partial);
  const resultLimitReached = payloadResultLimitReached(exec.result)
    || payloadResultLimitReached(exec.partial);
  const fullOutputPath = truncation?.fullOutputPath
    ?? payloadFullOutputPath(exec.result)
    ?? payloadFullOutputPath(exec.partial);
  if (truncation === null && !resultLimitReached) return null;
  return (
    <span className="chatbox-tool-tags">
      <Tag>{t("truncated")}</Tag>
      {fullOutputPath ? (
        <span className="chatbox-tool-path">{fullOutputPath}</span>
      ) : null}
    </span>
  );
}
