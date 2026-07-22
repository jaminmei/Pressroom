import { describe, expect, it } from "vitest";

import i18n from "./index";
import { formatDateTime, formatNumber, formatRelativeTimestamp } from "./format";

describe("localized formatting", () => {
  it("formats dates and numbers with the active locale", () => {
    const date = "2026-07-21T00:00:00.000Z";
    expect(formatDateTime(date, "en", { timeZone: "UTC", year: "numeric", month: "short", day: "numeric" })).toContain("Jul");
    expect(formatDateTime(date, "zh-TW", { timeZone: "UTC", year: "numeric", month: "short", day: "numeric" })).toContain("7月");
    expect(formatNumber(1234.5, "en")).toBe("1,234.5");
  });

  it("formats relative time through translated plural-aware messages", async () => {
    await i18n.changeLanguage("en");
    const timestamp = new Date(Date.now() - 2 * 60_000).toISOString();
    expect(formatRelativeTimestamp(timestamp, i18n.t.bind(i18n))).toBe("2m ago");
  });
});
