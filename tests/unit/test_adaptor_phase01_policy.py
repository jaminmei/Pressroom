from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.services.workspace_permissions import CAPABILITIES, WorkspaceRole

REPO_ROOT = Path(__file__).resolve().parents[2]
WIKI_ROOT = REPO_ROOT / "wiki"
MIGRATION_ROOT = WIKI_ROOT / "migrations" / "adaptor-iteration-public-migration"
PHASE01 = MIGRATION_ROOT / "phases" / "phase01-scope-and-security.md"
PHASE09 = MIGRATION_ROOT / "phases" / "phase09-workbench.md"
README = MIGRATION_ROOT / "README.md"
SCOPE = MIGRATION_ROOT / "scope-and-inventory.md"
SANDBOX = MIGRATION_ROOT / "sandbox-security-plan.md"
RELEASE = MIGRATION_ROOT / "release-boundary.md"
VERIFY = MIGRATION_ROOT / "verification-plan.md"
MIGRATIONS_INDEX = WIKI_ROOT / "migrations" / "_index.md"
WIKI_INDEX = WIKI_ROOT / "index.md"
COMPOSE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
MAIN = REPO_ROOT / "app" / "main.py"
WORKER = REPO_ROOT / "app" / "worker.py"
ATTESTATION_API = REPO_ROOT / "app" / "api" / "runtime_attestation.py"

_RELATIVE_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]*)?\)")


@dataclass(frozen=True)
class MarkdownAudit:
    files: tuple[Path, ...]
    inline_relative_markdown_links: tuple[tuple[Path, str], ...]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _migration_markdown_scope() -> tuple[Path, ...]:
    return tuple(sorted(set(MIGRATION_ROOT.rglob("*.md")).union({MIGRATIONS_INDEX, WIKI_INDEX})))


def _phase01_canonical_markdown_scope() -> tuple[Path, ...]:
    return (
        README,
        SCOPE,
        SANDBOX,
        RELEASE,
        VERIFY,
        PHASE01,
        MIGRATIONS_INDEX,
        WIKI_INDEX,
    )


def _audit_markdown(files: tuple[Path, ...]) -> MarkdownAudit:
    inline_relative_markdown_links: list[tuple[Path, str]] = []
    for path in files:
        for raw_target in _RELATIVE_MARKDOWN_LINK.findall(_text(path)):
            target = raw_target.strip()
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if not target.endswith((".md", ".mdx")):
                continue
            resolved = (path.parent / target).resolve()
            assert resolved.exists(), f"Broken markdown link in {path}: {target}"
            inline_relative_markdown_links.append((path, target))
    return MarkdownAudit(
        files=files,
        inline_relative_markdown_links=tuple(inline_relative_markdown_links),
    )


def _decision_lines(path: Path) -> set[str]:
    decisions: set[str] = set()
    for line in _text(path).splitlines():
        if line.startswith("Decision:"):
            decisions.add(line.removeprefix("Decision:").strip())
    return decisions


def _normalized_text(path: Path) -> str:
    return " ".join(_text(path).split())


def test_phase01_package_status_and_checklist_are_consistent() -> None:
    readme = _text(README)
    phase = _text(PHASE01)

    assert (
        "Status: Complete. Phases 01-11 are implemented, including Phase 09 Workbench on"
        " codex/adaptor-iteration-qa-recovery; Phase 11 docs, release boundary, and"
        " verification evidence are complete." in readme
    )
    assert "Phases 10-11 remain pending" not in readme
    assert "Status: Complete" in phase
    assert "- [x] Phase 01, scope and security" in readme
    assert "- [x] Phase 02, node contracts" in readme
    assert "- [x] Phase 07, persistence compatibility" in readme
    assert "- [x] Phase 08, frontend" in readme
    assert "- [x] Phase 09, Workbench" in readme
    assert "- [x] Phase 11, docs and release" in readme
    assert "The migration is documentation only at this stage." in readme
    assert "Phase 09 was initially deferred, then implemented on" in readme
    assert "Phase 10 stays unblocked." in readme


def test_phase01_locks_provenance_boundary_and_never_migrate_scope() -> None:
    phase = _text(PHASE01)
    readme = _text(README)
    scope = _text(SCOPE)
    normalized_phase = _normalized_text(PHASE01)

    for text in (phase, readme, scope):
        assert "provenance only" in text
        assert "behavioral reference" in text
        assert "target architecture" in text and "authoritative" in text

    assert "Status: Complete" in phase
    assert (
        "source sandbox Compose wiring must not be copied into the target before Phase 04"
        in normalized_phase
    )
    assert (
        "The source absolute path from the provenance repo is informational only"
        in normalized_phase
    )

    never_migrate_terms = {
        "private runtime data",
        "credentials",
        "private endpoints",
        "model weights",
        "unapproved binaries",
        "internal MCP",
        "source raw wiki/openspec/memory",
        "source local `.opencode`/`.claude` config",
    }
    for term in never_migrate_terms:
        assert term in phase


def test_phase01_locks_compose_profiles_workbench_scope_and_sandbox_deferral() -> None:
    phase = _text(PHASE01)
    readme = _text(README)
    compose = _text(COMPOSE)
    decisions = _decision_lines(PHASE01)
    normalized_phase = _normalized_text(PHASE01)

    assert "profiles:" in compose
    for profile in ("core", "standard", "full"):
        assert f"- {profile}" in compose

    assert "no new Compose profile is added in Phase 01" in phase
    assert any("sandbox is intentionally not wired" in decision for decision in decisions)
    assert "Standard profile remains the serial execution target" in normalized_phase
    assert "Full profile remains the queue execution target" in normalized_phase
    assert "core has no product runtime guarantee" in normalized_phase
    assert "serial sandbox coverage is required for standard" in phase
    assert "queue parity for full" in phase
    assert "Phase 09 Workbench" in readme
    assert "Phase 09 was initially deferred, then implemented on" in readme


