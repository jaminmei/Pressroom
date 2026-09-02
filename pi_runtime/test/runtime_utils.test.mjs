import assert from "node:assert/strict";
import test from "node:test";

import { runImageSelfChecks } from "../src/image_self_check.mjs";
import {
  abortWithSingleResponse,
  errorKind,
  JsonLineDecoder,
  MAX_COMMAND_LINE_LENGTH,
  MAX_LEGACY_MESSAGES,
  normalizeLegacyMessages,
  parseModelCapabilities,
  parseRuntimeBootstrap,
  parseProxyRequestBody,
  requireSuccessfulProxyResponse,
  scrubRuntimeEnvironment,
  splitJsonLines,
  toJsonEvent,
  waitForWritableFlush,
} from "../src/runtime_utils.mjs";

test("parseProxyRequestBody accepts JSON strings and an absent body", () => {
  assert.deepEqual(parseProxyRequestBody(undefined), {});
  assert.deepEqual(parseProxyRequestBody(null), {});
  assert.deepEqual(parseProxyRequestBody('{"messages":[]}'), { messages: [] });
});

test("parseProxyRequestBody rejects non-string bodies", () => {
  assert.throws(
    () => parseProxyRequestBody(new Uint8Array()),
    /unsupported fetch body type: object/,
  );
});

test("parseProxyRequestBody rejects invalid JSON strings", () => {
  assert.throws(() => parseProxyRequestBody("{bad json"), SyntaxError);
});

test("proxy response validation returns success and reports only a failing status", () => {
  const successful = { ok: true, status: 200 };
  assert.equal(requireSuccessfulProxyResponse(successful), successful);

  const failure = { ok: false, status: 503, body: "credential-bearing upstream detail" };
  assert.throws(
    () => requireSuccessfulProxyResponse(failure),
    (error) => {
      assert.equal(
        error.message,
        "pi-runtime: internal proxy rejected request (HTTP 503)",
      );
      assert.doesNotMatch(error.message, /credential-bearing/);
      return true;
    },
  );
});

test("JSON event projection strips partial snapshots and passes malformed updates through", () => {
  assert.deepEqual(
    toJsonEvent({
      type: "message_update",
      assistantMessageEvent: { type: "text_delta", delta: "hi", partial: { secret: true } },
    }),
    {
      type: "message_update",
      assistantMessageEvent: { type: "text_delta", delta: "hi" },
    },
  );

  for (const assistantMessageEvent of [undefined, null, "invalid", []]) {
    const event = { type: "message_update", assistantMessageEvent };
    assert.equal(toJsonEvent(event), event);
  }
});

test("scrubRuntimeEnvironment removes server-owned Pi values from tool environments", () => {
  const environment = {
    PATH: "/usr/bin",
    PI_PROXY_TOKEN: "internal-grant",
    PI_PROXY_URL: "http://internal-proxy",
    PI_WORKSPACE_ROOT: "/private/workspace",
  };

  scrubRuntimeEnvironment(environment, [
    "PI_PROXY_TOKEN",
    "PI_PROXY_URL",
    "PI_WORKSPACE_ROOT",
  ]);

  assert.deepEqual(environment, { PATH: "/usr/bin" });
});

test("parseRuntimeBootstrap requires a JSON object with every server field", () => {
  const required = ["PI_PROXY_TOKEN", "PI_WORKSPACE_ROOT"];
  assert.deepEqual(
    parseRuntimeBootstrap(
      '{"PI_PROXY_TOKEN":"grant","PI_WORKSPACE_ROOT":"/workspace"}',
      required,
    ),
    { PI_PROXY_TOKEN: "grant", PI_WORKSPACE_ROOT: "/workspace" },
  );
  assert.throws(() => parseRuntimeBootstrap("[]", required), TypeError);
  assert.throws(
    () => parseRuntimeBootstrap('{"PI_PROXY_TOKEN":"grant"}', required),
    /PI_WORKSPACE_ROOT/,
  );
  assert.throws(() => parseRuntimeBootstrap("{bad", required), SyntaxError);
});

