from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .contracts import NOTE_SPECS
from .errors import IntegrityError, ValidationError
from .metadata import dump_frontmatter, parse_document, replace_frontmatter


SNAPSHOT_START_RE = re.compile(
    r"<!-- goodidea:snapshot:start sha256=([0-9a-f]{64}) -->\n"
)
SNAPSHOT_END = "<!-- goodidea:snapshot:end -->"
_LEGACY_NOTE_START = "<!-- goodidea:literature:start -->"
_LEGACY_NOTE_END = "<!-- goodidea:literature:end -->"
_LEGACY_NOTE_PLACEHOLDER = (
    "> 待处理：这里由用户在后续阅读与回顾中补充，不由系统自动生成观点。"
)

TYPE_LOCATIONS = {kind: spec["location"] for kind, spec in NOTE_SPECS.items()}
INDEX_HEADINGS = {kind: spec["heading"] for kind, spec in NOTE_SPECS.items()}

STATUS_LABELS = {
    "pending": "待处理",
    "processed": "已处理",
    "dismissed": "已放弃",
    "complete": "完整",
    "partial": "部分抓取",
    "failed": "抓取失败",
    "update_available": "有更新待确认",
    "open": "进行中",
    "done": "已完成",
    "cancelled": "已取消",
    "active": "有效",
    "revised": "已修订",
    "retired": "已停用",
    "evolving": "演化中",
    "planned": "待行动",
    "acting": "行动中",
    "observing": "待观察",
    "reviewed": "已复盘",
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
        + "## 原文快照\n\n"
        + f"<!-- goodidea:snapshot:start sha256={digest} -->\n"
        + normalize_snapshot(snapshot)
        + f"{SNAPSHOT_END}\n\n"
        + "## 关联闪念\n\n"
        + links
        + "\n"
    )


