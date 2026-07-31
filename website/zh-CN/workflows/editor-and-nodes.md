---
title: Workflow Editor 和节点
description: 构建有效的带类型工作流、配置节点、理解连接规则，并安全地保存或发布版本。
---

# Workflow Editor 和节点

Workflow Editor 是一个带类型约束的 DAG Canvas。工作流图就是可执行配置：Node Type、Port Compatibility、Edge 和基于 Schema 的设置共同决定 PressRoom 如何执行。

## 前置条件

- 活动 Workspace
- 创建或编辑工作流的权限
- 计划使用的 Node Type 所对应的内置 Engine 处于健康状态
- Model Node 所需的已配置 Provider

如果这是你的第一个工作流图，请先使用 [Quick Convert](/zh-CN/getting-started/first-workflow)。

## 了解 Canvas

主要界面区域包括：

- **Canvas**：Node 和 Connection 在此定义数据流；
- Floating Toolbar：包含 **Run**、**Validation**、Clear、Template、Version、Publish 和 Restore 操作；
- **Inspector**：显示选中节点的 Configuration 或 Result；
- **Monitor**、**Compare** 和 **History** Panel：用于执行和审核。

选择一个节点可以查看其当前配置和兼容数据类型。

## 添加 Node

有三种添加方式：

1. 选择 **Add node** 并搜索 Registry。
2. 使用 Endpoint 的新增操作，选择兼容的 Upstream 或 Downstream Node。
3. 在现有 Connection 上插入兼容 Node；Editor 会自动重连这条 Edge。

基于 Endpoint 的菜单会过滤不兼容选项。如果没有可选项，可能是当前 Port 已达到连接上限，或没有已注册 Node 接受该类型。

## 连接工作流图

从 Source Endpoint 拖动到 Target Endpoint，或使用 Endpoint Picker。Editor 会验证：

- Node 不能连接自己；
- 不允许重复 Edge；
- Output 和 Input Type 必须兼容；
- Port 不能超过最大连接数量；
- 工作流图不能存在 Cycle；
- `End` 不能拥有 Downstream Connection。

Type 不兼容的 Connection 会被拒绝，不会保留为 Warning Edge。Orphan Node 可以留在 Canvas 上，并作为 Non-blocking Warning 报告，但不会参与执行。

## 配置常见 Node Family

### Input Node

选择 Input，并在 **Node Configuration** 中暂存文件。系统会在执行前检查支持类型和大小。一个工作流至少需要一个 Input Node。

模板会在 Saved Definition 中使用文件 Placeholder；实际上传路径属于 Run，而不是可复用 Workflow。

### Processor Node

Processor 会在推理前改变数据表示。常见用途包括：

- 把 PDF 页面转换成图片；
- 检测版面区域；
- 增强低质量扫描件；
- 纠正图片方向。

按顺序放置 Processor，确保其 Output Type 能满足下一个节点。

### Engine Node

Engine 配置由 Node Registry 和 Provider Schema 提供。内置 OCR 与转换 Engine 使用 System-managed Service Provider。Model Node 需要 Workspace 级 `openai_compatible` Provider 和已启用 Model。

如果存在多个 Enabled Model，请明确选择。如果恰好只有一个可用模型，新工作流可能自动选中；当候选为零个或多个时，不要假设系统已经选择。

### End Node

有效工作流恰好包含一个 `end/final` Node。多个 Upstream Branch 可以连接到它；Final Result View 会成为这些终止输出的入口。

`End` 不能单独运行。

## 执行前校验

选择 **Validation**（勾选圆圈按钮）检查当前工作流图。需要修复的 Blocking Issue 包括：

- 缺少 Input 或 Final Node；
- 存在多个 Final Node；
- 缺少必填配置；
- Model Node 没有 Provider；
- Connection Type 不兼容；
- 存在 Cycle。

Orphan Node 和 Engine Health 可能显示为 Advisory Warning。当前 Toolbar 不会因为 Warning 显示 **Run Anyway** Confirmation；Local Graph 没有 Blocking Issue 时，**Run** 会打开 Name Dialog，但 Server-side Validation 仍可能拒绝 **Execute**。

## 运行单个节点

如需局部迭代，请选择允许单独运行的节点，然后选择 **Run node**。它的必要 Predecessor 必须已经完成，所需 Input 也必须暂存。Input、Output 和 End Node 存在运行限制；完整 Workflow Run 仍是权威的端到端检查。

持久化 Task Context 支持时，可以重新运行失败节点。Monitor 会标识 Retry Scope。

## 保存和发布

- Header **Search** Command Palette（<kbd>Ctrl</kbd>/<kbd>Cmd</kbd> + <kbd>K</kbd>）中的 **Save Draft** 会写入新的 Shared Saved Version。
- **Publish** 选择公开调用版本，需要 Owner 或 Admin 权限。
- **Publish As** 在适用时创建并发布另一个 Workflow。

发布未发生变化的 DAG 时，系统可能提示与当前 Published Version 相比没有结构变化。

## 验证成功

在把工作流图视为就绪前：

1. 校验没有阻断问题。
2. 每个 Branch 都从带类型 Input 开始，并终止于唯一 End Node。
3. 需要的 Provider 和 Model 已明确选择。
4. 代表性文件可以成功完成。
5. Node-level Output 和 Final Output 使用预期格式并包含预期内容。
6. 目标 Saved Version 在 Workflow Studio 中可见。

## 故障排查

### Connection 被拒绝

阅读 Editor 显示的原因。检查方向、Source Output Type、Target Input Type 和 Port Capacity。在两个节点之间增加 Converter 或 Processor 可能解决 Type Mismatch。

### Node Type 未知

Saved Definition 引用了当前 Node Registry 中不存在的类型。确认对应 Engine 或可选 Registry Module 已安装且健康；否则请用受支持类型替换该 Node。

### Model Configuration 为空

打开 **Workspace Settings → Providers**，启用至少一个 Model 并执行测试。返回 Model Node，同时选择 Provider 和 Model。

### Save 报告存在更新版本

不要直接覆盖。**Refresh latest** 会加载 Shared Version；**Keep local draft** 会延后选择。对于 Owner 或 Admin，**Save As new name** 当前实际调用 **Publish As**，因此会创建并发布独立 Workflow，而不是保存另一个 Draft。

### Final Output 为空

先检查最后一个 Engine Node。如果该节点有输出，确认其 Output 已连接到 End；如果没有，请沿 Node Result 反向查找第一个为空或失败的步骤。

## 下一步

- [配置 Model Provider](/zh-CN/workflows/providers)
- [监控 Run 并查看结果](/zh-CN/workflows/run-and-results)
- [创建 Database 评测](/zh-CN/evaluation/databases)
