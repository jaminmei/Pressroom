---
title: Security and troubleshooting
description: Apply the PressRoom deployment baseline, protect Providers and public inputs, understand workspace RBAC, and diagnose issues without leaking sensitive data.
---

# Security and troubleshooting

PressRoom processes untrusted files and can call operator-configured services. Treat identity, workspace isolation, network destinations, credentials, logs, and retained results as one security boundary—not independent conveniences.

## Deployment baseline

Apply every item before exposing PressRoom beyond a trusted development machine:

- Replace every required `.env.example` placeholder with an independent secret.
- Enforce workspace RBAC. Stock Compose hard-codes `WORKSPACE_RBAC_ENFORCED=true`; preserve the same invariant in custom deployments.
- Terminate HTTPS and set `AUTH_SESSION_SECURE=true`.
- Allow only the intended frontend origin in backend CORS configuration.
- Keep `PROVIDER_ENCRYPTION_KEY` stable, private, and shared only by backend and worker.
- Set `PROVIDER_ALLOW_PRIVATE_HOSTS=false` for untrusted multi-tenant deployments unless private Provider routing is explicitly required.
- Keep public URL fetching private-host access disabled.
- Restrict backend, PostgreSQL, Redis, and engine ports with host and network controls.
- Keep TLS verification enabled for Provider calls unless your reviewed trust model requires otherwise.
- Back up PostgreSQL and shared storage together, and protect the encryption key separately.

## Workspace access control

Public deployments enforce workspace RBAC in the backend and worker.

| Operation | Roles |
| --- | --- |
| View workflows, Databases, Ground Truth, runs, and Providers | Owner, Admin, Editor, Runner, Viewer |
| Create/edit workflows and Databases; upload documents; edit Ground Truth | Owner, Admin, Editor |
| Run workflows and evaluations | Owner, Admin, Editor, Runner |
| Publish/restore workflows; manage Providers, API keys, members | Owner, Admin |
| Delete a workspace or transfer ownership | Owner |

Use the least privileged role that fits the member's task. A member losing access should also lose active WebSocket permissions and scoped resource visibility.

## Protect session authentication

- Use a long random `AUTH_SESSION_SECRET` and rotate it through a planned sign-out event.
- Use secure cookies with HTTPS.
- Do not expose the backend directly when the frontend expects same-origin `/api` and `/ws`.
- Review SameSite and CORS together; permissive cross-origin settings can undermine cookie protections.
- Do not put session cookies or browser storage dumps in issue reports.

## Protect Provider credentials

Provider credentials are encrypted at rest and decrypted only for invocation. They must never enter:

- workflow or node configuration;
- prompts;
- API responses;
- persisted traces;
- application logs;
- screenshots or public fixtures.

Editing a Provider intentionally does not display the stored key. Leaving the key field blank retains it; entering a value rotates it.

Provider private-host access is an operator-controlled risk. DNS validation and connection pinning still reject link-local, cloud metadata, reserved, multicast, unspecified, and rebinding destinations.

## Protect public workflow inputs

URL-mode input and multipart upload use different guardrails:

| Input | Controls |
| --- | --- |
| Remote URL | HTTP(S) resolution, DNS/IP validation, connection pinning, redirect revalidation, timeout, streaming byte ceiling. |
| Multipart upload | Per-key rate limit, header and streaming size checks, one-file rule, MIME/magic-byte validation. |

Input rejection occurs before workflow execution so a failed fetch or upload does not leave a half-started task.

Keep `INPUT_FETCH_ALLOW_PRIVATE_HOSTS=false` for public integrations. Never weaken metadata or link-local blocking to make a convenience URL work.

## Protect API keys and traces

- Issue separate workflow-scoped keys per calling system.
- Store the one-time full key in a server-side secret manager.
- Never embed it in frontend JavaScript, mobile binaries, URLs, or repository files.
- Rotate by issuing a replacement, updating the caller, testing, then revoking the old key.
- Review API usage retention and storage budgets.
- Treat run metadata, filenames, result content, and timing as sensitive.

The key service stores a hash and collapses invalid, expired, and revoked credentials into the same public error to avoid exposing their state.

