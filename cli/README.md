# PressRoom CLI

`pr` is the machine-readable business-tool CLI used by the Document Conversion
platform's managed Tool Executor. The platform-hosted Agent proposes structured
tool calls; the Executor supplies the fixed Agent Session context, enforces file
access and confirmation policy, and starts `pr`. The model never receives the
session Token and cannot select another host, workspace, or Agent Session.

The CLI has no second role system. Every request is authorized again by the
platform using the short-lived Agent Session Token, live workspace membership,
capability checks, resource ownership, and current business state.

## Install

From a source checkout:

```console
python -m pip install ./cli
pr --version
```

The package installs both `pr` and `pressroom`. POSIX systems commonly already
provide `/usr/bin/pr` as a text-pagination utility. The product command remains
`pr`; `pressroom` is the unambiguous fallback when PATH order cannot be
controlled.

## Managed execution context

When an Agent Session is created or resumed, the platform authenticates the
browser user, verifies access to the selected workspace and Session, and issues
a short-lived Agent Session Token. The controlled Executor exposes the following
context to `pr`:

```text
PRESSROOM_HOST=https://platform.example
PRESSROOM_WORKSPACE_ID=ws_123
PRESSROOM_AGENT_SESSION_ID=ags_456
PRESSROOM_TOKEN_FILE=/run/secrets/agent-session-token
PRESSROOM_ALLOWED_FILE_ROOTS=/session/attachments:/session/artifacts
```

`PRESSROOM_TOKEN_FILE` must be an absolute path. `pr` reads it for every HTTP
request so the Executor can rotate the Token without exposing it to the model or
persisting it in a profile. Allowed file roots are platform-selected directories
that constrain all CLI reads, uploads, and downloads. The separator follows the
host operating system (`:` on POSIX and `;` on Windows).

HTTPS is required. `PRESSROOM_ALLOW_INSECURE_HTTP=true` exists only for isolated
development environments. `--host`, `--base-url`, `--workspace`, and `--profile`
are rejected because managed Session context cannot be overridden by a tool
call. There are no public auth, profile, workspace-selection, doctor, or command
discovery subcommands.

## Tool discovery and approval

The Tool Executor reads the packaged `tool-catalog.yaml` directly. It exposes
only entries with `status: cli-ready` and uses `exposure` to distinguish:

- `agent-default`: available without a separate high-impact confirmation;
- `agent-confirmation`: requires explicit user approval through the platform.

The Executor's approval record is the platform control. `--yes` is only a CLI
mechanism for controlled invocation and manual testing; it is not proof of user
approval and never bypasses backend authorization. Deferred catalog entries are
not installed as CLI commands.

## Core flow

```console
pr file upload --file /session/attachments/source.pdf --json
pr workflow list --json
pr workflow execute WORKFLOW_ID --file-id FILE_ID --yes --json
pr run wait RUN_ID --json
pr run results RUN_ID --json
pr run download RUN_ID RESULT_ID --output /session/artifacts/result.md --json
```

Workflow, Run, Test Set, Ground Truth, Evaluation, Provider, Engine, and node
discovery commands are grouped by domain under `pr --help`. Binary responses
require `--output`; an existing file is replaced only with `--force`. Local wait
timeouts never cancel the remote operation.

## Machine contract

With `--json`, stdout contains one `pressroom-envelope.v1` document. Exit codes
are stable: `0` success, `2` usage, `3` authentication, `4` authorization, `5`
not found, `6` conflict, `7` validation, `8` local I/O, `9` wait timeout, `10`
network/TLS, `11` platform or upstream failure, and `12` partial batch success.
Provider and Engine diagnostics may return an informative successful envelope
with exit `11` when the reported domain status is unhealthy or unavailable.

The P0 CLI deliberately excludes Agent Session lifecycle, workspace/member
governance, Provider secrets and mutation, workflow API keys, audit/trace
export, evaluation accept/reject, Adaptor Test Case operations, direct Engine
processing, and non-durable advanced Run reset/node rerun controls.
