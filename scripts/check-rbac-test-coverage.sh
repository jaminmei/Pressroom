#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_DIR="${ROOT_DIR}/tests"

fail() {
  printf '[FAIL] %s\n' "$1" >&2
  exit 1
}

check_group() {
  local group="$1"
  local on_regex="$2"
  shift 2

  shopt -s nullglob
  local files=()
  local pattern
  for pattern in "$@"; do
    files+=("${pattern}")
  done

  if [[ "${#files[@]}" -eq 0 ]]; then
    fail "${group}: no matching test files found"
  fi

  local file
  for file in "${files[@]}"; do
    if grep -Eq "${on_regex}" "${file}"; then
      printf '[PASS] %s: %s\n' "${group}" "${file#${ROOT_DIR}/}"
      return 0
    fi
  done

  fail "${group}: no ON-mode assertion found"
}

main() {
  local rbac_hits
  rbac_hits="$(grep -R -n --include='*.py' -E 'WORKSPACE_RBAC_ENFORCED' "${TEST_DIR}" || true)"
  if [[ -z "${rbac_hits}" ]]; then
    fail "tests/: no WORKSPACE_RBAC_ENFORCED coverage found"
  fi

  check_group 'workflows' 'enable_rbac\(monkeypatch\)' "${TEST_DIR}/integration/test_workflow_rbac.py"
  check_group 'test_sets' 'WORKSPACE_RBAC_ENFORCED", "true"|enable_rbac\(monkeypatch\)' "${TEST_DIR}/integration/test_test_set_workspace_rbac.py"
  check_group 'evaluation_runs' 'WORKSPACE_RBAC_ENFORCED", "true"|enable_rbac\(monkeypatch\)' "${TEST_DIR}/integration/test_evaluation_runs_workspace_rbac.py"
  check_group 'tasks' 'enable_rbac\(monkeypatch\)' "${TEST_DIR}/integration/test_tasks_workspace_rbac.py"
  check_group 'providers' 'enable_rbac\(monkeypatch\)' "${TEST_DIR}/integration/test_providers_workspace_rbac.py"
  check_group 'admin' 'enable_rbac\(monkeypatch\)' "${TEST_DIR}/integration/test_admin_api_keys_rbac.py" "${TEST_DIR}/integration/test_admin_api_usage_rbac.py"
  check_group 'workspaces' 'WORKSPACE_RBAC_ENFORCED", "true"|enable_rbac\(monkeypatch\)' "${TEST_DIR}/integration/workspace_api_support.py" "${TEST_DIR}/integration/test_workspace_api.py"
}

main "$@"
