from __future__ import annotations

import base64
import copy
import hashlib
import json
import mimetypes
import re
import secrets
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from .capture import CaptureRuntime
from .contracts import (
    DISTANCE_LEVELS,
    ENUM_EN,
    ENUM_FIELDS,
    ENUM_ZH,
    FLASH_STALE_AFTER,
    FLASH_STATUS_DIRS,
    FORMATION_WITNESS_ID_PATTERN,
    FORMATION_WITNESS_ROOT,
    GOAL_SPECS,
    NOTE_SPECS,
    PERMANENT_CARD_TYPES,
    TODO_STATUS_DIRS,
    VALUATION_LEVELS,
    TODO_STALE_AFTER,
    localize_enums,
)
from .errors import GitError, IntegrityError, ValidationError
from .metadata import dump_frontmatter, parse_document, replace_frontmatter
from .notes import (
    TYPE_LOCATIONS,
    add_list_item_to_section,
    dated_filename,
    extract_snapshot,
    normalize_source_layout,
    note_scan_dirs,
    note_scan_entries,
    remove_list_item_from_section,
    remove_section,
    render_note,
    replace_section,
    render_flash_event,
    render_source_anchors,
    render_source_note,
    replace_source_snapshot,
    replace_section,
    snapshot_has_context_header,
    snapshot_hash,
    validate_required_metadata,
    validate_source_note,
    wiki_link,
)
from .repository import Repository, _run_git, now_iso
from .web import canonicalize_url


PURE_CONFIRMATIONS = {
    "同意",
    "可以",
    "确认",
    "好的",
    "好",
    "ok",
    "yes",
    "是",
    "没问题",
}
PROPOSAL_START = "<!-- goodidea:proposal-json:start -->"
PROPOSAL_END = "<!-- goodidea:proposal-json:end -->"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _pending_proposal(
    root: Path, category: str, proposal_id: str, expected_type: str
) -> tuple[Path, str, dict[str, Any]]:
    rel = Path(f".goodidea/proposals/{category}/{proposal_id}.md")
    path = root / rel
    if not path.is_file():
        raise ValidationError(f"找不到待处理候选：{proposal_id}")
    text = path.read_text(encoding="utf-8")
    metadata, _ = parse_document(text)
    if metadata.get("id") != proposal_id or metadata.get("type") != expected_type:
        raise IntegrityError(f"候选文件身份异常：{proposal_id}")
    if metadata.get("status") != "pending":
        raise ValidationError("候选已处理")
    return rel, text, metadata


def _origin_filename(value: Any) -> str:
    """Return a portable basename without ever accepting a host path."""
    filename = str(value or "").strip()
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
    ):
        raise ValidationError("本地来源 origin_filename 必须是文件名，不能包含路径")
    return filename


def _source_preview_identity(
    preview: dict[str, Any],
) -> tuple[str, str, str]:
    """Return kind, state identity key, and stable source id."""
    has_origin_field = any(
        key in preview for key in ("origin_filename", "origin_sha256")
    )
    if has_origin_field:
        if "canonical_url" in preview or "url" in preview:
            raise ValidationError("本地来源不能同时包含 canonical_url/url")
        _origin_filename(preview.get("origin_filename"))
        origin_sha256 = str(preview.get("origin_sha256") or "").strip()
        if not SHA256_RE.fullmatch(origin_sha256):
            raise ValidationError("本地来源 origin_sha256 必须是 64 位 SHA-256")
        actual_origin_sha256 = hashlib.sha256(
            str(preview.get("markdown") or "").encode("utf-8")
        ).hexdigest()
        if origin_sha256 != actual_origin_sha256:
            raise ValidationError(
                "本地来源 origin_sha256 与规范化 Markdown 正文不一致"
            )
        identity_key = f"local:sha256:{origin_sha256}"
        return (
            "local",
            identity_key,
            stable_id("SRC", identity_key, dated=False),
        )

    canonical_url = canonicalize_url(
        str(preview.get("canonical_url") or preview.get("url") or "")
    )
    if not canonical_url.startswith(("http://", "https://")):
        raise ValidationError(
            "网页来源必须包含有效的 http/https URL；本地来源必须包含 "
            "origin_filename 和 origin_sha256"
        )
    return (
        "web",
        canonical_url,
        stable_id("SRC", canonical_url, dated=False),
    )


def _persistable_source_preview(
    preview: dict[str, Any],
) -> tuple[dict[str, Any], str, str, str]:
    """Whitelist preview data so local host paths cannot enter state/proposals."""
    kind, identity_key, source_id = _source_preview_identity(preview)
    kept: dict[str, Any] = {}
    for key in (
        "title",
        "author",
        "published_at",
        "markdown",
        "status",
        "extractor",
        "tags",
    ):
        if key in preview:
            kept[key] = copy.deepcopy(preview[key])
    if kind == "web" and "error" in preview:
        kept["error"] = copy.deepcopy(preview["error"])
    if kind == "local":
        title = str(kept.get("title") or "")
        if Path(title).is_absolute() or bool(re.match(r"^[A-Za-z]:[\\/]", title)):
            raise ValidationError("本地来源标题不能包含绝对路径")

    images: list[dict[str, Any]] = []
    for raw_image in preview.get("images") or []:
        if not isinstance(raw_image, dict):
            continue
        image: dict[str, Any] = {}
        for key in ("url", "alt", "content_type", "data_base64"):
            if key in raw_image:
                image[key] = copy.deepcopy(raw_image[key])
        if "referer" in raw_image:
            referer = str(raw_image.get("referer") or "")
            if referer.startswith(("http://", "https://")):
                image["referer"] = referer
        url = str(image.get("url") or "")
        if kind == "local" and (
            Path(url).is_absolute()
            or bool(re.match(r"^[A-Za-z]:[\\/]", url))
            or url.startswith("file:")
        ):
            raise ValidationError("本地来源图片引用不能包含绝对路径")
        images.append(image)
    kept["images"] = images

    if kind == "web":
        kept["canonical_url"] = identity_key
    else:
        kept["origin_filename"] = _origin_filename(preview["origin_filename"])
        kept["origin_sha256"] = identity_key.removeprefix("local:sha256:")
    return kept, kind, identity_key, source_id


def _source_metadata_identity(
    metadata: dict[str, Any],
) -> tuple[str, str, str]:
    """Validate the mutually exclusive web/local identity stored in a source."""
    has_canonical = "canonical_url" in metadata
    has_origin_filename = "origin_filename" in metadata
    has_origin_sha256 = "origin_sha256" in metadata
    if has_canonical:
        if has_origin_filename or has_origin_sha256:
            raise ValidationError("网页来源不能包含本地来源身份字段")
        canonical = str(metadata.get("canonical_url") or "").strip()
        if not canonical.startswith(("http://", "https://")):
            raise ValidationError("网页来源 canonical_url 无效")
        if canonicalize_url(canonical) != canonical:
            raise ValidationError("网页来源 canonical_url 未规范化")
        return "web", canonical, stable_id("SRC", canonical, dated=False)

    if not (has_origin_filename and has_origin_sha256):
        raise ValidationError(
            "来源必须二选一：canonical_url，或 origin_filename + origin_sha256"
        )
    _origin_filename(metadata.get("origin_filename"))
    origin_sha256 = str(metadata.get("origin_sha256") or "").strip()
    if not SHA256_RE.fullmatch(origin_sha256):
        raise ValidationError("本地来源 origin_sha256 必须是 64 位 SHA-256")
    identity_key = f"local:sha256:{origin_sha256}"
    return "local", identity_key, stable_id("SRC", identity_key, dated=False)


def new_transaction_id(prefix: str) -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{stamp}-{secrets.token_hex(4)}"


def stable_id(prefix: str, seed: str, *, dated: bool = True) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    if dated:
        return f"{prefix}-{datetime.now().astimezone():%Y%m%d}-{digest[:8]}"
    return f"{prefix}-{digest[:12]}"


def _meaningful(text: str, *, minimum: int = 4) -> bool:
    normalized = re.sub(r"[\s，。！？、,.!?;；:：]+", "", text).lower()
    return len(normalized) >= minimum and normalized not in PURE_CONFIRMATIONS


def _normalize_direct_source(text: str) -> tuple[str, str]:
    normalized = _normalize_user_entry(text).strip()
    if "\n" in normalized:
        raise ValidationError("直接口述形成说明必须是一段简短的单行说明")
    if not _meaningful(normalized, minimum=8):
        raise ValidationError(
            "直接口述形成说明必须具体说明所回应的问题、经验或现实情境"
        )
    compact = re.sub(r"[\s，。！？、,.!?;；:：]+", "", normalized).lower()
    if compact in {"来自本轮口述", "用户说过", "本轮用户表达", "直接口述"}:
        raise ValidationError("直接口述形成说明不能只是来源标签或纯确认文本")
    if normalized.startswith("---") or PROPOSAL_START in normalized or PROPOSAL_END in normalized:
        raise ValidationError("直接口述形成说明不得包含 Frontmatter 或内部提案数据")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return normalized, digest


def _render_formation_witness(
    metadata: dict[str, Any], source_anchor: str, card_rel: Path, card_title: str
) -> str:
    return (
        dump_frontmatter(metadata)
        + "# 本轮直接表达形成来源\n\n"
        + source_anchor
        + "\n\n## 形成卡片\n\n"
        + f"- {wiki_link(card_rel, card_title)}\n"
    )


def _ensure_motivation(text: str) -> None:
    if not _meaningful(text, minimum=4):
        raise ValidationError(
            "必须先说明为什么要保存这份内容；纯“同意/可以/确认”不能触发持久化"
        )


def _proposal_payload(text: str) -> dict[str, Any]:
    start = text.find(PROPOSAL_START)
    end = text.find(PROPOSAL_END)
    if start < 0 or end < start:
        raise IntegrityError("提案缺少机器可读候选数据")
    raw = text[start + len(PROPOSAL_START):end].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IntegrityError("提案候选数据已损坏") from exc


def _proposal_document(metadata: dict[str, Any], payload: dict[str, Any]) -> str:
    readable = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return render_note(
        metadata,
        [
            ("候选内容", payload.get("claim") or payload.get("rationale") or "待确认"),
            ("机器数据", f"{PROPOSAL_START}\n{readable}\n{PROPOSAL_END}"),
        ],
    )


def _normalize_user_draft(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized and not normalized.endswith("\n"):
        normalized += "\n"
    return normalized


def _normalize_user_entry(text: str) -> str:
    """Preserve wording while making a fragment safe to wrap in Markdown."""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def _validate_user_draft(text: str) -> tuple[str, str, str]:
    """Validate syntax only; semantic quality belongs to the human/Skill review."""
    draft = _normalize_user_draft(text)
    if not draft.strip():
        raise ValidationError("用户草稿不能为空")
    if draft.lstrip().startswith("---\n"):
        raise ValidationError("用户草稿不要包含 Frontmatter；ID 和状态由 CLI 添加")
    if PROPOSAL_START in draft or PROPOSAL_END in draft or "## 机器数据" in draft:
        raise ValidationError("用户草稿不得包含内部提案数据或“机器数据”区块")
    headings = re.findall(r"(?m)^# ([^#\n].*)$", draft)
    if len(headings) != 1:
        raise ValidationError("用户草稿必须且只能包含一个一级标题（# 标题）")
    first_content = next((line for line in draft.splitlines() if line.strip()), "")
    if first_content != f"# {headings[0]}":
        raise ValidationError("用户草稿的第一行内容必须是一级标题")
    title = headings[0].strip()
    if not title:
        raise ValidationError("用户草稿标题不能为空")
    body_lines = [
        line.strip()
        for line in draft.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "<!--"))
    ]
    if not _meaningful("\n".join(body_lines), minimum=12):
        raise ValidationError("用户草稿正文过短，尚不能作为可审查的永久卡片草稿")
    digest = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    return title, draft, digest


def _prepare_permanent_draft(
    text: str,
    extracted_title: str = "",
    user_approved_structure: bool = False,
) -> tuple[str, str, str, str]:
    """Prepare either a user-titled draft or an agent-titled user body."""
    if user_approved_structure:
        if extracted_title.strip():
            raise ValidationError("已确认的结构化草稿必须自带标题，不再同时传 --title")
        title, draft, digest = _validate_user_draft(text)
        return title, draft, digest, "user_confirmed_agent_structured"
    if not extracted_title.strip():
        title, draft, digest = _validate_user_draft(text)
        return title, draft, digest, "user_verbatim"
    title = extracted_title.strip()
    if "\n" in title or title.startswith("#") or not _meaningful(title, minimum=4):
        raise ValidationError("从用户内容提炼的标题必须是单行且含有明确意义")
    body = _normalize_user_draft(text)
    if not body.strip():
        raise ValidationError("用户正文不能为空")
    if body.lstrip().startswith("---\n"):
        raise ValidationError("用户正文不要包含 Frontmatter；ID 和状态由 CLI 添加")
    if re.search(r"(?m)^# ", body):
        raise ValidationError("使用 --title 时，用户正文不得再包含一级标题")
    if PROPOSAL_START in body or PROPOSAL_END in body or "## 机器数据" in body:
        raise ValidationError("用户正文不得包含内部提案数据或“机器数据”区块")
    body_lines = [
        line.strip()
        for line in body.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "<!--"))
    ]
    if not _meaningful("\n".join(body_lines), minimum=12):
        raise ValidationError("用户正文过短，尚不能作为可审查的永久卡片草稿")
    draft = f"# {title}\n\n{body}"
    _, normalized, digest = _validate_user_draft(draft)
    return title, normalized, digest, "user_body_agent_title"


def _default_status(note_type: str) -> str:
    return str(NOTE_SPECS[note_type]["default"])


def _rewrite_wiki_paths(
    text: str,
    replacements: dict[str, str],
    *,
    protect_snapshot: bool = False,
) -> str:
    def rewrite(editable: str) -> str:
        if not replacements:
            return editable
        alternatives = "|".join(
            re.escape(old) for old in sorted(replacements, key=len, reverse=True)
        )
        pattern = re.compile(
            r"\[\[(?P<target>" + alternatives + r")(?=(?:\||#|\]\]))"
        )
        return pattern.sub(
            lambda match: f"[[{replacements[match.group('target')]}", editable
        )
    if not protect_snapshot:
        return rewrite(text)
    _, _, start, end = extract_snapshot(text)
    return rewrite(text[:start]) + text[start:end] + rewrite(text[end:])


def _rewrite_exact_paths(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            key: _rewrite_exact_paths(item, replacements)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite_exact_paths(item, replacements) for item in value]
    if isinstance(value, str):
        return replacements.get(value, value)
    return value


def _rewrite_default_alias(
    text: str,
    target: str,
    old_title: str,
    new_title: str,
    *,
    protect_snapshot: bool = False,
) -> str:
    def rewrite(editable: str) -> str:
        return editable.replace(
            f"[[{target}|{old_title}]]", f"[[{target}|{new_title}]]"
        )
    if not protect_snapshot:
        return rewrite(text)
    _, _, start, end = extract_snapshot(text)
    return rewrite(text[:start]) + text[start:end] + rewrite(text[end:])


