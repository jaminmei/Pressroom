<!-- Task Groups (## headings) are checkpoint units mirrored in one GitHub Issue dashboard. Apply executes one group at a time. -->

## 1. llm_api Provider schema and CRUD

- [x] 1.1 Add additive Provider schema: extend `provider_type` enum with `llm_api`; add nullable `api_protocol` enum (`openai_chat_completions` | `openai_responses` | `anthropic_messages`) required when `provider_type = llm_api`; add `model_id`, optional `model_display_name`, and workspace-scoped `is_chatbot_default` boolean. Backend Alembic migration is additive; existing rows unchanged.
- [x] 1.2 Server-side invariant: at most one `llm_api` Provider per workspace is `is_chatbot_default`; clearing the previous default on write. Unit-test the invariant.
- [x] 1.3 Extend `app/providers/models.py` and `app/providers/auth.py` additively for `llm_api` / `api_protocol`. Existing `openai_compatible`, `engine_service`, `api_style`, and Azure code paths unchanged.
- [x] 1.4 Extend `POST /api/providers` and `PATCH /api/providers/{provider_id}`: accept `provider_type = llm_api` with required `api_protocol`, `base_url`, `model_id`, and `token`. Token required on create; blank on edit preserves the existing credential.
- [x] 1.5 Extend `GET /api/providers/{provider_id}`: return `provider_type`, `api_protocol`, `model_id`, `model_display_name`, `is_chatbot_default`, and `has_credential: bool`. Never return the token.
- [x] 1.6 Form-level Base URL validation: strip trailing slash; reject URLs with embedded credentials, query strings, fragments, or already-appended resource path (`/chat/completions`, `/responses`, `/messages`); require absolute `https` for public services and allow `http` only under the existing Provider endpoint policy. Unit-test every rejected URL shape.
- [x] 1.7 Backend pytest coverage for CRUD, the unique-default invariant, credential preservation on edit, and URL validation. Ruff + mypy clean.
- [x] 1.8 Frontend: add the `llm_api` branch to `AddProviderDialog.tsx` with the form fields from spec (display name, API protocol, Base URL, API token, Model ID, optional model display name, "make workspace chatbot default"); extend `frontend/src/types/provider.ts`. ESLint, TypeScript, Vitest, and production build pass.

- [x] 1.9 Repair (review rejection): update `tests/unit/test_provider_workspace_migration.py::test_old_row_remains_legacy_when_v5_migrates` to assert the final `PRAGMA user_version` is 8 (the v7 llm_api and v8 chatbot_ready migrations extend the full upgrade path past 6); rerun `tests/unit/test_provider_workspace_migration.py` and the provider regression selection green.
- [x] 1.10 Repair (QA BUG-001): make the `llm_api` form branch reachable in the UI — add a Provider Type selector (OpenAI-compatible | LLM API) to `AddProviderDialog.tsx` create mode for multi-type sections (vlm), switching between the existing branches; Vitest coverage must drive the branch through the selector (not prop injection).
- [x] 1.11 Repair (QA BUG-002): return 422 (sanitized) instead of 500 when llm_api create/update validation fails — handle `ModelProviderCreate`/`ModelProviderUpdate` ValidationError at `app/api/providers.py` create/update handlers; pytest asserts llm_api create and PUT without `api_key` return 422.

## 2. Model readiness test

- [x] 2.1 Add `POST /api/providers/{provider_id}/readiness-test` endpoint (authenticated, workspace-RBAC). Returns structured per-step result and `chatbot_ready: bool`. Idempotent; safe to re-run after a config change.
- [x] 2.2 Implement step orchestration in order: (1) minimal non-streaming text response; (2) streaming text terminates correctly; (3) forced side-effect-free function-tool call returned correctly; (4) tool result submitted, followed by a final assistant response; (5) for OpenAI endpoints, `store: false` accepted; (6) cancellation and stream errors settle the Pi session.
- [x] 2.3 Sanitize failure detail at the step level: never include the upstream response body, tokens, or Provider diagnostics in the returned result.
- [x] 2.4 Reject any shortcut path: a `GET /models` call or a health-endpoint HTTP 200 SHALL NOT set `chatbot_ready = true`. Assert this in tests.
- [x] 2.5 Persist `chatbot_ready` state on the Provider; only Providers with `chatbot_ready = true` are selectable as the workspace default.
- [x] 2.6 Backend pytest with mocked upstreams per protocol (success path, streaming-termination failure, tool round-trip failure, `store: false` rejection, non-settling cancellation). Ruff + mypy clean.
- [x] 2.7 Frontend: surface per-step readiness status and the failing step in `AddProviderDialog.tsx`; only passing Providers become selectable as the chatbot default. Vitest coverage for the success and named-failure render states.

## 3. Internal model proxy and SSRF reuse

- [x] 3.1 Add an internal HTTP proxy target (server-side only; not browser-facing) that the Node Pi runtime will call. Accepts a Provider identifier, model identifier, `api_protocol`, and the invocation payload.
- [x] 3.2 Reuse `app/services/ssrf_transport.py` for all upstream calls: no redirects; link-local and cloud-metadata destinations blocked; same logging restrictions as non-chatbot Provider calls (no prompt, document content, secret, authorization header, or upstream response body in logs).
- [x] 3.3 Per-protocol request shaping per design D5: OpenAI Chat Completions (`Authorization: Bearer`, `messages`, streaming, function tools); OpenAI Responses (`Authorization: Bearer`, `input`, typed output, streaming, function tools, `store: false`, no `previous_response_id`, no Conversations API, only application-provided function tools); Anthropic Messages (`x-api-key`, server-pinned `anthropic-version`, `messages`, `max_tokens`, streaming, tools).
- [x] 3.4 Decrypt credentials only for an authorized invocation, in memory, never logged or persisted beyond the invocation.
- [x] 3.5 Backend pytest with mocked upstreams verifying per-protocol request shape, header set, `store: false`, SSRF blocking, and no-redirect behavior. Ruff + mypy clean.

## 4. Node Pi runtime launcher and lifecycle

- [x] 4.1 Pin a `@earendil-works/pi` SDK version; record the version in the lockfile and in a `wiki/` note provenance entry. Defer `@earendil-works/pi-protocol` per decision §alternatives.
- [x] 4.2 Decide and implement the runtime mode (embedded `AgentSession` or Pi RPC mode) with the smallest lifecycle-management surface for our process model; document the choice in code and a `wiki/` note.
- [x] 4.3 Runtime provisioning: the FastAPI boundary passes the Provider id, model id, `api_protocol`, and internal proxy address; never passes the external token or external Provider URL.
- [x] 4.4 Workspace-root grant: enforce that coding tools operate only inside the granted workspace root via host-level filesystem restrictions; do not rely on Pi for a sandbox. Document the enforcement mechanism in a `wiki/` note.
- [x] 4.5 Lifecycle: start, supervise, and clean up Pi sessions; ensure cancellation and stream errors settle the session to `agent_settled`.
- [x] 4.6 Integration test: runtime starts, executes one streamed exchange through the internal proxy against a mocked upstream, and settles to `agent_settled`.
- [x] 4.7 Repair (QA BUG-004): make the Pi runtime startable inside the backend image — `Dockerfile.backend` installs Node.js (version consistent with `pi_runtime/package.json`), COPYs `pi_runtime/` and runs its production install, and the runtime path is resolvable by `app/services/pi_runtime.py` at container runtime; add an image-level check (CI or integration step) asserting the backend image contains node and `pi_runtime/node_modules` so the deployment gap cannot regress silently.

## 5. Authenticated WebSocket boundary and Pi event projection

- [x] 5.1 Add `POST /api/chatbox/sessions` (creates a chatbot session bound to the workspace default or a chosen `llm_api` Provider) and `GET /api/chatbox/sessions/{session_id}` (authoritative state + message history for reconnect).
- [x] 5.2 Add `WebSocket /api/chatbox/sessions/{session_id}`: authenticated, workspace-scoped, bidirectional. Inbound frames use Pi RPC command correlation identifiers (prompt, steer, abort, extension interaction); the path identifies the session, so frames carry no second application envelope.
- [x] 5.3 Outbound projection (design D3): strip API tokens, authorization headers, decrypted credentials, raw Provider diagnostics, upstream response bodies, hidden custom messages (`display: false`), unrendered tool-internal details, host session-file/extension-source absolute paths, and any path outside the authorized workspace root. Normalize displayed filesystem paths to workspace-relative.
- [x] 5.4 Reconnect protocol: client first reloads authoritative state via `GET /api/chatbox/sessions/{session_id}`, then subscribes to new events; transient progress events are not used to reconstruct durable state.
- [x] 5.5 Backend pytest verifying projection removal across event types (message, tool execution, custom message with `display: false`, absolute path, out-of-workspace path). Ruff + mypy clean.

## 6. React chatbox shell and Pi event assembler

- [x] 6.1 Add a new chatbox feature module under `frontend/src/features/` with a fixed bottom-right launcher shown only on authenticated, workspace-active, chatbot-enabled pages; hidden without an authenticated workspace session.
- [x] 6.2 Compact conversation panel on wide viewports; drawer / full-height surface on narrow viewports; preserves workspace identity and the active Pi session across open/close.
- [x] 6.3 Pi event assembler implementing the streaming reconstruction rules: `message_start` creates the live message; `message_update.assistantMessageEvent` updates the block at `contentIndex`; text/thinking/tool-call argument deltas preserve block order; `message_end.message` replaces the assembled message authoritatively; `tool_execution_update.partialResult` replaces the previous partial; `agent_end` is a low-level run boundary, only `agent_settled` means idle.
- [x] 6.4 Reconnect flow on the client: reload authoritative state and messages first, then subscribe; discard stale cached transient progress.
- [x] 6.5 Built on existing React + TypeScript + Ant Design; renderer registry pluggable per Pi event/tool type. No per-message model picker; uses the workspace default `llm_api` Provider only.
- [x] 6.6 Production bundle: no debug store, no unconditional console diagnostics. Vitest coverage for the assembler rules and the launcher visibility logic. ESLint, TypeScript, and production build pass.
- [x] 6.7 Repair (QA BUG-003): make the chatbox WebSocket reachable through the frontend proxy — fix `useChatboxSession.ts` to build the `/api`-prefixed backend route (`/api/chatbox/sessions/{id}`), add an nginx location with WebSocket upgrade headers (proxy_set_header Upgrade / Connection "upgrade") covering that path in `frontend/nginx.conf`, and add coverage asserting the URL contract (unit assertion on the built URL plus a Playwright e2e connecting through the proxy).

## 7. Built-in coding-tool renderers and TUI lifecycle parity

- [x] 7.1 React renderers for `read` (path, range, content, image, truncation), `bash` (command, live output, duration, exit status, cancellation), `edit` (path, preview, unified diff, result), `write` (path, content preview, result), and `grep`/`find`/`ls` (query, result, truncation).
- [x] 7.2 Tool cards distinguish pending / success / error; result bodies collapsed by default with global and per-tool expansion.
- [x] 7.3 Unknown-tool fallback: render tool name + JSON arguments + text/image result. Pi extension terminal components are never executed as React components.
- [x] 7.4 TUI-visible lifecycle and category parity: working, queued, compacting, retrying, aborted, truncated, error; assistant Markdown in content-block order; thinking blocks with a visible/hidden toggle (no hidden chain-of-thought reconstruction); compaction and branch summaries; model/thinking level/token/cache usage/cost/context-window status.
- [x] 7.5 Vitest coverage for each renderer and for the unknown-tool fallback. ESLint, TypeScript, and production build pass.

## 8. Pi event contract fixture suite

- [x] 8.1 Build a fixture set covering streaming text, thinking, multi-tool execution, partial output, failure, abort, retry, compaction, and `agent_settled`. Provenance recorded (Pi SDK version, source links).
- [x] 8.2 Frontend contract tests assert the assembler reconstructs each fixture correctly.
- [x] 8.3 Backend projection tests assert each fixture, after projection, contains no disallowed field (tokens, upstream bodies, hidden custom messages, absolute host paths, out-of-workspace paths).
- [x] 8.4 Wire the contract suite into CI; document the upgrade procedure (fixture review on Pi SDK version bump) in `wiki/`.

## 9. Public boundary, verification, and docs

- [x] 9.1 Run `python3 scripts/check-public-boundary.py --include-untracked`; resolve any finding introduced by this change (no credentials, private endpoints, runtime data, or unapproved binary assets in the public clone).
- [x] 9.2 Backend: Ruff, mypy, focused pytest over touched code paths.
- [x] 9.3 Frontend: ESLint, TypeScript, Vitest, production build.
- [x] 9.4 Update durable `wiki/architecture/` pages for the chatbox runtime boundary, the `llm_api` Provider protocol extension, and the readiness test; no session transcripts, local paths, endpoints, credentials, or internal-only details added.
- [x] 9.5 Verify existing `openai_compatible`, `engine_service`, `api_style`, and Azure Provider behavior remains intact (no regression in the existing Provider test suite).
