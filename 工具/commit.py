#!/usr/bin/env python3
"""Commit one explicitly named record without staging unrelated changes."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", type=Path)
    args = parser.parse_args()
    record = (ROOT / args.record).resolve()
    if not record.is_file() or ROOT not in record.parents:
        print("记录路径无效", flush=True)
        return 2
    relative = record.relative_to(ROOT)
    subprocess.run(["git", "add", "--", str(relative)], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", f"capture: {record.stem}"], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
