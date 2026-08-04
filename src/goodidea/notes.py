from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .errors import IntegrityError, ValidationError
from .metadata import dump_frontmatter, parse_document, replace_frontmatter


SNAPSHOT_START_RE = re.compile(
    r"<!-- goodidea:snapshot:start sha256=([0-9a-f]{64}) -->\n"
)
SNAPSHOT_END = "<!-- goodidea:snapshot:end -->"
LITERATURE_START = "<!-- goodidea:literature:start -->"
LITERATURE_END = "<!-- goodidea:literature:end -->"

TYPE_LOCATIONS = {
    "flash": Path("闪念空间"),
    "source": Path("溯源空间"),
    "interesting": Path("有意思空间"),
    "todo": Path("待办空间"),
    "permanent": Path("永久空间/永久卡片"),
    "mother": Path("永久空间/母题卡片"),
    "action": Path("永久空间/行动卡片"),
    "index": Path("永久空间/索引卡片"),
}

INDEX_HEADINGS = {
    "flash": "闪念",
    "source": "溯源",
    "interesting": "有意思",
    "todo": "待办",
    "permanent": "永久卡片",
    "mother": "母题卡片",
    "action": "行动卡片",
    "index": "索引卡片",
}


def normalize_snapshot(text: str) -> str:
    return text.replace("\r\n", "\n").strip("\n") + "\n"


def snapshot_hash(text: str) -> str:
    return hashlib.sha256(normalize_snapshot(text).encode("utf-8")).hexdigest()


def extract_snapshot(note: str) -> tuple[str, str, int, int]:
    start = SNAPSHOT_START_RE.search(note)
    if not start:
        raise IntegrityError("来源缺少原文快照起始标记")
    end = note.find(SNAPSHOT_END, start.end())
    if end < 0:
        raise IntegrityError("来源缺少原文快照结束标记")
    content = note[start.end():end]
    return start.group(1), content, start.start(), end + len(SNAPSHOT_END)


def validate_source_note(note: str, path: str = "<memory>") -> None:
    metadata, _ = parse_document(note)
    declared, content, _, _ = extract_snapshot(note)
    actual = snapshot_hash(content)
    if declared != actual:
        raise IntegrityError(
            f"{path} 的快照标记哈希异常：expected={declared} actual={actual}"
        )
    if metadata.get("snapshot_sha256") != actual:
        raise IntegrityError(f"{path} 的 Frontmatter 快照哈希异常")


def render_source_note(
    metadata: dict[str, Any], snapshot: str, flash_links: list[str]
) -> str:
    digest = snapshot_hash(snapshot)
    metadata = dict(metadata)
    metadata["snapshot_sha256"] = digest
    links = "\n".join(f"- {link}" for link in flash_links) or "_暂无_"
    return (
        dump_frontmatter(metadata)
        + f"# {metadata['title']}\n\n"
        + "## 文献笔记\n\n"
        + f"{LITERATURE_START}\n"
        + "> 待处理：这里由用户在后续阅读与回顾中补充，不由系统自动生成观点。\n"
        + f"{LITERATURE_END}\n\n"
        + "## 关联闪念\n\n"
        + links
        + "\n\n## 原文快照\n\n"
        + f"<!-- goodidea:snapshot:start sha256={digest} -->\n"
        + normalize_snapshot(snapshot)
        + f"{SNAPSHOT_END}\n"
    )


def replace_source_snapshot(
    note: str, snapshot: str, metadata_updates: dict[str, Any]
) -> str:
    validate_source_note(note)
    metadata, _ = parse_document(note)
    metadata.update(metadata_updates)
    digest = snapshot_hash(snapshot)
    metadata["snapshot_sha256"] = digest
    _, _, start, end = extract_snapshot(note)
    replacement = (
        f"<!-- goodidea:snapshot:start sha256={digest} -->\n"
        + normalize_snapshot(snapshot)
        + SNAPSHOT_END
    )
    updated = note[:start] + replacement + note[end:]
    return replace_frontmatter(updated, metadata)


def add_list_item_to_section(note: str, heading: str, item: str) -> str:
    marker = f"## {heading}\n"
    position = note.find(marker)
    if position < 0:
        return note.rstrip() + f"\n\n## {heading}\n\n- {item}\n"
    next_heading = note.find("\n## ", position + len(marker))
    if next_heading < 0:
        next_heading = len(note)
    section = note[position:next_heading]
    if item in section:
        return note
    section = section.replace("\n_暂无_", "")
    section = section.rstrip() + f"\n\n- {item}\n"
    return note[:position] + section + note[next_heading:]


def render_note(
    metadata: dict[str, Any], sections: list[tuple[str, str]]
) -> str:
    body = [dump_frontmatter(metadata), f"# {metadata['title']}\n"]
    for heading, content in sections:
        body.append(f"\n## {heading}\n\n{content.strip()}\n")
    return "".join(body)


def validate_required_metadata(metadata: dict[str, Any]) -> list[str]:
    required = ("id", "type", "title", "status", "created_at", "updated_at")
    return [key for key in required if not metadata.get(key)]


def safe_filename(title: str, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|#\[\]]+', "-", title.strip())
    cleaned = re.sub(r"\s+", "-", cleaned).strip("-.")
    return (cleaned[:64] or fallback).strip("-.")


def wiki_link(path: Path, title: str) -> str:
    return f"[[{path.as_posix()[:-3]}|{title}]]"
