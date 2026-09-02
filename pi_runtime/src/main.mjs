#!/usr/bin/env node
// JSONL compatibility entrypoint for direct Runtime launches. The production
// control service imports runtime_session.mjs once and hosts many logical
// AgentSessions without spawning this process for every conversation switch.

import {
  errorKind,
  JsonLineDecoder,
  parseRuntimeBootstrap,
  scrubRuntimeEnvironment,
  waitForWritableFlush,
} from "./runtime_utils.mjs";
import {
  createRuntimeSession,
  REQUIRED_STRING_BOOTSTRAP_FIELDS,
  RUNTIME_BOOTSTRAP_ENV_FIELDS,
} from "./runtime_session.mjs";

const MAX_BOOTSTRAP_LINE_LENGTH = 1_048_576;

async function readBootstrapLine(stream) {
  stream.setEncoding("utf8");
  return new Promise((resolve, reject) => {
    let buffer = "";
    const cleanup = () => {
      stream.off("data", onData);
      stream.off("end", onEnd);
      stream.off("error", onError);
    };
    const fail = (error) => {
      cleanup();
      stream.pause();
      reject(error);
    };
    const onEnd = () => fail(new Error("stdin ended before runtime bootstrap"));
    const onError = (error) => fail(error);
    const onData = (chunk) => {
      buffer += chunk;
      const newlineIndex = buffer.indexOf("\n");
      if (newlineIndex === -1) {
        if (buffer.length > MAX_BOOTSTRAP_LINE_LENGTH) {
          fail(new RangeError("runtime bootstrap exceeds size limit"));
        }
        return;
      }
      if (newlineIndex > MAX_BOOTSTRAP_LINE_LENGTH) {
        fail(new RangeError("runtime bootstrap exceeds size limit"));
        return;
      }
      cleanup();
      stream.pause();
      let line = buffer.slice(0, newlineIndex);
      if (line.endsWith("\r")) line = line.slice(0, -1);
      resolve({ line, remainder: buffer.slice(newlineIndex + 1) });
    };
    stream.on("data", onData);
    stream.once("end", onEnd);
    stream.once("error", onError);
    stream.resume();
  });
}

function emit(event) {
  try {
    process.stdout.write(`${JSON.stringify(event)}\n`);
  } catch (error) {
    process.stderr.write(`pi-runtime: event serialization failed (${errorKind(error)})\n`);
  }
}

scrubRuntimeEnvironment(process.env, RUNTIME_BOOTSTRAP_ENV_FIELDS);
let bootstrap;
try {
  bootstrap = await readBootstrapLine(process.stdin);
} catch (error) {
  process.stderr.write(`pi-runtime: bootstrap read failed (${errorKind(error)})\n`);
  process.exit(1);
}

let config;
try {
  config = parseRuntimeBootstrap(bootstrap.line, REQUIRED_STRING_BOOTSTRAP_FIELDS);
} catch (error) {
  process.stderr.write(`pi-runtime: bootstrap validation failed (${errorKind(error)})\n`);
  process.exit(1);
}

let hosted;
try {
  hosted = await createRuntimeSession(config, {
    emit,
    log: (line) => process.stderr.write(`${line}\n`),
  });
} catch (error) {
  const stage = typeof error?.runtimeStage === "string" ? error.runtimeStage : "bootstrap";
  process.stderr.write(`pi-runtime: ${stage} failed (${errorKind(error)})\n`);
  process.exit(1);
}

const decoder = new JsonLineDecoder();
function consumeCommandChunk(chunk) {
  let lines;
  try {
    lines = decoder.push(chunk);
  } catch (error) {
    process.stderr.write(`pi-runtime: stdin framing failed (${errorKind(error)})\n`);
    void shutdown(1);
    return;
  }
  for (let line of lines) {
    if (line.endsWith("\r")) line = line.slice(0, -1);
    if (!line.trim()) continue;
    try {
      hosted.command(JSON.parse(line));
    } catch (error) {
      emit({
        type: "response",
        id: null,
        command: "parse",
        success: false,
        error: error instanceof SyntaxError ? "Invalid JSON command" : "Runtime command rejected",
      });
    }
  }
}

process.stdin.on("data", consumeCommandChunk);
process.stdin.on("end", () => void shutdown(0));
process.stdin.on("error", (error) => {
  process.stderr.write(`pi-runtime: stdin failed (${errorKind(error)})\n`);
  void shutdown(1);
});
if (bootstrap.remainder.length > 0) consumeCommandChunk(bootstrap.remainder);
process.stdin.resume();

let shuttingDown = false;
async function shutdown(exitCode) {
  if (shuttingDown) return;
  shuttingDown = true;
  process.stdin.pause();
  let finalExitCode = exitCode;
  try {
    await hosted.stop();
  } catch (error) {
    finalExitCode = 1;
    process.stderr.write(`pi-runtime: shutdown failed (${errorKind(error)})\n`);
  }
  if (!(await waitForWritableFlush(process.stdout))) finalExitCode = 1;
  process.exit(finalExitCode);
}

process.on("SIGTERM", () => void shutdown(0));
process.on("SIGINT", () => void shutdown(0));
