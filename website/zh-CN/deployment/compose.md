---
title: Docker Compose 部署
description: 选择 Core、Standard 或 Full Profile，配置 Secret、验证健康状态、保留数据并安全运行 PressRoom。
---

# Docker Compose 部署

PressRoom 以源代码形式分发。Docker Compose 使用仓库中的 Dockerfile 构建项目镜像；项目不会把预构建应用镜像发布到 Container Registry。

## 选择 Profile

| Profile | Service | Execution Model | 使用场景 |
| --- | --- | --- | --- |
| `core` | 八个内置 Engine Service | 仅 Engine Request | Engine 开发和 Contract Test。 |
| `standard` | Core + Frontend + Backend + PostgreSQL | Serial | 完整单 Runtime 安装和大多数评测。 |
| `full` | Standard + Redis + Celery Worker | 启用后的 Queue | 持久化队列 Workflow 和 Evaluation Execution。 |

这三个 Application Profile 构建相同的 Engine Implementation。启用 Queue Mode 后，`full` Profile 会改变 Orchestration，但不改变 Workflow Definition 或 Engine Contract；仅选择该 Profile 不会把 Serial Runtime 自动切换为 Queue Mode。

## 前置条件

- Docker Engine 和 Docker Compose v2
- `standard` 或 `full` 至少需要 16 GB 内存
- Model-heavy Engine 和大型并发工作负载需要更多内存
- PostgreSQL 和共享文档存储所需的持久磁盘
- Operator 管理的 Secret 和 Network Policy

## 配置 Environment

创建 Runtime File：

```bash
cp .env.example .env
```

替换每个 Required Placeholder。关键变量包括：

| Variable | 用途 |
| --- | --- |
| `AUTH_SESSION_SECRET` | 签署应用本地 Session State。使用足够长的随机值。 |
| `POSTGRES_PASSWORD` | 保护 PostgreSQL Role；不存在不安全默认值。 |
| `REDIS_PASSWORD` | Compose 必填，并由 Full Profile 中的 Redis 使用。 |
| `PROVIDER_ENCRYPTION_KEY` | Backend 和 Worker 共享的稳定 Fernet Key。 |

使用以下命令生成 Provider Key：

```bash
docker run --rm python:3.12-alpine python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Stock Compose 在 Backend 和 Worker 中固定设置 `WORKSPACE_RBAC_ENFORCED=true`，不能通过 `.env` 关闭这一安全不变量。自定义公开部署也必须强制执行 Workspace RBAC。不要提交 `.env`、在 CI 中打印它，或把它粘贴到 Issue。

## 部署 Standard Profile

保持 Serial Execution：

```dotenv
ORCHESTRATOR_MODE=serial
ENABLE_QUEUE_MODE=false
```

验证、构建并启动：

```bash
docker compose --profile standard config --quiet
docker compose --profile standard up -d --build
docker compose --profile standard ps
```

Backend 会在启动 Uvicorn 前运行 Database Migration。Frontend 等待 Backend 健康；Backend 则等待 PostgreSQL 和必要 Engine Health Check。

验证：

```bash
curl --fail http://localhost:8000/api/health
curl --fail http://localhost:8000/api/v1/health
```

然后打开 `http://localhost:5173`，或 `FRONTEND_PORT` 所选端口。

## 部署 Full Profile

在 `.env` 中启用 Queue Execution：

```dotenv
ORCHESTRATOR_MODE=queue
ENABLE_QUEUE_MODE=true
```

验证并启动：

```bash
docker compose --profile full config --quiet
docker compose --profile full up -d --build
docker compose --profile full ps
```

Full Profile 会增加：

- 带 Authentication 和 Append-only Persistence 的 Redis；
- 默认消费 `celery`、`workflow` 和 `evaluation` Queue 的 Celery Worker；
- Worker 与 Backend 之间的 Runtime Attestation，用于确认 Workspace Enforcement、Database、Provider Store 和 Encryption Configuration 一致。

Runtime Configuration 不匹配的 Worker 即使运行也不健康。保持 `PROVIDER_ENCRYPTION_KEY`、Provider Store Path、Database Connection 和 RBAC Enforcement 一致。

## Service 和 Port Exposure

默认 Development Mapping 包括：

- Frontend 使用 `FRONTEND_PORT`（默认 `5173`）；
- Backend 使用端口 `8000`；
- PostgreSQL 使用 Loopback 端口 `5432`；
- Full Profile 中 Redis 使用 Loopback 端口 `6379`；
- 内置 Engine 使用 Loopback 端口 `8002`–`8009`。

