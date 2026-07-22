import { beforeEach, describe, expect, it } from "vitest";

import { useTaskExecutionStore } from "@/features/task-execution/store";

describe("useTaskExecutionStore", () => {
  beforeEach(() => {
    useTaskExecutionStore.getState().reset();
  });

  it("updates task execution, reconnect, and block selection state", () => {
    const store = useTaskExecutionStore.getState();
    store.setTaskId("task_1");
    store.setTaskStatus("running");
    store.updateNodeStatus("engine_1", "running");
    store.batchUpdateNodeStatuses({
      engine_2: "pending"
    });
    store.setNodeProgress("engine_1", 45);
    store.setWsWarning("連線中斷，重連中...");
    store.setManualReconnectAvailable(true);
    store.appendEventLog("SSE connected");
    store.setBlockSelectionRequest({
      node_id: "block_selector_1",
      node_type: "processor/block_selector",
      input_type: "block_selection",
      payload: {
        source_image: {
          image_id: "img_001",
          page_number: 1,
          width: 1280,
          height: 720,
          preview_url: "/preview"
        },
        blocks: []
      }
    });

    const state = useTaskExecutionStore.getState();
    expect(state.currentTaskId).toBe("task_1");
    expect(state.taskStatus).toBe("running");
    expect(state.executionStartedAt).not.toBeNull();
    expect(state.nodeStatuses.engine_1).toBe("running");
    expect(state.nodeStatuses.engine_2).toBe("pending");
    expect(state.nodeProgress.engine_1).toBe(45);
    expect(state.wsWarning).toContain("重連中");
    expect(state.manualReconnectAvailable).toBe(true);
    expect(state.eventLogs).toHaveLength(1);
    expect(state.eventLogs[0]?.message).toBe("SSE connected");
    expect(state.blockSelectionRequest?.node_id).toBe("block_selector_1");
  });

  it("resets to initial state", () => {
    const store = useTaskExecutionStore.getState();
    store.setTaskId("task_1");
    store.setTaskStatus("running");
    store.updateNodeStatus("engine_1", "failed", "boom");
    store.setWsConnected(true);
    store.setWsWarning("warning");
    store.setManualReconnectAvailable(true);
    store.reset();

    const state = useTaskExecutionStore.getState();
    expect(state.currentTaskId).toBeNull();
    expect(state.taskStatus).toBe("idle");
    expect(state.executionStartedAt).toBeNull();
    expect(state.nodeStatuses).toEqual({});
    expect(state.nodeProgress).toEqual({});
    expect(state.nodeErrors).toEqual({});
    expect(state.eventLogs).toEqual([]);
    expect(state.wsConnected).toBe(false);
    expect(state.wsWarning).toBeNull();
    expect(state.manualReconnectAvailable).toBe(false);
    expect(state.blockSelectionRequest).toBeNull();
  });
});
