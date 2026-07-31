---
title: Workflow API reference
description: Reference the six public PressRoom API endpoints for health, URL and upload runs, status, results, and workflow run history.
---

# Workflow API reference

The public workflow API is mounted under `/api/v1`. It contains exactly six endpoints: health, two ways to start a run, run status, run results, and workflow run history.

## Authentication and variables

`GET /api/v1/health` is unauthenticated. Every other endpoint requires a workflow-scoped Bearer key:

```http
Authorization: Bearer <workflow-scoped-api-key>
```

Set request values in a trusted shell. Replace every placeholder locally:

```bash
export PRESSROOM_BASE_URL='<press-room-origin>'
export PRESSROOM_WORKFLOW_ID='<workflow-id>'
export PRESSROOM_API_KEY='<workflow-scoped-api-key>'
export PRESSROOM_DOCUMENT_URL='<public-document-url>'
export PRESSROOM_DOCUMENT_PATH='<local-document-path>'
export PRESSROOM_CALLER_ID='<caller-reference>'
export PRESSROOM_RUN_ID='<workflow-run-id>'
```

Do not commit these values, put the key in browser code, or send it in a query string.

## Endpoint summary

| Method | Path | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/health` | No | Check the public API router. |
| `POST` | `/api/v1/workflows/{workflow_id}/run` | Bearer key | Run with an HTTP(S) document URL. |
| `POST` | `/api/v1/workflows/{workflow_id}/run/upload` | Bearer key | Run with one multipart upload. |
| `GET` | `/api/v1/workflow-runs/{workflow_run_id}` | Bearer key | Read persisted run status. |
| `GET` | `/api/v1/workflow-runs/{workflow_run_id}/results` | Bearer key | Read results after completion. |
| `GET` | `/api/v1/workflows/{workflow_id}/runs` | Bearer key | List workflow run history. |

## Health

```http
GET /api/v1/health
```

```bash
curl --fail-with-body --silent --show-error \
  "$PRESSROOM_BASE_URL/api/v1/health"
```

Response:

```json
{
  "status": "ok"
}
```

This verifies the public router, not the readiness of every engine or Provider.

## Start a URL run

```http
POST /api/v1/workflows/{workflow_id}/run
```

Request body:

```json
{
  "inputs": {
    "file": "<public-document-url>"
  },
  "user": "<caller-reference>"
}
```

Example:

```bash
curl --fail-with-body --silent --show-error \
  --request POST \
  --url "$PRESSROOM_BASE_URL/api/v1/workflows/$PRESSROOM_WORKFLOW_ID/run" \
  --header "Authorization: Bearer $PRESSROOM_API_KEY" \
  --header 'Content-Type: application/json' \
  --data @- <<JSON
{"inputs":{"file":"${PRESSROOM_DOCUMENT_URL}"},"user":"${PRESSROOM_CALLER_ID}"}
JSON
```

`inputs.file` is required when the published graph contains file input nodes. For external callers, supply an HTTP(S) URL. The fetch is completed before the DAG starts and is subject to SSRF, redirect, timeout, and byte-limit controls. The default remote byte ceiling is 100 MiB.

## Start an upload run

```http
POST /api/v1/workflows/{workflow_id}/run/upload
```

Send exactly one `file` part. `options` is an optional JSON string that may contain `user`.

```bash
curl --fail-with-body --silent --show-error \
  --request POST \
  --url "$PRESSROOM_BASE_URL/api/v1/workflows/$PRESSROOM_WORKFLOW_ID/run/upload" \
  --header "Authorization: Bearer $PRESSROOM_API_KEY" \
  --form "file=@${PRESSROOM_DOCUMENT_PATH}" \
  --form "options={\"user\":\"${PRESSROOM_CALLER_ID}\"}"
```

Default upload controls:

- one file per request;
- 20 MiB multipart-body ceiling;
- 10 requests per minute per API key;
- magic-byte validation for PDF, PNG, JPEG, JPEG 2000, and TIFF;
- declared MIME type must match detected content.

The rate limiter is an in-memory bucket per backend process. A process restart resets it, and multiple backend replicas do not share one bucket.

## Run response

Both start endpoints block until terminal state or the runtime timeout. A successful execution returns HTTP `200`:

```json
{
  "workflow_run_id": "<workflow-run-id>",
  "status": "succeeded",
  "inputs": {
    "file": "<echoed-input-reference>"
  },
  "outputs": {
    "text": "<assembled-text>",
    "results": [
      {
        "result_id": "<result-id>",
        "node_id": "<node-id>",
        "node_type": "engine/<engine-type>",
        "engine_type": "<engine-type>",
        "output_format": "<output-format>",
        "result_preview": "<truncated-preview>",
        "duration_ms": 0,
        "status": "completed",
        "content": "<result-content>",
        "file": {
          "filename": "<result-filename>",
          "size_bytes": 0,
          "content_type": "<content-type>",
          "storage_path": "<server-storage-path>",
          "download_url": "<result-download-path>"
        },
        "metadata": {
          "processing_time_ms": 0,
          "page_count": 1,
          "char_count": 0,
          "word_count": 0
        }
      }
    ]
  },
  "elapsed_time_ms": 0,
  "total_steps": 0,
  "created_at": "<iso-8601-timestamp>",
  "finished_at": "<iso-8601-timestamp>"
}
```

The exact result entries depend on the current saved definition of a publication-enabled workflow. Treat `content`, `file`, and `metadata` as output data, not a fixed OCR-only schema. URL mode echoes the submitted `inputs` object; upload mode currently echoes a server-local saved path and places `options.user`, when supplied, in `inputs.user`. Treat those echoed input values as diagnostics, not reusable file locators.

The `storage_path` is server-local. A result `download_url` points to the session-authenticated application route under `/api/tasks`; a workflow Bearer key does not authorize that download route. External clients should consume the inline result content or copy it into caller-controlled storage.

A workflow execution failure also returns HTTP `200`, but with `status: "failed"` and an `error` object. Clients must inspect the response `status`, not only the HTTP code.

If the blocking wait reaches its default 300-second timeout, the API returns HTTP `504` with `RUN_TIMEOUT` and the `workflow_run_id`. The run continues server-side; poll status using that ID.

## Get run status

```http
GET /api/v1/workflow-runs/{workflow_run_id}
```

```bash
curl --fail-with-body --silent --show-error \
  --url "$PRESSROOM_BASE_URL/api/v1/workflow-runs/$PRESSROOM_RUN_ID" \
  --header "Authorization: Bearer $PRESSROOM_API_KEY"
