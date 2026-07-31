---
title: 发布并配置 API Access
description: 发布 Workflow Version、创建工作流级 Key、复制调用示例、查看使用情况并安全撤销访问。
---

# 发布并配置 API Access

**API Access** 把已保存 Workflow 转换为受控外部集成。Publish 选择 Workflow Version，Workflow-scoped Bearer Key 授权调用。Provider Credential 始终保留在 Server 端，绝不会返回给 Caller。

## 前置条件

- 一个已保存、并能使用代表性 Input 完成运行的 Workflow
- `Owner` 或 `Admin` Role（需要 `workflow.publish`、`api_key.manage` 和 `api_usage.view`）
- 用于保存一次性 API Key 的安全位置
- 从其他系统调用时所需的 PressRoom Deployment Public Base URL

## 1. 发布 Workflow Version

1. 从 **Workflow Studio** 打开 Saved Workflow。
2. 使用代表性文件运行，并检查 Final Output。
3. 选择 **Publish**。
4. 在 **Publish New Version** 中按需输入 Version Description，然后确认 **Publish**。该 Dialog 不会编辑 Saved Workflow Name。
5. 确认 Editor 报告 Published Version Number。

Publish 不会阻止以后编辑，你可以继续保存新 Version。

::: warning 公开 Run 使用的 Definition
在当前版本中，Publish 用于解锁 API 访问，但不会把执行固定到该 Version 的 Snapshot。Workflow 至少 Publish 一次后，每个新的公开 Run 都会使用 Current Saved Definition。因此，保存后续编辑可能在不再次 Publish 的情况下改变公开执行。在外部 Caller 调用前应重新测试 Saved Change，不要把 Published Version Indicator 视为不可变的 Deployment Boundary。
:::

## 2. 打开 API Access

在当前 Workflow Context 中，从 Sidebar 选择 **API Forward**。Route 为 `/workflows/{workflowId}/api-access`。

Unpublished Workflow 会显示 Locked State，并引导返回 Editor。Published Workflow 会显示：

- Current 和 Published Version Indicator；
- Workflow ID；
- JSON URL Mode 与 Multipart Upload Endpoint；
- Key Management；
- Readiness Check；
- Public Usage Summary 和 Call History。

![已发布工作流的 API Access 配置](/images/guides/api-access-setup.webp)

## 3. 创建 Key

1. 选择 **Generate Key**。
2. 添加可选 Key Name，用于标识 Calling System。
3. 选择 **Generate**。
4. 立即把完整 Key 复制到 Secret Manager。
5. 只有在成功保存后才确认 **I've saved it**。

完整 Key 只显示一次。之后 PressRoom 只显示其 Masked Prefix。Backend 保存用于校验的 SHA-256 Hash，而不是可复用 Plaintext Key。

每个 Key 都绑定到当前 Workflow。如果需要独立 Rotation 和 Usage Attribution，请为不同 Caller 使用不同 Key。

## 4. 选择 Input Mode

### URL Mode

当 Document 已经位于 PressRoom Backend 可以获取的 HTTP(S) URL 时，使用 URL Mode。Request Body 提供 `inputs.file`。

Remote Download 使用 DNS/IP Validation、Redirect Revalidation、Time Limit 和 Byte Ceiling 进行流式处理。默认只允许 Public-network Fetch；Link-local 和 Cloud Metadata Target 会被阻止。

### Upload Mode

当文件位于 Caller 本地时，使用 Upload Mode。发送一个 Multipart `file` Part 和可选的 `options` JSON Field。

默认策略允许 PDF、PNG、JPEG、JPEG 2000 和 TIFF Signature；Multipart Body 上限为 20 MiB；每个 Key 每分钟允许 10 个 Upload Request。Rate-limit Bucket 位于各 Backend Process 的内存中，因此重启会重置，多副本之间也不会共享同一个 Bucket。Server 会同时检查 Declared MIME Type 和 File Magic Bytes。

