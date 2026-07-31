---
title: Publish and configure API Access
description: Publish a workflow version, issue a workflow-scoped key, copy invocation examples, review usage, and revoke access safely.
---

# Publish and configure API Access

**API Access** turns a saved workflow into a controlled external integration. Publishing selects the workflow version; a workflow-scoped Bearer key authorizes calls. Provider credentials remain server-side and are never returned to callers.

## Prerequisites

- A saved workflow that completes with a representative input
- `Owner` or `Admin` role (`workflow.publish`, `api_key.manage`, and `api_usage.view`)
- A secure place to store the one-time API key
- A public base URL for the PressRoom deployment when calling from another system

## 1. Publish a workflow version

1. Open the saved workflow from **Workflow Studio**.
2. Run a representative file and inspect the final output.
3. Select **Publish**.
4. Optionally enter a version description in **Publish New Version**, then confirm **Publish**. The saved workflow name is not edited in this dialog.
5. Verify the editor reports the published version number.

Publishing does not freeze future editing. You can continue saving new versions.

::: warning Definition used by public runs
In the current release, publishing gates API access but does not pin execution to that version's snapshot. Once a workflow has been published, each new public run uses its current saved definition. Saving a later edit can therefore change public execution without another publish. Re-test saved changes before external callers invoke them, and do not treat the published-version indicator as an immutable deployment boundary.
:::

## 2. Open API Access

In the current workflow context, select **API Forward** in the sidebar. The route is `/workflows/{workflowId}/api-access`.

An unpublished workflow displays a locked state and directs you back to the editor. A published workflow shows:

- current and published version indicators;
- workflow ID;
- JSON URL-mode and multipart upload endpoints;
- key management;
- readiness checks;
- public usage summary and call history.

![API Access setup for a published workflow](/images/guides/api-access-setup.webp)

## 3. Generate a key

1. Select **Generate Key**.
2. Add an optional key name that identifies the calling system.
3. Select **Generate**.
4. Copy the complete key into your secret manager immediately.
5. Confirm **I've saved it** only after storage succeeds.

The complete key is shown once. Afterwards PressRoom displays only its masked prefix. The backend stores a SHA-256 hash for verification, not the reusable plaintext key.

Every key is bound to the current workflow. Use separate keys for separate callers when you need independent rotation and usage attribution.

## 4. Choose an input mode

### URL mode

Use URL mode when the document is already available at an HTTP(S) URL that the PressRoom backend may fetch. The request body supplies `inputs.file`.

Remote downloads are streamed with DNS/IP validation, redirect revalidation, a time limit, and a byte ceiling. Public-network fetching is the default; link-local and cloud metadata targets are blocked.

### Upload mode

Use upload mode when the file is local to the caller. Send one multipart `file` part and an optional `options` JSON field.

The default policy allows PDF, PNG, JPEG, JPEG 2000, and TIFF signatures, limits the multipart body to 20 MiB, and permits 10 upload requests per minute for each key. The rate-limit bucket is in memory per backend process, so restarts reset it and multiple replicas do not share one bucket. The server checks both declared MIME type and file magic bytes.

Both modes block while the workflow runs and return the same success envelope. The default blocking timeout is 300 seconds. If the request returns `504 RUN_TIMEOUT`, execution continues and the caller should poll the run status.

## 5. Test from a trusted terminal

Use the request shown on the API Access page or follow the [Workflow API reference](/api-reference/workflow-api). Put the base URL, workflow ID, API key, and document location in environment variables; never hard-code them in source.

Start with a non-sensitive fixture. Verify the response contains a `workflow_run_id`, `status: "succeeded"`, timing, steps, and results.

## 6. Review usage and traces

The **Usage** tab reports URL-mode and upload run attempts. Health, status, results, and history requests are not counted. It provides:

- call count, success rate, failures, and average response time;
- retained storage against the per-workflow budget;
- filters for status, endpoint kind, and key;
- metadata-only upload input details;
- a per-run trace view.

Uploaded document bodies and Provider secrets must not appear in usage records. Treat filenames and run metadata as potentially sensitive operational data.

The per-workflow storage budget is enforced, not just displayed. When it is exceeded, PressRoom evicts the oldest terminal API invocation records and their API-forward run artifacts until usage falls within the budget. Status, results, history, and trace lookup can therefore return no record for an evicted run; copy required output into caller-controlled storage before retention pressure removes it.

## 7. Revoke a key

1. Find the active key by description or prefix.
2. Select **Revoke**.
3. Confirm the irreversible action.

Calls using that key fail immediately. Update the calling system with a newly issued key before revoking when you need a no-downtime rotation.

## Verify success

- The page shows a `Published v…` indicator and forwarding enabled.
- Readiness reports a saved workflow, publication state, scoped key, remote URL support, and ownership checks; a separate card lists the run query endpoints.
- The full key exists only in your secret manager and calling environment.
- A URL or upload call returns a workflow run ID and successful result.
- The invocation appears in API usage without source content or a full endpoint disclosure.
- Revoking a test key causes it to receive `401 INVALID_API_KEY`.

## Troubleshooting

### API Access requires a published workflow

Return to the editor and publish a saved version. Saving alone does not select a public version.

### Generate Key is unavailable

Only Owners and Admins can view and manage workflow API keys. Confirm the active workspace and role.

### A key receives `WORKFLOW_MISMATCH`

The request uses a workflow ID different from the key's binding. Use the endpoint displayed for that key's workflow or issue a key for the intended workflow.

### URL input is rejected before a run exists

Check scheme, DNS, redirects, target network, response status, fetch timeout, and byte limit. Fetch guards run before DAG execution, so rejected input does not create a half-started run.

### Upload receives `RATE_LIMIT_EXCEEDED`

Back off and retry after capacity replenishes. Do not distribute one key across unrelated callers; separate keys make limits and rotation easier to manage.

## Next steps

- [Read the complete six-endpoint API reference](/api-reference/workflow-api)
- [Harden the deployment](/administration/security-and-troubleshooting)
- [Understand workflow versions](/concepts/core-concepts)
