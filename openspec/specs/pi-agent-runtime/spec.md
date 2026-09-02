# pi-agent-runtime Specification

## Purpose
TBD - created by archiving change pi-agent-chatbox-v1. Update Purpose after archive.
## Requirements
### Requirement: Runtime topology with FastAPI as authoritative boundary
The chatbox runtime SHALL follow the topology: React Chatbox ↔ authenticated FastAPI WebSocket boundary ↔ Node Pi Agent/Pi Coding Agent runtime ↔ internal FastAPI model proxy ↔ configured external model endpoint. FastAPI SHALL remain authoritative for browser authentication, workspace RBAC, chatbot-session ownership, and Provider resolution.

#### Scenario: Browser never reaches external model endpoint
- **WHEN** the browser dispatches a chat action
- **THEN** the request flows through the authenticated FastAPI WebSocket boundary and the Node Pi runtime to the internal model proxy, and the browser never obtains the external Provider URL or token

### Requirement: Node runtime owns Pi session execution without credentials
The Node Pi runtime SHALL own Pi Agent / Pi Coding Agent session execution and tool-lifecycle state. It SHALL receive only a Provider identifier, model identifier, `api_protocol`, and the internal proxy address. It SHALL NOT receive the external token or the external Provider URL.

#### Scenario: Runtime is provisioned with proxy address, not credentials
- **WHEN** the FastAPI boundary starts a Pi session for a chatbot request
- **THEN** it passes the Provider id, model id, `api_protocol`, and internal proxy address to the Node runtime and passes no external token or external URL

### Requirement: Internal model proxy uses SSRF-safe transport and per-invocation credential decryption
The internal model proxy SHALL resolve and decrypt Provider credentials only for an authorized invocation and SHALL forward the selected native protocol through the existing SSRF-safe, no-redirect transport that blocks link-local and cloud-metadata destinations.

#### Scenario: Credentials decrypted only at invocation
- **WHEN** an authorized Pi invocation requires a Provider call
- **THEN** the internal proxy decrypts the credential in memory for that invocation, forwards the native request through the SSRF-safe no-redirect transport, and never persists or logs the decrypted credential

#### Scenario: Link-local and cloud-metadata destinations remain blocked
- **WHEN** a configured Provider endpoint resolves to a link-local address or a cloud-metadata destination
- **THEN** the internal proxy blocks the request via the existing SSRF transport, identical to non-chatbot Provider calls

### Requirement: Pi AgentSessionEvent JSON is the UI source of truth
Outbound WebSocket payloads SHALL use Pi's documented `AgentSessionEvent` JSON event names directly. The system SHALL NOT introduce alternate event names such as `chat.delta`, `tool.started`, or `chat.done`.

#### Scenario: Event names match Pi vocabulary
- **WHEN** the runtime emits a streaming message event, a tool execution event, or a session lifecycle event
- **THEN** the WebSocket frame uses the corresponding Pi event name from `message_start`/`message_update`/`message_end`, `tool_execution_start`/`tool_execution_update`/`tool_execution_end`, `agent_start`/`agent_end`/`agent_settled`, `turn_start`/`turn_end`, `queue_update`, `compaction_start`/`compaction_end`, retry events, and supported extension UI requests

### Requirement: Streaming reconstruction follows Pi block ordering
The chatbox SHALL reconstruct streamed messages using the Pi rules: `message_start` creates the live message; `message_update.assistantMessageEvent` updates the content block at `contentIndex`; text, thinking, and tool-call argument deltas preserve original block order; `message_end.message` replaces the locally assembled message as the authoritative final value; `tool_execution_update.partialResult` is the accumulated result so far and replaces the previous partial rather than appending.

#### Scenario: message_end replaces assembled message
- **WHEN** a `message_end.message` frame arrives
- **THEN** the chatbox replaces the locally assembled message with the frame's `message` value as authoritative

#### Scenario: tool partial results replace, not append
- **WHEN** successive `tool_execution_update.partialResult` frames arrive for the same tool execution
- **THEN** each frame's `partialResult` replaces the previously displayed accumulated result

### Requirement: agent_settled is the only fully-idle signal
The chatbox SHALL treat `agent_end` as a low-level run boundary that may be followed by retry, compaction, or queued work. Only `agent_settled` SHALL be treated as "session fully idle."

#### Scenario: Idle indicator follows agent_settled only
- **WHEN** the runtime emits `agent_end` followed by a retry event
- **THEN** the chatbox continues to display the active session and only marks the session idle after `agent_settled`

### Requirement: Reconnect reloads authoritative state before subscribing
On WebSocket reconnect, the client SHALL reload authoritative state and message history first and then subscribe to new events. It SHALL NOT attempt to reconstruct durable state from an incomplete set of transient progress events.

