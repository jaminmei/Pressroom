import { create } from "zustand";

import type { TaskStatus } from "@/types/task";

/**
 * Lightweight store for live task status updates received via WebSocket.
 *
 * `useWebSocket` publishes terminal statuses here (completed / failed / cancelled).
 * HistoryPanel and RecentRunsDrawer subscribe to patch their list items in-place
 * without needing a full re-fetch.
 */

interface LiveStatusState {
  updates: Record<string, TaskStatus>;
  patchStatus: (taskId: string, status: TaskStatus) => void;
  consumeStatus: (taskId: string) => TaskStatus | undefined;
}

export const useLiveStatusStore = create<LiveStatusState>((set, get) => ({
  updates: {},

  patchStatus: (taskId, status) => {
    set((state) => ({
      updates: { ...state.updates, [taskId]: status },
    }));
  },

  /** Read and clear the status for a given task (one-shot consumption). */
  consumeStatus: (taskId) => {
    const status = get().updates[taskId];
    if (status !== undefined) {
      set((state) => {
        const next = { ...state.updates };
        delete next[taskId];
        return { updates: next };
      });
    }
    return status;
  },
}));
