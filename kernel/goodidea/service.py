from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .errors import ConflictError, NotFoundError, ValidationError
from .identity import canonical_url, file_identity, search_units, text_identity
from .store import DataStore


FLASH_WINDOW = timedelta(hours=48)


class GoodIdea:
    """Small deterministic surface beneath the rule layer."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        store: DataStore | None = None,
        now: Callable[[], datetime] | None = None,
        make_id: Callable[[str], str] | None = None,
    ) -> None:
        self.root = Path(project_root).resolve()
        self.store = store or DataStore(self.root)
        self._clock = now or (lambda: datetime.now(timezone.utc))
        self._make_id = make_id or (lambda prefix: f"{prefix}-{uuid.uuid4().hex[:16]}")

    # Original thought sessions -------------------------------------------------

    def start_session(
        self,
        message: str,
        *,
        user_started: bool,
        context: Iterable[str] = (),
    ) -> dict[str, Any]:
        if not user_started:
            raise ValidationError("a session requires an explicit user capture request")
        timestamp = self._now()
        session = {
            "id": self._make_id("THO"),
            "kind": "session",
            "status": "recording",
            "started_at": timestamp,
            "closed_at": None,
            "updated_at": timestamp,
            "messages": [self._message("user", self._required(message, "message"), timestamp)],
            "context": self._unique(context),
            "source_ids": [],
            "flash_ids": [],
            "insight_ids": [],
            "history": [self._history("started", timestamp)],
        }
        self._write([session], "session.start", timestamp)
        return session

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        context: Iterable[str] = (),
    ) -> dict[str, Any]:
        if role not in {"user", "assistant"}:
            raise ValidationError("role must be user or assistant")
        session = self._get("session", session_id)
        if session["status"] != "recording":
            raise ConflictError("closed sessions are immutable")
        timestamp = self._now()
        session["messages"].append(
            self._message(role, self._required(content, "content"), timestamp)
        )
        session["context"] = self._unique([*session["context"], *context])
        session["updated_at"] = timestamp
        self._write([session], "session.append", timestamp)
        return session

    def close_session(self, session_id: str) -> dict[str, Any]:
        session = self._get("session", session_id)
        if session["status"] == "closed":
            return session
        timestamp = self._now()
        session["status"] = "closed"
        session["closed_at"] = timestamp
        session["updated_at"] = timestamp
        session["history"].append(self._history("closed", timestamp))
        self._write([session], "session.close", timestamp)
        return session

    # Flash --------------------------------------------------------------------

    def draft_flash(
        self,
        session_id: str,
        *,
        title: str,
        content: str,
        trigger: str,
        source_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        self.store.read("session", session_id)
        sources = self._unique(source_ids)
        for source_id in sources:
            self.store.read("source", source_id)
        candidate = {
            "candidate": "flash",
            "session_id": session_id,
            "title": self._required(title, "title"),
            "content": self._required(content, "content"),
            "trigger": self._required(trigger, "trigger"),
            "source_ids": sources,
        }
        candidate["sha256"] = self._candidate_hash(candidate)
        return candidate

    def accept_flash(
        self, candidate: Mapping[str, Any], *, user_confirmed: bool
    ) -> dict[str, Any]:
        if not user_confirmed:
            raise ValidationError("the user must claim a flash candidate")
        if candidate.get("candidate") != "flash":
            raise ValidationError("not a flash candidate")
        session = self._get("session", str(candidate.get("session_id") or ""))
        sources = self._unique(candidate.get("source_ids", []))
        for source_id in sources:
            self.store.read("source", source_id)
        timestamp = self._now()
        flash = {
            "id": self._make_id("FLA"),
            "kind": "flash",
            "title": self._required(str(candidate.get("title") or ""), "title"),
            "content": self._required(str(candidate.get("content") or ""), "content"),
            "trigger": self._required(str(candidate.get("trigger") or ""), "trigger"),
            "session_id": session["id"],
            "source_ids": sources,
            "status": "pending",
            "claimed_at": timestamp,
            "updated_at": timestamp,
            "analysis": "",
            "gap": "",
            "retrigger": "",
            "insight_ids": [],
            "candidate_sha256": str(candidate.get("sha256") or self._candidate_hash(candidate)),
            "history": [self._history("claimed", timestamp)],
        }
        session["flash_ids"] = self._unique([*session["flash_ids"], flash["id"]])
        session["updated_at"] = timestamp
        writes = [flash, session]
        writes.extend(self._source_usage(sources, "flash", flash["id"], timestamp))
        self._write(self._dedupe(writes), "flash.claim", timestamp)
        return flash

    def decide_flash(
        self,
        flash_id: str,
        *,
        outcome: str,
        user_decided: bool,
        analysis: str = "",
        gap: str = "",
        retrigger: str = "",
    ) -> dict[str, Any]:
        if not user_decided:
            raise ValidationError("the user must decide a flash outcome")
        if outcome not in {"dismissed", "fermenting"}:
            raise ValidationError("outcome must be dismissed or fermenting")
        flash = self._get("flash", flash_id)
        if flash["status"] not in {"pending", "fermenting"}:
            raise ConflictError(f"cannot decide from {flash['status']}")
        if outcome == "fermenting":
            analysis = self._required(analysis, "analysis")
            gap = self._required(gap, "gap")
            retrigger = self._required(retrigger, "retrigger")
        timestamp = self._now()
        flash.update(
            status=outcome,
            analysis=analysis.strip(),
            gap=gap.strip(),
            retrigger=retrigger.strip(),
            updated_at=timestamp,
        )
        flash["history"].append(self._history(outcome, timestamp, analysis.strip()))
        self._write([flash], f"flash.{outcome}", timestamp)
        return flash

    def expire_flashes(
        self,
        *,
        at: datetime | None = None,
        active_flash_ids: Iterable[str] = (),
    ) -> list[dict[str, Any]]:
        timestamp = self._iso(at or self._clock())
        now = self._parse_time(timestamp)
        active = set(active_flash_ids)
        expired: list[dict[str, Any]] = []
        for flash in self.store.list("flash"):
            if flash["status"] != "pending" or flash["id"] in active:
                continue
            if now - self._parse_time(flash["claimed_at"]) < FLASH_WINDOW:
                continue
            flash["status"] = "expired"
            flash["updated_at"] = timestamp
            flash["history"].append(self._history("expired", timestamp))
            expired.append(flash)
        if expired:
            self._write(expired, "flash.expire", timestamp)
        return expired

    def reactivate_flash(self, flash_id: str, *, user_decided: bool) -> dict[str, Any]:
        if not user_decided:
            raise ValidationError("the user must reactivate a flash")
        flash = self._get("flash", flash_id)
        if flash["status"] != "expired":
            raise ConflictError("only expired flashes can be reactivated")
        timestamp = self._now()
        flash["status"] = "pending"
        flash["claimed_at"] = timestamp
        flash["updated_at"] = timestamp
        flash["history"].append(self._history("reactivated", timestamp))
        self._write([flash], "flash.reactivate", timestamp)
        return flash

    # Permanent insight ---------------------------------------------------------

    def draft_insight(
        self,
        *,
        title: str,
        judgment: str,
        reason: str,
        evidence: Iterable[Mapping[str, str]],
        boundary: str = "",
    ) -> dict[str, Any]:
        refs = [self._reference(item) for item in evidence]
        if not refs:
            raise ValidationError("formation evidence is required")
        candidate = {
            "candidate": "insight",
            "title": self._required(title, "title"),
            "judgment": self._required(judgment, "judgment"),
            "reason": self._required(reason, "reason"),
            "boundary": boundary.strip(),
            "evidence": refs,
        }
        candidate["sha256"] = self._candidate_hash(candidate)
        return candidate

    def accept_insight(
        self, candidate: Mapping[str, Any], *, user_confirmed: bool
    ) -> dict[str, Any]:
        if not user_confirmed:
            raise ValidationError("the user must claim the complete insight candidate")
        if candidate.get("candidate") != "insight":
            raise ValidationError("not an insight candidate")
        evidence = [self._reference(item) for item in candidate.get("evidence", [])]
        if not evidence:
            raise ValidationError("formation evidence is required")
        for ref in evidence:
            self.store.read(ref["kind"], ref["id"])
        timestamp = self._now()
        insight = {
            "id": self._make_id("INS"),
            "kind": "insight",
            "title": self._required(str(candidate.get("title") or ""), "title"),
            "judgment": self._required(
                str(candidate.get("judgment") or ""), "judgment"
            ),
            "reason": self._required(str(candidate.get("reason") or ""), "reason"),
            "boundary": str(candidate.get("boundary") or "").strip(),
            "evidence": evidence,
            "status": "active",
            "claimed_at": timestamp,
            "updated_at": timestamp,
            "revisions": [],
            "candidate_sha256": str(candidate.get("sha256") or self._candidate_hash(candidate)),
            "history": [self._history("claimed", timestamp)],
        }
        writes: list[dict[str, Any]] = [insight]
        for ref in evidence:
            related = self._get(ref["kind"], ref["id"])
            if ref["kind"] == "flash":
                if related["status"] in {"dismissed", "expired"}:
                    raise ConflictError("reactivate the flash before using it as evidence")
                related["status"] = "formed"
                related["insight_ids"] = self._unique(
                    [*related["insight_ids"], insight["id"]]
                )
                related["history"].append(
                    self._history("formed", timestamp, insight["id"])
                )
            elif ref["kind"] == "session":
                related["insight_ids"] = self._unique(
                    [*related["insight_ids"], insight["id"]]
                )
            elif ref["kind"] == "source":
                related["usage"] = self._append_usage(
                    related["usage"], "insight", insight["id"], timestamp
                )
            related["updated_at"] = timestamp
            writes.append(related)
        self._write(self._dedupe(writes), "insight.claim", timestamp)
        return insight

    def revise_insight(
        self,
        insight_id: str,
        *,
        user_confirmed: bool,
        judgment: str | None = None,
        reason: str | None = None,
        boundary: str | None = None,
    ) -> dict[str, Any]:
        if not user_confirmed:
            raise ValidationError("the user must confirm an insight revision")
        if judgment is None and reason is None and boundary is None:
            raise ValidationError("revision has no changes")
        insight = self._get("insight", insight_id)
        if insight["status"] == "retired":
            raise ConflictError("retired insight cannot be silently revised")
        timestamp = self._now()
        insight["revisions"].append(
            {
                "at": timestamp,
                "judgment": insight["judgment"],
                "reason": insight["reason"],
                "boundary": insight["boundary"],
            }
        )
        if judgment is not None:
            insight["judgment"] = self._required(judgment, "judgment")
        if reason is not None:
            insight["reason"] = self._required(reason, "reason")
        if boundary is not None:
            insight["boundary"] = boundary.strip()
        insight["status"] = "revised"
        insight["updated_at"] = timestamp
        insight["history"].append(self._history("revised", timestamp))
        self._write([insight], "insight.revise", timestamp)
        return insight

    def retire_insight(self, insight_id: str, *, user_decided: bool) -> dict[str, Any]:
        if not user_decided:
            raise ValidationError("the user must retire an insight")
        insight = self._get("insight", insight_id)
        if insight["status"] == "retired":
            return insight
        timestamp = self._now()
        insight["status"] = "retired"
        insight["updated_at"] = timestamp
        insight["history"].append(self._history("retired", timestamp))
        self._write([insight], "insight.retire", timestamp)
        return insight

    # External sources ----------------------------------------------------------

    def register_source(
        self,
        *,
        material_type: str,
        raw_reference: str,
        brought_by: str,
        persistence_intent: bool = False,
        session_id: str | None = None,
        content: str | bytes | None = None,
        filename: str | None = None,
        identity_confirmed: bool = True,
        same_source_id: str | None = None,
    ) -> dict[str, Any]:
        if brought_by not in {"user", "agent"}:
            raise ValidationError("brought_by must be user or agent")
        session = self._get("session", session_id) if session_id else None
        if not persistence_intent and not (brought_by == "user" and session_id):
            raise ValidationError("source registration requires user persistence intent")
        reference = self._required(raw_reference, "raw_reference")
        timestamp = self._now()
        if identity_confirmed:
            identity, normalized, metadata = self._source_identity(
                material_type, reference, content, filename
            )
            if same_source_id:
                source = self._get("source", same_source_id)
                if not source.get("identity"):
                    raise ConflictError("resolve source identity before adding a new version")
                identity = source["identity"]
            else:
                source = next(
                    (
                        item
                        for item in self.store.list("source")
                        if item.get("identity") == identity
                    ),
                    None,
                )
        else:
            identity, normalized, metadata, source = None, reference, {}, None
            if material_type == "file":
                normalized = Path(reference).name
        if source is None:
            source = {
                "id": self._make_id("SRC" if identity else "REF"),
                "kind": "source",
                "identity": identity,
                "material_type": material_type,
                "status": "pending_fetch" if identity else "pending_identity",
                "raw_references": [],
                "snapshots": [],
                "usage": [],
                "metadata": metadata,
                "created_at": timestamp,
                "updated_at": timestamp,
                "history": [
                    self._history("registered" if identity else "pending_identity", timestamp)
                ],
            }
        persisted_reference = normalized if material_type == "file" else reference
        if not any(item["reference"] == persisted_reference for item in source["raw_references"]):
            source["raw_references"].append(
                {
                    "reference": persisted_reference,
                    "normalized": normalized,
                    "brought_by": brought_by,
                    "session_id": session_id,
                    "seen_at": timestamp,
                }
            )
        if session_id:
            source["usage"] = self._append_usage(
                source["usage"], "session", session_id, timestamp
            )
        source["updated_at"] = timestamp
        writes = [source]
        if session:
            session["source_ids"] = self._unique([*session["source_ids"], source["id"]])
            session["context"] = self._unique([*session["context"], persisted_reference])
            session["updated_at"] = timestamp
            writes.append(session)
        self._write(writes, "source.register", timestamp)
        return source

    def resolve_source_identity(
        self,
        source_id: str,
        *,
        material_type: str,
        resolved_reference: str,
        content: str | bytes | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        source = self._get("source", source_id)
        if source["status"] != "pending_identity":
            raise ConflictError("only pending_identity sources can be resolved")
        identity, normalized, metadata = self._source_identity(
            material_type, resolved_reference, content, filename
        )
        duplicate = next(
            (
                item
                for item in self.store.list("source")
                if item["id"] != source_id and item.get("identity") == identity
            ),
            None,
        )
        if duplicate:
            raise ConflictError(f"identity already belongs to source {duplicate['id']}")
        timestamp = self._now()
        source["identity"] = identity
        source["material_type"] = material_type
        source["status"] = "pending_fetch"
        source["metadata"] = metadata
        persisted_reference = normalized if material_type == "file" else resolved_reference
        if not any(
            item["reference"] == persisted_reference
            for item in source["raw_references"]
        ):
            source["raw_references"].append(
                {
                    "reference": persisted_reference,
                    "normalized": normalized,
                    "brought_by": "resolver",
                    "session_id": None,
                    "seen_at": timestamp,
                }
            )
        source["updated_at"] = timestamp
        source["history"].append(self._history("identity_resolved", timestamp, normalized))
        self._write([source], "source.resolve_identity", timestamp)
        return source

    def add_snapshot(
        self,
        source_id: str,
        *,
        quality: str,
        content: str = "",
        title: str = "",
        author: str = "",
        published_at: str = "",
        error: str = "",
    ) -> dict[str, Any]:
        if quality not in {"complete", "partial", "failed"}:
            raise ValidationError("quality must be complete, partial, or failed")
        if quality in {"complete", "partial"}:
            content = self._required(content, "snapshot content")
        if quality == "failed" and not error.strip():
            raise ValidationError("failed snapshot requires an error")
        source = self._get("source", source_id)
        if not source.get("identity"):
            raise ConflictError("resolve source identity before adding a snapshot")
        timestamp = self._now()
        source["snapshots"].append(
            {
                "version": len(source["snapshots"]) + 1,
                "quality": quality,
                "content": content,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "title": title.strip(),
                "author": author.strip(),
                "published_at": published_at.strip(),
                "error": error.strip(),
                "fetched_at": timestamp,
            }
        )
        source["status"] = quality
        source["updated_at"] = timestamp
        source["history"].append(self._history(f"snapshot_{quality}", timestamp))
        self._write([source], "source.snapshot", timestamp)
        return source

    # Recall --------------------------------------------------------------------

    def recall(
        self,
        query: str,
        *,
        mode: str = "default",
        include_sources: bool = False,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        query = self._required(query, "query")
        if mode not in {"default", "analysis", "context"}:
            raise ValidationError("mode must be default, analysis, or context")
        candidates: list[dict[str, Any]] = [
            item
            for item in self.store.list("insight")
            if item["status"] in {"active", "revised"}
        ]
        candidates.extend(
            item
            for item in self.store.list("flash")
            if item["status"] == "fermenting"
            or (mode == "analysis" and item["status"] == "pending")
        )
        if mode == "context":
            candidates.extend(self.store.list("session"))
        if include_sources:
            candidates.extend(self.store.list("source"))
        matches = []
        for item in candidates:
            score, reason = self._score(query, self._search_text(item))
            if score <= 0:
                continue
            matches.append(
                {
                    "id": item["id"],
                    "type": item["kind"],
                    "status": item["status"],
                    "time": item.get("claimed_at")
                    or item.get("started_at")
                    or item.get("created_at"),
                    "title": item.get("title") or self._session_title(item),
                    "relevance": reason,
                    "score": score,
                }
            )
        matches.sort(key=lambda item: (item["score"], item["time"]), reverse=True)
        return matches[:limit]

    # Helpers -------------------------------------------------------------------

    def _get(self, kind: str, object_id: str | None) -> dict[str, Any]:
        if not object_id:
            raise NotFoundError(f"{kind} id is required")
        return copy.deepcopy(self.store.read(kind, object_id))

    def _write(self, objects: Iterable[Mapping[str, Any]], action: str, at: str) -> None:
        self.store.commit(objects, action=action, timestamp=at)

    def _source_usage(
        self, source_ids: Iterable[str], kind: str, object_id: str, at: str
    ) -> list[dict[str, Any]]:
        updates = []
        for source_id in self._unique(source_ids):
            source = self._get("source", source_id)
            source["usage"] = self._append_usage(source["usage"], kind, object_id, at)
            source["updated_at"] = at
            updates.append(source)
        return updates

    @staticmethod
    def _append_usage(
        usage: Iterable[Mapping[str, Any]], kind: str, object_id: str, at: str
    ) -> list[dict[str, Any]]:
        result = [dict(item) for item in usage]
        if not any(item["kind"] == kind and item["id"] == object_id for item in result):
            result.append({"kind": kind, "id": object_id, "linked_at": at})
        return result

    def _source_identity(
        self,
        material_type: str,
        reference: str,
        content: str | bytes | None,
        filename: str | None,
    ) -> tuple[str, str, dict[str, str]]:
        if material_type == "url":
            normalized = canonical_url(reference)
            return f"url:{normalized}", normalized, {"canonical_url": normalized}
        if material_type == "file":
            if content is None:
                raise ValidationError("file identity requires content")
            raw = content.encode() if isinstance(content, str) else bytes(content)
            identity, basename = file_identity(filename or reference, raw)
            return identity, basename, {
                "origin_filename": basename,
                "origin_sha256": identity.removeprefix("file:"),
            }
        if material_type == "text":
            if content is None:
                raise ValidationError("text identity requires content")
            text = content.decode() if isinstance(content, bytes) else content
            identity = text_identity(text)
            return identity, reference, {"content_sha256": identity.removeprefix("text:")}
        raise ValidationError("material_type must be url, file, or text")

    @staticmethod
    def _reference(item: Mapping[str, str]) -> dict[str, str]:
        kind = str(item.get("kind") or "")
        object_id = str(item.get("id") or "")
        if kind not in {"session", "flash", "source"} or not object_id:
            raise ValidationError("evidence must reference a session, flash, or source")
        return {"kind": kind, "id": object_id}

    def _message(self, role: str, content: str, at: str) -> dict[str, str]:
        return {"id": self._make_id("MSG"), "role": role, "content": content, "at": at}

    @staticmethod
    def _history(action: str, at: str, detail: str = "") -> dict[str, str]:
        return {"action": action, "at": at, "detail": detail}

    @staticmethod
    def _required(value: str, label: str) -> str:
        value = value.strip()
        if not value:
            raise ValidationError(f"{label} is required")
        return value

    @staticmethod
    def _unique(values: Iterable[Any]) -> list[str]:
        return list(dict.fromkeys(str(value) for value in values if str(value).strip()))

    @staticmethod
    def _candidate_hash(candidate: Mapping[str, Any]) -> str:
        payload = {key: value for key, value in candidate.items() if key != "sha256"}
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()

    @staticmethod
    def _dedupe(objects: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        keyed = {(item["kind"], item["id"]): item for item in objects}
        return list(keyed.values())

    def _now(self) -> str:
        return self._iso(self._clock())

    @staticmethod
    def _iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _parse_time(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _search_text(item: Mapping[str, Any]) -> str:
        parts = [
            str(item.get("title") or ""),
            str(item.get("content") or ""),
            str(item.get("trigger") or ""),
            str(item.get("analysis") or ""),
            str(item.get("gap") or ""),
            str(item.get("judgment") or ""),
            str(item.get("reason") or ""),
            str(item.get("boundary") or ""),
        ]
        parts.extend(str(message.get("content") or "") for message in item.get("messages", []))
        parts.extend(str(snapshot.get("content") or "") for snapshot in item.get("snapshots", []))
        return "\n".join(parts)

    @staticmethod
    def _session_title(item: Mapping[str, Any]) -> str:
        messages = item.get("messages", [])
        return str(messages[0]["content"])[:60] if messages else "原始思考会话"

    @staticmethod
    def _score(query: str, text: str) -> tuple[float, str]:
        score = 0.0
        reasons = []
        if query.casefold() in text.casefold():
            score += 10
            reasons.append("正文直接命中")
        query_units = search_units(query)
        shared = query_units & search_units(text)
        if shared:
            score += len(shared) / max(len(query_units), 1) * 5
            reasons.append(f"共享 {len(shared)} 个检索单元")
        return score, "；".join(reasons)
