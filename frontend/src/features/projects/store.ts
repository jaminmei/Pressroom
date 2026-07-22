import { create } from "zustand";

export interface ProjectsDomainState {
  activeProjectId: string | null;
  setActiveProjectId: (id: string | null) => void;
}

export const useProjectsDomainStore = create<ProjectsDomainState>((set) => ({
  activeProjectId: null,
  setActiveProjectId: (id) => set({ activeProjectId: id })
}));
