#!/usr/bin/env node
// Isolated Pi Runtime control plane. It exposes a narrow authenticated HTTP
// protocol and hosts isolated logical AgentSessions in one long-lived process.

import { timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";
import { basename, isAbsolute, relative, resolve } from "node:path";

import { parseRuntimeBootstrap } from "./runtime_utils.mjs";

const HOST = process.env.PI_RUNTIME_HOST ?? "0.0.0.0";
const PORT = Number(process.env.PI_RUNTIME_PORT ?? "8080");
const CONTROL_TOKEN = process.env.PI_RUNTIME_CONTROL_TOKEN ?? "";
const CHECKPOINT_ROOT = resolve(process.env.PI_RUNTIME_CHECKPOINT_ROOT ?? "/var/lib/pressroom-agent-sessions");
const MAX_BODY_BYTES = 1_048_576;
const MAX_SESSIONS = Number(process.env.PI_RUNTIME_MAX_SESSIONS ?? "16");
const EVENT_LIMIT = 5_000;
const LONG_POLL_MS = 20_000;
const SESSION_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;
const sessions = new Map();
let runtimeModulePromise;

if (!CONTROL_TOKEN || !Number.isSafeInteger(PORT) || PORT < 1 || PORT > 65_535) {
  process.stderr.write("pi-runtime-server: invalid required configuration\n");
  process.exit(1);
}

function authenticated(request) {
  const supplied = request.headers["x-pi-runtime-control"];
  if (typeof supplied !== "string") return false;
  const actual = Buffer.from(supplied);
  const expected = Buffer.from(CONTROL_TOKEN);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

function json(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
  });
  response.end(body);
}

async function readJson(request) {
  let size = 0;
  const chunks = [];
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) throw new RangeError("request body exceeds size limit");
    chunks.push(chunk);
  }
  const parsed = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new TypeError("request body must be an object");
  }
  return parsed;
}

function checkpointPath(value) {
  if (typeof value !== "string" || !value || !isAbsolute(value)) {
    throw new TypeError("checkpoint path must be absolute");
  }
  const candidate = resolve(value);
  const rel = relative(CHECKPOINT_ROOT, candidate);
  if (rel === "" || rel.startsWith("..") || isAbsolute(rel)) {
    throw new RangeError("checkpoint path escaped runtime boundary");
  }
  return candidate;
}

class RuntimeSession {
  constructor(bootstrap) {
    this.id = bootstrap.PI_SESSION_ID;
    this.bootstrap = { ...bootstrap };
    this.events = [];
    this.sequence = 0;
    this.waiters = new Set();
    this.hosted = null;
    this.state = "starting";
  }

  async start() {
    const checkpointDir = checkpointPath(this.bootstrap.PI_CHECKPOINT_DIR);
    if (
      typeof this.bootstrap.PI_AGENT_SESSION_ID !== "string"
      || !SESSION_ID_PATTERN.test(this.bootstrap.PI_AGENT_SESSION_ID)
      || basename(checkpointDir) !== this.bootstrap.PI_AGENT_SESSION_ID
    ) {
      throw new RangeError("checkpoint directory does not belong to the Agent Session");
    }
    if (this.bootstrap.PI_CHECKPOINT_PATH !== undefined) {
      this.bootstrap.PI_CHECKPOINT_PATH = checkpointPath(this.bootstrap.PI_CHECKPOINT_PATH);
    }
    // Runtime cwd is its private checkpoint directory. The backend-provided
    // workspace value is ignored so the logical session cannot acquire a
    // platform workspace mount.
    this.bootstrap.PI_WORKSPACE_ROOT = checkpointDir;
    const { createRuntimeSession, REQUIRED_STRING_BOOTSTRAP_FIELDS } = await runtimeModulePromise;
    const validated = parseRuntimeBootstrap(
      JSON.stringify(this.bootstrap),
      REQUIRED_STRING_BOOTSTRAP_FIELDS,
    );
    this.hosted = await createRuntimeSession(validated, {
      emit: (event) => this.push(event),
      log: (line) => process.stderr.write(`${line}\n`),
    });
    this.state = "running";
    return this.hosted;
  }

  push(event) {
    this.sequence += 1;
    this.events.push({ sequence: this.sequence, event });
    if (this.events.length > EVENT_LIMIT) this.events.splice(0, this.events.length - EVENT_LIMIT);
    this.wake();
  }

  wake() {
    for (const waiter of this.waiters) waiter();
    this.waiters.clear();
  }

