import { create } from "zustand";

import type { TaskResult } from "@/types/task";

export type ResultViewMode = "rendered" | "raw";

export interface ResultState {
  taskId: string | null;
  results: TaskResult[];
  displayMode: ResultViewMode;
  setTaskResults: (taskId: string, results: TaskResult[]) => void;
  setDisplayMode: (mode: ResultViewMode) => void;
  clearResults: () => void;
  reset: () => void;
}

export const initialResultState: Pick<ResultState, "taskId" | "results" | "displayMode"> = {
  taskId: null,
  results: [],
  displayMode: "rendered"
};

export const useResultStore = create<ResultState>((set) => ({
  ...initialResultState,
  setTaskResults: (taskId, results) => {
    set({ taskId, results });
  },
  setDisplayMode: (mode) => {
    set({ displayMode: mode });
  },
  clearResults: () => {
    set({ ...initialResultState });
  },
  reset: () => {
    set({ ...initialResultState });
  }
}));
