import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { mkdtemp, mkdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const SERVER_ENTRYPOINT = fileURLToPath(new URL("../src/server.mjs", import.meta.url));

async function unusedPort() {
  const probe = createServer();
  await new Promise((resolveListen, rejectListen) => {
    probe.once("error", rejectListen);
    probe.listen(0, "127.0.0.1", resolveListen);
  });
  const address = probe.address();
  assert.equal(typeof address, "object");
  const port = address.port;
  await new Promise((resolveClose) => probe.close(resolveClose));
  return port;
}

async function startRuntimeServer(t, checkpointRoot) {
  const port = await unusedPort();
  const child = spawn(process.execPath, [SERVER_ENTRYPOINT], {
    env: {
      PATH: process.env.PATH ?? "",
      PI_RUNTIME_HOST: "127.0.0.1",
      PI_RUNTIME_PORT: String(port),
      PI_RUNTIME_CONTROL_TOKEN: "runtime-control-test-token",
      PI_RUNTIME_CHECKPOINT_ROOT: checkpointRoot,
    },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let stderr = "";
  await new Promise((resolveReady, rejectReady) => {
    const timer = setTimeout(() => rejectReady(new Error(`server startup timed out: ${stderr}`)), 5_000);
    child.once("error", (error) => {
      clearTimeout(timer);
      rejectReady(error);
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
      if (stderr.includes("pi-runtime-server: listening")) {
        clearTimeout(timer);
        resolveReady();
      }
    });
  });
  t.after(async () => {
    if (child.exitCode === null) child.kill("SIGTERM");
    await new Promise((resolveExit) => {
      if (child.exitCode !== null) resolveExit();
      else child.once("exit", resolveExit);
    });
  });
  return `http://127.0.0.1:${port}`;
}

test("runtime control service authenticates requests and rejects escaped checkpoints", async (t) => {
  const checkpointRoot = await mkdtemp(join(tmpdir(), "pressroom-runtime-server-"));
  t.after(() => rm(checkpointRoot, { recursive: true, force: true }));
  const serviceUrl = await startRuntimeServer(t, checkpointRoot);

  const health = await fetch(`${serviceUrl}/health`);
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), { status: "healthy", sessions: 0 });

  const unauthorized = await fetch(`${serviceUrl}/v1/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ PI_SESSION_ID: "runtime-a" }),
  });
  assert.equal(unauthorized.status, 401);

  const escaped = await fetch(`${serviceUrl}/v1/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Pi-Runtime-Control": "runtime-control-test-token",
    },
    body: JSON.stringify({
      PI_SESSION_ID: "runtime-a",
      PI_AGENT_SESSION_ID: "agent-a",
      PI_CHECKPOINT_DIR: resolve(checkpointRoot, "..", "escaped", "agent-a"),
    }),
  });
  assert.equal(escaped.status, 400);

  const mismatched = await fetch(`${serviceUrl}/v1/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Pi-Runtime-Control": "runtime-control-test-token",
    },
    body: JSON.stringify({
      PI_SESSION_ID: "runtime-b",
      PI_AGENT_SESSION_ID: "agent-b",
      PI_CHECKPOINT_DIR: join(checkpointRoot, "workspace-a", "different-agent"),
    }),
  });
  assert.equal(mismatched.status, 400);

  const finalHealth = await fetch(`${serviceUrl}/health`);
  assert.deepEqual(await finalHealth.json(), { status: "healthy", sessions: 0 });
});

test("runtime control service seeds a durable checkpoint from bounded legacy history", async (t) => {
  const checkpointRoot = await mkdtemp(join(tmpdir(), "pressroom-runtime-bootstrap-"));
  t.after(() => rm(checkpointRoot, { recursive: true, force: true }));
  const serviceUrl = await startRuntimeServer(t, checkpointRoot);
  const checkpointDir = join(checkpointRoot, "workspace-a", "agent-legacy");
  await mkdir(checkpointDir, { recursive: true });

  const response = await fetch(`${serviceUrl}/v1/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Pi-Runtime-Control": "runtime-control-test-token",
    },
    body: JSON.stringify({
      PI_PROVIDER_ID: "provider-a",
      PI_MODEL_ID: "model-a",
      PI_MODEL_CONTEXT_WINDOW: 32_000,
      PI_MODEL_MAX_TOKENS: 4_096,
      PI_MODEL_REASONING: false,
      PI_API_PROTOCOL: "anthropic_messages",
      PI_PROXY_URL: "http://backend.invalid/internal/proxy/invoke/provider-a",
      PI_PROXY_TOKEN: "private-proxy-grant",
      PI_WORKSPACE_ROOT: checkpointDir,
      PI_SESSION_ID: "runtime-legacy",
      PI_AGENT_SESSION_ID: "agent-legacy",
      PI_RUNTIME_GENERATION: 1,
      PI_CHECKPOINT_DIR: checkpointDir,
      PI_TOOL_GATEWAY_URL: "http://backend.invalid/internal/agent-tools/execute",
      PI_TOOL_GATEWAY_GRANT: "private-tool-grant",
      PI_TOOL_CATALOG_VERSION: "0.1",
      PI_LEGACY_MESSAGES: [
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
          content: [{ type: "text", text: "I will remember alpha." }],
          usage: {
            input: 1,
            output: 1,
            cacheRead: 0,
            cacheWrite: 0,
            totalTokens: 2,
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
          },
          stopReason: "stop",
          timestamp: 2,
        },
      ],
    }),
  });

  assert.equal(response.status, 201);
  const payload = await response.json();
  const checkpoint = await readFile(payload.checkpoint_ref, "utf8");
  assert.match(checkpoint, /Remember alpha/);
  assert.doesNotMatch(checkpoint, /browser-user-id|browser-assistant-id/);

  const stopped = await fetch(`${serviceUrl}/v1/sessions/runtime-legacy`, {
    method: "DELETE",
    headers: { "X-Pi-Runtime-Control": "runtime-control-test-token" },
  });
  assert.equal(stopped.status, 200);
});

