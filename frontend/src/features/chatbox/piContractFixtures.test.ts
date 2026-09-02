import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  assemblePiEvent,
  initialPiAssemblerState,
  parsePiEvent,
  type PiAssemblerState,
  type PiEvent
} from "@/features/chatbox/piEventAssembler";

interface ContractFixture {
  readonly name: string;
  readonly raw_events: readonly unknown[];
  readonly projected_events: readonly unknown[];
}

const fixturesDir = resolve(process.cwd(), "../tests/fixtures/pi_contract");

function isContractFixture(value: unknown): value is ContractFixture {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.name === "string" &&
    Array.isArray(candidate.raw_events) &&
    Array.isArray(candidate.projected_events)
  );
}

function loadFixtures(): ContractFixture[] {
  return readdirSync(fixturesDir)
    .filter((name) => name.endsWith(".json"))
    .sort()
    .map((name) => {
      const parsed: unknown = JSON.parse(readFileSync(`${fixturesDir}/${name}`, "utf-8"));
      if (!isContractFixture(parsed)) throw new Error(`Invalid contract fixture: ${name}`);
      return parsed;
    });
}

function reduceFixture(events: readonly unknown[]): { state: PiAssemblerState; parsed: PiEvent[] } {
  let state = initialPiAssemblerState;
  const parsed: PiEvent[] = [];
  for (const raw of events) {
    const event = parsePiEvent(raw);
    if (event === null) continue;
    parsed.push(event);
    state = assemblePiEvent(state, event);
  }
  return { state, parsed };
}

function textOf(messageIndex: number, blockIndex: number, state: PiAssemblerState): string {
  const block = state.messages[messageIndex]?.content[blockIndex];
  if (block === undefined || !("text" in block)) return "";
  const text: unknown = block.text;
  return typeof text === "string" ? text : "";
}

describe("Pi event contract fixtures", () => {
  const fixtures = loadFixtures();
  const byName = new Map(fixtures.map((fixture) => [fixture.name, fixture]));

  it("loads the complete required fixture set", () => {
    expect(fixtures.map((fixture) => fixture.name)).toEqual([
      "abort",
      "agent-settled",
      "compaction",
      "failure",
      "multi-tool",
      "partial-output",
      "retry",
      "streaming-text",
      "thinking"
    ]);
  });

  it("streaming-text: reconstructs the streamed message and ends idle", () => {
    const { state } = reduceFixture(byName.get("streaming-text")!.projected_events);
    expect(state.runningState).toBe("idle");
    expect(state.messages).toHaveLength(2);
    expect(textOf(1, 0, state)).toBe("The file exports a single handler.");
  });

  it("thinking: preserves thinking-then-text block order", () => {
    const { state } = reduceFixture(byName.get("thinking")!.projected_events);
    const assistant = state.messages[state.messages.length - 1];
    expect(assistant?.content.map((block) => block.type)).toEqual(["thinking", "text"]);
    expect(assistant?.content[0]).toMatchObject({ type: "thinking", thinking: "The user wants a summary." });
  });

  it("multi-tool: tracks both executions and the tool result messages", () => {
    const { state } = reduceFixture(byName.get("multi-tool")!.projected_events);
    expect(state.toolExecutions["tc-read"]).toMatchObject({ isError: false, args: { path: "src/app.ts" } });
    expect(state.toolExecutions["tc-grep"]).toMatchObject({ toolName: "grep", isError: false });
    expect(state.messages.filter((message) => message.role === "toolResult")).toHaveLength(2);
    expect(state.runningState).toBe("idle");
  });

  it("partial-output: replaces partial results instead of appending", () => {
    const { state } = reduceFixture(byName.get("partial-output")!.projected_events);
    const execution = state.toolExecutions["tc-bash"];
    const partialText = JSON.stringify(execution?.partialResult);
    expect(partialText).toContain("PASS src/a\\nPASS src/b");
    expect(partialText).not.toContain("PASS src/aPASS src/b");
    expect(execution).toMatchObject({ isError: false });
  });

  it("failure: flags the error execution and still settles to idle", () => {
    const { state } = reduceFixture(byName.get("failure")!.projected_events);
    expect(state.toolExecutions["tc-bash"]?.isError).toBe(true);
    expect(state.messages[state.messages.length - 1]).toMatchObject({ status: "error", stopReason: "error" });
    expect(state.runningState).toBe("idle");
  });

  it("abort: keeps the aborted message and settles to idle", () => {
    const { state } = reduceFixture(byName.get("abort")!.projected_events);
    expect(state.messages[state.messages.length - 1]).toMatchObject({ status: "aborted", stopReason: "aborted" });
    expect(state.runningState).toBe("idle");
  });

  it("retry: maps retry lifecycle and drops nothing parseable", () => {
    const { state, parsed } = reduceFixture(byName.get("retry")!.projected_events);
    const retryStart = parsed.find((event) => event.type === "auto_retry_start");
    expect(retryStart).toBeDefined();
    expect(state.runningState).toBe("idle");
    expect(state.messages.some((message) => message.id === "c1")).toBe(false);
    expect(state.messages[state.messages.length - 1]?.content[0]).toMatchObject({ type: "text", text: "Retried and recovered." });
  });

  it("compaction: records the compaction note and continues", () => {
    const { state } = reduceFixture(byName.get("compaction")!.projected_events);
    expect(state.compactionNotes).toHaveLength(1);
    expect(state.compactionNotes[0]).toMatchObject({ kind: "compaction", aborted: false });
    expect(state.runningState).toBe("idle");
  });

  it("agent-settled: only agent_settled returns the session to idle", () => {
    const events = byName.get("agent-settled")!.projected_events;
    let state = initialPiAssemblerState;
    const seenStates: string[] = [];
    for (const raw of events) {
      const event = parsePiEvent(raw);
      if (event === null) continue;
      state = assemblePiEvent(state, event);
      seenStates.push(state.runningState);
    }
    expect(seenStates).toContain("queued");
    const firstAgentEnd = events.findIndex((value) =>
      value !== null && typeof value === "object" && "type" in value && (value as { type: string }).type === "agent_end"
    );
    expect(seenStates[firstAgentEnd]).not.toBe("idle");
    expect(state.runningState).toBe("idle");
  });
});
