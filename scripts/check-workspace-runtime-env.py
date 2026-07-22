#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# ─── How to run ───
# uv run scripts/check-workspace-runtime-env.py --expect-enforced true

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import check_workspace_runtime_env  # noqa: E402


def parse_bool(value: str) -> bool:
    normalized = value.lower()
    if normalized not in {"true", "false"}:
        raise argparse.ArgumentTypeError("expected true or false")
    return normalized == "true"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--peer-role",
        choices=("backend", "worker"),
        help="Deprecated compatibility option; live peer equality uses runtime attestation.",
    )
    parser.add_argument("--expect-enforced", type=parse_bool, default=True)
    args = parser.parse_args()
    report = check_workspace_runtime_env(expect_enforced=args.expect_enforced)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