def normalize_source_layout(note: str) -> str:
    """Apply the human-facing source layout without rewriting article Markdown."""
    validate_source_note(note)
    metadata, _ = parse_document(note)
    metadata = dict(metadata)
    metadata.pop("source_url", None)
    metadata.pop("summary", None)

    _, snapshot_content, _, _ = extract_snapshot(note)
    snapshot_lines = normalize_snapshot(snapshot_content).splitlines()
    if snapshot_lines and snapshot_lines[0].startswith("# 原文："):
        try:
            separator = snapshot_lines.index("---")
        except ValueError:
            separator = -1
        if separator >= 0:
            article_lines = snapshot_lines[separator + 1:]
            while article_lines and not article_lines[0]:
                article_lines.pop(0)
            context_lines: list[str] = []
            if metadata.get("author"):
                context_lines.append(f"> 作者：{metadata['author']}")
            if metadata.get("published_at"):
                context_lines.append(f"> 发布日期：{metadata['published_at']}")
            capture_note = next(
                (
                    line.removeprefix("- 抓取说明：")
                    for line in snapshot_lines[:separator]
                    if line.startswith("- 抓取说明：")
                ),
                "",
            )
            if capture_note:
                context_lines.append(f"> 抓取说明：{capture_note}")
            separator_lines = [""] if context_lines else []
            snapshot_content = "\n".join(
                [*context_lines, *separator_lines, *article_lines]
            )
    snapshot_content = normalize_snapshot(snapshot_content)
    digest = snapshot_hash(snapshot_content)
    metadata["snapshot_sha256"] = digest

    legacy_start = note.find(_LEGACY_NOTE_START)
    legacy_end = note.find(_LEGACY_NOTE_END, legacy_start)
    if legacy_start >= 0 or legacy_end >= 0:
        if legacy_start < 0 or legacy_end < 0:
            raise IntegrityError("旧版来源中间笔记标记不完整")
        legacy_content = note[
            legacy_start + len(_LEGACY_NOTE_START):legacy_end
        ].strip()
        if legacy_content and legacy_content != _LEGACY_NOTE_PLACEHOLDER:
            raise IntegrityError(
                "旧版来源中间笔记含有实际内容；请先由用户决定是否迁移为闪念"
            )

    heading = re.search(r"(?m)^## 关联闪念\s*$", note)
    if not heading:
        raise IntegrityError("来源缺少关联闪念区域")
    link_start = heading.end()
    next_heading = re.search(r"(?m)^## ", note[link_start:])
    link_end = link_start + next_heading.start() if next_heading else len(note)
    links = note[link_start:link_end].strip() or "_暂无_"
    return (
        dump_frontmatter(metadata)
        + f"# {metadata['title']}\n\n"
        + "## 原文快照\n\n"
        + f"<!-- goodidea:snapshot:start sha256={digest} -->\n"
        + snapshot_content
        + f"{SNAPSHOT_END}\n\n"
        + "## 关联闪念\n\n"
        + links
        + "\n"
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


def replace_section(note: str, heading: str, content: str) -> str:
    marker = f"## {heading}\n"
    position = note.find(marker)
    replacement = f"## {heading}\n\n{content.strip()}\n"
    if position < 0:
        return note.rstrip() + "\n\n" + replacement
    next_heading = note.find("\n## ", position + len(marker))
    if next_heading < 0:
        next_heading = len(note)
    return note[:position] + replacement + note[next_heading:]


def remove_section(note: str, heading: str) -> str:
    marker = f"## {heading}\n"
    position = note.find(marker)
    if position < 0:
        return note
    next_heading = note.find("\n## ", position + len(marker))
    if next_heading < 0:
        return note[:position].rstrip() + "\n"
    return note[:position].rstrip() + "\n\n" + note[next_heading + 1 :]


def render_source_anchors(
    anchors: list[tuple[str, str]], *, boundary: str = ""
) -> str:
    lines = [f"- {link}：{explanation.strip()}" for link, explanation in anchors]
    if boundary.strip():
        lines.extend(["", f"边界说明：{boundary.strip()}"])
    return "\n".join(lines)


def render_note(
    metadata: dict[str, Any], sections: list[tuple[str, str]]
) -> str:
    body = [dump_frontmatter(metadata), f"# {metadata['title']}\n"]
    for heading, content in sections:
        body.append(f"\n## {heading}\n\n{content.strip()}\n")
    return "".join(body)


def render_flash_event(metadata: dict[str, Any], event: dict[str, Any]) -> str:
    sections: list[tuple[str, str]] = []
    if event.get("trigger_anchor"):
        sections.append(("触发情境", str(event["trigger_anchor"])))
    sections.append(("闪念内容", str(event["body"])))
    if event.get("activated_logic"):
        sections.append(("激活逻辑", str(event["activated_logic"])))
    if event.get("source_anchors"):
        sections.append(("来源与论证锚点", "_来源链接将在后台维护完成后补入。_"))
    elif event.get("source_anchor"):
        sections.append(("来源与论证锚点", str(event["source_anchor"])))
    return render_note(metadata, sections)


def validate_required_metadata(metadata: dict[str, Any]) -> list[str]:
    required = ("id", "type", "title", "status", "created_at", "updated_at")
    return [key for key in required if not metadata.get(key)]


def safe_filename(title: str, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|#\[\]]+', "-", title.strip())
    cleaned = re.sub(r"\s+", "-", cleaned).strip("-.")
    cleaned = cleaned[:64] or fallback
    while len(cleaned.encode("utf-8")) > 180:
        cleaned = cleaned[:-1]
    return cleaned.strip("-.") or fallback


def dated_filename(title: str, created_at: str, *, collision: int = 1) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", created_at.strip())
    if not match:
        raise ValidationError("创建时间无法生成 YYYY-MM-DD 文件名前缀")
    readable_title = safe_filename(title, "未命名")
    suffix = "" if collision == 1 else f"-{collision}"
    return f"{match.group(1)}-{readable_title}{suffix}.md"


def wiki_link(path: Path, title: str) -> str:
    return f"[[{path.as_posix()[:-3]}|{title}]]"