def test_phase01_locks_workspace_capability_mapping_to_current_target_roles() -> None:
    phase = _text(PHASE01)

    expected_matrix = {
        WorkspaceRole.OWNER: {
            "workflow.view",
            "workflow.edit_draft",
            "workflow.publish",
            "workflow.run",
        },
        WorkspaceRole.ADMIN: {
            "workflow.view",
            "workflow.edit_draft",
            "workflow.publish",
            "workflow.run",
        },
        WorkspaceRole.EDITOR: {
            "workflow.view",
            "workflow.edit_draft",
            "workflow.run",
        },
        WorkspaceRole.RUNNER: {"workflow.view", "workflow.run"},
        WorkspaceRole.VIEWER: {"workflow.view"},
    }

    for role, capabilities in expected_matrix.items():
        workflow_capabilities = {
            capability for capability in CAPABILITIES[role] if capability.startswith("workflow.")
        }
        assert workflow_capabilities == capabilities

    for capability in (
        "workflow.view",
        "workflow.edit_draft",
        "workflow.publish",
        "workflow.run",
    ):
        assert capability in phase
    assert "workspace RBAC authority is the existing target capability map" in phase


def test_phase01_locks_attestation_and_sandbox_policy_against_current_target_surfaces() -> None:
    env_example = _text(ENV_EXAMPLE)
    main = _text(MAIN)
    worker = _text(WORKER)
    attestation_api = _text(ATTESTATION_API)

    assert "WORKSPACE_RBAC_ENFORCED=true" in env_example
    assert (
        "RUNTIME_ATTESTATION_URL=http://backend:8000/api/internal/runtime-attestation"
        in env_example
    )
    assert "RUNTIME_ATTESTATION_TIMEOUT_SECONDS=5" in env_example

    assert 'require_workspace_runtime_env("backend")' in main
    assert 'require_workspace_runtime_env("worker")' in worker
    assert "attest_backend_runtime()" in worker
    assert '"/internal/runtime-attestation"' in attestation_api

    normalized_phase = _normalized_text(PHASE01).lower()
    normalized_sandbox = _normalized_text(SANDBOX).lower()

    for term in (
        "out-of-process",
        "non-root",
        "read-only root filesystem",
        "deny docker socket mounts, host mounts",
        "default-deny network access",
        "block dynamic package installation at runtime",
        "redact logs by default",
    ):
        assert term in normalized_phase
        assert term in normalized_sandbox

    assert "cpu/memory/pid/time/input/output/recursion limits" in normalized_phase
    assert "cpu, memory, pid, time, input, output, and recursion limits" in normalized_sandbox

    assert (
        "current target backend and worker attestation stays in force in phase 01"
        in normalized_phase
    )
    assert "future sandbox runtime attestation is required" in normalized_phase


def test_phase01_markdown_evidence_snapshot_has_no_broken_inline_relative_markdown_links() -> None:
    audit = _audit_markdown(_phase01_canonical_markdown_scope())
    verify = _normalized_text(VERIFY)

    assert audit.files == _phase01_canonical_markdown_scope()
    assert len(audit.inline_relative_markdown_links) > 0
    evidence = (
        "The explicit canonical Phase 01 Markdown scope was audited for inline "
        "relative Markdown links and has zero broken targets."
    )
    assert evidence in _normalized_text(PHASE01)
    assert (
        "Markdown link evidence should state that the explicit canonical Phase 01 "
        "Markdown scope was audited for inline relative Markdown links and has zero "
        "broken targets." in verify
    )


def test_phase01_release_boundary_evidence_matches_current_authority_surfaces() -> None:
    phase = _text(PHASE01)
    readme = _text(README)
    release = _text(RELEASE)

    assert "public source clone boundary" in phase
    assert "filtered PressRoom release tree" in phase
    assert "scripts/check-public-boundary.py --include-untracked" in phase
    assert "scripts/prepare_pressroom_release.py" in phase
    assert ".github/pressroom/ci.yml" in phase
    assert "python3 scripts/generate-public-fixtures.py --check" in phase
    assert "python3 scripts/check-license-scope.py" in phase

    shared_boundary = (
        "The public source clone boundary is the set of code, tests, docs, and fixtures"
    )
    assert shared_boundary in readme
    assert shared_boundary in release
    phase09_release_tree = "Phase 09 does not require an allowlist expansion for the release tree."
    assert phase09_release_tree in _normalized_text(README)
    assert phase09_release_tree in _normalized_text(RELEASE)


def test_phase09_is_complete_and_does_not_block_phase10() -> None:
    phase09 = _text(PHASE09)
    normalized_phase09 = _normalized_text(PHASE09)
    normalized_readme = _normalized_text(README)

    assert "Status: Complete" in phase09
    assert "full Modal-based Test Workbench" in normalized_phase09
    assert "test case CRUD API" in normalized_phase09
    assert "upstream scope execution" in normalized_phase09
    assert "Output Inspector" in normalized_phase09
    assert "code editor" in normalized_phase09
    assert "Apply flow" in normalized_phase09
    assert "workspace RBAC" in normalized_phase09
    assert "in-memory store with TTL cleanup" in normalized_phase09
    assert "target DAG scheduler" in normalized_phase09
    assert "Phase 10 stays unblocked" in normalized_phase09

    assert "Phase 09 Workbench" in normalized_readme
    assert "Phase 09 Workbench on codex/adaptor-iteration-qa-recovery" in normalized_readme
    assert "Phase 10 stays unblocked" in normalized_readme
