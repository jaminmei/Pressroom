import { useMemo } from "react";
import { create } from "zustand";

const EXPERIMENTAL_CHATBOX_STORAGE_PREFIX = "dc.experimental-chatbox.enabled";

export function experimentalChatboxStorageKey(userId: string): string {
  return `${EXPERIMENTAL_CHATBOX_STORAGE_PREFIX}:${userId}`;
}

export function readExperimentalChatboxEnabled(userId: string): boolean {
  try {
    return window.localStorage.getItem(experimentalChatboxStorageKey(userId)) === "true";
  } catch {
    return false;
  }
}

interface ChatboxPreferenceState {
  readonly enabledByUser: Readonly<Record<string, boolean>>;
  readonly setEnabled: (userId: string, enabled: boolean) => void;
}

export const useChatboxPreferenceStore = create<ChatboxPreferenceState>((set) => ({
  enabledByUser: {},
  setEnabled: (userId, enabled) => {
    try {
      window.localStorage.setItem(experimentalChatboxStorageKey(userId), String(enabled));
    } catch {
      // Browser storage is optional; the in-memory preference still changes.
    }
    set((state) => ({
      enabledByUser: { ...state.enabledByUser, [userId]: enabled },
    }));
  },
}));

export function useExperimentalChatboxEnabled(userId: string | null): boolean {
  const storedEnabled = useMemo(
    () => userId !== null && readExperimentalChatboxEnabled(userId),
    [userId],
  );
  return useChatboxPreferenceStore((state) => {
    if (userId === null) return false;
    return state.enabledByUser[userId] ?? storedEnabled;
  });
}
