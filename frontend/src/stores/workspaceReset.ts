import { useResultStore } from "@/features/result/store";
import { useProjectsDomainStore } from "@/features/projects/store";
import { useLiveStatusStore } from "@/features/task-execution/liveStatusStore";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";
import { initialUIState, useUIStore } from "@/stores/uiStore";

export function resetWorkspaceScopedState(): void {
  useWorkflowStore.getState().clearCanvas();
  useWorkflowPersistenceStore.getState().reset();
  useTaskExecutionStore.getState().reset();
  useLiveStatusStore.setState({ updates: {} });
  useResultStore.getState().reset();
  useProjectsDomainStore.getState().setActiveProjectId(null);
  useUIStore.setState({
    selectedNodeId: initialUIState.selectedNodeId,
    rightPanelTab: initialUIState.rightPanelTab,
    nodePanelVisible: initialUIState.nodePanelVisible,
    commandPaletteOpen: initialUIState.commandPaletteOpen,
    recentRunsDrawerOpen: initialUIState.recentRunsDrawerOpen,
    engineStatuses: initialUIState.engineStatuses,
    lastWorkflowsRoute: initialUIState.lastWorkflowsRoute,
    lastProjectsRoute: initialUIState.lastProjectsRoute,
    lastDatabaseRoute: initialUIState.lastDatabaseRoute
  });
}