## Safe diagnostics

Start with narrow, non-secret commands:

```bash
docker compose --profile standard config --quiet
docker compose --profile standard ps
curl --fail http://localhost:8000/api/health
curl --fail http://localhost:8000/api/v1/health
```

Inspect only the affected service and limit output:

```bash
docker compose logs --tail=200 <service-name>
```

Before sharing diagnostics, remove document content, prompts, authorization headers, cookies, complete private endpoints, usernames, filenames, and upstream response bodies. Prefer status codes, stable error codes, component versions, and minimal reproduction steps.

## Troubleshooting matrix

| Symptom | Likely cause | Check |
| --- | --- | --- |
| Compose reports a required variable | Placeholder or missing secret | Compare secret-managed values with `.env.example`; do not add fallback defaults. |
| Browser loops to sign-in | Cookie security/origin mismatch | HTTPS, `AUTH_SESSION_SECURE`, SameSite, proxy headers, and trusted origin. |
| Resource returns 403 or is disabled | Role lacks capability | Active workspace, member role, and requested operation. |
| Resource returns 404 after a workspace switch | Resource belongs to another workspace | Switch back or use a resource in the active workspace; do not copy IDs across scopes. |
| Model Provider test fails | Reachability, TLS, auth, or model identifier | VLM adapter path, explicit base URL, credential, API style, Azure version/deployment. |
| Provider destination is blocked | Network policy rejected the target | Resolve host/IP class and operator policy; never bypass metadata blocking. |
| Public URL run returns `INVALID_INPUT` | URL/DNS/redirect/status/size/time guard | Use a reachable public URL within limits. |
| Upload returns `INVALID_INPUT` | Missing/multiple file, size, MIME, or signature | Send one supported file with matching content type. |
| Upload returns `RATE_LIMIT_EXCEEDED` | Per-key upload bucket exhausted | Back off and isolate callers by key. |
| API returns `WORKFLOW_NOT_PUBLISHED` | Saved but unpublished workflow | Publish the intended version, then retry. |
| API returns `RUN_TIMEOUT` | Blocking wait elapsed | Keep the run ID and poll status; do not immediately duplicate the run. |
| Evaluation run remains queued | Queue mode or worker problem | Redis, worker, queue settings, database, and runtime attestation. |
| Results or uploads fail as disk fills | Retained storage exhausted | Storage volume, PostgreSQL, API usage retention, and backup/cleanup policy. |

## Incident response

After suspected disclosure:

1. Revoke affected workflow API keys and upstream Provider credentials.
2. Rotate session, database, Redis, or encryption secrets according to impact.
3. Preserve minimal forensic evidence under your private incident policy.
4. Collect deployment-side access and audit evidence alongside API usage metadata. The current **Workspace Audit** page is a non-persisted placeholder and cannot supply historical events.
5. Remove exposed data from public channels; do not rely on deleting a later commit to erase a secret from history.
6. Validate a synthetic workflow and API call after recovery.

Changing `PROVIDER_ENCRYPTION_KEY` without a credential migration makes existing encrypted Provider credentials unreadable. Plan that rotation and re-enter Provider secrets as required.

## Report a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/jaminmei/Pressroom/security/advisories/new). Do not open a public issue containing exploit details, credentials, private documents, or deployment endpoints.

Include the affected version, impact, minimal reproduction, and suggested mitigation. Security fixes target the latest public release on `main`.

## Verify the baseline

- No example placeholder remains in effective runtime configuration.
- HTTPS, secure cookies, trusted origins, and WebSocket proxying work together.
- Workspace access checks pass for Owner, Admin, Editor, Runner, Viewer, and an outsider.
- Provider credentials do not appear in workflow exports, results, traces, or logs.
- Private Provider policy matches the deployment threat model.
- URL and upload input guards reject controlled negative fixtures.
- API key issue, use, rotation, and revocation are tested.
- Backups restore PostgreSQL, shared storage, and Provider access coherently.

## Next steps

- [Review Compose operations](/deployment/compose)
- [Configure Model Providers](/workflows/providers)
- [Integrate the public Workflow API](/api-reference/workflow-api)