test("legacy history normalization strips only browser projection ids", () => {
  const messages = normalizeLegacyMessages([
    {
      id: "browser-user-id",
      role: "user",
      content: [{ type: "text", text: "Remember alpha." }],
      timestamp: 1,
    },
    {
      id: "browser-assistant-id",
      role: "assistant",
      api: "anthropic-messages",
      provider: "doc-conv-proxy",
      model: "model-a",
      content: [{ type: "toolCall", id: "native-tool-id", name: "workflow_list", arguments: {} }],
      usage: {},
      stopReason: "toolUse",
      timestamp: 2,
    },
  ]);

  assert.equal(messages[0].id, undefined);
  assert.equal(messages[1].id, undefined);
  assert.equal(messages[1].content[0].id, "native-tool-id");
});

test("legacy history normalization rejects malformed and oversized projections", () => {
  assert.throws(() => normalizeLegacyMessages([]), /message count/);
  assert.throws(
    () => normalizeLegacyMessages(Array.from({ length: MAX_LEGACY_MESSAGES + 1 }, () => ({
      role: "user",
      content: "hello",
      timestamp: 1,
    }))),
    /message count/,
  );
  assert.throws(
    () => normalizeLegacyMessages([{ role: "system", content: "unsafe", timestamp: 1 }]),
    /invalid legacy message/,
  );
  assert.throws(
    () => normalizeLegacyMessages([{
      role: "user",
      content: [{ type: "browser-only", value: "unsafe" }],
      timestamp: 1,
    }]),
    /invalid legacy message content/,
  );
});

test("parseModelCapabilities accepts native bounded model metadata", () => {
  assert.deepEqual(
    parseModelCapabilities({
      PI_MODEL_CONTEXT_WINDOW: 200_000,
      PI_MODEL_MAX_TOKENS: 8_192,
      PI_MODEL_REASONING: true,
    }),
    { contextWindow: 200_000, maxTokens: 8_192, reasoning: true },
  );
});

test("parseModelCapabilities rejects coercible, unsafe, and inconsistent metadata", () => {
  const valid = {
    PI_MODEL_CONTEXT_WINDOW: 128_000,
    PI_MODEL_MAX_TOKENS: 4_096,
    PI_MODEL_REASONING: false,
  };
  assert.throws(
    () => parseModelCapabilities({ ...valid, PI_MODEL_CONTEXT_WINDOW: "128000" }),
    /context window/,
  );
  assert.throws(
    () => parseModelCapabilities({
      ...valid,
      PI_MODEL_CONTEXT_WINDOW: Number.MAX_SAFE_INTEGER + 1,
    }),
    /context window/,
  );
  for (const invalidContextWindow of [Number.NaN, Number.POSITIVE_INFINITY, 0, -1]) {
    assert.throws(
      () => parseModelCapabilities({
        ...valid,
        PI_MODEL_CONTEXT_WINDOW: invalidContextWindow,
      }),
      /context window/,
    );
  }
  assert.throws(
    () => parseModelCapabilities({ ...valid, PI_MODEL_MAX_TOKENS: 128_001 }),
    /max tokens/,
  );
  for (const invalidMaxTokens of [Number.NaN, Number.POSITIVE_INFINITY, 0, -1]) {
    assert.throws(
      () => parseModelCapabilities({
        ...valid,
        PI_MODEL_MAX_TOKENS: invalidMaxTokens,
      }),
      /max tokens/,
    );
  }
  assert.throws(
    () => parseModelCapabilities({ ...valid, PI_MODEL_REASONING: "false" }),
    /reasoning capability/,
  );
});

