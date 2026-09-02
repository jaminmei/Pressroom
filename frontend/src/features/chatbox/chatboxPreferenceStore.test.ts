import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  experimentalChatboxStorageKey,
  readExperimentalChatboxEnabled,
  useExperimentalChatboxEnabled,
  useChatboxPreferenceStore,
} from "@/features/chatbox/chatboxPreferenceStore";

describe("experimental Chatbox preference", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useChatboxPreferenceStore.setState({ enabledByUser: {} });
  });

  it("defaults off and persists independently for each user", () => {
    expect(readExperimentalChatboxEnabled("user-a")).toBe(false);

    useChatboxPreferenceStore.getState().setEnabled("user-a", true);

    expect(readExperimentalChatboxEnabled("user-a")).toBe(true);
    expect(readExperimentalChatboxEnabled("user-b")).toBe(false);
    expect(window.localStorage.getItem(experimentalChatboxStorageKey("user-a"))).toBe("true");
  });

  it("hydrates storage once and then reacts to in-memory preference changes", () => {
    window.localStorage.setItem(experimentalChatboxStorageKey("user-a"), "true");
    const { result } = renderHook(() => useExperimentalChatboxEnabled("user-a"));
    expect(result.current).toBe(true);

    act(() => useChatboxPreferenceStore.getState().setEnabled("user-a", false));
    expect(result.current).toBe(false);
  });
});
