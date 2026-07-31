---
title: PressRoom 概览
description: 了解 PressRoom 的用途、主要产品区域如何协作，以及应该选择哪一种部署 Profile。
---

# PressRoom 概览

PressRoom 是一个自托管工作空间，用于设计、运行、评测和发布文档处理工作流。它把可视化、带类型约束的 DAG 编辑器，与内置转换 Engine、工作空间级 Model Provider、可复用评测数据和工作流级公开 API 组合在一起。

## 可以用它做什么

### 构建文档工作流

**Workflow Editor（工作流编辑器）** 连接四类构建单元：

1. **Input（输入）** 用于暂存 PDF、图片或其他受支持文件。
2. **Processor（处理器）** 在推理前转换输入，例如把文档转换为逐页图片、增强图片或纠正旋转方向。
3. **Engine（引擎）** 执行 OCR、版面检测、Text 或 HTML 处理、MarkItDown 转换、Docling 转换或模型推理。
4. **End（终点）** 是唯一终止节点，对外提供工作流最终结果。

连接会根据节点和端口类型进行校验。循环、孤立节点、不兼容的数据类型和多个终止节点都会在执行前报告。

### 进行可复现评测

**Database** 是可复用的文档集合，并不是 PostgreSQL 服务本身。在一个 Database 中，你可以：

- 上传文档；
- 选择已保存的工作流和部分文档；
- 监控批次进度和逐文档状态；
- 将输出与当前 Ground Truth 对比；
- 把审核后的输出接受为新的 Ground Truth 版本。

![使用版本化 Ground Truth 对比合成发票的评测运行](/images/product/evaluation-compare.webp)

### 发布集成接口

保存和发布是两个独立动作。已保存的工作流可以继续编辑，也可以用于评测；Publish 会记录 Publication State 并解锁公开 API 访问。在当前版本中，新的公开 Run 执行 Workflow 的 Current Saved Definition。

在工作流的 **API Access** 页面中，Owner 或 Admin 可以创建和撤销工作流级 Key、复制 URL 与上传请求示例，并查看公开调用使用情况。一个工作流的 Key 不能调用另一个工作流。

## 系统如何协作

```text
Browser
  └─ React application
       └─ FastAPI backend
            ├─ PostgreSQL: workspaces, workflows, runs, evaluation data
            ├─ SQLite Provider store: encrypted workspace Provider records
            ├─ Shared storage: uploaded documents and generated results
            └─ Engine services: OCR, VLM adapter, Text, MarkItDown, Docling,
                                layout detection, enhancement, and rotation
```

Standard Profile 在应用运行时中串行执行工作流。Full Profile 增加 Redis 和 Celery Worker 来进行队列执行。两个 Profile 使用相同的工作流和 Engine 契约。

## 开始之前

你需要：

- Docker Engine 与 Docker Compose v2；
- 为 `standard` 或 `full` Profile 准备至少 16 GB 内存；
- 为模型较重的 Engine 和保留文件准备额外内存与磁盘；
- 具备本地构建镜像的权限，因为项目不发布预构建应用镜像。

运行第一个 OCR 工作流 **不需要** 外部 Model Provider。

## 产品导航

| 区域 | 用途 |
| --- | --- |
| **Workflow Editor** | 创建或修改当前工作流并查看执行状态。 |
| **Workflow Studio** | 搜索、打开、重命名、进入 API Access 和删除已保存工作流。Publish 在 Editor 中执行。 |
| **Template Center** | 应用内置起始模板或导入工作流 JSON。 |
| **Database** | 管理文档集、批次运行、对比和 Ground Truth。 |
| **Settings** | 查看内置 Engine 服务及其健康状态。 |
| **Workspace Settings → Providers** | 管理工作空间级 Model Provider 和模型。 |
| **API Access** | 为已解锁 Publication State 的 Workflow 配置外部调用。 |

产品 UI 支持英文和繁体中文。本套文档提供英文和简体中文版本；需要精确对应界面时，中文文档会保留英文 UI 名称。

## 验证你的理解

理解以下区别后，就可以开始安装：

- **workflow draft（工作流草稿）** 可以编辑，Publication State 则作为外部 API 访问 Current Saved Definition 的门禁；
- **Database** 拥有评测文档和 Ground Truth，而 **workspace（工作空间）** 控制对所有产品资源的访问；
- 内置 **engine service** 实现 `/process`、`/health` 和 `/config` 契约，而 `openai_compatible` **Provider** 通过本地 VLM Adapter 提供调用时模型访问。

## 排障入口

| 现象 | 从这里开始 |
| --- | --- |
| 应用无法启动 | [安装故障排查](/zh-CN/getting-started/installation#故障排查) |
| 节点不可用或不健康 | [Model Providers](/zh-CN/workflows/providers) 和 [运行与结果](/zh-CN/workflows/run-and-results) |
| 批次没有可对比结果 | [Ground Truth](/zh-CN/evaluation/ground-truth) |
| API Access 处于锁定状态 | [发布并配置 API Access](/zh-CN/publish/api-access) |
| 部署需要加固 | [安全与故障排查](/zh-CN/administration/security-and-troubleshooting) |

## 下一步

- [安装 Standard Profile](/zh-CN/getting-started/installation)
- [运行第一个 PDF → OCR 工作流](/zh-CN/getting-started/first-workflow)
- [了解核心概念](/zh-CN/concepts/core-concepts)
