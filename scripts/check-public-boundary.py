#!/usr/bin/env python3
"""Validate the generic safety boundary of the public source tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]

INITIAL_RELEASE_NAME = "ricoyudog"
INITIAL_RELEASE_EMAIL = "73219750+ricoyudog@users.noreply.github.com"
PUBLIC_NPM_REGISTRY = "registry.npmjs.org"
PUBLIC_GIT_HOST = "github.com"
PUBLIC_E2E_SUBTREES = {"fixtures", "public"}
PUBLIC_FRONTEND_ROOTS = {
    ".dockerignore",
    ".gitignore",
    ".prettierignore",
    ".prettierrc",
    "Dockerfile",
    "e2e",
    "eslint.config.js",
    "index.html",
    "nginx.conf",
    "package-lock.json",
    "package.json",
    "playwright.public.config.ts",
    "public",
    "src",
    "tsconfig.app.json",
    "tsconfig.json",
    "tsconfig.node.json",
    "vite.config.ts",
}
PUBLIC_SCRIPT_FILES = {
    "assign-legacy-providers.py",
    "assign-legacy-providers_test.py",
    "check-license-scope.py",
    "check-frontend-audit.py",
    "check-public-boundary.py",
    "check_public_release_llm.py",
    "check_public_release_llm_test.py",
    "check_release_provenance.py",
    "check_release_provenance_test.py",
    "check-rbac-test-coverage.sh",
    "check-workspace-rbac-readiness.py",
    "check-workspace-runtime-env.py",
    "check-workspace-runtime-env_test.py",
    "check_license_scope_test.py",
    "check_public_boundary_test.py",
    "collect-service-logs.sh",
    "generate-public-fixtures.py",
    "generate_public_fixtures_test.py",
    "init-db.sql",
    "migrate_vlm_to_model.py",
    "public-binary-assets.txt",
    "prepare_pressroom_release.py",
    "prepare_pressroom_release_test.py",
    "rehome-dataset-core.py",
    "rehome-dataset-core_test.py",
    "start_worker.sh",
    "stress-test.py",
    "test-full-profile-connectivity.sh",
    "wait-for-services.sh",
}
PUBLIC_DOC_FILES = {
    "dependency-audit-exceptions.md",
    "model-licenses.md",
}

ALLOWED_ROOTS = {
    ".dockerignore",
    ".env.example",
    ".gitattributes",
    ".github",
    ".gitleaks.toml",
    ".gitignore",
    ".lychee.toml",
    "AGENTS.md",
    "ASSETS.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "Dockerfile.backend",
    "LICENSE",
    "LICENSES",
    "README.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "TRADEMARKS.md",
    "alembic",
    "alembic.ini",
    "app",
    "docker-compose.yml",
    "docs",
    "engines",
    "frontend",
    "pyproject.toml",
    "requirements-dev.lock",
    "requirements-dev.txt",
    "requirements.lock",
    "requirements.txt",
    "scripts",
    "tests",
}

BINARY_SUFFIXES = {
    ".7z",
    ".bin",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".onnx",
    ".pdf",
    ".png",
    ".pt",
    ".pth",
    ".tar",
    ".ttf",
    ".webp",
    ".woff",
    ".woff2",
    ".zip",
}

_UNSAFE_PLACEHOLDER = "change" + "me"
DANGEROUS_DEFAULT_PATTERNS = (
    (
        re.compile(r"\b" + re.escape(_UNSAFE_PLACEHOLDER) + r"\b", re.IGNORECASE),
        "unsafe placeholder credential",
    ),
)
SENSITIVE_ENV_FALLBACK = re.compile(
    r"\$\{[a-z0-9_]*(?:password|secret|token|api[_-]?key|encryption[_-]?key)"
    r"[a-z0-9_]*:-[^}\r\n]+\}",
    re.IGNORECASE,
)
LITERAL_DSN_CREDENTIAL = re.compile(
    r"\b[a-z][a-z0-9+.-]*://(?:[^\s/:@${}]+)?:"
    r"(?P<password>[^\s@/${}]+)@",
    re.IGNORECASE,
)
DOCUMENTED_CREDENTIAL_PLACEHOLDER = re.compile(
    r"(?:replace[_-]with|example|your[_-]|<)",
    re.IGNORECASE,
)
ARTIFACT_ONLY_TEXT_PATTERNS = (
    (re.compile(r"__wfstore", re.IGNORECASE), "development state store"),
    (re.compile(r"\[debug canvas\]", re.IGNORECASE), "debug diagnostic"),
)
SEMVER_TAG = re.compile(
    r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*)?"
    r"(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?"
)


def _run_git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    )


def _git_paths(include_untracked: bool) -> list[Path]:
    args = ["ls-files", "-z"]
    if include_untracked:
        args.extend(["--cached", "--others", "--exclude-standard"])
    result = _run_git(*args)
    if result.returncode != 0:
        raise RuntimeError("git could not enumerate the public tree")
    return [Path(raw.decode()) for raw in result.stdout.split(b"\0") if raw]


def _gitlink_paths() -> set[str]:
    result = _run_git("ls-files", "--stage", "-z")
    if result.returncode != 0:
        return set()
    gitlinks: set[str] = set()
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, separator, raw_path = entry.partition(b"\t")
        if separator and metadata.startswith(b"160000 "):
            gitlinks.add(raw_path.decode())
    return gitlinks


def _approved_binaries() -> dict[str, str]:
    manifest = REPO_ROOT / "scripts/public-binary-assets.txt"
    approved: dict[str, str] = {}
    for raw_line in manifest.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        digest, separator, path = line.partition("  ")
        if (
            not separator
            or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None
            or not path
            or Path(path).is_absolute()
            or ".." in Path(path).parts
        ):
            raise ValueError("invalid binary manifest")
        approved[path] = digest.lower()
    return approved


def _has_binary_content(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if b"\0" in data:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _is_deployment_config(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith(".env") or name.startswith("dockerfile") or path.suffix.lower() == ".ini":
        return True
    if name.startswith(("docker-compose", "compose.")) and path.suffix.lower() in {
        ".yml",
        ".yaml",
    }:
        return True
    return (len(path.parts) >= 2 and path.parts[:2] == (".github", "workflows")) or path == Path(
        ".github/pressroom/ci.yml"
    )


def _dangerous_default_labels(
    text: str,
    *,
    deployment_config: bool,
    allow_documented_placeholders: bool = False,
) -> list[str]:
    labels = [label for pattern, label in DANGEROUS_DEFAULT_PATTERNS if pattern.search(text)]
    if deployment_config and SENSITIVE_ENV_FALLBACK.search(text):
        labels.append("literal fallback for a sensitive environment variable")
    if deployment_config:
        for match in LITERAL_DSN_CREDENTIAL.finditer(text):
            password = match.group("password")
            if allow_documented_placeholders and DOCUMENTED_CREDENTIAL_PLACEHOLDER.match(password):
                continue
            labels.append("literal credential embedded in a deployment DSN")
            break
    return labels


def _load_private_patterns(
    policy_files: list[Path],
) -> tuple[list[re.Pattern[str]], list[str]]:
    patterns: list[re.Pattern[str]] = []
    errors: list[str] = []
    repository = REPO_ROOT.resolve()
    for policy_file in policy_files:
        resolved = policy_file.resolve()
        try:
            resolved.relative_to(repository)
        except ValueError:
            pass
        else:
            errors.append("private policy files must remain outside the public repository")
            continue
        try:
            lines = resolved.read_text(encoding="utf-8").splitlines()
        except OSError:
            errors.append("private policy file could not be read")
            continue
        for line_number, raw_line in enumerate(lines, start=1):
            expression = raw_line.strip()
            if not expression or expression.startswith("#"):
                continue
            try:
                patterns.append(re.compile(expression, re.IGNORECASE))
            except re.error:
                errors.append(
                    f"private policy file contains an invalid pattern on line {line_number}"
                )
    return patterns, errors


def _matches_private_policy(patterns: list[re.Pattern[str]], value: str) -> bool:
    return any(pattern.search(value) is not None for pattern in patterns)


def _read_text(path: Path) -> tuple[str | None, str | None]:
    try:
        data = path.read_bytes()
    except OSError:
        return None, f"cannot read file: {path}"
    if b"\0" in data:
        return None, None
    return data.decode("utf-8", errors="ignore"), None


def check_tree(paths: list[Path], private_patterns: list[re.Pattern[str]]) -> list[str]:
    errors: list[str] = []
    try:
        approved_binaries = _approved_binaries()
    except (OSError, ValueError):
        return ["binary asset manifest is missing or invalid"]
    gitlinks = _gitlink_paths()
    present = {path.as_posix() for path in paths}

    for relative in sorted(paths):
        relative_posix = relative.as_posix()
        parts = relative.parts
        if _matches_private_policy(private_patterns, relative_posix):
            errors.append(f"private policy match in path: {relative_posix}")
        if not parts or parts[0] not in ALLOWED_ROOTS:
            errors.append(f"path is outside the public allowlist: {relative_posix}")
            continue
        if len(parts) >= 2 and parts[0] == "frontend" and parts[1] not in PUBLIC_FRONTEND_ROOTS:
            errors.append(f"path is outside the public frontend allowlist: {relative_posix}")
            continue
        if (
            len(parts) >= 2
            and parts[:2] == ("frontend", "e2e")
            and (len(parts) < 3 or parts[2] not in PUBLIC_E2E_SUBTREES)
        ):
            errors.append(f"path is outside the public E2E allowlist: {relative_posix}")
            continue
        if parts[0] == "scripts" and (len(parts) != 2 or parts[1] not in PUBLIC_SCRIPT_FILES):
            errors.append(f"path is outside the public scripts allowlist: {relative_posix}")
            continue
        if parts[0] == "docs" and "/".join(parts[1:]) not in PUBLIC_DOC_FILES:
            errors.append(f"path is outside the public docs allowlist: {relative_posix}")
            continue
        if relative_posix in gitlinks:
            errors.append(f"gitlinks and submodules are not allowed: {relative_posix}")
            continue
        absolute = REPO_ROOT / relative
        if absolute.is_symlink():
            errors.append(f"symbolic links are not allowed: {relative_posix}")
            continue
        is_binary = relative.suffix.lower() in BINARY_SUFFIXES or (
            absolute.is_file() and _has_binary_content(absolute)
        )
        if is_binary:
            expected_digest = approved_binaries.get(relative_posix)
            if expected_digest is None:
                errors.append(f"unapproved binary asset: {relative_posix}")
            elif absolute.is_file():
                actual_digest = hashlib.sha256(absolute.read_bytes()).hexdigest()
                if actual_digest != expected_digest:
                    errors.append(f"binary asset hash mismatch: {relative_posix}")
            continue
        if not absolute.is_file():
            continue
        text, read_error = _read_text(absolute)
        if read_error:
            errors.append(read_error)
            continue
        if text is None:
            continue
        if _matches_private_policy(private_patterns, text):
            errors.append(f"private policy match in text: {relative_posix}")
        for label in _dangerous_default_labels(
            text,
            deployment_config=_is_deployment_config(relative),
            allow_documented_placeholders=relative.name.lower() == ".env.example",
        ):
            errors.append(f"dangerous default detected ({label}): {relative_posix}")

    missing = set(approved_binaries) - present
    errors.extend(f"approved binary missing from tree: {path}" for path in sorted(missing))
    errors.extend(_check_npm_registry())
    return errors


def _check_npm_registry() -> list[str]:
    lock_path = REPO_ROOT / "frontend/package-lock.json"
    if not lock_path.exists():
        return ["frontend/package-lock.json is missing"]
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["frontend/package-lock.json cannot be parsed"]

    packages = lock.get("packages", {})
    if not isinstance(packages, dict):
        return ["frontend/package-lock.json has no packages map"]
    errors: list[str] = []
    for package_path, metadata in packages.items():
        if not isinstance(metadata, dict):
            continue
        resolved = metadata.get("resolved")
        if resolved is None:
            continue
        if not isinstance(resolved, str):
            errors.append(f"invalid npm resolution for {package_path}")
            continue
        parsed = urlparse(resolved)
        try:
            port = parsed.port
        except ValueError:
            port = -1
        if (
            parsed.scheme != "https"
            or parsed.hostname != PUBLIC_NPM_REGISTRY
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or not parsed.path.startswith("/")
        ):
            errors.append(f"non-public npm registry for {package_path}")
    return errors


def _git_ref_exists(ref: str) -> bool:
    return _run_git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0


def _git_lines(*args: str) -> list[str]:
    result = _run_git(*args)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.decode(errors="replace").splitlines() if line]


def _git_config_values(key: str) -> list[str] | None:
    result = _run_git("config", "--get-all", key)
    if result.returncode == 1:
        return []
    if result.returncode != 0:
        return None
    return result.stdout.decode(errors="replace").splitlines()


def _git_command_values(*args: str) -> list[str] | None:
    result = _run_git(*args)
    if result.returncode != 0:
        return None
    return result.stdout.decode(errors="replace").splitlines()


def _is_approved_remote_url(url: str) -> bool:
    if re.fullmatch(r"git@github\.com:[^/\s:]+/[^/\s:]+(?:\.git)?", url):
        return True
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    if parsed.hostname != PUBLIC_GIT_HOST or parsed.password is not None:
        return False
    if parsed.scheme == "https":
        return parsed.username is None and port in {None, 443} and bool(parsed.path.strip("/"))
    if parsed.scheme == "ssh":
        return (
            parsed.username in {None, "git"} and port in {None, 22} and bool(parsed.path.strip("/"))
        )
    return False


def _parse_expected_origin(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]+", value) is None:
        raise argparse.ArgumentTypeError("expected origin must use the OWNER/REPO form")
    return value.casefold()


def _github_repository_from_remote_url(url: str) -> str | None:
    scp_match = re.fullmatch(r"git@github\.com:([^/\s:]+)/([^/\s:]+)", url)
    if scp_match is not None:
        owner, repository = scp_match.groups()
    else:
        parsed = urlparse(url)
        try:
            port = parsed.port
        except ValueError:
            return None
        if (
            parsed.hostname != PUBLIC_GIT_HOST
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            return None
        if parsed.scheme == "https":
            if parsed.username is not None or port not in {None, 443}:
                return None
        elif parsed.scheme == "ssh":
            if parsed.username not in {None, "git"} or port not in {None, 22}:
                return None
        else:
            return None
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 2:
            return None
        owner, repository = parts

    if repository.endswith(".git"):
        repository = repository[:-4]
    candidate = f"{owner}/{repository}"
    try:
        return _parse_expected_origin(candidate)
    except argparse.ArgumentTypeError:
        return None


def _urls_match_expected_repository(urls: list[str] | None, expected_origin: str) -> bool:
    return (
        urls is not None
        and len(urls) == 1
        and _github_repository_from_remote_url(urls[0]) == expected_origin
    )


def _check_remote_metadata(
    private_patterns: list[re.Pattern[str]],
    expected_origin: str | None = None,
) -> list[str]:
    errors: list[str] = []
    remotes = _git_lines("remote")
    if any(remote != "origin" for remote in remotes):
        errors.append("repository has an unapproved remote")
    for remote in remotes:
        urls = _git_lines("config", "--get-all", f"remote.{remote}.url")
        urls.extend(_git_lines("config", "--get-all", f"remote.{remote}.pushurl"))
        if not urls or any(not _is_approved_remote_url(url) for url in urls):
            errors.append("repository remote does not use an approved public URL")
        if any(_matches_private_policy(private_patterns, url) for url in urls):
            errors.append("private policy match in repository metadata")

    if expected_origin is not None:
        if "origin" not in remotes:
            errors.append("repository is missing the required origin remote")
        else:
            configured_fetch_urls = _git_config_values("remote.origin.url")
            effective_fetch_urls = _git_command_values("remote", "get-url", "--all", "origin")
            if not _urls_match_expected_repository(
                configured_fetch_urls, expected_origin
            ) or not _urls_match_expected_repository(effective_fetch_urls, expected_origin):
                errors.append("repository origin fetch URL does not match the expected repository")

            configured_push_urls = _git_config_values("remote.origin.pushurl")
            valid_configured_push = configured_push_urls == [] or _urls_match_expected_repository(
                configured_push_urls, expected_origin
            )
            effective_push_urls = _git_command_values(
                "remote", "get-url", "--push", "--all", "origin"
            )
            if not valid_configured_push or not _urls_match_expected_repository(
                effective_push_urls, expected_origin
            ):
                errors.append("repository origin push URL does not match the expected repository")

    tracking = _run_git("config", "--get-regexp", r"^branch\..*\.remote$")
    if tracking.returncode == 0:
        for line in tracking.stdout.decode(errors="replace").splitlines():
            _, _, remote = line.partition(" ")
            if remote not in {".", "origin"}:
                errors.append("branch tracks an unapproved remote")
            if _matches_private_policy(private_patterns, line):
                errors.append("private policy match in repository metadata")
    return errors


def _check_release_tags(private_patterns: list[re.Pattern[str]]) -> list[str]:
    errors: list[str] = []
    for ref in _git_lines("for-each-ref", "--format=%(refname)", "refs/tags"):
        name = ref.removeprefix("refs/tags/")
        if SEMVER_TAG.fullmatch(name) is None:
            errors.append("repository has a tag that is not a semantic release version")
        if not _git_ref_exists(ref):
            errors.append("release tag does not resolve to a commit")
        if _matches_private_policy(private_patterns, name):
            errors.append("private policy match in repository metadata")
    return errors


def _check_root_metadata(root: str) -> list[str]:
    errors: list[str] = []
    parent_line = _git_lines("rev-list", "--parents", "-n", "1", root)
    if len(parent_line) != 1 or len(parent_line[0].split()) != 1:
        errors.append("initial release root must not have a parent")

    metadata = _run_git("show", "-s", "--format=%an%x00%ae%x00%cn%x00%ce", root)
    fields = metadata.stdout.decode(errors="replace").strip().split("\0")
    if fields != [
        INITIAL_RELEASE_NAME,
        INITIAL_RELEASE_EMAIL,
        INITIAL_RELEASE_NAME,
        INITIAL_RELEASE_EMAIL,
    ]:
        errors.append("initial release root has unapproved author or committer metadata")

    message = _run_git("show", "-s", "--format=%B", root).stdout.decode(errors="replace")
    if not message.strip():
        errors.append("initial release root must have a non-empty commit message")
    tree = _run_git("ls-tree", "-r", "--name-only", root)
    if tree.returncode != 0 or not tree.stdout.strip():
        errors.append("initial release root must contain the public source tree")
    return errors


def _resolve_commit(ref: str) -> str | None:
    result = _run_git("rev-parse", "--verify", f"{ref}^{{commit}}")
    if result.returncode != 0:
        return None
    commit = result.stdout.decode(errors="replace").strip()
    return commit or None


def _check_initial_release(expected_tag: str) -> list[str]:
    """Apply the one-time, stricter provenance gate for a new public root."""

    if SEMVER_TAG.fullmatch(expected_tag) is None:
        return ["expected initial release tag must be a semantic version"]

    errors: list[str] = []
    commits = list(dict.fromkeys(_git_lines("rev-list", "--all")))
    target = commits[0] if len(commits) == 1 else None
    if target is None:
        errors.append("initial release refs must contain exactly one commit")

    local_heads = _git_lines("for-each-ref", "--format=%(refname)", "refs/heads")
    remote_heads = _git_lines("for-each-ref", "--format=%(refname)", "refs/remotes")
    tags = _git_lines("for-each-ref", "--format=%(refname)", "refs/tags")
    all_refs = _git_lines("for-each-ref", "--format=%(refname)")

    if len(local_heads) > 1:
        errors.append("initial release may have at most one local head")

    heads = local_heads + remote_heads
    if target is not None and any(_resolve_commit(ref) != target for ref in heads):
        errors.append("initial release heads must point to the sole commit")

    expected_tag_ref = f"refs/tags/{expected_tag}"
    if tags and tags != [expected_tag_ref]:
        errors.append("initial release has an unexpected tag")
    elif tags and target is not None and _resolve_commit(expected_tag_ref) != target:
        errors.append("initial release tag must point to the sole commit")

    allowed_refs = set(heads) | set(tags)
    if any(ref not in allowed_refs for ref in all_refs):
        errors.append("initial release has an unexpected ref")

    if target is not None:
        parent_line = _git_lines("rev-list", "--parents", "-n", "1", target)
        if len(parent_line) != 1 or len(parent_line[0].split()) != 1:
            errors.append("initial release commit must not have a parent")
    return errors


def check_history(
    private_patterns: list[re.Pattern[str]],
    *,
    initial_release_tag: str | None = None,
    expected_origin: str | None = None,
) -> list[str]:
    errors: list[str] = []
    shallow = _run_git("rev-parse", "--is-shallow-repository")
    if shallow.returncode == 0 and shallow.stdout.strip() == b"true":
        errors.append("history validation requires a complete, non-shallow clone")

    rewrite_refs = _git_lines(
        "for-each-ref",
        "--format=%(refname)",
        "refs/original",
        "refs/replace",
    )
    if rewrite_refs:
        errors.append("history rewrite refs are not allowed in the public repository")

    roots = _git_lines("rev-list", "--all", "--max-parents=0")
    if not roots:
        if _git_ref_exists("HEAD"):
            errors.append("public history has no initial release root")
    elif len(set(roots)) != 1:
        errors.append("public refs must share exactly one history root")
    else:
        root = roots[0]
        errors.extend(_check_root_metadata(root))
        if not _git_ref_exists("HEAD"):
            errors.append("repository has commits but HEAD is unborn")

    refs = _git_lines("for-each-ref", "--format=%(refname)")
    if any(_matches_private_policy(private_patterns, ref) for ref in refs):
        errors.append("private policy match in repository metadata")
    history_metadata = _run_git(
        "log",
        "--all",
        "--format=%B%n%an%n%ae%n%cn%n%ce",
    )
    if history_metadata.returncode == 0 and _matches_private_policy(
        private_patterns,
        history_metadata.stdout.decode(errors="replace"),
    ):
        errors.append("private policy match in repository metadata")

    errors.extend(_check_release_tags(private_patterns))
    errors.extend(_check_remote_metadata(private_patterns, expected_origin))
    if initial_release_tag is not None:
        errors.extend(_check_initial_release(initial_release_tag))
    return errors


def _display_path(path: Path) -> str:
    try:
        return path.absolute().relative_to(REPO_ROOT.absolute()).as_posix()
    except ValueError:
        return path.as_posix()


def check_artifacts(
    scan_dirs: list[Path],
    private_patterns: list[re.Pattern[str]],
) -> list[str]:
    errors: list[str] = []
    try:
        approved_binary_digests = set(_approved_binaries().values())
    except (OSError, ValueError):
        return ["binary asset manifest is missing or invalid"]
    for directory in scan_dirs:
        absolute_dir = directory if directory.is_absolute() else REPO_ROOT / directory
        if absolute_dir.is_symlink():
            display = _display_path(absolute_dir)
            errors.append(f"symbolic links are not allowed in artifacts: {display}")
            continue
        if not absolute_dir.exists():
            errors.append(f"artifact directory does not exist: {directory}")
            continue
        if not absolute_dir.is_dir():
            errors.append(f"artifact scan target is not a directory: {directory}")
            continue
        for path in sorted(absolute_dir.rglob("*")):
            display = _display_path(path)
            if _matches_private_policy(private_patterns, display):
                errors.append(f"private policy match in artifact path: {display}")
            if path.is_symlink():
                errors.append(f"symbolic links are not allowed in artifacts: {display}")
                continue
            if not path.is_file():
                continue
            is_binary = path.suffix.lower() in BINARY_SUFFIXES or _has_binary_content(path)
            if is_binary:
                try:
                    actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError:
                    errors.append(f"cannot read artifact: {display}")
                    continue
                if actual_digest not in approved_binary_digests:
                    errors.append(f"unapproved binary asset in artifact: {display}")
                continue
            text, read_error = _read_text(path)
            if read_error:
                errors.append(f"cannot read artifact: {display}")
                continue
            if text is None:
                continue
            if _matches_private_policy(private_patterns, text):
                errors.append(f"private policy match in artifact text: {display}")
            for label in _dangerous_default_labels(text, deployment_config=True):
                errors.append(f"artifact contains a dangerous default ({label}): {display}")
            for pattern, label in ARTIFACT_ONLY_TEXT_PATTERNS:
                if pattern.search(text):
                    errors.append(f"artifact contains {label}: {display}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--include-untracked", action="store_true")
    mode.add_argument("--scan-dir", action="append", default=[], type=Path)
    parser.add_argument(
        "--deny-pattern-file",
        action="append",
        default=[],
        type=Path,
        help="load case-insensitive private deny regexes from a file outside the repository",
    )
    parser.add_argument(
        "--initial-release-tag",
        metavar="TAG",
        help=(
            "one-time release gate: require exactly one parentless commit, at most one "
            "local head, no unrelated refs, and zero tags or exactly TAG (for example, "
            "--initial-release-tag v0.2.0); do not use for normal post-release CI"
        ),
    )
    parser.add_argument(
        "--expected-origin",
        metavar="OWNER/REPO",
        type=_parse_expected_origin,
        help="require origin fetch and push URLs to target exactly this public GitHub repository",
    )
    args = parser.parse_args()

    if args.scan_dir and args.initial_release_tag is not None:
        parser.error("--initial-release-tag cannot be combined with --scan-dir")
    if args.scan_dir and args.expected_origin is not None:
        parser.error("--expected-origin cannot be combined with --scan-dir")

    private_patterns, errors = _load_private_patterns(args.deny_pattern_file)
    if args.scan_dir:
        errors.extend(check_artifacts(args.scan_dir, private_patterns))
    else:
        try:
            paths = _git_paths(args.include_untracked)
        except RuntimeError as exc:
            errors.append(str(exc))
        else:
            errors.extend(check_tree(paths, private_patterns))
        errors.extend(
            check_history(
                private_patterns,
                initial_release_tag=args.initial_release_tag,
                expected_origin=args.expected_origin,
            )
        )
    if errors:
        for error in dict.fromkeys(errors):
            print(f"PUBLIC BOUNDARY: {error}", file=sys.stderr)
        return 1
    print("Public boundary check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
