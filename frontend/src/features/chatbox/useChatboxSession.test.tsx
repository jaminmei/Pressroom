import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useChatboxSession } from "@/features/chatbox/useChatboxSession";
import { setActiveWorkspaceId } from "@/services/api";
import type { ChatboxSession } from "@/services/chatboxApi";

const getChatboxSession = vi.fn();

vi.mock("@/services/chatboxApi", async () => {
  const actual = await vi.importActual<typeof import("@/services/chatboxApi")>("@/services/chatboxApi");
  return { ...actual, getChatboxSession: (...args: readonly unknown[]) => getChatboxSession(...args) };
});

class WebSocketMock {
  static readonly instances: WebSocketMock[] = [];
  static readonly OPEN = 1;
  readonly url: string;
  readyState = WebSocketMock.OPEN;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  sent: string[] = [];
  constructor(url: string) { this.url = url; WebSocketMock.instances.push(this); }
  close(): void {}
  send(message: string): void { this.sent.push(message); }
}

function markRuntimeReady(socket: WebSocketMock | undefined): void {
  socket?.onopen?.();
  socket?.onmessage?.({
    data: JSON.stringify({
      type: "runtime_status",
      status: "ready",
      runtime_generation: 1,
    }),
  } as MessageEvent);
}

describe("useChatboxSession", () => {
  beforeEach(() => {
    WebSocketMock.instances.length = 0;
    getChatboxSession.mockClear();
    getChatboxSession.mockResolvedValue({ session_id: "session-1", state: "idle", provider_id: "provider-1", model_id: "model-1", messages: [] });
    setActiveWorkspaceId("workspace-1");
    vi.stubGlobal("WebSocket", WebSocketMock);
  });
  afterEach(() => { setActiveWorkspaceId(null); vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("connects to the api-prefixed backend chatbox route with workspace scope", async () => {
    const { result } = renderHook(() => useChatboxSession({ sessionId: "session-1", enabled: true }));
    await act(async () => { await Promise.resolve(); });
    const url = new URL(WebSocketMock.instances[0]?.url ?? "");
    expect(url.pathname).toBe("/api/chatbox/sessions/session-1");
    expect(url.searchParams.get("workspace_id")).toBe("workspace-1");
    expect(url.searchParams.get("after_revision")).toBe("0");
    act(() => WebSocketMock.instances[0]?.onopen?.());
    expect(result.current.runtimeStatus).toBe("restoring-runtime");
    expect(result.current.connected).toBe(false);
    act(() => markRuntimeReady(WebSocketMock.instances[0]));
    expect(result.current.runtimeStatus).toBe("ready");
    expect(result.current.connected).toBe(true);
  });

  it("sends Pi prompt commands with a correlation identifier", async () => {
    const { result } = renderHook(() => useChatboxSession({ sessionId: "session-1", enabled: true }));
    await act(async () => { await Promise.resolve(); });
    expect(WebSocketMock.instances).toHaveLength(1);
    let sent = false;
    act(() => { sent = result.current.send("Hello"); });
    expect(sent).toBe(false);
    act(() => markRuntimeReady(WebSocketMock.instances[0]));
    act(() => { sent = result.current.send("Hello"); });
    expect(sent).toBe(true);
    expect(JSON.parse(WebSocketMock.instances[0]?.sent[0] ?? "{}")).toMatchObject({
      type: "prompt",
      id: expect.stringMatching(/^prompt-/),
      message: "Hello",
    });
  });

  it("returns false instead of dropping a prompt while the socket is unavailable", () => {
    getChatboxSession.mockReturnValue(new Promise(() => undefined));
    const { result } = renderHook(() => useChatboxSession({ sessionId: "session-1", enabled: true }));

    expect(result.current.send("Keep this prompt")).toBe(false);
    expect(WebSocketMock.instances).toHaveLength(0);
  });

  it("renders an optimistic snapshot without connecting until activation is enabled", async () => {
    const initialSession: ChatboxSession = {
      session_id: "session-1",
      state: "idle",
      provider_id: "provider-1",
      model_id: "model-1",
      messages: [{
        id: "history-1",
        role: "assistant",
        content: [{ type: "text", text: "Saved history" }],
      }],
      tool_executions: {},
      compaction_notes: [],
      live_message_id: null,
      snapshot_revision: 1,
      session_state: "paused",
      runtime_state: "stopped",
      runtime_generation: 1,
      title: "Saved session",
      preview: "Saved history",
      first_settled_at: "2026-08-27T00:00:00Z",
      last_activity_at: "2026-08-27T00:00:00Z",
      archived_at: null,
      is_current: false,
    };
    const { result, rerender } = renderHook(
      ({ enabled }) => useChatboxSession({ sessionId: "session-1", enabled, initialSession }),
      { initialProps: { enabled: false } },
    );

    expect(result.current.messages[0]?.content[0]).toEqual({ type: "text", text: "Saved history" });
    expect(result.current.runtimeStatus).toBe("restoring-runtime");
    expect(getChatboxSession).not.toHaveBeenCalled();
    expect(WebSocketMock.instances).toHaveLength(0);

    rerender({ enabled: true });
    await act(async () => { await Promise.resolve(); });

    expect(getChatboxSession).toHaveBeenCalledTimes(1);
    expect(WebSocketMock.instances).toHaveLength(1);
  });

  it("renders native Pi messages and exposes the working lifecycle", async () => {
    const { result } = renderHook(() => useChatboxSession({ sessionId: "session-1", enabled: true }));
    await act(async () => { await Promise.resolve(); });
    const socket = WebSocketMock.instances[0];

    act(() => {
      socket?.onmessage?.({ data: JSON.stringify({ type: "agent_start" }) } as MessageEvent);
      socket?.onmessage?.({
        data: JSON.stringify({
          type: "message_start",
          message: { role: "user", content: "Hi", timestamp: 1 },
        }),
      } as MessageEvent);
      socket?.onmessage?.({
        data: JSON.stringify({
          type: "message_end",
          message: { role: "user", content: "Hi", timestamp: 1 },
        }),
      } as MessageEvent);
    });

    expect(result.current.runningState).toBe("working");
    expect(result.current.messages[0]).toMatchObject({
      role: "user",
      content: [{ type: "text", text: "Hi" }],
    });

    act(() => {
      socket?.onmessage?.({
        data: JSON.stringify({
          type: "message_start",
          message: { role: "assistant", content: [], timestamp: 2 },
        }),
      } as MessageEvent);
      socket?.onmessage?.({
        data: JSON.stringify({
          type: "message_end",
          message: {
            role: "assistant",
            content: [{ type: "text", text: "Hello!" }],
            timestamp: 3,
          },
        }),
      } as MessageEvent);
      socket?.onmessage?.({ data: JSON.stringify({ type: "agent_settled" }) } as MessageEvent);
    });

    expect(result.current.runningState).toBe("idle");
    expect(result.current.messages[1]).toMatchObject({
      role: "assistant",
      content: [{ type: "text", text: "Hello!" }],
    });
  });

  it("reloads authoritative state before opening a replacement socket", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useChatboxSession({ sessionId: "session-1", enabled: true }));
    await act(async () => { await Promise.resolve(); });
    act(() => WebSocketMock.instances[0]?.onclose?.({ code: 1006 } as CloseEvent));
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(getChatboxSession).toHaveBeenCalledTimes(2);
    expect(WebSocketMock.instances).toHaveLength(2);
    expect(result.current.runningState).toBe("idle");
    vi.useRealTimers();
  });

  it("asks for Refresh when the server normally closes a live session", async () => {
    const { result } = renderHook(() => useChatboxSession({
      sessionId: "session-1",
      enabled: true,
    }));
    await act(async () => { await Promise.resolve(); });

    act(() => WebSocketMock.instances[0]?.onclose?.({ code: 1000 } as CloseEvent));

    expect(result.current.connected).toBe(false);
    expect(result.current.requiresRefresh).toBe(true);
    expect(WebSocketMock.instances).toHaveLength(1);
  });

  it("leaves policy closes to the auth and workspace owner", async () => {
    const { result } = renderHook(() => useChatboxSession({
      sessionId: "session-1",
      enabled: true,
    }));
    await act(async () => { await Promise.resolve(); });

    act(() => WebSocketMock.instances[0]?.onclose?.({ code: 1008 } as CloseEvent));

    expect(result.current.connected).toBe(false);
    expect(result.current.requiresRefresh).toBe(false);
    expect(result.current.accessUnavailable).toBe(true);
    expect(WebSocketMock.instances).toHaveLength(1);
  });

  it("maps an active durable lifecycle to the working UI state", async () => {
    getChatboxSession.mockResolvedValue({
      session_id: "session-1",
      state: "active",
      provider_id: "provider-1",
      model_id: "model-1",
      messages: [],
    });

    const { result } = renderHook(() => useChatboxSession({
      sessionId: "session-1",
      enabled: true,
    }));
    await act(async () => { await Promise.resolve(); });

    expect(result.current.runningState).toBe("working");
  });

  it("stops reconnecting and asks for Refresh when the durable session is dead", async () => {
    vi.useFakeTimers();
    getChatboxSession.mockResolvedValue({
      session_id: "session-1",
      state: "dead",
      provider_id: "provider-1",
      model_id: "model-1",
      messages: [],
    });

    const { result } = renderHook(() => useChatboxSession({
      sessionId: "session-1",
      enabled: true,
    }));
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await vi.runAllTimersAsync(); });

    expect(result.current.requiresRefresh).toBe(true);
    expect(result.current.connected).toBe(false);
    expect(getChatboxSession).toHaveBeenCalledTimes(1);
    expect(WebSocketMock.instances).toHaveLength(0);
  });

  it("restores messages, tool progress, and the live message from the server snapshot", async () => {
    getChatboxSession.mockResolvedValue({
      session_id: "session-1",
      state: "active",
      provider_id: "provider-1",
      model_id: "model-1",
      messages: [{
        id: "server-message-1",
        role: "assistant",
        content: [{ type: "text", text: "partial" }],
      }],
      tool_executions: {
        "tool-1": { toolCallId: "tool-1", toolName: "read", args: { path: "README.md" } },
      },
      compaction_notes: [{
        id: "compaction-1",
        kind: "compaction",
        summary: "Earlier work",
        aborted: false,
      }],
      live_message_id: "server-message-1",
    });

    const { result } = renderHook(() => useChatboxSession({
      sessionId: "session-1",
      enabled: true,
    }));
    await act(async () => { await Promise.resolve(); });

    expect(result.current.messages[0]?.content[0]).toEqual({ type: "text", text: "partial" });
    expect(result.current.toolExecutions["tool-1"]?.toolName).toBe("read");
    expect(result.current.compactionNotes[0]?.summary).toBe("Earlier work");

    act(() => {
      WebSocketMock.instances[0]?.onmessage?.({
        data: JSON.stringify({
          type: "message_update",
          assistantMessageEvent: { type: "text_delta", contentIndex: 0, delta: " response" },
        }),
      } as MessageEvent);
    });
    expect(result.current.messages[0]?.content[0]).toEqual({
      type: "text",
      text: "partial response",
    });
  });

  it("keeps retrying snapshot failures until the session becomes available", async () => {
    vi.useFakeTimers();
    getChatboxSession
      .mockRejectedValueOnce(new Error("first failure"))
      .mockRejectedValueOnce(new Error("second failure"))
      .mockResolvedValue({ session_id: "session-1", state: "idle", provider_id: "provider-1", model_id: "model-1", messages: [] });

    renderHook(() => useChatboxSession({ sessionId: "session-1", enabled: true }));
    await act(async () => { await Promise.resolve(); });
    expect(getChatboxSession).toHaveBeenCalledTimes(1);

    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(getChatboxSession).toHaveBeenCalledTimes(2);
    expect(WebSocketMock.instances).toHaveLength(0);

    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(getChatboxSession).toHaveBeenCalledTimes(3);
    expect(WebSocketMock.instances).toHaveLength(1);
    vi.useRealTimers();
  });

  it("stops reconnecting after a bounded number of snapshot failures", async () => {
    vi.useFakeTimers();
    getChatboxSession.mockRejectedValue(new Error("unavailable"));

    renderHook(() => useChatboxSession({ sessionId: "session-1", enabled: true }));
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await vi.runAllTimersAsync(); });

    expect(getChatboxSession).toHaveBeenCalledTimes(6);
    expect(WebSocketMock.instances).toHaveLength(0);
  });

  it("renews the reconnect budget after a socket remains stable", async () => {
    vi.useFakeTimers();
    renderHook(() => useChatboxSession({ sessionId: "session-1", enabled: true }));
    await act(async () => { await Promise.resolve(); });

    const delays = [1000, 2000, 5000, 5000, 5000];
    for (const [index, delay] of delays.entries()) {
      act(() => WebSocketMock.instances[index]?.onclose?.({ code: 1006 } as CloseEvent));
      await act(async () => { await vi.advanceTimersByTimeAsync(delay); });
    }
    expect(WebSocketMock.instances).toHaveLength(6);

    act(() => WebSocketMock.instances[5]?.onopen?.());
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    act(() => WebSocketMock.instances[5]?.onclose?.({ code: 1006 } as CloseEvent));
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });

    expect(WebSocketMock.instances).toHaveLength(7);
  });
});
