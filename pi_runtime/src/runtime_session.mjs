import { performance } from "node:perf_hooks";

import {
  createAgentSession,
  DefaultResourceLoader,
  ModelRuntime,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { createProvider, InMemoryCredentialStore } from "@earendil-works/pi-ai";
import { anthropicMessagesApi } from "@earendil-works/pi-ai/api/anthropic-messages.lazy";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";
import { openAIResponsesApi } from "@earendil-works/pi-ai/api/openai-responses.lazy";

import { createPressroomExtension } from "./pressroom_extension.mjs";
import {
  abortWithSingleResponse,
  errorKind,
  errorMessage,
  normalizeLegacyMessages,
  parseModelCapabilities,
  parseProxyRequestBody,
  requireSuccessfulProxyResponse,
  toJsonEvent,
} from "./runtime_utils.mjs";

const INTERNAL_PROXY_KEY = "pi-runtime-internal";
const COMMAND_DRAIN_TIMEOUT_MS = 5_000;
const NATIVE_API = {
  openai_chat_completions: () => openAICompletionsApi(),
  openai_responses: () => openAIResponsesApi(),
  anthropic_messages: () => anthropicMessagesApi(),
};
const PROTOCOL_TO_API = {
  openai_chat_completions: "openai-completions",
  openai_responses: "openai-responses",
  anthropic_messages: "anthropic-messages",
};

export const REQUIRED_STRING_BOOTSTRAP_FIELDS = [
  "PI_PROVIDER_ID",
  "PI_MODEL_ID",
  "PI_API_PROTOCOL",
  "PI_PROXY_URL",
  "PI_PROXY_TOKEN",
  "PI_WORKSPACE_ROOT",
  "PI_SESSION_ID",
  "PI_AGENT_SESSION_ID",
  "PI_CHECKPOINT_DIR",
  "PI_TOOL_GATEWAY_URL",
  "PI_TOOL_GATEWAY_GRANT",
  "PI_TOOL_CATALOG_VERSION",
];

export const RUNTIME_BOOTSTRAP_ENV_FIELDS = [
  ...REQUIRED_STRING_BOOTSTRAP_FIELDS,
  "PI_MODEL_CONTEXT_WINDOW",
  "PI_MODEL_MAX_TOKENS",
  "PI_MODEL_REASONING",
  "PI_RUNTIME_GENERATION",
  "PI_CHECKPOINT_PATH",
  "PI_LEGACY_MESSAGES",
];

function staged(error, runtimeStage, reasonCode) {
  const wrapped = error instanceof Error ? error : new Error(String(error));
  wrapped.runtimeStage = runtimeStage;
  wrapped.reasonCode = reasonCode;
  return wrapped;
}

function elapsed(started) {
  return Math.round((performance.now() - started) * 10) / 10;
}

function buildProxyStreams(config, protocol, modelId) {
  const native = NATIVE_API[protocol]();
  const proxyFetch = async (_input, init = {}) => {
    let rawBody;
    try {
      rawBody = parseProxyRequestBody(init.body);
    } catch (error) {
      throw new Error(
        `pi-runtime: proxy body re-envelope failed (${errorKind(error)})`,
        { cause: error },
      );
    }
    const response = await globalThis.fetch(config.PI_PROXY_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-DocConv-Proxy-Token": config.PI_PROXY_TOKEN,
      },
      body: JSON.stringify({ model_id: modelId, api_protocol: protocol, payload: rawBody }),
      signal: init.signal ?? undefined,
    });
    return requireSuccessfulProxyResponse(response);
  };
  const withProxy = (options) => ({
    ...options,
    apiKey: INTERNAL_PROXY_KEY,
    fetch: proxyFetch,
  });
  return {
    stream: (model, context, options) => native.stream(model, context, withProxy(options)),
    streamSimple: (model, context, options) =>
      native.streamSimple(model, context, withProxy(options)),
  };
}

