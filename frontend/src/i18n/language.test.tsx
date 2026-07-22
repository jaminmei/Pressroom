import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "./index";
import {
  LANGUAGE_STORAGE_KEY,
  persistLanguage,
  readStoredLanguage,
  resolveInitialLanguage
} from "./language";
import { useLanguage } from "./useLanguage";

describe("language preference", () => {
  beforeEach(async () => {
    window.localStorage.clear();
    await i18n.changeLanguage("en");
    document.documentElement.lang = "en";
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("prioritizes a valid stored preference over the browser language", () => {
    expect(resolveInitialLanguage("en", ["zh-CN", "zh-TW"])).toBe("en");
    expect(resolveInitialLanguage("zh-TW", ["en-US"])).toBe("zh-TW");
  });

  it("maps any zh browser locale to zh-TW and otherwise falls back to English", () => {
    expect(resolveInitialLanguage(null, ["zh-HK"])).toBe("zh-TW");
    expect(resolveInitialLanguage(null, ["ZH-cn"])).toBe("zh-TW");
    expect(resolveInitialLanguage(null, ["zhongwen"])).toBe("en");
    expect(resolveInitialLanguage("fr", ["en-GB"])).toBe("en");
    expect(resolveInitialLanguage("invalid", ["zh-SG"])).toBe("zh-TW");
  });

  it("tolerates unavailable localStorage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied");
    });

    expect(readStoredLanguage()).toBeNull();
    expect(() => persistLanguage("zh-TW")).not.toThrow();
  });

  it("switches immediately, persists the preference, and updates html lang", async () => {
    const { result } = renderHook(() => useLanguage());

    await act(async () => {
      await result.current.setLanguage("zh-TW");
    });

    expect(result.current.language).toBe("zh-TW");
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("zh-TW");
    expect(document.documentElement.lang).toBe("zh-TW");
  });
});
