---
title: 核心概念
description: 了解 PressRoom 中 Workspace、Workflow、Node、Provider、Run、Database、Ground Truth 和已发布 API 之间的关系。
---

# 核心概念

PressRoom 使用一组明确的资源边界，让工作流编排、执行、评测和外部访问保持清晰。最重要的边界是活动 Workspace：几乎所有资源和权限都在其范围内进行判断。

## Workspace

**Workspace（工作空间）** 是以下资源的协作与隔离边界：

- 成员和 Role；
- 工作流和版本；
- Database、文档、Ground Truth 和评测运行；
- 工作空间级 Model Provider；
- Workflow API Key 和使用 Trace。

Workspace Switcher 决定当前活动范围。切换 Workspace 会改变应用能够解析的资源，而不是对全局列表应用一个视觉筛选条件。

### Role 概览

| Role | 适用场景 |
| --- | --- |
| `Owner` | 完全控制，包括删除 Workspace 和转移所有权。 |
| `Admin` | 日常管理、发布、Provider、成员、API Key 和 Workspace Settings。 |
| `Editor` | 构建工作流、管理 Database 与文档、编辑 Ground Truth 并运行评测。 |
| `Runner` | 运行工作流和评测并查看结果，但不能编辑资源。 |
| `Viewer` | 对资源和结果进行只读访问。 |

Backend 会强制执行 Capability。UI 中禁用或隐藏的控件只是同一授权结果的呈现，并不是安全边界本身。

## Workflow 和 Version

**Workflow（工作流）** 是已保存并命名的 DAG，其定义包含节点、连接和节点配置。

PressRoom 区分三种状态：

- **Unsaved Draft（未保存草稿）** 是当前 Editor 中的工作，并不是共享事实来源。
- **Saved Version（已保存版本）** 可供 Workspace 使用，也可以选择用于评测。
- **Published Version（已发布版本）** 记录最近一次 Publish 的 Version，并解锁公开 API 访问。

保存和发布解决不同问题。与团队迭代时先保存；只有准备好向 Workflow-scoped API Caller 开放工作流时才 Publish。在当前版本中，Publish State 是访问门禁：新的公开 Run 会解析 Workflow 的 Current Saved Definition，而不是加载不可变的 Published Snapshot。

## Node 和 Connection

**Node（节点）** 执行一个带类型约束的步骤。节点定义来自 Backend Registry，其中提供输入/输出类型、连接规则和基于 Schema 的配置。

标准节点 Family 包括：

| Family | 示例 | 在工作流图中的作用 |
| --- | --- | --- |
| Input | PDF Input、Image Input | 绑定本次运行的源文件。 |
| Processor | Document to Image、Enhancement、Rotation | 在进入 Engine 前转换数据。 |
| Engine | OCR、Model、Text、MarkItDown、Docling、Layout Detection | 生成文档理解或转换输出。 |
| End | End | 汇集工作流最终结果。 |

**Connection（连接）** 把节点输出路由到兼容的 Input Port。Validator 会拒绝循环、缺失节点、超出端口连接数量、不兼容类型，以及没有且仅有一个 Final Node 的工作流图。

## Engine 和 Provider

**Engine Service** 实现 PressRoom 的 `/process`、`/health` 和 `/config` 服务契约。内置 Compose Engine 覆盖 OCR、本地 VLM Adapter、Text、MarkItDown、Docling、Layout Detection、Image Enhancement 和 Image Rotation。

**Provider** 告诉节点应该在何处、以何种方式调用能力：

- `engine_service` Provider 会通过 Engine `/process` 契约直接调用。
- `openai_compatible` Provider 会通过本地 VLM Adapter 调用；Adapter 会为本次请求选择标准 OpenAI-compatible 或 Azure OpenAI 行为。

Workspace Provider 凭据会加密保存。凭据只在调用时解析，不能复制到节点配置、工作流定义、Trace 或日志中。

## Task Run 和 Result

**Task Run** 是使用特定输入和 Workflow Snapshot 执行一次工作流的记录。它跟踪节点进度、Event、终止状态、耗时和生成结果。

Editor 通过 WebSocket 获取活动 Task 更新，并持久化 Run Snapshot 供以后访问。节点级输出有助于诊断 Pipeline；`End` 节点是最终结果入口。

公开 API 调用同样会创建 Task Run。API 把 Task ID 称为 `workflow_run_id`，但二者指向同一个持久化执行标识。

## Database 和 Document

**Database** 是一个评测集合（Backend 的部分内部 Route 仍保留历史名称 `test-set`）。它拥有：

- 上传的源文档；
- 针对选定文档的评测运行；
- 逐文档 Run History；
- Ground Truth 版本。

它与作为基础设施运行的 PostgreSQL 服务不是同一个概念。

## Ground Truth 和 Comparison

**Ground Truth** 是一份文档的预期内容。版本只追加、不覆盖：手动上传 JSON 或接受评测结果都会创建新版本，而不会改写历史。

评测过程中，每个结果可能：

- 与当前 Ground Truth 匹配；
- 与其不同；
- 因 Ground Truth 缺失或不可用而没有对比；
- 在执行过程中失败或跳过。

结果审核是明确操作。**Accept as Ground Truth** 会把该输出提升为新版本；**Reject** 只记录审核，不会替换现有 Ground Truth。

## Published API 和 API Key

**Published Workflow API** 在 Workflow 存在 Published Version 后才可调用。当前版本执行 Current Saved Definition，并支持远程 URL 输入和 Multipart 文件上传。

一个 **API Key**：

- 只绑定到一个工作流；
- 只在创建时完整返回一次；
- 由 API Key Service 以 Hash 形式保存；
- 可以立即撤销；
- 不会授予 Browser Session 的管理访问权限。

公开 `/api/v1` Runtime 与使用 Session 认证的 `/api` 管理界面被刻意分开。

## 完整生命周期

```text
Workspace
  ├─ Provider ───────────────┐
  ├─ Workflow → saved version → run → result
  │                    └──────→ publication gate → scoped API key → API run
  └─ Database → document → Ground Truth versions
                    └────→ evaluation run → compare → accept/reject
```

## 验证你的理解模型

构建生产工作流前，确认你能够回答：

1. 哪个 Workspace 拥有该 Workflow 和 Provider？
2. 正在评测哪个 Saved Version？
3. 当前发布的是哪个 Version？
4. 哪一份 Document 和 Ground Truth Version 生成了这次 Comparison？
5. 哪个 Workflow 拥有 API Key 和由此产生的 Run？

这些标识是诊断异常访问或输出时最快的入口。

## 概念相关故障排查

- 如果切换 Workspace 后某个资源似乎丢失，请先确认活动 Workspace，不要立即重新创建。
- 如果编辑功能不可用，请将所需操作与当前成员 Role 对照。
- 如果 Model Node 没有选项，请检查 Enabled Model 和 Provider Default。
- 如果 API 输出与 Editor 不同，请确认当前发布的是哪个 Workflow Version。
- 如果评测显示 `No GT`，请为对应 Document 添加或接受 Ground Truth。

## 下一步

- [使用 Workflow Studio 和模板](/zh-CN/workflows/studio-and-templates)
- [使用 Editor Node 构建工作流](/zh-CN/workflows/editor-and-nodes)
- [配置评测 Database](/zh-CN/evaluation/databases)