两种 Mode 都会在 Workflow 运行期间保持 Blocking，并返回相同的 Success Envelope。默认 Blocking Timeout 为 300 秒。如果 Request 返回 `504 RUN_TIMEOUT`，Execution 会继续，Caller 应轮询 Run Status。

## 5. 在可信 Terminal 中测试

使用 API Access 页面提供的请求，或按照 [Workflow API 参考](/zh-CN/api-reference/workflow-api) 操作。把 Base URL、Workflow ID、API Key 和 Document Location 放在 Environment Variable 中，不要在 Source 中硬编码。

先使用不敏感的 Fixture。确认 Response 包含 `workflow_run_id`、`status: "succeeded"`、Timing、Step 和 Result。

## 6. 查看 Usage 和 Trace

**Usage** Tab 只报告 URL Mode 和 Upload Run 的启动尝试，不统计 Health、Status、Results 或 History Request。其中提供：

- Call Count、Success Rate、Failure 和 Average Response Time；
- Retained Storage 与 Per-workflow Budget 对比；
- Status、Endpoint Kind 和 Key Filter；
- 只包含 Metadata 的 Upload Input Detail；
- Per-run Trace View。

上传文档正文和 Provider Secret 不能出现在 Usage Record 中。Filename 和 Run Metadata 也应被视为潜在敏感运行数据。

Per-workflow Storage Budget 会被实际执行，而不只是展示。超过上限时，PressRoom 会逐步清理最旧的 Terminal API Invocation Record 及其 API-forward Run Artifact，直到回到预算内。因此，被清理的 Run 可能无法再通过 Status、Results、History 或 Trace 查询找到；Retention Pressure 清理前，应把所需输出复制到 Caller 管理的存储中。

## 7. 撤销 Key

1. 根据 Description 或 Prefix 找到 Active Key。
2. 选择 **Revoke**。
3. 确认不可恢复操作。

使用该 Key 的调用会立即失败。需要无停机轮换时，应先更新 Calling System 并验证新 Key，再撤销旧 Key。

## 验证成功

- 页面显示 `Published v…` Indicator 和 Forwarding Enabled。
- Readiness 报告 Saved Workflow、Publication State、Scoped Key、Remote URL Support 和 Ownership Check；Run Query Endpoint 由单独的 Card 列出。
- 完整 Key 只存在于你的 Secret Manager 和 Calling Environment 中。
- URL 或 Upload Call 返回 Workflow Run ID 和成功 Result。
- Invocation 出现在 API Usage 中，且不包含 Source Content 或完整 Private Endpoint。
- 撤销 Test Key 后，使用它调用会收到 `401 INVALID_API_KEY`。

## 故障排查

### API Access 提示需要 Published Workflow

返回 Editor 并 Publish 一个 Saved Version。仅保存不会选择 Public Version。

### Generate Key 不可用

只有 Owner 和 Admin 可以查看和管理 Workflow API Key。确认 Active Workspace 和 Role。

### Key 收到 `WORKFLOW_MISMATCH`

Request 使用的 Workflow ID 与 Key Binding 不同。请使用该 Key 所属 Workflow 页面显示的 Endpoint，或为目标 Workflow 创建 Key。

### URL Input 在创建 Run 前被拒绝

检查 Scheme、DNS、Redirect、Target Network、Response Status、Fetch Timeout 和 Byte Limit。Fetch Guard 在 DAG Execution 前运行，因此被拒绝的 Input 不会创建半启动 Run。

### Upload 收到 `RATE_LIMIT_EXCEEDED`

退避后等待 Capacity 恢复再重试。不要让无关 Caller 共享同一个 Key；分离 Key 更便于限流和轮换。

## 下一步

- [阅读完整六端点 API Reference](/zh-CN/api-reference/workflow-api)
- [加固部署](/zh-CN/administration/security-and-troubleshooting)
- [了解 Workflow Version](/zh-CN/concepts/core-concepts)
