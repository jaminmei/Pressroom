#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
HEALTH_PATH="${HEALTH_PATH:-/api/health}"
TIMEOUT="${TIMEOUT:-${WAIT_TIMEOUT_SECONDS:-120}}"
INTERVAL="${INTERVAL:-5}"

if ! [[ "${TIMEOUT}" =~ ^[0-9]+$ ]] || ! [[ "${INTERVAL}" =~ ^[0-9]+$ ]]; then
  echo "[wait-for-services] TIMEOUT and INTERVAL must be integer seconds" >&2
  exit 1
fi

if [[ "${INTERVAL}" -le 0 ]]; then
  echo "[wait-for-services] INTERVAL must be > 0" >&2
  exit 1
fi

deadline=$((SECONDS + TIMEOUT))
url="${BASE_URL%/}${HEALTH_PATH}"
last_body=""

echo "[wait-for-services] Waiting for ${url} (timeout=${TIMEOUT}s interval=${INTERVAL}s)"

while (( SECONDS <= deadline )); do
  if body="$(curl -fsS "${url}" 2>/dev/null)"; then
    last_body="${body}"
    if python3 -c '
import json
import sys

data = json.loads(sys.stdin.read())
overall = data.get("overall")
if isinstance(overall, dict):
    status = overall.get("status")
else:
    status = overall
if status is None:
    status = data.get("status")
raise SystemExit(0 if status == "healthy" else 1)
' <<<"${body}"; then
      echo "[wait-for-services] Service is healthy"
      exit 0
    fi
  fi
  sleep "${INTERVAL}"
done

echo "[wait-for-services] Timed out after ${TIMEOUT}s waiting for ${url}" >&2
if [[ -n "${last_body}" ]]; then
  echo "[wait-for-services] Last response: ${last_body}" >&2
fi
exit 1
