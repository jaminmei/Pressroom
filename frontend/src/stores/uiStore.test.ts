import { beforeEach, describe, expect, it } from "vitest";

import { initialUIState, useUIStore } from "@/stores/uiStore";

describe("uiStore", () => {
  beforeEach(() => {
    useUIStore.setState(initialUIState);
  });

  it("starts with default ui state", () => {
    const state = useUIStore.getState();
    expect(state.selectedNodeId).toBeNull();
    expect(state.rightPanelTab).toBe("config");
    expect(state.sidebarCollapsed).toBe(false);
    expect(state.commandPaletteOpen).toBe(false);
    expect(state.recentRunsDrawerOpen).toBe(false);
    expect(state.engineStatuses).toEqual({});
  });

  it("updates selected node and right panel tab", () => {
    useUIStore.getState().selectNode("node_1");
    useUIStore.getState().setRightPanelTab("run");

    const state = useUIStore.getState();
    expect(state.selectedNodeId).toBe("node_1");
    expect(state.rightPanelTab).toBe("run");
  });

  it("updates global workspace controls and engine statuses", () => {
    useUIStore.getState().toggleSidebar();
    useUIStore.getState().setCommandPaletteOpen(true);
    useUIStore.getState().setRecentRunsDrawerOpen(true);
    useUIStore.getState().setEngineStatuses({ ocr: "healthy" });

    const state = useUIStore.getState();
    expect(state.sidebarCollapsed).toBe(true);
    expect(state.commandPaletteOpen).toBe(true);
    expect(state.recentRunsDrawerOpen).toBe(true);
    expect(state.engineStatuses).toEqual({ ocr: "healthy" });
  });
});