#### Scenario: Reconnect restores authoritative history
- **WHEN** the WebSocket reconnects after a disconnect
- **THEN** the client first loads authoritative session state and message history via the session REST endpoint, then subscribes to new events, and discards any stale locally cached transient progress

### Requirement: Server-side browser security projection
Before any event leaves the FastAPI WebSocket boundary, the server SHALL strip: API tokens, authorization headers, decrypted credentials; raw Provider diagnostics or upstream response bodies; hidden custom messages with `display: false`; unrendered tool-internal details; host session-file and extension-source absolute paths; and any path outside the authorized workspace root. Displayed filesystem paths SHALL be normalized to workspace-relative paths.

#### Scenario: Tokens never leave the boundary
- **WHEN** any event would carry an API token, authorization header, or decrypted credential
- **THEN** the projection removes it before the frame is sent to the browser

#### Scenario: Hidden custom messages are dropped
- **WHEN** a Pi custom message event with `display: false` is emitted
- **THEN** the projection drops the event and the browser never receives it

#### Scenario: Absolute session paths normalized
- **WHEN** an event references a host session-file or extension-source absolute path
- **THEN** the projection either drops the path or rewrites it to a workspace-relative path, and the browser never sees the absolute host path

#### Scenario: Out-of-workspace paths blocked
- **WHEN** an event references a filesystem path outside the authorized workspace root
- **THEN** the projection drops the reference and the browser never receives the absolute path

### Requirement: Coding tools operate only inside the granted workspace root
Coding tools SHALL operate only inside the workspace root granted to the session. Filesystem, process, and network restrictions SHALL remain host responsibilities; the system SHALL NOT rely on Pi to provide a security sandbox.

#### Scenario: Tool execution confined to workspace root
- **WHEN** a coding tool attempts to access a path outside the granted workspace root
- **THEN** the host workspace-root enforcement prevents the access and the tool execution reports failure without leaking the out-of-workspace absolute path

### Requirement: React renderers for built-in coding tools and TUI lifecycle
The chatbox SHALL provide React renderers for the built-in Pi coding tools: `read` (path, range, content, image, truncation state), `bash` (command, live output, duration, exit status, cancellation), `edit` (path, preview, unified diff, result), `write` (path, content preview, result), and `grep`, `find`, `ls` (query, result, truncation state). Tool cards SHALL distinguish pending, success, and error states and SHALL collapse result bodies by default with global and per-tool expansion.

#### Scenario: bash tool renders lifecycle
- **WHEN** a `bash` tool execution streams output and then completes with an exit status
- **THEN** the renderer shows the command, the accumulated live output, the duration, the exit status, and a collapsed-by-default result body that can be expanded globally or per tool

#### Scenario: Unknown tool falls back
- **WHEN** a tool execution arrives for a tool without a registered React renderer
- **THEN** the chatbox renders the tool name, JSON arguments, and any text/image result, without executing a Pi extension terminal component

### Requirement: TUI-visible categories and ordering
The chatbox SHALL render the same user-visible categories and ordering as the Pi Coding Agent TUI: user messages, Markdown, and supported images; assistant Markdown streamed in content-block order; provider-exposed thinking blocks with a visible/hidden toggle; tool calls and tool results inline at execution position; working, queued, compacting, retrying, aborted, truncated, and error states; compaction and branch summaries when present; display-enabled custom messages and supported extension interaction requests; and model, thinking level, token/cache usage, cost, and context-window status.

#### Scenario: Thinking blocks toggle
- **WHEN** an assistant message includes an explicit `thinking` block emitted by Pi
- **THEN** the chatbox renders the block with a visible/hidden toggle and never requests, reconstructs, or displays hidden chain-of-thought

### Requirement: Bidirectional WebSocket supports prompt, steer, abort, and extension interaction
The WebSocket transport SHALL be bidirectional and SHALL support prompting, steering, aborting, and supported extension interaction requests using Pi's documented RPC command correlation identifiers. The authenticated WebSocket path SHALL identify the chatbot session, so Pi event payloads SHALL NOT carry a second application envelope.

#### Scenario: Abort in-flight turn
- **WHEN** the user issues an abort command during an active turn
- **THEN** the runtime cancels the in-flight turn and the session settles cleanly to `agent_settled`

### Requirement: Pi event contract fixture coverage
A contract test suite SHALL cover Pi event fixtures for streaming text, thinking, multi-tool execution, partial output, failure, abort, retry, compaction, and `agent_settled`. The browser security projection SHALL be exercised by the same suite.

#### Scenario: Contract suite covers all named cases
- **WHEN** the contract suite runs in CI
- **THEN** it exercises fixture-driven cases for streaming text, thinking, multi-tool execution, partial output, failure, abort, retry, compaction, and `agent_settled`, and asserts the projection removes every disallowed field
