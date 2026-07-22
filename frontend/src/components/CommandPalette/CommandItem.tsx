import type { ReactNode } from "react";

interface CommandItemProps {
  label: string;
  selected: boolean;
  index: number;
  onSelect: () => void;
  shortcut?: string;
  description?: string;
  badge?: string;
  icon?: ReactNode;
  testId?: string;
}

export default function CommandItem({
  label,
  selected,
  index,
  onSelect,
  shortcut,
  description,
  badge,
  icon,
  testId
}: CommandItemProps) {
  return (
    <button
      className={`command-item ${selected ? "is-selected" : ""}`.trim()}
      data-selected={selected ? "true" : "false"}
      data-testid={testId ?? `command-item-${index}`}
      onClick={onSelect}
      type="button"
    >
      <span className="command-item-main">
        {icon ? <span className="command-item-icon">{icon}</span> : null}
        <span className="command-item-copy">
          <span className="command-item-label">{label}</span>
          {description ? <span className="command-item-description">{description}</span> : null}
        </span>
      </span>
      <span className="command-item-meta">
        {badge ? <span className="command-item-badge">{badge}</span> : null}
        {shortcut ? <span className="command-item-shortcut">{shortcut}</span> : null}
      </span>
    </button>
  );
}
