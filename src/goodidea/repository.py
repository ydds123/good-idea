from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import GitError, IntegrityError, TransactionError, ValidationError
from .metadata import parse_document
from .notes import (
    INDEX_HEADINGS,
    TYPE_LOCATIONS,
    validate_source_note,
    wiki_link,
)


STATE_PATH = Path(".goodidea/state.json")
INDEX_PATH = Path("index.md")
LOG_PATH = Path("log.md")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _run_git(
    root: Path, args: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip()
        raise GitError(f"git {' '.join(args)} 失败：{message}")
    return process


class Repository:
    def __init__(self, root: Path):
        self.root = root.resolve()
        if not (self.root / STATE_PATH).is_file():
            raise ValidationError(f"{self.root} 不是已初始化的 Good idea 仓库")
        if not (self.root / ".git").is_dir():
            raise ValidationError(f"{self.root} 缺少独立 Git 仓库")

    @classmethod
    def discover(cls, root: str | Path | None = None) -> "Repository":
        if root:
            return cls(Path(root))
        current = Path.cwd().resolve()
        for candidate in (current, *current.parents):
            if (candidate / STATE_PATH).is_file():
                return cls(candidate)
        raise ValidationError("当前目录不在 Good idea 仓库中；请传入 --root")

    def read_state(self) -> dict[str, Any]:
        try:
            return json.loads((self.root / STATE_PATH).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntegrityError("无法读取 .goodidea/state.json") from exc

    def transaction_result(self, transaction_id: str) -> dict[str, Any] | None:
        record = self.read_state().get("transactions", {}).get(transaction_id)
        if not record:
            return None
        return {"idempotent": True, **record}

    def preflight_integrity(self) -> None:
        for location in TYPE_LOCATIONS.values():
            directory = self.root / location
            if directory.is_symlink():
                raise IntegrityError(f"内容目录不得为符号链接：{location}")
        source_dir = self.root / TYPE_LOCATIONS["source"]
        for path in sorted(source_dir.glob("*.md")):
            if path.is_symlink():
                raise IntegrityError(f"来源文件不得为符号链接：{path.name}")
            validate_source_note(
                path.read_text(encoding="utf-8"), path.relative_to(self.root).as_posix()
            )

    def find_note(
        self, note_id: str
    ) -> tuple[Path, str, dict[str, Any]] | None:
        for location in TYPE_LOCATIONS.values():
            for path in sorted((self.root / location).glob("*.md")):
                try:
                    text = path.read_text(encoding="utf-8")
                    metadata, _ = parse_document(text)
                except (OSError, ValidationError):
                    continue
                if metadata.get("id") == note_id:
                    return path.relative_to(self.root), text, metadata
        return None

    def _pending_note_texts(
        self, writes: dict[Path, str | bytes]
    ) -> dict[Path, str]:
        notes: dict[Path, str] = {}
        for location in TYPE_LOCATIONS.values():
            for path in sorted((self.root / location).glob("*.md")):
                rel = path.relative_to(self.root)
                notes[rel] = path.read_text(encoding="utf-8")
        for rel, content in writes.items():
            if rel.suffix == ".md" and any(
                rel == location or location in rel.parents
                for location in TYPE_LOCATIONS.values()
            ):
                if isinstance(content, bytes):
                    continue
                notes[rel] = content
        return notes

    def generate_index(self, writes: dict[Path, str | bytes]) -> str:
        groups: dict[str, list[tuple[Path, dict[str, Any], str]]] = {
            kind: [] for kind in INDEX_HEADINGS
        }
        for rel, text in self._pending_note_texts(writes).items():
            try:
                metadata, body = parse_document(text)
            except ValidationError:
                continue
            note_type = str(metadata.get("type", ""))
            if note_type not in groups:
                continue
            summary = str(metadata.get("summary", "")).strip()
            if not summary:
                for line in body.splitlines():
                    candidate = line.strip()
                    if (
                        candidate
                        and not candidate.startswith(("#", ">", "<!--", "- [["))
                    ):
                        summary = candidate[:100]
                        break
            groups[note_type].append((rel, metadata, summary))

        lines = [
            "# Good idea 索引",
            "",
            "> 由 goodidea CLI 自动生成，请勿手工改写。",
            "",
        ]
        for note_type, heading in INDEX_HEADINGS.items():
            lines.extend([f"## {heading}", ""])
            items = sorted(
                groups[note_type],
                key=lambda item: (
                    str(item[1].get("updated_at", "")),
                    str(item[1].get("id", "")),
                ),
                reverse=True,
            )
            if not items:
                lines.extend(["_暂无_", ""])
                continue
            for rel, metadata, summary in items:
                link = wiki_link(rel, str(metadata.get("title", rel.stem)))
                status = metadata.get("status", "")
                suffix = f" — {summary}" if summary else ""
                lines.append(
                    f"- {link} · {metadata.get('id', '')} · {status}{suffix}"
                )
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def commit(
        self,
        *,
        transaction_id: str,
        action: str,
        summary: str,
        writes: dict[Path, str | bytes],
        state: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self.transaction_result(transaction_id)
        if existing:
            return existing
        self.preflight_integrity()
        staged_before = _run_git(
            self.root, ["diff", "--cached", "--name-only"], check=True
        ).stdout.strip()
        if staged_before:
            raise GitError(
                "检测到调用前已经暂存的文件，拒绝把用户变更混入自动事务："
                + staged_before.replace("\n", ", ")
            )
        timestamp = now_iso()
        state = copy.deepcopy(state)
        state.setdefault("transactions", {})[transaction_id] = {
            "transaction_id": transaction_id,
            "action": action,
            "summary": summary,
            "timestamp": timestamp,
            "result": result,
        }
        final_writes = dict(writes)
        final_writes[STATE_PATH] = (
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        log_text = (self.root / LOG_PATH).read_text(encoding="utf-8")
        if not log_text.endswith("\n"):
            log_text += "\n"
        final_writes[LOG_PATH] = (
            log_text
            + f"## [{timestamp}] {action} | {summary} | tx={transaction_id}\n\n"
        )
        final_writes[INDEX_PATH] = self.generate_index(final_writes)
        self._atomic_apply(final_writes, transaction_id, f"{action}: {summary}")
        commit_hash = _run_git(self.root, ["rev-parse", "HEAD"]).stdout.strip()
        return {
            "idempotent": False,
            "transaction_id": transaction_id,
            "action": action,
            "summary": summary,
            "timestamp": timestamp,
            "commit": commit_hash,
            "result": result,
        }

    def _atomic_apply(
        self,
        writes: dict[Path, str | bytes],
        transaction_id: str,
        commit_message: str,
    ) -> None:
        tx_root = self.root / ".goodidea/transactions" / transaction_id
        backup_root = tx_root / "backup"
        backup_root.mkdir(parents=True, exist_ok=True)
        originals: dict[Path, bytes | None] = {}
        written: list[Path] = []
        relpaths = sorted(writes, key=lambda path: path.as_posix())
        try:
            for rel in relpaths:
                if rel.is_absolute() or ".." in rel.parts:
                    raise TransactionError(f"事务路径非法：{rel}")
                target = self.root / rel
                parent = target.parent
                parent.mkdir(parents=True, exist_ok=True)
                if parent.resolve() != self.root and not parent.resolve().is_relative_to(
                    self.root
                ):
                    raise TransactionError(f"事务路径越界：{rel}")
                if target.is_symlink():
                    raise TransactionError(f"拒绝覆盖符号链接：{rel}")
                originals[rel] = target.read_bytes() if target.exists() else None
                if target.exists():
                    backup = backup_root / rel
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
                content = writes[rel]
                data = content if isinstance(content, bytes) else content.encode("utf-8")
                descriptor, temp_name = tempfile.mkstemp(
                    prefix=".goodidea-", dir=parent
                )
                try:
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp_name, target)
                finally:
                    if os.path.exists(temp_name):
                        os.unlink(temp_name)
                written.append(rel)
            path_args = [path.as_posix() for path in relpaths]
            _run_git(self.root, ["add", "--", *path_args])
            diff = _run_git(
                self.root, ["diff", "--cached", "--name-only"], check=True
            ).stdout.strip()
            if not diff:
                raise TransactionError("事务没有产生可提交的变化")
            _run_git(self.root, ["commit", "-m", commit_message])
        except Exception:
            _run_git(
                self.root,
                ["restore", "--staged", "--", *[p.as_posix() for p in relpaths]],
                check=False,
            )
            for rel in reversed(written):
                target = self.root / rel
                original = originals[rel]
                if original is None:
                    if target.exists() and not target.is_dir():
                        target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(original)
            raise


def initialize_vault(path: Path) -> dict[str, Any]:
    root = path.resolve()
    state_path = root / STATE_PATH
    if state_path.exists():
        repo = Repository(root)
        return {
            "initialized": False,
            "root": str(repo.root),
            "reason": "already_initialized",
        }
    root.mkdir(parents=True, exist_ok=True)
    for location in TYPE_LOCATIONS.values():
        (root / location).mkdir(parents=True, exist_ok=True)
    for relative in (
        ".goodidea/assets",
        ".goodidea/proposals/source-updates",
        ".goodidea/proposals/permanent",
        ".goodidea/proposals/connections",
        ".goodidea/transactions",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": "0.1",
        "transactions": {},
        "sources": {},
        "proposals": {},
        "connections": [],
    }
    starter_files = {
        STATE_PATH: json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        INDEX_PATH: (
            "# Good idea 索引\n\n"
            "> 由 goodidea CLI 自动生成，请勿手工改写。\n\n"
            "## 闪念\n\n_暂无_\n\n"
            "## 溯源\n\n_暂无_\n\n"
            "## 有意思\n\n_暂无_\n\n"
            "## 待办\n\n_暂无_\n\n"
            "## 永久卡片\n\n_暂无_\n\n"
            "## 母题卡片\n\n_暂无_\n\n"
            "## 行动卡片\n\n_暂无_\n\n"
            "## 索引卡片\n\n_暂无_\n"
        ),
        LOG_PATH: "# Good idea 操作日志\n\n> 只允许 CLI 追加。\n",
        Path("AGENTS.md"): (
            "# Good idea\n\n用户负责判断；Agent 负责对话；CLI 负责确定性写入。"
            "\n读取 schema.md 后再操作。\n"
        ),
        Path("schema.md"): (
            "# Good idea v0.1 Schema\n\n本仓库使用五个内容空间和受哈希保护的"
            "来源快照。完整规范由安装此 CLI 的项目版本提供。\n"
        ),
        Path(".gitignore"): (
            ".venv/\n__pycache__/\n*.py[cod]\n.goodidea/transactions/*\n"
        ),
    }
    for rel, content in starter_files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _run_git(root, ["init", "-b", "main"])
    _run_git(root, ["config", "user.name", "Good idea"])
    _run_git(root, ["config", "user.email", "goodidea@local"])
    _run_git(root, ["config", "core.quotepath", "false"])
    _run_git(root, ["add", "--", *[path.as_posix() for path in starter_files]])
    _run_git(root, ["commit", "-m", "chore: initialize Good idea vault"])
    return {"initialized": True, "root": str(root)}