test("runtime control service reports a safe restore stage for malformed legacy history", async (t) => {
  const checkpointRoot = await mkdtemp(join(tmpdir(), "pressroom-runtime-reject-"));
  t.after(() => rm(checkpointRoot, { recursive: true, force: true }));
  const serviceUrl = await startRuntimeServer(t, checkpointRoot);
  const checkpointDir = join(checkpointRoot, "workspace-a", "agent-invalid");
  await mkdir(checkpointDir, { recursive: true });

  const response = await fetch(`${serviceUrl}/v1/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Pi-Runtime-Control": "runtime-control-test-token",
    },
    body: JSON.stringify({
      PI_PROVIDER_ID: "provider-a",
      PI_MODEL_ID: "model-a",
      PI_MODEL_CONTEXT_WINDOW: 32_000,
      PI_MODEL_MAX_TOKENS: 4_096,
      PI_MODEL_REASONING: false,
      PI_API_PROTOCOL: "anthropic_messages",
      PI_PROXY_URL: "http://backend.invalid/internal/proxy/invoke/provider-a",
      PI_PROXY_TOKEN: "private-proxy-grant",
      PI_WORKSPACE_ROOT: checkpointDir,
      PI_SESSION_ID: "runtime-invalid",
      PI_AGENT_SESSION_ID: "agent-invalid",
      PI_RUNTIME_GENERATION: 1,
      PI_CHECKPOINT_DIR: checkpointDir,
      PI_TOOL_GATEWAY_URL: "http://backend.invalid/internal/agent-tools/execute",
      PI_TOOL_GATEWAY_GRANT: "private-tool-grant",
      PI_TOOL_CATALOG_VERSION: "0.1",
      PI_LEGACY_MESSAGES: [{ role: "system", content: "not allowed", timestamp: 1 }],
    }),
  });

  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), {
    error: "invalid runtime request",
    stage: "session_restore",
    reason_code: "session_restore_failed",
  });
});
