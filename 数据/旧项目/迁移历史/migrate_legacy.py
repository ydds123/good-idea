#!/usr/bin/env python3
"""旧 Goodidea 数据的首批语义试迁工具。

只读取 ../good-idea 冻结库；显式选择四类各 10 条，生成完整迁移清单，
并在 --apply 时写入新数据层。脚本拒绝覆盖既有正式记录。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

TARGET_ROOT = Path(__file__).resolve().parents[2]
LEGACY_ROOT = (TARGET_ROOT / "../good-idea").resolve()
FREEZE_COMMIT = "9489f308f82bcc9896c11156aba673fdf5cabc8c"
MIGRATION_ID = "MIG-20260925-001"
MIGRATION_DATE = "2026-09-25"
MANIFEST_REL = Path("数据/系统/操作事件") / f"{MIGRATION_ID}.json"

TYPE_CONFIG = {
    "有意思": {"prefix": "INT", "directory": "有意思"},
    "闪念": {"prefix": "FLA", "directory": "闪念"},
    "永久认识": {"prefix": "INS", "directory": "永久认识"},
    "外部来源": {"prefix": "SRC", "directory": "外部来源"},
}

SELECTED = {
    "有意思": [
        "有意思空间/2026-08-10-《无期迷途》游戏美术风格：AI人像创作的参考方向.md",
        "有意思空间/2026-08-11-Logseq-的时间旅行和图谱设计对-Goodidea-有帮助：时间旅行=回滚的.md",
        "有意思空间/2026-08-11-高级概念海报生成提示词（词义→视觉隐喻）.md",
        "有意思空间/2026-08-13-炒饭会196期演示的行业分析工作台（Web-Coding-开发）：输入行业→细分.md",
        "有意思空间/2026-08-25-球球Token-AI-中转站（生图-API-来源候选）.md",
        "有意思空间/2026-08-25-拆开-DeepSeek-Harness（dsh.papertok.ai-交互式教程）.md",
        "有意思空间/2026-08-28-Lux3D：AI-3D-生成模型.md",
        "有意思空间/2026-08-31-WikiSkill与现有skill结合实现可进化.md",
        "有意思空间/2026-08-31-Dify全新Agent体验：独立生命周期与能力模块化.md",
        "有意思空间/2026-09-04-PMFrame.works：100-个产品设计框架库.md",
    ],
    "闪念": [
        "闪念空间/已处理/2026-08-09-以控制论为底座，研究如何让-AI-生成超越平庸.md",
        "闪念空间/已处理/2026-08-09-闪念卡片记录的不是孤立要点，而是一次认知激活事件.md",
        "闪念空间/已处理/2026-08-09-主体性：找到自己想做的事，而不是为别人做事.md",
        "闪念空间/已处理/2026-08-10-母题级课题：AI图像-摄影与视觉叙事的-skill-化.md",
        "闪念空间/已处理/2026-08-10-《人生脚本》：主体性是产物，人生脚本是观察维度.md",
        "闪念空间/已处理/2026-08-11-普通永久卡片标准是最小任务调用循环的前置条件.md",
        "闪念空间/发酵中/2026-08-12-打字其实并不是一个很自然的人机交互动作——打字更多是为了适应机器，而不是人的想法.md",
        "闪念空间/已处理/2026-08-13-①企业AI转型四阶段（工具散点期-试点治理期-流程重构期-AI原生期）可联系昨天.md",
        "闪念空间/2026-09-20-时间并不归自己所有：有所有权，没有使用权.md",
        "闪念空间/已放弃/2026-08-18-人生脚本解释为何，主体性自有参照系.md",
    ],
    "永久认识": [
        "永久空间/永久卡片/2026-08-11-以-AI-生图为实践抓手理解控制论与科学方法论，是提升驾驭-AI-素养的研究路径之一.md",
        "永久空间/永久卡片/2026-08-11-人与-AI-协作的本质：把-AI-当作共同创作对象，而非执行工具.md",
        "永久空间/永久卡片/2026-08-12-闪念卡片记录的不是孤立要点，而是一次认知激活事件.md",
        "永久空间/永久卡片/2026-08-12-普通永久卡片标准是最小任务调用循环的前置条件.md",
        "永久空间/永久卡片/2026-08-13-判断力不靠熬年头，靠主动催化.md",
        "永久空间/永久卡片/2026-08-13-职业规划已失效：行业选择是长出来的.md",
        "永久空间/永久卡片/2026-08-13-企业AI转型四阶段：理解AI入企的分析积木.md",
        "永久空间/永久卡片/2026-08-13-主体性：行为原因的自我归属.md",
        "永久空间/永久卡片/2026-08-16-AI-产业价值流架构：八层一条链，治理横贯.md",
        "永久空间/永久卡片/2026-08-20-母题级课题：AI-图像-摄影与视觉叙事的-skill-化.md",
    ],
    "外部来源": [
        "溯源空间/2026-08-12-2026中国企业级AI-Agent发展洞察报告.md",
        "溯源空间/2026-08-16-北京智能体新政-解读.md",
        "溯源空间/2026-08-13-阅读素材：曾鸣《智能商业》（第一章AI产业化的展开+第二章智能复利和黑洞效应）.md",
        "溯源空间/2026-08-09-8-月-9-日-可能性空间讨论.md",
        "溯源空间/2026-08-13-广义认知行动系统分析.md",
        "溯源空间/2026-08-16-2026-WAIC参展企业MECE分层全景-v7（主流玩家补全版）.md",
        "溯源空间/2026-08-09-来了！热狗GPT作图心法大公开！.md",
        "溯源空间/2026-08-09-控制论与科学方法论.md",
        "溯源空间/2026-08-13-AI时代职场自救法则：消失的入门梯子与用AI搭建学习路径.md",
        "溯源空间/2026-08-11-对话李继刚：让AI超越平庸表现｜读完周报再来聊聊闭门会第5期精华.md",
    ],
}

REMOVED_FIELDS = [
    "type",
    "title",
    "updated_at",
    "source_ids",
    "derived_from",
    "authoring_mode",
    "formation_draft_sha256",
    "capture_session",
    "discussion_log",
]


@dataclass
class LegacyRecord:
    kind: str
    path: Path
    rel: str
    meta: dict[str, Any]
    body: str
    sha256: str
    selected: bool = False
    target_id: str = ""
    target_rel: str = ""
    target_status: str | None = None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def json_value(raw: str) -> Any:
    raw = raw.strip()
    if raw == "":
        return ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Frontmatter 值不是 JSON-compatible YAML: {raw[:120]}") from exc


def parse_markdown(text: str) -> tuple[dict[str, Any], str]:
    match = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not match:
        raise ValueError("缺少 Frontmatter")
    meta: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"无法解析 Frontmatter 行: {line}")
        key, raw = line.split(":", 1)
        meta[key.strip()] = json_value(raw)
    return meta, text[match.end() :]


def dump_markdown(meta: dict[str, Any], body: str) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, (str, list, dict)):
            encoded = json.dumps(value, ensure_ascii=False)
        elif value is None:
            encoded = '""'
        else:
            encoded = json.dumps(value, ensure_ascii=False)
        lines.append(f"{key}: {encoded}")
    lines.extend(["---", body.strip(), ""])
    return "\n".join(lines)


def strip_h1(body: str) -> str:
    lines = body.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def safe_title(title: str) -> str:
    title = re.sub(r"[\r\n\t]+", " ", title).strip()
    return title.replace("/", "／")


def plain_wikilinks(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        value = match.group(1)
        if "|" in value:
            return f"《{value.rsplit('|', 1)[1]}》"
        return f"《{Path(value).name}》"

    return re.sub(r"\[\[([^\]]+)\]\]", repl, text)


def replace_role_labels(text: str) -> str:
    return text.replace("用户表达", "松海表达").replace("用户确认", "松海确认")


def demote_headings(text: str, levels: int) -> str:
    def repl(match: re.Match[str]) -> str:
        hashes = match.group(1)
        return "#" * min(6, len(hashes) + levels) + " "

    return re.sub(r"(?m)^(#{2,5})\s+", repl, text)


def remove_sections(text: str, names: set[str]) -> tuple[str, dict[str, str]]:
    pattern = re.compile(r"(?m)^##\s+(.+?)\s*$")
    matches = list(pattern.finditer(text))
    removed: dict[str, str] = {}
    keep: list[str] = []
    cursor = 0
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = match.group(1).strip()
        keep.append(text[cursor:start])
        if title in names:
            removed[title] = text[match.end() : end].strip()
        else:
            keep.append(text[start:end])
        cursor = end
    keep.append(text[cursor:])
    return "".join(keep).strip(), removed


def created_date(record: LegacyRecord) -> str:
    value = str(record.meta.get("created_at") or "")
    match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    if not match:
        match = re.match(r"(\d{4}-\d{2}-\d{2})", Path(record.rel).name)
    if not match:
        raise ValueError(f"无法确定日期: {record.rel}")
    return match.group(1)


def load_record(kind: str, path: Path, selected: set[str]) -> LegacyRecord:
    text = path.read_text(encoding="utf-8")
    meta, body = parse_markdown(text)
    rel = path.relative_to(LEGACY_ROOT).as_posix()
    return LegacyRecord(
        kind=kind,
        path=path,
        rel=rel,
        meta=meta,
        body=body,
        sha256=sha256_bytes(text.encode("utf-8")),
        selected=rel in selected,
    )


def collect_records() -> dict[str, list[LegacyRecord]]:
    selected = {kind: set(paths) for kind, paths in SELECTED.items()}
    records: dict[str, list[LegacyRecord]] = {
        "有意思": [load_record("有意思", p, selected["有意思"]) for p in sorted((LEGACY_ROOT / "有意思空间").glob("*.md"))],
        "闪念": [load_record("闪念", p, selected["闪念"]) for p in sorted((LEGACY_ROOT / "闪念空间").rglob("*.md"))],
        "永久认识": [load_record("永久认识", p, selected["永久认识"]) for p in sorted((LEGACY_ROOT / "永久空间/永久卡片").glob("*.md"))],
    }

    source_ids: set[str] = set()
    for kind in ("有意思", "闪念", "永久认识"):
        for record in records[kind]:
            source_ids.update(str(item) for item in record.meta.get("source_ids", []) if str(item).startswith("SRC-"))
            source_ids.update(str(item) for item in record.meta.get("derived_from", []) if str(item).startswith("SRC-"))

    source_by_id: dict[str, LegacyRecord] = {}
    for path in sorted((LEGACY_ROOT / "溯源空间").glob("*.md")):
        record = load_record("外部来源", path, selected["外部来源"])
        legacy_id = str(record.meta.get("id") or "")
        if legacy_id in source_ids:
            source_by_id[legacy_id] = record
    missing = source_ids - set(source_by_id)
    if missing:
        raise ValueError(f"缺少来源文件: {sorted(missing)}")
    records["外部来源"] = list(source_by_id.values())

    expected = {"有意思": 13, "闪念": 29, "永久认识": 21, "外部来源": 17}
    actual = {kind: len(items) for kind, items in records.items()}
    if actual != expected:
        raise ValueError(f"旧数据数量与审计基线不符: {actual} != {expected}")
    for kind, paths in selected.items():
        located = {record.rel for record in records[kind] if record.selected}
        if located != paths:
            raise ValueError(f"{kind} 选择清单无法定位: missing={sorted(paths-located)}, extra={sorted(located-paths)}")
        if len(located) != 10:
            raise ValueError(f"{kind} 试迁数量不是 10: {len(located)}")
    return records


def assign_targets(records: dict[str, list[LegacyRecord]]) -> tuple[dict[str, LegacyRecord], dict[str, list[LegacyRecord]]]:
    by_old_id: dict[str, LegacyRecord] = {}
    insights_by_flash: dict[str, list[LegacyRecord]] = defaultdict(list)
    for insight in records["永久认识"]:
        for dep in insight.meta.get("derived_from", []):
            if str(dep).startswith("FLA-"):
                insights_by_flash[str(dep)].append(insight)

    for kind, items in records.items():
        config = TYPE_CONFIG[kind]
        by_date: dict[str, list[LegacyRecord]] = defaultdict(list)
        for record in items:
            by_date[created_date(record)].append(record)
        for date, dated in by_date.items():
            dated.sort(key=lambda item: (str(item.meta.get("created_at") or ""), str(item.meta.get("id") or ""), item.rel))
            for seq, record in enumerate(dated, 1):
                compact = date.replace("-", "")
                record.target_id = f"{config['prefix']}-{compact}-{seq:03d}"
                filename = f"{date}-{seq:03d}-{safe_title(str(record.meta.get('title') or Path(record.rel).stem))}.md"
                record.target_rel = (Path("数据/记录") / config["directory"] / filename).as_posix()
                legacy_id = str(record.meta.get("id") or "")
                if not legacy_id or legacy_id in by_old_id:
                    raise ValueError(f"旧 ID 缺失或重复: {legacy_id} ({record.rel})")
                by_old_id[legacy_id] = record

    for record in records["有意思"]:
        record.target_status = "待处理"
    for record in records["永久认识"]:
        record.target_status = "有效" if record.meta.get("status") in {"有效", "已修订"} else "已停用"
    source_status = {
        "完整": "完整",
        "部分抓取": "部分获取",
        "部分获取": "部分获取",
        "抓取失败": "获取失败",
        "获取失败": "获取失败",
        "待抓取": "待获取",
        "待获取": "待获取",
        "待确认身份": "待确认身份",
    }
    for record in records["外部来源"]:
        old = str(record.meta.get("status") or record.meta.get("capture_status") or "待确认身份")
        if old not in source_status:
            raise ValueError(f"未知来源状态 {old}: {record.rel}")
        record.target_status = source_status[old]
    flash_status = {"待处理": "待处理", "发酵中": "发酵中", "已放弃": "已放弃"}
    for record in records["闪念"]:
        old = str(record.meta.get("status") or "")
        if old == "已处理" and str(record.meta.get("id")) in insights_by_flash:
            record.target_status = "已形成认识"
        elif old in flash_status:
            record.target_status = flash_status[old]
        else:
            record.target_status = None
        if record.selected and record.target_status is None:
            raise ValueError(f"选中闪念需要松海先裁决状态: {record.rel}")
    return by_old_id, insights_by_flash


def relation_line(dep: LegacyRecord, from_kind: str) -> str:
    title = str(dep.meta.get("title") or Path(dep.rel).stem)
    if from_kind == "永久认识" and dep.kind == "闪念":
        rel = Path("../闪念") / Path(dep.target_rel).name
        return f"- `{dep.target_id}` — [[{rel.as_posix()}|{title}]]"
    if dep.kind == "外部来源":
        rel = Path("../外部来源") / Path(dep.target_rel).name
        return f"- `{dep.target_id}#snapshot-1` — [[{rel.as_posix()}#snapshot-1|{title}]]"
    return f"- `{dep.target_id}` — {title}"


def dependency_records(record: LegacyRecord, by_old_id: dict[str, LegacyRecord]) -> list[LegacyRecord]:
    result: list[LegacyRecord] = []
    for key in ("source_ids", "derived_from"):
        for legacy_id in record.meta.get(key, []):
            dep = by_old_id.get(str(legacy_id))
            if dep and dep not in result:
                result.append(dep)
    return result


def transform_interesting(record: LegacyRecord) -> str:
    content = strip_h1(record.body)
    content = content.replace("## 原始记录", "## 保存内容").replace("## 产生情境", "## 保存动机")
    content = replace_role_labels(plain_wikilinks(content))
    created = str(record.meta.get("created_at") or "")[:16].replace("T", " ")
    content += f"\n\n## 处理历史\n\n- {created}：旧项目保存为有意思，状态为 `待处理`。\n- {MIGRATION_DATE}：按新对象契约迁入，状态保持 `待处理`。"
    meta = {"id": record.target_id, "status": "待处理", "created_at": record.meta.get("created_at")}
    title = str(record.meta.get("title"))
    return dump_markdown(meta, f"# {title}\n\n{content}")


def transform_flash(
    record: LegacyRecord,
    by_old_id: dict[str, LegacyRecord],
    insights_by_flash: dict[str, list[LegacyRecord]],
) -> str:
    content = strip_h1(record.body)
    content = content.replace("## 闪念内容", "## 核心内容").replace("## 原始记录", "## 核心内容")
    content = content.replace("## 来源与论证锚点", "## 材料与论证锚点（旧项目迁入）")
    content = replace_role_labels(plain_wikilinks(content))
    content, _ = remove_sections(content, {"讨论记录"})
    deps = [dep for dep in dependency_records(record, by_old_id) if dep.selected and dep.kind == "外部来源"]
    formed_from = [f"{dep.target_id}#snapshot-1" for dep in deps]
    meta = {
        "id": record.target_id,
        "status": record.target_status,
        "claimed_at": record.meta.get("created_at"),
        "freshness_window": "",
        "window_ends_at": "",
        "formed_from": formed_from,
    }
    old_status = str(record.meta.get("status") or "")
    history = [f"- {MIGRATION_DATE}：从旧项目语义迁入；旧状态 `{old_status}` 转为 `{record.target_status}`。"]
    if record.target_status == "待处理":
        history.append("- 本条属于历史迁入的待处理闪念，不追溯执行 48 小时保鲜期限。")
    if record.target_status == "已形成认识":
        targets = [item for item in insights_by_flash.get(str(record.meta.get("id")), []) if item.selected]
        history.extend(f"- 已参与形成 `{item.target_id}`：{item.meta.get('title')}。" for item in targets)
    content += "\n\n## 状态历史\n\n" + "\n".join(history)
    title = str(record.meta.get("title"))
    return dump_markdown(meta, f"# {title}\n\n{content}")


def git_version_events(record: LegacyRecord) -> list[tuple[str, str, str, str]]:
    command = ["git", "log", "--follow", "--format=%H%x09%cI%x09%s", "--", record.rel]
    raw = subprocess.run(command, cwd=LEGACY_ROOT, check=True, text=True, capture_output=True).stdout
    events: list[tuple[str, str, str, str]] = []
    for line in reversed(raw.splitlines()):
        commit, when, subject = line.split("\t", 2)
        if not (subject.startswith("permanent-accept:") or subject.startswith("permanent-revise:")):
            continue
        shown = subprocess.run(
            ["git", "show", f"{commit}:{record.rel}"],
            cwd=LEGACY_ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout
        _, body = parse_markdown(shown)
        events.append((commit, when, subject, body))
    if not events:
        events.append((FREEZE_COMMIT, str(record.meta.get("created_at")), "旧项目冻结版本", record.body))
    return events


def semantic_insight_body(body: str) -> tuple[str, str]:
    content = strip_h1(body)
    content, removed = remove_sections(content, {"形成来源", "连接", "讨论记录"})
    content = replace_role_labels(plain_wikilinks(content))
    connection = replace_role_labels(plain_wikilinks(removed.get("连接", "")))
    return content.strip(), connection.strip()


def formation_lines(record: LegacyRecord, by_old_id: dict[str, LegacyRecord]) -> list[str]:
    lines: list[str] = []
    for dep in dependency_records(record, by_old_id):
        if dep.selected:
            lines.append(relation_line(dep, "永久认识"))
        else:
            lines.append(f"- 历史依赖 `{dep.target_id}` 尚未纳入首批试迁：{dep.meta.get('title')}。")
    return lines or ["- 历史迁入对象；旧项目没有可转换为当前正式对象的显式形成依据。"]


def transform_insight(record: LegacyRecord, by_old_id: dict[str, LegacyRecord]) -> str:
    events = git_version_events(record)
    current_core, current_connection = semantic_insight_body(record.body)
    formation = formation_lines(record, by_old_id)
    current = demote_headings(current_core, 1)
    current += "\n\n### 形成依据\n\n" + "\n".join(formation)
    if current_connection:
        current += "\n\n### 延伸关系（旧项目迁入）\n\n" + current_connection

    versions: list[str] = []
    seen_hashes: set[str] = set()
    version_number = 0
    for commit, when, subject, body in events:
        core, _ = semantic_insight_body(body)
        digest = sha256_bytes(core.encode("utf-8"))
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        version_number += 1
        action = "旧项目认领" if subject.startswith("permanent-accept:") else "旧项目修订"
        versions.append(
            f"### v{version_number}｜{when[:16].replace('T', ' ')}｜{action}\n\n"
            f"<!-- legacy-commit: {commit} -->\n\n"
            f"{demote_headings(core, 2)}\n\n"
            f"#### 形成依据\n\n" + "\n".join(formation)
        )
    expected_revised = record.meta.get("status") == "已修订"
    if expected_revised and version_number < 2:
        raise ValueError(f"已修订永久认识没有恢复出多个版本: {record.rel}")
    meta = {
        "id": record.target_id,
        "status": "有效",
        "created_at": record.meta.get("created_at"),
        "current_version": version_number,
    }
    title = str(record.meta.get("title"))
    body = f"# {title}\n\n## 当前版本\n\n{current}\n\n## 版本历史\n\n" + "\n\n".join(versions)
    return dump_markdown(meta, body)


def source_snapshot(record: LegacyRecord) -> str:
    body = strip_h1(record.body)
    start_marker = re.search(r"<!--\s*goodidea:snapshot:start[^>]*-->", body)
    end_marker = re.search(r"<!--\s*goodidea:snapshot:end\s*-->", body)
    if start_marker and end_marker and end_marker.start() >= start_marker.end():
        return body[start_marker.end() : end_marker.start()].strip()
    heading = re.search(r"(?m)^##\s+原文快照\s*$", body)
    if heading:
        remainder = body[heading.end() :]
        next_heading = re.search(r"(?m)^##\s+关联闪念\s*$", remainder)
        if next_heading:
            remainder = remainder[: next_heading.start()]
        return remainder.strip()
    return body.strip()


def source_asset_refs(record: LegacyRecord) -> list[tuple[str, Path]]:
    refs: list[tuple[str, Path]] = []
    for ref in re.findall(r"!\[[^\]]*\]\(([^)\n]+)\)", source_snapshot(record)):
        if re.match(r"^[a-z]+://", ref):
            continue
        resolved = (record.path.parent / ref).resolve()
        if resolved.is_file() and resolved.is_relative_to(LEGACY_ROOT):
            refs.append((ref, resolved))
    return refs


def build_asset_map(records: dict[str, list[LegacyRecord]]) -> tuple[dict[Path, str], list[dict[str, Any]]]:
    by_path: dict[Path, str] = {}
    entries_by_hash: dict[str, dict[str, Any]] = {}
    for source in records["外部来源"]:
        for old_ref, legacy_path in source_asset_refs(source):
            digest = sha256_file(legacy_path)
            target_name = f"{digest}{legacy_path.suffix.lower()}"
            by_path[legacy_path] = target_name
            entry = entries_by_hash.setdefault(
                digest,
                {
                    "legacy_paths": [],
                    "legacy_sha256": digest,
                    "target_path": f"数据/资产/{target_name}",
                    "referenced_by": [],
                    "selected": False,
                    "action": "暂缓",
                    "validation": "未执行",
                },
            )
            legacy_rel = legacy_path.relative_to(LEGACY_ROOT).as_posix()
            if legacy_rel not in entry["legacy_paths"]:
                entry["legacy_paths"].append(legacy_rel)
            if source.rel not in entry["referenced_by"]:
                entry["referenced_by"].append(source.rel)
            if source.selected:
                entry["selected"] = True
                entry["action"] = "迁入"
                entry["validation"] = "待验证"
    entries = sorted(entries_by_hash.values(), key=lambda item: item["target_path"])
    return by_path, entries


def rewrite_snapshot_assets(record: LegacyRecord, snapshot: str, asset_map: dict[Path, str]) -> tuple[str, dict[str, str]]:
    rewrites: dict[str, str] = {}
    for old_ref, legacy_path in source_asset_refs(record):
        target_name = asset_map[legacy_path]
        new_ref = f"../../资产/{target_name}"
        snapshot = snapshot.replace(f"]({old_ref})", f"]({new_ref})")
        rewrites[old_ref] = new_ref
    return snapshot, rewrites


def transform_source(record: LegacyRecord, asset_map: dict[Path, str]) -> tuple[str, dict[str, str], str, str]:
    snapshot_original = source_snapshot(record)
    snapshot, rewrites = rewrite_snapshot_assets(record, snapshot_original, asset_map)
    canonical = str(record.meta.get("canonical_url") or record.meta.get("origin_filename") or record.meta.get("title"))
    material_type = "网页" if record.meta.get("canonical_url") else ("文件" if record.meta.get("origin_filename") else "文本")
    created = str(record.meta.get("created_at") or "")
    fetched = str(record.meta.get("fetched_at") or created)
    status = str(record.target_status)
    method = "旧项目完整快照迁入" if status == "完整" else "旧项目已有快照迁入"
    original_ref = str(record.meta.get("canonical_url") or record.meta.get("origin_filename") or "旧项目来源记录")
    title = str(record.meta.get("title"))
    body = (
        f"# {title}\n\n"
        "## 原始引用\n\n"
        f"- {created[:16].replace('T', ' ')}｜带入者：松海｜出现位置：旧项目历史记录\n"
        f"  - 原始引用：{original_ref}\n\n"
        "## 身份与别名\n\n"
        f"- 规范身份：{canonical}\n"
        f"- 已知别名：{title}\n\n"
        "## 快照\n\n"
        f"### snapshot-1｜{fetched[:16].replace('T', ' ')}｜{status}\n\n"
        f"- 获取方式：{method}\n"
        "- 内容位置或正文：见下方完整快照。\n\n"
        f"{snapshot}\n\n"
        "> 本记录只说明外部材料说过什么，不代表松海赞同或吸收。"
    )
    meta = {
        "id": record.target_id,
        "status": status,
        "created_at": created,
        "canonical_identity": canonical,
        "material_type": material_type,
    }
    return (
        dump_markdown(meta, body),
        rewrites,
        sha256_bytes(snapshot_original.encode("utf-8")),
        sha256_bytes(snapshot.encode("utf-8")),
    )


def manifest_object(
    record: LegacyRecord,
    by_old_id: dict[str, LegacyRecord],
    rendered: str | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    deps = []
    for dep in dependency_records(record, by_old_id):
        deps.append(
            {
                "legacy_id": dep.meta.get("id"),
                "target_id": dep.target_id,
                "target_type": dep.kind,
                "selected_in_batch": dep.selected,
            }
        )
    action = "迁入" if record.selected else "暂缓"
    entry: dict[str, Any] = {
        "legacy_path": record.rel,
        "legacy_id": record.meta.get("id"),
        "legacy_sha256": record.sha256,
        "selected": record.selected,
        "action": action,
        "copy_mode": "复制后结构转换" if record.selected else "暂缓",
        "target_type": record.kind,
        "target_id": record.target_id,
        "target_path": record.target_rel,
        "status_mapping": f"{record.meta.get('status', '')} → {record.target_status or '待裁决'}",
        "removed_fields": [field for field in REMOVED_FIELDS if field in record.meta],
        "dependencies": deps,
        "decision": "按已确认自动规则迁入" if record.selected else ("状态需松海裁决" if record.target_status is None else "不在首批 10 条内"),
        "validation": "待验证" if record.selected else "未执行",
    }
    if rendered is not None:
        entry["target_sha256"] = sha256_bytes(rendered.encode("utf-8"))
    if extra:
        entry.update(extra)
    return entry


def render_selected(
    records: dict[str, list[LegacyRecord]],
    by_old_id: dict[str, LegacyRecord],
    insights_by_flash: dict[str, list[LegacyRecord]],
    asset_map: dict[Path, str],
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    rendered: dict[str, str] = {}
    extras: dict[str, dict[str, Any]] = {}
    for record in records["有意思"]:
        if record.selected:
            rendered[record.target_rel] = transform_interesting(record)
    for record in records["闪念"]:
        if record.selected:
            rendered[record.target_rel] = transform_flash(record, by_old_id, insights_by_flash)
    for record in records["永久认识"]:
        if record.selected:
            rendered[record.target_rel] = transform_insight(record, by_old_id)
    for record in records["外部来源"]:
        if record.selected:
            text, rewrites, original_hash, target_hash = transform_source(record, asset_map)
            rendered[record.target_rel] = text
            extras[record.rel] = {
                "snapshot_original_sha256": original_hash,
                "snapshot_target_sha256": target_hash,
                "asset_rewrites": rewrites,
            }
    return rendered, extras


def current_old_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=LEGACY_ROOT, check=True, text=True, capture_output=True).stdout.strip()


def build_manifest(
    records: dict[str, list[LegacyRecord]],
    by_old_id: dict[str, LegacyRecord],
    rendered: dict[str, str],
    extras: dict[str, dict[str, Any]],
    asset_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    for kind in ("有意思", "闪念", "永久认识", "外部来源"):
        for record in sorted(records[kind], key=lambda item: item.rel):
            objects.append(manifest_object(record, by_old_id, rendered.get(record.target_rel), extras.get(record.rel)))
    return {
        "migration_id": MIGRATION_ID,
        "phase": "四类对象各 10 条首批试迁",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "legacy_root": str(LEGACY_ROOT),
        "legacy_commit": current_old_commit(),
        "expected_freeze_commit": FREEZE_COMMIT,
        "selection_policy": "各类选择 10 条；闪念只选择状态可按现行契约确定的记录；新 ID 序号按各类全量旧记录计算，保证后续追加稳定。",
        "objects": objects,
        "assets": asset_entries,
        "summary": {
            "legacy_content_objects": sum(len(records[k]) for k in ("有意思", "闪念", "永久认识")),
            "legacy_sources": len(records["外部来源"]),
            "legacy_assets": len(asset_entries),
            "selected_by_type": {kind: sum(1 for item in records[kind] if item.selected) for kind in records},
            "selected_assets": sum(1 for item in asset_entries if item["selected"]),
        },
        "validation": {"status": "待验证", "checks": []},
    }


def validate_rendered(rendered: dict[str, str], manifest: dict[str, Any], target_root: Path, on_disk: bool) -> list[str]:
    errors: list[str] = []
    allowed_status = {
        "有意思": {"待处理", "已处理", "已放弃"},
        "闪念": {"待处理", "发酵中", "已放弃", "已失效", "已形成认识"},
        "永久认识": {"有效", "已停用"},
        "外部来源": {"待确认身份", "待获取", "完整", "部分获取", "获取失败"},
    }
    expected_prefix = {kind: cfg["prefix"] for kind, cfg in TYPE_CONFIG.items()}
    id_seen: set[str] = set()
    file_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{3}-.+\.md$")
    entry_by_path = {entry["target_path"]: entry for entry in manifest["objects"] if entry["selected"]}
    for rel, expected_text in rendered.items():
        text = (target_root / rel).read_text(encoding="utf-8") if on_disk else expected_text
        entry = entry_by_path[rel]
        try:
            meta, body = parse_markdown(text)
        except Exception as exc:
            errors.append(f"{rel}: {exc}")
            continue
        kind = entry["target_type"]
        if meta.get("status") not in allowed_status[kind]:
            errors.append(f"{rel}: 非法中文状态 {meta.get('status')}")
        if not str(meta.get("id", "")).startswith(expected_prefix[kind] + "-"):
            errors.append(f"{rel}: ID 类型不匹配 {meta.get('id')}")
        if meta.get("id") in id_seen:
            errors.append(f"{rel}: ID 重复 {meta.get('id')}")
        id_seen.add(str(meta.get("id")))
        if not file_pattern.match(Path(rel).name):
            errors.append(f"{rel}: 文件名不符合日期-序号-标题")
        if re.match(r"^(SES|INT|FLA|INS|SRC)-", Path(rel).name):
            errors.append(f"{rel}: 文件名含类型前缀")
        forbidden = set(meta) & set(REMOVED_FIELDS)
        if forbidden:
            errors.append(f"{rel}: 残留旧字段 {sorted(forbidden)}")
        if "/Users/" in text or str(LEGACY_ROOT) in text:
            errors.append(f"{rel}: 正式内容含绝对路径")
        if body.count("# ") < 1:
            errors.append(f"{rel}: 缺少一级标题")
        if sha256_bytes(text.encode("utf-8")) != entry.get("target_sha256"):
            errors.append(f"{rel}: 目标哈希与清单不一致")
        for asset_ref in re.findall(r"!\[[^\]]*\]\((\.\./\.\./资产/[^)]+)\)", text):
            resolved = (target_root / rel).parent.joinpath(asset_ref).resolve()
            if not resolved.is_file() and on_disk:
                errors.append(f"{rel}: 图片引用无法解析 {asset_ref}")
    counts = defaultdict(int)
    for entry in entry_by_path.values():
        counts[entry["target_type"]] += 1
    if dict(counts) != {"有意思": 10, "闪念": 10, "永久认识": 10, "外部来源": 10}:
        errors.append(f"试迁数量不正确: {dict(counts)}")
    if any("原始思考会话" in rel for rel in rendered):
        errors.append("首批试迁不应创建原始思考会话")
    return errors


def apply(
    rendered: dict[str, str],
    manifest: dict[str, Any],
    asset_map: dict[Path, str],
    records: dict[str, list[LegacyRecord]],
) -> None:
    created: list[Path] = []
    manifest_path = TARGET_ROOT / MANIFEST_REL
    selected_asset_paths = {
        legacy_path
        for source in records["外部来源"]
        if source.selected
        for _, legacy_path in source_asset_refs(source)
    }
    targets = [TARGET_ROOT / rel for rel in rendered]
    asset_targets = [TARGET_ROOT / "数据/资产" / asset_map[path] for path in selected_asset_paths]
    existing = [str(path) for path in [manifest_path, *targets, *asset_targets] if path.exists()]
    if existing:
        raise FileExistsError("拒绝覆盖既有迁移产物:\n" + "\n".join(existing))
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        created.append(manifest_path)
        for rel, text in rendered.items():
            path = TARGET_ROOT / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            created.append(path)
        for legacy_path in sorted(selected_asset_paths):
            target = TARGET_ROOT / "数据/资产" / asset_map[legacy_path]
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copyfile(legacy_path, target)
                created.append(target)
            if sha256_file(target) != sha256_file(legacy_path):
                raise ValueError(f"资产复制哈希不一致: {legacy_path}")

        errors = validate_rendered(rendered, manifest, TARGET_ROOT, on_disk=True)
        for entry in manifest["objects"]:
            if entry["selected"]:
                legacy = LEGACY_ROOT / entry["legacy_path"]
                if sha256_file(legacy) != entry["legacy_sha256"]:
                    errors.append(f"旧输入在迁移期间发生变化: {entry['legacy_path']}")
                entry["validation"] = "已通过" if not errors else "失败"
        for entry in manifest["assets"]:
            if entry["selected"]:
                target = TARGET_ROOT / entry["target_path"]
                if not target.is_file() or sha256_file(target) != entry["legacy_sha256"]:
                    errors.append(f"资产验证失败: {entry['target_path']}")
                entry["validation"] = "已通过" if not errors else "失败"
        manifest["validation"] = {
            "status": "已通过" if not errors else "失败",
            "checks": [
                "四类对象各 10 条",
                "中文状态白名单",
                "日期-序号-标题文件名",
                "内部 ID 唯一且类型匹配",
                "旧字段与绝对路径清理",
                "正式内容哈希与迁移清单一致",
                "图片引用可解析且复制前后 SHA-256 一致",
                "旧输入文件哈希未变化",
                "未创建旧原始思考会话",
            ],
            "errors": errors,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if errors:
            raise ValueError("迁移验证失败:\n" + "\n".join(errors))
    except Exception:
        for path in reversed(created):
            if path.exists() and path.is_file():
                path.unlink()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="写入首批 40 条正式记录、引用资产和迁移清单")
    parser.add_argument("--verify", action="store_true", help="验证已经写入的首批迁移")
    args = parser.parse_args()

    if current_old_commit() != FREEZE_COMMIT:
        raise SystemExit("旧项目 HEAD 已偏离冻结提交，拒绝迁移")
    records = collect_records()
    by_old_id, insights_by_flash = assign_targets(records)
    asset_map, asset_entries = build_asset_map(records)
    rendered, extras = render_selected(records, by_old_id, insights_by_flash, asset_map)
    manifest = build_manifest(records, by_old_id, rendered, extras, asset_entries)

    dry_errors = validate_rendered(rendered, manifest, TARGET_ROOT, on_disk=False)
    if dry_errors:
        raise SystemExit("迁移前验证失败:\n" + "\n".join(dry_errors))
    if args.apply:
        apply(rendered, manifest, asset_map, records)
    elif args.verify:
        manifest_path = TARGET_ROOT / MANIFEST_REL
        if not manifest_path.is_file():
            raise SystemExit(f"迁移清单不存在: {manifest_path}")
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        errors = validate_rendered(rendered, saved, TARGET_ROOT, on_disk=True)
        if errors:
            raise SystemExit("已写入数据验证失败:\n" + "\n".join(errors))
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else ("verify" if args.verify else "dry-run"),
                "selected": manifest["summary"]["selected_by_type"],
                "selected_assets": manifest["summary"]["selected_assets"],
                "full_inventory": {
                    "content_objects": manifest["summary"]["legacy_content_objects"],
                    "sources": manifest["summary"]["legacy_sources"],
                    "assets": manifest["summary"]["legacy_assets"],
                },
                "manifest": MANIFEST_REL.as_posix(),
                "status": "passed",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
