import { generateChatboxId } from "@/features/chatbox/chatboxId";

export type RunningState = "idle" | "working" | "queued" | "compacting" | "retrying";

export type PiContentBlock =
  | { readonly type: "text"; readonly text: string }
  | { readonly type: "thinking"; readonly thinking: string; readonly redacted?: boolean }
  | { readonly type: "toolCall"; readonly toolCallId: string; readonly toolName: string; readonly input: unknown }
  | { readonly type: "admission"; readonly status: string; readonly reasonCode: string }
  | { readonly type: string; readonly [key: string]: unknown };

export interface PiMessage {
  readonly id: string;
  readonly role: string;
  readonly content: readonly PiContentBlock[];
  readonly [key: string]: unknown;
}

export interface PiWireMessage {
  readonly id?: string;
  readonly role: string;
  readonly content: string | readonly PiContentBlock[];
  readonly [key: string]: unknown;
}

export type PiEvent =
  | { readonly type: "message_start"; readonly message: PiWireMessage }
  | { readonly type: "message_update"; readonly assistantMessageEvent: AssistantMessageEvent }
  | { readonly type: "message_end"; readonly message: PiWireMessage }
  | { readonly type: "tool_execution_start"; readonly toolCallId: string; readonly toolName: string; readonly args: unknown }
  | { readonly type: "tool_execution_update"; readonly toolCallId: string; readonly toolName: string; readonly args: unknown; readonly partialResult: unknown }
  | { readonly type: "tool_execution_end"; readonly toolCallId: string; readonly toolName: string; readonly result: unknown; readonly isError: boolean }
  | { readonly type: "agent_start" | "turn_start" | "turn_end" | "agent_end" | "agent_settled" }
  | { readonly type: "queue_update"; readonly steering: readonly string[]; readonly followUp: readonly string[] }
  | { readonly type: "compaction_start"; readonly reason: string }
  | { readonly type: "compaction_end"; readonly reason: string; readonly aborted: boolean; readonly willRetry: boolean; readonly result?: { readonly summary?: string } | null }
  | { readonly type: "auto_retry_start"; readonly attempt: number; readonly maxAttempts: number; readonly delayMs: number; readonly errorMessage: string }
  | { readonly type: "auto_retry_end"; readonly success: boolean; readonly attempt: number; readonly finalError?: string };

export type AssistantMessageEvent = {
  readonly type: "text_delta" | "thinking_delta" | "toolcall_delta";
  readonly contentIndex: number;
  readonly delta: string;
};

export interface ToolExecution {
  readonly toolCallId: string;
  readonly toolName: string;
  readonly args?: unknown;
  readonly partialResult?: unknown;
  readonly result?: unknown;
  readonly isError?: boolean;
}

export interface CompactionNote {
  readonly id: string;
  readonly kind: "compaction";
  readonly summary: string | null;
  readonly aborted: boolean;
}

export interface PiAssemblerState {
  readonly messages: readonly PiMessage[];
  readonly runningState: RunningState;
  readonly liveMessageId: string | null;
  readonly toolExecutions: Readonly<Record<string, ToolExecution>>;
  readonly compactionNotes: readonly CompactionNote[];
}

export const initialPiAssemblerState: PiAssemblerState = {
  messages: [],
  runningState: "idle",
  liveMessageId: null,
  toolExecutions: {},
  compactionNotes: []
};

const MAX_CONTENT_INDEX = 4096;
const CONTENT_PLACEHOLDER: PiContentBlock = { type: "placeholder" };

function appendDelta(block: PiContentBlock | undefined, event: AssistantMessageEvent): PiContentBlock {
  if (event.type === "text_delta") {
    return {
      type: "text",
      text: block?.type === "text" ? block.text + event.delta : event.delta,
    };
  }
  if (event.type === "thinking_delta") {
    return {
      type: "thinking",
      thinking: block?.type === "thinking" ? block.thinking + event.delta : event.delta,
    };
  }
  const input = block?.type === "toolCall" && typeof block.input !== "string"
    ? (block.input ?? event.delta)
    : `${block?.type === "toolCall" ? block.input : ""}${event.delta}`;
  return {
    type: "toolCall",
    toolCallId: block?.type === "toolCall" ? block.toolCallId : "",
    toolName: block?.type === "toolCall" ? block.toolName : "",
    input,
  };
}

