---
title: Workflow API 参考
description: 查看 PressRoom 六个公开 API Endpoint：Health、URL 与 Upload Run、Status、Result 和 Workflow Run History。
---

# Workflow API 参考

公开 Workflow API 挂载在 `/api/v1` 下，严格包含六个 Endpoint：Health、两种启动 Run 的方式、Run Status、Run Result 和 Workflow Run History。

## Authentication 和变量

`GET /api/v1/health` 不需要认证。其他每个 Endpoint 都需要 Workflow-scoped Bearer Key：

```http
Authorization: Bearer <workflow-scoped-api-key>
```

在可信 Shell 中设置 Request Value，并在本地替换每个 Placeholder：

```bash
export PRESSROOM_BASE_URL='<press-room-origin>'
export PRESSROOM_WORKFLOW_ID='<workflow-id>'
export PRESSROOM_API_KEY='<workflow-scoped-api-key>'
export PRESSROOM_DOCUMENT_URL='<public-document-url>'
export PRESSROOM_DOCUMENT_PATH='<local-document-path>'
export PRESSROOM_CALLER_ID='<caller-reference>'
export PRESSROOM_RUN_ID='<workflow-run-id>'
```

不要提交这些值、把 Key 放入 Browser Code，或通过 Query String 发送 Key。

## Endpoint 汇总

| Method | Path | Authentication | 用途 |
| --- | --- | --- | --- |
| `GET` | `/api/v1/health` | 无 | 检查 Public API Router。 |
| `POST` | `/api/v1/workflows/{workflow_id}/run` | Bearer Key | 使用 HTTP(S) Document URL 运行。 |
| `POST` | `/api/v1/workflows/{workflow_id}/run/upload` | Bearer Key | 使用一个 Multipart Upload 运行。 |
| `GET` | `/api/v1/workflow-runs/{workflow_run_id}` | Bearer Key | 读取持久化 Run Status。 |
| `GET` | `/api/v1/workflow-runs/{workflow_run_id}/results` | Bearer Key | 完成后读取 Result。 |
| `GET` | `/api/v1/workflows/{workflow_id}/runs` | Bearer Key | 列出 Workflow Run History。 |

## Health

```http
GET /api/v1/health
```

```bash
curl --fail-with-body --silent --show-error \
  "$PRESSROOM_BASE_URL/api/v1/health"
```

Response：

```json
{
  "status": "ok"
}
```

该 Endpoint 只验证 Public Router，并不表示每个 Engine 或 Provider 都已就绪。

## 启动 URL Run

```http
POST /api/v1/workflows/{workflow_id}/run
```

Request Body：

```json
{
  "inputs": {
    "file": "<public-document-url>"
  },
  "user": "<caller-reference>"
}
```

示例：

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

当 Published Graph 包含 File Input Node 时，`inputs.file` 为必填。外部 Caller 应提供 HTTP(S) URL。Fetch 会在 DAG 启动前完成，并受 SSRF、Redirect、Timeout 和 Byte-limit Control 约束。Remote Byte Ceiling 默认是 100 MiB。

## 启动 Upload Run

```http
POST /api/v1/workflows/{workflow_id}/run/upload
```

只发送一个 `file` Part。`options` 是可选 JSON String，可以包含 `user`。

```bash
curl --fail-with-body --silent --show-error \
  --request POST \
  --url "$PRESSROOM_BASE_URL/api/v1/workflows/$PRESSROOM_WORKFLOW_ID/run/upload" \
  --header "Authorization: Bearer $PRESSROOM_API_KEY" \
  --form "file=@${PRESSROOM_DOCUMENT_PATH}" \
  --form "options={\"user\":\"${PRESSROOM_CALLER_ID}\"}"
```

默认 Upload Control：

- 每个 Request 一个 File；
- 20 MiB Multipart-body Ceiling；
- 每个 API Key 每分钟 10 次 Request；
- 对 PDF、PNG、JPEG、JPEG 2000 和 TIFF 进行 Magic-byte Validation；
- Declared MIME Type 必须与检测到的 Content 一致。

Rate Limiter 是每个 Backend Process 独立的 In-memory Bucket。Process 重启会重置它，多个 Backend Replica 也不会共享同一个 Bucket。

## Run Response

两个 Start Endpoint 都会 Blocking 到 Terminal State 或 Runtime Timeout。成功执行返回 HTTP `200`：

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

具体 Result Entry 取决于已解锁 Publication State 的 Workflow 当前 Saved Definition。应把 `content`、`file` 和 `metadata` 当作 Output Data，而不是固定的 OCR-only Schema。URL Mode 会回显提交的 `inputs` Object；Upload Mode 当前会回显 Server-local Saved Path，并在提供 `options.user` 时把它放入 `inputs.user`。这些回显 Input Value 只应用于诊断，不能当作可复用 File Locator。

`storage_path` 是 Server-local Path。Result 中的 `download_url` 指向 `/api/tasks` 下使用 Session 认证的 Application Route；Workflow Bearer Key 无权调用该下载 Route。External Client 应使用 Inline Result Content，或把结果复制到 Caller 管理的存储中。

Workflow Execution Failure 同样返回 HTTP `200`，但包含 `status: "failed"` 和 `error` Object。Client 必须检查 Response `status`，不能只看 HTTP Code。

