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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .errors import GitError, IntegrityError, ValidationError
from .metadata import dump_frontmatter, parse_document, replace_frontmatter
from .notes import (
    TYPE_LOCATIONS,
    add_list_item_to_section,
    dated_filename,
    extract_snapshot,
    normalize_source_layout,
    render_note,
    render_source_note,
    replace_source_snapshot,
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
PERMANENT_CARD_TYPES = {"permanent", "mother", "action", "index"}
PROPOSAL_START = "<!-- goodidea:proposal-json:start -->"
PROPOSAL_END = "<!-- goodidea:proposal-json:end -->"


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
    text: str, extracted_title: str = ""
) -> tuple[str, str, str, str]:
    """Prepare either a user-titled draft or an agent-titled user body."""
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
    return {
        "flash": "pending",
        "interesting": "pending",
        "todo": "open",
        "permanent": "active",
        "mother": "open",
        "action": "planned",
        "index": "active",
    }[note_type]


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
            "summary": text.strip().replace("\n", " ")[:100],
            "source_ids": [source_id] if source_id else [],
        }
        sections = [("原始记录", text)]
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
        self, preview: dict[str, Any]
    ) -> tuple[str, dict[Path, bytes], list[str]]:
        markdown = str(preview.get("markdown", ""))
        image_records = {
            str(item.get("url")): item
            for item in preview.get("images", [])
            if item.get("url")
        }
        urls = list(
            dict.fromkeys(
                match.group(2)
                for match in re.finditer(
                    r"!\[([^\]]*)\]\((https?://[^)]+)\)", markdown
                )
            )
        )
        writes: dict[Path, bytes] = {}
        failures: list[str] = []
        for url in urls:
            try:
                data, extension = self._download_image(url, image_records.get(url))
                digest = hashlib.sha256(data).hexdigest()
                rel = Path(f".goodidea/assets/{digest}{extension}")
                writes[rel] = data
                markdown = markdown.replace(
                    f"]({url})", f"](../{rel.as_posix()})"
                )
            except Exception as exc:
                failures.append(f"{url}: {exc}")
                pattern = re.compile(
                    r"!\[([^\]]*)\]\(" + re.escape(url) + r"\)"
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
        if preview.get("author"):
            lines.append(f"> 作者：{preview['author']}")
        if preview.get("published_at"):
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
        motivation: str,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        _ensure_motivation(motivation)
        txid = transaction_id or new_transaction_id("source-commit")
        if existing := self._idempotent(txid):
            return existing
        canonical_url = canonicalize_url(
            str(preview.get("canonical_url") or preview.get("url") or "")
        )
        if not canonical_url.startswith(("http://", "https://")):
            raise ValidationError("来源必须包含有效的 http/https URL")
        title = str(preview.get("title") or canonical_url).strip()
        source_id = stable_id("SRC", canonical_url, dated=False)
        flash_id = stable_id("FLA", f"{txid}:{motivation}")
        timestamp = now_iso()
        state = self.repo.read_state()
        writes: dict[Path, str | bytes] = {}
        source_record = state.get("sources", {}).get(canonical_url)
        source_created = source_record is None
        flash_title = motivation.strip().splitlines()[0][:40]

        if source_record:
            source_rel = Path(source_record["path"])
            source_path = self.repo.root / source_rel
            if not source_path.is_file():
                raise IntegrityError(f"来源账本指向不存在的文件：{source_rel}")
            source_note = source_path.read_text(encoding="utf-8")
            source_meta, _ = parse_document(source_note)
            source_title = source_meta["title"]
        else:
            localized, assets, failures = self._localize_images(preview)
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
                "canonical_url": canonical_url,
                "author": str(preview.get("author") or ""),
                "published_at": str(preview.get("published_at") or ""),
                "fetched_at": timestamp,
                "created_at": timestamp,
                "updated_at": timestamp,
                "content_sha256": hashlib.sha256(
                    str(preview.get("markdown", "")).encode("utf-8")
                ).hexdigest(),
                "image_failures": failures,
                "flash_ids": [flash_id],
                "summary": "原文快照，文献笔记待处理",
            }

        flash_rel = self._new_note_path("flash", flash_title, timestamp)
        source_link = wiki_link(source_rel, source_title)
        flash_meta = {
            "id": flash_id,
            "type": "flash",
            "title": flash_title,
            "status": "pending",
            "created_at": timestamp,
            "updated_at": timestamp,
            "expires_at": (
                datetime.now().astimezone() + timedelta(hours=48)
            ).isoformat(timespec="seconds"),
            "source_ids": [source_id],
            "summary": motivation.strip().replace("\n", " ")[:100],
        }
        flash_note = render_note(
            flash_meta,
            [
                ("原始记录", motivation),
                ("产生情境", "保存外部资料时形成的个人注意与保存动机。"),
                ("关联来源", source_link),
            ],
        )
        flash_link = wiki_link(flash_rel, flash_title)
        if source_record:
            source_meta["updated_at"] = timestamp
            source_meta["flash_ids"] = list(
                dict.fromkeys([*source_meta.get("flash_ids", []), flash_id])
            )
            source_note = add_list_item_to_section(
                source_note, "关联闪念", flash_link
            )
            source_note = replace_frontmatter(source_note, source_meta)
            source_note = normalize_source_layout(source_note)
        else:
            source_note = render_source_note(source_meta, snapshot, [flash_link])
        writes[source_rel] = source_note
        writes[flash_rel] = flash_note
        state.setdefault("sources", {})[canonical_url] = {
            "id": source_id,
            "path": source_rel.as_posix(),
            "title": source_title,
        }
        result = {
            "source_id": source_id,
            "source_path": source_rel.as_posix(),
            "source_created": source_created,
            "flash_id": flash_id,
            "flash_path": flash_rel.as_posix(),
        }
        return self.repo.commit(
            transaction_id=txid,
            action="source-commit",
            summary=f"{source_title} + 保存动机",
            writes=writes,
            state=state,
            result=result,
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

        if confirm_proposal:
            proposal_record = state.get("proposals", {}).get(confirm_proposal)
            if not proposal_record or proposal_record.get("kind") != "source-update":
                raise ValidationError(f"找不到来源更新候选：{confirm_proposal}")
            if proposal_record.get("status") != "pending":
                raise ValidationError("来源更新候选已处理")
            proposal_rel = Path(proposal_record["path"])
            proposal_text = (self.repo.root / proposal_rel).read_text(encoding="utf-8")
            payload = _proposal_payload(proposal_text)
            if payload.get("source_id") != source_id:
                raise ValidationError("更新候选与目标来源不一致")
            candidate = payload["preview"]
            localized, assets, failures = self._localize_images(candidate)
            capture_status = str(candidate.get("status") or "complete")
            if failures and capture_status == "complete":
                capture_status = "partial"
            snapshot = self._build_snapshot(candidate, localized)
            timestamp = now_iso()
            updated_source = replace_source_snapshot(
                source_note,
                snapshot,
                {
                    "title": str(candidate.get("title") or source_meta["title"]),
                    "status": capture_status,
                    "capture_status": capture_status,
                    "author": str(candidate.get("author") or ""),
                    "published_at": str(candidate.get("published_at") or ""),
                    "fetched_at": timestamp,
                    "updated_at": timestamp,
                    "content_sha256": hashlib.sha256(
                        str(candidate.get("markdown", "")).encode("utf-8")
                    ).hexdigest(),
                    "image_failures": failures,
                    "pending_update": "",
                },
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
            proposal_meta, _ = parse_document(proposal_text)
            proposal_meta["status"] = "accepted"
            proposal_meta["updated_at"] = timestamp
            proposal_text = replace_frontmatter(proposal_text, proposal_meta)
            state["proposals"][confirm_proposal]["status"] = "accepted"
            writes: dict[Path, str | bytes] = {proposal_rel: proposal_text, **assets}
            deletes: set[Path] = set()
            if new_source_rel != source_rel:
                wiki_replacements = {
                    source_rel.with_suffix("").as_posix():
                    new_source_rel.with_suffix("").as_posix()
                }
                for note_type, location in TYPE_LOCATIONS.items():
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
                state = _rewrite_exact_paths(
                    state,
                    {source_rel.as_posix(): new_source_rel.as_posix()},
                )
            else:
                writes[source_rel] = updated_source
            canonical = str(updated_meta.get("canonical_url", ""))
            if canonical in state.get("sources", {}):
                state["sources"][canonical]["title"] = new_title
                state["sources"][canonical]["path"] = new_source_rel.as_posix()
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
        state.setdefault("proposals", {})[proposal_id] = {
            "kind": "source-update",
            "path": proposal_rel.as_posix(),
            "status": "pending",
            "source_id": source_id,
        }
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
        source_ids: list[str] | None = None,
        from_ids: list[str] | None = None,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if card_type not in PERMANENT_CARD_TYPES:
            raise ValidationError(f"不支持的永久卡片类型：{card_type}")
        title, user_draft, draft_sha256, authoring_mode = _prepare_permanent_draft(
            draft, title
        )
        txid = transaction_id or new_transaction_id("permanent-propose")
        if existing := self._idempotent(txid):
            return existing
        proposal_id = stable_id("PRP", f"{card_type}:{txid}", dated=False)
        proposal_rel = Path(f".goodidea/proposals/permanent/{proposal_id}.md")
        timestamp = now_iso()
        checked_source_ids = source_ids or []
        checked_from_ids = from_ids or []
        for note_id in checked_source_ids + checked_from_ids:
            if not self.repo.find_note(note_id):
                raise ValidationError(f"用户草稿引用了不存在的对象：{note_id}")
        proposal_meta = {
            "id": proposal_id,
            "type": "permanent_proposal",
            "title": title,
            "status": "pending",
            "card_type": card_type,
            "authoring_mode": authoring_mode,
            "draft_sha256": draft_sha256,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        proposal_text = dump_frontmatter(proposal_meta) + user_draft
        state = self.repo.read_state()
        state.setdefault("proposals", {})[proposal_id] = {
            "kind": "permanent",
            "path": proposal_rel.as_posix(),
            "status": "pending",
            "card_type": card_type,
            "authoring_mode": authoring_mode,
            "draft_sha256": draft_sha256,
            "title": title,
            "source_ids": checked_source_ids,
            "from_ids": checked_from_ids,
        }
        result = {
            "proposal_id": proposal_id,
            "proposal_path": proposal_rel.as_posix(),
            "card_type": card_type,
        }
        return self.repo.commit(
            transaction_id=txid,
            action="permanent-propose",
            summary=title,
            writes={proposal_rel: proposal_text},
            state=state,
            result=result,
        )

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
        record = state.get("proposals", {}).get(proposal_id)
        if not record or record.get("kind") != "permanent":
            raise ValidationError(f"找不到永久卡片候选：{proposal_id}")
        if record.get("status") != "pending":
            raise ValidationError("永久卡片候选已处理")
        authoring_mode = record.get("authoring_mode")
        if authoring_mode not in {"user_verbatim", "user_body_agent_title"}:
            raise ValidationError("该候选不是用户原文草稿，禁止接纳；请撤销后由用户重新发起")
        proposal_rel = Path(record["path"])
        proposal_text = (self.repo.root / proposal_rel).read_text(encoding="utf-8")
        proposal_meta, user_draft = parse_document(proposal_text)
        title, normalized_draft, draft_sha256 = _validate_user_draft(user_draft)
        expected_sha256 = record.get("draft_sha256")
        card_type = record.get("card_type")
        if card_type not in PERMANENT_CARD_TYPES:
            raise IntegrityError("永久卡片草稿类型非法")
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
        if record.get("title") != title:
            raise IntegrityError("永久卡片草稿标题与账本不一致")
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
        metadata = {
            "id": card_id,
            "type": card_type,
            "title": title,
            "status": status,
            "created_at": timestamp,
            "updated_at": timestamp,
            "authoring_mode": authoring_mode,
            "source_ids": record.get("source_ids", []),
            "derived_from": record.get("from_ids", []),
            "summary": next(
                (
                    line.strip()[:100]
                    for line in normalized_draft.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                ),
                title,
            ),
        }
        card_text = dump_frontmatter(metadata) + normalized_draft
        writes: dict[Path, str | bytes] = {card_rel: card_text}
        proposal_meta["status"] = "accepted"
        proposal_meta["accepted_card_id"] = card_id
        proposal_meta["updated_at"] = timestamp
        writes[proposal_rel] = replace_frontmatter(proposal_text, proposal_meta)
        for from_id in record.get("from_ids", []):
            found = self.repo.find_note(from_id)
            if not found or found[2].get("type") != "flash":
                continue
            from_rel, from_text, from_meta = found
            from_meta["status"] = "processed"
            from_meta["converted_to"] = card_id
            from_meta["updated_at"] = timestamp
            writes[from_rel] = replace_frontmatter(from_text, from_meta)
        state["proposals"][proposal_id]["status"] = "accepted"
        state["proposals"][proposal_id]["card_id"] = card_id
        result = {
            "proposal_id": proposal_id,
            "card_id": card_id,
            "card_path": card_rel.as_posix(),
            "card_type": card_type,
        }
        return self.repo.commit(
            transaction_id=txid,
            action="permanent-accept",
            summary=title,
            writes=writes,
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
        record = state.get("proposals", {}).get(proposal_id)
        if not record or record.get("kind") != "permanent":
            raise ValidationError(f"找不到永久卡片候选：{proposal_id}")
        if record.get("status") != "pending":
            raise ValidationError("只有待处理的永久卡片候选可以撤销")
        proposal_rel = Path(record["path"])
        proposal_path = self.repo.root / proposal_rel
        if not proposal_path.is_file():
            raise IntegrityError(f"永久卡片候选文件不存在：{proposal_rel}")
        proposal_text = proposal_path.read_text(encoding="utf-8")
        proposal_meta, _ = parse_document(proposal_text)
        timestamp = now_iso()
        proposal_meta = {
            "id": proposal_id,
            "type": "permanent_proposal",
            "title": f"已撤销候选 {proposal_id}",
            "status": "withdrawn",
            "card_type": record.get("card_type", "unknown"),
            "created_at": proposal_meta.get("created_at", timestamp),
            "updated_at": timestamp,
            "withdrawn_at": timestamp,
            "withdraw_reason": reason.strip(),
        }
        tombstone = render_note(
            proposal_meta,
            [("撤销记录", reason.strip())],
        )
        record.update(
            {
                "status": "withdrawn",
                "withdrawn_at": timestamp,
                "withdraw_reason": reason.strip(),
            }
        )
        record.pop("title", None)
        record.pop("draft_sha256", None)
        record.pop("authoring_mode", None)
        result = {
            "proposal_id": proposal_id,
            "proposal_path": proposal_rel.as_posix(),
            "status": "withdrawn",
        }
        return self.repo.commit(
            transaction_id=txid,
            action="permanent-withdraw",
            summary=f"撤销 {proposal_id}",
            writes={proposal_rel: tombstone},
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
        allowed = {
            "permanent": {"active", "revised", "retired"},
            "mother": {"open", "evolving", "retired"},
            "action": {"planned", "acting", "observing", "reviewed"},
            "index": {"active", "revised", "retired"},
        }[metadata["type"]]
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
        for note_type, location in TYPE_LOCATIONS.items():
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
            f"规范化 {len(changed)} 份溯源笔记"
            if changed
            else "溯源笔记已经符合当前格式"
        )
        return self.repo.commit(
            transaction_id=txid,
            action="maintain-sources",
            summary=summary,
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
        permanent_types = {"permanent", "mother", "action", "index"}
        if not left or left[2].get("type") not in permanent_types:
            raise ValidationError(f"连接起点不是正式卡片：{from_id}")
        if not right or right[2].get("type") not in permanent_types:
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
        state.setdefault("proposals", {})[proposal_id] = {
            "kind": "connection",
            "path": proposal_rel.as_posix(),
            "status": "pending",
            "from_id": from_id,
            "to_id": to_id,
        }
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
        record = state.get("proposals", {}).get(proposal_id)
        if not record or record.get("kind") != "connection":
            raise ValidationError(f"找不到连接候选：{proposal_id}")
        if record.get("status") != "pending":
            raise ValidationError("连接候选已处理")
        proposal_rel = Path(record["path"])
        proposal_text = (self.repo.root / proposal_rel).read_text(encoding="utf-8")
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
        proposal_meta, _ = parse_document(proposal_text)
        proposal_meta["status"] = "accepted"
        proposal_meta["updated_at"] = timestamp
        proposal_text = replace_frontmatter(proposal_text, proposal_meta)
        state["proposals"][proposal_id]["status"] = "accepted"
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
                proposal_rel: proposal_text,
            },
            state=state,
            result=result,
        )

    def review(
        self,
        *,
        expire: bool = False,
        transaction_id: str | None = None,
        current_time: datetime | None = None,
    ) -> dict[str, Any]:
        now = current_time or datetime.now().astimezone()
        pending: list[dict[str, Any]] = []
        expired_writes: dict[Path, str] = {}
        for note_type in ("flash", "interesting", "todo", "source"):
            for path in sorted((self.repo.root / TYPE_LOCATIONS[note_type]).glob("*.md")):
                text = path.read_text(encoding="utf-8")
                metadata, _ = parse_document(text)
                if metadata.get("status") in {"pending", "open", "partial", "failed"}:
                    pending.append(
                        {
                            "id": metadata["id"],
                            "type": metadata["type"],
                            "title": metadata["title"],
                            "status": metadata["status"],
                            "path": path.relative_to(self.repo.root).as_posix(),
                        }
                    )
                if (
                    expire
                    and note_type == "flash"
                    and metadata.get("status") == "pending"
                ):
                    deadline_raw = metadata.get("expires_at")
                    if deadline_raw:
                        deadline = datetime.fromisoformat(deadline_raw)
                    else:
                        deadline = datetime.fromisoformat(metadata["created_at"]) + timedelta(
                            hours=48
                        )
                    if now >= deadline:
                        metadata["status"] = "expired"
                        metadata["updated_at"] = now.isoformat(timespec="seconds")
                        expired_writes[path.relative_to(self.repo.root)] = (
                            replace_frontmatter(text, metadata)
                        )
        if not expire:
            return {"pending": pending, "count": len(pending), "write": False}
        if not expired_writes:
            return {
                "pending": pending,
                "expired": [],
                "count": 0,
                "no_change": True,
            }
        txid = transaction_id or new_transaction_id("review-expire")
        if existing := self._idempotent(txid):
            return existing
        state = self.repo.read_state()
        expired_ids = []
        for content in expired_writes.values():
            metadata, _ = parse_document(content)
            expired_ids.append(metadata["id"])
        result = {"expired": expired_ids, "count": len(expired_ids)}
        return self.repo.commit(
            transaction_id=txid,
            action="review-expire",
            summary=f"失效 {len(expired_ids)} 条闪念",
            writes=expired_writes,
            state=state,
            result=result,
        )

    def lint(self, *, verify_git: bool = False) -> dict[str, Any]:
        issues: list[str] = []
        warnings: list[str] = []
        seen_ids: dict[str, str] = {}
        all_notes: list[tuple[Path, str, dict[str, Any]]] = []
        for expected_type, location in TYPE_LOCATIONS.items():
            for path in sorted((self.repo.root / location).glob("*.md")):
                rel = path.relative_to(self.repo.root)
                try:
                    text = path.read_text(encoding="utf-8")
                    metadata, _ = parse_document(text)
                except Exception as exc:
                    issues.append(f"{rel}: 无法解析：{exc}")
                    continue
                missing = validate_required_metadata(metadata)
                if missing:
                    issues.append(f"{rel}: 缺少字段 {missing}")
                if metadata.get("type") != expected_type:
                    issues.append(
                        f"{rel}: 目录要求 {expected_type}，实际 {metadata.get('type')}"
                    )
                note_id = str(metadata.get("id", ""))
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
                    if not metadata.get("canonical_url"):
                        issues.append(f"{rel}: 缺少规范链接 canonical_url")
                    headings = {
                        heading: text.find(f"## {heading}\n")
                        for heading in ("原文快照", "文献笔记", "关联闪念")
                    }
                    if not (
                        -1 < headings["原文快照"] < headings["文献笔记"]
                        < headings["关联闪念"]
                    ):
                        issues.append(
                            f"{rel}: 溯源顺序必须为标题、原文快照、文献笔记、关联闪念"
                        )
                    try:
                        _, snapshot_content, _, _ = extract_snapshot(text)
                        if snapshot_content.startswith("# 原文："):
                            issues.append(f"{rel}: 原文快照仍使用旧版重复标题包装")
                    except IntegrityError:
                        pass
                all_notes.append((rel, text, metadata))
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
        for canonical, record in state.get("sources", {}).items():
            target = self.repo.root / record.get("path", "")
            if not target.is_file():
                issues.append(f"来源账本失效：{canonical}")
        for proposal_id, record in state.get("proposals", {}).items():
            if record.get("kind") != "permanent":
                continue
            proposal_path = self.repo.root / record.get("path", "")
            if not proposal_path.is_file():
                issues.append(f"永久卡片草稿账本失效：{proposal_id}")
                continue
            try:
                proposal_text = proposal_path.read_text(encoding="utf-8")
                proposal_meta, proposal_body = parse_document(proposal_text)
            except Exception as exc:
                issues.append(f"永久卡片草稿无法解析：{proposal_id}: {exc}")
                continue
            if proposal_meta.get("status") != record.get("status"):
                issues.append(f"永久卡片草稿状态不一致：{proposal_id}")
            if record.get("status") in {"pending", "accepted"}:
                if record.get("authoring_mode") not in {
                    "user_verbatim",
                    "user_body_agent_title",
                }:
                    issues.append(f"永久卡片草稿不是用户原文：{proposal_id}")
                    continue
                try:
                    _, _, actual_sha256 = _validate_user_draft(proposal_body)
                except ValidationError as exc:
                    issues.append(f"永久卡片草稿格式异常：{proposal_id}: {exc}")
                    continue
                if (
                    actual_sha256 != record.get("draft_sha256")
                    or actual_sha256 != proposal_meta.get("draft_sha256")
                ):
                    issues.append(f"永久卡片草稿哈希异常：{proposal_id}")
            elif record.get("status") == "withdrawn":
                if PROPOSAL_START in proposal_text or "## 机器数据" in proposal_text:
                    issues.append(f"已撤销草稿仍暴露内部负载：{proposal_id}")
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
            if app_config.get("propertiesInDocument") != "hidden":
                issues.append("Obsidian 未默认隐藏机器 Frontmatter")
            if app_config.get("alwaysUpdateLinks") is not True:
                issues.append("Obsidian 未启用自动更新链接")
            if app_config.get("attachmentFolderPath") != ".goodidea/assets":
                issues.append("Obsidian 附件目录未指向 .goodidea/assets")
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
            if ".metadata-container" not in css:
                issues.append("Obsidian 样式未隐藏机器属性区域")
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
                f"## [{timestamp}] rollback | 回滚 {resolved[:12]} {subject} "
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
        return {
            "rolled_back": resolved,
            "revert_commit": revert_commit,
            "transaction_id": rollback_tx,
            "strategy": "git-revert",
        }
