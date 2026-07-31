---
title: Model Providers
description: 配置工作空间级 OpenAI-compatible 或 Azure OpenAI Provider，管理 Model，并应用网络安全策略。
---

# Model Providers

Model Provider 将 PressRoom 工作流连接到 OpenAI-compatible Vision Service。它们按 Workspace 隔离、加密保存，并通过本地 VLM Adapter 调用。内置 Engine Service 在 **Settings** 中单独显示，不需要把凭据复制到 Workflow。

## 前置条件

- 活动 Workspace
- 管理 Provider 所需的 `Owner` 或 `Admin` Role
- Backend 和 VLM Adapter 能够访问的 Provider Base URL
- 保存在 Source Control 之外的 Secret
- 对于 Azure OpenAI，需要 Azure Resource 提供的 API Version 和 Deployment Name

## 1. 打开 Provider Settings

打开 Workspace Switcher，选择 **Workspace Settings**，然后选择 **Providers**。应用的直接 Route 是 `/settings/workspace/providers`。

页面分为：

- **Workspace Providers**：有权限的 Workspace 成员可以管理；
- **System Providers**：由 Environment 管理，在此视图中只读。

![Workspace Provider 配置表单](/images/guides/provider-configuration.webp)

## 2. 添加 OpenAI-compatible Provider

1. 选择 **Add Provider**。
2. 输入清晰的 **Name**。
3. 将 **API Style** 设置为 **OpenAI-compatible**。
4. 选择所需的 **Auth Type**——通常为 **API Key**；仅对于明确无认证的服务才使用 **None**。
5. 输入该服务明确的 **Base URL**。
6. 创建时输入 API Key。
7. 选择 **Create**。

PressRoom 不会替换为 Deployment-wide Upstream URL。每条 Provider Record 都有明确的 Base URL。

在当前 UI 中展开 **Show Models**，选择 **Add Model**，并输入准确的 Upstream Model ID。只启用工作流需要的 Model，然后测试 Model 和 Provider Connection。

## 3. 添加 Azure OpenAI Provider

1. 选择 **Add Provider**。
2. 将 **API Style** 设置为 **Azure OpenAI**。
3. 把 Azure Endpoint 填入 **Base URL**。
4. 输入必需的 **Azure API Version**。
5. 选择 **API Key** 并提供凭据。
6. 创建 Provider。
7. 选择 **Add Model**，手动输入每个 Azure Deployment Name。

Azure OpenAI Deployment 不会从 `/models` 自动发现；PressRoom 会把 Deployment Name 作为 Model Identifier 通过 Adapter 发送。

## 4. 测试并启用 Model

在 Provider Card 上使用 **Test Connection**。展开 **Show Models** 后可以：

- 添加或移除 Model；
- 启用或禁用 Model；
- 执行 Model-level Test；
- 查看逐 Model 健康状态。

当某个 Provider 应成为其 Engine Category 的首选时，将它设置为 **Default**。如果恰好只有一个 Enabled Model，新工作流可以自动选中；否则请在 Model Node 中选择 Provider 和 Model。

## 5. 在 Workflow 中使用 Provider

1. 应用 **Custom Workflow**，或添加一个 Model Node。
2. 选择 Model Node。
3. 在 **Node Configuration** 中选择 Provider。
4. 选择一个已启用且支持 Vision 的 Model。
5. 查看 Prompt 和 Structured Output Schema。
6. 运行校验，然后使用不敏感的测试文档执行。

凭据会在调用时解析。Workflow Definition 包含 Provider/Model Reference 和 Node Parameter，不包含解密后的 Secret。

## 私有网络策略

`PROVIDER_ALLOW_PRIVATE_HOSTS=true` 允许 Provider Destination 位于 Private 或 Loopback Network，适合本地服务。这是由 Operator 控制的信任决定。

即使允许 Private Host，PressRoom 仍会阻止 Link-local 和 Cloud Metadata Destination、Reserved 和 Multicast Address、Unspecified Destination 及 DNS Rebinding。

对于不受信任的 Multi-tenant Deployment，请设置：

```dotenv
PROVIDER_ALLOW_PRIVATE_HOSTS=false
```

除非 Deployment Threat Model 明确要求并且你已经评估后果，否则不要禁用 TLS Certificate Verification。

## 轮换 Credential

1. 从 Provider 创建或取得替换 Credential。
2. 编辑 PressRoom Provider。
3. 输入新 Key；留空会保留现有加密 Key。
4. 保存并测试 Provider 和一个 Model。
5. 撤销旧 Upstream Credential。

绝不能把 Credential 粘贴到 Node Prompt、Workflow JSON、截图、Issue Report 或 Browser Code 中。

## 验证成功

- Provider Card 位于 **Workspace Providers** 下。
- **Test Connection** 报告 Healthy，或显示成功的 Model Result。
- 至少一个目标 Model 已启用。
- Model Node 可以选择该 Provider 和 Model。
- 测试 Run 可以完成，且 Configuration 与 Result View 中不出现 Credential。

## 故障排查

### 添加的 Model 无法通过测试

当前 UI 采用手动登记 Model ID。Azure OpenAI 应输入 Deployment Name；其他兼容服务应先确认准确的 Model ID、Base URL 和 Credential Scope，再运行 Model-level 或 Provider Connection Test。

### Connection Test 失败

检查 Backend/VLM Adapter 可访问性、Base URL 结构、DNS、TLS Trust、Auth Type 和 Key Scope。不要在公开 Issue 中发布完整 Private Base URL 或 Authorization Header。

### Private 或 Loopback Destination 被阻止

确认 Operator 确实为该部署设置了 `PROVIDER_ALLOW_PRIVATE_HOSTS=true`。Link-local 和 Metadata Destination 仍然会被阻止，不能绕过。

### Provider 存在，但 Model Node 中没有

确认 Provider 属于活动 Workspace、其 Model 已启用，并且你的 Role 拥有 `provider.use`。切换 Workspace 后重新加载 Workflow。

### 编辑时已有 Key 消失

这是预期行为。PressRoom 绝不会把已存储 Secret 重新填入表单。Key 字段留空可保留原值，输入新值则会替换。

## 下一步

- [构建并配置 Model Node](/zh-CN/workflows/editor-and-nodes)
- [运行并对比输出](/zh-CN/workflows/run-and-results)
- [查看安全基线](/zh-CN/administration/security-and-troubleshooting)
