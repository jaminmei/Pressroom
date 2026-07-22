import { beforeEach, describe, expect, it } from "vitest";

import { useLiveStatusStore } from "@/features/task-execution/liveStatusStore";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import { useProjectsDomainStore } from "@/features/projects/store";
import { useResultStore } from "@/features/result/store";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";
import { initialUIState, useUIStore } from "@/stores/uiStore";
import { resetWorkspaceScopedState } from "@/stores/workspaceReset";

describe("resetWorkspaceScopedState", () => {
  beforeEach(() => {
    useWorkflowStore.getState().clearCanvas();
    useWorkflowPersistenceStore.getState().reset();
    useTaskExecutionStore.getState().reset();
    useResultStore.getState().reset();
    useLiveStatusStore.setState({ updates: {} });
    useProjectsDomainStore.setState({ activeProjectId: null });
    useUIStore.setState(initialUIState);
  });

  it("clears every workspace-scoped store after a successful switch", () => {
    useWorkflowStore.setState({ selectedNodeId: "node-1", nodeConfigs: { "node-1": { value: 1 } } });
    useWorkflowPersistenceStore.getState().setWorkflowMeta({ workflowId: "workflow-1" });
    useTaskExecutionStore.getState().setTaskId("task-1");
    useResultStore.getState().setTaskResults("task-1", []);
    useLiveStatusStore.setState({ updates: { "task-1": "running" } });
    useProjectsDomainStore.setState({ activeProjectId: "project-1" });
    useUIStore.setState({
      selectedNodeId: "node-1",
      nodePanelVisible: true,
      rightPanelTab: "result",
      commandPaletteOpen: true,
      recentRunsDrawerOpen: true,
      engineStatuses: { ocr: "healthy" },
      lastWorkflowsRoute: "/workflows/1",
      lastProjectsRoute: "/projects/1",
      lastDatabaseRoute: "/database/1"
    });

    resetWorkspaceScopedState();

    expect(useWorkflowStore.getState()).toMatchObject({ nodes: [], edges: [], nodeConfigs: {}, selectedNodeId: null });
    expect(useWorkflowPersistenceStore.getState().workflowId).toBeNull();
    expect(useTaskExecutionStore.getState().currentTaskId).toBeNull();
    expect(useResultStore.getState().taskId).toBeNull();
    expect(useLiveStatusStore.getState().updates).toEqual({});
    expect(useProjectsDomainStore.getState().activeProjectId).toBeNull();
    expect(useUIStore.getState()).toMatchObject(initialUIState);
  });
});
