# llm-api-provider Specification

## Purpose
TBD - created by archiving change pi-agent-chatbox-v1. Update Purpose after archive.
## Requirements
### Requirement: Additive llm_api Provider type with required api_protocol
The Provider Store SHALL gain an additive `provider_type = "llm_api"` that requires an `api_protocol` discriminator of `openai_chat_completions`, `openai_responses`, or `anthropic_messages`. Existing `openai_compatible`, `engine_service`, `api_style`, and Azure behavior SHALL remain unchanged.

#### Scenario: llm_api requires api_protocol
- **WHEN** a Provider is created with `provider_type = "llm_api"` and no `api_protocol`
- **THEN** the request is rejected with a validation error

#### Scenario: Existing Provider types unchanged
- **WHEN** an existing `openai_compatible` or `engine_service` Provider is read or written
- **THEN** its behavior, `api_style`, and Azure semantics are identical to before this change

### Requirement: One Provider configuration represents exactly one protocol
One Provider configuration SHALL represent exactly one wire protocol. If the same service exposes both Chat Completions and Responses, the operator SHALL create two Provider configurations.

#### Scenario: Two protocols require two Providers
- **WHEN** an operator wants to use both OpenAI Chat Completions and OpenAI Responses against the same upstream service
- **THEN** they configure two separate `llm_api` Providers, each with its own `api_protocol`

### Requirement: Provider form fields and credential preservation semantics
The user-facing form for an `llm_api` Provider SHALL collect: display name, API protocol, Base URL, API token, Model ID, optional model display name, and an option to make the model the workspace chatbot default. The token SHALL be required on create. On edit, a blank token SHALL preserve the existing credential. API responses SHALL expose only whether a credential exists, never the credential value.

#### Scenario: Create requires token
- **WHEN** a Provider is created without a token
- **THEN** the request is rejected

#### Scenario: Blank token on edit preserves credential
- **WHEN** a Provider is edited with a blank token field
- **THEN** the stored credential is preserved unchanged

#### Scenario: API never returns the token
- **WHEN** any Provider is read via the API
- **THEN** the response includes `has_credential: bool` and never includes the token value

### Requirement: Base URL validation and protocol resource append
The application SHALL strip a trailing slash from the user-supplied Base URL and append the protocol resource path: `/chat/completions` for OpenAI Chat Completions, `/responses` for OpenAI Responses, and `/messages` for Anthropic Messages. The form SHALL reject Base URLs with embedded credentials, query strings, fragments, or an already-appended resource path. Absolute `https` SHALL be expected for public services; operator-controlled self-hosted deployments MAY use `http` under the existing Provider endpoint policy. The selected protocol SHALL determine authentication and request format; it SHALL NOT be auto-detected from the URL.

#### Scenario: Trailing slash stripped and resource appended
- **WHEN** an operator saves a Provider with Base URL `https://api.openai.com/v1/` and `api_protocol = openai_chat_completions`
- **THEN** the stored Base URL is normalized to `https://api.openai.com/v1` and outgoing requests target `https://api.openai.com/v1/chat/completions`

#### Scenario: URLs with embedded credentials rejected
- **WHEN** the operator enters a Base URL containing userinfo, a query string, a fragment, or an already-appended resource path
- **THEN** the form rejects the URL with a validation error before save

#### Scenario: Protocol is not auto-detected
- **WHEN** an operator selects `api_protocol = openai_responses` against `https://api.openai.com/v1`
- **THEN** outgoing requests use the OpenAI Responses request shape regardless of URL appearance

### Requirement: Per-protocol authentication and request shape
The selected `api_protocol` SHALL determine authentication and request shape: OpenAI Chat Completions uses `Authorization: Bearer ${TOKEN}` with `messages`, streaming, and function tools; OpenAI Responses uses `Authorization: Bearer ${TOKEN}` with `input`, typed output, streaming, and function tools; Anthropic Messages uses `x-api-key: ${TOKEN}` with a server-pinned `anthropic-version`, `messages`, `max_tokens`, streaming, and tools. V1 SHALL pin the supported Anthropic API version server-side and SHALL NOT allow arbitrary user-supplied headers. `${TOKEN}` is a placeholder for the decrypted credential value at invocation time.

#### Scenario: Anthropic version pinned server-side
- **WHEN** an `anthropic_messages` Provider is invoked
- **THEN** the request includes a server-pinned `anthropic-version` header and the operator cannot override it with a custom header

### Requirement: OpenAI Responses stateless boundary
For OpenAI Responses, the system SHALL send `store: false`, SHALL keep the durable conversation in the application/Pi session, SHALL NOT use `previous_response_id` or the Conversations API, MAY permit Pi to replay opaque or encrypted Provider items required for stateless reasoning continuity without rendering or logging them, SHALL support only application-provided function tools, and SHALL exclude hosted web search, file search, computer use, code interpreter, remote MCP, background mode, and other Provider-managed agent features. A service claiming Responses compatibility SHALL accept this stateless contract.

#### Scenario: store=false is always sent
- **WHEN** an `openai_responses` Provider is invoked
- **THEN** the outgoing request includes `store: false`

#### Scenario: No previous_response_id or Conversations API
- **WHEN** an `openai_responses` Provider is invoked across multiple turns
- **THEN** no request carries `previous_response_id` and no Conversations API endpoint is used; durable state stays in the application/Pi session

#### Scenario: Hosted Provider tools excluded
- **WHEN** an `openai_responses` Provider is configured for the chatbox
- **THEN** the request shape excludes hosted web search, file search, computer use, code interpreter, remote MCP, and background mode

### Requirement: Workspace-default chatbot model selection
At most one `llm_api` Provider per workspace SHALL be marked `is_chatbot_default`. The server SHALL enforce this invariant on writes.

#### Scenario: Default is unique per workspace
- **WHEN** an operator marks a second `llm_api` Provider as the workspace default
- **THEN** the server clears the previous default so that exactly one `llm_api` Provider remains the workspace chatbot default
