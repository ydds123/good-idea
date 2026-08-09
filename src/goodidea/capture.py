from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .errors import IntegrityError, ValidationError
from .repository import now_iso


SESSION_RE = re.compile(r"^CAP-[0-9]{8}-[0-9a-f]{8}$")
TX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ACTIVE_STATES = {"active", "reviewing", "paused"}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


class CaptureRuntime:
    """Crash-safe, Git-ignored capture sessions for the cognition foreground."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.runtime = self.root / ".goodidea/runtime"
        self.captures = self.runtime / "captures"
        self.completed = self.runtime / "completed-captures"
        self.maintenance = self.runtime / "maintenance"
        self.transactions = self.runtime / "transactions"
        for directory in (
            self.runtime,
            self.captures,
            self.completed,
            self.maintenance,
            self.transactions,
        ):
            resolved = directory.resolve(strict=False)
            if directory.is_symlink() or not resolved.is_relative_to(self.root):
                raise IntegrityError(f"运行时目录越界或为符号链接：{directory}")
            directory.mkdir(parents=True, exist_ok=True)

    def _transaction_path(self, transaction_id: str) -> Path:
        if not TX_RE.fullmatch(transaction_id):
            raise ValidationError("无效的捕获事务 ID")
        digest = hashlib.sha256(transaction_id.encode("utf-8")).hexdigest()
        return self.transactions / f"{digest}.json"

    def _global_result(self, transaction_id: str) -> dict[str, Any] | None:
        path = self._transaction_path(transaction_id)
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntegrityError("捕获事务记录损坏") from exc
        if record.get("transaction_id") != transaction_id or not isinstance(
            record.get("result"), dict
        ):
            raise IntegrityError("捕获事务记录不一致")
        return dict(record["result"])

    def _record_global(self, transaction_id: str, result: dict[str, Any]) -> None:
        path = self._transaction_path(transaction_id)
        existing = self._global_result(transaction_id)
        if existing is not None:
            if existing != result:
                raise IntegrityError("同一捕获事务 ID 对应了不同结果")
            return
        _atomic_json(path, {"transaction_id": transaction_id, "result": result})

    def _validate_session_id(self, session_id: str) -> None:
        if not SESSION_RE.fullmatch(session_id):
            raise ValidationError("无效的捕获会话 ID")

    def _session_dir(self, session_id: str, *, completed: bool = False) -> Path:
        self._validate_session_id(session_id)
        base = self.completed if completed else self.captures
        path = base / session_id
        if path.is_symlink() or not path.resolve(strict=False).is_relative_to(base):
            raise IntegrityError("捕获会话路径越界或为符号链接")
        return path

    def _find_session_dir(self, session_id: str) -> Path:
        active = self._session_dir(session_id)
        if active.is_dir():
            return active
        completed = self._session_dir(session_id, completed=True)
        if completed.is_dir():
            return completed
        raise ValidationError(f"找不到捕获会话：{session_id}")

    @contextlib.contextmanager
    def _locked(self, directory: Path) -> Iterator[None]:
        directory.mkdir(parents=True, exist_ok=True)
        lock_path = directory / ".lock"
        if lock_path.is_symlink():
            raise IntegrityError("捕获会话锁不得为符号链接")
        with lock_path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _read(self, directory: Path) -> dict[str, Any]:
        try:
            value = json.loads((directory / "session.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntegrityError("捕获会话状态损坏") from exc
        if not isinstance(value, dict):
            raise IntegrityError("捕获会话状态必须是对象")
        return value

    def _write(self, directory: Path, state: dict[str, Any]) -> None:
        _atomic_json(directory / "session.json", state)
        transcript = "".join(
            _canonical_json(entry) + "\n" for entry in state.get("entries", [])
        )
        transcript_path = directory / "transcript.jsonl"
        handle, temporary = tempfile.mkstemp(prefix=".transcript.", dir=directory)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(transcript)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, transcript_path)
        except Exception:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)
            raise
        _atomic_json(directory / "context.json", state.get("contexts", []))
        proposal = state.get("proposal")
        proposal_path = directory / "proposal.json"
        if proposal:
            _atomic_json(proposal_path, proposal)
        elif proposal_path.exists():
            proposal_path.unlink()

    def _transaction(
        self, state: dict[str, Any], transaction_id: str, result: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not TX_RE.fullmatch(transaction_id):
            raise ValidationError("无效的捕获事务 ID")
        transactions = state.setdefault("transactions", {})
        existing = transactions.get(transaction_id)
        if existing is not None:
            return {"idempotent": True, **existing}
        transactions[transaction_id] = result
        return None

    def start(
        self,
        *,
        text: str,
        context_refs: list[str],
        transaction_id: str,
    ) -> dict[str, Any]:
        if not text.strip():
            raise ValidationError("捕获内容不能为空")
        if existing := self._global_result(transaction_id):
            return {"idempotent": True, **existing}
        suffix = hashlib.sha256(transaction_id.encode("utf-8")).hexdigest()[:8]
        session_id = f"CAP-{datetime.now().astimezone():%Y%m%d}-{suffix}"
        directory = self._session_dir(session_id)
        with self._locked(directory):
            if (directory / "session.json").exists():
                state = self._read(directory)
                if transaction_id in state.get("transactions", {}):
                    result = dict(state["transactions"][transaction_id])
                    self._record_global(transaction_id, result)
                    return {"idempotent": True, **result}
                raise IntegrityError("确定性捕获会话 ID 发生冲突")
            timestamp = now_iso()
            entry_id = f"ENT-{secrets.token_hex(6)}"
            refs = list(dict.fromkeys(ref.strip() for ref in context_refs if ref.strip()))
            state = {
                "session_id": session_id,
                "status": "active",
                "created_at": timestamp,
                "updated_at": timestamp,
                "entries": [
                    {"entry_id": entry_id, "role": "user", "text": text, "recorded_at": timestamp}
                ],
                "contexts": [{"ref": ref, "status": "unchecked"} for ref in refs],
                "proposal": None,
                "transactions": {},
            }
            result = {"session_id": session_id, "status": "active", "entry_id": entry_id}
            self._transaction(state, transaction_id, result)
            self._write(directory, state)
            self._record_global(transaction_id, result)
            self.pause_processing_jobs()
            return {"idempotent": False, **result}

    def append(
        self,
        session_id: str,
        *,
        text: str,
        context_refs: list[str],
        transaction_id: str,
    ) -> dict[str, Any]:
        if not text.strip():
            raise ValidationError("追加内容不能为空")
        if existing := self._global_result(transaction_id):
            return {"idempotent": True, **existing}
        directory = self._find_session_dir(session_id)
        with self._locked(directory):
            state = self._read(directory)
            if state.get("status") not in {"active", "reviewing"}:
                raise ValidationError("只能向 active 或 reviewing 会话追加内容")
            provisional = {"session_id": session_id}
            if existing := self._transaction(state, transaction_id, provisional):
                existing.pop("idempotent", None)
                self._record_global(transaction_id, existing)
                existing["idempotent"] = True
                return existing
            timestamp = now_iso()
            entry_id = f"ENT-{secrets.token_hex(6)}"
            state["entries"].append(
                {"entry_id": entry_id, "role": "user", "text": text, "recorded_at": timestamp}
            )
            known = {item["ref"] for item in state.get("contexts", [])}
            for raw in context_refs:
                ref = raw.strip()
                if ref and ref not in known:
                    state.setdefault("contexts", []).append({"ref": ref, "status": "unchecked"})
                    known.add(ref)
            state["proposal"] = None
            state["status"] = "active"
            state["updated_at"] = timestamp
            result = {
                "session_id": session_id,
                "status": "active",
                "entry_id": entry_id,
                "entry_count": len(state["entries"]),
                "proposal_invalidated": True,
            }
            state["transactions"][transaction_id] = result
            self._write(directory, state)
            self._record_global(transaction_id, result)
            return {"idempotent": False, **result}

    def propose(
        self,
        session_id: str,
        *,
        flashes: list[dict[str, Any]],
        transaction_id: str,
    ) -> dict[str, Any]:
        if existing := self._global_result(transaction_id):
            return {"idempotent": True, **existing}
        directory = self._find_session_dir(session_id)
        with self._locked(directory):
            state = self._read(directory)
            if state.get("status") not in {"active", "reviewing"}:
                raise ValidationError("当前会话不能生成候选清单")
            if existing := self._transaction(state, transaction_id, {"session_id": session_id}):
                existing.pop("idempotent", None)
                self._record_global(transaction_id, existing)
                existing["idempotent"] = True
                return existing
            entry_ids = {
                item["entry_id"] for item in state.get("entries", []) if item.get("role") == "user"
            }
            normalized: list[dict[str, Any]] = []
            for index, flash in enumerate(flashes):
                title = str(flash.get("title") or "").strip()
                body = str(flash.get("body") or "").strip()
                refs = list(dict.fromkeys(str(item) for item in flash.get("entry_ids", [])))
                if not title or not body:
                    raise ValidationError(f"候选闪念 {index + 1} 缺少标题或正文")
                if not refs or not set(refs).issubset(entry_ids):
                    raise ValidationError(f"候选闪念 {index + 1} 必须追溯到用户表达")
                normalized.append(
                    {
                        "title": title,
                        "body": body,
                        "entry_ids": refs,
                        "context_refs": list(
                            dict.fromkeys(str(item) for item in flash.get("context_refs", []))
                        ),
                    }
                )
            version = int((state.get("proposal") or {}).get("version", 0)) + 1
            digest = hashlib.sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()
            proposal = {
                "proposal_id": f"CPR-{digest[:12]}",
                "version": version,
                "sha256": digest,
                "created_at": now_iso(),
                "last_entry_id": state["entries"][-1]["entry_id"],
                "flashes": normalized,
            }
            state["proposal"] = proposal
            state["status"] = "reviewing"
            state["updated_at"] = now_iso()
            result = {
                "session_id": session_id,
                "status": "reviewing",
                "proposal_id": proposal["proposal_id"],
                "version": version,
                "flash_count": len(normalized),
            }
            state["transactions"][transaction_id] = result
            self._write(directory, state)
            self._record_global(transaction_id, result)
            return {"idempotent": False, **result}

    def update_context(
        self,
        session_id: str,
        *,
        ref: str,
        status: str,
        fingerprint: dict[str, Any],
        transaction_id: str,
    ) -> dict[str, Any]:
        if status not in {"readable", "unreadable", "partial"}:
            raise ValidationError("上下文状态必须是 readable、unreadable 或 partial")
        if existing := self._global_result(transaction_id):
            return {"idempotent": True, **existing}
        directory = self._find_session_dir(session_id)
        with self._locked(directory):
            state = self._read(directory)
            if state.get("status") not in ACTIVE_STATES:
                raise ValidationError("当前会话不能更新上下文检查结果")
            if existing := self._transaction(state, transaction_id, {"session_id": session_id}):
                existing.pop("idempotent", None)
                self._record_global(transaction_id, existing)
                existing["idempotent"] = True
                return existing
            target = next(
                (item for item in state.get("contexts", []) if item.get("ref") == ref),
                None,
            )
            if target is None:
                raise ValidationError("上下文引用不属于当前捕获会话")
            clean_fingerprint = {
                key: value
                for key, value in fingerprint.items()
                if key in {"sha256", "size", "modified_at", "resolved_ref", "checked_at"}
                and isinstance(value, (str, int, float))
            }
            target.update(
                {
                    "status": status,
                    "fingerprint": clean_fingerprint,
                    "checked_at": now_iso(),
                }
            )
            state["updated_at"] = now_iso()
            result = {"session_id": session_id, "ref": ref, "status": status}
            state["transactions"][transaction_id] = result
            self._write(directory, state)
            self._record_global(transaction_id, result)
            return {"idempotent": False, **result}

    def maintenance_status(self, session_id: str = "") -> dict[str, Any]:
        jobs: list[dict[str, Any]] = []
        for path in sorted(self.maintenance.glob("JOB-*.json")):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise IntegrityError(f"后台维护任务损坏：{path.name}") from exc
            if not session_id or job.get("session_id") == session_id:
                jobs.append(job)
        return {"jobs": jobs, "count": len(jobs)}

    def update_maintenance_job(
        self,
        job_id: str,
        *,
        status: str,
        error: str = "",
    ) -> dict[str, Any]:
        if not re.fullmatch(r"JOB-[0-9a-f]{12}", job_id):
            raise ValidationError("无效的后台维护任务 ID")
        allowed = {
            "pending", "processing", "maintenance_paused", "retry_pending",
            "partial", "failed", "complete", "cancelled", "context_changed",
        }
        if status not in allowed:
            raise ValidationError("无效的后台维护状态")
        path = self.maintenance / f"{job_id}.json"
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"找不到后台维护任务：{job_id}") from exc
        current = str(job.get("status") or "")
        transitions = {
            "pending": {"processing", "maintenance_paused", "failed", "cancelled", "context_changed"},
            "processing": {"complete", "partial", "failed", "retry_pending", "maintenance_paused", "cancelled", "context_changed"},
            "maintenance_paused": {"pending", "processing", "cancelled", "context_changed"},
            "retry_pending": {"processing", "failed", "maintenance_paused", "cancelled", "context_changed"},
            "context_changed": {"pending", "failed", "cancelled"},
            "partial": set(),
            "failed": set(),
            "complete": set(),
            "cancelled": set(),
        }
        if status != current and status not in transitions.get(current, set()):
            raise ValidationError(f"后台维护状态不能从 {current} 转为 {status}")
        job["status"] = status
        job["updated_at"] = now_iso()
        if status == "retry_pending":
            attempts = int(job.get("attempts", 0)) + 1
            job["attempts"] = attempts
            if status == "retry_pending" and attempts >= int(job.get("max_attempts", 3)):
                job["status"] = "failed"
        if error:
            job["last_error"] = error
        _atomic_json(path, job)
        return job

    def pause_processing_jobs(self) -> list[str]:
        paused: list[str] = []
        for job in self.maintenance_status()["jobs"]:
            if job.get("status") != "processing":
                continue
            self.update_maintenance_job(job["job_id"], status="maintenance_paused")
            paused.append(job["job_id"])
        return paused

    def check_maintenance_context(
        self, job_id: str, *, fingerprint: dict[str, Any]
    ) -> dict[str, Any]:
        if not re.fullmatch(r"JOB-[0-9a-f]{12}", job_id):
            raise ValidationError("无效的后台维护任务 ID")
        path = self.maintenance / f"{job_id}.json"
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"找不到后台维护任务：{job_id}") from exc
        original = job.get("context", {}).get("fingerprint") or {}
        comparable = {"sha256", "size", "modified_at", "resolved_ref"}
        changed = any(
            key in original and original.get(key) != fingerprint.get(key)
            for key in comparable
        )
        if changed:
            job["status"] = "context_changed"
            job["updated_at"] = now_iso()
            _atomic_json(path, job)
        return {"job_id": job_id, "changed": changed, "status": job["status"]}

    def cancel_jobs_for_session(self, session_id: str) -> list[str]:
        cancelled: list[str] = []
        for job in self.maintenance_status(session_id)["jobs"]:
            if job.get("status") in {"complete", "cancelled"}:
                continue
            self.update_maintenance_job(job["job_id"], status="cancelled")
            cancelled.append(job["job_id"])
        completed = self._session_dir(session_id, completed=True)
        if completed.is_dir():
            with self._locked(completed):
                state = self._read(completed)
                state["status"] = "reverted"
                state["reverted_at"] = now_iso()
                self._write(completed, state)
        return cancelled

    def cleanup_completed(self, *, current_time: datetime | None = None) -> list[str]:
        now = current_time or datetime.now().astimezone()
        removed: list[str] = []
        for directory in sorted(self.completed.iterdir()):
            if not directory.is_dir():
                continue
            state = self._read(directory)
            cleanup_raw = state.get("cleanup_after")
            if not cleanup_raw or now < datetime.fromisoformat(str(cleanup_raw)):
                continue
            jobs = self.maintenance_status(str(state["session_id"]))["jobs"]
            if any(job.get("status") not in {"complete", "failed", "cancelled", "partial"} for job in jobs):
                continue
            shutil.rmtree(directory)
            removed.append(str(state["session_id"]))
        return removed

    def transition(
        self,
        session_id: str,
        *,
        action: str,
        transaction_id: str,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if existing := self._global_result(transaction_id):
            return {"idempotent": True, **existing}
        directory = self._find_session_dir(session_id)
        with self._locked(directory):
            state = self._read(directory)
            if existing := self._transaction(state, transaction_id, {"session_id": session_id}):
                existing.pop("idempotent", None)
                self._record_global(transaction_id, existing)
                existing["idempotent"] = True
                return existing
            current = state.get("status")
            targets = {
                "pause": ({"active", "reviewing"}, "paused"),
                "resume": ({"paused"}, "active"),
                "discard": (ACTIVE_STATES, "abandoned"),
            }
            allowed, target = targets[action]
            if current not in allowed:
                raise ValidationError(f"不能从 {current} 执行 {action}")
            if action == "discard" and not confirmed:
                raise ValidationError("放弃捕获会话必须确认用户明确放弃")
            result = {"session_id": session_id, "status": target}
            state["status"] = target
            state["updated_at"] = now_iso()
            state["transactions"][transaction_id] = result
            if action == "discard":
                self._record_global(transaction_id, result)
                shutil.rmtree(directory)
            else:
                self._write(directory, state)
                self._record_global(transaction_id, result)
            return {"idempotent": False, **result}

    def status(self, session_id: str = "") -> dict[str, Any]:
        directories: list[Path]
        if session_id:
            directories = [self._find_session_dir(session_id)]
        else:
            directories = [path for path in sorted(self.captures.iterdir()) if path.is_dir()]
        sessions = []
        for directory in directories:
            state = self._read(directory)
            sessions.append(
                {
                    "session_id": state["session_id"],
                    "status": state["status"],
                    "created_at": state["created_at"],
                    "updated_at": state["updated_at"],
                    "entry_count": len(state.get("entries", [])),
                    "proposal": state.get("proposal"),
                    "contexts": state.get("contexts", []),
                }
            )
        return {"sessions": sessions, "count": len(sessions)}

    def load_for_finalize(self, session_id: str, proposal_id: str) -> tuple[Path, dict[str, Any]]:
        directory = self._find_session_dir(session_id)
        state = self._read(directory)
        proposal = state.get("proposal")
        if state.get("status") != "reviewing" or not isinstance(proposal, dict):
            raise ValidationError("捕获会话没有可确认的最新候选")
        if proposal.get("proposal_id") != proposal_id:
            raise ValidationError("只能确认最新闪念候选")
        if proposal.get("last_entry_id") != state.get("entries", [])[-1].get("entry_id"):
            raise ValidationError("候选生成后出现新表达，必须重新审阅")
        return directory, state

    def finalize_runtime(
        self,
        directory: Path,
        state: dict[str, Any],
        *,
        formal_result: dict[str, Any],
    ) -> None:
        with self._locked(directory):
            current = self._read(directory)
            if current.get("proposal") != state.get("proposal"):
                raise IntegrityError("正式写入期间捕获候选发生变化")
            timestamp = now_iso()
            current["status"] = "finalized"
            current["finalized_at"] = timestamp
            current["cleanup_after"] = (
                datetime.now().astimezone() + timedelta(hours=24)
            ).isoformat(timespec="seconds")
            current["formal_result"] = formal_result
            self._write(directory, current)
            target = self._session_dir(current["session_id"], completed=True)
            if target.exists():
                raise IntegrityError("已存在同名完成会话")
            os.replace(directory, target)

    def enqueue_maintenance(
        self, session_id: str, contexts: list[dict[str, Any]], flashes: list[dict[str, Any]]
    ) -> list[str]:
        job_ids: list[str] = []
        for context in contexts:
            ref = str(context.get("ref") or "")
            related = [
                flash["id"]
                for flash in flashes
                if ref in flash.get("context_refs", [])
            ]
            if not related:
                continue
            digest = hashlib.sha256(f"{session_id}:{ref}".encode("utf-8")).hexdigest()
            job_id = f"JOB-{digest[:12]}"
            payload = {
                "job_id": job_id,
                "kind": "capture-source-maintenance",
                "session_id": session_id,
                "context": context,
                "flash_ids": related,
                "status": "pending",
                "attempts": 0,
                "max_attempts": 3,
                "created_at": now_iso(),
            }
            path = self.maintenance / f"{job_id}.json"
            if path.exists():
                existing = json.loads(path.read_text(encoding="utf-8"))
                identity = ("job_id", "session_id", "flash_ids")
                if any(existing.get(key) != payload.get(key) for key in identity):
                    raise IntegrityError("后台维护任务身份冲突")
            else:
                _atomic_json(path, payload)
            job_ids.append(job_id)
        return job_ids

    def maintenance_job_ids(
        self, session_id: str, contexts: list[dict[str, Any]], flashes: list[dict[str, Any]]
    ) -> list[str]:
        ids: list[str] = []
        for context in contexts:
            ref = str(context.get("ref") or "")
            if any(ref in flash.get("context_refs", []) for flash in flashes):
                digest = hashlib.sha256(f"{session_id}:{ref}".encode("utf-8")).hexdigest()
                ids.append(f"JOB-{digest[:12]}")
        return ids