async function waitForDrain(pending, timeoutMs) {
  let timer;
  try {
    return await Promise.race([
      pending.then(() => true, () => true),
      new Promise((resolve) => {
        timer = setTimeout(() => resolve(false), timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Create one isolated logical AgentSession inside the long-lived Runtime host.
 * Pi modules are loaded once by the host; every attach still receives a fresh
 * ModelRuntime, ResourceLoader, SessionManager and AgentSession.
 */
export async function createRuntimeSession(config, { emit, log = () => undefined } = {}) {
  if (typeof emit !== "function") throw new TypeError("runtime event sink is required");
  const started = performance.now();
  const sessionId = config.PI_SESSION_ID;
  const emitEvent = (event) => emit(toJsonEvent(event));
  const mark = (stage, stageStarted) => {
    log(`pi-runtime: timing session=${sessionId} stage=${stage} duration_ms=${elapsed(stageStarted)} total_ms=${elapsed(started)}`);
  };

  const capabilityStarted = performance.now();
  let modelCapabilities;
  let runtimeGeneration;
  try {
    modelCapabilities = parseModelCapabilities(config);
    runtimeGeneration = Number(config.PI_RUNTIME_GENERATION);
    if (!Number.isSafeInteger(runtimeGeneration) || runtimeGeneration < 1) {
      throw new TypeError("runtime generation validation failed");
    }
  } catch (error) {
    throw staged(error, "bootstrap", "model_capability_invalid");
  }
  mark("validate", capabilityStarted);

  const model = {
    id: config.PI_MODEL_ID,
    name: config.PI_MODEL_ID,
    api: PROTOCOL_TO_API[config.PI_API_PROTOCOL],
    provider: "doc-conv-proxy",
    baseUrl: config.PI_PROXY_URL,
    reasoning: modelCapabilities.reasoning,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: modelCapabilities.contextWindow,
    maxTokens: modelCapabilities.maxTokens,
  };
  const provider = createProvider({
    id: "doc-conv-proxy",
    name: "Internal model proxy",
    baseUrl: config.PI_PROXY_URL,
    auth: {
      apiKey: {
        name: "Internal proxy (credentials stay server-side)",
        resolve: async () => ({
          auth: { apiKey: INTERNAL_PROXY_KEY },
          source: "internal-proxy",
        }),
      },
    },
    models: [model],
    api: buildProxyStreams(config, config.PI_API_PROTOCOL, config.PI_MODEL_ID),
  });

  const modelRuntimeStarted = performance.now();
  const modelRuntime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(),
    modelsPath: null,
    allowModelNetwork: false,
    refreshOnCreate: false,
  });
  modelRuntime.registerNativeProvider(provider);
  mark("model_runtime", modelRuntimeStarted);

  const resourceStarted = performance.now();
  const resourceLoader = new DefaultResourceLoader({
    cwd: config.PI_WORKSPACE_ROOT,
    agentDir: config.PI_WORKSPACE_ROOT,
    noExtensions: true,
    noSkills: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
    extensionFactories: [{
      name: "pressroom",
      hidden: true,
      factory: createPressroomExtension({
        gatewayUrl: config.PI_TOOL_GATEWAY_URL,
        gatewayGrant: config.PI_TOOL_GATEWAY_GRANT,
        catalogVersion: config.PI_TOOL_CATALOG_VERSION,
      }),
    }],
  });
  await resourceLoader.reload();
  mark("resource_loader", resourceStarted);

  const checkpointStarted = performance.now();
  let sessionManager;
  try {
    if (config.PI_CHECKPOINT_PATH) {
      if (config.PI_LEGACY_MESSAGES !== undefined) {
        throw new TypeError("checkpoint and legacy history are mutually exclusive");
      }
      sessionManager = SessionManager.open(
        config.PI_CHECKPOINT_PATH,
        config.PI_CHECKPOINT_DIR,
        config.PI_WORKSPACE_ROOT,
      );
    } else {
      sessionManager = SessionManager.create(
        config.PI_WORKSPACE_ROOT,
        config.PI_CHECKPOINT_DIR,
        { id: config.PI_AGENT_SESSION_ID },
      );
      for (const message of normalizeLegacyMessages(config.PI_LEGACY_MESSAGES)) {
        sessionManager.appendMessage(message);
      }
    }
    const checkpointRef = sessionManager.getSessionFile();
    if (typeof checkpointRef !== "string" || checkpointRef.length === 0) {
      throw new TypeError("durable checkpoint initialization failed");
    }
  } catch (error) {
    throw staged(error, "session_restore", "session_restore_failed");
  }
  const checkpointRef = sessionManager.getSessionFile();
  mark("checkpoint_open", checkpointStarted);

  const agentStarted = performance.now();
  const { session } = await createAgentSession({
    cwd: config.PI_WORKSPACE_ROOT,
    model,
    modelRuntime,
    resourceLoader,
    sessionManager,
    settingsManager: SettingsManager.inMemory(),
    noTools: "builtin",
    customTools: [],
  });
  mark("create_agent_session", agentStarted);

  const unsubscribe = session.subscribe(emitEvent);
  let commandQueue = Promise.resolve();
  let stopping = false;

  const respond = (id, command, success, error) => {
    const response = { type: "response", command, success };
    if (id !== undefined && id !== null) response.id = id;
    if (error !== undefined) response.error = error;
    emit(response);
  };

  const handlePrompt = (cmd) => new Promise((resolve) => {
    const { id } = cmd;
    let responded = false;
    let accepted = false;
    const once = (success, error) => {
      if (responded) return;
      responded = true;
      try {
        respond(id, "prompt", success, error);
      } finally {
        resolve();
      }
    };
    const options = {};
    if (cmd.streamingBehavior) options.streamingBehavior = cmd.streamingBehavior;
    options.preflightResult = (wasAccepted) => {
      accepted = wasAccepted;
      once(wasAccepted, wasAccepted ? undefined : "Prompt rejected");
    };
    session.prompt(cmd.message, options).catch((error) => {
      if (responded) {
        if (accepted) log(`pi-runtime: prompt failed after acceptance (${errorKind(error)})`);
        return;
      }
      once(false, errorMessage(error));
    });
  });

  const handleCommand = async (cmd) => {
    switch (cmd.type) {
      case "prompt":
        await handlePrompt(cmd);
        break;
      case "steer":
        await session.steer(cmd.message);
        respond(cmd.id, "steer", true);
        break;
      case "follow_up":
        await session.followUp(cmd.message);
        respond(cmd.id, "follow_up", true);
        break;
      case "abort":
        await abortWithSingleResponse(
          () => session.abort(),
          (success, error) => respond(cmd.id, "abort", success, error),
          (kind) => log(`pi-runtime: abort failed after acceptance (${kind})`),
        );
        break;
      default:
        respond(cmd.id, String(cmd.type ?? "unknown"), false, `Unknown command type: ${cmd.type}`);
    }
  };

  const command = (cmd) => {
    if (stopping) throw new Error("runtime session is stopping");
    commandQueue = commandQueue.then(async () => {
      try {
        await handleCommand(cmd);
      } catch (error) {
        try {
          respond(cmd?.id ?? null, String(cmd?.type ?? "unknown"), false, errorMessage(error));
        } catch (responseError) {
          log(`pi-runtime: command response failed (${errorKind(responseError)})`);
        }
      }
    });
  };

  const stop = async () => {
    if (stopping) return;
    stopping = true;
    let drained = await waitForDrain(commandQueue, COMMAND_DRAIN_TIMEOUT_MS);
    if (!drained) {
      log("pi-runtime: command drain timed out");
    }
    try {
      await session.abort();
    } catch (error) {
      log(`pi-runtime: shutdown abort failed (${errorKind(error)})`);
    }
    if (!drained) drained = await waitForDrain(commandQueue, COMMAND_DRAIN_TIMEOUT_MS);
    if (!drained) {
      log("pi-runtime: command drain remained blocked after abort");
    }
    try {
      if (typeof unsubscribe === "function") unsubscribe();
      session.dispose();
    } catch (error) {
      log(`pi-runtime: shutdown dispose failed (${errorKind(error)})`);
    }
  };

  log(`pi-runtime: session=${sessionId} provider=${config.PI_PROVIDER_ID} model=${config.PI_MODEL_ID}`);
  mark("ready", started);
  emit({
    type: "runtime_ready",
    checkpoint_ref: checkpointRef,
    checkpoint_schema_version: 3,
    runtime_generation: runtimeGeneration,
    restore_duration_ms: elapsed(started),
  });
  return {
    checkpointRef,
    checkpointSchemaVersion: 3,
    command,
    stop,
  };
}