互联网部署应把 Frontend/API 放在 HTTPS Reverse Proxy 后，并通过 Host 和 Network Control 限制 Backend、Database、Redis 和 Engine Port。不要把 Container Port Declaration 当作 Network Access Policy。

Production Frontend 使用同源 `/api` 和 `/ws` Route。Reverse Proxy 必须保留 WebSocket Upgrade Header 和 Session Cookie。

## Production Session 设置

最低配置：

```dotenv
AUTH_SESSION_SECURE=true
AUTH_SESSION_SAME_SITE=lax
BACKEND_CORS_ORIGINS=https://<press-room-host>
```

Stock Compose 会独立于这段 `.env` 配置保持 Workspace RBAC 启用。只使用准确的 Trusted Origin。如果 Topology 需要 Cross-site Cookie，请在修改 SameSite 行为前审查浏览器要求和相关 CSRF 风险。

## Persistent Data

Compose 声明：

- `postgres_data`：Relational Application Data；
- `doc-conv-storage`：上传文件、生成结果和默认 SQLite Provider Store；
- `redis_data`：Full Profile 中的 Redis Persistence。

PostgreSQL 和 Shared Storage 应一起备份，确保 Database Reference 与 File 一致。另行在 Secret-management Backup 中保存 Provider Encryption Key。Redis 属于 Execution Infrastructure，不能替代作为事实来源的 PostgreSQL 和 Storage。

## 运行 Deployment

检查 State：

```bash
docker compose --profile standard ps
docker compose logs --tail=200 backend
```

Full Profile：

```bash
docker compose --profile full ps
docker compose logs --tail=200 celery-worker
```

停止但不删除数据：

```bash
docker compose --profile standard down
```

Full Deployment 使用匹配的 `full` Profile。除非明确要永久删除数据且已经备份，否则不要添加 `--volumes`。

## 从源代码升级

1. 阅读 Release Change 和 Dependency Notice。
2. 备份 PostgreSQL、Shared Storage 和 Provider Encryption Key。
3. 对照新的 `.env.example` 检查 Secret-managed Configuration。
4. 对活动 Profile 运行 Compose Configuration Validation。
5. 使用 `up -d --build` 重新构建并启动。
6. 等待 Backend Migration 和全部必要 Health Check。
7. 使用合成数据执行 Login、OCR Workflow、Database Evaluation 和 Published API Smoke Test。

本地构建镜像包含第三方 Base Image、Package 和 System Component。重新分发镜像前，请查看 `THIRD_PARTY_NOTICES.md`、Lockfile 和 License Metadata。

## 故障排查

### Backend 在启动前退出

检查 Required Secret、PostgreSQL Reachability、Migration 和 Workspace Readiness。Backend 会刻意拒绝不完整的 Public Runtime Configuration。

### Frontend 一直不健康

先确认 Backend Health。Frontend Service 会等待 Backend，其 Nginx Layer 把 `/api` 和 `/ws` 代理到 Backend。

### Layout 或 Docling 很久才能健康

这些 Service 的 Start Period 更长，也可能需要初始化 Model Artifact。增加 Health Timeout 前，先确认 Memory、Disk 和允许的 Artifact Access。

### Full Profile 中任务一直处于 Queued

验证 Redis Authentication、Worker Health、Queue Name、Queue-mode Variable 和 Runtime Attestation。检查 Backend 和 Worker 是否使用相同 Database 与 Provider Encryption Configuration。

### 重建后 Data 消失

确认 Named Volume 仍然存在，并且没有使用 `down --volumes`。从同一个 Backup Point 恢复 PostgreSQL 和 Shared Storage。

## 验证部署

- 所选 Profile 的 `docker compose ... config --quiet` 通过。
- 必要 Container 全部健康。
- 两个 Health Endpoint 都能响应。
- Registration、Workspace Selection 和 OCR Fixture 可以运行。
- Browser Reload 后 Database Evaluation 仍然存在。
- Full Profile 中的 Queued Run 会被 Worker 消费。
- Production 中 External Port 受到限制，并通过 HTTPS 访问 Browser UI。

## 下一步

- [应用安全基线](/zh-CN/administration/security-and-troubleshooting)
- [运行第一个 Workflow](/zh-CN/getting-started/first-workflow)
- [配置 API Access](/zh-CN/publish/api-access)
