import { describe, expect, it } from "vitest";

import {
  assemblePiEvent,
  initialPiAssemblerState,
  parsePiEvent,
  resetPiAssembler,
} from "@/features/chatbox/piEventAssembler";

const assistant = { id: "assistant-1", role: "assistant", content: [] };

describe("Pi event assembler", () => {
  it("creates a live message and appends a delta at its content index", () => {
    const started = assemblePiEvent(initialPiAssemblerState, { type: "message_start", message: assistant });
    const updated = assemblePiEvent(started, { type: "message_update", assistantMessageEvent: { type: "text_delta", contentIndex: 1, delta: "hello" } });
    expect(updated.messages[0]?.content[1]).toEqual({ type: "text", text: "hello" });
  });

  it("preserves block order while appending thinking and tool-call argument deltas", () => {
    const started = assemblePiEvent(initialPiAssemblerState, { type: "message_start", message: assistant });
    const thinking = assemblePiEvent(started, { type: "message_update", assistantMessageEvent: { type: "thinking_delta", contentIndex: 0, delta: "consider" } });
    const tool = assemblePiEvent(thinking, { type: "message_update", assistantMessageEvent: { type: "toolcall_delta", contentIndex: 2, delta: "{\"path\":\"a\"}" } });
    expect(tool.messages[0]?.content).toEqual([
      { type: "thinking", thinking: "consider" },
      { type: "placeholder" },
      { type: "toolCall", toolCallId: "", toolName: "", input: "{\"path\":\"a\"}" }
    ]);
  });

  it("preserves structured tool input and removes sparse placeholders at message end", () => {
    const started = assemblePiEvent(initialPiAssemblerState, {
      type: "message_start",
      message: {
        ...assistant,
        content: [{
          type: "toolCall",
          toolCallId: "tool-1",
          toolName: "read",
          input: { path: "existing.ts" },
        }],
      },
    });
    const updated = assemblePiEvent(started, {
      type: "message_update",
      assistantMessageEvent: { type: "toolcall_delta", contentIndex: 2, delta: "ignored" },
    });
    const preserved = assemblePiEvent(updated, {
      type: "message_update",
      assistantMessageEvent: { type: "toolcall_delta", contentIndex: 0, delta: "ignored" },
    });
    const ended = assemblePiEvent(preserved, {
      type: "message_end",
      message: { ...assistant, content: [] },
    });

    expect(preserved.messages[0]?.content[0]).toMatchObject({
      input: { path: "existing.ts" },
    });
    expect(ended.messages[0]?.content).toEqual([
      {
        type: "toolCall",
        toolCallId: "tool-1",
        toolName: "read",
        input: { path: "existing.ts" },
      },
      { type: "toolCall", toolCallId: "", toolName: "", input: "ignored" },
    ]);
  });

  it("normalizes the SDK tool-call block shape used by final Pi messages", () => {
    const state = assemblePiEvent(initialPiAssemblerState, {
      type: "message_start",
      message: {
        role: "assistant",
        content: [{
          type: "toolCall",
          id: "sdk-tool-1",
          name: "read",
          arguments: { path: "src/main.ts" },
        }],
      },
    });

    expect(state.messages[0]?.content[0]).toMatchObject({
      type: "toolCall",
      toolCallId: "sdk-tool-1",
      toolName: "read",
      input: { path: "src/main.ts" },
    });
  });

  it("replaces the local message when an authoritative message ends", () => {
    const started = assemblePiEvent(initialPiAssemblerState, { type: "message_start", message: assistant });
    const ended = assemblePiEvent(started, { type: "message_end", message: { ...assistant, content: [{ type: "text", text: "final" }] } });
    expect(ended.messages[0]?.content).toEqual([{ type: "text", text: "final" }]);
  });

  it("appends an authoritative terminal message when reconnect missed its start", () => {
    const ended = assemblePiEvent(initialPiAssemblerState, {
      type: "message_end",
      message: {
        id: "server-message-1",
        role: "assistant",
        content: [{ type: "text", text: "recovered" }],
      },
    });

    expect(ended.messages).toEqual([{
      id: "server-message-1",
      role: "assistant",
      content: [{ type: "text", text: "recovered" }],
    }]);
  });

  it("assigns an id when a terminal message arrives without a matching start", () => {
    const ended = assemblePiEvent(initialPiAssemblerState, {
      type: "message_end",
      message: {
        role: "assistant",
        content: [{ type: "text", text: "recovered without an id" }],
      },
    });

    expect(ended.messages).toEqual([{
      id: expect.stringMatching(/^pi-message-/),
      role: "assistant",
      content: [{ type: "text", text: "recovered without an id" }],
    }]);
  });

  it("keeps streamed content when a terminal event omits its content", () => {
    const started = assemblePiEvent(initialPiAssemblerState, {
      type: "message_start",
      message: assistant,
    });
    const streamed = assemblePiEvent(started, {
      type: "message_update",
      assistantMessageEvent: { type: "text_delta", contentIndex: 0, delta: "partial" },
    });
    const ended = assemblePiEvent(streamed, {
      type: "message_end",
      message: { ...assistant, content: [], status: "error" },
    });

    expect(ended.messages[0]?.content).toEqual([{ type: "text", text: "partial" }]);
    expect(ended.messages[0]?.status).toBe("error");
  });

  it("replaces tool partial results rather than appending them", () => {
    const started = assemblePiEvent(initialPiAssemblerState, { type: "tool_execution_start", toolCallId: "tool-1", toolName: "read", args: {} });
    const first = assemblePiEvent(started, { type: "tool_execution_update", toolCallId: "tool-1", toolName: "read", args: {}, partialResult: "first" });
    const second = assemblePiEvent(first, { type: "tool_execution_update", toolCallId: "tool-1", toolName: "read", args: {}, partialResult: "second" });
    expect(second.toolExecutions["tool-1"]?.partialResult).toBe("second");
  });

  it("keeps working after agent end and becomes idle only when settled", () => {
    const working = assemblePiEvent(initialPiAssemblerState, { type: "agent_start" });
    const ended = assemblePiEvent(working, { type: "agent_end" });
    const settled = assemblePiEvent(ended, { type: "agent_settled" });
    expect(ended.runningState).toBe("working");
    expect(settled.runningState).toBe("idle");
  });

  it("maps queue, compaction, and retry lifecycle events", () => {
    const queued = assemblePiEvent(initialPiAssemblerState, { type: "queue_update", steering: ["later"], followUp: [] });
    const compacting = assemblePiEvent(queued, { type: "compaction_start", reason: "threshold" });
    const retrying = assemblePiEvent(compacting, { type: "auto_retry_start", attempt: 1, maxAttempts: 3, delayMs: 1000, errorMessage: "retry" });
    expect([queued.runningState, compacting.runningState, retrying.runningState]).toEqual(["queued", "compacting", "retrying"]);
  });

  it("assigns a unique id to compaction notes after restoring history", () => {
    const restored = resetPiAssembler([], "idle", {}, [{
      id: "compaction-2",
      kind: "compaction",
      summary: null,
      aborted: false,
    }]);

    const compacted = assemblePiEvent(restored, {
      type: "compaction_end",
      reason: "threshold",
      aborted: false,
      willRetry: false,
      result: { summary: "summary" },
    });

    expect(compacted.compactionNotes[1]?.id).toMatch(/^compaction-/);
    expect(compacted.compactionNotes[1]?.id).not.toBe("compaction-2");
  });

  it("accepts native Pi messages without ids and normalizes string user content", () => {
    const userStart = parsePiEvent({
      type: "message_start",
      message: { role: "user", content: "Hi", timestamp: 1 },
    });
    const userEnd = parsePiEvent({
      type: "message_end",
      message: { role: "user", content: "Hi", timestamp: 1 },
    });
    const assistantStart = parsePiEvent({
      type: "message_start",
      message: { role: "assistant", content: [], timestamp: 2 },
    });
    const assistantEnd = parsePiEvent({
      type: "message_end",
      message: {
        role: "assistant",
        content: [{ type: "text", text: "Hello!" }],
        timestamp: 3,
      },
    });

    expect([userStart, userEnd, assistantStart, assistantEnd]).not.toContain(null);
    const events = [
      userStart!,
      userEnd!,
      { type: "agent_start" } as const,
      assistantStart!,
      assistantEnd!,
      { type: "agent_settled" } as const,
    ];
    const state = events.reduce(assemblePiEvent, initialPiAssemblerState);

    expect(state.messages).toHaveLength(2);
    expect(state.messages[0]).toMatchObject({
      id: expect.stringMatching(/^pi-message-/),
      role: "user",
      content: [{ type: "text", text: "Hi" }],
    });
    expect(state.messages[1]).toMatchObject({
      id: expect.stringMatching(/^pi-message-/),
      role: "assistant",
      content: [{ type: "text", text: "Hello!" }],
    });
    expect(state.runningState).toBe("idle");
  });

  it("does not collide with fallback-shaped ids restored from history", () => {
    const restored = resetPiAssembler([
      { id: "pi-message-2", role: "user", content: [{ type: "text", text: "existing" }] },
    ], "idle");

    const started = assemblePiEvent(restored, {
      type: "message_start",
      message: { role: "assistant", content: [] },
    });

    expect(started.messages[1]?.id).not.toBe("pi-message-2");
    expect(new Set(started.messages.map((message) => message.id)).size).toBe(2);
  });

  it("normalizes native tool calls restored from a REST snapshot", () => {
    const restored = resetPiAssembler(
      [{
        id: "assistant-tool-call",
        role: "assistant",
        content: [{
          type: "toolCall",
          id: "call-restored",
          name: "workflow_list",
          arguments: { page: 1 },
        }],
      }],
      "idle",
      {
        "call-restored": {
          toolCallId: "call-restored",
          toolName: "workflow_list",
          args: { page: 1 },
          result: { content: [], details: { schema_version: "pressroom-envelope.v1", ok: true } },
          isError: false,
        },
      },
    );

    expect(restored.messages[0]?.content[0]).toMatchObject({
      type: "toolCall",
      toolCallId: "call-restored",
      toolName: "workflow_list",
      input: { page: 1 },
    });
    expect(restored.toolExecutions["call-restored"]?.toolName).toBe("workflow_list");
  });

  it("rejects malformed event payloads before they reach the reducer", () => {
    expect(parsePiEvent({
      type: "message_update",
      assistantMessageEvent: { type: "unknown_delta", contentIndex: 0, delta: "x" },
    })).toBeNull();
    expect(parsePiEvent({
      type: "message_update",
      assistantMessageEvent: { type: "text_delta", contentIndex: 5000, delta: "x" },
    })).toBeNull();
    expect(parsePiEvent({
      type: "tool_execution_update",
      toolCallId: "tool-1",
      toolName: 42,
      args: {},
      partialResult: {},
    })).toBeNull();
    expect(parsePiEvent({
      type: "compaction_end",
      reason: "threshold",
      aborted: false,
      willRetry: false,
      result: { summary: 42 },
    })).toBeNull();
  });
});
