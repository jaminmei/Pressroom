---
title: Ground Truth
description: 为评测文档添加预期内容、查看只追加版本、对比结果，并接受或拒绝审核后的输出。
---

# Ground Truth

Ground Truth 是一份 Database Document 的预期内容。PressRoom 按 Document 保存，并采用只追加方式：手动上传和接受 Result 都会创建新版本，而不是修改旧记录。

## 前置条件

- 一个至少包含一份上传 Document 的 Database
- 查看 Ground Truth 所需的 `ground_truth.view`
- 上传或审核 Ground Truth 所需的 `Owner`、`Admin` 或 `Editor` Role
- 一个 `.json` 文件；当前 UI 会把内容作为 Text 读取和保存，但不会校验 JSON Syntax

## 手动添加 Ground Truth

1. 打开 Database。
2. 选择 **Ground Truth**。
3. 使用 Radio Control 选择 Document。
4. 选择 **Upload GT**。
5. 选择包含预期输出的 `.json` 文件。

当前 UI 接受 `.json` Extension，把文件作为 Text 读取，并创建 `json` Format、`manual` Source 的新 Ground Truth Version。UI 和该 Endpoint 当前都不会拒绝无效 JSON Syntax；需要 Structured Display 时，请另行校验文件。

请使用与 Workflow 预期输出一致的 Shape。例如：

```json
{
  "invoice_number": "<expected-number>",
  "currency": "<expected-currency>",
  "total": "<expected-total>"
}
```

公开示例使用 Placeholder，共享 Fixture 使用合成数据。Ground Truth 属于应用数据，可能包含敏感文档内容。

## 查看 Document Version

可以从两个位置查看 Ground Truth：

- **Ground Truth** 汇总 Approved、Pending 和 Missing Document。
- 在 **Documents** 下选择 Document，可以打开其 Ground Truth Tab，查看 Current Version、Source、Format、Timestamp、Note、Content 和 Version History。

选择 Historical Version 只会读取内容。Current Marker 标识未来 Comparison 会使用的最新版本。

## 对比 Evaluation Result

1. 对 Database 中的 Document 运行已保存 Workflow。
2. 打开 **Runs** 并选择 Completed Run。
3. 选择一条 Document Result。
4. 将 **Original / Ground Truth** 与 **OCR Output** 并排审核。即使 Workflow 并非 OCR-based，Actual-output Column 当前仍使用该标签。

PressRoom 会记录可比较内容是 Matched 还是 Mismatched。如果 Ground Truth 缺失，Result 为 `No GT`，不会被视为失败或通过。

## 接受 Output 为新版本

当 Actual Result 正确且应成为新的预期内容时，选择 **Accept as Ground Truth**。

PressRoom 会：

1. 使用 Result 的 Output Content 和 Format 创建新的 Ground Truth Version；
2. 将其链接到 Source Task Run；
3. 把 Evaluation Result 标记为 Accepted；
4. 将该已审核 Result 的 Comparison 记录为 Matched。

旧 Ground Truth 会保留在 Version History 中。

## 拒绝 Output

当 Actual Result 不应成为 Ground Truth 时，选择 **Reject**。当前 UI 会记录 Rejected Review Status，但不会要求输入 Reason，也不会删除或替换当前 Ground Truth。

修复 Workflow 或 Provider Configuration，重新运行，再比较新 Result。

## Versioning 实践

- 把 Manual Ground Truth 当作审核后的数据，而不是任意预期字符串。
- 同一 Document 的不同 Version 使用一致 Output Format。
- 接受 Result 前检查完整 Actual Content。
- 命名 Evaluation Run，让 Accepted Version 的来源容易理解。
- 比较 Model 或 Workflow Change 时保持 Deterministic Document Set。
- 根据 Retention Policy 导出或备份应用数据；Version History 不能替代基础设施备份。

## 验证成功

- Upload 成功后重新加载或重新进入 Database，因为当前 Ground Truth View 不会自动刷新；之后 Document 应从 Missing 变为 Approved。
- Document Panel 显示 Current Version 和 Stored Content；有效 JSON 会进行格式化显示。
- 新 Manual Upload 会增加 Version，而不是覆盖历史。
- 有 Ground Truth 的 Evaluation Result 显示 Matched 或 Mismatched Content。
- 接受审核后的 Output 会添加与 Run 关联的 Version。
- Reject 不会改变 Current Ground Truth。

## 故障排查

### Upload GT 提示先选择 Document

先在 Ground Truth Table 中选择一份 Document，再选择 **Upload GT**。

### JSON 显示为单行或普通 Text

Upload Path 不会校验 JSON Syntax。需要 Structured Content 时，请在上传前自行校验。只有 Stored Format 包含 `json` 且解析成功时，Document Panel 才会格式化内容；否则会显示 Stored Text。

### Comparison 不可用

确认 Workflow Result 已完成，并且 Expected/Actual Content 都存在。Failed/Skipped Execution 或缺失 Ground Truth 无法生成 Content Comparison。

### Accept 和 Reject 不可用

你的 Role 需要 `ground_truth.accept_reject`。Owner、Admin 和 Editor 拥有此 Capability；Runner 和 Viewer 没有。

### Current Version 与预期不符

打开 Version History，检查 Source 和 Timestamp。每次 Manual Upload 和 Accepted Run 都会追加 Version；最新 Version 会成为 Current。

## 下一步

- [运行另一个 Database Baseline](/zh-CN/evaluation/databases)
- [调整 Workflow Execution 和 Result](/zh-CN/workflows/run-and-results)
- [查看 Workspace Role 和安全策略](/zh-CN/administration/security-and-troubleshooting)
