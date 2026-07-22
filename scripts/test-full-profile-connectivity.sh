#!/usr/bin/env bash
set -Eeuo pipefail

PROFILE="${PROFILE:-full}"
CONNECTIVITY_TIMEOUT="${CONNECTIVITY_TIMEOUT:-5}"
ENGINE_INTERNAL_PORT="${ENGINE_INTERNAL_PORT:-8080}"
ENGINE_PATH="${ENGINE_PATH:-/health}"

REQUIRED_SERVICES=(
  backend
  celery-worker
  redis
  postgres
  ocr-engine
  vlm-engine
  text-engine
  markitdown-engine
  docling-engine
  layout-detection-engine
  image-enhancement-engine
  image-rotation-engine
  frontend
)

compose_cmd=(docker compose --profile "${PROFILE}")

log() {
  printf '[INFO] %s\n' "$*"
}

pass() {
  printf '[PASS] %s\n' "$*"
}

fail() {
  printf '[FAIL] %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  scripts/test-full-profile-connectivity.sh

Environment variables:
  PROFILE               Compose profile (default: full)
  CONNECTIVITY_TIMEOUT  Probe timeout in seconds (default: 5)
  ENGINE_INTERNAL_PORT  Engine container port (default: 8080)
  ENGINE_PATH           Engine health path (default: /health)

Expected precondition:
  IS_SANDBOX=1 docker compose --profile full up -d

Behavior:
  - Verifies required services exist in compose profile.
  - Verifies required services are currently running.
  - Verifies all required services are on doc-conv-network.
  - From backend and celery-worker containers, probes Redis/Postgres/4 engines.
  - Any failure returns non-zero exit code.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  fail "docker command not found."
fi

log "Checking compose services for profile '${PROFILE}'."
compose_services="$("${compose_cmd[@]}" config --services 2>/dev/null)" || {
  fail "Unable to load compose services for profile '${PROFILE}'."
}

for service in "${REQUIRED_SERVICES[@]}"; do
  if ! grep -qx "${service}" <<<"${compose_services}"; then
    fail "Required service '${service}' is missing from profile '${PROFILE}'."
  fi
done
pass "All required services are defined in profile '${PROFILE}'."

running_services="$("${compose_cmd[@]}" ps --services --status running 2>/dev/null)" || {
  fail "Unable to list running services. Start full profile before running this script."
}

for service in "${REQUIRED_SERVICES[@]}"; do
  if ! grep -qx "${service}" <<<"${running_services}"; then
    fail "Service '${service}' is not running. Run: IS_SANDBOX=1 docker compose --profile ${PROFILE} up -d"
  fi
done
pass "All required services are running."

for service in "${REQUIRED_SERVICES[@]}"; do
  container_id="$("${compose_cmd[@]}" ps -q "${service}")"
  [[ -n "${container_id}" ]] || fail "Cannot resolve container id for service '${service}'."
  networks="$(docker inspect --format '{{range $k, $_ := .NetworkSettings.Networks}}{{printf "%s\n" $k}}{{end}}' "${container_id}")"
  if ! grep -q 'doc-conv-network' <<<"${networks}"; then
    fail "Service '${service}' is not attached to a doc-conv-network compose network."
  fi
done
pass "Network attachment check passed for required services."

run_probe_from() {
  local source_service="$1"

  log "Running connectivity probes from '${source_service}'."
  "${compose_cmd[@]}" exec -T "${source_service}" env \
    CONNECTIVITY_TIMEOUT="${CONNECTIVITY_TIMEOUT}" \
    ENGINE_INTERNAL_PORT="${ENGINE_INTERNAL_PORT}" \
    ENGINE_PATH="${ENGINE_PATH}" \
    python - <<'PY'
import os
import socket
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

timeout = float(os.environ.get("CONNECTIVITY_TIMEOUT", "5"))
engine_port = int(os.environ.get("ENGINE_INTERNAL_PORT", "8080"))
engine_path = os.environ.get("ENGINE_PATH", "/health")

tcp_targets = [
    ("redis", "redis", 6379),
    ("postgres", "postgres", 5432),
    ("ocr-engine", "ocr-engine", engine_port),
    ("vlm-engine", "vlm-engine", engine_port),
    ("text-engine", "text-engine", engine_port),
    ("markitdown-engine", "markitdown-engine", engine_port),
    ("docling-engine", "docling-engine", engine_port),
    ("layout-detection-engine", "layout-detection-engine", engine_port),
    ("image-enhancement-engine", "image-enhancement-engine", engine_port),
    ("image-rotation-engine", "image-rotation-engine", engine_port),
]

http_targets = [
    ("ocr-engine", f"http://ocr-engine:{engine_port}{engine_path}"),
    ("vlm-engine", f"http://vlm-engine:{engine_port}{engine_path}"),
    ("text-engine", f"http://text-engine:{engine_port}{engine_path}"),
    ("markitdown-engine", f"http://markitdown-engine:{engine_port}{engine_path}"),
    ("docling-engine", f"http://docling-engine:{engine_port}{engine_path}"),
    ("layout-detection-engine", f"http://layout-detection-engine:{engine_port}{engine_path}"),
    ("image-enhancement-engine", f"http://image-enhancement-engine:{engine_port}{engine_path}"),
    ("image-rotation-engine", f"http://image-rotation-engine:{engine_port}{engine_path}"),
]

all_ok = True

def ok(message: str) -> None:
    print(f"[PASS] {message}")

def bad(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)

def normalize_database_url(raw: str) -> str:
    # SQLAlchemy style URLs may use driver hints (e.g. postgresql+psycopg://).
    if raw.startswith("postgresql+"):
        return "postgresql://" + raw.split("://", 1)[1]
    if raw.startswith("postgres://"):
        return "postgresql://" + raw[len("postgres://") :]
    return raw

for target, host, port in tcp_targets:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            ok(f"TCP connect to {target} ({host}:{port})")
    except OSError as exc:
        bad(f"TCP connect to {target} ({host}:{port}) failed: {exc}")
        all_ok = False

for target, url in http_targets:
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.getcode() or 0)
        if status == 200:
            ok(f"HTTP health check for {target} ({url})")
        else:
            bad(f"HTTP health check for {target} returned status {status}: {url}")
            all_ok = False
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        bad(f"HTTP health check for {target} failed: {url} ({exc})")
        all_ok = False

redis_url = (
    os.environ.get("REDIS_URL")
    or os.environ.get("CELERY_BROKER_URL")
    or "redis://redis:6379/0"
)
try:
    import redis

    redis_client = redis.Redis.from_url(
        redis_url,
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
    )
    if redis_client.ping():
        ok("Redis PING via redis-py")
    else:
        bad("Redis PING returned false-like response")
        all_ok = False
except Exception as exc:
    bad(f"Redis application-level probe failed: {type(exc).__name__}")
    all_ok = False

database_url = normalize_database_url(os.environ.get("DATABASE_URL", "").strip())
if not database_url:
    bad("DATABASE_URL is missing; cannot run PostgreSQL query probe")
    all_ok = False
else:
    parsed = urlparse(database_url)
    db_target = f"{parsed.hostname or 'postgres'}:{parsed.port or 5432}/{(parsed.path or '/').lstrip('/') or 'postgres'}"
    try:
        import psycopg

        with psycopg.connect(
            database_url,
            connect_timeout=max(int(timeout), 1),
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                row = cur.fetchone()
        if row and row[0] == 1:
            ok(f"PostgreSQL SELECT 1 via psycopg ({db_target})")
        else:
            bad(f"PostgreSQL SELECT 1 returned unexpected payload ({db_target}): {row!r}")
            all_ok = False
    except Exception as exc:
        bad(f"PostgreSQL query probe failed ({db_target}): {exc}")
        all_ok = False

sys.exit(0 if all_ok else 1)
PY
}

if ! run_probe_from backend; then
  fail "Connectivity probe failed from backend."
fi
pass "Backend connectivity checks passed."

if ! run_probe_from celery-worker; then
  fail "Connectivity probe failed from celery-worker."
fi
pass "Celery worker connectivity checks passed."

pass "Full profile connectivity checks completed successfully."
