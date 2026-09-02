# Design: Pi Agent Chatbox V1

References: [proposal](./proposal.md); accepted decision `wiki/decisions/2026-08-14/pi-agent-chatbox-v1-boundaries.md`.

## Context

The repository already has a workspace-scoped Provider Store: encrypted credentials, model subresources, RBAC, and an SSRF-safe, no-redirect transport (`app/services/ssrf_transport.py`). Today it distinguishes only `openai_compatible` (with `api_style ∈ {openai, azure_openai}`) and `engine_service` Providers. That shape cannot represent OpenAI Responses or Anthropic Messages as first-class protocols.

Pi Agent and Pi Coding Agent (`@earendil-works/pi`) already define the agent lifecycle, message structure, tool execution lifecycle, retry/compaction behavior, and a documented `AgentSessionEvent` JSON vocabulary that the TUI consumes. The decision is to align the Web UI to that vocabulary rather than invent a parallel chat protocol, and to obtain the model from the existing Provider Store through an internal proxy so credentials stay server-side.

Stack constraints (from `AGENTS.md` and `wiki/`): FastAPI + SQLAlchemy/PostgreSQL backend with an encrypted SQLite Provider store and optional Celery; React + TypeScript + Vite + Ant Design frontend; production frontend bundles must not expose debug stores or unconditional console diagnostics; Provider credentials are decrypted only at invocation time and never enter logs, API responses, persisted traces, or workflow/node configuration; all external Provider calls go through the SSRF-safe transport with link-local and cloud-metadata destinations blocked.

## Goals / Non-Goals

**Goals:**

- A workspace-scoped bottom-right chatbox opened from a fixed launcher that preserves the active Pi session across open/close and across reconnect.
- A Node Pi runtime behind an authenticated FastAPI WebSocket boundary, consuming the Pi `AgentSessionEvent` JSON vocabulary as the UI source of truth.
- An internal model proxy that reuses the existing SSRF-safe transport and Provider credential decryption, supporting OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages.
- An additive `llm_api` Provider type with required `api_protocol` discriminator; existing Provider types and Azure behavior unchanged.
- A server-side readiness test that must pass before a Provider is marked chatbot-usable.
- A server-side browser security projection that strips non-TUI-visible or security-sensitive fields before events leave the backend.
- React renderers for the built-in Pi coding tools and TUI-visible lifecycle states.

**Non-Goals** (decision §10): Azure OpenAI Responses; Anthropic via Bedrock/Vertex; OAuth/workload identity; arbitrary headers / query params / OpenAI org-project headers; keyless local model endpoints; automatic model discovery; separate chat/coding models; per-user credentials or per-message model selection; multimodal file attachments; Provider-hosted tools/conversations; UI for advanced Pi compatibility flags; exact Web rendering of arbitrary Pi extension TUI components.

## Unknowns & Investigation

- **Exact Pi SDK version to pin.** The decision requires pinning `@earendil-works/pi` and defers `@earendil-works/pi-protocol`. Investigation at implementation time: read Pi's release notes and the `AgentSessionEvent` contract fixture coverage required by spec; pin the latest stable minor whose event shape matches the spec scenarios. Conclusion deferred to the implementation Task Group that adds the dependency, with the version recorded in the lockfile and in the contract-fixture provenance.
- **Embedded `AgentSession` vs Pi RPC mode.** Decision §3 permits either. Investigation: both produce the same JSON event payload over WebSocket; the chosen mode is the one with smaller lifecycle-management surface for our process model. Conclusion: implementation Task Group for the runtime launcher evaluates both and records the choice in code + a wiki note. The WebSocket payload contract is identical either way, so this does not block specs/tasks.
- **Whether any compatibility flag must be surfaced.** Decision §10 explicitly excludes UI controls for advanced compatibility flags. Conclusion: no UI; flags, if needed at all, are operator-only config outside V1 scope.
- **Whether existing Azure OpenAI code path can be reused for the internal proxy.** The `openai_compatible` + `azure_openai` adapter exists. Investigation: that path is closely tied to Chat Completions and Azure-specific auth, so the proxy should branch by `api_protocol` rather than overload the Azure path. Conclusion: separate proxy handlers per protocol, sharing only the SSRF transport and credential-resolution service.

## Decisions

### D1. Runtime topology

Adopt the boundary from decision §2 verbatim:

