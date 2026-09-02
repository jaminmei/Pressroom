export function parseProxyRequestBody(body) {
  if (body === undefined || body === null) return {};
  if (typeof body !== "string") {
    throw new TypeError(`pi-runtime: unsupported fetch body type: ${typeof body}`);
  }
  return JSON.parse(body);
}

export function requireSuccessfulProxyResponse(response) {
  if (response?.ok !== true) {
    const status = Number.isInteger(response?.status) ? response.status : "unknown";
    throw new Error(`pi-runtime: internal proxy rejected request (HTTP ${status})`);
  }
  return response;
}

// Pi's documented JSON wire transform (docs/json.md): message_update carries only
// the delta event, without the cumulative partial message snapshot.
export function toJsonEvent(event) {
  const assistantMessageEvent = event?.assistantMessageEvent;
  if (
    event?.type === "message_update"
    && typeof assistantMessageEvent === "object"
    && assistantMessageEvent !== null
    && !Array.isArray(assistantMessageEvent)
  ) {
    const { partial: _partial, ...delta } = assistantMessageEvent;
    return { type: event.type, assistantMessageEvent: delta };
  }
  return event;
}

export const errorMessage = (error) =>
  error instanceof Error ? error.message : String(error ?? "unknown error");

export function scrubRuntimeEnvironment(environment, names) {
  for (const name of names) delete environment[name];
}

export function parseRuntimeBootstrap(line, requiredFields) {
  let payload;
  try {
    payload = JSON.parse(line);
  } catch (error) {
    throw new SyntaxError("Invalid runtime bootstrap JSON", { cause: error });
  }
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    throw new TypeError("Runtime bootstrap must be a JSON object");
  }
  for (const field of requiredFields) {
    if (typeof payload[field] !== "string" || payload[field].length === 0) {
      throw new TypeError(`Runtime bootstrap is missing ${field}`);
    }
  }
  return payload;
}

const LEGACY_MESSAGE_ROLES = new Set(["user", "assistant", "toolResult"]);
const LEGACY_CONTENT_TYPES = new Set(["text", "thinking", "image", "toolCall"]);
export const MAX_LEGACY_MESSAGES = 200;

function isPlainObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Validate browser-projected legacy messages before they become Pi context.
 * The browser-only top-level id is removed; native content ids (for example a
 * tool-call id) remain part of the model conversation contract.
 */
export function normalizeLegacyMessages(value) {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length === 0 || value.length > MAX_LEGACY_MESSAGES) {
    throw new TypeError("Runtime bootstrap has invalid legacy message count");
  }
  return value.map((rawMessage) => {
    if (
      !isPlainObject(rawMessage)
      || !LEGACY_MESSAGE_ROLES.has(rawMessage.role)
      || !Number.isSafeInteger(rawMessage.timestamp)
      || rawMessage.timestamp < 0
    ) {
      throw new TypeError("Runtime bootstrap has an invalid legacy message");
    }
    const content = typeof rawMessage.content === "string"
      ? rawMessage.content
      : Array.isArray(rawMessage.content)
        ? rawMessage.content.map((block) => {
            if (!isPlainObject(block) || !LEGACY_CONTENT_TYPES.has(block.type)) {
              throw new TypeError("Runtime bootstrap has invalid legacy message content");
            }
            return structuredClone(block);
          })
        : null;
    if (content === null) {
      throw new TypeError("Runtime bootstrap has invalid legacy message content");
    }
    const message = structuredClone(rawMessage);
    delete message.id;
    message.content = content;
    return message;
  });
}

