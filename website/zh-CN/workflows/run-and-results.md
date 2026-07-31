---
title: 运行工作流并检查结果
description: 校验并执行工作流、监控节点进度、查看输出、对比 Run 并诊断失败。
---

# 运行工作流并检查结果

Editor Run 会校验当前工作流图、绑定暂存 Input File、执行 Workflow Snapshot，并持久化 Task Status 和 Result。实时 WebSocket 更新改善当前操作体验；持久化 Snapshot 则支持断线后返回查看。

## 前置条件

- 一个有效工作流，至少包含一个 Input，并且恰好包含一个 End Node
- Input Node 上已经暂存所需文件
- 健康的 Engine 和已配置的 Provider
- 拥有 `workflow.run` 的 Workspace Role

## 1. 校验工作流图

选择 **Validation**（勾选圆圈按钮），检查 Local Structure 和 Configuration Finding。运行前修复每个 Blocking Issue。

Orphan Node 或 Engine-health Advisory 等 Warning 不会在当前 Toolbar 中触发 **Run Anyway** Dialog。决定继续前应先审查这些 Warning。

只需选择一次 **Run**。Local Graph 可执行时会直接打开 **Name this Run**；选择 **Execute** 后，Server-side Validation 仍可能在 Task 启动前返回 Structure、Port、Provider/Model 或 Engine Finding。

## 2. 命名并执行 Run

在 **Name this Run** 中添加一个便于在 Compare 和 History 中识别的标签，例如：

```text
Invoice sample — OCR baseline
```

名称是可选的；留空时使用 Task ID。选择 **Execute**。

Monitor 会显示：

- Task ID 和 Elapsed Time；
- 当前 Node 和 Overall Progress；
- 逐 Node Timeline 和 Terminal Status；
- Connection State 和 Cancellation Control。

创建 Task 或加载 Result 期间不要切换 Workspace。

## 3. 检查 Node Output

选择已完成的非 End Node，并打开其 **Result** Tab。这是定位内容从哪里开始改变或消失的最直接方法。

按从左到右的顺序检查：

1. 确认 Input Metadata 对应预期文件。
2. 确认 Preprocessing 生成了预期 Representation 或 Page Image。
3. 查看 Engine Output 和 Metadata。
4. 确认最后一个 Engine Output 到达 End。

在 API Trace Mode 中不会渲染上传的源文件。

## 4. 检查 Final Result

选择 **End** Node。当前 Tab 包括：

- **Configuration**：查看 Terminal Contract；
- **Run**：查看 Task Status 和 Control；
- **Compare**：选择此前 Run，并使用 **Diff**、**Sync** 和 **Download**；
- **History**：查看持久化 Task 和 Workflow-version Context。

对于普通 Node，PDF 和 Image-producing Result 可以显示 Visual Preview 和 Raw Data。当前 Engine Output 通常显示为带 Metadata 和 Binary Preview 的 Structured Raw JSON。大型 Stored Result 应使用 **Compare** 中的 Download，不要从 Browser 复制。

## 5. 对比并重新打开 Run

打开 **Compare** 并选择之前的 Run。前两个 Pane 支持 Diff 和 Synchronized Scrolling；更多 Pane 会各自独立滚动。

使用 **History** 或 **Recent Runs** 可以：

- 重新打开已完成 Task；
- 恢复 Result Context；
- 检查 Published Workflow Version；
- 将符合条件的 Version 恢复到 Editor。

恢复 Version 会改变 Editor 当前展示的工作流图；请先保存或处理未保存内容。

## Node-level 迭代

完成一次 Baseline Run 后，可以使用 **Run node** 获取局部反馈。Node 只有在必要 Predecessor 和 Input 可用时才能运行。End Node 不能单独运行。

对于失败 Task，**Rerun node** 可能会重试失败 Scope。Node-level Retry 后仍应重新检查完整 Workflow。

## 验证成功

- Task 进入完成的 Terminal State。
- 每个预期 Node 都报告完成，或有意跳过的 Branch 已清晰标记。
- 所选 Input Metadata 与暂存文档一致。
- End 之前存在 Node-level Output。
- Final Output Format 和 Content 符合 Workflow Contract。
- 页面刷新后仍能从 Recent Runs 或 History 找到本次运行。

## 故障排查

### 某个 Node 执行失败

选择该节点并查看 Error 和 Configuration。在 **Settings** 中检查对应 Service，或在 **Workspace Settings → Providers** 中检查 Provider。修复依赖后再重试。

### Live Progress 断开

使用 **Reconnect manually**。如果达到重连上限，刷新页面并从 **Recent Runs** 重新打开 Task。WebSocket 失败本身并不表示 Server-side Execution 已停止。

### 完成后加载 Result 失败

刷新页面，确认仍选择同一个 Workspace，然后重新打开 Task。Workspace 切换期间正在进行的 Result Request 会被刻意拒绝。

### Model Output 没有结构

查看 Node Prompt 和 **Output Schema**，确认所选 Model 支持目标 Capability，并在该 Node 的 **Result** JSON 中检查 Upstream Validation Detail。

### Result 与上一次 Run 不同

确认 Input File、Saved Workflow Version、Provider 和 Model、Node Parameter 以及 Engine Health。命名 Run 时记录这些变量，才能让 Compare 更有意义。

## 下一步

- [在 Database 上评测 Saved Workflow](/zh-CN/evaluation/databases)
- [维护版本化 Ground Truth](/zh-CN/evaluation/ground-truth)
- [发布 Workflow API](/zh-CN/publish/api-access)
