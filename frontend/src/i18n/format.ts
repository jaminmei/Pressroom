import type { TFunction } from "i18next";

import type { SupportedLanguage } from "./language";

export function toIntlLocale(language: SupportedLanguage): string {
  return language === "zh-TW" ? "zh-TW" : "en-US";
}

export function formatDateTime(
  value: string | number | Date,
  language: SupportedLanguage,
  options?: Intl.DateTimeFormatOptions
): string {
  return new Intl.DateTimeFormat(toIntlLocale(language), options).format(new Date(value));
}

export function formatNumber(
  value: number,
  language: SupportedLanguage,
  options?: Intl.NumberFormatOptions
): string {
  return new Intl.NumberFormat(toIntlLocale(language), options).format(value);
}

export function formatRelativeTimestamp(
  timestamp: string,
  t: TFunction
): string {
  const diffMs = Date.now() - new Date(timestamp).getTime();
  const diffMinutes = Math.floor(diffMs / 60_000);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMinutes < 1) return t("common:relativeTime.now");
  if (diffMinutes < 60) return t("common:relativeTime.minuteAgo", { count: diffMinutes });
  if (diffHours < 24) return t("common:relativeTime.hourAgo", { count: diffHours });
  return t("common:relativeTime.dayAgo", { count: diffDays });
}
