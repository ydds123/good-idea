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

from .contracts import (
    FORMATION_WITNESS_ROOT,
    TODO_STATUS_DIRS,
    TRANSACTION_ID_PATTERN,
)
from .errors import GitError, IntegrityError, TransactionError, ValidationError
from .metadata import parse_document
from .notes import (
    INDEX_HEADINGS,
    STATUS_LABELS,
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
        if not TRANSACTION_ID_PATTERN.fullmatch(transaction_id):
            raise ValidationError(
                "transaction-id 只能包含字母、数字、点、下划线和连字符，且最长 128 字符"
            )
        record = self.read_state().get("transactions", {}).get(transaction_id)
        if not record:
            return None
        return {"idempotent": True, **record}

    def preflight_integrity(self, *, validate_sources: bool = True) -> None:
        for location in TYPE_LOCATIONS.values():
            directory = self.root / location
            if directory.is_symlink():
                raise IntegrityError(f"内容目录不得为符号链接：{location}")
        for status_dir in TODO_STATUS_DIRS.values():
            directory = self.root / status_dir
            if directory.is_symlink():
                raise IntegrityError(f"内容目录不得为符号链接：{status_dir}")
        if not validate_sources:
            return
        source_dir = self.root / TYPE_LOCATIONS["source"]
        for path in sorted(source_dir.glob("*.md")):
            if path.is_symlink():
                raise IntegrityError(f"来源文件不得为符号链接：{path.name}")
            validate_source_note(
                path.read_text(encoding="utf-8"), path.relative_to(self.root).as_posix()
            )
        witness_dir = self.root / FORMATION_WITNESS_ROOT
        if witness_dir.is_symlink():
            raise IntegrityError("形成来源见证目录不得为符号链接")
        for path in sorted(witness_dir.glob("*.md")):
            if path.is_symlink():
                raise IntegrityError(f"形成来源见证不得为符号链接：{path.name}")

    def find_note(
        self, note_id: str
    ) -> tuple[Path, str, dict[str, Any]] | None:
        for location in (*TYPE_LOCATIONS.values(), *TODO_STATUS_DIRS.values(), FORMATION_WITNESS_ROOT):
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
        self,
        writes: dict[Path, str | bytes],
        deletes: set[Path] | None = None,
    ) -> dict[Path, str]:
        deleted = deletes or set()
        notes: dict[Path, str] = {}
        for location in (*TYPE_LOCATIONS.values(), *TODO_STATUS_DIRS.values()):
            for path in sorted((self.root / location).glob("*.md")):
                rel = path.relative_to(self.root)
                if rel not in deleted:
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

    def generate_index(
        self,
        writes: dict[Path, str | bytes],
        deletes: set[Path] | None = None,
    ) -> str:
        groups: dict[str, list[tuple[Path, dict[str, Any]]]] = {
            kind: [] for kind in INDEX_HEADINGS
        }
        for rel, text in self._pending_note_texts(writes, deletes).items():
            try:
                metadata, _body = parse_document(text)
            except ValidationError:
                continue
            note_type = str(metadata.get("type", ""))
            if note_type not in groups:
                continue
            groups[note_type].append((rel, metadata))

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
            for rel, metadata in items:
                link = wiki_link(rel, str(metadata.get("title", rel.stem)))
                raw_status = str(metadata.get("status", ""))
                status = STATUS_LABELS.get(raw_status, raw_status)
                lines.append(f"- {link} · {status}")
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
        deletes: set[Path] | None = None,
        validate_sources: bool = True,
        accept_dirty: bool = False,
    ) -> dict[str, Any]:
        existing = self.transaction_result(transaction_id)
        if existing:
            return existing
        self.preflight_integrity(validate_sources=validate_sources)
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
        final_deletes = set(deletes or set())
        if final_deletes.intersection(writes):
            overlap = sorted(path.as_posix() for path in final_deletes.intersection(writes))
            raise TransactionError("事务不能同时写入和删除同一路径：" + ", ".join(overlap))
        final_writes = dict(writes)
        final_writes[STATE_PATH] = (
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        log_text = (self.root / LOG_PATH).read_text(encoding="utf-8")
        if not log_text.endswith("\n"):
            log_text += "\n"
        final_writes[LOG_PATH] = (
            log_text
            + f"[{timestamp}] {action} | {summary} | tx={transaction_id}\n\n"
        )
        final_writes[INDEX_PATH] = self.generate_index(final_writes, final_deletes)
        target_paths = sorted(
            set(final_writes).union(final_deletes),
            key=lambda path: path.as_posix(),
        )
        dirty_targets = _run_git(
            self.root,
            ["status", "--porcelain", "--", *[path.as_posix() for path in target_paths]],
            check=True,
        ).stdout.strip()
        if dirty_targets and not accept_dirty:
            raise GitError(
                "事务目标已有未提交变更，拒绝覆盖或混入自动提交："
                + dirty_targets.replace("\n", "; ")
            )
        self._atomic_apply(
            final_writes,
            final_deletes,
            transaction_id,
            f"{action}: {summary} [tx:{transaction_id}]",
        )
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
        deletes: set[Path],
        transaction_id: str,
        commit_message: str,
    ) -> None:
        if not TRANSACTION_ID_PATTERN.fullmatch(transaction_id):
            raise TransactionError("事务编号格式非法")
        transactions_root = self.root / ".goodidea/transactions"
        resolved_transactions = transactions_root.resolve(strict=False)
        if (
            (self.root / ".goodidea").is_symlink()
            or transactions_root.is_symlink()
            or not resolved_transactions.is_relative_to(self.root)
        ):
            raise TransactionError("事务备份目录不得通过符号链接越出仓库")
        tx_root = Path(
            tempfile.mkdtemp(prefix=f"{transaction_id}-", dir=transactions_root)
        )
        backup_root = tx_root / "backup"
        backup_root.mkdir(parents=True, exist_ok=True)
        originals: dict[Path, bytes | None] = {}
        affected = set(writes).union(deletes)
        relpaths = sorted(affected, key=lambda path: path.as_posix())
        try:
            for rel in relpaths:
                if rel.is_absolute() or ".." in rel.parts:
                    raise TransactionError(f"事务路径非法：{rel}")
                target = self.root / rel
                parent = target.parent
                resolved_parent = parent.resolve(strict=False)
                if resolved_parent != self.root and not resolved_parent.is_relative_to(self.root):
                    raise TransactionError(f"事务路径越界：{rel}")
                parent.mkdir(parents=True, exist_ok=True)
                if target.is_symlink():
                    raise TransactionError(f"拒绝修改符号链接：{rel}")
                originals[rel] = target.read_bytes() if target.exists() else None
                if target.exists():
                    backup = backup_root / rel
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
            for rel in sorted(writes, key=lambda path: path.as_posix()):
                target = self.root / rel
                parent = target.parent
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
            for rel in sorted(deletes, key=lambda path: path.as_posix()):
                target = self.root / rel
                if not target.is_file():
                    raise TransactionError(f"事务删除目标不是普通文件：{rel}")
                target.unlink()
            path_args = [path.as_posix() for path in relpaths]
            _run_git(self.root, ["add", "--all", "--", *path_args])
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
            for rel in reversed(list(originals)):
                target = self.root / rel
                original = originals[rel]
                if original is None:
                    if target.exists() and not target.is_dir():
                        target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(original)
            raise
