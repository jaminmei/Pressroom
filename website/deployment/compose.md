---
title: Docker Compose deployment
description: Choose the core, standard, or full profile; configure secrets; verify health; preserve data; and operate PressRoom safely.
---

# Docker Compose deployment

PressRoom is distributed as source code. Docker Compose builds project images from the checked-in Dockerfiles; the project does not publish prebuilt application images to a container registry.

## Choose a profile

| Profile | Services | Execution model | Use case |
| --- | --- | --- | --- |
| `core` | Eight built-in engine services | Engine requests only | Engine development and contract testing. |
| `standard` | Core + frontend + backend + PostgreSQL | Serial | Complete single-runtime installation and most evaluations. |
| `full` | Standard + Redis + Celery worker | Queue when enabled | Durable queued workflow and evaluation execution. |

These three application profiles build the same engine implementations. With queue mode enabled, the `full` profile changes orchestration without changing workflow definitions or engine contracts; selecting the profile alone does not switch a serial runtime to queue mode.

## Prerequisites

- Docker Engine and Docker Compose v2
- At least 16 GB RAM for `standard` or `full`
- More memory for model-heavy engines and large concurrent workloads
- Persistent disk for PostgreSQL and shared document storage
- Operator-controlled secrets and network policy

## Configure the environment

Create the runtime file:

```bash
cp .env.example .env
```

Replace every required placeholder. The critical values are:

| Variable | Purpose |
| --- | --- |
| `AUTH_SESSION_SECRET` | Signs app-local session state. Use a long random value. |
| `POSTGRES_PASSWORD` | Protects the PostgreSQL role; no insecure default exists. |
| `REDIS_PASSWORD` | Required by Compose and used by Redis in the full profile. |
| `PROVIDER_ENCRYPTION_KEY` | Stable Fernet key shared by backend and worker. |

Generate the Provider key with:

```bash
docker run --rm python:3.12-alpine python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

The stock Compose services hard-code `WORKSPACE_RBAC_ENFORCED=true` for the backend and worker; `.env` cannot disable this security invariant. Custom public deployments must enforce workspace RBAC too. Do not commit `.env`, print it in CI, or paste it into an issue.

## Deploy the standard profile

Keep serial execution enabled:

```dotenv
ORCHESTRATOR_MODE=serial
ENABLE_QUEUE_MODE=false
```

Validate, build, and start:

```bash
docker compose --profile standard config --quiet
docker compose --profile standard up -d --build
docker compose --profile standard ps
```

The backend runs database migrations before starting Uvicorn. The frontend waits for backend health; the backend waits for PostgreSQL and the required engine health checks.

Verify:

```bash
curl --fail http://localhost:8000/api/health
curl --fail http://localhost:8000/api/v1/health
```

Then open `http://localhost:5173` or the port selected by `FRONTEND_PORT`.

## Deploy the full profile

Enable queue execution in `.env`:

```dotenv
ORCHESTRATOR_MODE=queue
ENABLE_QUEUE_MODE=true
```

Validate and start:

```bash
docker compose --profile full config --quiet
docker compose --profile full up -d --build
docker compose --profile full ps
```

The full profile adds:

- Redis with authentication and append-only persistence;
- a Celery worker consuming `celery`, `workflow`, and `evaluation` queues by default;
- runtime attestation between worker and backend so workspace enforcement, database, Provider store, and encryption configuration agree.

A running worker with mismatched runtime configuration is not healthy. Keep `PROVIDER_ENCRYPTION_KEY`, Provider store path, database connection, and RBAC enforcement consistent.

## Service and port exposure

The default development mappings include:

- frontend on `FRONTEND_PORT` (default `5173`);
- backend on port `8000`;
- PostgreSQL on loopback port `5432`;
- Redis on loopback port `6379` in the full profile;
- built-in engines on loopback ports `8002`–`8009`.

For an internet deployment, place the frontend/API behind an HTTPS reverse proxy and firewall backend, database, Redis, and engine ports. Do not rely on a container port declaration as a network access policy.

The production frontend uses same-origin `/api` and `/ws` routes. Preserve WebSocket upgrade headers and session cookies in the reverse proxy.

## Production session settings

At minimum:

```dotenv
AUTH_SESSION_SECURE=true
AUTH_SESSION_SAME_SITE=lax
BACKEND_CORS_ORIGINS=https://<press-room-host>
```

Stock Compose keeps workspace RBAC enabled independently of this `.env` block. Use the exact trusted origin. If your topology requires cross-site cookies, review browser requirements and the associated CSRF risk before changing SameSite behavior.

## Persistent data

Compose declares:

- `postgres_data` for relational application data;
- `doc-conv-storage` for uploaded files, generated results, and the default SQLite Provider store;
- `redis_data` for Redis persistence in the full profile.

Back up PostgreSQL and shared storage together so database references and files remain consistent. Preserve the Provider encryption key separately in your secret-management backup. Redis is execution infrastructure, not the authoritative replacement for PostgreSQL and storage.

## Operate the deployment

Inspect state:

```bash
docker compose --profile standard ps
docker compose logs --tail=200 backend
```

For the full profile:

```bash
docker compose --profile full ps
docker compose logs --tail=200 celery-worker
```

Stop without deleting data:

```bash
docker compose --profile standard down
```

Use the matching `full` profile for a full deployment. Do not add `--volumes` unless permanent data deletion is intended and backed up.

## Upgrade from source

1. Read the release changes and dependency notices.
2. Back up PostgreSQL, shared storage, and the Provider encryption key.
3. Validate the new `.env.example` against your secret-managed configuration.
4. Run Compose configuration validation for the active profile.
5. Rebuild and start with `up -d --build`.
6. Wait for backend migration and every required health check.
7. Run a synthetic login, OCR workflow, Database evaluation, and published API smoke test.

Locally built images contain third-party base images, packages, and system components. Review `THIRD_PARTY_NOTICES.md`, lockfiles, and license metadata before redistributing images.

## Troubleshooting

### Backend exits before startup

Check required secrets, PostgreSQL reachability, migrations, and workspace readiness. The backend intentionally refuses incomplete public runtime configuration.

### Frontend remains unhealthy

Confirm backend health first. The frontend service waits for the backend and its Nginx layer proxies `/api` and `/ws` to it.

### Layout or Docling takes a long time to become healthy

These services have longer start periods and may initialize model artifacts. Confirm memory, disk, and allowed artifact access before increasing health timeouts.

### Full-profile work remains queued

Verify Redis authentication, worker health, queue names, queue-mode variables, and runtime attestation. Check that backend and worker use the same database and Provider encryption configuration.

### Data disappears after recreation

Confirm the named volumes still exist and that `down --volumes` was not used. Restore PostgreSQL and shared storage from the same backup point.

## Verify the deployment

- `docker compose ... config --quiet` passes for the selected profile.
- Required containers are healthy.
- Both health endpoints respond.
- Registration, workspace selection, and an OCR fixture work.
- A Database evaluation persists after browser reload.
- In the full profile, a queued run is consumed by the worker.
- External ports are restricted and browser access uses HTTPS in production.

## Next steps

- [Apply the security baseline](/administration/security-and-troubleshooting)
- [Run the first workflow](/getting-started/first-workflow)
- [Configure API Access](/publish/api-access)
