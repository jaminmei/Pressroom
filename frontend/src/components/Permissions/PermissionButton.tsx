
import { useId } from "react";
import { Button, Tooltip, Typography } from 'antd';
import type { ButtonProps } from 'antd';
import { WorkspaceCapability } from '@/types/workspace';
import { usePermission } from '@/hooks/usePermission';

export interface PermissionButtonProps extends ButtonProps {
  capability: WorkspaceCapability;
  disabledReasonPlacement?: "tooltip" | "inline";
  disabledReason?: string;
}

export function PermissionButton({
  capability,
  disabledReasonPlacement = "tooltip",
  disabledReason,
  disabled,
  ...buttonProps
}: PermissionButtonProps) {
  const reasonId = useId();
  const { can, explain } = usePermission();
  const allowed = can(capability);
  const permissionReason = allowed
    ? undefined
    : explain(capability).reason || "You don't have permission to perform this action.";
  const reason = permissionReason ?? disabledReason;

  if (allowed && !disabled) {
    return (
      <Button {...buttonProps} />
    );
  }

  if (!reason) return <Button {...buttonProps} disabled />;

  const btn = (
    <Button
      {...buttonProps}
      aria-describedby={reasonId}
      disabled
      style={{ pointerEvents: 'none', ...buttonProps.style }}
    >
      {buttonProps.children}
    </Button>
  );

  const preventDisabledActivation = (event: React.SyntheticEvent) => {
    event.preventDefault();
    event.stopPropagation();
  };

  const preventDisabledKeyboardActivation = (event: React.KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") preventDisabledActivation(event);
  };

  const description = (
    <span
      id={reasonId}
      style={{
        border: 0,
        clip: "rect(0 0 0 0)",
        height: 1,
        margin: -1,
        overflow: "hidden",
        padding: 0,
        position: "absolute",
        whiteSpace: "nowrap",
        width: 1,
      }}
    >
      {reason}
    </span>
  );

  if (disabledReasonPlacement === "inline") {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', alignItems: 'flex-start' }}>
        <span
          aria-describedby={reasonId}
          aria-disabled="true"
          onClick={preventDisabledActivation}
          onKeyDown={preventDisabledKeyboardActivation}
          tabIndex={0}
        >
          {btn}
          {description}
        </span>
        <Typography.Text type="secondary" style={{ fontSize: '12px' }}>{reason}</Typography.Text>
      </div>
    );
  }

  return (
    <Tooltip title={reason}>
      <span
        aria-describedby={reasonId}
        aria-disabled="true"
        onClick={preventDisabledActivation}
        onKeyDown={preventDisabledKeyboardActivation}
        style={{ display: 'inline-block', cursor: 'not-allowed' }}
        tabIndex={0}
      >
        {btn}
        {description}
      </span>
    </Tooltip>
  );
}
