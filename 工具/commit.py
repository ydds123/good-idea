#!/usr/bin/env python3
"""Commit one explicitly named record without staging unrelated changes."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def staged_paths() -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {line for line in result.stdout.splitlines() if line}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", type=Path)
    args = parser.parse_args()
    record = (ROOT / args.record).resolve()
    if not record.is_file() or ROOT not in record.parents:
        print("记录路径无效", flush=True)
        return 2
    relative = record.relative_to(ROOT)
    existing = staged_paths()
    if existing and existing != {str(relative)}:
        print("存在其他已暂存改动，拒绝提交以免误提交", flush=True)
        return 3
    subprocess.run(["git", "add", "--", str(relative)], cwd=ROOT, check=True)
    if staged_paths() != {str(relative)}:
        print("暂存区包含非目标记录，拒绝提交", flush=True)
        return 4
    subprocess.run(["git", "commit", "-m", f"capture: {record.stem}"], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
