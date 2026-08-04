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
from .metadata import parse_document, replace_frontmatter
from .notes import (
    TYPE_LOCATIONS,
    add_list_item_to_section,
    render_note,
    render_source_note,
    replace_source_snapshot,
    safe_filename,
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


class GoodIdeaService:
    def __init__(self, repo: Repository):
        self.repo = repo

    def _idempotent(self, transaction_id: str) -> dict[str, Any] | None:
        return self.repo.transaction_result(transaction_id)

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
        filename = f"{note_id}-{safe_filename(note_title, note_id)}.md"
        rel = TYPE_LOCATIONS[kind] / filename
        timestamp = now_iso()
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
        lines = [f"# 原文：{preview.get('title') or preview.get('canonical_url')}"]
        if preview.get("author"):
            lines.append(f"- 作者：{preview['author']}")
        if preview.get("published_at"):
            lines.append(f"- 发布日期：{preview['published_at']}")
        lines.extend(
            [
                f"- 原始链接：{preview.get('url', '')}",
                f"- 规范链接：{preview.get('canonical_url', '')}",
            ]
        )
        if preview.get("error"):
            lines.append(f"- 抓取说明：{preview['error']}")
        lines.extend(["", "---", "", localized_markdown or "> 未能取得正文。"])
        return "\n".join(lines).strip() + "\n"

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
            filename = f"{source_id}-{safe_filename(title, source_id)}.md"
            source_rel = TYPE_LOCATIONS["source"] / filename
            source_title = title
            source_meta = {
                "id": source_id,
                "type": "source",
                "title": title,
                "status": capture_status,
                "capture_status": capture_status,
                "source_url": str(preview.get("url") or canonical_url),
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
                "summary": "原文快照，文献笔记待处理",
            }

        flash_rel = TYPE_LOCATIONS["flash"] / (
            f"{flash_id}-{safe_filename(flash_title, flash_id)}.md"
        )
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
            source_note = add_list_item_to_section(
                source_note, "关联闪念", flash_link
            )
            source_note = replace_frontmatter(source_note, source_meta)
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
                    "source_url": str(
                        candidate.get("url") or source_meta.get("source_url", "")
                    ),
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
            proposal_meta, _ = parse_document(proposal_text)
            proposal_meta["status"] = "accepted"
            proposal_meta["updated_at"] = timestamp
            proposal_text = replace_frontmatter(proposal_text, proposal_meta)
            state["proposals"][confirm_proposal]["status"] = "accepted"
            writes: dict[Path, str | bytes] = {
                source_rel: updated_source,
                proposal_rel: proposal_text,
                **assets,
            }
            result = {
                "source_id": source_id,
                "source_path": source_rel.as_posix(),
                "proposal_id": confirm_proposal,
                "status": capture_status,
            }
            return self.repo.commit(
                transaction_id=txid,
                action="source-refresh-accept",
                summary=source_meta["title"],
                writes=writes,
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
        title: str,
        claim: str,
        reason: str = "",
        boundaries: str = "",
        source_ids: list[str] | None = None,
        from_ids: list[str] | None = None,
        context: str = "",
        judgment: str = "",
        action: str = "",
        result_text: str = "",
        adjustment: str = "",
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if card_type not in {"permanent", "mother", "action", "index"}:
            raise ValidationError(f"不支持的永久卡片类型：{card_type}")
        if not title.strip() or not claim.strip():
            raise ValidationError("卡片候选必须包含标题和中心内容")
        txid = transaction_id or new_transaction_id("permanent-propose")
        if existing := self._idempotent(txid):
            return existing
        proposal_id = stable_id("PRP", f"{card_type}:{txid}", dated=False)
        proposal_rel = Path(f".goodidea/proposals/permanent/{proposal_id}.md")
        timestamp = now_iso()
        payload = {
            "card_type": card_type,
            "title": title.strip(),
            "claim": claim.strip(),
            "reason": reason.strip(),
            "boundaries": boundaries.strip(),
            "source_ids": source_ids or [],
            "from_ids": from_ids or [],
            "context": context.strip(),
            "judgment": judgment.strip(),
            "action": action.strip(),
            "result": result_text.strip(),
            "adjustment": adjustment.strip(),
        }
        for note_id in payload["source_ids"] + payload["from_ids"]:
            if not self.repo.find_note(note_id):
                raise ValidationError(f"候选引用了不存在的对象：{note_id}")
        proposal_meta = {
            "id": proposal_id,
            "type": "permanent_proposal",
            "title": f"候选：{title.strip()}",
            "status": "pending",
            "card_type": card_type,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        proposal_text = _proposal_document(proposal_meta, payload)
        state = self.repo.read_state()
        state.setdefault("proposals", {})[proposal_id] = {
            "kind": "permanent",
            "path": proposal_rel.as_posix(),
            "status": "pending",
            "card_type": card_type,
        }
        result = {
            "proposal_id": proposal_id,
            "proposal_path": proposal_rel.as_posix(),
            "card_type": card_type,
        }
        return self.repo.commit(
            transaction_id=txid,
            action="permanent-propose",
            summary=title.strip(),
            writes={proposal_rel: proposal_text},
            state=state,
            result=result,
        )

    def permanent_accept(
        self,
        proposal_id: str,
        *,
        explanation: str,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        if not _meaningful(explanation, minimum=8):
            raise ValidationError(
                "正式接纳永久卡片前，必须用自己的语言解释这条认识；纯确认或过短复述无效"
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
        proposal_rel = Path(record["path"])
        proposal_text = (self.repo.root / proposal_rel).read_text(encoding="utf-8")
        payload = _proposal_payload(proposal_text)
        card_type = payload["card_type"]
        prefix = {
            "permanent": "PER",
            "mother": "MOT",
            "action": "ACT",
            "index": "IDX",
        }[card_type]
        card_id = stable_id(prefix, f"{proposal_id}:{explanation}")
        title = payload["title"]
        card_rel = TYPE_LOCATIONS[card_type] / (
            f"{card_id}-{safe_filename(title, card_id)}.md"
        )
        timestamp = now_iso()
        status = _default_status(card_type)
        metadata = {
            "id": card_id,
            "type": card_type,
            "title": title,
            "status": status,
            "created_at": timestamp,
            "updated_at": timestamp,
            "source_ids": payload.get("source_ids", []),
            "derived_from": payload.get("from_ids", []),
            "summary": payload["claim"].replace("\n", " ")[:100],
        }
        source_links: list[str] = []
        for note_id in payload.get("source_ids", []):
            found = self.repo.find_note(note_id)
            if found:
                source_links.append(wiki_link(found[0], found[2]["title"]))
        source_text = "\n".join(f"- {link}" for link in source_links) or "_暂无_"
        if card_type == "permanent":
            sections = [
                ("核心判断", payload["claim"]),
                ("我的解释", explanation),
                ("成立理由", payload.get("reason") or "待继续验证"),
                ("边界与反例", payload.get("boundaries") or "待继续寻找"),
                ("来源", source_text),
                ("连接", "_暂无_"),
            ]
        elif card_type == "mother":
            sections = [
                ("开放问题", payload["claim"]),
                ("当前阶段性认识", payload.get("reason") or "尚未形成"),
                ("我的解释", explanation),
                ("证据与矛盾", payload.get("boundaries") or "待积累"),
                ("下一步", payload.get("action") or "继续观察与提问"),
                ("连接", "_暂无_"),
            ]
        elif card_type == "action":
            sections = [
                ("情境", payload.get("context") or payload["claim"]),
                ("当时信息", payload.get("reason") or "待补充"),
                ("判断", payload.get("judgment") or payload["claim"]),
                ("行动", payload.get("action") or "待执行"),
                ("结果", payload.get("result") or "待反馈"),
                ("修正", payload.get("adjustment") or "待复盘"),
                ("我的解释", explanation),
                ("连接", "_暂无_"),
            ]
        else:
            sections = [
                ("索引目的", payload["claim"]),
                ("入口卡片", source_text),
                ("我的解释", explanation),
                ("维护说明", payload.get("boundaries") or "随卡片网络演化调整"),
                ("连接", "_暂无_"),
            ]
        card_text = render_note(metadata, sections)
        writes: dict[Path, str | bytes] = {card_rel: card_text}
        proposal_meta, _ = parse_document(proposal_text)
        proposal_meta["status"] = "accepted"
        proposal_meta["accepted_card_id"] = card_id
        proposal_meta["updated_at"] = timestamp
        writes[proposal_rel] = replace_frontmatter(proposal_text, proposal_meta)
        for from_id in payload.get("from_ids", []):
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

    def permanent_revise(
        self,
        card_id: str,
        *,
        note: str,
        status: str = "",
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
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
        text = add_list_item_to_section(
            text, "演化记录", f"{timestamp} — {note.strip()}"
        )
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
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
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
        text = add_list_item_to_section(
            text, "结果", f"{timestamp} — {result_text.strip()}"
        )
        text = add_list_item_to_section(
            text, "修正", f"{timestamp} — {adjustment.strip()}"
        )
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
                if expected_type == "source":
                    try:
                        validate_source_note(text, rel.as_posix())
                    except IntegrityError as exc:
                        issues.append(str(exc))
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
        process = _run_git(
            self.repo.root, ["revert", "--no-edit", resolved], check=False
        )
        if process.returncode != 0:
            _run_git(self.repo.root, ["revert", "--abort"], check=False)
            raise GitError(process.stderr.strip() or "git revert 失败")
        revert_commit = _run_git(self.repo.root, ["rev-parse", "HEAD"]).stdout.strip()
        return {
            "rolled_back": resolved,
            "revert_commit": revert_commit,
            "strategy": "git-revert",
        }