```
React Chatbox
  ↔ authenticated FastAPI chat / WebSocket boundary
  ↔ Node Pi Agent / Pi Coding Agent runtime
  ↔ internal FastAPI model proxy
  ↔ configured external model endpoint
```

- FastAPI is authoritative for browser auth, workspace RBAC, chatbot-session ownership, and Provider resolution.
- The Node runtime owns Pi Agent / Pi Coding Agent session execution and tool-lifecycle state. It receives a Provider identifier, model identifier, `api_protocol`, and the internal proxy address. It does **not** receive the external token or the external Provider URL.
- The internal model proxy decrypts credentials only for an authorized invocation and forwards the native protocol request through `app/services/sssr_transport.py`.
- Coding tools operate only inside the workspace root granted to the session. The host remains responsible for filesystem, process, and network restrictions; Pi supplies no sandbox of its own.

### D2. Pi events are the UI source of truth (no parallel protocol)

The WebSocket payload uses Pi's documented event names directly: `agent_start`, `agent_end`, `agent_settled`, `turn_start`, `turn_end`, `message_start`, `message_update`, `message_end`, `tool_execution_start`, `tool_execution_update`, `tool_execution_end`, `queue_update`, `compaction_start`, `compaction_end`, retry events, and supported extension UI requests. The application does **not** introduce `chat.delta`/`tool.started`/`chat.done` style aliases.

Streaming reconstruction rules (decision §3) are normative:

1. `message_start` creates the live message.
2. `message_update.assistantMessageEvent` updates the content block identified by `contentIndex`.
3. Text, thinking, and tool-call argument deltas preserve original block order.
4. `message_end.message` replaces the locally assembled message and is the authoritative final value.
5. `tool_execution_update.partialResult` is the accumulated result so far; the UI replaces the previous partial, not appends.
6. `agent_end` is a low-level run boundary that may be followed by retry, compaction, or queued work. Only `agent_settled` means fully idle.

Reconnect reloads authoritative state and messages first, then subscribes to new events. It does not reconstruct durable state from incomplete transient progress events.

### D3. Server-side browser security projection

The FastAPI boundary applies a visible-field projection on every outgoing event (decision §5). The browser must never receive:

- API tokens, authorization headers, decrypted credentials.
- Raw Provider diagnostics or upstream response bodies.
- Hidden custom messages (`display: false`).
- Unrendered tool-internal details.
- Host session-file / extension-source absolute paths.
- Paths outside the authorized workspace root.

Displayed filesystem paths are normalized to workspace-relative paths. This is a security projection of Pi events, not a second agent-state protocol — event names and visible semantics stay identical.

### D4. Provider type and protocol discriminator

Add an additive `llm_api` Provider type. `api_protocol` is **required** for `llm_api` and is one of `openai_chat_completions`, `openai_responses`, `anthropic_messages`. Existing `openai_compatible`, `engine_service`, `api_style`, and Azure behavior remain unchanged. One Provider configuration has exactly one protocol; if a service exposes both Chat Completions and Responses, the operator creates two Providers.

Form fields (decision §6): Provider display name, API protocol, Base URL, API token, Model ID, optional model display name, "make workspace chatbot default" option. Token is required on create; blank on edit means preserve. API responses expose only whether a credential exists (boolean), never the value.

### D5. URL and protocol contract (decision §7)

The user supplies a Base URL through the version prefix. The application strips a trailing slash and appends the protocol resource path:

| Protocol | Example Base URL | Resource appended |
| --- | --- | --- |
| OpenAI Chat Completions | `https://api.openai.com/v1` | `/chat/completions` |
| OpenAI Responses | `https://api.openai.com/v1` | `/responses` |
| Anthropic Messages | `https://api.anthropic.com/v1` | `/messages` |

The form rejects URLs with embedded credentials, query strings, fragments, or an already-appended resource path. Absolute `https` is expected for public services. Operator-controlled self-hosted deployments may use `http` under the existing Provider endpoint policy. Authentication per protocol (the literal `${TOKEN}` stands in for the decrypted credential value):

| Protocol | Authentication | Core request shape |
| --- | --- | --- |
| OpenAI Chat Completions | `Authorization: Bearer ${TOKEN}` | `messages`, streaming, function tools |
| OpenAI Responses | `Authorization: Bearer ${TOKEN}` | `input`, typed output, streaming, function tools |
| Anthropic Messages | `x-api-key: ${TOKEN}` and pinned `anthropic-version` | `messages`, `max_tokens`, streaming, tools |

