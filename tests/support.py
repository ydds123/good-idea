from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from goodidea.notes import TYPE_LOCATIONS
from goodidea.repository import INDEX_PATH, LOG_PATH, STATE_PATH, Repository


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def initialize_test_vault(root: Path) -> None:
    """Build a test vault from the checked-in product configuration."""
    root.mkdir(parents=True)
    for location in TYPE_LOCATIONS.values():
        (root / location).mkdir(parents=True, exist_ok=True)
    for relative in (
        "assets",
        ".goodidea/proposals/source-updates",
        ".goodidea/proposals/permanent",
        ".goodidea/proposals/connections",
        ".goodidea/transactions",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": "0.1",
        "transactions": {},
        "connections": [],
    }
    (root / STATE_PATH).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for relative in ("AGENTS.md", "schema.md", ".gitignore"):
        shutil.copy2(PROJECT_ROOT / relative, root / relative)
    shutil.copytree(
        PROJECT_ROOT / ".obsidian",
        root / ".obsidian",
        ignore=shutil.ignore_patterns(".DS_Store"),
    )
    (root / LOG_PATH).write_text(
        "# Good idea 操作日志\n\n> 只允许 CLI 追加。\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Good idea"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "goodidea@local"], cwd=root, check=True)
    subprocess.run(["git", "config", "core.quotepath", "false"], cwd=root, check=True)
    repo = Repository(root)
    (root / INDEX_PATH).write_text(repo.generate_index({}), encoding="utf-8")
    subprocess.run(["git", "add", "--all"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-m", "test: initialize fixture"],
        cwd=root,
        check=True,
        capture_output=True,
    )
