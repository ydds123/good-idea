from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import Any


TRANSACTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SESSION_ID_PATTERN = re.compile(r"^CAP-[0-9]{8}-[0-9a-f]{8}$")
MAINTENANCE_JOB_ID_PATTERN = re.compile(r"^JOB-[0-9a-f]{12}$")
FORMATION_WITNESS_ID_PATTERN = re.compile(r"^WIT-[0-9a-f]{12}$")
FORMATION_WITNESS_ROOT = Path(".goodidea/formation-witnesses")
FLASH_EVENT_FORMAT_VERSION = 2

FLASH_STALE_AFTER = timedelta(hours=48)
# 待办 48h 行动窗口（2026-08-15 拍板）：未开始超 48h 未动 → 已过期（capture sweep）
TODO_STALE_AFTER = timedelta(hours=48)
CAPTURE_RECOVERY_WINDOW = timedelta(hours=24)
PERMANENT_CARD_TYPES = frozenset({"permanent", "mother", "action", "index"})

# 语义连接端点组合图（2026-08-20 拍板：闪念连接通道）
# 正式卡四类互通（现状保留）；闪念↔闪念、闪念↔来源（本轮新开放）；
# 正式卡↔闪念/来源、来源↔来源 暂无需求场景，不开放。
# 愿景：各种类型卡片都支持双向连接——以后放开组合只改此表，
# 校验逻辑（service.connect_propose）不感知具体组合；本图必须对称。
CONNECT_GRAPH: dict[str, frozenset[str]] = {
    "permanent": PERMANENT_CARD_TYPES,
    "mother": PERMANENT_CARD_TYPES,
    "action": PERMANENT_CARD_TYPES,
    "index": PERMANENT_CARD_TYPES,
    "flash": frozenset({"flash", "source"}),
    "source": frozenset({"flash"}),
}
CAPTURE_ACTIVE_STATES = frozenset({"active", "reviewing", "paused"})
MAINTENANCE_STATES = (
    "pending", "processing", "maintenance_paused", "retry_pending",
    "partial", "failed", "complete", "cancelled", "context_changed",
)

# ---------------------------------------------------------------------------
# 枚举值中文化（2026-08-11 契约决策：frontmatter 写中文值，内部逻辑保持英文）
#
# 原则：能中文化的英文词（type/status/authoring_mode/card_type/capture_status
# 的取值）在 Frontmatter 文件层面使用中文；CLI 在读写边界做双向归一化，
# 状态机、校验、事务逻辑全部在英文内部值上运行。ID、哈希、时间戳等机器
# 字段保持原样。内部类型（permanent_proposal / formation_witness）与运行时
# 状态（MAINTENANCE_STATES / 可读性检查）不进入映射表，保持英文。
#
# 中文译法复用 notes.STATUS_LABELS（index.md 一直在用的人类可读标签），
# 保持单一事实源；type 译法对齐空间名。
# ---------------------------------------------------------------------------
ENUM_ZH: dict[str, str] = {
    # type（与空间/目录对应）
    "flash": "闪念",
    "source": "来源",
    "interesting": "有意思",
    "todo": "待办",
    "permanent": "永久卡",
    "mother": "母题",
    "action": "行动",
    "index": "索引",
    # status（跨类型共用词，译法 = 原 STATUS_LABELS）
    "pending": "待处理",
    "fermenting": "发酵中",
    "processed": "已处理",
    "dismissed": "已放弃",
    "complete": "完整",
    "partial": "部分抓取",
    "failed": "抓取失败",
    "update_available": "有更新待确认",
    "open": "进行中",
    "done": "已完成",
    "cancelled": "已取消",
    "not_started": "未开始",
    "expired": "已过期",
    "active": "有效",
    "revised": "已修订",
    "retired": "已停用",
    "evolving": "演化中",
    "planned": "待行动",
    "acting": "行动中",
    "observing": "待观察",
    "reviewed": "已复盘",
    # authoring_mode
    "user_verbatim": "用户原文",
    "user_body_agent_title": "仅提炼标题",
    "user_confirmed_agent_structured": "用户确认·Agent结构化",
    # 待办估价标签（2026-08-15 用户拍板：按目标规划方法论五段流程加工）
    "autonomy": "自主",
    "competence": "能力",
    "relatedness": "归属",
    "goal_cognition": "认知中枢",
    "goal_career": "行业职业",
    "goal_creation": "创作能力",
    "goal_tools": "工具效能",
    "high": "高",
    "medium": "中",
    "low": "低",
    # 距离/具体性（2026-08-15 补全方法论六特征）
    "near": "近",
    "far": "远",
    "specific": "具体",
    "vague": "模糊",
}
ENUM_EN: dict[str, str] = {zh: en for en, zh in ENUM_ZH.items()}
ENUM_FIELDS = frozenset({
    "type", "status", "authoring_mode", "card_type", "capture_status",
    # 待办估价标签（2026-08-15）：文件层中文、内部英文，读写边界归一化
    "need_type", "goal_id", "equifinality", "multifinality", "success_probability",
    "distance", "specificity",
})