V1 pins the Anthropic API version server-side. Users cannot enter arbitrary headers.

### D6. OpenAI Responses stateless boundary (decision §8)

Responses is a distinct protocol, not a Chat Completions feature flag. V1 sends `store: false` for OpenAI requests, keeps the durable conversation in the application/Pi session, and uses neither `previous_response_id` nor the Conversations API. Pi may replay opaque or encrypted Provider items required for stateless reasoning continuity; the application neither renders nor logs them. Only application-provided function tools are supported. Excluded: hosted web search, file search, computer use, code interpreter, remote MCP, background mode, and other Provider-managed agent features. A service claiming Responses compatibility must accept this stateless contract.

### D7. Model readiness test (decision §9)

Saving a Provider is not sufficient to mark it chatbot-usable. A server-side readiness test must verify the configured protocol and model:

1. A minimal non-streaming text response succeeds.
2. Streaming text succeeds and terminates correctly.
3. A forced, side-effect-free function-tool call is returned correctly.
4. A tool result can be submitted and followed by a final assistant response.
5. OpenAI endpoints accept `store: false`.
6. Cancellation and stream errors settle the Pi session correctly.

Listing models or HTTP 200 from a health endpoint is not an agent-readiness test. Model discovery is not required in V1; the administrator enters the Model ID explicitly.

### D8. TUI-visible rendering contract (decision §4)

The browser renders the same user-visible categories and ordering as the Pi Coding Agent TUI: user messages, Markdown, and supported images; assistant Markdown streamed in content-block order; provider-exposed thinking blocks with a visible/hidden toggle; tool calls and tool results inline at execution position; working / queued / compacting / retrying / aborted / truncated / error states; compaction and branch summaries; display-enabled custom messages and supported extension interaction requests; and model / thinking level / token / cache usage / cost / context-window status. Thinking output is limited to the explicit `thinking` blocks Pi emits — the application does not request, reconstruct, or display hidden chain-of-thought.

V1 supplies React renderers for the built-in coding tools (`read`, `bash`, `edit`, `write`, `grep`, `find`, `ls`). Tool cards mirror TUI lifecycle (pending / success / error). Result bodies are collapsed by default with global and per-tool expansion. Unknown tools fall back to tool name + JSON arguments + text/image results. Pi extension renderers return terminal components and cannot be executed as React components; exact parity is therefore out of V1 unless an extension also supplies a Web renderer.

## Risks / Trade-offs

- **Risk**: Pi SDK upgrade breaks the event contract. → Mitigation: pin the SDK version; add a contract-fixture suite (acceptance criterion 8) covering text streaming, thinking, multi-tool execution, partial output, failure, abort, retry, compaction, and `agent_settled`. Upgrade = fixture review.
- **Risk**: The browser security projection drifts from the TUI-visible set and either leaks internal details or hides TUI-visible state. → Mitigation: projection is implemented as a single allow-list keyed by event type, exercised by the same contract-fixture suite; the projection rules are documented in `wiki/` when implementation lands.
- **Risk**: A self-hosted "OpenAI-compatible" endpoint passes URL validation but fails the readiness test, leaving users confused. → Mitigation: readiness result is surfaced verbatim in the Provider form with the failing step named; only Providers that pass are selectable as the chatbot default.
- **Risk**: Bidirectional WebSocket transport is required (prompting, steering, abort, extension interaction) and adds a new server attack surface. → Mitigation: WebSocket path requires authenticated workspace session; events flow through the same projection; coding-tool workspace root enforced server-side.
- **Risk**: OpenAI's Responses `store: false` and Conversations-API exclusion may surprise services that depend on `previous_response_id`. → Mitigation: documented as a hard V1 contract; services that cannot accept it fail readiness and cannot be selected.
- **Trade-off**: Coupling the Web renderer to the pinned Pi event contract reduces protocol flexibility in exchange for parity and one shared state machine. Accepted per decision §3 and §alternatives.

## Data Model

The Provider schema gains an additive `llm_api` path. There is no destructive migration.

