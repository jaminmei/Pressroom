#!/usr/bin/env python3
"""Migrate saved workflow JSON files from engine/vlm to engine/model.

Usage:
    python scripts/migrate_vlm_to_model.py --dir ./workflows --dry-run
    python scripts/migrate_vlm_to_model.py --dir ./workflows
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path so we can import app modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.workflow_migrator import migrate_workflow


def main():
    parser = argparse.ArgumentParser(
        description="Migrate engine/vlm to engine/model in workflow JSON files"
    )
    parser.add_argument("--dir", required=True, help="Directory containing workflow JSON files")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    args = parser.parse_args()

    workflow_dir = Path(args.dir)
    if not workflow_dir.is_dir():
        print(f"Error: {workflow_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    json_files = list(workflow_dir.glob("*.json"))
    if not json_files:
        print(f"No JSON files found in {workflow_dir}")
        return

    migrated_count = 0
    for json_file in json_files:
        with open(json_file) as f:
            workflow = json.load(f)

        result = migrate_workflow(workflow)
        if result is not workflow:  # Migration happened
            migrated_count += 1
            if args.dry_run:
                print(f"[DRY RUN] Would migrate: {json_file}")
                # Show which nodes changed
                for node in workflow.get("nodes", []):
                    if node.get("type") == "engine/vlm":
                        print(f"  - Node {node.get('id')}: engine/vlm -> engine/model")
            else:
                with open(json_file, "w") as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                print(f"Migrated: {json_file}")

    print(f"\nTotal: {len(json_files)} files scanned, {migrated_count} migrated")


if __name__ == "__main__":
    main()
