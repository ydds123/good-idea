from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import Any


TRANSACTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SESSION_ID_PATTERN = re.compile(r"^CAP-[0-9]{8}-[0-9a-f]{8}$")
MAINTENANCE_JOB_ID_PATTERN = re.compile(r"^JOB-[0-9a-f]{12}$")
FLASH_EVENT_FORMAT_VERSION = 2

FLASH_STALE_AFTER = timedelta(hours=48)
CAPTURE_RECOVERY_WINDOW = timedelta(hours=24)
PERMANENT_CARD_TYPES = frozenset({"permanent", "mother", "action", "index"})
CAPTURE_ACTIVE_STATES = frozenset({"active", "reviewing", "paused"})
MAINTENANCE_STATES = (
    "pending", "processing", "maintenance_paused", "retry_pending",
    "partial", "failed", "complete", "cancelled", "context_changed",
)


def normalize_flash_event(
    raw: dict[str, Any], known_entry_ids: set[str], *, format_version: int
) -> dict[str, Any]:
    """Validate the flash-event payload without interpreting its prose."""
    title = str(raw.get("title") or "").strip()
    body = str(raw.get("body") or "").strip()
    entry_ids = list(dict.fromkeys(str(item) for item in raw.get("entry_ids", [])))
    if not title or not body:
        raise ValueError("缺少标题或正文")
    if not entry_ids or not set(entry_ids).issubset(known_entry_ids):
        raise ValueError("必须追溯到用户表达")
    event = {
        "title": title,
        "body": body,
        "entry_ids": entry_ids,
        "context_refs": list(
            dict.fromkeys(str(item) for item in raw.get("context_refs", []))
        ),
    }
    if format_version >= FLASH_EVENT_FORMAT_VERSION:
        for field in ("source_anchor", "trigger_anchor", "activated_logic"):
            value = str(raw.get(field) or "").strip()
            if not value:
                raise ValueError(f"缺少认知事件字段 {field}")
            event[field] = value
    return event

NOTE_SPECS: dict[str, dict[str, Any]] = {
    "flash": {
        "location": Path("闪念空间"), "heading": "闪念", "default": "pending",
        "statuses": {"pending", "processed", "dismissed"},
        "required": {"source_ids"}, "id": re.compile(r"^FLA-[0-9]{8}-[0-9a-f]{8}$"),
    },
    "source": {
        "location": Path("溯源空间"), "heading": "溯源", "default": "complete",
        "statuses": {"complete", "partial", "failed", "update_available"},
        "required": {"capture_status", "fetched_at", "content_sha256", "snapshot_sha256", "image_failures"},
        "id": re.compile(r"^SRC-[0-9a-f]{12}$"),
    },
    "interesting": {
        "location": Path("有意思空间"), "heading": "有意思", "default": "pending",
        "statuses": {"pending", "processed", "dismissed"}, "required": {"source_ids"},
        "id": re.compile(r"^INT-[0-9]{8}-[0-9a-f]{8}$"),
    },
    "todo": {
        "location": Path("待办空间"), "heading": "待办", "default": "open",
        "statuses": {"open", "done", "cancelled"}, "required": {"source_ids"},
        "id": re.compile(r"^TODO-[0-9]{8}-[0-9a-f]{8}$"),
    },
    "permanent": {
        "location": Path("永久空间/永久卡片"), "heading": "永久卡片", "default": "active",
        "statuses": {"active", "revised", "retired"}, "required": {"authoring_mode", "source_ids", "derived_from"},
        "id": re.compile(r"^PER-[0-9]{8}-[0-9a-f]{8}$"),
    },
    "mother": {
        "location": Path("永久空间/母题卡片"), "heading": "母题卡片", "default": "open",
        "statuses": {"open", "evolving", "retired"}, "required": {"authoring_mode", "source_ids", "derived_from"},
        "id": re.compile(r"^MOT-[0-9]{8}-[0-9a-f]{8}$"),
    },
    "action": {
        "location": Path("永久空间/行动卡片"), "heading": "行动卡片", "default": "planned",
        "statuses": {"planned", "acting", "observing", "reviewed"}, "required": {"authoring_mode", "source_ids", "derived_from"},
        "id": re.compile(r"^ACT-[0-9]{8}-[0-9a-f]{8}$"),
    },
    "index": {
        "location": Path("永久空间/索引卡片"), "heading": "索引卡片", "default": "active",
        "statuses": {"active", "revised", "retired"}, "required": {"authoring_mode", "source_ids", "derived_from"},
        "id": re.compile(r"^IDX-[0-9]{8}-[0-9a-f]{8}$"),
    },
}
