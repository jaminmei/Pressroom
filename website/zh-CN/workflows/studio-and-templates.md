---
title: Workflow Studio 和模板
description: 从精选工作流模板开始，导入定义，并在 Workflow Studio 中管理已保存工作流。
---

# Workflow Studio 和模板

**Template Center** 是创建有效工作流图最快的入口，**Workflow Studio** 则是已保存工作流的资源库。两者结合使用：先从可靠的 Topology 开始，在 Editor 中调整，然后保存到活动 Workspace。

## 前置条件

- 已登录用户和活动 Workspace
- 创建及修改工作流所需的 `workflow.create` 与 `workflow.edit_draft` Capability
- 如果准备使用 Model 模板，需要一个已启用 Vision Model 的 Provider

## 选择内置模板

从 Sidebar 打开 **Template Center**。PressRoom 内置三个起始模板：

| 卡片 | Topology | 适用场景 |
| --- | --- | --- |
| **Quick Convert** | PDF → Page Image → OCR → End | 不使用模型的首次运行，以及文字为主的文档。 |
| **Custom Workflow** | PDF → Page Image → Model → End | 复杂版面、表格或结构化 Vision Model 提取。 |
| **Multi-Engine Compare** | PDF → Page Image → OCR 和 Model → End | 对同一源文件比较两种处理方式。 |

在卡片上选择 **Apply now**。模板会本地化、复制到 Editor Store，并以可编辑 Draft 打开；系统不会自动保存它。

应用模板会立即替换当前 Canvas 上的全部节点；当前 Template Center 流程不会显示未保存工作确认提示。请先保存重要内容。

## 调整起始模板

应用模板后：

1. 逐个选择节点并查看 **Node Configuration**。
2. 确认文档页码选择和预处理选项。
3. 对于 Model Node，选择一个 Workspace Provider 和已启用、支持 Vision 的 Model。
4. 根据需要增加、删除或重新连接节点，同时保留一个终止 `End` 节点。
5. 上传安全的样本文档，并在保存前运行校验。

内置模板是 Baseline，并不是不可修改的产品配方。

## 导入 Workflow JSON

已有工作流定义时，可在 Template Center 使用 **Import**。

Importer 需要包含 `nodes` 和 `connections` Array 的 JSON。它会尽可能修复 Final Node 结构，并在 Editor 中打开结果。导入不会绕过 Node Registry 或连接校验。

导入来自其他人的定义前：

- 查看 Provider 引用和 Prompt；
- 删除本地文件路径与环境特定值；
- 确认本部署已注册全部 Node Type；
- 把嵌入内容视为不受信任的配置。

无效 JSON、缺失 Array 或空 Node List 会被拒绝，而且不会替换当前工作流图。

## 导出模板定义

在模板卡片上选择 **Export**，可以下载包含模板名称、节点和连接的 JSON。导出的定义不包含 Provider Secret；但 Node Prompt 和 Workflow Structure 仍可能涉及你的使用场景，公开前应仔细检查。

## 保存到 Workflow Studio

在 Editor 中：

1. 打开 Header 中的 **Search** Command Palette，或按 <kbd>Ctrl</kbd>/<kbd>Cmd</kbd> + <kbd>K</kbd>。
2. 选择 **Save Draft**。
3. 打开 **Workflow Studio**，使用 **Rename** 设置或完善 Workflow Name 和 Description。
4. 搜索已保存名称，并确认 Latest Version。

Workflow Studio 允许有权限的成员打开、重命名已保存工作流，查看 Latest/Published Version 标记，并删除工作流。删除不可恢复，其权限也比编辑更加严格。

## 处理版本冲突

Saved Workflow Version 是共享的。如果另一位成员保存了更新版本，而你的 Local Draft 仍基于旧版本，Editor 会报告冲突，不会静默覆盖新版本。

请明确选择：

- **Refresh latest**：用最新 Shared Version 替换 Editor 内容。
- **Keep local draft**：延后决定，不修改 Server Version。
- 对于 Owner 或 Admin，**Save As new name** 当前实际会打开 **Publish As**，创建并发布一个独立 Workflow；它不是只保存 Draft 的操作。

不要把 Publish 当作版本冲突解决方式。

## 验证成功

- 应用模板会在 Editor 中打开已连接的工作流图。
- 没有可用模型时，Model 模板会明确提示选择 Provider/Model。
- 保存后，工作流会出现在 Workflow Studio 中。
- 重新打开工作流会恢复其 Saved Node 和 Connection。
- 在有权限的成员发布 Version 前，不会显示 Published Badge。

## 故障排查

### 模板打开后显示 Provider 警告

OCR 模板使用内置 Engine；Model 模板需要已配置并启用的 Model。请先按照 [Model Providers](/zh-CN/workflows/providers) 完成配置，然后返回节点进行明确选择。

### Import 报告 Schema 无效

确认顶层 Object（或其中的 Workflow Definition）包含非空 `nodes` 和一个 `connections` Array。只能导入当前 Registry 支持的 Node Type。

### 看不到已保存工作流

检查活动 Workspace，并清空 Workflow Studio Search。工作流按 Workspace 隔离。

### Rename 或 Delete 不可用

Editor 可以重命名 Saved Workflow。按照当前 Capability Matrix，Delete 需要 Owner 或 Admin。Publish 在 Workflow Editor 中执行，不在 Workflow Studio List 中执行，并且同样需要 Owner 或 Admin。

## 下一步

- [了解节点配置和连接规则](/zh-CN/workflows/editor-and-nodes)
- [运行并检查工作流](/zh-CN/workflows/run-and-results)
- [发布 API Access](/zh-CN/publish/api-access)