export function parseModelCapabilities(config) {
  const contextWindow = config.PI_MODEL_CONTEXT_WINDOW;
  const maxTokens = config.PI_MODEL_MAX_TOKENS;
  if (
    typeof contextWindow !== "number"
    || !Number.isSafeInteger(contextWindow)
    || contextWindow <= 0
  ) {
    throw new TypeError("Runtime bootstrap has invalid model context window");
  }
  if (
    typeof maxTokens !== "number"
    || !Number.isSafeInteger(maxTokens)
    || maxTokens <= 0
    || maxTokens > contextWindow
  ) {
    throw new TypeError("Runtime bootstrap has invalid model max tokens");
  }
  if (typeof config.PI_MODEL_REASONING !== "boolean") {
    throw new TypeError("Runtime bootstrap has invalid model reasoning capability");
  }
  return {
    contextWindow,
    maxTokens,
    reasoning: config.PI_MODEL_REASONING,
  };
}

const SAFE_ERROR_KINDS = new Set([
  "AbortError",
  "AggregateError",
  "Error",
  "EvalError",
  "RangeError",
  "ReferenceError",
  "SyntaxError",
  "TimeoutError",
  "TypeError",
  "URIError",
]);

export function errorKind(error) {
  if (error instanceof Error) {
    return SAFE_ERROR_KINDS.has(error.name) ? error.name : "Error";
  }
  return typeof error;
}

export const MAX_COMMAND_LINE_LENGTH = 1_048_576;

export class JsonLineDecoder {
  constructor(maxLength = MAX_COMMAND_LINE_LENGTH) {
    this.maxLength = maxLength;
    this.segments = [];
    this.length = 0;
  }

  push(chunk) {
    if (typeof chunk !== "string") throw new TypeError("JSONL input chunk must be a string");
    const lines = [];
    let lineStart = 0;
    let newlineIndex = chunk.indexOf("\n", lineStart);

    while (newlineIndex !== -1) {
      const segment = chunk.slice(lineStart, newlineIndex);
      if (this.length + segment.length > this.maxLength) {
        throw new RangeError("JSONL command exceeds the maximum line length");
      }
      this.segments.push(segment);
      lines.push(this.segments.join(""));
      this.segments = [];
      this.length = 0;
      lineStart = newlineIndex + 1;
      newlineIndex = chunk.indexOf("\n", lineStart);
    }

    const remainder = chunk.slice(lineStart);
    if (this.length + remainder.length > this.maxLength) {
      throw new RangeError("JSONL command exceeds the maximum line length");
    }
    if (remainder.length > 0) {
      this.segments.push(remainder);
      this.length += remainder.length;
    }
    return lines;
  }

  remainder() {
    return this.segments.join("");
  }
}

export function splitJsonLines(buffer, chunk, maxLength = MAX_COMMAND_LINE_LENGTH) {
  const decoder = new JsonLineDecoder(maxLength);
  if (decoder.push(buffer).length > 0) {
    throw new TypeError("JSONL remainder must not contain a newline");
  }
  const lines = decoder.push(chunk);
  return { lines, remainder: decoder.remainder() };
}

export async function waitForWritableFlush(writable, timeoutMs = 1_000) {
  if (writable.writableLength === 0) return true;
  if (writable.destroyed) return false;

  return new Promise((resolve) => {
    let timer;
    let settled = false;
    const finish = (flushed) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      writable.off("drain", onDrain);
      writable.off("error", onError);
      writable.off("close", onClose);
      resolve(flushed);
    };
    const onDrain = () => finish(true);
    const onError = () => finish(false);
    const onClose = () => finish(false);

    writable.once("drain", onDrain);
    writable.once("error", onError);
    writable.once("close", onClose);
    timer = setTimeout(() => finish(writable.writableLength === 0), timeoutMs);
    setImmediate(() => {
      if (writable.writableLength === 0) finish(true);
    });
  });
}

export async function abortWithSingleResponse(abort, onResponse, onLateFailure = () => {}) {
  let responded = false;
  const respondOnce = (success, error) => {
    if (responded) return;
    responded = true;
    onResponse(success, error);
  };

  try {
    const completion = abort();
    respondOnce(true);
    await completion;
  } catch (error) {
    if (responded) {
      onLateFailure(errorKind(error));
    } else {
      respondOnce(false, errorMessage(error));
    }
  }
}
