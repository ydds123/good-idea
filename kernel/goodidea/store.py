from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .errors import ConflictError, NotFoundError, TransactionError, ValidationError


DIRECTORIES = {
    "session": "sessions",
    "flash": "flashes",
    "insight": "insights",
    "source": "sources",
    "event": "events",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class DataStore:
    """Atomic JSON store for the data layer."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        fault: Callable[[int, Path], None] | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.data_root = self.project_root / "data"
        self.current_root = self.data_root / "current"
        self._fault = fault

    def path_for(self, kind: str, object_id: str) -> Path:
        if kind not in DIRECTORIES:
            raise ValidationError(f"unknown data kind: {kind}")
        if not SAFE_ID.fullmatch(object_id):
            raise ValidationError(f"unsafe object id: {object_id}")
        return self.current_root / DIRECTORIES[kind] / f"{object_id}.json"

    def read(self, kind: str, object_id: str) -> dict[str, Any]:
        path = self.path_for(kind, object_id)
        if not path.is_file():
            raise NotFoundError(f"{kind} not found: {object_id}")
        return self._read(path)

    def maybe_read(self, kind: str, object_id: str) -> dict[str, Any] | None:
        path = self.path_for(kind, object_id)
        return self._read(path) if path.is_file() else None

    def list(self, kind: str) -> list[dict[str, Any]]:
        directory = self.path_for(kind, "placeholder").parent
        if not directory.exists():
            return []
        return [self._read(path) for path in sorted(directory.glob("*.json"))]

    def commit(
        self,
        objects: Iterable[Mapping[str, Any]],
        *,
        action: str,
        timestamp: str,
    ) -> dict[str, Any]:
        facts = [dict(item) for item in objects]
        if not facts:
            raise ValidationError("transaction has no facts")
        transaction_id = f"TX-{uuid.uuid4().hex[:16]}"
        event = {
            "id": transaction_id,
            "kind": "event",
            "action": action,
            "timestamp": timestamp,
            "objects": [
                {"kind": item.get("kind"), "id": item.get("id")} for item in facts
            ],
        }
        facts.append(event)
        writes: dict[Path, bytes] = {}
        for item in facts:
            kind = str(item.get("kind") or "")
            object_id = str(item.get("id") or "")
            target = self.path_for(kind, object_id)
            if target in writes:
                raise ValidationError(f"duplicate transaction target: {kind}/{object_id}")
            writes[target] = self._serialize(item)
        with self._lock():
            self._replace(writes, transaction_id)
        return event

    @staticmethod
    def _serialize(value: Mapping[str, Any]) -> bytes:
        return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"invalid data object: {path}") from exc
        if not isinstance(value, dict):
            raise ValidationError(f"data object must be a JSON object: {path}")
        return value

    @contextmanager
    def _lock(self):
        self.data_root.mkdir(parents=True, exist_ok=True)
        lock = self.data_root / ".write.lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise ConflictError("another write is in progress") from exc
        try:
            os.write(descriptor, str(os.getpid()).encode())
            os.close(descriptor)
            yield
        finally:
            lock.unlink(missing_ok=True)

    def _replace(self, writes: Mapping[Path, bytes], transaction_id: str) -> None:
        workspace = self.data_root / ".transactions" / transaction_id
        staged_root = workspace / "staged"
        backup_root = workspace / "backup"
        staged_root.mkdir(parents=True)
        backup_root.mkdir(parents=True)
        backups: dict[Path, Path | None] = {}
        replaced: list[Path] = []
        try:
            for index, (target, content) in enumerate(writes.items(), start=1):
                relative = target.relative_to(self.current_root)
                staged = staged_root / relative
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(content)
                if target.exists():
                    backup = backup_root / relative
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
                    backups[target] = backup
                else:
                    backups[target] = None
                if self._fault:
                    self._fault(index, target)
            total = len(writes)
            for index, target in enumerate(writes, start=1):
                staged = staged_root / target.relative_to(self.current_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, target)
                replaced.append(target)
                if self._fault:
                    self._fault(total + index, target)
        except Exception as exc:
            for target in reversed(replaced):
                backup = backups[target]
                if backup is None:
                    target.unlink(missing_ok=True)
                else:
                    shutil.copy2(backup, target)
            raise TransactionError(f"transaction rolled back: {transaction_id}") from exc
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