test("errorKind reports only a bounded error classification", () => {
  const error = new Error("credential-bearing diagnostic");
  error.name = "CredentialMaterial";

  assert.equal(errorKind(new TypeError("sensitive message")), "TypeError");
  assert.equal(errorKind(error), "Error");
  assert.equal(errorKind({ secret: "not rendered" }), "object");
});

test("splitJsonLines preserves partial input and accepts CRLF framing", () => {
  assert.deepEqual(splitJsonLines("first", " line\r\nsecond\npartial", 32), {
    lines: ["first line\r", "second"],
    remainder: "partial",
  });
});

test("JsonLineDecoder accumulates fragmented commands without repeated whole-buffer copies", () => {
  const decoder = new JsonLineDecoder(32);
  assert.deepEqual(decoder.push("first"), []);
  assert.deepEqual(decoder.push(" line\r\nsecond\npartial"), ["first line\r", "second"]);
  assert.equal(decoder.remainder(), "partial");
  assert.throws(() => decoder.push("x".repeat(26)), RangeError);
});

test("splitJsonLines rejects oversized complete and partial lines", () => {
  assert.throws(() => splitJsonLines("", "x".repeat(5), 4), RangeError);
  assert.throws(() => splitJsonLines("", `${"x".repeat(5)}\n`, 4), RangeError);
  assert.doesNotThrow(() =>
    splitJsonLines("", `${"x".repeat(MAX_COMMAND_LINE_LENGTH)}\n`),
  );
});

test("abortWithSingleResponse reports synchronous rejection once", async () => {
  const responses = [];

  await abortWithSingleResponse(
    () => {
      throw new Error("abort rejected");
    },
    (success, error) => responses.push({ success, error }),
  );

  assert.deepEqual(responses, [{ success: false, error: "abort rejected" }]);
});

test("abortWithSingleResponse does not emit a second response after acceptance", async () => {
  const responses = [];
  const lateFailures = [];

  await abortWithSingleResponse(
    () => Promise.reject(new Error("late abort failure")),
    (success, error) => responses.push({ success, error }),
    (kind) => lateFailures.push(kind),
  );

  assert.deepEqual(responses, [{ success: true, error: undefined }]);
  assert.deepEqual(lateFailures, ["Error"]);
});

test("waitForWritableFlush resolves on drain and bounds a stalled stream", async () => {
  const listeners = new Map();
  const writable = {
    destroyed: false,
    writableLength: 1,
    once(event, listener) {
      listeners.set(event, listener);
    },
    off(event, listener) {
      if (listeners.get(event) === listener) listeners.delete(event);
    },
  };

  const drained = waitForWritableFlush(writable, 100);
  writable.writableLength = 0;
  listeners.get("drain")();
  assert.equal(await drained, true);

  writable.writableLength = 1;
  assert.equal(await waitForWritableFlush(writable, 1), false);
  assert.equal(listeners.size, 0);

  writable.destroyed = true;
  assert.equal(await waitForWritableFlush(writable, 100), false);
  writable.destroyed = false;

  writable.writableLength = 1;
  const closed = waitForWritableFlush(writable, 100);
  writable.destroyed = true;
  listeners.get("close")();
  assert.equal(await closed, false);
  assert.equal(listeners.size, 0);
});

test("image self-check failure output includes a safe kind, not exception details", async () => {
  let stdout = "";
  let stderr = "";
  const streams = {
    stdout: {
      write(value) {
        stdout += value;
      },
    },
    stderr: {
      write(value) {
        stderr += value;
      },
    },
  };

  const passed = await runImageSelfChecks(
    [
      ["runtime entry", async () => {}],
      ["dependency import", async () => Promise.reject(new Error("credential material"))],
    ],
    streams,
  );

  assert.equal(passed, false);
  assert.equal(stdout, "pi-runtime image check passed: runtime entry\n");
  assert.equal(stderr, "pi-runtime image check failed: dependency import (Error)\n");
  assert.doesNotMatch(`${stdout}${stderr}`, /credential material/);
});