- `provider_type`: enum gains value `llm_api`. Existing values (`openai_compatible`, `engine_service`) unchanged.
- `api_protocol`: nullable enum column; **required** when `provider_type = llm_api`; values `openai_chat_completions`, `openai_responses`, `anthropic_messages`. Null for non-`llm_api` Providers.
- `base_url`: existing column; same validation as today, plus the protocol-aware resource-append rule from D5.
- `model_id`: existing column; required for `llm_api` (no discovery in V1).
- `model_display_name`: existing optional column; reused.
- `is_chatbot_default`: new workspace-scoped boolean flag (at most one `llm_api` Provider per workspace is the default; enforced server-side).
- Credentials: existing encrypted store; `llm_api` Providers store one token. Edit-with-blank-token preserves the existing credential (existing pattern). API responses expose only `has_credential: bool`.

Chatbot session ownership is owned by FastAPI and persisted in PostgreSQL (new table for chatbot sessions: workspace id, user id, Pi session handle, created/updated timestamps, lifecycle state). Pi-internal session files live on the Node runtime host and are never exposed.

## API Contracts

### `GET /api/providers/{provider_id}` (modified)

Adds `provider_type = "llm_api"`, `api_protocol` (when applicable), `model_id`, `model_display_name`, `is_chatbot_default`, and `has_credential: bool`. Never returns the token. No breaking change for existing Provider shapes.

### `POST /api/providers` and `PATCH /api/providers/{provider_id}` (modified)

Accepts `provider_type = "llm_api"` with required `api_protocol`, `base_url`, `model_id`, and `token` (required on create; blank-on-edit means preserve). Form-level URL validation per D5.

### `POST /api/providers/{provider_id}/readiness-test` (new)

Triggers the server-side readiness probe (D7). Returns a structured result: per-step status, failure detail at the step level (no upstream body), and a boolean `chatbot_ready`. Idempotent; safe to re-run after a config change.

### `WebSocket /api/chatbox/sessions/{session_id}` (new)

Authenticated, workspace-scoped. Bidirectional. Outbound frames are Pi `AgentSessionEvent` JSON after the D3 projection. Inbound frames carry RPC commands (prompt, steer, abort, extension interaction) using Pi's documented correlation identifiers. The path identifies the chatbot session; no second application envelope is added around Pi payloads.

### `POST /api/chatbox/sessions` (new)

Creates a chatbot session bound to the workspace default `llm_api` Provider (or a chosen `llm_api` Provider if multiple exist). Returns `session_id` and authoritative initial state. Reconnect reloads authoritative state and messages before subscribing to new events.

### `GET /api/chatbox/sessions/{session_id}` (new)

Returns authoritative session state and message history for reconnect.

### Internal model proxy (new, not browser-facing)

Server-side HTTP target used by the Node Pi runtime. Resolves Provider credentials per invocation, forwards the native protocol request through the SSRF-safe transport, and returns the upstream response stream. Never receives or returns credentials. Reuses `app/services/sssr_transport.py` link-local/metadata blocking and no-redirect behavior.

## Migration Plan

1. Backend additive schema migration for `provider_type`, `api_protocol`, `is_chatbot_default`, and the chatbot-session table. Existing rows need no changes.
2. Ship `llm_api` Provider CRUD + readiness test behind existing RBAC; no chatbox UI yet.
3. Ship the Node Pi runtime launcher, internal model proxy, and WebSocket boundary.
4. Ship the React chatbox shell, Pi event assembler, and built-in tool renderers.
5. Ship the contract-fixture suite and public-boundary checks.
6. Rollback: the new endpoints and the chatbox feature flag are disabled; existing Provider behavior is unchanged because the schema change is additive.

## Deferred Implementation Decisions

The following are not unresolved design questions; they are deliberate deferrals, each scoped to a Task Group with a recorded outcome:

- **Pinned `@earendil-works/pi` version** — resolved at the dependency-add Task Group (4.1); the version is recorded in the lockfile and in a `wiki/` provenance note.
- **Embedded `AgentSession` vs Pi RPC mode** — resolved at the runtime-launcher Task Group (4.2); the choice and rationale are documented in code and a `wiki/` note. The WebSocket payload contract is identical either way.
- **Workspace-root grant mechanism for the Node runtime** — resolved at the runtime-launcher Task Group (4.4); must satisfy "tools operate only inside the granted workspace root"; documented in a `wiki/` note.