class GoodIdeaService:
    def __init__(self, repo: Repository):
        self.repo = repo

    def _idempotent(self, transaction_id: str) -> dict[str, Any] | None:
        return self.repo.transaction_result(transaction_id)

    def _new_note_path(
        self,
        note_type: str,
        title: str,
        created_at: str,
        *,
        reserved: set[Path] | None = None,
    ) -> Path:
        occupied = reserved if reserved is not None else set()
        location = TYPE_LOCATIONS[note_type]
        collision = 1
        while True:
            candidate = location / dated_filename(
                title, created_at, collision=collision
            )
            if candidate not in occupied and not (self.repo.root / candidate).exists():
                return candidate
            collision += 1

    def capture(
        self,
        kind: str,
        *,
        text: str,
        title: str = "",
        context: str = "",
        source_id: str = "",
        reason: str = "",
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if kind not in {"flash", "interesting", "todo"}:
            raise ValidationError(f"不支持的轻量记录类型：{kind}")
        if not text.strip():
            raise ValidationError("记录内容不能为空")
        txid = transaction_id or new_transaction_id(f"capture-{kind}")
        if existing := self._idempotent(txid):
            return existing
        prefix = {"flash": "FLA", "interesting": "INT", "todo": "TODO"}[kind]
        note_id = stable_id(prefix, f"{txid}:{text}")
        note_title = title.strip() or text.strip().splitlines()[0][:40]
        timestamp = now_iso()
        rel = self._new_note_path(kind, note_title, timestamp)
        metadata = {
            "id": note_id,
            "type": kind,
            "title": note_title,
            "status": _default_status(kind),
            "created_at": timestamp,
            "updated_at": timestamp,
            "source_ids": [source_id] if source_id else [],
        }
        if kind == "todo":
            # 48h 行动窗口（2026-08-15 拍板）：未开始计时基准=进入未开始的时刻
            metadata["not_started_at"] = timestamp
        sections = [("原始记录", text)]
        if kind == "todo" and reason.strip():
            # 摄入澄清（2026-08-15 拍板）：用户确认过的动机原话写入卡片正文，属于用户认知正文
            sections.append(("为什么做", reason.strip()))
        if context:
            sections.append(("产生情境", context))
        if source_id:
            found = self.repo.find_note(source_id)
            if not found:
                raise ValidationError(f"找不到来源：{source_id}")
            source_path, _, source_meta = found
            sections.append(("关联来源", wiki_link(source_path, source_meta["title"])))
        note = render_note(metadata, sections)
        state = self.repo.read_state()
        result = {"id": note_id, "path": rel.as_posix(), "type": kind}
        return self.repo.commit(
            transaction_id=txid,
            action=f"capture-{kind}",
            summary=note_title,
            writes={rel: note},
            state=state,
            result=result,
        )

    def capture_revise(
        self,
        note_id: str,
        *,
        note: str,
        confirmed_by_user: bool,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if not confirmed_by_user:
            raise ValidationError("轻量记录修订只能逐字追加用户亲自写下的内容")
        if not _meaningful(note, minimum=8):
            raise ValidationError("演化记录必须包含用户明确的补充或修正")
        found = self.repo.find_note(note_id)
        if not found or found[2].get("type") not in {
            "flash",
            "interesting",
            "todo",
        }:
            raise ValidationError(f"找不到轻量记录：{note_id}")
        rel, text, metadata = found
        txid = transaction_id or new_transaction_id("capture-revise")
        if existing := self._idempotent(txid):
            return existing
        timestamp = now_iso()
        user_note = _normalize_user_entry(note)
        text = add_list_item_to_section(
            text, "演化记录", f"{timestamp} — {user_note}"
        )
        metadata["updated_at"] = timestamp
        text = replace_frontmatter(text, metadata)
        state = self.repo.read_state()
        result = {
            "id": note_id,
            "path": rel.as_posix(),
            "type": metadata["type"],
        }
        return self.repo.commit(
            transaction_id=txid,
            action="capture-revise",
            summary=metadata["title"],
            writes={rel: text},
            state=state,
            result=result,
        )

    def capture_discuss(
        self,
        note_id: str,
        *,
        text: str,
        role: str,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        """讨论过程原文记录（2026-08-15 用户拍板）。

        围绕轻量卡片（闪念/有意思/待办）的讨论过程——用户原文与 Agent 原文
        ——按时间线追加到独立 JSON 文件（.goodidea/runtime/discussions/<id>.json，
        Git 忽略的内部层），卡片 frontmatter 写 discussion_log 关联。
        讨论不因结论（转/不转永久卡）而丢失；未转时原文仍挂在卡片下，可延续。
        只记录原文，不转化、不结构化摘要。
        """
        if role not in ("user", "assistant"):
            raise ValidationError("role 只能是 user 或 assistant")
        if not text.strip():
            raise ValidationError("讨论内容不能为空")
        found = self.repo.find_note(note_id)
        if not found or found[2].get("type") not in {
            "flash",
            "interesting",
            "todo",
        }:
            raise ValidationError(f"找不到轻量记录：{note_id}")
        rel, text_note, metadata = found
        txid = transaction_id or new_transaction_id("capture-discuss")
        if existing := self._idempotent(txid):
            return existing
        timestamp = now_iso()
        # 讨论记录文件（Git 忽略的内部层，时间线原文）
        log_rel = (
            Path(".goodidea") / "runtime" / "discussions" / f"{note_id}.json"
        )
        log_path = self.repo.root / log_rel
        if log_path.exists():
            log = json.loads(log_path.read_text(encoding="utf-8"))
        else:
            log = {"note_id": note_id, "created_at": timestamp, "entries": []}
        log["entries"].append(
            {"role": role, "text": text, "recorded_at": timestamp}
        )
        log["updated_at"] = timestamp
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            json.dumps(log, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        # 卡片 frontmatter 关联（CLI 维护）
        metadata["discussion_log"] = log_rel.as_posix()
        metadata["updated_at"] = timestamp
        # 卡片正文"讨论记录"导航区（CLI 机械维护，人类可读证据）
        log_summary = (
            f"讨论档案：`{log_rel.as_posix()}`（{len(log['entries'])} 条时间线原文，"
            f"最后更新 {timestamp[:16]}）\n\n"
            "> 讨论过程原文按时间线记录在档案文件，`capture discuss` 逐轮追加；"
            "结论沉淀按「原文归原文、结论归结论」——Agent 不生产摘要。"
        )
        note_text = replace_section(text_note, "讨论记录", log_summary)
        updated = replace_frontmatter(note_text, metadata)
        state = self.repo.read_state()
        result = {
            "id": note_id,
            "path": rel.as_posix(),
            "type": metadata["type"],
            "discussion_log": log_rel.as_posix(),
            "entry_count": len(log["entries"]),
        }
        return self.repo.commit(
            transaction_id=txid,
            action="capture-discuss",
            summary=metadata["title"],
            writes={rel: updated},
            state=state,
            result=result,
        )

    def capture_summarize(
        self,
        note_id: str,
        *,
        window: str,
        summary: str,
        confirmed_by_user: bool,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        """讨论摘要落盘（2026-08-15 用户拍板）。

        基于一次讨论的原文时间线生成的核心摘要，追加到卡片"讨论摘要"区
        （CLI 机械维护）。摘要保留讨论血肉：关键原话与细节直接摘录，
        结构在叙述中自然流动，不贴分类标签；内容只来自原文（不新增），
        必须经用户确认（--confirm-user-authored）后才落盘。
        """
        if not confirmed_by_user:
            raise ValidationError("讨论摘要必须经用户确认后才能落盘")
        if not _meaningful(summary, minimum=20):
            raise ValidationError("摘要必须包含用户确认的实质内容")
        if not window.strip():
            raise ValidationError("摘要必须带讨论时间窗口")
        found = self.repo.find_note(note_id)
        if not found or found[2].get("type") not in {
            "flash",
            "interesting",
            "todo",
        }:
            raise ValidationError(f"找不到轻量记录：{note_id}")
        rel, text_note, metadata = found
        txid = transaction_id or new_transaction_id("capture-summarize")
        if existing := self._idempotent(txid):
            return existing
        timestamp = now_iso()
        # 统计已有摘要条目数（编号"第 N 次讨论"）
        body_start = text_note.find("\n---", 4)
        body = text_note[body_start + 5:] if body_start >= 0 else text_note
        existing_count = 0
        for line in body.splitlines():
            if line.startswith("- **") and "｜" in line:
                existing_count += 1
        # 摘要条目：时间窗口 + 血肉正文（多行，4 空格缩进续行；
        # add_list_item_to_section 会自动加 "- " 前缀）
        indented = "\n".join(
            f"    {line}" if line.strip() else line
            for line in summary.strip().splitlines()
        )
        entry_marker = f"- **{window.strip()}**"
        if entry_marker in text_note:
            # 同窗口条目存在 → 覆盖重写（同一讨论的摘要升级，不新增编号）
            start = text_note.find(entry_marker)
            next_item = text_note.find("\n- **", start + len(entry_marker))
            if next_item < 0:
                next_item = len(text_note)
            new_block = (
                f"{entry_marker}｜第 {existing_count} 次讨论\n\n{indented}"
            )
            text_note = text_note[:start] + new_block + text_note[next_item:]
            result_count = existing_count
        else:
            entry = (
                f"**{window.strip()}**｜第 {existing_count + 1} 次讨论\n\n"
                f"{indented}"
            )
            text_note = add_list_item_to_section(text_note, "讨论摘要", entry)
            result_count = existing_count + 1
        metadata["updated_at"] = timestamp
        text_note = replace_frontmatter(text_note, metadata)
        state = self.repo.read_state()
        result = {
            "id": note_id,
            "path": rel.as_posix(),
            "type": metadata["type"],
            "summary_count": result_count,
        }
        return self.repo.commit(
            transaction_id=txid,
            action="capture-summarize",
            summary=metadata["title"],
            writes={rel: text_note},
            state=state,
            result=result,
        )

    def capture_transition(
        self,
        note_id: str,
        *,
        status: str,
        transaction_id: str | None = None,
        accept_dirty: bool = False,
    ) -> dict[str, Any]:
        found = self.repo.find_note(note_id)
        if not found or found[2].get("type") not in {
            "flash",
            "interesting",
            "todo",
        }:
            raise ValidationError(f"找不到轻量记录：{note_id}")
        rel, text, metadata = found
        note_type = metadata["type"]
        allowed = set(NOTE_SPECS[note_type]["statuses"])
        # flash 的 processed 由系统在永久卡片接纳时自动设置，也允许手动归档
        # （2026-08-15：认知生命周期完成、转化为机制/被消化后，用户确认归档）
        if status not in allowed:
            raise ValidationError(
                f"{note_type} 不允许状态 {status}；可选：{sorted(allowed)}"
            )
        txid = transaction_id or new_transaction_id("capture-transition")
        if existing := self._idempotent(txid):
            return existing
        timestamp = now_iso()
        metadata["status"] = status
        metadata["updated_at"] = timestamp
        if note_type == "todo":
            if status == "not_started":
                # 重新承诺（2026-08-15 拍板）：进入未开始重新计时 48h 行动窗口
                metadata["not_started_at"] = timestamp
            elif status in ("open", "done", "cancelled", "expired") and "not_started_at" in metadata:
                # 退出未开始：清除计时基准（进行中不参与 48h 窗口）
                metadata.pop("not_started_at", None)
        text = replace_frontmatter(text, metadata)
        state = self.repo.read_state()
        # 状态归档（2026-08-15 用户拍板）：状态变化时把文件移到对应状态目录
        target_rel = rel
        writes: dict[Path, str | bytes] = {}
        deletes: set[Path] = set()
        if note_type == "todo":
            relocation_writes, relocation_deletes, target_rel = self._relocate_note(
                rel, status, TODO_STATUS_DIRS
            )
            writes.update(relocation_writes)
            deletes.update(relocation_deletes)
        elif note_type == "flash" and status in FLASH_STATUS_DIRS:
            # 闪念与待办同构：待处理=根目录，已处理=已处理/ 子目录（dismissed 无归档目录，保持原位）
            relocation_writes, relocation_deletes, target_rel = self._relocate_note(
                rel, status, FLASH_STATUS_DIRS
            )
            writes.update(relocation_writes)
            deletes.update(relocation_deletes)
        result = {
            "id": note_id,
            "path": target_rel.as_posix(),
            "type": note_type,
            "status": status,
        }
        writes[target_rel] = text
        return self.repo.commit(
            transaction_id=txid,
            action="capture-transition",
            summary=metadata["title"],
            writes=writes,
            deletes=deletes,
            state=state,
            result=result,
            accept_dirty=accept_dirty,
        )

    def _relocate_note(
        self, rel: Path, status: str, status_dirs: dict[str, Path]
    ) -> tuple[dict[Path, str | bytes], set[Path], Path]:
        """状态归档：计算目标目录路径，全库重写引用旧路径的 wikilink。

        待办/闪念共用（TODO_STATUS_DIRS / FLASH_STATUS_DIRS）。来源快照区受保护
        不参与替换；返回（引用改写 writes、旧路径 deletes、目标路径）。
        status 必须存在于 status_dirs，否则 KeyError。
        """
        target_dir = status_dirs[status]
        target_rel = target_dir / rel.name
        writes: dict[Path, str | bytes] = {}
        deletes: set[Path] = set()
        if target_rel != rel:
            replacements = {
                rel.with_suffix("").as_posix(): target_rel.with_suffix("").as_posix()
            }
            for note_type_, location_ in note_scan_entries():
                for path in sorted((self.repo.root / location_).glob("*.md")):
                    other_rel = path.relative_to(self.repo.root)
                    if other_rel == rel:
                        continue
                    note_text = path.read_text(encoding="utf-8")
                    note_meta, _ = parse_document(note_text)
                    protect = note_meta.get("type") == "source"
                    rewritten = _rewrite_wiki_paths(
                        note_text, replacements, protect_snapshot=protect
                    )
                    if rewritten != note_text:
                        writes[other_rel] = rewritten
            deletes.add(rel)
        return writes, deletes, target_rel

    def capture_sync(
        self, *, transaction_id: str | None = None
    ) -> dict[str, Any]:
        """扫描待办/闪念归档目录，把 frontmatter 状态与所在目录不一致的记录归位。

        阅读层（Obsidian note-database）手动修改 status 后，文件状态与目录脱节：
        本命令把用户已表达的状态作为事实，一次事务完成所有归档移动、全库引用
        重写、frontmatter 规范化与聚焦提交。状态值无法识别的文件跳过并报告；
        闪念 dismissed 暂无归档目录，保持原位跳过。
        """
        status_dirs_by_type: dict[str, dict[str, Path]] = {
            "todo": TODO_STATUS_DIRS,
            "flash": FLASH_STATUS_DIRS,
        }
        moves: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        seen: set[Path] = set()
        for note_type, status_dirs in status_dirs_by_type.items():
            for location in status_dirs.values():
                for path in sorted((self.repo.root / location).glob("*.md")):
                    rel = path.relative_to(self.repo.root)
                    if rel in seen:
                        continue
                    seen.add(rel)
                    try:
                        text = path.read_text(encoding="utf-8")
                        metadata, _ = parse_document(text)
                    except (OSError, ValidationError) as exc:
                        skipped.append(
                            {"path": rel.as_posix(), "reason": f"解析失败：{exc}"}
                        )
                        continue
                    if metadata.get("type") != note_type:
                        continue
                    status = metadata.get("status")
                    if status not in status_dirs:
                        if note_type == "flash" and status == "dismissed":
                            continue
                        skipped.append(
                            {"path": rel.as_posix(), "reason": f"无法识别状态：{status!r}"}
                        )
                        continue
                    target_dir = status_dirs[status]
                    target_rel = target_dir / rel.name
                    if target_rel == rel:
                        continue
                    moves.append(
                        {
                            "id": metadata.get("id"),
                            "from": rel.as_posix(),
                            "path": target_rel.as_posix(),
                            "status": status,
                        }
                    )
        if not moves:
            return {"moved": [], "skipped": skipped, "synced": False}

        txid = transaction_id or new_transaction_id("capture-sync")
        if existing := self._idempotent(txid):
            return existing
        timestamp = now_iso()

        replacements = {
            Path(item["from"])
            .with_suffix("")
            .as_posix(): Path(item["path"]).with_suffix("").as_posix()
            for item in moves
        }
        move_sources = {Path(item["from"]) for item in moves}
        originals: dict[Path, tuple[str, dict[str, Any]]] = {}
        for status_dirs in status_dirs_by_type.values():
            for location in status_dirs.values():
                for path in sorted((self.repo.root / location).glob("*.md")):
                    rel = path.relative_to(self.repo.root)
                    if rel in move_sources:
                        text = path.read_text(encoding="utf-8")
                        originals[rel] = (text, parse_document(text)[0])

        writes: dict[Path, str | bytes] = {}
        deletes: set[Path] = set()
        # 全库引用重写（跳过移动源本身，其目标内容单独生成）
        for note_type_, location_ in note_scan_entries():
            for path in sorted((self.repo.root / location_).glob("*.md")):
                other_rel = path.relative_to(self.repo.root)
                if other_rel in move_sources:
                    continue
                note_text = path.read_text(encoding="utf-8")
                note_meta, _ = parse_document(note_text)
                protect = note_meta.get("type") == "source"
                rewritten = _rewrite_wiki_paths(
                    note_text, replacements, protect_snapshot=protect
                )
                if rewritten != note_text:
                    writes[other_rel] = rewritten
        # 移动源：正文应用全局替换，frontmatter 规范化，写入目标路径
        for item in moves:
            rel = Path(item["from"])
            target_rel = Path(item["path"])
            text, metadata = originals[rel]
            text = _rewrite_wiki_paths(text, replacements, protect_snapshot=False)
            metadata["updated_at"] = timestamp
            writes[target_rel] = replace_frontmatter(text, metadata)
            deletes.add(rel)

        state = self.repo.read_state()
        return self.repo.commit(
            transaction_id=txid,
            action="capture-sync",
            summary=f"归档 {len(moves)} 条记录",
            writes=writes,
            deletes=deletes,
            state=state,
            result={"moved": moves, "skipped": skipped},
            accept_dirty=True,
        )

    def capture_sweep(
        self,
        *,
        now: datetime | None = None,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        """48h 行动窗口扫描（2026-08-15 拍板）：未开始超 48h 未动 → 已过期。

        判定基准 = 最近一次进入未开始的时刻（not_started_at，进入时由 CLI 记录）；
        未开始且 now - not_started_at >= 48h 的待办批量转 已过期，移入
        待办空间/已过期/ 并全库重写 wikilink。进行中不参与窗口（开始即退出）。
        返回移动清单；无过期项时不产生事务。not_started_at 缺失视为刚进入
        未开始（存量待办迁移时补齐），跳过并报告。
        """
        now = now or datetime.now().astimezone()
        txid = transaction_id or new_transaction_id("capture-sweep")
        if existing := self._idempotent(txid):
            return existing
        root_dir = self.repo.root / TODO_STATUS_DIRS["not_started"]
        expired: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for path in sorted(root_dir.glob("*.md")):
            rel = path.relative_to(self.repo.root)
            try:
                text = path.read_text(encoding="utf-8")
                metadata, _ = parse_document(text)
            except (OSError, ValidationError) as exc:
                skipped.append({"path": rel.as_posix(), "reason": f"解析失败：{exc}"})
                continue
            if metadata.get("type") != "todo" or metadata.get("status") != "not_started":
                continue
            marker = metadata.get("not_started_at")
            if not marker:
                skipped.append(
                    {"path": rel.as_posix(), "reason": "缺少 not_started_at，跳过（迁移时补齐）"}
                )
                continue
            try:
                entered = datetime.fromisoformat(str(marker))
            except ValueError:
                skipped.append(
                    {"path": rel.as_posix(), "reason": f"not_started_at 无法解析：{marker!r}"}
                )
                continue
            if now - entered >= TODO_STALE_AFTER:
                expired.append(
                    {
                        "id": metadata.get("id"),
                        "path": rel.as_posix(),
                        "status": "expired",
                        "entered_at": str(marker),
                    }
                )
        if not expired:
            return {"expired": [], "skipped": skipped, "swept": False}

        timestamp = now_iso()

        target_dir = TODO_STATUS_DIRS["expired"]
        replacements = {
            Path(item["path"]).with_suffix("").as_posix(): (
                target_dir / Path(item["path"]).name
            ).with_suffix("").as_posix()
            for item in expired
        }
        move_sources = {Path(item["path"]) for item in expired}
        originals: dict[Path, tuple[str, dict[str, Any]]] = {}
        for path in sorted(root_dir.glob("*.md")):
            rel = path.relative_to(self.repo.root)
            if rel in move_sources:
                originals[rel] = (path.read_text(encoding="utf-8"), parse_document(path.read_text(encoding="utf-8"))[0])

        writes: dict[Path, str | bytes] = {}
        deletes: set[Path] = set()
        # 全库引用重写（跳过移动源本身，其目标内容单独生成）
        for note_type_, location_ in note_scan_entries():
            for path in sorted((self.repo.root / location_).glob("*.md")):
                other_rel = path.relative_to(self.repo.root)
                if other_rel in move_sources:
                    continue
                note_text = path.read_text(encoding="utf-8")
                note_meta, _ = parse_document(note_text)
                protect = note_meta.get("type") == "source"
                rewritten = _rewrite_wiki_paths(
                    note_text, replacements, protect_snapshot=protect
                )
                if rewritten != note_text:
                    writes[other_rel] = rewritten
        # 移动源：状态转已过期、清除计时基准、正文应用全局替换，写入目标路径
        for item in expired:
            rel = Path(item["path"])
            target_rel = target_dir / rel.name
            text, metadata = originals[rel]
            text = _rewrite_wiki_paths(text, replacements, protect_snapshot=False)
            metadata["status"] = "expired"
            metadata["updated_at"] = timestamp
            metadata.pop("not_started_at", None)
            writes[target_rel] = replace_frontmatter(text, metadata)
            deletes.add(rel)

        state = self.repo.read_state()
        return self.repo.commit(
            transaction_id=txid,
            action="capture-sweep",
            summary=f"过期 {len(expired)} 条待办",
            writes=writes,
            deletes=deletes,
            state=state,
            result={"expired": expired, "skipped": skipped},
            # 文件当前内容视为事务输入（阅读层可能手动改过标签/状态；选中即已确认超时）
            accept_dirty=True,
        )

    def capture_valuate(
        self,
        note_id: str,
        *,
        need_type: str,
        goal_id: str,
        equifinality: str,
        multifinality: str,
        success_probability: str,
        distance: str,
        specificity: str,
        rationale: str,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        """待办估价（2026-08-15 用户拍板：目标规划方法论五段流程的落盘命令）。

        Agent 按方法论完成语义判断（需求类型/高阶目标/等效性/多效性/成功概率/
        距离/具体性——覆盖方法论六特征）并给出可审计的推理理由（rationale，必填
        ——机制不接受黑箱估价），本命令校验枚举合法性、写回中文标签、把理由写入
        卡片"估价依据"区（CLI 机械维护，含确定性得分与优先级），并按期望×价值
        ×距离规则确定性重算全部"进行中"待办的 priority：主键=概率×多效性×距离，
        tie-break=等效性，未估价待办排最后按创建时间。
        """
        rationale = rationale.strip()
        if not rationale:
            raise ValidationError("估价必须提供理由（--rationale）：机制不接受黑箱估价")
        found = self.repo.find_note(note_id)
        if not found or found[2].get("type") != "todo":
            raise ValidationError(f"找不到待办：{note_id}")
        if found[2].get("status") not in {"not_started", "open"}:
            raise ValidationError("只对行动清单（未开始/进行中）的待办估价；已过期/已完成/已取消请用 capture transition 流转")
        rel, text, metadata = found
        labels = {
            "need_type": need_type,
            "goal_id": goal_id,
            "equifinality": equifinality,
            "multifinality": multifinality,
            "success_probability": success_probability,
            "distance": distance,
            "specificity": specificity,
        }
        normalized: dict[str, str] = {}
        for key, value in labels.items():
            if value not in ENUM_EN and value not in ENUM_ZH:
                raise ValidationError(f"{key} 不允许值 {value!r}；可选：高/中/低、自主/能力/归属、四个高阶目标、近/中/远、具体/模糊")
            normalized[key] = ENUM_EN.get(value, value)
        if normalized["goal_id"] not in GOAL_SPECS:
            raise ValidationError(f"高阶目标必须是 {sorted(GOAL_SPECS)} 之一")
        for key in ("equifinality", "multifinality", "success_probability"):
            if normalized[key] not in VALUATION_LEVELS:
                raise ValidationError(f"{key} 必须是 高/中/低")
        if normalized["distance"] not in DISTANCE_LEVELS:
            raise ValidationError("distance 必须是 近/中/远")
        if normalized["specificity"] not in ("specific", "vague"):
            raise ValidationError("specificity 必须是 具体/模糊")

        txid = transaction_id or new_transaction_id("capture-valuate")
        if existing := self._idempotent(txid):
            return existing
        timestamp = now_iso()

        # 收集行动集待办（未开始+进行中；已过期/已完成/已取消归档不产生行动，不参与估价排序）
        todos: list[tuple[Path, dict[str, Any]]] = []
        scan_locations = sorted({loc for loc in TODO_STATUS_DIRS.values()})
        for location in scan_locations:
            for path in sorted((self.repo.root / location).glob("*.md")):
                try:
                    meta, _ = parse_document(path.read_text(encoding="utf-8"))
                except (OSError, ValidationError):
                    continue
                if meta.get("type") != "todo" or meta.get("status") not in {"not_started", "open"}:
                    continue
                todos.append((path.relative_to(self.repo.root), meta))
        # 目标卡片用更新后的 metadata 参与重排（否则刚写入的新标签排不进正确位置）
        metadata.update(normalized)
        todos = [
            (rel, metadata) if other_rel == rel else (other_rel, other_meta)
            for other_rel, other_meta in todos
        ]
        ranked = self._rank_todos(todos)
        priority_map = dict(ranked)

        writes: dict[Path, str | bytes] = {}
        # 目标卡片：标签 + priority + "估价依据"区一次写入（CLI 机械维护，推理链摊开）
        metadata["priority"] = priority_map[rel]
        metadata["updated_at"] = timestamp
        score = (
            VALUATION_LEVELS[normalized["success_probability"]]
            * VALUATION_LEVELS[normalized["multifinality"]]
            * DISTANCE_LEVELS[normalized["distance"]]
        )
        rationale_block = self._render_rationale_table(
            rationale,
            score=score,
            priority=priority_map[rel],
            todo_count=len(todos),
            probability_zh=ENUM_ZH[normalized["success_probability"]],
            multifinality_zh=ENUM_ZH[normalized["multifinality"]],
            distance_zh=ENUM_ZH[normalized["distance"]],
        )
        updated_text = replace_frontmatter(text, metadata)
        updated_text = replace_section(updated_text, "估价依据", rationale_block)
        writes[rel] = updated_text
        # 其余卡片：priority 变化才写入
        for other_rel, priority in ranked:
            if other_rel == rel:
                continue
            current_path = self.repo.root / other_rel
            current_text = current_path.read_text(encoding="utf-8")
            current_meta, _ = parse_document(current_text)
            if current_meta.get("priority") == priority:
                continue
            current_meta["priority"] = priority
            current_meta["updated_at"] = timestamp
            writes[other_rel] = replace_frontmatter(current_text, current_meta)

        state = self.repo.read_state()
        result_ranked = [
            {
                "id": meta.get("id"),
                "title": meta.get("title"),
                "priority": priority_map[rel_path],
                "path": rel_path.as_posix(),
            }
            for rel_path, meta in todos
        ]
        result_ranked.sort(key=lambda item: item["priority"])
        return self.repo.commit(
            transaction_id=txid,
            action="capture-valuate",
            summary=metadata["title"],
            writes=writes,
            deletes=set(),
            state=state,
            result={
                "id": note_id,
                "labels": normalized,
                "priority": priority_map[rel],
                "ranked": result_ranked,
            },
        )

    @staticmethod
    def _render_rationale_table(
        rationale: str,
        *,
        score: int,
        priority: int,
        todo_count: int,
        probability_zh: str,
        multifinality_zh: str,
        distance_zh: str,
    ) -> str:
        """估价依据渲染为 Markdown 表格（CLI 机械维护，格式统一可审计）。

        解析 '维度：判定 —— 说明' 形式的行（维度必须是七个标签之一），
        渲染成 对象|内容|说明 三列表格；无法解析的行原样保留（容错）。
        末尾追加确定性得分与优先级。
        """
        dims = ("需求类型", "高阶目标", "等效性", "多效性", "成功概率", "距离", "具体性")
        pattern = re.compile(r"^[-*]?\s*(.+?)[：:]\s*(.+?)\s*——\s*(.+)$")
        rows: list[tuple[str, str, str]] = []
        leftover: list[str] = []
        for line in rationale.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            m = pattern.match(line)
            if m and m.group(1).strip() in dims:
                rows.append((m.group(1).strip(), m.group(2).strip(), m.group(3).strip()))
            else:
                leftover.append(line)
        if rows:
            # 按固定维度顺序排序（需求类型→高阶目标→等效性→多效性→成功概率），
            # 三列：对象（维度）| 内容（判定值）| 说明（理由）
            dim_index = {dim: i for i, dim in enumerate(dims)}
            rows.sort(key=lambda row: dim_index[row[0]])
            table = ["| 对象 | 内容 | 说明 |", "| --- | --- | --- |"]
            table.extend(
                f"| {dim} | {judgment} | {explanation} |"
                for dim, judgment, explanation in rows
            )
            body = "\n".join(table)
        else:
            body = rationale.strip()
        if leftover:
            body += "\n\n" + "\n".join(leftover)
        body += (
            f"\n\n- 期望×价值×距离：{score} 分"
            f"（概率 {probability_zh} × 多效 {multifinality_zh} × 距离 {distance_zh}）"
            f"→ 优先级 P{priority}（{todo_count} 条进行中待办）"
        )
        return body

    @staticmethod
    def _rank_todos(
        todos: list[tuple[Path, dict[str, Any]]],
    ) -> list[tuple[Path, int]]:
        """期望×价值×距离排序：概率×多效性×距离降序，等效性 tie-break，未估价排最后按创建时间。"""
        def score(meta: dict[str, Any]) -> tuple[int, ...] | None:
            if not all(
                key in meta
                for key in ("need_type", "goal_id", "equifinality", "multifinality", "success_probability", "distance", "specificity")
            ):
                return None
            p = VALUATION_LEVELS.get(meta.get("success_probability", ""), 0)
            m = VALUATION_LEVELS.get(meta.get("multifinality", ""), 0)
            d = DISTANCE_LEVELS.get(meta.get("distance", ""), 0)
            e = VALUATION_LEVELS.get(meta.get("equifinality", ""), 0)
            return (p * m * d, p, m, d, e)

        valued: list[tuple[Path, dict[str, Any], tuple[int, ...]]] = []
        unvalued: list[tuple[Path, dict[str, Any]]] = []
        for rel, meta in todos:
            s = score(meta)
            if s is None:
                unvalued.append((rel, meta))
            else:
                valued.append((rel, meta, s))
        valued.sort(
            key=lambda item: (
                -item[2][0], -item[2][1],
                -item[2][2], -item[2][3],
                item[0].as_posix(),
            )
        )
        unvalued.sort(key=lambda item: (item[1].get("created_at", ""), item[0].as_posix()))
        ranked: list[tuple[Path, int]] = []
        for rank, (rel, _, _) in enumerate(valued, start=1):
            ranked.append((rel, rank))
        for rank, (rel, _) in enumerate(unvalued, start=len(valued) + 1):
            ranked.append((rel, rank))
        return ranked

    def capture_update(
        self,
        note_id: str,
        *,
        text: str,
        confirmed_by_user: bool,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if not confirmed_by_user:
            raise ValidationError("轻量记录更新只能写入用户亲自确认的内容")
        if not _meaningful(text, minimum=8):
            raise ValidationError("更新内容必须包含用户明确的完整表达")
        found = self.repo.find_note(note_id)
        if not found or found[2].get("type") not in {
            "flash",
            "interesting",
            "todo",
        }:
            raise ValidationError(f"找不到轻量记录：{note_id}")
        rel, note_text, metadata = found
        txid = transaction_id or new_transaction_id("capture-update")
        if existing := self._idempotent(txid):
            return existing
        timestamp = now_iso()
        user_text = _normalize_user_entry(text)
        note_text = replace_section(note_text, "原始记录", user_text)
        metadata["updated_at"] = timestamp
        note_text = replace_frontmatter(note_text, metadata)
        state = self.repo.read_state()
        result = {
            "id": note_id,
            "path": rel.as_posix(),
            "type": metadata["type"],
        }
        return self.repo.commit(
            transaction_id=txid,
            action="capture-update",
            summary=metadata["title"],
            writes={rel: note_text},
            state=state,
            result=result,
        )

    def capture_retitle(
        self,
        note_id: str,
        *,
        title: str,
        confirmed_by_user: bool,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if not confirmed_by_user:
            raise ValidationError("标题修改只能写入用户亲自确认的新标题")
        new_title = title.strip()
        if not _meaningful(new_title, minimum=2):
            raise ValidationError("新标题必须包含实际含义")
        found = self.repo.find_note(note_id)
        if not found or found[2].get("type") not in {
            "flash",
            "interesting",
            "todo",
        }:
            raise ValidationError(f"找不到轻量记录：{note_id}")
        rel, text, metadata = found
        old_title = str(metadata.get("title", ""))
        if new_title == old_title:
            raise ValidationError("新标题与当前标题相同，无需修改")
        txid = transaction_id or new_transaction_id("capture-retitle")
        if existing := self._idempotent(txid):
            return existing
        timestamp = now_iso()
        note_type = metadata["type"]
        # 目标目录：todo 按状态归档保持当前目录；其余类型用固定目录
        if note_type == "todo":
            location = rel.parent
        else:
            location = TYPE_LOCATIONS[note_type]
        # 计算新路径；与现有文件冲突时递增序号（同 maintain-filenames 逻辑）
        reserved = {rel}
        collision = 1
        while True:
            candidate = location / dated_filename(
                new_title, str(metadata["created_at"]), collision=collision
            )
            if candidate not in reserved and not candidate.exists():
                break
            collision += 1
        new_rel = candidate
        metadata["title"] = new_title
        metadata["updated_at"] = timestamp
        # 更新正文首行标题，再写回 frontmatter
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("# "):
                lines[i] = f"# {new_title}"
                break
        updated_text = replace_frontmatter("\n".join(lines), metadata)
        writes: dict[Path, str | bytes] = {}
        deletes: set[Path] = set()
        if new_rel != rel:
            deletes.add(rel)
            # 全库重写引用旧路径/旧标题的 wikilink（来源快照受保护）
            replacements = {rel.with_suffix("").as_posix(): new_rel.with_suffix("").as_posix()}
            for note_type_, location_ in note_scan_entries():
                for path in sorted((self.repo.root / location_).glob("*.md")):
                    other_rel = path.relative_to(self.repo.root)
                    if other_rel == rel:
                        continue
                    note_text = path.read_text(encoding="utf-8")
                    note_meta, _ = parse_document(note_text)
                    protect = note_meta.get("type") == "source"
                    rewritten = _rewrite_wiki_paths(
                        note_text, replacements, protect_snapshot=protect
                    )
                    rewritten = _rewrite_default_alias(
                        rewritten,
                        new_rel.with_suffix("").as_posix(),
                        old_title,
                        new_title,
                        protect_snapshot=protect,
                    )
                    if rewritten != note_text:
                        writes[other_rel] = rewritten
            state = _rewrite_exact_paths(
                self.repo.read_state(), {rel.as_posix(): new_rel.as_posix()}
            )
        else:
            state = self.repo.read_state()
        writes[new_rel] = updated_text
        result = {
            "id": note_id,
            "path": new_rel.as_posix(),
            "type": note_type,
            "renamed": new_rel != rel,
            "from": rel.as_posix(),
            "to": new_rel.as_posix(),
        }
        return self.repo.commit(
            transaction_id=txid,
            action="capture-retitle",
            summary=new_title,
            writes=writes,
            deletes=deletes,
            state=state,
            result=result,
        )

    def capture_finalize(
        self,
        runtime: CaptureRuntime,
        session_id: str,
        *,
        proposal_id: str,
        confirmed_by_user: bool,
        transaction_id: str,
    ) -> dict[str, Any]:
        if not confirmed_by_user:
            raise ValidationError("正式生成闪念前必须确认最新清单已覆盖本轮内容")
        if existing := self._idempotent(transaction_id):
            record = existing.get("result", {})
            if (
                existing.get("action") == "capture-finalize"
                and record.get("session_id") == session_id
            ):
                try:
                    directory, session = runtime.load_for_finalize(session_id, proposal_id)
                except ValidationError:
                    directory = None
                    session = None
                if directory is not None and session is not None:
                    runtime.enqueue_maintenance(
                        session_id,
                        list(session.get("contexts", [])),
                        list(record.get("flashes", [])),
                    )
                    runtime.finalize_runtime(directory, session, formal_result=record)
            return existing
        directory, session = runtime.load_for_finalize(session_id, proposal_id)
        proposal = session["proposal"]
        entries = {entry["entry_id"]: entry for entry in session.get("entries", [])}
        timestamp = now_iso()
        writes: dict[Path, str] = {}
        reserved: set[Path] = set()
        formal_flashes: list[dict[str, Any]] = []
        for index, candidate in enumerate(proposal.get("flashes", [])):
            related_entries = [entries[item] for item in candidate["entry_ids"]]
            if any(entry.get("role") != "user" for entry in related_entries):
                raise ValidationError("正式闪念只能追溯到用户表达")
            created_at = min(str(entry["recorded_at"]) for entry in related_entries)
            flash_id = stable_id(
                "FLA",
                f"{session_id}:{proposal_id}:{index}:{candidate['body']}",
            )
            title = str(candidate["title"]).strip()
            rel = self._new_note_path(
                "flash", title, created_at, reserved=reserved
            )
            reserved.add(rel)
            metadata = {
                "id": flash_id,
                "type": "flash",
                "title": title,
                "status": "pending",
                "created_at": created_at,
                "updated_at": timestamp,
                "source_ids": [],
                # 讨论会话关联（2026-08-15：卡片可回溯到自己的讨论过程存档）
                "capture_session": session_id,
            }
            writes[rel] = render_flash_event(metadata, candidate)
            formal_flashes.append(
                {
                    "id": flash_id,
                    "path": rel.as_posix(),
                    "title": title,
                    "context_refs": list(candidate.get("context_refs", [])),
                    "source_anchors": list(candidate.get("source_anchors", [])),
                    "source_boundary": str(candidate.get("source_boundary") or ""),
                }
            )
        state = self.repo.read_state()
        result = {
            "session_id": session_id,
            "proposal_id": proposal_id,
            "flashes": formal_flashes,
            "flash_count": len(formal_flashes),
            "maintenance_job_ids": runtime.maintenance_job_ids(
                session_id, list(session.get("contexts", [])), formal_flashes
            ),
        }
        committed = self.repo.commit(
            transaction_id=transaction_id,
            action="capture-finalize",
            summary=f"确认本轮 {len(formal_flashes)} 张闪念",
            writes=writes,
            state=state,
            result=result,
            validate_sources=False,
        )
        runtime.enqueue_maintenance(
            session_id,
            list(session.get("contexts", [])),
            formal_flashes,
        )
        runtime.finalize_runtime(directory, session, formal_result=result)
        return committed

    def _download_image(
        self, url: str, image: dict[str, Any] | None
    ) -> tuple[bytes, str]:
        if image and image.get("data_base64"):
            data = base64.b64decode(image["data_base64"], validate=True)
            content_type = image.get("content_type", "")
        else:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 GoodIdea/0.1",
                    "Referer": image.get("referer", "") if image else "",
                },
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read(20 * 1024 * 1024)
                content_type = response.headers.get_content_type()
        if not data:
            raise ValidationError("图片内容为空")
        extension = mimetypes.guess_extension(content_type or "") or Path(
            urllib.parse.urlsplit(url).path
        ).suffix
        extension = extension.lower()
        if extension not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}:
            extension = ".bin"
        return data, extension

    def _localize_images(
        self, preview: dict[str, Any], *, maintenance_job_id: str = ""
    ) -> tuple[str, dict[Path, bytes], list[str]]:
        markdown = str(preview.get("markdown", ""))
        image_records = {
            str(item.get("url")): item
            for item in preview.get("images", [])
            if item.get("url")
        }
        remote_urls = [
            match.group(2)
            for match in re.finditer(
                r"!\[([^\]]*)\]\((https?://[^)]+)\)", markdown
            )
        ]
        local_record_urls = [
            url
            for url in image_records
            if f"]({url})" in markdown or f"](<{url}>)" in markdown
        ]
        urls = list(dict.fromkeys([*remote_urls, *local_record_urls]))
        writes: dict[Path, bytes] = {}
        failures: list[str] = []
        runtime = CaptureRuntime(self.repo.root) if maintenance_job_id else None
        for url in urls:
            try:
                cached = runtime.read_cached_asset(maintenance_job_id, url) if runtime else None
                if cached is not None:
                    data, extension = cached
                else:
                    data, extension = self._download_image(url, image_records.get(url))
                    if runtime:
                        runtime.cache_asset(maintenance_job_id, url, data, extension)
                digest = hashlib.sha256(data).hexdigest()
                rel = Path(f"assets/{digest}{extension}")
                writes[rel] = data
                markdown = markdown.replace(
                    f"]({url})", f"](../{rel.as_posix()})"
                )
                markdown = markdown.replace(
                    f"](<{url}>)", f"](../{rel.as_posix()})"
                )
            except Exception as exc:
                failures.append(f"{url}: {exc}")
                pattern = re.compile(
                    r"!\[([^\]]*)\]\((?:<)?" + re.escape(url) + r"(?:>)?\)"
                )
                markdown = pattern.sub(
                    lambda match: (
                        f"[图片未能保存：{match.group(1) or '无替代文本'}；"
                        f"原地址 {url}]"
                    ),
                    markdown,
                )
        return markdown, writes, failures

    def _build_snapshot(
        self, preview: dict[str, Any], localized_markdown: str
    ) -> str:
        lines: list[str] = []
        skip_author, skip_date = snapshot_has_context_header(localized_markdown)
        if preview.get("author") and not skip_author:
            lines.append(f"> 作者：{preview['author']}")
        if preview.get("published_at") and not skip_date:
            lines.append(f"> 发布日期：{preview['published_at']}")
        if preview.get("error"):
            lines.append(f"> 抓取说明：{preview['error']}")
        if lines:
            lines.append("")
        lines.append(localized_markdown or "> 未能取得正文。")
        return "\n".join(lines).strip("\n") + "\n"

    def source_commit(
        self,
        preview: dict[str, Any],
        *,
        motivation: str = "",
        attach_flash_ids: list[str] | None = None,
        anchor_explanation: str = "",
        maintenance_job_id: str = "",
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        attached_ids = list(dict.fromkeys(attach_flash_ids or []))
        if attached_ids and motivation.strip():
            raise ValidationError("关联已有闪念时不要重复提供保存动机")
        if not attached_ids:
            _ensure_motivation(motivation)
        txid = transaction_id or new_transaction_id("source-commit")
        if existing := self._idempotent(txid):
            if maintenance_job_id:
                runtime = CaptureRuntime(self.repo.root)
                job = runtime.get_maintenance_job(maintenance_job_id)
                desired = (
                    "partial"
                    if existing.get("result", {}).get("image_failures")
                    else "complete"
                )
                if job.get("status") not in {"partial", "complete"}:
                    runtime.update_maintenance_job(maintenance_job_id, status=desired)
            return existing
        preview, source_kind, identity_key, source_id = _persistable_source_preview(
            preview
        )
        fallback_title = (
            Path(str(preview["origin_filename"])).stem
            if source_kind == "local"
            else identity_key
        )
        title = str(preview.get("title") or fallback_title).strip()
        flash_ids = attached_ids or [stable_id("FLA", f"{txid}:{motivation}")]
        timestamp = now_iso()
        state = self.repo.read_state()
        writes: dict[Path, str | bytes] = {}
        failures: list[str] = []
        runtime = CaptureRuntime(self.repo.root) if maintenance_job_id else None
        if runtime:
            job = runtime.get_maintenance_job(maintenance_job_id)
            if job.get("kind") != "capture-source-maintenance":
                raise ValidationError("维护任务类型不能用于来源提交")
            if set(attached_ids) != set(job.get("flash_ids", [])):
                raise ValidationError("来源提交关联闪念与维护任务不一致")
        attached_flashes: list[tuple[Path, str, dict[str, Any]]] = []
        if attached_ids:
            for flash_id in flash_ids:
                found = self.repo.find_note(flash_id)
                if not found or found[2].get("type") != "flash":
                    raise ValidationError(f"找不到要关联的正式闪念：{flash_id}")
                attached_flashes.append(found)
        existing_source = self.repo.find_note(source_id)
        source_created = existing_source is None
        flash_title = motivation.strip().splitlines()[0][:40] if not attached_ids else ""

        if existing_source is not None:
            source_rel, source_note, source_meta = existing_source
            if source_meta.get("type") != "source":
                raise IntegrityError(f"来源 ID 与非来源内容冲突：{source_id}")
            stored_kind, stored_identity_key, stored_source_id = (
                _source_metadata_identity(source_meta)
            )
            if (
                stored_kind != source_kind
                or stored_identity_key != identity_key
                or stored_source_id != source_id
            ):
                raise IntegrityError(f"来源文件身份不一致：{identity_key}")
            source_title = source_meta["title"]
            if runtime:
                localized, assets, failures = self._localize_images(
                    preview, maintenance_job_id=maintenance_job_id
                )
                writes.update(assets)
                capture_status = str(preview.get("status") or "complete")
                if failures and capture_status == "complete":
                    capture_status = "partial"
                source_note = replace_source_snapshot(
                    source_note,
                    self._build_snapshot(preview, localized),
                    {
                        "status": capture_status,
                        "capture_status": capture_status,
                        "fetched_at": timestamp,
                        "updated_at": timestamp,
                        "content_sha256": hashlib.sha256(
                            str(preview.get("markdown", "")).encode("utf-8")
                        ).hexdigest(),
                        "image_failures": failures,
                    },
                )
                source_meta, _ = parse_document(source_note)
        else:
            localized, assets, failures = self._localize_images(
                preview, maintenance_job_id=maintenance_job_id
            )
            writes.update(assets)
            capture_status = str(preview.get("status") or "complete")
            if failures and capture_status == "complete":
                capture_status = "partial"
            snapshot = self._build_snapshot(preview, localized)
            source_rel = self._new_note_path("source", title, timestamp)
            source_title = title
            source_meta = {
                "id": source_id,
                "type": "source",
                "title": title,
                "status": capture_status,
                "capture_status": capture_status,
                "author": str(preview.get("author") or ""),
                "published_at": str(preview.get("published_at") or ""),
                "fetched_at": timestamp,
                "created_at": timestamp,
                "updated_at": timestamp,
                "content_sha256": hashlib.sha256(
                    str(preview.get("markdown", "")).encode("utf-8")
                ).hexdigest(),
                "image_failures": failures,
            }
            tags = list(preview.get("tags") or [])
            if tags:
                source_meta["tags"] = tags
            if source_kind == "web":
                source_meta["canonical_url"] = identity_key
            else:
                source_meta["origin_filename"] = preview["origin_filename"]
                source_meta["origin_sha256"] = preview["origin_sha256"]

        source_link = wiki_link(source_rel, source_title)
        flash_links: list[str] = []
        flash_paths: list[str] = []
        if attached_ids:
            for flash_rel, flash_note, flash_meta in attached_flashes:
                flash_meta["source_ids"] = list(
                    dict.fromkeys([*flash_meta.get("source_ids", []), source_id])
                )
                flash_meta["updated_at"] = timestamp
                explanation = (
                    str(
                        (job.get("anchor_explanations") or {}).get(flash_meta["id"])
                        or "该来源是本轮闪念使用的外部上下文；旧版维护任务未记录更具体的论证说明。"
                    ).strip()
                    if runtime
                    else anchor_explanation.strip()
                )
                if not explanation:
                    raise ValidationError("关联正式闪念时必须提供来源的论证作用")
                marker = "## 来源与论证锚点\n"
                start = flash_note.find(marker)
                current_links: list[tuple[str, str]] = []
                if start >= 0:
                    end = flash_note.find("\n## ", start + len(marker))
                    section = flash_note[start : end if end >= 0 else len(flash_note)]
                    for line in section.splitlines():
                        match = re.match(r"^- (\[\[.+?\]\])：(.+)$", line)
                        if match:
                            current_links.append((match.group(1), match.group(2)))
                current_links.append((source_link, explanation))
                current_links = list(dict.fromkeys(current_links))
                boundary = str(
                    (job.get("source_boundaries") or {}).get(flash_meta["id"]) or ""
                ) if runtime else ""
                flash_note = remove_section(flash_note, "关联来源")
                flash_note = replace_section(
                    flash_note,
                    "来源与论证锚点",
                    render_source_anchors(current_links, boundary=boundary),
                )
                writes[flash_rel] = replace_frontmatter(flash_note, flash_meta)
                flash_links.append(wiki_link(flash_rel, str(flash_meta["title"])))
                flash_paths.append(flash_rel.as_posix())
        else:
            flash_id = flash_ids[0]
            flash_rel = self._new_note_path("flash", flash_title, timestamp)
            flash_meta = {
                "id": flash_id,
                "type": "flash",
                "title": flash_title,
                "status": "pending",
                "created_at": timestamp,
                "updated_at": timestamp,
                "source_ids": [source_id],
            }
            flash_note = render_note(
                flash_meta,
                [
                    ("原始记录", motivation),
                    ("产生情境", "保存外部资料时形成的个人注意与保存动机。"),
                    (
                        "来源与论证锚点",
                        render_source_anchors([(source_link, motivation)]),
                    ),
                ],
            )
            writes[flash_rel] = flash_note
            flash_links.append(wiki_link(flash_rel, flash_title))
            flash_paths.append(flash_rel.as_posix())
        if existing_source is not None:
            source_meta["updated_at"] = timestamp
            for flash_link in flash_links:
                source_note = add_list_item_to_section(
                    source_note, "关联闪念", flash_link
                )
            source_note = replace_frontmatter(source_note, source_meta)
            source_note = normalize_source_layout(source_note)
        else:
            source_note = render_source_note(source_meta, snapshot, flash_links)
        writes[source_rel] = source_note
        result = {
            "source_id": source_id,
            "source_path": source_rel.as_posix(),
            "source_created": source_created,
            "flash_ids": flash_ids,
            "flash_paths": flash_paths,
            "flash_created": not bool(attached_ids),
            "image_failures": failures,
        }
        if not attached_ids:
            result["flash_id"] = flash_ids[0]
            result["flash_path"] = flash_paths[0]
        committed = self.repo.commit(
            transaction_id=txid,
            action="source-commit",
            summary=(
                f"{source_title} + 关联 {len(flash_ids)} 张闪念"
                if attached_ids
                else f"{source_title} + 保存动机"
            ),
            writes=writes,
            state=state,
            result=result,
        )
        if runtime:
            runtime.update_maintenance_job(
                maintenance_job_id, status="partial" if failures else "complete"
            )
        return committed

    def revise_flash_source_anchors(
        self,
        flash_id: str,
        *,
        anchors: list[dict[str, Any]],
        boundary: str = "",
        confirmed_by_user: bool,
        transaction_id: str,
    ) -> dict[str, Any]:
        if not confirmed_by_user:
            raise ValidationError("修正闪念来源锚点前必须得到用户确认")
        if existing := self._idempotent(transaction_id):
            return existing
        found = self.repo.find_note(flash_id)
        if not found or found[2].get("type") != "flash":
            raise ValidationError(f"找不到正式闪念：{flash_id}")
        flash_rel, flash_note, flash_meta = found
        rendered: list[tuple[str, str]] = []
        source_ids: list[str] = []
        for anchor in anchors:
            source_id = str(anchor.get("source_id") or "").strip()
            explanation = str(anchor.get("explanation") or "").strip()
            source = self.repo.find_note(source_id)
            if not source or source[2].get("type") != "source" or not explanation:
                raise ValidationError("每个来源锚点都必须引用有效来源并说明论证作用")
            rendered.append((wiki_link(source[0], str(source[2]["title"])), explanation))
            source_ids.append(source_id)
        if not rendered:
            raise ValidationError("至少需要一个来源锚点")
        if set(source_ids) != set(flash_meta.get("source_ids", [])):
            raise ValidationError("来源锚点必须与闪念 Frontmatter 的来源集合一致")
        flash_meta["updated_at"] = now_iso()
        flash_note = remove_section(flash_note, "关联来源")
        flash_note = replace_section(
            flash_note,
            "来源与论证锚点",
            render_source_anchors(rendered, boundary=boundary),
        )
        flash_note = replace_frontmatter(flash_note, flash_meta)
        return self.repo.commit(
            transaction_id=transaction_id,
            action="capture-revise-source-anchors",
            summary=f"修正《{flash_meta['title']}》来源与论证锚点",
            writes={flash_rel: flash_note},
            state=self.repo.read_state(),
            result={"flash_id": flash_id, "path": flash_rel.as_posix()},
        )

    def source_refresh(
        self,
        source_id: str,
        *,
        preview: dict[str, Any] | None = None,
        confirm_proposal: str = "",
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        found = self.repo.find_note(source_id)
        if not found or found[2].get("type") != "source":
            raise ValidationError(f"找不到来源：{source_id}")
        source_rel, source_note, source_meta = found
        txid = transaction_id or new_transaction_id("source-refresh")
        if existing := self._idempotent(txid):
            return existing
        state = self.repo.read_state()
        source_kind, source_identity_key, expected_source_id = (
            _source_metadata_identity(source_meta)
        )
        source_is_local = source_kind == "local"
        if expected_source_id != source_id:
            raise IntegrityError(f"来源文件 ID 与身份不一致：{source_id}")

        if confirm_proposal:
            if source_meta.get("pending_update") != confirm_proposal:
                raise IntegrityError("来源文件当前待处理候选与确认目标不一致")
            proposal_rel, proposal_text, _ = _pending_proposal(
                self.repo.root,
                "source-updates",
                confirm_proposal,
                "source_update_proposal",
            )
            payload = _proposal_payload(proposal_text)
            if payload.get("source_id") != source_id:
                raise ValidationError("更新候选与目标来源不一致")
            candidate, candidate_kind, candidate_identity_key, _ = (
                _persistable_source_preview(payload["preview"])
            )
            candidate_content_sha256 = hashlib.sha256(
                str(candidate.get("markdown", "")).encode("utf-8")
            ).hexdigest()
            if payload.get("old_content_sha256") != source_meta.get(
                "content_sha256"
            ):
                raise IntegrityError("来源更新候选的旧内容哈希已失效")
            if payload.get("new_content_sha256") != candidate_content_sha256:
                raise IntegrityError("来源更新候选的新内容哈希与 preview 不一致")
            if source_is_local != (candidate_kind == "local"):
                raise ValidationError("更新候选的来源类型与目标来源不一致")
            if not source_is_local and candidate_identity_key != source_identity_key:
                raise ValidationError("网页更新候选的规范链接与目标来源不一致")
            localized, assets, failures = self._localize_images(candidate)
            capture_status = str(candidate.get("status") or "complete")
            if failures and capture_status == "complete":
                capture_status = "partial"
            snapshot = self._build_snapshot(candidate, localized)
            timestamp = now_iso()
            metadata_updates = {
                "title": str(candidate.get("title") or source_meta["title"]),
                "status": capture_status,
                "capture_status": capture_status,
                "author": str(candidate.get("author") or ""),
                "published_at": str(candidate.get("published_at") or ""),
                "fetched_at": timestamp,
                "updated_at": timestamp,
                "content_sha256": candidate_content_sha256,
                "image_failures": failures,
                "pending_update": "",
            }
            if source_is_local:
                # origin_sha256 is the immutable first-import identity seed.
                # A refresh may come from changed bytes or a moved/renamed copy,
                # but origin metadata continues to describe the first import.
                metadata_updates["origin_filename"] = source_meta["origin_filename"]
                metadata_updates["origin_sha256"] = source_meta["origin_sha256"]
            updated_source = replace_source_snapshot(
                source_note,
                snapshot,
                metadata_updates,
            )
            updated_source = normalize_source_layout(updated_source)
            updated_meta, _ = parse_document(updated_source)
            new_title = str(updated_meta["title"])
            new_source_rel = source_rel
            if new_title != str(source_meta["title"]):
                collision = 1
                while True:
                    candidate_rel = TYPE_LOCATIONS["source"] / dated_filename(
                        new_title,
                        str(source_meta["created_at"]),
                        collision=collision,
                    )
                    if candidate_rel == source_rel or not (
                        self.repo.root / candidate_rel
                    ).exists():
                        new_source_rel = candidate_rel
                        break
                    collision += 1
            writes: dict[Path, str | bytes] = {**assets}
            deletes: set[Path] = {proposal_rel}
            if new_source_rel != source_rel:
                wiki_replacements = {
                    source_rel.with_suffix("").as_posix():
                    new_source_rel.with_suffix("").as_posix()
                }
                for note_type, location in note_scan_entries():
                    for path in sorted((self.repo.root / location).glob("*.md")):
                        rel = path.relative_to(self.repo.root)
                        note_text = (
                            updated_source
                            if rel == source_rel
                            else path.read_text(encoding="utf-8")
                        )
                        rewritten = _rewrite_wiki_paths(
                            note_text,
                            wiki_replacements,
                            protect_snapshot=note_type == "source",
                        )
                        rewritten = _rewrite_default_alias(
                            rewritten,
                            new_source_rel.with_suffix("").as_posix(),
                            str(source_meta["title"]),
                            new_title,
                            protect_snapshot=note_type == "source",
                        )
                        target_rel = new_source_rel if rel == source_rel else rel
                        if target_rel != rel or rewritten != note_text:
                            writes[target_rel] = rewritten
                deletes.add(source_rel)
            else:
                writes[source_rel] = updated_source
            result = {
                "source_id": source_id,
                "source_path": new_source_rel.as_posix(),
                "proposal_id": confirm_proposal,
                "status": capture_status,
            }
            return self.repo.commit(
                transaction_id=txid,
                action="source-refresh-accept",
                summary=source_meta["title"],
                writes=writes,
                deletes=deletes,
                state=state,
                result=result,
            )

        if preview is None:
            raise ValidationError("生成更新候选时必须提供新的 preview")
        preview, candidate_kind, candidate_identity_key, _ = (
            _persistable_source_preview(preview)
        )
        if source_is_local != (candidate_kind == "local"):
            raise ValidationError("更新候选的来源类型与目标来源不一致")
        if not source_is_local and candidate_identity_key != source_identity_key:
            raise ValidationError("网页更新候选的规范链接与目标来源不一致")
        candidate_hash = hashlib.sha256(
            str(preview.get("markdown", "")).encode("utf-8")
        ).hexdigest()
        if candidate_hash == source_meta.get("content_sha256"):
            return {
                "idempotent": True,
                "no_change": True,
                "source_id": source_id,
            }
        proposal_id = stable_id("PRP", f"source-refresh:{source_id}:{txid}", dated=False)
        proposal_rel = Path(
            f".goodidea/proposals/source-updates/{proposal_id}.md"
        )
        timestamp = now_iso()
        payload = {
            "source_id": source_id,
            "old_content_sha256": source_meta.get("content_sha256", ""),
            "new_content_sha256": candidate_hash,
            "preview": preview,
        }
        proposal_meta = {
            "id": proposal_id,
            "type": "source_update_proposal",
            "title": f"来源更新候选：{source_meta['title']}",
            "status": "pending",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        proposal_text = _proposal_document(proposal_meta, payload)
        source_meta["status"] = "update_available"
        source_meta["pending_update"] = proposal_id
        source_meta["updated_at"] = timestamp
        updated_source = replace_frontmatter(source_note, source_meta)
        result = {
            "source_id": source_id,
            "proposal_id": proposal_id,
            "proposal_path": proposal_rel.as_posix(),
            "status": "update_available",
        }
        return self.repo.commit(
            transaction_id=txid,
            action="source-refresh-propose",
            summary=source_meta["title"],
            writes={proposal_rel: proposal_text, source_rel: updated_source},
            state=state,
            result=result,
        )

    def permanent_propose(
        self,
        card_type: str,
        *,
        draft: str,
        title: str = "",
        user_approved_structure: bool = False,
        source_ids: list[str] | None = None,
        from_ids: list[str] | None = None,
        direct_source: str = "",
        formation_sources_confirmed: bool = False,
        preauthorize_accept: bool = False,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if card_type not in PERMANENT_CARD_TYPES:
            raise ValidationError(f"不支持的永久卡片类型：{card_type}")
        title, user_draft, draft_sha256, authoring_mode = _prepare_permanent_draft(
            draft, title, user_approved_structure
        )
        txid = transaction_id or new_transaction_id("permanent-propose")
        accept_txid = f"{txid}-accept" if preauthorize_accept else ""
        if existing := self._idempotent(txid):
            if not accept_txid:
                return existing
            # 预授权重放：propose 事务已提交；accept 已完成则返回原结果，
            # 未完成（如首次运行在 accept 前异常中断）则继续完成 accept，候选不残留。
            if accepted := self._idempotent(accept_txid):
                return accepted
            return self._preauthorized_accept(
                existing["result"]["proposal_id"], accept_txid
            )
        proposal_id = stable_id("PRP", f"{card_type}:{txid}", dated=False)
        proposal_rel = Path(f".goodidea/proposals/permanent/{proposal_id}.md")
        timestamp = now_iso()
        checked_source_ids = list(dict.fromkeys(source_ids or []))
        checked_from_ids = list(dict.fromkeys(from_ids or []))
        direct_source_anchor = ""
        direct_source_sha256 = ""
        if card_type == "permanent":
            if not formation_sources_confirmed:
                raise ValidationError("普通永久卡片必须先由用户确认形成来源")
            if "## 形成来源\n" in user_draft:
                raise ValidationError("普通永久卡片的“形成来源”是 CLI 维护区，请勿写入用户草稿")
            if direct_source.strip():
                direct_source_anchor, direct_source_sha256 = (
                    _normalize_direct_source(direct_source)
                )
            if not checked_from_ids and not direct_source_anchor:
                raise ValidationError(
                    "普通永久卡片必须引用至少一个形成来源，或提供本轮直接表达形成说明"
                )
        elif direct_source.strip() or formation_sources_confirmed:
            raise ValidationError(
                "直接表达来源和形成来源确认参数只适用于普通永久卡片"
            )
        for note_id in checked_source_ids + checked_from_ids:
            found = self.repo.find_note(note_id)
            if not found:
                raise ValidationError(f"用户草稿引用了不存在的对象：{note_id}")
            if (
                card_type == "permanent"
                and note_id in checked_source_ids
                and found[2].get("type") != "source"
            ):
                raise ValidationError(f"普通永久卡片的外部依据不是来源对象：{note_id}")
            if (
                card_type == "permanent"
                and note_id in checked_from_ids
                and found[2].get("type") not in {*NOTE_SPECS, "formation_witness"}
            ):
                raise ValidationError(f"普通永久卡片的形成来源类型非法：{note_id}")
        proposal_meta = {
            "id": proposal_id,
            "type": "permanent_proposal",
            "title": title,
            "status": "pending",
            "card_type": card_type,
            "authoring_mode": authoring_mode,
            "draft_sha256": draft_sha256,
            "source_ids": checked_source_ids,
            "from_ids": checked_from_ids,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        if card_type == "permanent":
            proposal_meta["formation_sources_confirmed"] = True
            if direct_source_anchor:
                proposal_meta["direct_source_anchor"] = direct_source_anchor
                proposal_meta["direct_source_sha256"] = direct_source_sha256
        proposal_text = dump_frontmatter(proposal_meta) + user_draft
        state = self.repo.read_state()
        result = {
            "proposal_id": proposal_id,
            "proposal_path": proposal_rel.as_posix(),
            "card_type": card_type,
        }
        result = self.repo.commit(
            transaction_id=txid,
            action="permanent-propose",
            summary=title,
            writes={proposal_rel: proposal_text},
            state=state,
            result=result,
        )
        if accept_txid:
            # 预授权：同一调用内继续执行 accept 全部校验并创建正式卡片。
            return self._preauthorized_accept(
                result["result"]["proposal_id"], accept_txid
            )
        return result

    def _preauthorized_accept(
        self, proposal_id: str, accept_txid: str
    ) -> dict[str, Any]:
        """预授权模式下完成 accept：所有 accept 门禁原样执行，不因预授权放宽。

        预授权只在时机上提前了“用户的明确创建确认”：
        ``--preauthorize-accept`` 是用户在确认草稿时同时给出的创建授权，
        等价于 accept 门禁要求的“候选形成后的明确创建确认”。
        """
        accepted = self.permanent_accept(
            proposal_id,
            confirmed_by_user=True,
            transaction_id=accept_txid,
        )
        return accepted

    def permanent_accept(
        self,
        proposal_id: str,
        *,
        confirmed_by_user: bool,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if not confirmed_by_user:
            raise ValidationError(
                "只有用户审查自己的草稿并明确发起正式创建后，才能接纳永久卡片"
            )
        txid = transaction_id or new_transaction_id("permanent-accept")
        if existing := self._idempotent(txid):
            return existing
        state = self.repo.read_state()
        proposal_rel, proposal_text, proposal_meta = _pending_proposal(
            self.repo.root, "permanent", proposal_id, "permanent_proposal"
        )
        authoring_mode = proposal_meta.get("authoring_mode")
        if authoring_mode not in {
            "user_verbatim",
            "user_body_agent_title",
            "user_confirmed_agent_structured",
        }:
            raise ValidationError("该候选不是用户原文草稿，禁止接纳；请撤销后由用户重新发起")
        _, user_draft = parse_document(proposal_text)
        title, normalized_draft, draft_sha256 = _validate_user_draft(user_draft)
        expected_sha256 = proposal_meta.get("draft_sha256")
        card_type = proposal_meta.get("card_type")
        if card_type not in PERMANENT_CARD_TYPES:
            raise IntegrityError("永久卡片草稿类型非法")
        raw_source_ids = proposal_meta.get("source_ids", [])
        raw_from_ids = proposal_meta.get("from_ids", [])
        if not isinstance(raw_source_ids, list) or not isinstance(raw_from_ids, list):
            raise IntegrityError("永久卡片候选的来源字段必须是 ID 列表")
        checked_source_ids = list(dict.fromkeys(raw_source_ids))
        checked_from_ids = list(dict.fromkeys(raw_from_ids))
        found_sources: dict[str, tuple[Path, str, dict[str, Any]]] = {}
        for note_id in checked_source_ids + checked_from_ids:
            found = self.repo.find_note(note_id)
            if not found:
                raise IntegrityError(f"永久卡片候选引用的对象已不存在：{note_id}")
            found_sources[note_id] = found
        direct_source_anchor = ""
        direct_source_sha256 = ""
        if card_type == "permanent":
            if proposal_meta.get("formation_sources_confirmed") is not True:
                raise ValidationError("普通永久卡片候选缺少用户形成来源确认")
            for source_id in checked_source_ids:
                if found_sources[source_id][2].get("type") != "source":
                    raise IntegrityError(f"普通永久卡片的外部依据不是来源对象：{source_id}")
            for from_id in checked_from_ids:
                if found_sources[from_id][2].get("type") not in {
                    *NOTE_SPECS,
                    "formation_witness",
                }:
                    raise IntegrityError(f"普通永久卡片的形成来源类型非法：{from_id}")
            raw_direct_source = str(proposal_meta.get("direct_source_anchor") or "")
            if raw_direct_source:
                direct_source_anchor, direct_source_sha256 = (
                    _normalize_direct_source(raw_direct_source)
                )
                if direct_source_sha256 != proposal_meta.get("direct_source_sha256"):
                    raise IntegrityError("直接口述形成说明哈希异常")
            elif "direct_source_sha256" in proposal_meta:
                raise IntegrityError("直接口述形成说明字段不完整")
            if not checked_from_ids and not direct_source_anchor:
                raise ValidationError("普通永久卡片候选没有可接纳的形成来源")
        mirrored_fields = {
            "id": proposal_id,
            "type": "permanent_proposal",
            "status": "pending",
            "card_type": card_type,
            "authoring_mode": authoring_mode,
            "title": title,
            "draft_sha256": expected_sha256,
        }
        for key, expected in mirrored_fields.items():
            if proposal_meta.get(key) != expected:
                raise IntegrityError(f"永久卡片草稿 Frontmatter 与账本不一致：{key}")
        if (
            not expected_sha256
            or draft_sha256 != expected_sha256
        ):
            raise IntegrityError("用户草稿内容哈希异常；停止发布，需重新提交审查")
        prefix = {
            "permanent": "PER",
            "mother": "MOT",
            "action": "ACT",
            "index": "IDX",
        }[card_type]
        card_id = stable_id(prefix, f"{proposal_id}:{draft_sha256}")
        timestamp = now_iso()
        card_rel = self._new_note_path(card_type, title, timestamp)
        status = _default_status(card_type)
        witness_id = ""
        witness_rel: Path | None = None
        derived_from = list(checked_from_ids)
        if card_type == "permanent" and direct_source_anchor:
            witness_id = stable_id(
                "WIT", f"{proposal_id}:{direct_source_sha256}", dated=False
            )
            witness_rel = FORMATION_WITNESS_ROOT / f"{witness_id}.md"
            if (self.repo.root / witness_rel).exists():
                raise IntegrityError(f"形成来源见证已存在：{witness_id}")
            derived_from.append(witness_id)
        derived_from = list(dict.fromkeys(derived_from))
        if card_type == "permanent" and not derived_from:
            raise ValidationError("普通永久卡片必须具有至少一个可寻址形成来源")
        metadata = {
            "id": card_id,
            "type": card_type,
            "title": title,
            "status": status,
            "created_at": timestamp,
            "updated_at": timestamp,
            "authoring_mode": authoring_mode,
            "source_ids": checked_source_ids,
            "derived_from": derived_from,
        }
        if card_type == "permanent":
            metadata["formation_draft_sha256"] = draft_sha256
        card_body = normalized_draft
        for from_id in checked_from_ids:
            found = found_sources[from_id]
            card_body = add_list_item_to_section(
                card_body,
                "形成来源",
                f"形成于 {wiki_link(found[0], found[2]['title'])}",
            )
        writes: dict[Path, str | bytes] = {}
        deletes: set[Path] = set()
        # 形成来源闪念：pending→processed 并归档到 闪念空间/已处理/，全库引用同步重写
        flash_moves: list[tuple[Path, Path]] = []
        for from_id in checked_from_ids:
            found = found_sources[from_id]
            if found[2].get("type") != "flash":
                continue
            from_rel, from_text, from_meta = found
            if from_meta.get("status") == "dismissed":
                raise ValidationError(f"已放弃闪念不能直接作为形成来源：{from_id}")
            if from_meta.get("status") == "processed":
                continue
            if from_meta.get("status") not in {"pending", "fermenting"}:
                raise IntegrityError(f"闪念状态不能转换为已处理：{from_id}")
            from_meta = copy.deepcopy(from_meta)
            from_meta["status"] = "processed"
            from_meta["updated_at"] = timestamp
            reloc_writes, reloc_deletes, target_rel = self._relocate_note(
                from_rel, "processed", FLASH_STATUS_DIRS
            )
            writes.update(reloc_writes)
            deletes.update(reloc_deletes)
            flash_moves.append((from_rel, target_rel))
            from_text = _rewrite_wiki_paths(
                from_text,
                {
                    from_rel.with_suffix("").as_posix(): target_rel.with_suffix("").as_posix()
                },
                protect_snapshot=False,
            )
            writes[target_rel] = replace_frontmatter(from_text, from_meta)
        if flash_moves:
            # 永久卡"形成来源"导航区链接指向归档后的新路径
            replacements = {
                old.with_suffix("").as_posix(): new.with_suffix("").as_posix()
                for old, new in flash_moves
            }
            card_body = _rewrite_wiki_paths(
                card_body, replacements, protect_snapshot=False
            )
        if witness_rel is not None:
            witness_metadata = {
                "id": witness_id,
                "type": "formation_witness",
                "title": "本轮直接表达形成来源",
                "created_at": timestamp,
                "card_id": card_id,
                "proposal_id": proposal_id,
                "draft_sha256": draft_sha256,
                "source_anchor_sha256": direct_source_sha256,
            }
            writes[witness_rel] = _render_formation_witness(
                witness_metadata, direct_source_anchor, card_rel, title
            )
            card_body = add_list_item_to_section(
                card_body,
                "形成来源",
                (
                    f"形成于 {wiki_link(witness_rel, '本轮直接表达形成来源')}："
                    f"{direct_source_anchor}"
                ),
            )
        card_text = dump_frontmatter(metadata) + card_body
        writes[card_rel] = card_text
        result = {
            "proposal_id": proposal_id,
            "card_id": card_id,
            "card_path": card_rel.as_posix(),
            "card_type": card_type,
        }
        if witness_id:
            result["formation_witness_id"] = witness_id
            result["formation_witness_path"] = witness_rel.as_posix()
        return self.repo.commit(
            transaction_id=txid,
            action="permanent-accept",
            summary=title,
            writes=writes,
            deletes=deletes | {proposal_rel},
            state=state,
            result=result,
        )

    def permanent_withdraw(
        self,
        proposal_id: str,
        *,
        reason: str,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if not _meaningful(reason, minimum=6):
            raise ValidationError("撤销永久卡片草稿时必须记录明确原因")
        txid = transaction_id or new_transaction_id("permanent-withdraw")
        if existing := self._idempotent(txid):
            return existing
        state = self.repo.read_state()
        proposal_rel, _, _ = _pending_proposal(
            self.repo.root, "permanent", proposal_id, "permanent_proposal"
        )
        result = {
            "proposal_id": proposal_id,
            "status": "withdrawn",
            "reason": reason.strip(),
        }
        return self.repo.commit(
            transaction_id=txid,
            action="permanent-withdraw",
            summary=f"撤销 {proposal_id}",
            writes={},
            deletes={proposal_rel},
            state=state,
            result=result,
        )

    def permanent_revise(
        self,
        card_id: str,
        *,
        note: str,
        confirmed_by_user: bool,
        status: str = "",
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if not confirmed_by_user:
            raise ValidationError("永久卡片修订只能逐字追加用户亲自写下的内容")
        if not _meaningful(note, minimum=8):
            raise ValidationError("演化记录必须包含用户明确的修正或新认识")
        found = self.repo.find_note(card_id)
        if not found or found[2].get("type") not in {
            "permanent",
            "mother",
            "action",
            "index",
        }:
            raise ValidationError(f"找不到正式卡片：{card_id}")
        rel, text, metadata = found
        allowed = NOTE_SPECS[metadata["type"]]["statuses"]
        if status and status not in allowed:
            raise ValidationError(
                f"{metadata['type']} 不允许状态 {status}；可选：{sorted(allowed)}"
            )
        txid = transaction_id or new_transaction_id("permanent-revise")
        if existing := self._idempotent(txid):
            return existing
        timestamp = now_iso()
        user_note = _normalize_user_entry(note)
        text = add_list_item_to_section(text, "演化记录", f"{timestamp} — {user_note}")
        metadata["updated_at"] = timestamp
        metadata["status"] = status or (
            "evolving" if metadata["type"] == "mother" else "revised"
        )
        if metadata["type"] == "action" and not status:
            metadata["status"] = "observing"
        text = replace_frontmatter(text, metadata)
        state = self.repo.read_state()
        result = {
            "card_id": card_id,
            "card_path": rel.as_posix(),
            "status": metadata["status"],
        }
        return self.repo.commit(
            transaction_id=txid,
            action="permanent-revise",
            summary=metadata["title"],
            writes={rel: text},
            state=state,
            result=result,
        )

    def action_feedback(
        self,
        card_id: str,
        *,
        result_text: str,
        adjustment: str,
        confirmed_by_user: bool,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if not confirmed_by_user:
            raise ValidationError("行动结果与修正只能逐字追加用户亲自写下的内容")
        if not _meaningful(result_text, minimum=4) or not _meaningful(
            adjustment, minimum=4
        ):
            raise ValidationError("行动反馈必须同时包含现实结果和后续修正")
        found = self.repo.find_note(card_id)
        if not found or found[2].get("type") != "action":
            raise ValidationError(f"找不到行动卡片：{card_id}")
        rel, text, metadata = found
        txid = transaction_id or new_transaction_id("action-feedback")
        if existing := self._idempotent(txid):
            return existing
        timestamp = now_iso()
        user_result = _normalize_user_entry(result_text)
        user_adjustment = _normalize_user_entry(adjustment)
        text = add_list_item_to_section(text, "结果", f"{timestamp} — {user_result}")
        text = add_list_item_to_section(text, "修正", f"{timestamp} — {user_adjustment}")
        metadata["status"] = "reviewed"
        metadata["updated_at"] = timestamp
        text = replace_frontmatter(text, metadata)
        state = self.repo.read_state()
        result = {
            "card_id": card_id,
            "card_path": rel.as_posix(),
            "status": "reviewed",
        }
        return self.repo.commit(
            transaction_id=txid,
            action="action-feedback",
            summary=metadata["title"],
            writes={rel: text},
            state=state,
            result=result,
        )

    def maintain_filenames(
        self,
        *,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        txid = transaction_id or new_transaction_id("maintain-filenames")
        if existing := self._idempotent(txid):
            return existing
        self.repo.preflight_integrity()
        notes: list[tuple[Path, str, dict[str, Any]]] = []
        for note_type, location in note_scan_entries():
            for path in sorted((self.repo.root / location).glob("*.md")):
                rel = path.relative_to(self.repo.root)
                text = path.read_text(encoding="utf-8")
                metadata, _ = parse_document(text)
                if metadata.get("type") != note_type:
                    raise IntegrityError(f"{rel} 的类型与所在目录不一致")
                notes.append((rel, text, metadata))

        reserved: set[Path] = set()
        renames: dict[Path, Path] = {}
        for old_rel, _, metadata in sorted(
            notes,
            key=lambda item: (
                str(item[2].get("created_at", "")),
                str(item[2].get("id", "")),
                item[0].as_posix(),
            ),
        ):
            # todo 按状态归档：candidate 保持在当前状态目录，不把已完成/已取消移回根目录
            if metadata["type"] == "todo":
                location = old_rel.parent
            else:
                location = TYPE_LOCATIONS[str(metadata["type"])]
            collision = 1
            while True:
                candidate = location / dated_filename(
                    str(metadata["title"]),
                    str(metadata["created_at"]),
                    collision=collision,
                )
                if candidate not in reserved:
                    break
                collision += 1
            reserved.add(candidate)
            if candidate != old_rel:
                renames[old_rel] = candidate

        if not renames:
            state = self.repo.read_state()
            result = {"no_change": True, "renamed": [], "count": 0}
            return self.repo.commit(
                transaction_id=txid,
                action="maintain-filenames",
                summary="内容文件名已经符合日期加标题规范",
                writes={},
                state=state,
                result=result,
            )

        replacements = {
            old.with_suffix("").as_posix(): new.with_suffix("").as_posix()
            for old, new in renames.items()
        }
        writes: dict[Path, str | bytes] = {}
        deletes: set[Path] = set()
        renamed_result: list[dict[str, str]] = []
        for old_rel, text, metadata in notes:
            updated = _rewrite_wiki_paths(
                text,
                replacements,
                protect_snapshot=metadata.get("type") == "source",
            )
            new_rel = renames.get(old_rel, old_rel)
            if new_rel != old_rel:
                deletes.add(old_rel)
                renamed_result.append(
                    {
                        "from": old_rel.as_posix(),
                        "to": new_rel.as_posix(),
                    }
                )
            if new_rel != old_rel or updated != text:
                writes[new_rel] = updated

        state = _rewrite_exact_paths(
            self.repo.read_state(),
            {old.as_posix(): new.as_posix() for old, new in renames.items()},
        )
        # Rename chains and swaps may reuse an old path as another note's final
        # destination. Such destinations are overwritten by writes, not deleted.
        deletes.difference_update(writes)
        result = {"renamed": renamed_result, "count": len(renamed_result)}
        return self.repo.commit(
            transaction_id=txid,
            action="maintain-filenames",
            summary=f"将 {len(renamed_result)} 个内容文件改为日期加标题",
            writes=writes,
            deletes=deletes,
            state=state,
            result=result,
        )

    def maintain_sources(
        self,
        *,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        txid = transaction_id or new_transaction_id("maintain-sources")
        if existing := self._idempotent(txid):
            return existing
        self.repo.preflight_integrity()
        writes: dict[Path, str | bytes] = {}
        changed: list[str] = []
        for path in sorted((self.repo.root / TYPE_LOCATIONS["source"]).glob("*.md")):
            rel = path.relative_to(self.repo.root)
            original = path.read_text(encoding="utf-8")
            normalized = normalize_source_layout(original)
            if normalized != original:
                writes[rel] = normalized
                changed.append(rel.as_posix())
        state = self.repo.read_state()
        result = {"changed": changed, "count": len(changed)}
        summary = (
            f"规范化 {len(changed)} 份来源快照"
            if changed
            else "来源快照已经符合当前格式"
        )
        return self.repo.commit(
            transaction_id=txid,
            action="maintain-sources",
            summary=summary,
            writes=writes,
            state=state,
            result=result,
        )

    def maintain_index(
        self,
        *,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        txid = transaction_id or new_transaction_id("maintain-index")
        if existing := self._idempotent(txid):
            return existing
        expected = self.repo.generate_index({})
        current = (self.repo.root / "index.md").read_text(encoding="utf-8")
        state = self.repo.read_state()
        if current == expected:
            return self.repo.commit(
                transaction_id=txid,
                action="maintain-index",
                summary="内容索引已经符合无摘要展示规范",
                writes={},
                state=state,
                result={"no_change": True},
            )
        return self.repo.commit(
            transaction_id=txid,
            action="maintain-index",
            summary="重新生成不展示摘要的内容索引",
            writes={},
            state=state,
            result={"no_change": False},
        )

    def maintain_metadata(
        self,
        *,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        txid = transaction_id or new_transaction_id("maintain-metadata")
        if existing := self._idempotent(txid):
            return existing
        self.repo.preflight_integrity()
        writes: dict[Path, str | bytes] = {}
        changed: list[str] = []
        for location in TYPE_LOCATIONS.values():
            for path in sorted((self.repo.root / location).glob("*.md")):
                rel = path.relative_to(self.repo.root)
                text = path.read_text(encoding="utf-8")
                metadata, _ = parse_document(text)
                if "summary" not in metadata:
                    continue
                metadata.pop("summary")
                writes[rel] = replace_frontmatter(text, metadata)
                changed.append(rel.as_posix())
        state = self.repo.read_state()
        result = {
            "no_change": not changed,
            "changed": changed,
            "count": len(changed),
        }
        summary = (
            f"从 {len(changed)} 份正式内容移除过时摘要字段"
            if changed
            else "正式内容已经不包含摘要字段"
        )
        return self.repo.commit(
            transaction_id=txid,
            action="maintain-metadata",
            summary=summary,
            writes=writes,
            state=state,
            result=result,
        )

    def maintain_source_tags(
        self,
        *,
        source_id: str,
        tags: list[str],
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        """设置或清除来源的可选渠道标签（用户命名的高辨识度实体名）。

        只改 Frontmatter 的 tags 字段，不触碰快照区、不触发哈希变化。
        传空列表即清除标签；重跑同命令传新值即整体替换（修正路径）。
        标签约束：全中文专有名词、去重；数量由对话层与用户商定，不做上限校验。
        """
        txid = transaction_id or new_transaction_id("maintain-source-tags")
        if existing := self._idempotent(txid):
            return existing
        self.repo.preflight_integrity()
        found = self.repo.find_note(source_id)
        if not found or found[2].get("type") != "source":
            raise ValidationError(f"找不到要打标签的来源：{source_id}")
        source_rel, source_note, source_meta = found
        cleaned: list[str] = []
        for tag in tags:
            tag = str(tag).strip()
            if not tag:
                continue
            if not re.fullmatch(r"[\u4e00-\u9fff]+", tag):
                raise ValidationError(f"来源标签必须是全中文专有名词：{tag}")
            if tag not in cleaned:
                cleaned.append(tag)
        current = list(source_meta.get("tags") or [])
        writes: dict[Path, str | bytes] = {}
        if current != cleaned:
            metadata = dict(source_meta)
            if cleaned:
                metadata["tags"] = cleaned
            else:
                metadata.pop("tags", None)
            writes[source_rel] = replace_frontmatter(source_note, metadata)
        state = self.repo.read_state()
        result = {
            "no_change": not writes,
            "changed": [rel.as_posix() for rel in writes],
            "tags": cleaned,
        }
        summary = (
            f"来源标签已更新：{source_meta['title']} → {cleaned}"
            if writes
            else (
                f"来源标签无变化：{source_meta['title']}"
                if cleaned
                else f"来源没有标签可清除：{source_meta['title']}"
            )
        )
        return self.repo.commit(
            transaction_id=txid,
            action="maintain-source-tags",
            summary=summary,
            writes=writes,
            state=state,
            result=result,
        )

    def maintain_contracts(
        self, *, transaction_id: str | None = None
    ) -> dict[str, Any]:
        """Make files canonical and remove state or terminal-proposal mirrors."""
        txid = transaction_id or new_transaction_id("maintain-contracts")
        if existing := self._idempotent(txid):
            return existing
        state = self.repo.read_state()
        legacy_proposals = state.pop("proposals", {}) or {}
        state.pop("sources", None)
        writes: dict[Path, str | bytes] = {}
        deletes: set[Path] = set()
        cleaned_fields = 0
        for note_type, location in note_scan_entries():
            for path in sorted((self.repo.root / location).glob("*.md")):
                rel = path.relative_to(self.repo.root)
                text = path.read_text(encoding="utf-8")
                metadata, _ = parse_document(text)
                changed = False
                for field in ("expires_at", "converted_to"):
                    if field in metadata:
                        metadata.pop(field)
                        cleaned_fields += 1
                        changed = True
                if note_type == "source" and "flash_ids" in metadata:
                    metadata.pop("flash_ids")
                    cleaned_fields += 1
                    changed = True
                if changed:
                    writes[rel] = replace_frontmatter(text, metadata)

        proposal_root = self.repo.root / ".goodidea/proposals"
        for path in sorted(proposal_root.glob("*/*.md")):
            rel = path.relative_to(self.repo.root)
            text = path.read_text(encoding="utf-8")
            metadata, _ = parse_document(text)
            proposal_id = str(metadata.get("id") or path.stem)
            if metadata.get("status") != "pending":
                deletes.add(rel)
                continue
            if metadata.get("type") == "permanent_proposal":
                legacy = legacy_proposals.get(proposal_id, {})
                changed = False
                for field, legacy_field in (
                    ("source_ids", "source_ids"),
                    ("from_ids", "from_ids"),
                ):
                    if field not in metadata:
                        metadata[field] = list(legacy.get(legacy_field, []))
                        changed = True
                if changed:
                    writes[rel] = replace_frontmatter(text, metadata)
        result = {
            "cleaned_fields": cleaned_fields,
            "deleted_terminal_proposals": len(deletes),
            "removed_state_mirrors": ["sources", "proposals"],
        }
        return self.repo.commit(
            transaction_id=txid,
            action="maintain-contracts",
            summary="移除可推导状态镜像与已终结候选",
            writes=writes,
            deletes=deletes,
            state=state,
            result=result,
        )

    def maintain_enums_zh(
        self, *, transaction_id: str | None = None
    ) -> dict[str, Any]:
        """把正式内容 Frontmatter 枚举值从英文迁移为中文（2026-08-11 契约）。

        幂等：parse 会把中文值归一化为英文内部值，dump 再本地化回中文，
        已迁移文件重写后输出不变，不会产生空事务。updated_at 保持不变。
        """
        txid = transaction_id or new_transaction_id("maintain-enums-zh")
        if existing := self._idempotent(txid):
            return existing
        state = self.repo.read_state()
        writes: dict[Path, str | bytes] = {}
        for note_type, location in note_scan_entries():
            for path in sorted((self.repo.root / location).glob("*.md")):
                rel = path.relative_to(self.repo.root)
                text = path.read_text(encoding="utf-8")
                metadata, _ = parse_document(text)
                localized = localize_enums(metadata)
                if any(
                    localized.get(field) != metadata.get(field)
                    for field in ENUM_FIELDS
                ):
                    writes[rel] = replace_frontmatter(text, metadata)
        if not writes:
            return {"migrated": 0, "already_current": True}
        result = {
            "migrated": len(writes),
            "files": sorted(rel.as_posix() for rel in writes),
        }
        return self.repo.commit(
            transaction_id=txid,
            action="maintain-enums-zh",
            summary=f"枚举值中文化迁移 {len(writes)} 张卡片",
            writes=writes,
            state=state,
            result=result,
        )

    def connect_propose(
        self,
        from_id: str,
        to_id: str,
        *,
        relation: str,
        rationale: str,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if from_id == to_id:
            raise ValidationError("不能把卡片连接到自身")
        if not relation.strip() or not rationale.strip():
            raise ValidationError("连接候选必须包含关系类型和理由")
        left = self.repo.find_note(from_id)
        right = self.repo.find_note(to_id)
        if not left or left[2].get("type") not in PERMANENT_CARD_TYPES:
            raise ValidationError(f"连接起点不是正式卡片：{from_id}")
        if not right or right[2].get("type") not in PERMANENT_CARD_TYPES:
            raise ValidationError(f"连接终点不是正式卡片：{to_id}")
        txid = transaction_id or new_transaction_id("connect-propose")
        if existing := self._idempotent(txid):
            return existing
        proposal_id = stable_id("PRP", f"connection:{txid}", dated=False)
        proposal_rel = Path(f".goodidea/proposals/connections/{proposal_id}.md")
        timestamp = now_iso()
        payload = {
            "from_id": from_id,
            "to_id": to_id,
            "relation": relation.strip(),
            "rationale": rationale.strip(),
        }
        metadata = {
            "id": proposal_id,
            "type": "connection_proposal",
            "title": f"连接候选：{left[2]['title']} → {right[2]['title']}",
            "status": "pending",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        proposal = _proposal_document(metadata, payload)
        state = self.repo.read_state()
        result = {
            "proposal_id": proposal_id,
            "proposal_path": proposal_rel.as_posix(),
            **payload,
        }
        return self.repo.commit(
            transaction_id=txid,
            action="connect-propose",
            summary=metadata["title"],
            writes={proposal_rel: proposal},
            state=state,
            result=result,
        )

    def connect_accept(
        self,
        proposal_id: str,
        *,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        txid = transaction_id or new_transaction_id("connect-accept")
        if existing := self._idempotent(txid):
            return existing
        state = self.repo.read_state()
        proposal_rel, proposal_text, _ = _pending_proposal(
            self.repo.root, "connections", proposal_id, "connection_proposal"
        )
        payload = _proposal_payload(proposal_text)
        left = self.repo.find_note(payload["from_id"])
        right = self.repo.find_note(payload["to_id"])
        if not left or not right:
            raise IntegrityError("连接候选引用的卡片已不存在")
        relation = payload["relation"]
        rationale = payload["rationale"]
        left_item = (
            f"{relation} → {wiki_link(right[0], right[2]['title'])}：{rationale}"
        )
        right_item = (
            f"{relation} ← {wiki_link(left[0], left[2]['title'])}：{rationale}"
        )
        timestamp = now_iso()
        left_meta = copy.deepcopy(left[2])
        right_meta = copy.deepcopy(right[2])
        left_meta["updated_at"] = timestamp
        right_meta["updated_at"] = timestamp
        left_text = replace_frontmatter(
            add_list_item_to_section(left[1], "连接", left_item), left_meta
        )
        right_text = replace_frontmatter(
            add_list_item_to_section(right[1], "连接", right_item), right_meta
        )
        state.setdefault("connections", []).append(
            {
                "proposal_id": proposal_id,
                "from_id": payload["from_id"],
                "to_id": payload["to_id"],
                "relation": relation,
                "rationale": rationale,
                "accepted_at": timestamp,
            }
        )
        result = {"proposal_id": proposal_id, **payload}
        return self.repo.commit(
            transaction_id=txid,
            action="connect-accept",
            summary=f"{left[2]['title']} ↔ {right[2]['title']}",
            writes={
                left[0]: left_text,
                right[0]: right_text,
            },
            deletes={proposal_rel},
            state=state,
            result=result,
        )

    def connect_withdraw(
        self,
        proposal_id: str,
        *,
        reason: str,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if not _meaningful(reason, minimum=6):
            raise ValidationError("撤回连接候选时必须记录明确原因")
        txid = transaction_id or new_transaction_id("connect-withdraw")
        if existing := self._idempotent(txid):
            return existing
        state = self.repo.read_state()
        proposal_rel, _, _ = _pending_proposal(
            self.repo.root, "connections", proposal_id, "connection_proposal"
        )
        result = {
            "proposal_id": proposal_id,
            "status": "withdrawn",
            "reason": reason.strip(),
        }
        return self.repo.commit(
            transaction_id=txid,
            action="connect-withdraw",
            summary=f"撤回 {proposal_id}",
            writes={},
            deletes={proposal_rel},
            state=state,
            result=result,
        )

    def connect_disconnect(
        self,
        proposal_id: str,
        *,
        reason: str,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if not _meaningful(reason, minimum=6):
            raise ValidationError("断开语义连接时必须记录明确原因")
        txid = transaction_id or new_transaction_id("connect-disconnect")
        if existing := self._idempotent(txid):
            return existing
        state = self.repo.read_state()
        connections = state.get("connections", [])
        target = next(
            (
                conn
                for conn in connections
                if conn.get("proposal_id") == proposal_id
            ),
            None,
        )
        if target is None:
            raise ValidationError(f"找不到已接受的连接：{proposal_id}")
        left = self.repo.find_note(target["from_id"])
        right = self.repo.find_note(target["to_id"])
        if not left or not right:
            raise IntegrityError("连接引用的卡片已不存在")
        relation = target["relation"]
        rationale = target["rationale"]
        left_item = (
            f"{relation} → {wiki_link(right[0], right[2]['title'])}：{rationale}"
        )
        right_item = (
            f"{relation} ← {wiki_link(left[0], left[2]['title'])}：{rationale}"
        )
        timestamp = now_iso()
        left_meta = copy.deepcopy(left[2])
        right_meta = copy.deepcopy(right[2])
        left_meta["updated_at"] = timestamp
        right_meta["updated_at"] = timestamp
        left_text = replace_frontmatter(
            remove_list_item_from_section(left[1], "连接", left_item), left_meta
        )
        right_text = replace_frontmatter(
            remove_list_item_from_section(right[1], "连接", right_item), right_meta
        )
        state["connections"] = [
            conn
            for conn in connections
            if conn.get("proposal_id") != proposal_id
        ]
        result = {
            "proposal_id": proposal_id,
            "from_id": target["from_id"],
            "to_id": target["to_id"],
            "status": "disconnected",
            "reason": reason.strip(),
        }
        return self.repo.commit(
            transaction_id=txid,
            action="connect-disconnect",
            summary=f"断开 {left[2]['title']} ↔ {right[2]['title']}",
            writes={left[0]: left_text, right[0]: right_text},
            state=state,
            result=result,
        )

    def review(
        self,
        *,
        current_time: datetime | None = None,
    ) -> dict[str, Any]:
        now = current_time or datetime.now().astimezone()
        pending: list[dict[str, Any]] = []
        stale: list[str] = []
        for note_type in ("flash", "interesting", "todo", "source"):
            for scan_dir in (
                note_scan_dirs(note_type) if note_type == "todo" else [TYPE_LOCATIONS[note_type]]
            ):
                for path in sorted((self.repo.root / scan_dir).glob("*.md")):
                    text = path.read_text(encoding="utf-8")
                    metadata, _ = parse_document(text)
                    if metadata.get("status") in {"pending", "open", "partial", "failed", "not_started"}:
                        item = {
                                "id": metadata["id"],
                                "type": metadata["type"],
                                "title": metadata["title"],
                                "status": metadata["status"],
                                "path": path.relative_to(self.repo.root).as_posix(),
                            }
                        if note_type == "flash" and metadata.get("status") == "pending":
                            deadline = datetime.fromisoformat(metadata["created_at"]) + FLASH_STALE_AFTER
                            item["stale"] = now >= deadline
                            if item["stale"]:
                                stale.append(str(metadata["id"]))
                        pending.append(item)
        return {"pending": pending, "stale": stale, "count": len(pending), "write": False}

    def lint(self, *, verify_git: bool = False) -> dict[str, Any]:
        issues: list[str] = []
        warnings: list[str] = []
        seen_ids: dict[str, str] = {}
        all_notes: list[tuple[Path, str, dict[str, Any]]] = []
        for expected_type, location in note_scan_entries():
            for path in sorted((self.repo.root / location).glob("*.md")):
                rel = path.relative_to(self.repo.root)
                try:
                    text = path.read_text(encoding="utf-8")
                    metadata, body = parse_document(text)
                except Exception as exc:
                    issues.append(f"{rel}: 无法解析：{exc}")
                    continue
                missing = validate_required_metadata(metadata)
                if missing:
                    issues.append(f"{rel}: 缺少字段 {missing}")
                if "summary" in metadata:
                    issues.append(f"{rel}: 正式内容不得包含过时字段 summary")
                if metadata.get("type") != expected_type:
                    issues.append(
                        f"{rel}: 目录要求 {expected_type}，实际 {metadata.get('type')}"
                    )
                spec = NOTE_SPECS[expected_type]
                if metadata.get("status") not in spec["statuses"]:
                    issues.append(
                        f"{rel}: {expected_type} 不允许状态 {metadata.get('status')}"
                    )
                missing_type_fields = sorted(
                    key for key in spec["required"] if key not in metadata
                )
                if missing_type_fields:
                    issues.append(f"{rel}: {expected_type} 缺少字段 {missing_type_fields}")
                for relation_field in ("source_ids", "derived_from"):
                    if relation_field in metadata and not isinstance(metadata[relation_field], list):
                        issues.append(f"{rel}: {relation_field} 必须是 ID 列表")
                note_id = str(metadata.get("id", ""))
                if note_id and not spec["id"].fullmatch(note_id):
                    issues.append(f"{rel}: ID 格式与 {expected_type} 不一致")
                if note_id in seen_ids:
                    issues.append(f"重复 ID {note_id}: {seen_ids[note_id]}, {rel}")
                seen_ids[note_id] = rel.as_posix()
                try:
                    base_name = Path(
                        dated_filename(
                            str(metadata.get("title", "")),
                            str(metadata.get("created_at", "")),
                        )
                    ).stem
                    filename_ok = path.stem == base_name or bool(
                        re.fullmatch(re.escape(base_name) + r"-[2-9]\d*", path.stem)
                    )
                    if not filename_ok:
                        issues.append(
                            f"{rel}: 文件名必须使用创建日期加标题，不得使用 ID 前缀"
                        )
                except ValidationError as exc:
                    issues.append(f"{rel}: 无法校验文件名：{exc}")
                if expected_type == "source":
                    try:
                        validate_source_note(text, rel.as_posix())
                    except IntegrityError as exc:
                        issues.append(str(exc))
                    if metadata.get("source_url"):
                        issues.append(f"{rel}: 不应持久化原始分享链接 source_url")
                    try:
                        _, _, expected_source_id = (
                            _source_metadata_identity(metadata)
                        )
                        if note_id != expected_source_id:
                            issues.append(f"{rel}: 来源 ID 与身份字段不一致")
                    except ValidationError as exc:
                        issues.append(f"{rel}: {exc}")
                    expected_h1 = f"# {metadata.get('title', '')}\n"
                    if not body.startswith(expected_h1):
                        issues.append(f"{rel}: 一级标题与 Frontmatter title 不一致")
                    snapshot_heading = text.find("## 原文快照\n")
                    flashes_heading = text.find("## 关联闪念\n")
                    if not (-1 < snapshot_heading < flashes_heading):
                        issues.append(
                            f"{rel}: 溯源顺序必须为标题、原文快照、关联闪念"
                        )
                    if "## 文献笔记\n" in text:
                        issues.append(f"{rel}: 溯源空间不得包含文献笔记层")
                    try:
                        _, snapshot_content, _, _ = extract_snapshot(text)
                        if snapshot_content.startswith("# 原文："):
                            issues.append(f"{rel}: 原文快照仍使用旧版重复标题包装")
                    except IntegrityError:
                        pass
                all_notes.append((rel, text, metadata))
        notes_by_id = {
            str(metadata.get("id")): (rel, text, metadata)
            for rel, text, metadata in all_notes
        }
        witnesses_by_id: dict[str, tuple[Path, str, dict[str, Any], str]] = {}
        witness_root = self.repo.root / FORMATION_WITNESS_ROOT
        for witness_path in sorted(witness_root.glob("*.md")):
            rel = witness_path.relative_to(self.repo.root)
            try:
                witness_text = witness_path.read_text(encoding="utf-8")
                witness_meta, witness_body = parse_document(witness_text)
            except Exception as exc:
                issues.append(f"{rel}: 无法解析形成来源见证：{exc}")
                continue
            witness_id = str(witness_meta.get("id") or "")
            if witness_path.is_symlink():
                issues.append(f"{rel}: 形成来源见证不得为符号链接")
            if witness_meta.get("type") != "formation_witness":
                issues.append(f"{rel}: 形成来源见证类型非法")
            if witness_path.stem != witness_id or not FORMATION_WITNESS_ID_PATTERN.fullmatch(
                witness_id
            ):
                issues.append(f"{rel}: 形成来源见证 ID 或文件名非法")
            if witness_id in seen_ids:
                issues.append(f"重复 ID {witness_id}: {seen_ids[witness_id]}, {rel}")
            seen_ids[witness_id] = rel.as_posix()
            required_fields = {
                "title",
                "created_at",
                "card_id",
                "proposal_id",
                "draft_sha256",
                "source_anchor_sha256",
            }
            missing_fields = sorted(
                key for key in required_fields if key not in witness_meta
            )
            if missing_fields:
                issues.append(f"{rel}: 形成来源见证缺少字段 {missing_fields}")
            prefix = "# 本轮直接表达形成来源\n\n"
            marker = "\n\n## 形成卡片\n"
            marker_at = witness_body.find(marker)
            if not witness_body.startswith(prefix) or marker_at < len(prefix):
                issues.append(f"{rel}: 形成来源见证正文结构异常")
                continue
            source_anchor = witness_body[len(prefix):marker_at].strip()
            try:
                normalized_anchor, anchor_sha256 = _normalize_direct_source(
                    source_anchor
                )
            except ValidationError as exc:
                issues.append(f"{rel}: {exc}")
                continue
            if anchor_sha256 != witness_meta.get("source_anchor_sha256"):
                issues.append(f"{rel}: 形成说明哈希异常")
            if not SHA256_RE.fullmatch(str(witness_meta.get("draft_sha256") or "")):
                issues.append(f"{rel}: 草稿哈希非法")
            witnesses_by_id[witness_id] = (
                rel,
                witness_text,
                witness_meta,
                normalized_anchor,
            )
        notes_by_id.update(
            {
                witness_id: (rel, text, metadata)
                for witness_id, (rel, text, metadata, _) in witnesses_by_id.items()
            }
        )
        for rel, text, metadata in all_notes:
            if metadata.get("type") != "permanent":
                continue
            source_ids = metadata.get("source_ids", [])
            derived_from = metadata.get("derived_from", [])
            if not isinstance(source_ids, list) or not isinstance(derived_from, list):
                continue
            if not derived_from:
                issues.append(f"{rel}: 普通永久卡片缺少形成来源连接")
                continue
            for source_id in source_ids:
                source = notes_by_id.get(str(source_id))
                if not source or source[2].get("type") != "source":
                    issues.append(f"{rel}: 外部依据不是有效来源：{source_id}")
            is_new_contract = "formation_draft_sha256" in metadata
            if is_new_contract and "## 形成来源\n" not in text:
                issues.append(f"{rel}: 新版普通永久卡片缺少形成来源导航区")
            for from_id in derived_from:
                target = notes_by_id.get(str(from_id))
                if not target:
                    issues.append(f"{rel}: 形成来源不存在：{from_id}")
                    continue
                if target[2].get("type") not in {*NOTE_SPECS, "formation_witness"}:
                    issues.append(f"{rel}: 形成来源类型非法：{from_id}")
                    continue
                if is_new_contract:
                    expected_link = wiki_link(target[0], target[2].get("title", ""))
                    if expected_link not in text:
                        issues.append(f"{rel}: 形成来源导航缺少 {from_id}")
        for witness_id, (rel, text, metadata, source_anchor) in witnesses_by_id.items():
            card_id = str(metadata.get("card_id") or "")
            card = notes_by_id.get(card_id)
            if not card or card[2].get("type") != "permanent":
                issues.append(f"{rel}: 形成来源见证引用的普通永久卡片不存在")
                continue
            if witness_id not in card[2].get("derived_from", []):
                issues.append(f"{rel}: 形成来源见证与普通永久卡片不是双向关系")
            if metadata.get("draft_sha256") != card[2].get(
                "formation_draft_sha256"
            ):
                issues.append(f"{rel}: 形成来源见证与卡片草稿哈希不一致")
            if wiki_link(card[0], card[2].get("title", "")) not in text:
                issues.append(f"{rel}: 形成来源见证缺少正式卡片反向链接")
            expected_witness_link = wiki_link(rel, metadata.get("title", ""))
            if expected_witness_link not in card[1] or source_anchor not in card[1]:
                issues.append(f"{rel}: 正式卡片缺少形成见证导航或形成说明")
        for rel, text, metadata in all_notes:
            if metadata.get("type") != "flash":
                continue
            source_ids = list(metadata.get("source_ids", []))
            if not source_ids or "## 来源与论证锚点\n" not in text:
                # v0.1 旧闪念保留历史布局；新写入路径只产生统一锚点。
                continue
            if "## 关联来源\n" in text:
                issues.append(f"{rel}: 已使用来源与论证锚点，不得再设关联来源节")
            for source_id in source_ids:
                source = notes_by_id.get(str(source_id))
                if not source or source[2].get("type") != "source":
                    issues.append(f"{rel}: 引用的来源不存在：{source_id}")
                    continue
                expected_link = source[0].with_suffix("").as_posix()
                if f"[[{expected_link}|" not in text:
                    issues.append(f"{rel}: 来源锚点未链接 {source[2].get('title')}")
        for rel, text, _ in all_notes:
            for link in re.findall(r"\[\[([^|\]#]+)", text):
                target = self.repo.root / f"{link}.md"
                if not target.exists():
                    issues.append(f"{rel}: 断链 [[{link}]]")
        expected_index = self.repo.generate_index({})
        current_index = (self.repo.root / "index.md").read_text(encoding="utf-8")
        if expected_index != current_index:
            issues.append("index.md 与当前卡片集合不一致")
        state = self.repo.read_state()
        if state.get("sources"):
            issues.append("state.json 仍包含可由来源文件推导的 sources 镜像")
        if state.get("proposals"):
            issues.append("state.json 仍包含可由候选文件推导的 proposals 镜像")
        permanent_proposals = self.repo.root / ".goodidea/proposals/permanent"
        for proposal_path in sorted(permanent_proposals.glob("*.md")):
            proposal_id = proposal_path.stem
            try:
                proposal_text = proposal_path.read_text(encoding="utf-8")
                proposal_meta, proposal_body = parse_document(proposal_text)
            except Exception as exc:
                issues.append(f"永久卡片草稿无法解析：{proposal_id}: {exc}")
                continue
            if proposal_meta.get("id") != proposal_id:
                issues.append(f"永久卡片草稿文件名与 ID 不一致：{proposal_id}")
            if proposal_meta.get("status") != "pending":
                issues.append(f"候选目录只允许待处理草稿：{proposal_id}")
            if proposal_meta.get("authoring_mode") not in {
                "user_verbatim",
                "user_body_agent_title",
                "user_confirmed_agent_structured",
            }:
                issues.append(f"永久卡片草稿不是用户原文：{proposal_id}")
                continue
            try:
                _, _, actual_sha256 = _validate_user_draft(proposal_body)
            except ValidationError as exc:
                issues.append(f"永久卡片草稿格式异常：{proposal_id}: {exc}")
                continue
            if actual_sha256 != proposal_meta.get("draft_sha256"):
                issues.append(f"永久卡片草稿哈希异常：{proposal_id}")
            card_type = proposal_meta.get("card_type")
            if card_type == "permanent":
                raw_source_ids = proposal_meta.get("source_ids", [])
                raw_from_ids = proposal_meta.get("from_ids", [])
                if not isinstance(raw_source_ids, list) or not isinstance(
                    raw_from_ids, list
                ):
                    issues.append(f"普通永久卡片候选来源字段非法：{proposal_id}")
                    continue
                if proposal_meta.get("formation_sources_confirmed") is not True:
                    issues.append(f"普通永久卡片候选缺少来源确认：{proposal_id}")
                raw_direct_source = str(
                    proposal_meta.get("direct_source_anchor") or ""
                )
                if not raw_from_ids and not raw_direct_source:
                    issues.append(f"普通永久卡片候选缺少形成来源：{proposal_id}")
                if raw_direct_source:
                    try:
                        _, direct_sha256 = _normalize_direct_source(
                            raw_direct_source
                        )
                    except ValidationError as exc:
                        issues.append(f"普通永久卡片候选形成说明非法：{proposal_id}: {exc}")
                    else:
                        if direct_sha256 != proposal_meta.get(
                            "direct_source_sha256"
                        ):
                            issues.append(f"普通永久卡片候选形成说明哈希异常：{proposal_id}")
            elif any(
                key in proposal_meta
                for key in (
                    "formation_sources_confirmed",
                    "direct_source_anchor",
                    "direct_source_sha256",
                )
            ):
                issues.append(f"非普通永久卡片候选含有专属来源字段：{proposal_id}")
        obsidian_root = self.repo.root / ".obsidian"
        try:
            app_config = json.loads(
                (obsidian_root / "app.json").read_text(encoding="utf-8")
            )
            appearance_config = json.loads(
                (obsidian_root / "appearance.json").read_text(encoding="utf-8")
            )
            plugin_config = json.loads(
                (obsidian_root / "core-plugins.json").read_text(encoding="utf-8")
            )
            if app_config.get("propertiesInDocument") != "visible":
                issues.append("Obsidian 未默认显示卡片 Frontmatter 属性")
            if app_config.get("alwaysUpdateLinks") is not True:
                issues.append("Obsidian 未启用自动更新链接")
            if app_config.get("attachmentFolderPath") != "assets":
                issues.append("Obsidian 附件目录未指向 assets")
            if app_config.get("defaultViewMode") != "preview":
                issues.append("Obsidian 未默认使用阅读视图")
            if app_config.get("newLinkFormat") != "absolute":
                issues.append("Obsidian 链接格式必须使用仓库根路径")
            if app_config.get("showInlineTitle") is not False:
                issues.append("Obsidian 必须隐藏重复的行内标题")
            if "goodidea" not in appearance_config.get("enabledCssSnippets", []):
                issues.append("Obsidian 未启用 Good idea 阅读界面样式")
            if plugin_config.get("sync") is not False:
                issues.append("Obsidian Sync 必须在本机 v0.1 基线中关闭")
            css = (obsidian_root / "snippets/goodidea.css").read_text(
                encoding="utf-8"
            )
            if ".metadata-container" in css:
                issues.append("Obsidian 样式仍在隐藏卡片属性区域")
            for selector in (".goodidea", ".agents", "AGENTS.md", "schema.md"):
                if selector not in css:
                    issues.append(f"Obsidian 样式未隐藏内部项目：{selector}")
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            issues.append(f"Obsidian 产品基线缺失或损坏：{exc}")
        log_text = (self.repo.root / "log.md").read_text(encoding="utf-8")
        git_messages = _run_git(
            self.repo.root, ["log", "--format=%B"], check=True
        ).stdout
        for txid in state.get("transactions", {}):
            if f"tx={txid}" not in log_text:
                issues.append(f"事务账本缺少日志记录：{txid}")
            if f"[tx:{txid}]" not in git_messages:
                issues.append(f"事务账本缺少对应 Git 提交：{txid}")
        if verify_git:
            status = _run_git(
                self.repo.root, ["status", "--porcelain"], check=True
            ).stdout.strip()
            if status:
                issues.append("Git 工作区不干净：" + status.replace("\n", "; "))
        return {
            "ok": not issues,
            "issues": issues,
            "warnings": warnings,
            "note_count": len(all_notes),
            "source_count": sum(
                1 for _, _, meta in all_notes if meta.get("type") == "source"
            ),
        }

    def rollback(self, commit: str, *, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            raise ValidationError("回滚必须显式传入 --yes")
        self.repo.preflight_integrity()
        status = _run_git(
            self.repo.root, ["status", "--porcelain"], check=True
        ).stdout.strip()
        if status:
            raise GitError("回滚前 Git 工作区必须干净")
        resolved = _run_git(
            self.repo.root, ["rev-parse", "--verify", f"{commit}^{{commit}}"]
        ).stdout.strip()
        parent = _run_git(
            self.repo.root, ["rev-parse", "--verify", f"{resolved}^"], check=False
        )
        if parent.returncode != 0:
            raise ValidationError("不能回滚仓库的初始提交")
        subject = _run_git(
            self.repo.root, ["show", "-s", "--format=%s", resolved]
        ).stdout.strip()
        before_state = self.repo.read_state()
        before_log = (self.repo.root / "log.md").read_text(encoding="utf-8")
        process = _run_git(
            self.repo.root, ["revert", "--no-commit", resolved], check=False
        )
        if process.returncode != 0:
            _run_git(self.repo.root, ["revert", "--abort"], check=False)
            raise GitError(process.stderr.strip() or "git revert 失败")
        timestamp = now_iso()
        rollback_tx = f"rollback-{resolved[:12]}"
        try:
            reverted_state = self.repo.read_state()
            reverted_transactions = reverted_state.setdefault("transactions", {})
            for txid, record in before_state.get("transactions", {}).items():
                if txid not in reverted_transactions:
                    preserved = copy.deepcopy(record)
                    preserved["rolled_back_at"] = timestamp
                    preserved["rolled_back_by"] = rollback_tx
                    reverted_transactions[txid] = preserved
            rollback_result = {
                "rolled_back": resolved,
                "strategy": "git-revert",
            }
            reverted_transactions[rollback_tx] = {
                "transaction_id": rollback_tx,
                "action": "rollback",
                "summary": f"回滚 {resolved[:12]} {subject}",
                "timestamp": timestamp,
                "result": rollback_result,
            }
            reverted_state.setdefault("rollbacks", []).append(
                {
                    "transaction_id": rollback_tx,
                    "commit": resolved,
                    "subject": subject,
                    "timestamp": timestamp,
                }
            )
            log_text = before_log
            if not log_text.endswith("\n"):
                log_text += "\n"
            log_text += (
                f"[{timestamp}] rollback | 回滚 {resolved[:12]} {subject} "
                f"| tx={rollback_tx}\n\n"
            )
            (self.repo.root / ".goodidea/state.json").write_text(
                json.dumps(
                    reverted_state,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (self.repo.root / "log.md").write_text(log_text, encoding="utf-8")
            (self.repo.root / "index.md").write_text(
                self.repo.generate_index({}), encoding="utf-8"
            )
            _run_git(
                self.repo.root,
                ["add", "--", ".goodidea/state.json", "log.md", "index.md"],
            )
            _run_git(
                self.repo.root,
                [
                    "commit",
                    "-m",
                    (
                        f"rollback: {subject} [tx:{rollback_tx}] "
                        f"[reverts:{resolved}]"
                    ),
                ],
            )
        except Exception:
            _run_git(self.repo.root, ["revert", "--abort"], check=False)
            raise
        revert_commit = _run_git(self.repo.root, ["rev-parse", "HEAD"]).stdout.strip()
        cancelled_jobs: list[str] = []
        tx_match = re.search(r"\[tx:([^\]]+)\]", subject)
        if tx_match:
            record = before_state.get("transactions", {}).get(tx_match.group(1), {})
            if record.get("action") == "capture-finalize":
                session_id = str(record.get("result", {}).get("session_id") or "")
                if session_id:
                    cancelled_jobs = CaptureRuntime(self.repo.root).cancel_jobs_for_session(
                        session_id
                    )
        return {
            "rolled_back": resolved,
            "revert_commit": revert_commit,
            "transaction_id": rollback_tx,
            "strategy": "git-revert",
            "cancelled_maintenance_jobs": cancelled_jobs,
        }
