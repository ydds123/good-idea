from __future__ import annotations

import json
import re
from typing import Any

from .contracts import localize_enums, normalize_enums
from .errors import ValidationError


FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)


def dump_frontmatter(metadata: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in localize_enums(metadata).items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise ValidationError(f"非法 Frontmatter 字段：{key}")
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def parse_document(text: str) -> tuple[dict[str, Any], str]:
    normalized = text.replace("\r\n", "\n")
    match = FRONTMATTER_RE.match(normalized)
    if not match:
        raise ValidationError("Markdown 缺少合法 Frontmatter")
    metadata: dict[str, Any] = {}
    for raw_line in match.group(1).splitlines():
        if not raw_line.strip():
            continue
        if ":" not in raw_line:
            raise ValidationError(f"无法解析 Frontmatter：{raw_line}")
        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        try:
            metadata[key] = json.loads(raw_value.strip())
        except json.JSONDecodeError as exc:
            raise ValidationError(
                f"Frontmatter 字段 {key} 不是 JSON-compatible YAML"
            ) from exc
    return normalize_enums(metadata), normalized[match.end():]


def replace_frontmatter(text: str, metadata: dict[str, Any]) -> str:
    _, body = parse_document(text)
    return dump_frontmatter(metadata) + body.lstrip("\n")
