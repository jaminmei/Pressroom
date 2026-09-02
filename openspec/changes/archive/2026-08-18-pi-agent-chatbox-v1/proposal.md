# Proposal: Pi Agent Chatbox V1

Source decision: `wiki/decisions/2026-08-14/pi-agent-chatbox-v1-boundaries.md` (status: accepted).

## Why

The product lacks an in-application assistant. Users must leave the document-conversion UI to ask questions or perform coding-oriented work, and the repository's existing Provider Store (encrypted credentials, workspace RBAC, SSRF-safe transport) only models OpenAI-compatible and engine-service Providers, so it cannot represent OpenAI Responses or Anthropic Messages cleanly. V1 introduces a workspace-scoped chatbot backed by Pi Agent / Pi Coding Agent, with the model selected from the existing Provider Store, so that an authenticated user can drive a single agent session without exposing model credentials to the browser or duplicating the Provider boundary.

## What Changes

- Add a fixed bottom-right launcher that opens a workspace-scoped chatbox panel preserving the active Pi session across open/close and across reconnect. The panel reuses the existing React / TypeScript / Ant Design stack.
- Add a Node-based Pi runtime (`@earendil-works/pi` Agent + Coding Agent) behind an authenticated FastAPI WebSocket boundary. The browser consumes Pi's documented `AgentSessionEvent` JSON event vocabulary directly; no second application-specific chat protocol is introduced.
- Add an internal FastAPI model proxy that resolves and decrypts Provider credentials per invocation and forwards the selected native protocol (OpenAI Chat Completions, OpenAI Responses, or Anthropic Messages) through the existing SSRF-safe, no-redirect transport. The Pi runtime and browser never receive model credentials.
- Add a new `llm_api` Provider type with a required `api_protocol` discriminator (`openai_chat_completions` | `openai_responses` | `anthropic_messages`). Existing `openai_compatible`, `engine_service`, `api_style`, and Azure behavior remain unchanged. One Provider configuration represents exactly one protocol.
- Add a server-side model readiness test that must pass before a Provider is marked usable by the chatbot: non-streaming response, streaming termination, forced function-tool call, tool-result round-trip, OpenAI `store: false` acceptance, and clean settle on cancellation / stream error.
- Add React renderers for the built-in Pi coding tools (`read`, `bash`, `edit`, `write`, `grep`, `find`, `ls`) and the TUI-visible lifecycle states (working, queued, compacting, retrying, aborted, truncated, error), matching Pi Coding Agent's visible ordering.
- Add a server-side browser security projection that strips tokens, raw upstream bodies, hidden custom messages, tool-internal details, absolute session/extension paths, and any path outside the authorized workspace root before events leave the FastAPI boundary. Displayed filesystem paths are normalized to workspace-relative paths.
- Pin OpenAI Responses to a stateless contract: `store: false`, no `previous_response_id`, no Conversations API, no Provider-hosted tools (web search, file search, computer use, code interpreter, remote MCP, background mode). Application + Pi session state remain authoritative.

Non-goals (V1) — see decision §10: Azure OpenAI Responses, Anthropic via Bedrock/Vertex, OAuth/workload identity, arbitrary headers, keyless local endpoints, model discovery, separate chat/coding models, per-user credentials, multimodal file attachments, Provider-hosted conversations, UI for advanced compatibility flags, and exact Web rendering of arbitrary extension TUI components.

## Capabilities

### New Capabilities

- `chatbox-shell`: Workspace-scoped bottom-right launcher and conversation panel, active session preservation across open/close and reconnect, single workspace-default model, no per-message model picker.
- `pi-agent-runtime`: Node Pi Agent / Pi Coding Agent runtime behind an authenticated FastAPI WebSocket; Pi `AgentSessionEvent` JSON as the UI source of truth; internal model proxy; server-side browser security projection; workspace-rooted tool execution.
- `llm-api-provider`: New `llm_api` Provider type with required `api_protocol`; URL/protocol contract; credential preservation semantics; OpenAI Responses stateless boundary (`store: false`, no Provider-owned conversations).
- `model-readiness-test`: Server-side readiness probe required before a Provider is marked chatbot-usable; covers streaming, function-tool round-trip, `store: false`, and cancellation/stream-error settle.

### Modified Capabilities

_None._ No `openspec/specs/` exist yet; this change introduces the first specs. Existing `openai_compatible` / `engine_service` / `api_style` / Azure behavior is explicitly preserved unchanged.

## Impact

- **Backend (`app/`)**: new WebSocket chat endpoint(s); new internal model proxy that reuses `app/services/ssrf_transport.py` and Provider credential decryption; new readiness test orchestrator; `app/providers/models.py`, `app/providers/auth.py` extended additively for `llm_api` / `api_protocol`; new Node runtime launcher / lifecycle manager. No destructive migration of existing Providers.
- **Provider Store**: additive schema change (`provider_type = llm_api`, `api_protocol` enum). Existing records and existing API styles continue to work.
- **Frontend (`frontend/src/`)**: new chatbox feature module under `frontend/src/features/`; Pi event stream assembler / state machine; React renderers for built-in coding tools and lifecycle states; new `llm_api` form branch in `AddProviderDialog.tsx`; `frontend/src/types/provider.ts` extended. Production bundle must continue to honor the no-debug-store / no-unconditional-console-diagnostics rule.
- **Security invariants**: extends the existing SSRF/no-redirect transport and logging restrictions; new browser-facing projection rule. Provider credentials continue to never enter workflow/node configuration, logs, API responses, or persisted traces.
- **Verification**: backend Ruff/mypy/pytest; frontend ESLint/TypeScript/Vitest/production build; new Pi-event contract fixture suite covering text streaming, thinking, multi-tool execution, partial output, failure, abort, retry, compaction, and `agent_settled`; new readiness-test fixtures per protocol; `scripts/check-public-boundary.py --include-untracked` before handoff.
- **Dependencies**: pins a `@earendil-works/pi` SDK version (exact version chosen at implementation time; `pi-protocol` deferred per decision §alternatives).
- **Docs / wiki**: durable update to `wiki/architecture/` for the chatbox runtime boundary, the Provider protocol extension, and the readiness test, added when implementation lands.

## GitHub Issue

<!-- This change is `trackingProvider: none`. No GitHub Issue will be created. -->
