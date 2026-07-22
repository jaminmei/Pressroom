/**
 * Format a timestamp as a human-readable relative time string.
 *
 * Examples: "just now", "3m ago", "2h ago", "1d ago"
 */
export function formatRelativeTime(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMinutes = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMinutes < 1) return i18n.t("common:relativeTime.now");
  if (diffMinutes < 60) return i18n.t("common:relativeTime.minuteAgo", { count: diffMinutes });
  if (diffHours < 24) return i18n.t("common:relativeTime.hourAgo", { count: diffHours });
  return i18n.t("common:relativeTime.dayAgo", { count: diffDays });
}
import i18n from "@/i18n";
