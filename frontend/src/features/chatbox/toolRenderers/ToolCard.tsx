import { DownOutlined, RightOutlined } from "@ant-design/icons";
import { Tag } from "antd";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ToolStatus } from "@/features/chatbox/toolRenderers/types";

interface ToolCardProps {
  readonly title: string;
  readonly status: ToolStatus;
  readonly meta?: ReactNode;
  readonly forceExpand: boolean;
  readonly children: ReactNode;
}

export function ToolCard({ title, status, meta, forceExpand, children }: ToolCardProps) {
  const { t } = useTranslation("chatbox");
  const [expanded, setExpanded] = useState(false);
  const open = forceExpand || expanded;
  const statusClass = `chatbox-tool-card-${status}`;

  return (
    <div className={`chatbox-tool-card ${statusClass}`} data-status={status} data-testid="chatbox-tool-card">
      <button
        aria-expanded={open}
        aria-label={t("toolToggle")}
        className="chatbox-tool-card-header"
        onClick={() => setExpanded((value) => !value)}
        type="button"
      >
        {open ? <DownOutlined className="chatbox-tool-chevron" /> : <RightOutlined className="chatbox-tool-chevron" />}
        <span className="chatbox-tool-card-title">{title}</span>
        <Tag className={`chatbox-tool-status chatbox-tool-status-${status}`}>{t(`toolStatus.${status}`)}</Tag>
        {meta ? <span className="chatbox-tool-card-meta">{meta}</span> : null}
      </button>
      {open ? <div className="chatbox-tool-card-body" data-testid="chatbox-tool-body">{children}</div> : null}
    </div>
  );
}
