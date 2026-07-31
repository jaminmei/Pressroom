---
title: 安装 PressRoom
description: 使用 Docker Compose 构建并启动 PressRoom Standard Profile，然后验证 UI、API、数据库和 Engine。
---

# 安装 PressRoom

最快的完整安装方式是 Docker Compose 的 `standard` Profile。它会从源代码构建应用，并启动 Frontend、FastAPI Backend、PostgreSQL 和全部八个内置 Engine 服务，工作流使用串行执行模式。

## 前置条件

- Docker Engine
- Docker Compose v2（使用 `docker compose`，而不是旧版 `docker-compose` 命令）
- Git
- 至少 16 GB 内存
- 足够的可用磁盘，用于本地构建镜像、PostgreSQL、上传文档和 Engine 产物

克隆公开仓库并进入仓库根目录：

```bash
git clone https://github.com/jaminmei/Pressroom.git
cd Pressroom
```

## 1. 创建环境变量文件

复制公开模板：

```bash
cp .env.example .env
```

替换 **每一个** 标记为 `REQUIRED` 的值。至少应为以下变量分别选择独立值：

- `AUTH_SESSION_SECRET`
- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `PROVIDER_ENCRYPTION_KEY`

即使 Standard Profile 不启动 Redis，Redis 密码也是共享 Compose 配置的一部分。不要保留任何 `replace_with_...` 占位符。

生成一个稳定的 Provider Fernet 加密 Key：

```bash
docker run --rm python:3.12-alpine python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

把输出复制到 `PROVIDER_ENCRYPTION_KEY`。Backend 重启后必须保持该 Key 不变；使用 Full Profile 时，Worker 也必须共享相同的值。丢失该 Key 会导致已有的加密 Provider 凭据无法使用。

本地 HTTP 安装可以使用以下 Session 默认设置：

```dotenv
AUTH_SESSION_SECURE=false
AUTH_SESSION_SAME_SITE=lax
ORCHESTRATOR_MODE=serial
ENABLE_QUEUE_MODE=false
```

Stock Compose 在 Backend 和 Worker 中固定设置 `WORKSPACE_RBAC_ENFORCED=true`，不能通过 `.env` 关闭这一安全不变量。自定义公开部署也必须强制执行 Workspace RBAC。

## 2. 验证 Compose 配置

构建之前，先让 Compose 解析所选 Profile：

```bash
docker compose --profile standard config --quiet
```

如果命令报告缺少必需变量，请返回 `.env` 并替换对应占位符。

## 3. 构建并启动

```bash
docker compose --profile standard up -d --build
```

第一次构建可能需要一些时间，因为所有项目镜像都会在本地构建，部分 Engine 的依赖也比较大。

查看就绪状态，无需打印环境变量文件：

```bash
docker compose --profile standard ps
```

等待 Frontend、Backend、PostgreSQL 和 Engine 容器全部显示为 `healthy`。

## 4. 验证安装

检查无需认证的 Application Backend Liveness Endpoint：

```bash
curl --fail http://localhost:8000/api/health
```

Response 应报告 Backend Process Healthy。所需 PostgreSQL 和 Engine 检查由 Compose Container Health 覆盖，而不是这个 Liveness Response。然后检查无需认证的 Public API Namespace：

```bash
curl --fail http://localhost:8000/api/v1/health
```

预期响应：

```json
{"status":"ok"}
```

打开 [http://localhost:5173](http://localhost:5173)，创建应用本地账号，然后创建或选择一个 Workspace。登录后应能看到 Workspace Switcher。

## 5. 确认首次使用路径

1. 打开 **Template Center**。
2. 找到 **Quick Convert**，即 `PDF → OCR` 起始模板。
3. 确认选择 **Apply now** 后会打开 Workflow Editor。

此时，应用、内置 OCR Engine、Session 认证、Workspace 选择和工作流 Registry 已经可以用于引导式运行。

## 故障排查

### Compose 拒绝某个变量

重新运行 `docker compose --profile standard config --quiet`。源代码配置刻意不提供不安全的 Secret 回退值。请在 `.env` 中替换命令指出的必填值，不要修改 `docker-compose.yml` 来增加默认密码。

### 容器一直不健康

先列出容器状态：

```bash
docker compose --profile standard ps
```

然后只查看受影响的服务，例如：

```bash
docker compose logs --tail=200 backend
docker compose logs --tail=200 ocr-engine
```

日志属于运行数据。如果其中可能包含文件名、部署地址或其他敏感上下文，请勿原样发布到公开渠道。

### 端口 5173、8000 或 5432 已被占用

- 修改 `FRONTEND_PORT` 来调整浏览器 UI 端口。
- 在暴露 Backend 的 8000 端口前，停止冲突的本地服务。
- 如果本机 PostgreSQL Loopback 映射冲突，修改 `POSTGRES_PORT`。

Engine 的 Host 端口同样绑定到 Loopback，也可能与已有本地服务冲突。

### 构建时内存不足

增加 Docker 的内存配额。Standard Profile 至少需要 16 GB；Docling 或 Layout 模型初始化可能还需要额外空间。

### 注册成功，但产品资源显示无权限

确认 Workspace Switcher 中已经选中一个 Workspace。访问权限根据活动 Workspace 及成员在其中的 Role 进行判断。

## 停止或移除安装

停止容器但保留持久数据：

```bash
docker compose --profile standard down
```

除非明确要删除 PostgreSQL 和共享存储数据，否则不要添加 `--volumes`。

## 下一步

- [运行第一个 OCR 工作流](/zh-CN/getting-started/first-workflow)
- [了解 Compose Profile](/zh-CN/deployment/compose)
- [查看生产安全基线](/zh-CN/administration/security-and-troubleshooting)
