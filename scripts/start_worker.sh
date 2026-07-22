#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

: "${CELERY_BROKER_URL:?CELERY_BROKER_URL is required}"
: "${CELERY_RESULT_BACKEND:?CELERY_RESULT_BACKEND is required}"
export CELERY_BROKER_URL CELERY_RESULT_BACKEND

if ! python -c "from app.worker import ping_redis; raise SystemExit(0 if ping_redis() else 1)"; then
  echo "[start_worker] Redis ping failed" >&2
  exit 1
fi

LOG_LEVEL="${CELERY_WORKER_LOGLEVEL:-info}"
WORKER_CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-2}"
WORKER_POOL="${CELERY_WORKER_POOL:-prefork}"
WORKER_QUEUES="${CELERY_WORKER_QUEUES:-celery,workflow,evaluation}"
echo "[start_worker] Redis ping OK"
echo "[start_worker] Starting Celery worker with loglevel=${LOG_LEVEL}, concurrency=${WORKER_CONCURRENCY}, pool=${WORKER_POOL}, queues=${WORKER_QUEUES}"

cmd=(
  celery -A app.worker worker
  "--loglevel=${LOG_LEVEL}"
  --concurrency "${WORKER_CONCURRENCY}"
  --pool "${WORKER_POOL}"
  --queues "${WORKER_QUEUES}"
)

exec "${cmd[@]}"
