#!/usr/bin/env python3
"""Validate every project Skill with Codex's official quick validator."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKILLS_ROOT = PROJECT_ROOT / ".agents" / "skills"
VALIDATOR_ENV = "GOODIDEA_SKILL_VALIDATOR"


def validator_candidates() -> list[Path]:
    configured = os.environ.get(VALIDATOR_ENV)
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            Path.home()
            / ".codex/skills/.system/skill-creator/scripts/quick_validate.py",
            Path.home()
            / ".Codex/skills/.system/skill-creator/scripts/quick_validate.py",
        ]
    )
    return candidates


def resolve_validator(explicit: str | None) -> Path:
    candidates = [Path(explicit).expanduser()] if explicit else validator_candidates()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    searched = "\n  - ".join(str(path) for path in candidates)
    raise FileNotFoundError(
        "找不到 skill-creator 官方校验器。已检查：\n"
        f"  - {searched}\n"
        f"可用 --validator 或 {VALIDATOR_ENV} 指定 quick_validate.py。"
    )


def discover_skills(skills_root: Path) -> list[Path]:
    root = skills_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Skill 目录不存在：{root}")
    skills = sorted(path for path in root.iterdir() if (path / "SKILL.md").is_file())
    if not skills:
        raise FileNotFoundError(f"没有发现包含 SKILL.md 的 Skill：{root}")
    return skills


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validator",
        help=f"quick_validate.py 路径；也可使用 {VALIDATOR_ENV}",
    )
    parser.add_argument(
        "--skills-root",
        type=Path,
        default=DEFAULT_SKILLS_ROOT,
        help="项目 Skills 根目录",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import yaml

        validator = resolve_validator(args.validator)
        skills = discover_skills(args.skills_root)
    except (ImportError, FileNotFoundError) as error:
        if isinstance(error, ImportError):
            print("缺少开发依赖 PyYAML；请先运行 `uv sync --group dev`。", file=sys.stderr)
        else:
            print(error, file=sys.stderr)
        return 2

    print(f"PyYAML {yaml.__version__}", flush=True)
    print(f"官方校验器：{validator}", flush=True)
    failures: list[str] = []
    for skill in skills:
        print(f"\n[{skill.name}]", flush=True)
        result = subprocess.run(
            [sys.executable, str(validator), str(skill)],
            cwd=PROJECT_ROOT,
            check=False,
        )
        if result.returncode != 0:
            failures.append(skill.name)

    if failures:
        print(f"\n校验失败：{', '.join(failures)}", file=sys.stderr)
        return 1
    print(f"\n全部通过：{len(skills)}/{len(skills)} Skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
