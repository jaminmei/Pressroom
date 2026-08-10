from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("check-public-boundary.py")
PUBLIC_NAME = "ricoyudog"
PUBLIC_EMAIL = "73219750+ricoyudog@users.noreply.github.com"


def _prepare_repo(tmp_path: Path, manifest: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    scripts = repo / "scripts"
    scripts.mkdir()
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    (scripts / "public-binary-assets.txt").write_text(manifest, encoding="utf-8")
    frontend = repo / "frontend"
    frontend.mkdir()
    (frontend / "package-lock.json").write_text('{"packages": {}}\n', encoding="utf-8")
    website = repo / "website"
    website.mkdir()
    (website / "package-lock.json").write_text('{"packages": {}}\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    return repo


def _run_tree(
    repo: Path,
    *,
    include_untracked: bool = True,
    policy_files: tuple[Path, ...] = (),
    initial_release_tag: str | None = None,
    expected_origin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    args = ["--include-untracked"] if include_untracked else []
    for policy_file in policy_files:
        args.extend(("--deny-pattern-file", str(policy_file)))
    if initial_release_tag is not None:
        args.extend(("--initial-release-tag", initial_release_tag))
    if expected_origin is not None:
        args.extend(("--expected-origin", expected_origin))
    return subprocess.run(
        [sys.executable, "scripts/check-public-boundary.py", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def _run_artifact(
    repo: Path,
    *scan_dirs: str,
    policy_files: tuple[Path, ...] = (),
) -> subprocess.CompletedProcess[str]:
    args = [argument for directory in scan_dirs for argument in ("--scan-dir", directory)]
    for policy_file in policy_files:
        args.extend(("--deny-pattern-file", str(policy_file)))
    return subprocess.run(
        [sys.executable, "scripts/check-public-boundary.py", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def _identity_env(name: str = PUBLIC_NAME, email: str = PUBLIC_EMAIL) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }
    )
    return env


def _commit_all(
    repo: Path,
    message: str,
    *,
    name: str = PUBLIC_NAME,
    email: str = PUBLIC_EMAIL,
    allow_empty_message: bool = False,
) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    command = ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message]
    if allow_empty_message:
        command.append("--allow-empty-message")
    subprocess.run(command, cwd=repo, check=True, env=_identity_env(name, email))


def test_rejects_path_outside_the_public_allowlist(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    note = repo / "release-notes-draft/notes.txt"
    note.parent.mkdir()
    note.write_text("draft", encoding="utf-8")

    result = _run_tree(repo)

    assert result.returncode == 1
    assert "path is outside the public allowlist" in result.stderr


def test_ignores_tracked_files_deleted_from_the_candidate_tree(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    retired = repo / "docs/assets/readme/retired.webp"
    retired.parent.mkdir(parents=True)
    retired.write_bytes(b"retired-public-asset")
    _commit_all(repo, "add retired asset")
    retired.unlink()

    result = _run_tree(repo)

    assert result.returncode == 0, result.stderr


def test_allows_only_the_approved_root_readme_localization(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    (repo / "README.md").write_text("# English\n", encoding="utf-8")
    (repo / "README.zh-CN.md").write_text("# 简体中文\n", encoding="utf-8")

    allowed = _run_tree(repo)

    assert allowed.returncode == 0, allowed.stderr

    (repo / "README.fr.md").write_text("# Français\n", encoding="utf-8")
    rejected = _run_tree(repo)

    assert rejected.returncode == 1
    assert "path is outside the public allowlist: README.fr.md" in rejected.stderr


def test_allows_only_public_playwright_and_fixture_subtrees(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    public_test = repo / "frontend/e2e/public/smoke.spec.ts"
    public_test.parent.mkdir(parents=True)
    public_test.write_text("export {};\n", encoding="utf-8")
    internal_test = repo / "frontend/e2e/manual-acceptance.spec.ts"
    internal_test.write_text("export {};\n", encoding="utf-8")

    result = _run_tree(repo)

    assert result.returncode == 1
    assert (
        "path is outside the public E2E allowlist: frontend/e2e/manual-acceptance.spec.ts"
    ) in result.stderr
    assert "frontend/e2e/public/smoke.spec.ts" not in result.stderr


def test_rejects_unknown_frontend_subtree(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    baseline = repo / "frontend/test-baselines/known-failures.json"
    baseline.parent.mkdir()
    baseline.write_text("{}\n", encoding="utf-8")

    result = _run_tree(repo)

    assert result.returncode == 1
    assert (
        "path is outside the public frontend allowlist: frontend/test-baselines/known-failures.json"
    ) in result.stderr


def test_rejects_unknown_public_script_and_document(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    private_script = repo / "scripts/manual-acceptance.sh"
    private_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    draft = repo / "docs/release-roadmap.md"
    draft.parent.mkdir()
    draft.write_text("draft\n", encoding="utf-8")

    result = _run_tree(repo)

    assert result.returncode == 1
    assert (
        "path is outside the public scripts allowlist: scripts/manual-acceptance.sh"
        in result.stderr
    )
    assert "path is outside the public docs allowlist: docs/release-roadmap.md" in result.stderr


def test_allows_only_manifested_website_visual_assets(tmp_path: Path) -> None:
    payload = b"synthetic-readme-screenshot"
    digest = hashlib.sha256(payload).hexdigest()
    approved_path = "website/public/images/product/workflow-editor.webp"
    repo = _prepare_repo(tmp_path, f"{digest}  {approved_path}\n")
    approved = repo / approved_path
    approved.parent.mkdir(parents=True)
    approved.write_bytes(payload)

    allowed = _run_tree(repo)

    assert allowed.returncode == 0, allowed.stderr

    unapproved = repo / "website/public/images/product/private-dashboard.webp"
    unapproved.write_bytes(b"not-approved")
    rejected = _run_tree(repo)

    assert rejected.returncode == 1
    assert (
        "unapproved binary asset: website/public/images/product/private-dashboard.webp"
    ) in rejected.stderr


def test_allows_only_curated_website_structure(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    approved = {
        "website/index.md": "# Docs\n",
        "website/zh-CN/index.md": "# 文档\n",
        "website/getting-started/overview.md": "# Overview\n",
        "website/.vitepress/config.mts": "export default {};\n",
        "website/.vitepress/theme/styles/base.css": ":root {}\n",
        "website/public/favicon.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>\n",
    }
    for filename, content in approved.items():
        path = repo / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    allowed = _run_tree(repo)

    assert allowed.returncode == 0, allowed.stderr

    cache = repo / "website/.vitepress/cache/private.json"
    cache.parent.mkdir(parents=True)
    cache.write_text("{}\n", encoding="utf-8")
    unknown_locale = repo / "website/fr/index.md"
    unknown_locale.parent.mkdir(parents=True)
    unknown_locale.write_text("# Privé\n", encoding="utf-8")

    rejected = _run_tree(repo)

    assert rejected.returncode == 1
    assert (
        "path is outside the public website allowlist: website/.vitepress/cache/private.json"
        in rejected.stderr
    )
    assert "path is outside the public website allowlist: website/fr/index.md" in rejected.stderr


def test_allows_curated_public_knowledge_and_agent_aids(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    pages = {
        "wiki/index.md": "# Wiki\n",
        "wiki/architecture/overview.md": "# Overview\n",
        "wiki/migrations/_index.md": "# Migrations\n",
        "wiki/migrations/example/README.md": "# Example\n",
        "memory/pitfalls.md": "# Pitfalls\n",
        "memory/session-bridge.md": "# Session Bridge\n",
        ".claude/settings.json": "{}\n",
        ".claude/commands/corgi/verify.md": "# Verify\n",
        ".claude/skills/creating-backlog-issue-card/SKILL.md": "# Skill\n",
    }
    for name, content in pages.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    result = _run_tree(repo)

    assert result.returncode == 0


def test_rejects_unapproved_public_knowledge_and_agent_paths(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    local_settings = repo / ".claude/settings.local.json"
    local_settings.parent.mkdir()
    local_settings.write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", ".claude/settings.local.json"], cwd=repo, check=True)
    screenshot = repo / "wiki/screenshots/overview.png"
    screenshot.parent.mkdir(parents=True)
    screenshot.write_bytes(b"not-an-approved-image")
    private_migration = repo / "wiki/migrations/example/private.json"
    private_migration.parent.mkdir(parents=True)
    private_migration.write_text("{}\n", encoding="utf-8")

    result = _run_tree(repo)

    assert result.returncode == 1
    assert (
        "path is outside the public Claude allowlist: .claude/settings.local.json" in result.stderr
    )
    assert (
        "path is outside the public wiki allowlist: wiki/screenshots/overview.png" in result.stderr
    )
    assert (
        "path is outside the public wiki allowlist: wiki/migrations/example/private.json"
        in result.stderr
    )


def test_allows_frontend_dependency_audit_script(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    audit = repo / "scripts/check-frontend-audit.py"
    audit.write_text("raise SystemExit(0)\n", encoding="utf-8")

    result = _run_tree(repo)

    assert result.returncode == 0


def test_allows_release_provenance_scripts(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    checker = repo / "scripts/check_release_provenance.py"
    checker.write_text("raise SystemExit(0)\n", encoding="utf-8")
    tests = repo / "scripts/check_release_provenance_test.py"
    tests.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")

    result = _run_tree(repo)

    assert result.returncode == 0


def test_rejects_unsafe_placeholder_but_allows_change_member_label(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    unsafe_placeholder = "change" + "me"
    (repo / "README.md").write_text(f"password={unsafe_placeholder}", encoding="utf-8")
    label = repo / "frontend/src/label.ts"
    label.parent.mkdir()
    label.write_text('export const changeMemberRole = "Change Member Role";', encoding="utf-8")

    result = _run_tree(repo)

    assert result.returncode == 1
    assert "dangerous default detected (unsafe placeholder credential): README.md" in result.stderr
    assert "frontend/label.ts" not in result.stderr


def test_rejects_sensitive_literal_fallback_in_deployment_config(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    fallback = "$" + "{API_TOKEN:-example-token}"
    (repo / "docker-compose.yml").write_text(
        f"services:\n  app:\n    environment:\n      - API_TOKEN={fallback}\n",
        encoding="utf-8",
    )

    result = _run_tree(repo)

    assert result.returncode == 1
    assert "literal fallback for a sensitive environment variable" in result.stderr


def test_treats_pressroom_workflow_template_as_deployment_config(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    fallback = "$" + "{API_TOKEN:-example-token}"
    template = repo / ".github/pressroom/ci.yml"
    template.parent.mkdir(parents=True)
    template.write_text(
        f"env:\n  API_TOKEN: {fallback}\n",
        encoding="utf-8",
    )

    result = _run_tree(repo)

    assert result.returncode == 1
    assert "literal fallback for a sensitive environment variable" in result.stderr


def test_rejects_literal_dsn_credentials_in_deployment_config(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    (repo / "alembic.ini").write_text(
        "[alembic]\nsqlalchemy.url = postgresql://app:weak-default@db/app\n",
        encoding="utf-8",
    )

    result = _run_tree(repo)

    assert result.returncode == 1
    assert "literal credential embedded in a deployment DSN" in result.stderr


def test_allows_documented_dsn_placeholders_in_env_example(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    (repo / ".env.example").write_text(
        "DATABASE_URL=postgresql://app:replace_with_a_strong_password@db/app\n",
        encoding="utf-8",
    )

    result = _run_tree(repo)

    assert result.returncode == 0, result.stderr


def test_external_private_policy_scans_paths_and_text_without_echoing_rule(
    tmp_path: Path,
) -> None:
    repo = _prepare_repo(tmp_path, "")
    private_rule = "violet[-_]otter"
    policy = tmp_path / "private.rules"
    policy.write_text(private_rule + "\n", encoding="utf-8")
    matched_path = repo / "app/violet_otter.py"
    matched_path.parent.mkdir()
    matched_path.write_text("codename = 'Violet-Otter'\n", encoding="utf-8")

    result = _run_tree(repo, policy_files=(policy,))

    assert result.returncode == 1
    assert "private policy match in path: app/violet_otter.py" in result.stderr
    assert "private policy match in text: app/violet_otter.py" in result.stderr
    assert private_rule not in result.stderr
    assert "Violet-Otter" not in result.stderr


def test_private_policy_file_must_remain_outside_repository(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    policy = repo / "scripts/private.rules"
    policy.write_text("violet[-_]otter\n", encoding="utf-8")

    result = _run_tree(repo, policy_files=(policy,))

    assert result.returncode == 1
    assert "private policy files must remain outside the public repository" in result.stderr


def test_allows_repository_attributes_for_binary_fixtures(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    (repo / ".gitattributes").write_text("*.pdf binary\n", encoding="utf-8")

    result = _run_tree(repo)

    assert result.returncode == 0, result.stderr


def test_allows_only_manifested_binary(tmp_path: Path) -> None:
    payload = b"\x89PNG\r\n"
    digest = hashlib.sha256(payload).hexdigest()
    repo = _prepare_repo(tmp_path, f"{digest}  frontend/public/logo.png\n")
    approved = repo / "frontend/public/logo.png"
    approved.parent.mkdir(parents=True)
    approved.write_bytes(payload)

    result = _run_tree(repo)

    assert result.returncode == 0, result.stderr


def test_rejects_development_markers_in_production_artifacts(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    bundle = repo / "dist/assets/app.js"
    bundle.parent.mkdir(parents=True)
    bundle.write_text("window.__wfstore = {}; console.log('[debug canvas]')", encoding="utf-8")

    result = _run_artifact(repo, "dist")

    assert result.returncode == 1
    assert "development state store" in result.stderr
    assert "debug diagnostic" in result.stderr


def test_private_policy_scans_artifacts_without_echoing_rule(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    policy = tmp_path / "private.rules"
    policy.write_text("violet[-_]otter\n", encoding="utf-8")
    bundle = repo / "dist/assets/app.js"
    bundle.parent.mkdir(parents=True)
    bundle.write_text("const codename = 'violet_otter';", encoding="utf-8")

    result = _run_artifact(repo, "dist", policy_files=(policy,))

    assert result.returncode == 1
    assert "private policy match in artifact text: dist/assets/app.js" in result.stderr
    assert "violet_otter" not in result.stderr


def test_rejects_unapproved_binary_with_disguised_suffix(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    disguised = repo / "tests/fixture.dat"
    disguised.parent.mkdir(parents=True)
    disguised.write_bytes(b"public-prefix\x00binary-payload")

    result = _run_tree(repo)

    assert result.returncode == 1
    assert "unapproved binary asset: tests/fixture.dat" in result.stderr


def test_rejects_gitlinks(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    subprocess.run(
        [
            "git",
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{('1' * 40)},app/vendor",
        ],
        cwd=repo,
        check=True,
    )

    result = _run_tree(repo)

    assert result.returncode == 1
    assert "gitlinks and submodules are not allowed: app/vendor" in result.stderr


def test_rejects_symbolic_links_in_source_tree(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    target = repo / "app/target.py"
    target.parent.mkdir()
    target.write_text("value = 1\n", encoding="utf-8")
    (repo / "app/linked.py").symlink_to(target.name)

    result = _run_tree(repo)

    assert result.returncode == 1
    assert "symbolic links are not allowed: app/linked.py" in result.stderr


@pytest.mark.parametrize(
    "lockfile",
    ("frontend/package-lock.json", "website/package-lock.json"),
)
def test_rejects_non_public_npm_resolution(tmp_path: Path, lockfile: str) -> None:
    repo = _prepare_repo(tmp_path, "")
    lock = {
        "packages": {
            "node_modules/example": {
                "resolved": "https://packages.example.invalid/example-1.0.0.tgz"
            }
        }
    }
    (repo / lockfile).write_text(json.dumps(lock), encoding="utf-8")

    result = _run_tree(repo)

    assert result.returncode == 1
    assert "non-public npm registry for node_modules/example" in result.stderr
    assert lockfile in result.stderr
    assert "packages.example.invalid" not in result.stderr


def test_rejects_missing_website_lock(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    (repo / "website/package-lock.json").unlink()

    result = _run_tree(repo)

    assert result.returncode == 1
    assert "website/package-lock.json is missing" in result.stderr


def test_artifact_scan_allows_approved_binary_without_requiring_manifest_paths(
    tmp_path: Path,
) -> None:
    payload = b"\x89PNG\r\n"
    digest = hashlib.sha256(payload).hexdigest()
    repo = _prepare_repo(
        tmp_path,
        f"{digest}  frontend/e2e/fixtures/source-only.png\n",
    )
    artifact = repo / "dist/assets/bundled-logo.png"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(payload)

    result = _run_artifact(repo, "dist")

    assert result.returncode == 0, result.stderr
    assert "approved binary missing from tree" not in result.stderr


def test_default_tree_scan_still_requires_every_manifest_path(tmp_path: Path) -> None:
    payload = b"\x89PNG\r\n"
    digest = hashlib.sha256(payload).hexdigest()
    repo = _prepare_repo(tmp_path, f"{digest}  frontend/public/missing.png\n")
    subprocess.run(
        ["git", "add", "scripts", "frontend/package-lock.json"],
        cwd=repo,
        check=True,
    )

    result = _run_tree(repo, include_untracked=False)

    assert result.returncode == 1
    assert "approved binary missing from tree: frontend/public/missing.png" in result.stderr


def test_untracked_tree_scan_still_rejects_manifest_hash_mismatch(tmp_path: Path) -> None:
    expected = hashlib.sha256(b"approved").hexdigest()
    repo = _prepare_repo(tmp_path, f"{expected}  frontend/public/logo.png\n")
    asset = repo / "frontend/public/logo.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"different")

    result = _run_tree(repo)

    assert result.returncode == 1
    assert "binary asset hash mismatch: frontend/public/logo.png" in result.stderr


def test_artifact_scan_rejects_unapproved_binary(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    artifact = repo / "dist/assets/model.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"unapproved-binary")

    result = _run_artifact(repo, "dist")

    assert result.returncode == 1
    assert "unapproved binary asset in artifact: dist/assets/model.bin" in result.stderr


def test_artifact_scan_rejects_symbolic_links(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    artifact_dir = repo / "dist"
    artifact_dir.mkdir()
    target = artifact_dir / "target.js"
    target.write_text("console.info('production')", encoding="utf-8")
    (artifact_dir / "linked.js").symlink_to(target.name)

    result = _run_artifact(repo, "dist")

    assert result.returncode == 1
    assert "symbolic links are not allowed in artifacts: dist/linked.js" in result.stderr


def test_artifact_scan_rejects_symbolic_link_scan_root(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    real_artifact_dir = repo / "real-dist"
    real_artifact_dir.mkdir()
    (repo / "dist").symlink_to(real_artifact_dir.name, target_is_directory=True)

    result = _run_artifact(repo, "dist")

    assert result.returncode == 1
    assert "symbolic links are not allowed in artifacts: dist" in result.stderr


def test_accepts_single_parentless_release_root_and_semver_tag(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    subprocess.run(["git", "tag", "v0.2.0"], cwd=repo, check=True)

    result = _run_tree(repo, include_untracked=False)

    assert result.returncode == 0, result.stderr
    root_line = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert len(root_line) == 1


def test_initial_release_gate_accepts_root_before_and_after_expected_tag(
    tmp_path: Path,
) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")

    before_tag = _run_tree(
        repo,
        include_untracked=False,
        initial_release_tag="v0.2.0",
    )

    assert before_tag.returncode == 0, before_tag.stderr

    subprocess.run(["git", "tag", "v0.2.0"], cwd=repo, check=True)
    after_tag = _run_tree(
        repo,
        include_untracked=False,
        initial_release_tag="v0.2.0",
    )

    assert after_tag.returncode == 0, after_tag.stderr


def test_initial_release_gate_rejects_more_than_one_commit(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    (repo / "README.md").write_text("Second commit\n", encoding="utf-8")
    _commit_all(repo, "Second public commit")

    result = _run_tree(
        repo,
        include_untracked=False,
        initial_release_tag="v0.2.0",
    )

    assert result.returncode == 1
    assert "initial release refs must contain exactly one commit" in result.stderr


def test_initial_release_gate_rejects_multiple_local_heads(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    subprocess.run(["git", "branch", "candidate"], cwd=repo, check=True)

    result = _run_tree(
        repo,
        include_untracked=False,
        initial_release_tag="v0.2.0",
    )

    assert result.returncode == 1
    assert "initial release may have at most one local head" in result.stderr


def test_initial_release_gate_allows_remote_heads_at_the_sole_commit(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", commit],
        cwd=repo,
        check=True,
    )

    result = _run_tree(
        repo,
        include_untracked=False,
        initial_release_tag="v0.2.0",
    )

    assert result.returncode == 0, result.stderr


def test_initial_release_gate_rejects_unexpected_semver_tag(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    subprocess.run(["git", "tag", "v0.1.0"], cwd=repo, check=True)

    result = _run_tree(
        repo,
        include_untracked=False,
        initial_release_tag="v0.2.0",
    )

    assert result.returncode == 1
    assert "initial release has an unexpected tag" in result.stderr
    assert "v0.1.0" not in result.stderr


def test_initial_release_gate_rejects_other_refs(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/archive/root", commit],
        cwd=repo,
        check=True,
    )

    result = _run_tree(
        repo,
        include_untracked=False,
        initial_release_tag="v0.2.0",
    )

    assert result.returncode == 1
    assert "initial release has an unexpected ref" in result.stderr
    assert "refs/archive/root" not in result.stderr


def test_allows_later_linear_commits_from_other_public_contributors(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    (repo / "README.md").write_text("Public documentation\n", encoding="utf-8")
    _commit_all(
        repo,
        "Improve documentation",
        name="Public Contributor",
        email="contributor@example.org",
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/example/document-conversion.git"],
        cwd=repo,
        check=True,
    )

    result = _run_tree(repo, include_untracked=False)

    assert result.returncode == 0, result.stderr


def test_rejects_multiple_unrelated_history_roots(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    unrelated = subprocess.run(
        ["git", "commit-tree", tree],
        cwd=repo,
        check=True,
        input="Independent history\n",
        capture_output=True,
        text=True,
        env=_identity_env(),
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/heads/alternate", unrelated],
        cwd=repo,
        check=True,
    )

    result = _run_tree(repo, include_untracked=False)

    assert result.returncode == 1
    assert "public refs must share exactly one history root" in result.stderr


def test_rejects_merge_that_introduces_an_unrelated_root(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    first_root = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    unrelated_root = subprocess.run(
        ["git", "commit-tree", tree],
        cwd=repo,
        check=True,
        input="Independent history\n",
        capture_output=True,
        text=True,
        env=_identity_env(),
    ).stdout.strip()
    merge = subprocess.run(
        ["git", "commit-tree", tree, "-p", first_root, "-p", unrelated_root],
        cwd=repo,
        check=True,
        input="Invalid combined history\n",
        capture_output=True,
        text=True,
        env=_identity_env(),
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/heads/main", merge, first_root],
        cwd=repo,
        check=True,
    )

    result = _run_tree(repo, include_untracked=False)

    assert result.returncode == 1
    assert "public refs must share exactly one history root" in result.stderr


def test_rejects_unapproved_initial_release_identity(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(
        repo,
        "Initial public release",
        name="Example Maintainer",
        email="maintainer@example.org",
    )

    result = _run_tree(repo, include_untracked=False)

    assert result.returncode == 1
    assert "initial release root has unapproved author or committer metadata" in result.stderr
    assert "maintainer@example.org" not in result.stderr


def test_rejects_empty_initial_release_message(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "", allow_empty_message=True)

    result = _run_tree(repo, include_untracked=False)

    assert result.returncode == 1
    assert "initial release root must have a non-empty commit message" in result.stderr


def test_rejects_non_semver_tag_without_echoing_tag_name(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    tag_name = "release-candidate"
    subprocess.run(["git", "tag", tag_name], cwd=repo, check=True)

    result = _run_tree(repo, include_untracked=False)

    assert result.returncode == 1
    assert "repository has a tag that is not a semantic release version" in result.stderr
    assert tag_name not in result.stderr


def test_rejects_non_public_remote_without_echoing_url(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    remote_url = "https://example.invalid/example/repository.git"
    subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=repo, check=True)

    result = _run_tree(repo, include_untracked=False)

    assert result.returncode == 1
    assert "repository remote does not use an approved public URL" in result.stderr
    assert remote_url not in result.stderr


def test_expected_origin_accepts_matching_fetch_and_push_urls(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/jaminmei/Pressroom.git"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "remote", "set-url", "--push", "origin", "git@github.com:jaminmei/Pressroom.git"],
        cwd=repo,
        check=True,
    )

    result = _run_tree(repo, include_untracked=False, expected_origin="jaminmei/Pressroom")

    assert result.returncode == 0, result.stderr


def test_expected_origin_accepts_matching_fetch_with_implicit_push_url(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/jaminmei/Pressroom.git"],
        cwd=repo,
        check=True,
    )

    result = _run_tree(repo, include_untracked=False, expected_origin="jaminmei/Pressroom")

    assert result.returncode == 0, result.stderr


def test_expected_origin_rejects_missing_remote(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")

    result = _run_tree(repo, include_untracked=False, expected_origin="jaminmei/Pressroom")

    assert result.returncode == 1
    assert "repository is missing the required origin remote" in result.stderr


def test_expected_origin_rejects_additional_remote_without_echoing_url(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/jaminmei/Pressroom.git"],
        cwd=repo,
        check=True,
    )
    extra_url = "https://github.com/example/internal-mirror.git"
    subprocess.run(["git", "remote", "add", "mirror", extra_url], cwd=repo, check=True)

    result = _run_tree(repo, include_untracked=False, expected_origin="jaminmei/Pressroom")

    assert result.returncode == 1
    assert "repository has an unapproved remote" in result.stderr
    assert extra_url not in result.stderr


def test_expected_origin_rejects_wrong_fetch_url_without_echoing_url(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    remote_url = "https://github.com/example/wrong-public-repository.git"
    subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=repo, check=True)

    result = _run_tree(repo, include_untracked=False, expected_origin="jaminmei/Pressroom")

    assert result.returncode == 1
    assert "repository origin fetch URL does not match the expected repository" in result.stderr
    assert remote_url not in result.stderr


def test_expected_origin_rejects_wrong_push_url_without_echoing_url(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/jaminmei/Pressroom.git"],
        cwd=repo,
        check=True,
    )
    push_url = "git@github.com:example/wrong-public-repository.git"
    subprocess.run(
        ["git", "remote", "set-url", "--push", "origin", push_url],
        cwd=repo,
        check=True,
    )

    result = _run_tree(repo, include_untracked=False, expected_origin="jaminmei/Pressroom")

    assert result.returncode == 1
    assert "repository origin push URL does not match the expected repository" in result.stderr
    assert push_url not in result.stderr


def test_expected_origin_rejects_instead_of_rewrite_without_echoing_url(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    expected_url = "https://github.com/jaminmei/Pressroom.git"
    rewritten_url = "https://github.com/example/rewritten-fetch.git"
    subprocess.run(["git", "remote", "add", "origin", expected_url], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", f"url.{rewritten_url}.insteadOf", expected_url],
        cwd=repo,
        check=True,
    )

    result = _run_tree(repo, include_untracked=False, expected_origin="jaminmei/Pressroom")

    assert result.returncode == 1
    assert "repository origin fetch URL does not match the expected repository" in result.stderr
    assert rewritten_url not in result.stderr


def test_expected_origin_rejects_push_instead_of_rewrite_without_echoing_url(
    tmp_path: Path,
) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    expected_url = "https://github.com/jaminmei/Pressroom.git"
    rewritten_url = "https://github.com/example/rewritten-push.git"
    subprocess.run(["git", "remote", "add", "origin", expected_url], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", f"url.{rewritten_url}.pushInsteadOf", expected_url],
        cwd=repo,
        check=True,
    )

    result = _run_tree(repo, include_untracked=False, expected_origin="jaminmei/Pressroom")

    assert result.returncode == 1
    assert "repository origin push URL does not match the expected repository" in result.stderr
    assert rewritten_url not in result.stderr


def test_expected_origin_rejects_empty_fetch_url(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/jaminmei/Pressroom.git"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "--replace-all", "remote.origin.url", ""],
        cwd=repo,
        check=True,
    )

    result = _run_tree(repo, include_untracked=False, expected_origin="jaminmei/Pressroom")

    assert result.returncode == 1
    assert "repository origin fetch URL does not match the expected repository" in result.stderr


def test_expected_origin_rejects_empty_push_url(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/jaminmei/Pressroom.git"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "remote.origin.pushurl", ""],
        cwd=repo,
        check=True,
    )

    result = _run_tree(repo, include_untracked=False, expected_origin="jaminmei/Pressroom")

    assert result.returncode == 1
    assert "repository origin push URL does not match the expected repository" in result.stderr


def test_expected_origin_rejects_duplicate_fetch_urls(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    expected_url = "https://github.com/jaminmei/Pressroom.git"
    subprocess.run(["git", "remote", "add", "origin", expected_url], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "--add", "remote.origin.url", expected_url],
        cwd=repo,
        check=True,
    )

    result = _run_tree(repo, include_untracked=False, expected_origin="jaminmei/Pressroom")

    assert result.returncode == 1
    assert "repository origin fetch URL does not match the expected repository" in result.stderr


def test_expected_origin_rejects_duplicate_push_urls(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    _commit_all(repo, "Initial public release")
    expected_url = "https://github.com/jaminmei/Pressroom.git"
    subprocess.run(["git", "remote", "add", "origin", expected_url], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "--add", "remote.origin.pushurl", expected_url],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "--add", "remote.origin.pushurl", expected_url],
        cwd=repo,
        check=True,
    )

    result = _run_tree(repo, include_untracked=False, expected_origin="jaminmei/Pressroom")

    assert result.returncode == 1
    assert "repository origin push URL does not match the expected repository" in result.stderr


def test_private_policy_scans_history_metadata_without_echoing_rule(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path, "")
    private_rule = "violet[-_]otter"
    policy = tmp_path / "private.rules"
    policy.write_text(private_rule + "\n", encoding="utf-8")
    _commit_all(repo, "Initial public release: violet_otter")

    result = _run_tree(repo, include_untracked=False, policy_files=(policy,))

    assert result.returncode == 1
    assert "private policy match in repository metadata" in result.stderr
    assert private_rule not in result.stderr
    assert "violet_otter" not in result.stderr
