#!/usr/bin/env python3
"""Commit one or more explicitly named records; no product decisions."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=ROOT, text=True, capture_output=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("paths", nargs="+")
    p.add_argument("--message", default="capture: 保存捕捉记录")
    args = p.parse_args()
    paths = []
    for value in args.paths:
        path = Path(value)
        if path.is_absolute():
            try:
                path = path.relative_to(ROOT)
            except ValueError:
                print(f"路径不在仓库内：{value}", file=sys.stderr)
                return 2
        if not (ROOT / path).exists():
            print(f"文件不存在：{value}", file=sys.stderr)
            return 2
        paths.append(str(path))
    staged = run("diff", "--cached", "--name-only")
    if staged.stdout.strip():
        print("存在其他已暂存改动，拒绝提交", file=sys.stderr)
        return 4
    added = run("add", "--", *paths)
    if added.returncode:
        print(added.stderr, file=sys.stderr)
        return 3
    check = run("diff", "--cached", "--name-only")
    expected = set(paths)
    actual = {line for line in check.stdout.splitlines() if line}
    if actual != expected:
        run("reset", "--", *paths)
        print("暂存文件与指定路径不一致，已撤销暂存", file=sys.stderr)
        return 4
    committed = run("commit", "-m", args.message)
    if committed.returncode:
        run("reset", "--", *paths)
        print(committed.stderr, file=sys.stderr)
        return 5
    print(committed.stdout, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
