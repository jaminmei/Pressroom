---
title: Install PressRoom
description: Build and start the standard PressRoom profile with Docker Compose, then verify the UI, API, database, and engines.
---

# Install PressRoom

The fastest complete installation is the `standard` Docker Compose profile. It builds the application from source and starts the frontend, FastAPI backend, PostgreSQL, and all eight built-in engine services with serial workflow execution.

## Prerequisites

- Docker Engine
- Docker Compose v2 (`docker compose`, not the legacy `docker-compose` command)
- Git
- At least 16 GB RAM
- Free disk space for locally built images, PostgreSQL, uploaded documents, and engine artifacts

Clone the public repository and enter its root directory:

```bash
git clone https://github.com/jaminmei/Pressroom.git
cd Pressroom
```

## 1. Create the environment file

Copy the public template:

```bash
cp .env.example .env
```

Replace **every** value marked `REQUIRED`. At minimum, choose independent values for:

- `AUTH_SESSION_SECRET`
- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `PROVIDER_ENCRYPTION_KEY`

The Redis password is part of the shared Compose configuration even when the standard profile does not start Redis. Do not keep any `replace_with_...` placeholder.

Generate a stable Fernet key for Provider encryption:

```bash
docker run --rm python:3.12-alpine python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Copy the output into `PROVIDER_ENCRYPTION_KEY`. Keep this key stable across backend restarts and, in the full profile, share the same value with the worker. Losing it makes existing encrypted Provider credentials unusable.

For a local HTTP installation, the session defaults are appropriate:

```dotenv
AUTH_SESSION_SECURE=false
AUTH_SESSION_SAME_SITE=lax
ORCHESTRATOR_MODE=serial
ENABLE_QUEUE_MODE=false
```

The stock Compose services hard-code `WORKSPACE_RBAC_ENFORCED=true` for the backend and worker; `.env` cannot disable this invariant. Custom public deployments must enforce workspace RBAC too.

## 2. Validate the Compose configuration

Ask Compose to resolve the selected profile before building it:

```bash
docker compose --profile standard config --quiet
```

If this reports a required variable, return to `.env` and replace the missing placeholder.

## 3. Build and start

```bash
docker compose --profile standard up -d --build
```

The first build can take time because every project image is built locally and some engine dependencies are large.

Follow readiness without printing your environment file:

```bash
docker compose --profile standard ps
```

Wait until the frontend, backend, PostgreSQL, and engine containers report `healthy`.

## 4. Verify the installation

Check the application's unauthenticated backend liveness endpoint:

```bash
curl --fail http://localhost:8000/api/health
```

The response should report a healthy backend process. Compose container health, rather than this liveness response, covers the required PostgreSQL and engine checks. Then check the unauthenticated public namespace:

```bash
curl --fail http://localhost:8000/api/v1/health
```

Expected response:

```json
{"status":"ok"}
```

Open [http://localhost:5173](http://localhost:5173), create an app-local account, and create or select a workspace. The workspace switcher should be visible after sign-in.

## 5. Confirm the first-run path

1. Open **Template Center**.
2. Locate **Quick Convert**, the `PDF → OCR` starter.
3. Confirm that **Apply now** opens the Workflow Editor.

At this point the application, built-in OCR engine, session authentication, workspace selection, and workflow registry are ready for the guided run.

## Troubleshooting

### Compose rejects a variable

Run `docker compose --profile standard config --quiet` again. The source configuration intentionally has no insecure secret fallback. Replace the named required value in `.env`; do not edit `docker-compose.yml` to introduce a default password.

### A container remains unhealthy

List container state first:

```bash
docker compose --profile standard ps
```

Then inspect only the affected service, for example:

```bash
docker compose logs --tail=200 backend
docker compose logs --tail=200 ocr-engine
```

Treat logs as operational data. Do not post raw logs publicly if they might include filenames, deployment addresses, or other sensitive context.

### Port 5173, 8000, or 5432 is already in use

- Change `FRONTEND_PORT` for the browser UI.
- Stop the conflicting local service before exposing the backend on port 8000.
- Change `POSTGRES_PORT` if the loopback PostgreSQL mapping conflicts.

The engine host ports are also bound to loopback and may conflict with existing local services.

### The build runs out of memory

Increase Docker's memory allocation. The standard profile is designed for at least 16 GB, and Docling or layout-model initialization may need additional headroom.

### Registration works but product resources are forbidden

Confirm that a workspace is selected in the workspace switcher. Access is evaluated against the active workspace and its role capabilities.

## Stop or remove the installation

Stop containers while keeping persistent data:

```bash
docker compose --profile standard down
```

Do not add `--volumes` unless you intend to delete PostgreSQL and shared storage data.

## Next steps

- [Run your first OCR workflow](/getting-started/first-workflow)
- [Understand the Compose profiles](/deployment/compose)
- [Review the production security baseline](/administration/security-and-troubleshooting)