function updateLiveMessage(state: PiAssemblerState, event: AssistantMessageEvent): PiAssemblerState {
  const liveId = state.liveMessageId;
  if (liveId === null) return state;
  return {
    ...state,
    messages: state.messages.map((message) => {
      if (message.id !== liveId) return message;
      const content = [...message.content];
      while (content.length < event.contentIndex) {
        content.push(CONTENT_PLACEHOLDER);
      }
      content[event.contentIndex] = appendDelta(content[event.contentIndex], event);
      return { ...message, content };
    })
  };
}

function uniqueMessageId(state: PiAssemblerState): string {
  let candidate = generateChatboxId("pi-message");
  while (state.messages.some((message) => message.id === candidate)) {
    candidate = generateChatboxId("pi-message");
  }
  return candidate;
}

function withoutPlaceholders(content: readonly PiContentBlock[]): readonly PiContentBlock[] {
  return content.filter((block) => block.type !== CONTENT_PLACEHOLDER.type);
}

function normalizeContentBlock(block: PiContentBlock): PiContentBlock {
  if (block.type !== "toolCall") return block;
  // Pi's final SDK message can use id/name/arguments instead of the browser
  // toolCallId/toolName/input shape, so retain runtime checks despite the
  // broad catch-all member in PiContentBlock.
  const rawBlock = block as Readonly<Record<string, unknown>>;
  let toolCallId = "";
  if (typeof block.toolCallId === "string") toolCallId = block.toolCallId;
  else if (typeof rawBlock.id === "string") toolCallId = rawBlock.id;
  let toolName = "";
  if (typeof block.toolName === "string") toolName = block.toolName;
  else if (typeof rawBlock.name === "string") toolName = rawBlock.name;
  const input = "input" in rawBlock ? rawBlock.input : rawBlock.arguments;
  return { ...block, toolCallId, toolName, input };
}

function normalizeMessage(message: PiWireMessage, id: string): PiMessage {
  return {
    ...message,
    id,
    content:
      typeof message.content === "string"
        ? [{ type: "text", text: message.content }]
        : message.content.map(normalizeContentBlock),
  };
}

export function assemblePiEvent(state: PiAssemblerState, event: PiEvent): PiAssemblerState {
  switch (event.type) {
    case "message_start": {
      const message = normalizeMessage(
        event.message,
        event.message.id ?? uniqueMessageId(state),
      );
      return { ...state, messages: [...state.messages, message], liveMessageId: message.id };
    }
    case "message_update": return updateLiveMessage(state, event.assistantMessageEvent);
    case "message_end": {
      const messageId = event.message.id ?? state.liveMessageId ?? uniqueMessageId(state);
      const currentMessage = state.messages.find((current) => current.id === messageId);
      const authoritativeMessage = normalizeMessage(event.message, messageId);
      const preferAuthoritative =
        authoritativeMessage.content.length > 0 || currentMessage === undefined;
      // A terminal event can omit content after streaming it. Keep the accumulated
      // blocks in that case, but discard internal sparse-index placeholders.
      const message = preferAuthoritative
        ? authoritativeMessage
        : { ...authoritativeMessage, content: withoutPlaceholders(currentMessage.content) };
      if (currentMessage === undefined) {
        return {
          ...state,
          messages: [...state.messages, message],
          liveMessageId: state.liveMessageId === messageId ? null : state.liveMessageId,
        };
      }
      return {
        ...state,
        messages: state.messages.map((current) => current.id === messageId ? message : current),
        liveMessageId: state.liveMessageId === messageId ? null : state.liveMessageId,
      };
    }
    case "tool_execution_start": return { ...state, toolExecutions: { ...state.toolExecutions, [event.toolCallId]: { toolCallId: event.toolCallId, toolName: event.toolName, args: event.args } } };
    case "tool_execution_update": {
      const current = state.toolExecutions[event.toolCallId] ?? { toolCallId: event.toolCallId, toolName: event.toolName, args: event.args };
      return { ...state, toolExecutions: { ...state.toolExecutions, [event.toolCallId]: { ...current, partialResult: event.partialResult } } };
    }
    case "tool_execution_end": {
      const current = state.toolExecutions[event.toolCallId] ?? { toolCallId: event.toolCallId, toolName: event.toolName, args: undefined };
      return { ...state, toolExecutions: { ...state.toolExecutions, [event.toolCallId]: { ...current, result: event.result, isError: event.isError } } };
    }
    case "agent_start": case "turn_start": return { ...state, runningState: "working" };
    case "queue_update": return { ...state, runningState: event.steering.length + event.followUp.length > 0 ? "queued" : "working" };
    case "compaction_start": return { ...state, runningState: "compacting" };
    case "compaction_end": {
      const note: CompactionNote = {
        id: generateChatboxId("compaction"),
        kind: "compaction",
        summary: event.result?.summary ?? null,
        aborted: event.aborted
      };
      return { ...state, runningState: event.willRetry ? "retrying" : "working", compactionNotes: [...state.compactionNotes, note] };
    }
    case "auto_retry_start": return { ...state, runningState: "retrying" };
    case "auto_retry_end": return { ...state, runningState: event.success ? "working" : "retrying" };
    case "agent_settled": return { ...state, runningState: "idle", liveMessageId: null };
    case "agent_end": case "turn_end": return state;
    default: return state;
  }
}

