---
title: Database 与批量评测
description: 创建可复用文档 Database、上传 Fixture、对所选文件运行已保存工作流，并审核逐文档结果。
---

# Database 与批量评测

PressRoom **Database** 是按 Workspace 隔离的评测集合。它把文档、评测运行、结果对比和 Ground Truth 放在一起，因此可以用稳定的数据集衡量工作流变化。

## 前置条件

- 活动 Workspace
- 该 Workspace 中一个已保存的 Workflow
- 创建 Database 和上传 Document 所需的 `Owner`、`Admin` 或 `Editor` Role
- 启动 Run 所需的 `Owner`、`Admin`、`Editor` 或 `Runner` Role
- 具有代表性且不敏感的 PDF、PNG、JPEG 或 WebP 文件

Database Upload 使用 Backend 的 `MAX_FILE_SIZE_MB` 设置，默认每份文档 50 MiB。Stock Compose 不会从 `.env` 映射该变量；除非 Deployment 同时把它传入 Backend Environment，否则只修改 `.env` 不会生效。

## 1. 创建 Database

1. 在产品顶部导航中选择 **Database**。
2. 选择 **Create Database**。
3. 输入面向任务的名称，例如 `Synthetic invoices — regression`。
4. 添加 Description，记录文档来源、目标工作流和审核目的。
5. 选择 **Create**。

新 Database 会在所属 Workspace 中打开。产品的部分内部 API Route 仍可能保留 `test-set` 名称；面向用户的资源名称是 **Database**。

## 2. 上传文档

1. 打开 **Documents** Section。
2. 选择 **Upload**。
3. 选择一个或多个受支持文件。
4. 确认每个文件都显示 Type、Size、Upload Time 和 Ground Truth Status。

比较 Workflow Version 时，请使用确定性 Fixture。不要在同一个 Database 中混入无关的 Document Family；稳定且说明清晰的数据集能让 Pass Rate 更有意义。

![Database 文档与 Ground Truth 工作流](/images/guides/database-ground-truth.webp)

选择 Document Row 可以打开 Preview 和 Detail。浏览器能否预览取决于文件类型，但源文件仍可供 Evaluation Runtime 使用。

## 3. 选择 Run Document

选择 Document Row，然后选择 **Run Workflow**。也可以打开 **Runs** Section 并选择 **New Run**。

在 Run Configuration 页面：

1. 从活动 Workspace 中选择一个已保存的 **Workflow**。
2. 输入可选的 **Run Name**，例如 `OCR v3 — July baseline`。
3. 搜索并选择一个或多个 Document。
4. 检查 Selected Count 和 Workflow Summary。
5. 选择动态显示的 **Run _N_ documents** 按钮，其中 _N_ 是 Selected Count。

Backend 会为本次 Evaluation 创建 Current Workflow Definition Snapshot。如果 Workflow 已有 Published Version，本次 Run 会关联该 Version Number；否则使用 Latest Saved Version。在当前版本中，关联的 Published Number 可能早于 Snapshot 中的 Saved Definition，因此应把 Snapshot 视为执行事实来源。之后的 Workflow Edit 不会改写已有 Run。

一个 Database 同一时间只允许一个活动 Evaluation Run。等待当前 Run 进入 Terminal State 后再启动下一个。

## 4. 监控进度

创建后，PressRoom 会返回 Database 并显示 Live Progress。逐 Document State 包括 Queued、Running、Completed、Failed 和 Skipped。

`standard` Profile 在应用 Runtime 中调度串行/后台 Evaluation Execution。启用 Queue Mode 后，`full` Profile 可以通过 Redis 和 Celery 分发评测工作。

你可以离开当前 View，稍后从 **Runs** 重新打开本次运行。Status 和 Result 都会持久化。

## 5. 审核结果

打开 Completed Run 可以查看：

- Workflow Name 和 Run Timing；
- Document Count 和 Execution Summary；
- 能够执行对比的 Document Pass Rate；
- 每个 Document 的 Execution、Ground Truth、Comparison 和 Review Status。

选择 Result Row，将 UI 中的 **Original / Ground Truth** 列与 **OCR Output** 并排对比。即使所选 Workflow 并非 OCR-based，当前第二列仍使用该标签。没有 Ground Truth 的结果会标记为 `No GT`，不会算作 Match。

只有在检查实际内容后才使用 **Accept as Ground Truth**；该操作会创建新的 Ground Truth Version。**Reject** 会记录该输出不应成为 Ground Truth。

## 构建有效的评测数据集

- 比较 Workflow Version 时保持 Source Document 不变。
- 纳入与你使用场景相关的干净、含噪、旋转、表格密集和混合版面示例。
- 使用 Workflow Version、Provider/Model 和重要 Parameter 命名 Run。
- 在依赖 Pass Rate 之前添加 Ground Truth。
- 把 Execution Failure 与 Content Difference 分开审核；执行失败不是 Comparison Mismatch。

## 验证成功

- Database 仅在所属 Workspace 中可见。
- 上传文档显示预期 Filename、MIME Type 和 Size。
- Run 记录所选 Workflow 和 Document Count。
- 每份 Document 的 Progress 都进入 Terminal State。
- 刷新页面后，Completed Result 仍能从 **Runs** 查看。
- 有 Ground Truth 的 Document 显示 `Pass` 或 `Differs`；缺少 Ground Truth 时显示 `No GT`。

## 故障排查

### 上传只完成了部分文件

Backend 可以同时返回成功文件和逐文件 Error，但当前 UI 不会显示该 Error Array，并且 Success Message 使用的是所选文件数。如果实际出现的 Document 少于预期，请检查不支持的 MIME Type、空内容和 File-size Limit，再逐个重试不确定的文件。

### 没有可选 Workflow

在同一活动 Workspace 中保存一个 Workflow。清空 Workflow Search 并确认 Workspace Selection。Evaluation 不能绑定其他 Workspace 所拥有的 Workflow。

### 新 Run 返回 Conflict

该 Database 已有另一个活动 Evaluation。打开 **Runs**，等待它完成或失败，再创建下一次 Run。

### Pass Rate 缺失

Pass Rate 根据 Matched 和 Mismatched Comparison 计算。为相关 Document 添加 Ground Truth，然后重新运行 Workflow。

### Full Profile 中 Run 一直处于 Queued

确认 Redis 和 `celery-worker` 健康、`ORCHESTRATOR_MODE=queue`、`ENABLE_QUEUE_MODE=true`，并且 Backend/Worker Runtime Configuration 一致。

## 下一步

- [创建并审核 Ground Truth Version](/zh-CN/evaluation/ground-truth)
- [对比 Editor Run](/zh-CN/workflows/run-and-results)
- [选择 Standard 或 Queue Execution](/zh-CN/deployment/compose)
