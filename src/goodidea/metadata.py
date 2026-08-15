from __future__ import annotations

import json
import re
from typing import Any

from .contracts import localize_enums, normalize_enums
from .errors import ValidationError


FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)


def _parse_loose_scalar(raw: str) -> Any:
    """Frontmatter 值兼容 YAML 裸标量（Obsidian 插件写回时常给字符串脱引号）。

    不引入 PyYAML 运行依赖，手写覆盖常见标量：空、true/false/null（含大小写）、
    整数、浮点；其余一律按字符串原样返回。日期（2026-08-13T…）与 ID 等
    含字母/冒号/连字符的值不会被误判为数字。
    """
    value = raw.strip()
    if not value:
        return ""
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "~"):
        return None
    if re.fullmatch(r"[-+]?\d+", value):
        return int(value)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+)([eE][-+]?\d+)?", value):
        return float(value)
    return value


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
        except json.JSONDecodeError:
            stripped = raw_value.strip()
            if stripped[:1] in "[{":
                # 数组/对象必须是 JSON-compatible YAML，不静默降级
                raise ValidationError(
                    f"Frontmatter 字段 {key} 不是 JSON-compatible YAML"
                ) from None
            metadata[key] = _parse_loose_scalar(stripped)
    return normalize_enums(metadata), normalized[match.end():]


def replace_frontmatter(text: str, metadata: dict[str, Any]) -> str:
    _, body = parse_document(text)
    return dump_frontmatter(metadata) + body.lstrip("\n")
