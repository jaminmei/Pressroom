import { beforeEach, describe, expect, it } from "vitest";

import i18n, { en, zhTW } from "./index";

function flattenLeaves(value: unknown, prefix = ""): Record<string, string> {
  if (typeof value === "string") return { [prefix]: value };
  if (!value || typeof value !== "object") return {};

  return Object.entries(value).reduce<Record<string, string>>((result, [key, child]) => ({
    ...result,
    ...flattenLeaves(child, prefix ? `${prefix}.${key}` : key)
  }), {});
}

function interpolationVariables(value: string): string[] {
  return [...value.matchAll(/{{\s*([^},\s]+)[^}]*}}/g)].map((match) => match[1]).sort();
}

describe("translation resources", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("keeps English and Traditional Chinese keys and interpolation variables identical", () => {
    const english = flattenLeaves(en);
    const chinese = flattenLeaves(zhTW);

    expect(Object.keys(chinese).sort()).toEqual(Object.keys(english).sort());
    for (const key of Object.keys(english)) {
      expect(interpolationVariables(chinese[key]), key).toEqual(interpolationVariables(english[key]));
    }
  });

  it("falls back to English when a Chinese resource is unavailable", async () => {
    i18n.addResource("en", "common", "fallbackProbe", "English fallback");
    await i18n.changeLanguage("zh-TW");
    expect(i18n.t("common:fallbackProbe")).toBe("English fallback");
  });

  it("uses English plural forms", async () => {
    await i18n.changeLanguage("en");
    expect(i18n.t("common:count", { count: 1 })).toBe("1 item");
    expect(i18n.t("common:count", { count: 2 })).toBe("2 items");
  });
});
