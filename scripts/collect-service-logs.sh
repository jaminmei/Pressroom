#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-${PROFILE:-standard}}"
OUTPUT_DIR="${2:-${OUTPUT_DIR:-artifacts/${PROFILE}}}"

mkdir -p "${OUTPUT_DIR}"

echo "[collect-service-logs] profile=${PROFILE} output=${OUTPUT_DIR}"

docker compose --profile "${PROFILE}" ps -a > "${OUTPUT_DIR}/compose-ps.txt" 2>&1 || true
docker compose --profile "${PROFILE}" logs --no-color > "${OUTPUT_DIR}/compose-logs.txt" 2>&1 || true
docker compose --profile "${PROFILE}" config --services > "${OUTPUT_DIR}/compose-services.txt" 2>&1 || true

echo "[collect-service-logs] done"
