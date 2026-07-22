import { create } from "zustand";

export type RightPanelTab = "config" | "result" | "run" | "compare" | "history";

export interface UIState {
  selectedNodeId: string | null;
  rightPanelTab: RightPanelTab;
  nodePanelVisible: boolean;
  sidebarCollapsed: boolean;
  commandPaletteOpen: boolean;
  recentRunsDrawerOpen: boolean;
  engineStatuses: Record<string, string>;
  lastWorkflowsRoute: string;
  lastProjectsRoute: string;
  lastDatabaseRoute: string;
  selectNode: (nodeId: string | null) => void;
  setRightPanelTab: (tab: RightPanelTab) => void;
  openNodePanel: () => void;
  closeNodePanel: () => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setCommandPaletteOpen: (open: boolean) => void;
  setRecentRunsDrawerOpen: (open: boolean) => void;
  setEngineStatuses: (statuses: Record<string, string>) => void;
  setLastWorkflowsRoute: (route: string) => void;
  setLastProjectsRoute: (route: string) => void;
  setLastDatabaseRoute: (route: string) => void;
}

export const initialUIState: Pick<
  UIState,
  | "selectedNodeId"
  | "rightPanelTab"
  | "nodePanelVisible"
  | "sidebarCollapsed"
  | "commandPaletteOpen"
  | "recentRunsDrawerOpen"
  | "engineStatuses"
  | "lastWorkflowsRoute"
  | "lastProjectsRoute"
  | "lastDatabaseRoute"
> = {
  selectedNodeId: null,
  rightPanelTab: "config",
  nodePanelVisible: false,
  sidebarCollapsed: false,
  commandPaletteOpen: false,
  recentRunsDrawerOpen: false,
  engineStatuses: {},
  lastWorkflowsRoute: "/",
  lastProjectsRoute: "/projects",
  lastDatabaseRoute: "/database"
};

export const useUIStore = create<UIState>((set) => ({
  ...initialUIState,
  selectNode: (nodeId) =>
    set({
      selectedNodeId: nodeId,
      nodePanelVisible: nodeId !== null
    }),
  setRightPanelTab: (tab) => set({ rightPanelTab: tab }),
  openNodePanel: () => set({ nodePanelVisible: true }),
  closeNodePanel: () => set({ nodePanelVisible: false }),
  toggleSidebar: () =>
    set((state) => ({
      sidebarCollapsed: !state.sidebarCollapsed
    })),
  setSidebarCollapsed: (collapsed) =>
    set({
      sidebarCollapsed: collapsed
    }),
  setCommandPaletteOpen: (open) =>
    set({
      commandPaletteOpen: open
    }),
  setRecentRunsDrawerOpen: (open) =>
    set({
      recentRunsDrawerOpen: open
    }),
  setEngineStatuses: (statuses) =>
    set({
      engineStatuses: statuses
    }),
  setLastWorkflowsRoute: (route) => set({ lastWorkflowsRoute: route }),
  setLastProjectsRoute: (route) => set({ lastProjectsRoute: route }),
  setLastDatabaseRoute: (route) => set({ lastDatabaseRoute: route })
}));
