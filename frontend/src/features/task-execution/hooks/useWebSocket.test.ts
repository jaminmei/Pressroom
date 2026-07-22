import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useTaskExecutionStore } from "@/features/task-execution/store";
import { useWebSocket } from "@/features/task-execution/hooks/useWebSocket";
import { getActiveWorkspaceId, setActiveWorkspaceId } from "@/services/api";
import { useWorkspaceStore } from "@/stores/workspaceStore";

class WebSocketMock {
  static readonly urls: string[] = [];
  static readonly instances: WebSocketMock[] = [];
  static readonly OPEN = 1;

  readonly readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(url: string) {
    WebSocketMock.urls.push(url);
    WebSocketMock.instances.push(this);
  }

  close(): void {}
  send(): void {}
}

describe("useWebSocket workspace URL", () => {
  beforeEach(() => {
    WebSocketMock.urls.length = 0;
    WebSocketMock.instances.length = 0;
    vi.stubGlobal("WebSocket", WebSocketMock);
    useTaskExecutionStore.getState().reset();
    useWorkspaceStore.getState().resetWorkspaceState();
  });

  afterEach(() => {
    setActiveWorkspaceId(null);
    vi.unstubAllGlobals();
  });

  it("includes the active workspace ID", () => {
    // Given
    setActiveWorkspaceId("ws_active");

    // When
    renderHook(() => useWebSocket({ taskId: "task_1" }));

    // Then
    expect(getActiveWorkspaceId()).toBe("ws_active");
    expect(new URL(WebSocketMock.urls[0]).searchParams.get("workspace_id")).toBe("ws_active");
  });

  it("omits the workspace ID when none is active", () => {
    // Given
    setActiveWorkspaceId(null);

    // When
    renderHook(() => useWebSocket({ taskId: "task_1" }));

    // Then
    expect(new URL(WebSocketMock.urls[0]).searchParams.has("workspace_id")).toBe(false);
  });

  it("rejects a connected message for a different task", () => {
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "ws_active",
        name: "Active",
        isDefault: false,
        role: "admin",
        capabilities: [],
      },
      contextGeneration: 7,
    });
    setActiveWorkspaceId("ws_active");
    useTaskExecutionStore.setState({ currentTaskId: "task_1", taskStatus: "running" });
    renderHook(() => useWebSocket({ taskId: "task_1" }));

    act(() => {
      WebSocketMock.instances[0].onmessage?.({
        data: JSON.stringify({ type: "connected", data: { task_id: "task_other" } }),
      } as MessageEvent);
    });

    expect(useTaskExecutionStore.getState().currentTaskId).toBe("task_1");
    expect(useTaskExecutionStore.getState().wsConnected).toBe(false);
    const eventLogs = useTaskExecutionStore.getState().eventLogs;
    expect(eventLogs[eventLogs.length - 1]?.message).toContain("task mismatch");
  });

  it("ignores a late event from a previous workspace generation", () => {
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "ws-a",
        name: "A",
        isDefault: false,
        role: "admin",
        capabilities: [],
      },
      contextGeneration: 30,
    });
    setActiveWorkspaceId("ws-a");
    useTaskExecutionStore.setState({ currentTaskId: "task_1", taskStatus: "running" });
    renderHook(() => useWebSocket({ taskId: "task_1" }));
    const lateHandler = WebSocketMock.instances[0].onmessage;

    act(() => {
      useTaskExecutionStore.getState().reset();
      useWorkspaceStore.setState({
        currentWorkspace: {
          id: "ws-b",
          name: "B",
          isDefault: false,
          role: "admin",
          capabilities: [],
        },
        contextGeneration: 31,
      });
      lateHandler?.({
        data: JSON.stringify({ type: "workflow_state", data: { status: "completed" } }),
      } as MessageEvent);
    });

    expect(useTaskExecutionStore.getState()).toMatchObject({
      currentTaskId: null,
      taskStatus: "idle",
      eventLogs: [],
    });
  });
});
