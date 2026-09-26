#!/usr/bin/env python3
"""Create a dated Markdown record from a repository template."""

from __future__ import annotations

import argparse
import shutil
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DESTINATIONS = {
    "interesting": ROOT / "数据/记录/有意思",
    "action": ROOT / "数据/记录/行动",
    "flash": ROOT / "数据/记录/闪念",
    "permanent": ROOT / "数据/记录/永久卡片",
    "source": ROOT / "数据/记录/外部来源",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("type", choices=sorted(DESTINATIONS))
    parser.add_argument("title")
    return parser.parse_args()


def safe_title(title: str) -> str:
    cleaned = " ".join(title.split())
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise ValueError("标题不能为空，且不能包含路径分隔符")
    return cleaned


def next_path(directory: Path, stem: str) -> Path:
    candidate = directory / f"{stem}.md"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{index}.md"
        index += 1
    return candidate


def main() -> int:
    args = parse_args()
    title = safe_title(args.title)
    template = ROOT / "数据/模板" / f"{args.type}.md"
    directory = DESTINATIONS[args.type]
    if not template.is_file():
        raise SystemExit(f"模板不存在：{template}")
    directory.mkdir(parents=True, exist_ok=True)
    target = next_path(directory, f"{date.today().isoformat()}-{title}")
    shutil.copyfile(template, target)
    print(target.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        raise SystemExit(f"错误：{error}")
