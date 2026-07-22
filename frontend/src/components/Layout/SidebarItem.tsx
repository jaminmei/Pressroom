import type { ReactNode } from "react";

export interface SidebarItemProps {
  icon: ReactNode;
  label: string;
  badge?: ReactNode;
  active: boolean;
  collapsed: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onClick: () => void;
  dataTestId: string;
}

export default function SidebarItem({
  icon,
  label,
  badge,
  active,
  collapsed,
  disabled = false,
  disabledReason,
  onClick,
  dataTestId
}: SidebarItemProps) {
  const title = disabled && disabledReason
    ? `${label}: ${disabledReason}`
    : collapsed
      ? label
      : undefined;

  return (
    <button
      aria-current={active ? "page" : undefined}
      className={`sidebar-item ${active ? "is-active" : ""} ${disabled ? "is-disabled" : ""}`.trim()}
      data-testid={dataTestId}
      disabled={disabled}
      onClick={onClick}
      title={title}
      type="button"
    >
      <span className="sidebar-item-main">
        <span aria-hidden className="sidebar-item-icon">
          {icon}
        </span>
        {!collapsed ? <span className="sidebar-item-label">{label}</span> : null}
      </span>
      {!collapsed ? badge : null}
    </button>
  );
}
