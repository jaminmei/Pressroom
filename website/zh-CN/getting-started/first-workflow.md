---
title: 运行第一个 PDF → OCR 工作流
description: 应用内置 Quick Convert 模板，上传 PDF，执行 OCR，检查结果并保存工作流。
---

# 运行第一个 PDF → OCR 工作流

本指南使用内置 **Quick Convert** 模板。它会创建 `PDF Input → Document to Image → OCR → End` 工作流，不需要外部 Model Provider。

## 前置条件

- 健康的 PressRoom `standard` 或 `full` 部署
- 拥有应用本地账号，并已选择活动 Workspace
- 一份体积较小、不含敏感信息，且包含可见文字的 PDF
- 允许创建、编辑和运行工作流的 Workspace Role（`Owner`、`Admin` 或 `Editor`）

## 1. 应用起始模板

1. 登录 PressRoom。
2. 在左侧导航中选择 **Template Center**。
3. 找到 **Quick Convert** 卡片；它的说明会标识这是 PDF 转图片再执行 OCR 的路径。
4. 选择 **Apply now**。

PressRoom 会打开 Workflow Editor，其中包含四个相连节点：

```text
PDF Input → Document to Image → OCR → End
```

![Template Center 中的 Quick Convert PDF 转 OCR 起始模板](/images/guides/template-center-ocr.webp)

应用模板会立即替换当前 Canvas。当前 Template Center 流程不会显示未保存工作确认提示，因此选择 **Apply now** 前请先保存重要内容。

## 2. 检查工作流图

依次选择节点，并在 **Inspector** 中查看配置：

- **PDF Input** 负责文件绑定。
- **Document to Image** 默认转换第 1 页。
- **OCR** 使用内置 OCR Engine，初始配置启用中文识别和方向分类。
- **End** 是最终结果入口。

连接线代表带类型的数据流：文档进入 Processor，页面图片进入 OCR，识别结果到达终止节点。

## 3. 上传 PDF

1. 选择 **PDF Input**。
2. 在 **Node Configuration** 中选择 **Choose file**，或使用上传拖放区域。
3. 选择本地 PDF。
4. 确认 Editor 提示该文档已暂存，等待随运行提交。

上传文件会随本次执行提交；在浏览器中选择文件并不会发布它，也不会让它成为模板的一部分。

## 4. 校验并运行

1. 在浮动 Toolbar 中选择 **Validation**（勾选圆圈按钮），并修复其中列出的 Blocking Issue。
2. 选择 **Run**。Local Graph 可执行时会直接打开 Run Name Dialog。
3. 在 **Name this Run** 中输入可选标签，例如 `OCR baseline`；也可以留空并使用 Task ID。
4. 选择 **Execute**。Server-side Validation 仍可能在 Execution 开始前返回 Blocking Error。

Execution Monitor 会通过 WebSocket 接收实时 Task 和节点状态。在 Task 完成前保持当前 Workspace 不变。

## 5. 检查结果

运行完成后：

1. 选择 **OCR** 节点并打开 **Result** Tab。当前 Engine Output 通常显示为带 Metadata 的 Structured Raw JSON。
2. 选择 **End**，打开其 **Run**、**Compare** 和 **History** Tab。
3. 拥有多次运行后使用 **Compare**；其 Toolbar 提供 **Diff**、**Sync** 和 **Download**。
4. 使用 **History** 重新加载之前的 Task Context。

对于文字为主的 PDF，最终输出中应包含可识别的文档文字。OCR 质量会受到页面分辨率、语言、旋转方向和源文件质量影响。

## 6. 保存工作流

1. 打开 Header 中的 **Search** Command Palette，或按 <kbd>Ctrl</kbd>/<kbd>Cmd</kbd> + <kbd>K</kbd>。
2. 选择 **Save Draft**。
3. 打开 **Workflow Studio**。如果新 Record 尚未命名，选择 **Rename**，输入有意义的名称，例如 `Invoice OCR baseline`。
4. 确认已保存工作流及其 Latest Version 已经出现。

保存会为活动 Workspace 创建共享工作流记录，但不会让工作流可以通过公开 API 调用；公开调用还需要单独执行 **Publish**。

## 验证成功

满足以下全部条件即表示本指南完成：

- 工作流图包含一个 Input 和一个 `End` 节点；
- 校验没有阻断问题；
- 运行进入完成状态；
- 结果视图中可以看到 OCR 内容；
- 工作流出现在 **Workflow Studio** 中。

## 故障排查

### Run 不可用

选择 PDF Input 并确认文件已经暂存，然后检查所有节点是否相连，并确保恰好存在一个 `End` 节点。

### 校验报告 Engine 离线

打开 **Settings** 查看 OCR Engine 健康状态。在 Host 上运行：

```bash
docker compose --profile standard ps ocr-engine backend
```

如有需要，只查看受影响服务的日志，并且不要公开分享其中的文档内容。

### 运行完成，但 OCR 文字质量不佳

尝试使用更高分辨率的源文件、启用合适的 OCR 语言，或在 OCR 前增加 Image Enhancement 和 Rotation Processor。对于复杂表格和混合版面，可在配置 Provider 后对比 OCR 与 Vision Model。

### 系统提示存在更新的工作流版本

这表示另一个 Saved Version 已经存在。**Refresh latest** 会加载该版本；**Keep local draft** 会延后决定。对于 Owner 或 Admin，Banner 中的 **Save As new name** 当前实际会打开 **Publish As**，创建并发布一个独立 Workflow；只有确实需要该结果时才使用。

### Task 丢失实时更新

使用手动重连操作，或从 **Recent Runs** 重新打开该运行。即使浏览器 WebSocket 断开，已完成 Task 的 Snapshot 和结果仍会持久化。

## 下一步

- [了解 Editor 与节点规则](/zh-CN/workflows/editor-and-nodes)
- [配置 OpenAI-compatible Model Provider](/zh-CN/workflows/providers)
- [为批量评测创建 Database](/zh-CN/evaluation/databases)
