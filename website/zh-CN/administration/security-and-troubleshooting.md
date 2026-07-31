---
title: 安全与故障排查
description: 应用 PressRoom 部署安全基线，保护 Provider 与公开 Input，理解 Workspace RBAC，并在不泄露敏感数据的情况下诊断问题。
---

# 安全与故障排查

PressRoom 会处理不受信任的文件，也可以调用 Operator 配置的服务。应把 Identity、Workspace Isolation、Network Destination、Credential、Log 和 Retained Result 视为一个整体安全边界，而不是彼此独立的便利功能。

## 部署安全基线

在受信任的开发机器之外暴露 PressRoom 前，落实以下每一项：

- 使用相互独立的 Secret 替换 `.env.example` 中每个 Required Placeholder。
- 强制执行 Workspace RBAC。Stock Compose 固定设置 `WORKSPACE_RBAC_ENFORCED=true`；自定义部署也必须保留相同安全不变量。
- 终止 HTTPS，并设置 `AUTH_SESSION_SECURE=true`。
- Backend CORS Configuration 只允许目标 Frontend Origin。
- 保持 `PROVIDER_ENCRYPTION_KEY` 稳定、私密，并且只由 Backend 与 Worker 共享。
- 对不受信任的 Multi-tenant Deployment 设置 `PROVIDER_ALLOW_PRIVATE_HOSTS=false`，除非明确需要 Private Provider Routing。
- 保持 Public URL Fetch 的 Private-host Access 关闭。
- 使用 Host 和 Network Control 限制 Backend、PostgreSQL、Redis 和 Engine Port。
- 除非经过审核的 Trust Model 要求，否则保持 Provider Call 的 TLS Verification 开启。
- 同时备份 PostgreSQL 和 Shared Storage，并单独保护 Encryption Key。

## Workspace Access Control

公开部署会在 Backend 和 Worker 中强制执行 Workspace RBAC。

| 操作 | Role |
| --- | --- |
| 查看 Workflow、Database、Ground Truth、Run 和 Provider | Owner、Admin、Editor、Runner、Viewer |
| 创建/编辑 Workflow 和 Database；上传 Document；编辑 Ground Truth | Owner、Admin、Editor |
| 运行 Workflow 和 Evaluation | Owner、Admin、Editor、Runner |
| Publish/Restore Workflow；管理 Provider、API Key 和 Member | Owner、Admin |
| 删除 Workspace 或转移所有权 | Owner |

为成员分配满足任务所需的最低 Role。成员失去访问权限时，也应失去 Active WebSocket Permission 和 Scoped Resource Visibility。

## 保护 Session Authentication

- 使用足够长的随机 `AUTH_SESSION_SECRET`，并通过计划内全员退出事件进行轮换。
- 在 HTTPS 下使用 Secure Cookie。
- 当 Frontend 依赖同源 `/api` 和 `/ws` 时，不要直接暴露 Backend。
- 一起审查 SameSite 和 CORS；过度宽松的 Cross-origin 设置可能破坏 Cookie Protection。
- 不要把 Session Cookie 或 Browser Storage Dump 放入 Issue Report。

## 保护 Provider Credential

Provider Credential 会加密保存，并且只在调用时解密。它们绝不能进入：

- Workflow 或 Node Configuration；
- Prompt；
- API Response；
- Persisted Trace；
- Application Log；
- Screenshot 或 Public Fixture。

编辑 Provider 时不显示 Stored Key 是预期行为。Key Field 留空会保留原值，输入新值则会轮换。

Provider Private-host Access 是由 Operator 控制的风险。DNS Validation 和 Connection Pinning 仍会拒绝 Link-local、Cloud Metadata、Reserved、Multicast、Unspecified 和 Rebinding Destination。

## 保护 Public Workflow Input

URL Mode Input 与 Multipart Upload 使用不同 Guardrail：

| Input | Control |
| --- | --- |
| Remote URL | HTTP(S) Resolution、DNS/IP Validation、Connection Pinning、Redirect Revalidation、Timeout、Streaming Byte Ceiling。 |
| Multipart Upload | Per-key Rate Limit、Header 与 Streaming Size Check、One-file Rule、MIME/Magic-byte Validation。 |

Input Rejection 会发生在 Workflow Execution 前，因此失败 Fetch 或 Upload 不会留下半启动 Task。

Public Integration 保持 `INPUT_FETCH_ALLOW_PRIVATE_HOSTS=false`。不要为了访问便利 URL 而削弱 Metadata 或 Link-local Blocking。

## 保护 API Key 和 Trace

- 为每个 Calling System 创建独立 Workflow-scoped Key。
- 把一次性完整 Key 保存在 Server-side Secret Manager。
- 绝不嵌入 Frontend JavaScript、Mobile Binary、URL 或 Repository File。
- 先创建 Replacement、更新 Caller 并测试，再撤销 Old Key。
- 查看 API Usage Retention 和 Storage Budget。
- 把 Run Metadata、Filename、Result Content 和 Timing 视为敏感信息。

Key Service 保存 Hash，并把 Invalid、Expired 和 Revoked Credential 合并为同一个 Public Error，避免泄露其具体状态。

## 安全诊断