```

Response:

```json
{
  "workflow_run_id": "<workflow-run-id>",
  "workflow_id": "<workflow-id>",
  "status": "<task-status>",
  "elapsed_time_ms": 0,
  "total_steps": 0,
  "created_at": "<iso-8601-timestamp>",
  "finished_at": null
}
```

Status exposes the persisted task value, including `pending`, `running`, `completed`, `partial_completed`, `failed`, or `cancelled`. The key must belong to the workflow that owns the run.

## Get run results

```http
GET /api/v1/workflow-runs/{workflow_run_id}/results
```

```bash
curl --fail-with-body --silent --show-error \
  --url "$PRESSROOM_BASE_URL/api/v1/workflow-runs/$PRESSROOM_RUN_ID/results" \
  --header "Authorization: Bearer $PRESSROOM_API_KEY"
```

Completed or partially completed response:

```json
{
  "workflow_run_id": "<workflow-run-id>",
  "status": "succeeded",
  "results": []
}
```

The endpoint succeeds only for `completed` or `partial_completed`. It returns HTTP `409` with `RUN_NOT_COMPLETE` for `pending` or `running` runs and also for terminal `failed` or `cancelled` runs.

## List workflow run history

```http
GET /api/v1/workflows/{workflow_id}/runs?page={page}&limit={limit}
```

`page` starts at 1. `limit` accepts 1–100 and defaults to 20.

```bash
curl --fail-with-body --silent --show-error \
  --url "$PRESSROOM_BASE_URL/api/v1/workflows/$PRESSROOM_WORKFLOW_ID/runs?page=1&limit=20" \
  --header "Authorization: Bearer $PRESSROOM_API_KEY"
```

Response:

```json
{
  "data": [
    {
      "workflow_run_id": "<workflow-run-id>",
      "status": "<task-status>",
      "created_at": "<iso-8601-timestamp>",
      "finished_at": "<iso-8601-timestamp>",
      "elapsed_time_ms": 0
    }
  ],
  "meta": {
    "total": 1,
    "page": 1,
    "limit": 20
  }
}
```

## Domain error envelope

Authentication and domain errors raised by the public handlers use this shape:

```json
{
  "error": {
    "code": "<stable-error-code>",
    "message": "<safe-error-message>"
  }
}
```

Some errors include `workflow_run_id` so the caller can continue polling.

| HTTP | Code | Meaning |
| ---: | --- | --- |
| 400 | `INVALID_INPUT` | Missing/malformed input, blocked URL fetch, invalid multipart data, size, or signature. |
| 401 | `UNAUTHORIZED` | Missing or malformed Bearer authorization. |
| 401 | `INVALID_API_KEY` | Unknown, expired, or revoked key. |
| 403 | `WORKFLOW_MISMATCH` | Key is bound to a different workflow. |
| 403 | `WORKFLOW_NOT_PUBLISHED` | Workflow has no published version. |
| 403 | `RUN_NOT_OWNED` | Key's workflow does not own the requested run. |
| 404 | `WORKFLOW_NOT_FOUND` | Workflow is unavailable in the key's workspace scope. |
| 404 | `RUN_NOT_FOUND` | No scoped run snapshot exists for the ID. |
| 409 | `RUN_NOT_COMPLETE` | Results were requested before a successful terminal state. |
| 429 | `RATE_LIMIT_EXCEEDED` | Per-key upload capacity is exhausted. |
| 503 | `SERVICE_UNAVAILABLE` | API key verification service is not initialized. |
| 504 | `RUN_TIMEOUT` | Blocking wait ended; server-side execution continues. |

Execution-level `WORKFLOW_EXECUTION_FAILED` and `WORKFLOW_CANCELLED` are returned inside an HTTP `200` run response with `status: "failed"`.

Framework-level failures are exceptions to that envelope. Request-body, path, or query validation can return HTTP `422` with FastAPI's `detail` array. An unexpected HTTP `500` uses the application envelope with `error_code`, `message`, `details`, and `trace_id`. Clients should branch on HTTP status before parsing a specific error shape.

## Client behavior checklist

1. Store the key in a server-side secret manager.
2. Set connect and overall client timeouts deliberately; the server may block for up to its configured workflow timeout.
3. Inspect both HTTP status and response `status`.
4. On `RUN_TIMEOUT`, retain the returned run ID and poll with backoff.
5. Request results only after status is `completed` or `partial_completed`.
6. Treat output content, filenames, paths, and metadata as sensitive; do not assume `download_url` accepts the workflow key.
7. Copy required output before the per-workflow retention budget evicts an older API-forward run.
8. Rotate and revoke keys independently for each calling system.

## Next steps

- [Set up API Access in the UI](/publish/api-access)
- [Review input and secret protections](/administration/security-and-troubleshooting)
- [Deploy the full queue profile](/deployment/compose)