# 高阶目标定义（2026-08-15 从待办素材抽象，供估价排序与 Agent 加工参考；演化时扩展）
GOAL_SPECS: dict[str, dict[str, str]] = {
    "goal_cognition": {"name": "认知中枢", "desc": "让 good idea 成为替你思考的系统"},
    "goal_career": {"name": "行业职业", "desc": "行业理解与职业跃迁"},
    "goal_creation": {"name": "创作能力", "desc": "AI 创作能力谱系（生图→视频→控制论实践）"},
    "goal_tools": {"name": "工具效能", "desc": "让日常工具链顺手"},
}

# 估价分级（期望×价值×距离排序：概率=期望，多效性=价值杠杆代理，距离=动力权重）
VALUATION_LEVELS = {"high": 3, "medium": 2, "low": 1}
DISTANCE_LEVELS = {"near": 3, "medium": 2, "far": 1}


def localize_enums(metadata: dict[str, Any]) -> dict[str, Any]:
    """写入 Frontmatter 前：英文内部值 → 中文文件值（不修改入参）。"""
    localized = dict(metadata)
    for field in ENUM_FIELDS:
        value = localized.get(field)
        if isinstance(value, str) and value in ENUM_ZH:
            localized[field] = ENUM_ZH[value]
    return localized


def normalize_enums(metadata: dict[str, Any]) -> dict[str, Any]:
    """读取 Frontmatter 后：中文文件值 → 英文内部值（不修改入参）。"""
    normalized = dict(metadata)
    for field in ENUM_FIELDS:
        value = normalized.get(field)
        if isinstance(value, str) and value in ENUM_EN:
            normalized[field] = ENUM_EN[value]
    return normalized


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
        for field in ("trigger_anchor", "activated_logic"):
            value = str(raw.get(field) or "").strip()
            if not value:
                raise ValueError(f"缺少认知事件字段 {field}")
            event[field] = value
        context_refs = event["context_refs"]
        if context_refs:
            anchors = raw.get("source_anchors")
            if not isinstance(anchors, list):
                raise ValueError("有外部上下文时必须提供 source_anchors 数组")
            normalized_anchors: list[dict[str, str]] = []
            seen_refs: set[str] = set()
            for anchor in anchors:
                if not isinstance(anchor, dict):
                    raise ValueError("source_anchors 每项必须是对象")
                context_ref = str(anchor.get("context_ref") or "").strip()
                explanation = str(anchor.get("explanation") or "").strip()
                if context_ref not in context_refs or not explanation:
                    raise ValueError("每个来源锚点必须对应上下文并说明其论证作用")
                if context_ref in seen_refs:
                    raise ValueError("同一上下文不能重复维护来源锚点")
                seen_refs.add(context_ref)
                normalized_anchors.append(
                    {"context_ref": context_ref, "explanation": explanation}
                )
            if seen_refs != set(context_refs):
                raise ValueError("每个外部上下文都必须有且只有一个来源锚点")
            event["source_anchors"] = normalized_anchors
            boundary = str(raw.get("source_boundary") or "").strip()
            if boundary:
                event["source_boundary"] = boundary
        else:
            source_anchor = str(raw.get("source_anchor") or "").strip()
            if not source_anchor:
                raise ValueError("无外部上下文时必须说明用户口述来源")
            event["source_anchor"] = source_anchor
    return event

NOTE_SPECS: dict[str, dict[str, Any]] = {
    "flash": {
        "location": Path("闪念空间"), "heading": "闪念", "default": "pending",
        "statuses": {"pending", "fermenting", "processed", "dismissed"},
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
        "location": Path("待办空间"), "heading": "待办", "default": "not_started",
        "statuses": {"not_started", "open", "done", "cancelled", "expired"}, "required": {"source_ids"},
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

# 待办按状态归档（2026-08-15 用户拍板，v2 扩展）：根目录=未开始+进行中（行动清单），
# 已过期/ 与 已完成/ 与 已取消/ 为状态子目录。capture transition 流转状态时按此移动文件；
# 扫描待办时需同时覆盖这些目录。48h 行动窗口（2026-08-15 拍板）：未开始超 48h 未动
# → capture sweep 转已过期；判定基准=最近一次进入未开始的时刻（not_started_at）。
TODO_STATUS_DIRS: dict[str, Path] = {
    "not_started": Path("待办空间"),
    "open": Path("待办空间"),
    "expired": Path("待办空间/已过期"),
    "done": Path("待办空间/已完成"),
    "cancelled": Path("待办空间/已取消"),
}

# 闪念按状态归档（2026-08-15 用户拍板）：根目录=待处理，已处理/ 为状态子目录，与待办同构。
# 已放弃（dismissed）暂不映射归档目录：transition 到 dismissed 时文件保持原位，sync 跳过。
FLASH_STATUS_DIRS: dict[str, Path] = {
    "pending": Path("闪念空间"),
    "fermenting": Path("闪念空间/发酵中"),
    "processed": Path("闪念空间/已处理"),
}
