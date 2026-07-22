interface ValidationBadgeProps {
  blockingCount: number;
  warningCount: number;
  onClick: () => void;
}

export default function ValidationBadge({ blockingCount, warningCount, onClick }: ValidationBadgeProps) {
  const hasBlocking = blockingCount > 0;
  const total = hasBlocking ? blockingCount : warningCount;

  if (total === 0) {
    return null;
  }

  return (
    <button
      aria-label={hasBlocking ? `Blocking errors: ${blockingCount}` : `Warnings: ${warningCount}`}
      className={`validation-badge ${hasBlocking ? "is-blocking" : "is-warning"}`}
      data-severity={hasBlocking ? "blocking" : "warning"}
      data-testid="validation-badge"
      onClick={onClick}
      type="button"
    >
      {total}
    </button>
  );
}