如果 Blocking Wait 达到默认 300 秒 Timeout，API 会返回 HTTP `504`、`RUN_TIMEOUT` 和 `workflow_run_id`。Run 会继续在 Server 端执行；使用该 ID 轮询 Status。

## 获取 Run Status

```http
GET /api/v1/workflow-runs/{workflow_run_id}
```

```bash
curl --fail-with-body --silent --show-error \
  --url "$PRESSROOM_BASE_URL/api/v1/workflow-runs/$PRESSROOM_RUN_ID" \
  --header "Authorization: Bearer $PRESSROOM_API_KEY"
```

Response：

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

Status 暴露持久化 Task Value，包括 `pending`、`running`、`completed`、`partial_completed`、`failed` 或 `cancelled`。Key 必须属于拥有该 Run 的 Workflow。

## 获取 Run Result

```http
GET /api/v1/workflow-runs/{workflow_run_id}/results
```

```bash
curl --fail-with-body --silent --show-error \
  --url "$PRESSROOM_BASE_URL/api/v1/workflow-runs/$PRESSROOM_RUN_ID/results" \
  --header "Authorization: Bearer $PRESSROOM_API_KEY"
```

Completed 或 Partially Completed Response：

```json
{
  "workflow_run_id": "<workflow-run-id>",
  "status": "succeeded",
  "results": []
}
```

只有 `completed` 或 `partial_completed` 才会成功。`pending` 或 `running` Run 会返回 HTTP `409` 和 `RUN_NOT_COMPLETE`；已经终止的 `failed` 或 `cancelled` Run 也会返回相同错误。

## 列出 Workflow Run History

```http
GET /api/v1/workflows/{workflow_id}/runs?page={page}&limit={limit}
```

`page` 从 1 开始。`limit` 接受 1–100，默认为 20。

```bash
curl --fail-with-body --silent --show-error \
  --url "$PRESSROOM_BASE_URL/api/v1/workflows/$PRESSROOM_WORKFLOW_ID/runs?page=1&limit=20" \
  --header "Authorization: Bearer $PRESSROOM_API_KEY"
```

Response：

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

## Domain Error Envelope

Public Handler 抛出的 Authentication 和 Domain Error 使用以下 Shape：

```json
{
  "error": {
    "code": "<stable-error-code>",
    "message": "<safe-error-message>"
  }
}
```

部分 Error 会包含 `workflow_run_id`，使 Caller 可以继续轮询。

| HTTP | Code | 含义 |
| ---: | --- | --- |
| 400 | `INVALID_INPUT` | 缺失/畸形 Input、被阻止的 URL Fetch、无效 Multipart Data、大小或 Signature。 |
| 401 | `UNAUTHORIZED` | 缺失或格式错误的 Bearer Authorization。 |
| 401 | `INVALID_API_KEY` | 未知、过期或已撤销 Key。 |
| 403 | `WORKFLOW_MISMATCH` | Key 绑定到另一个 Workflow。 |
| 403 | `WORKFLOW_NOT_PUBLISHED` | Workflow 没有 Published Version。 |
| 403 | `RUN_NOT_OWNED` | Key 所属 Workflow 不拥有请求的 Run。 |
| 404 | `WORKFLOW_NOT_FOUND` | Workflow 在 Key 的 Workspace Scope 中不可用。 |
| 404 | `RUN_NOT_FOUND` | 该 ID 不存在 Scoped Run Snapshot。 |
| 409 | `RUN_NOT_COMPLETE` | 在成功进入 Terminal State 前请求 Result。 |
| 429 | `RATE_LIMIT_EXCEEDED` | Per-key Upload Capacity 已耗尽。 |
| 503 | `SERVICE_UNAVAILABLE` | API Key Verification Service 未初始化。 |
| 504 | `RUN_TIMEOUT` | Blocking Wait 已结束；Server-side Execution 继续。 |

Execution-level `WORKFLOW_EXECUTION_FAILED` 和 `WORKFLOW_CANCELLED` 会包含在 HTTP `200` Run Response 中，并带有 `status: "failed"`。

Framework-level Failure 不使用上述 Envelope。Request Body、Path 或 Query Validation 可能返回 HTTP `422` 和 FastAPI `detail` Array；未处理的 HTTP `500` 使用包含 `error_code`、`message`、`details` 和 `trace_id` 的 Application Envelope。Client 应先按 HTTP Status 分支，再解析具体 Error Shape。

## Client 行为检查清单

1. 把 Key 保存在 Server-side Secret Manager 中。
2. 明确设置 Connect 和 Overall Client Timeout；Server 最长可能 Blocking 到其配置的 Workflow Timeout。
3. 同时检查 HTTP Status 和 Response `status`。
4. 收到 `RUN_TIMEOUT` 时保留返回的 Run ID，并使用 Backoff 轮询。
5. 只有 Status 为 `completed` 或 `partial_completed` 后才请求 Result。
6. 把 Output Content、Filename、Path 和 Metadata 视为敏感信息；不要假设 `download_url` 接受 Workflow Key。
7. 在 Per-workflow Retention Budget 清理较旧 API-forward Run 前，把所需 Output 复制到 Caller 管理的存储中。
8. 为每个 Calling System 单独轮换和撤销 Key。

## 下一步

- [在 UI 中配置 API Access](/zh-CN/publish/api-access)
- [查看 Input 和 Secret Protection](/zh-CN/administration/security-and-troubleshooting)
- [部署 Full Queue Profile](/zh-CN/deployment/compose)