  async poll(after) {
    const available = () => this.events.filter((item) => item.sequence > after);
    let items = available();
    if (items.length === 0 && this.state === "running") {
      await new Promise((resolveWait) => {
        const timer = setTimeout(() => {
          this.waiters.delete(done);
          resolveWait();
        }, LONG_POLL_MS);
        const done = () => {
          clearTimeout(timer);
          resolveWait();
        };
        this.waiters.add(done);
      });
      items = available();
    }
    return { items, state: this.state, last_sequence: this.sequence };
  }

  command(command) {
    if (this.state !== "running" || this.hosted === null) {
      throw new Error("runtime session is not running");
    }
    const payload = JSON.stringify(command);
    if (Buffer.byteLength(payload) > MAX_BODY_BYTES) throw new RangeError("command exceeds size limit");
    this.hosted.command(command);
  }

  async stop() {
    if (this.state === "stopped" || this.state === "dead") return;
    this.state = "stopping";
    try {
      await this.hosted?.stop();
      this.state = "stopped";
    } catch (error) {
      this.state = "dead";
      throw error;
    } finally {
      this.hosted = null;
      this.wake();
    }
  }
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url ?? "/", `http://${request.headers.host ?? "runtime"}`);
    if (request.method === "GET" && url.pathname === "/health") {
      json(response, 200, { status: "healthy", sessions: sessions.size });
      return;
    }
    if (!authenticated(request)) {
      json(response, 401, { error: "unauthorized" });
      return;
    }
    if (request.method === "POST" && url.pathname === "/v1/sessions") {
      if (sessions.size >= MAX_SESSIONS) {
        json(response, 429, { error: "runtime capacity reached" });
        return;
      }
      const bootstrap = await readJson(request);
      if (
        typeof bootstrap.PI_SESSION_ID !== "string"
        || !SESSION_ID_PATTERN.test(bootstrap.PI_SESSION_ID)
        || sessions.has(bootstrap.PI_SESSION_ID)
      ) {
        json(response, 409, { error: "invalid or duplicate runtime session" });
        return;
      }
      const runtime = new RuntimeSession(bootstrap);
      sessions.set(runtime.id, runtime);
      try {
        const ready = await runtime.start();
        json(response, 201, {
          session_id: runtime.id,
          checkpoint_ref: ready.checkpointRef,
          checkpoint_schema_version: ready.checkpointSchemaVersion,
          runtime_generation: runtime.bootstrap.PI_RUNTIME_GENERATION,
        });
      } catch (error) {
        await runtime.stop();
        sessions.delete(runtime.id);
        throw error;
      }
      return;
    }
    const match = url.pathname.match(/^\/v1\/sessions\/([A-Za-z0-9_-]+)(?:\/(events|commands))?$/);
    if (!match) {
      json(response, 404, { error: "not found" });
      return;
    }
    const runtime = sessions.get(match[1]);
    if (!runtime) {
      json(response, 404, { error: "runtime session not found" });
      return;
    }
    if (request.method === "GET" && match[2] === "events") {
      const after = Number(url.searchParams.get("after") ?? "0");
      if (!Number.isSafeInteger(after) || after < 0) throw new TypeError("invalid event cursor");
      json(response, 200, await runtime.poll(after));
      return;
    }
    if (request.method === "POST" && match[2] === "commands") {
      runtime.command(await readJson(request));
      json(response, 202, { accepted: true });
      return;
    }
    if (request.method === "DELETE" && match[2] === undefined) {
      await runtime.stop();
      sessions.delete(runtime.id);
      json(response, 200, { stopped: true });
      return;
    }
    json(response, 405, { error: "method not allowed" });
  } catch (error) {
    const stage = typeof error?.runtimeStage === "string" ? error.runtimeStage : "request_validation";
    const reasonCode = typeof error?.reasonCode === "string" ? error.reasonCode : "invalid_runtime_request";
    process.stderr.write(
      `pi-runtime-server: request failed type=${error?.constructor?.name ?? "Error"} stage=${stage} reason=${reasonCode}\n`,
    );
    if (!response.headersSent) {
      json(response, 400, {
        error: "invalid runtime request",
        stage,
        reason_code: reasonCode,
      });
    }
    else response.end();
  }
});

async function shutdown() {
  server.close();
  await Promise.allSettled([...sessions.values()].map((runtime) => runtime.stop()));
  process.exit(0);
}

server.listen(PORT, HOST, () => {
  process.stderr.write(`pi-runtime-server: listening port=${PORT}\n`);
  // Begin loading Pi as soon as the control plane is reachable. The cached
  // module and SDK graph are reused by every later logical session attach.
  runtimeModulePromise = import("./runtime_session.mjs");
  runtimeModulePromise.catch((error) => {
    process.stderr.write(`pi-runtime-server: runtime preload failed type=${error?.constructor?.name ?? "Error"}\n`);
  });
});
process.on("SIGTERM", () => void shutdown());
process.on("SIGINT", () => void shutdown());