export function resetPiAssembler(
  messages: readonly PiMessage[],
  state: RunningState,
  toolExecutions: Readonly<Record<string, ToolExecution>> = {},
  compactionNotes: readonly CompactionNote[] = [],
  liveMessageId: string | null = null,
): PiAssemblerState {
  return {
    ...initialPiAssemblerState,
    // REST snapshots persist Pi's native final message shape. Normalize them
    // exactly like live message_end events so id/name/arguments tool calls can
    // still join their tool_execution record after reconnect or page reload.
    messages: messages.map((message) => normalizeMessage(message, message.id)),
    runningState: state,
    toolExecutions,
    compactionNotes,
    liveMessageId,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isPiWireMessage(value: unknown): value is PiWireMessage {
  if (!isRecord(value)) return false;
  const contentIsValid = typeof value.content === "string"
    || (Array.isArray(value.content)
      && value.content.every((block) => isRecord(block) && typeof block.type === "string"));
  return (
    typeof value.role === "string"
    && contentIsValid
    && (!("id" in value) || typeof value.id === "string")
  );
}

function isAssistantMessageEvent(value: unknown): value is AssistantMessageEvent {
  if (!isRecord(value)) return false;
  return (
    (value.type === "text_delta"
      || value.type === "thinking_delta"
      || value.type === "toolcall_delta")
    && typeof value.contentIndex === "number"
    && Number.isInteger(value.contentIndex)
    && value.contentIndex >= 0
    && value.contentIndex <= MAX_CONTENT_INDEX
    && typeof value.delta === "string"
  );
}

function isStringArray(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isCompactionResult(value: unknown): boolean {
  return value === undefined
    || value === null
    || (isRecord(value)
      && !Array.isArray(value)
      && (!("summary" in value) || typeof value.summary === "string"));
}

export function parsePiEvent(value: unknown): PiEvent | null {
  if (!isRecord(value)) return null;
  const type = value.type;
  if (typeof type !== "string") return null;
  switch (type) {
    case "message_start":
    case "message_end":
      return isPiWireMessage(value.message) ? value as PiEvent : null;
    case "message_update":
      return isAssistantMessageEvent(value.assistantMessageEvent) ? value as PiEvent : null;
    case "tool_execution_start":
      return typeof value.toolCallId === "string"
        && typeof value.toolName === "string"
        && "args" in value
        ? value as PiEvent
        : null;
    case "tool_execution_update":
      return typeof value.toolCallId === "string"
        && typeof value.toolName === "string"
        && "args" in value
        && "partialResult" in value
        ? value as PiEvent
        : null;
    case "tool_execution_end":
      return typeof value.toolCallId === "string"
        && typeof value.toolName === "string"
        && "result" in value
        && typeof value.isError === "boolean"
        ? value as PiEvent
        : null;
    case "queue_update":
      return isStringArray(value.steering) && isStringArray(value.followUp)
        ? value as PiEvent
        : null;
    case "compaction_start":
      return typeof value.reason === "string" ? value as PiEvent : null;
    case "compaction_end":
      return typeof value.reason === "string"
        && typeof value.aborted === "boolean"
        && typeof value.willRetry === "boolean"
        && isCompactionResult(value.result)
        ? value as PiEvent
        : null;
    case "auto_retry_start":
      return typeof value.attempt === "number"
        && typeof value.maxAttempts === "number"
        && typeof value.delayMs === "number"
        && typeof value.errorMessage === "string"
        ? value as PiEvent
        : null;
    case "auto_retry_end":
      return typeof value.success === "boolean"
        && typeof value.attempt === "number"
        && (!("finalError" in value) || typeof value.finalError === "string")
        ? value as PiEvent
        : null;
    case "agent_start":
    case "turn_start":
    case "turn_end":
    case "agent_end":
    case "agent_settled":
      return value as PiEvent;
    default:
      return null;
  }
}
