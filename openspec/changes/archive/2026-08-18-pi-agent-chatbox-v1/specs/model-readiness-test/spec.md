# Spec: model-readiness-test

Capability: server-side readiness probe required before an `llm_api` Provider is marked chatbot-usable.

Source: [proposal](../../proposal.md); accepted decision `wiki/decisions/2026-08-14/pi-agent-chatbox-v1-boundaries.md` §9.

## ADDED Requirements

### Requirement: Server-side readiness test before chatbot usability
A `llm_api` Provider SHALL NOT be marked usable by the chatbot until a server-side readiness test passes. Saving a Provider SHALL NOT be sufficient to mark it usable.

#### Scenario: Saved Provider is not chatbot-ready by default
- **WHEN** an operator saves a new `llm_api` Provider without running the readiness test
- **THEN** the Provider is persisted but its `chatbot_ready` state is false and it cannot be selected as the workspace default

### Requirement: Readiness test sequence
The readiness test SHALL verify, in order: (1) a minimal non-streaming text response succeeds; (2) streaming text succeeds and terminates correctly; (3) a forced, side-effect-free function-tool call is returned correctly; (4) a tool result can be submitted and followed by a final assistant response; (5) for OpenAI endpoints, `store: false` is accepted; and (6) cancellation and stream errors settle the Pi session correctly.

#### Scenario: All steps pass
- **WHEN** the readiness test runs against a correctly configured `llm_api` Provider
- **THEN** every step succeeds, `chatbot_ready` becomes true, and the Provider becomes selectable as the workspace default

#### Scenario: Streaming termination failure fails readiness
- **WHEN** the readiness test reaches step 2 and the streaming response does not terminate correctly
- **THEN** `chatbot_ready` remains false and the result names step 2 as the failing step

#### Scenario: Tool round-trip failure fails readiness
- **WHEN** the readiness test reaches step 3 or step 4 and the function-tool call or tool-result submission fails
- **THEN** `chatbot_ready` remains false and the result names the failing step

#### Scenario: store=false rejection fails readiness for OpenAI
- **WHEN** an OpenAI endpoint rejects `store: false`
- **THEN** `chatbot_ready` remains false at step 5 with the rejection reported as the failure

#### Scenario: Cancellation and stream errors must settle
- **WHEN** the readiness test reaches step 6 and a cancellation or stream error leaves the Pi session in a non-settled state
- **THEN** `chatbot_ready` remains false with step 6 named as the failing step

### Requirement: Listing models or HTTP 200 is not a readiness test
Listing models or receiving HTTP 200 from a health endpoint SHALL NOT be considered an agent-readiness test.

#### Scenario: Health endpoint 200 does not mark ready
- **WHEN** the readiness test is replaced or shortcut by a `GET /models` call or a health-endpoint HTTP 200
- **THEN** `chatbot_ready` remains false because these checks do not satisfy the readiness sequence

### Requirement: Model discovery is not required; model id is explicit
The readiness test SHALL NOT depend on automatic model discovery. The operator SHALL enter the Model ID explicitly when configuring the Provider.

#### Scenario: No model discovery step
- **WHEN** the operator configures a `llm_api` Provider
- **THEN** they enter the Model ID explicitly and the readiness test runs against that Model ID without any discovery step

### Requirement: Readiness result is structured and surfacable
The readiness test SHALL return a structured result with per-step status and a step-level failure detail that excludes upstream response bodies. The result SHALL be safe to surface in the Provider form.

#### Scenario: Failure detail excludes upstream body
- **WHEN** a step fails because the upstream returned an error body
- **THEN** the readiness result names the failing step and a sanitized failure reason, and never includes the raw upstream response body

#### Scenario: Result surfaces in the Provider form
- **WHEN** an operator runs the readiness test from the Provider form
- **THEN** the form displays the per-step status and the failing step verbatim, and only Providers that pass become selectable as the chatbot default