从范围小且不含 Secret 的命令开始：

```bash
docker compose --profile standard config --quiet
docker compose --profile standard ps
curl --fail http://localhost:8000/api/health
curl --fail http://localhost:8000/api/v1/health
```

只查看受影响 Service，并限制输出量：

```bash
docker compose logs --tail=200 <service-name>
```

共享诊断信息前，删除 Document Content、Prompt、Authorization Header、Cookie、完整 Private Endpoint、Username、Filename 和 Upstream Response Body。优先提供 Status Code、Stable Error Code、Component Version 和最小 Reproduction Step。

## 故障排查矩阵

| 现象 | 可能原因 | 检查项 |
| --- | --- | --- |
| Compose 报告 Required Variable | Placeholder 或缺失 Secret | 对照 `.env.example` 检查 Secret-managed Value；不要添加默认回退。 |
| Browser 循环返回 Sign-in | Cookie Security/Origin 不匹配 | HTTPS、`AUTH_SESSION_SECURE`、SameSite、Proxy Header 和 Trusted Origin。 |
| Resource 返回 403 或控件禁用 | Role 缺少 Capability | Active Workspace、Member Role 和目标 Operation。 |
| 切换 Workspace 后 Resource 返回 404 | Resource 属于另一个 Workspace | 切换回原 Workspace，或使用活动 Workspace 中的 Resource；不要跨 Scope 复制 ID。 |
| Model Provider Test 失败 | Reachability、TLS、Auth 或 Model Identifier | VLM Adapter Path、Explicit Base URL、Credential、API Style、Azure Version/Deployment。 |
| Provider Destination 被阻止 | Network Policy 拒绝 Target | 检查 Host/IP Class 和 Operator Policy；绝不能绕过 Metadata Blocking。 |
| Public URL Run 返回 `INVALID_INPUT` | URL/DNS/Redirect/Status/Size/Time Guard | 使用在限制内且可访问的 Public URL。 |
| Upload 返回 `INVALID_INPUT` | 缺失/多个 File、Size、MIME 或 Signature | 发送一个 Content Type 匹配的受支持文件。 |
| Upload 返回 `RATE_LIMIT_EXCEEDED` | Per-key Upload Bucket 耗尽 | 使用 Backoff，并按 Key 隔离 Caller。 |
| API 返回 `WORKFLOW_NOT_PUBLISHED` | Workflow 已保存但未发布 | Publish 目标 Version 后重试。 |
| API 返回 `RUN_TIMEOUT` | Blocking Wait 已结束 | 保留 Run ID 并轮询 Status；不要立即重复创建 Run。 |
| Evaluation Run 一直处于 Queued | Queue Mode 或 Worker 问题 | Redis、Worker、Queue Setting、Database 和 Runtime Attestation。 |
| Disk 填满后 Result 或 Upload 失败 | Retained Storage 耗尽 | Storage Volume、PostgreSQL、API Usage Retention 和 Backup/Cleanup Policy。 |

## Incident Response

怀疑信息泄露后：

1. 撤销受影响的 Workflow API Key 和 Upstream Provider Credential。
2. 根据影响范围轮换 Session、Database、Redis 或 Encryption Secret。
3. 按 Private Incident Policy 保存最少必要 Forensic Evidence。
4. 收集 Deployment 侧的 Access/Audit Evidence，并结合 API Usage Metadata 调查。当前 **Workspace Audit** 页面是不持久化数据的占位页，不能提供历史 Event。
5. 从公开渠道移除暴露数据；不要认为删除后续 Commit 就能从历史中抹除 Secret。
6. 恢复后使用合成数据验证 Workflow 和 API Call。

在没有 Credential Migration 的情况下更改 `PROVIDER_ENCRYPTION_KEY`，会使已有加密 Provider Credential 无法读取。需要对轮换进行计划，并按需重新输入 Provider Secret。

## 报告 Vulnerability

使用 [GitHub Private Vulnerability Reporting](https://github.com/jaminmei/Pressroom/security/advisories/new)。不要创建包含 Exploit Detail、Credential、Private Document 或 Deployment Endpoint 的 Public Issue。

请提供 Affected Version、Impact、Minimal Reproduction 和 Suggested Mitigation。Security Fix 以 `main` 上的 Latest Public Release 为目标。

## 验证安全基线

- Effective Runtime Configuration 中没有保留 Example Placeholder。
- HTTPS、Secure Cookie、Trusted Origin 和 WebSocket Proxy 协同工作。
- Owner、Admin、Editor、Runner、Viewer 和 Outsider 的 Workspace Access Check 均符合预期。
- Workflow Export、Result、Trace 和 Log 中不存在 Provider Credential。
- Private Provider Policy 与 Deployment Threat Model 一致。
- URL 和 Upload Input Guard 能拒绝受控 Negative Fixture。
- API Key 创建、使用、轮换和撤销均经过测试。
- Backup 能一致恢复 PostgreSQL、Shared Storage 和 Provider Access。

## 下一步

- [查看 Compose 运行方式](/zh-CN/deployment/compose)
- [配置 Model Provider](/zh-CN/workflows/providers)
- [集成公开 Workflow API](/zh-CN/api-reference/workflow-api)
