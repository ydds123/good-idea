from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .errors import GoodIdeaError, ValidationError
from .repository import Repository, initialize_vault
from .service import GoodIdeaService
from .web import preview_from_html, preview_from_markdown, preview_from_url


def _json(data: Any, *, stream: Any = sys.stdout) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), file=stream)


def _read_json(path: str) -> dict[str, Any]:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValidationError("preview 必须是 JSON 对象")
    return value


def _read_text(path: str) -> str:
    return sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")


def _split_ids(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="goodidea", description="Good idea v0.1 deterministic local kernel"
    )
    parser.add_argument("--root", help="Good idea 仓库路径")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="初始化一个独立 Good idea 仓库")
    init.add_argument("path", nargs="?", default=".")

    capture = sub.add_parser("capture", help="捕捉轻量记录")
    capture.add_argument("kind", choices=["flash", "interesting", "todo"])
    capture.add_argument("--text", required=True)
    capture.add_argument("--title", default="")
    capture.add_argument("--context", default="")
    capture.add_argument("--source-id", default="")
    capture.add_argument("--transaction-id")

    source = sub.add_parser("source", help="来源预读、录入和刷新")
    source_sub = source.add_subparsers(dest="source_command", required=True)
    preview = source_sub.add_parser("preview", help="只读生成临时来源 preview")
    preview.add_argument("--url", required=True)
    input_group = preview.add_mutually_exclusive_group()
    input_group.add_argument("--html-file")
    input_group.add_argument("--markdown-file")
    preview.add_argument("--title", default="")
    preview.add_argument("--author", default="")
    preview.add_argument("--published-at", default="")
    preview.add_argument("--output")

    source_commit = source_sub.add_parser(
        "commit", help="在用户说明保存动机后录入来源和闪念"
    )
    source_commit.add_argument("--preview-file", required=True)
    source_commit.add_argument("--motivation", required=True)
    source_commit.add_argument("--transaction-id")

    refresh = source_sub.add_parser("refresh", help="生成或接受来源更新候选")
    refresh.add_argument("--source-id", required=True)
    refresh.add_argument("--preview-file")
    refresh.add_argument("--confirm-proposal", default="")
    refresh.add_argument("--transaction-id")

    review = sub.add_parser("review", help="回顾中间材料")
    review.add_argument("--expire", action="store_true")
    review.add_argument("--transaction-id")

    maintain = sub.add_parser("maintain", help="执行确定性的仓库机械维护")
    maintain_sub = maintain.add_subparsers(dest="maintain_command", required=True)
    filenames = maintain_sub.add_parser(
        "filenames", help="把所有内容文件统一为 YYYY-MM-DD-标题.md"
    )
    filenames.add_argument("--transaction-id")
    sources = maintain_sub.add_parser(
        "sources", help="统一溯源笔记顺序并只保留规范链接"
    )
    sources.add_argument("--transaction-id")

    permanent = sub.add_parser("permanent", help="用户原文草稿与永久卡片状态流转")
    permanent_sub = permanent.add_subparsers(
        dest="permanent_command", required=True
    )
    propose = permanent_sub.add_parser("propose", help="提交用户亲自写成的草稿")
    propose.add_argument(
        "--type", required=True, choices=["permanent", "mother", "action", "index"]
    )
    propose.add_argument(
        "--title",
        default="",
        help="Agent 从用户内容中忠实提炼的标题；使用时 draft-file 只含用户正文",
    )
    propose.add_argument(
        "--draft-file",
        required=True,
        help="用户原文 Markdown 草稿；传 - 从 stdin 读取",
    )
    propose.add_argument("--source-ids", default="")
    propose.add_argument("--from-ids", default="")
    propose.add_argument("--transaction-id")

    accept = permanent_sub.add_parser("accept", help="按用户明确指令发布原文草稿")
    accept.add_argument("--proposal-id", required=True)
    accept.add_argument("--confirm-user-authored", action="store_true")
    accept.add_argument("--transaction-id")

    withdraw = permanent_sub.add_parser("withdraw", help="撤销待处理草稿")
    withdraw.add_argument("--proposal-id", required=True)
    withdraw.add_argument("--reason", required=True)
    withdraw.add_argument("--transaction-id")

    revise = permanent_sub.add_parser("revise")
    revise.add_argument("--card-id", required=True)
    revise.add_argument("--note", required=True)
    revise.add_argument("--status", default="")
    revise.add_argument("--confirm-user-authored", action="store_true")
    revise.add_argument("--transaction-id")

    feedback = permanent_sub.add_parser("feedback")
    feedback.add_argument("--card-id", required=True)
    feedback.add_argument("--result", required=True)
    feedback.add_argument("--adjustment", required=True)
    feedback.add_argument("--confirm-user-authored", action="store_true")
    feedback.add_argument("--transaction-id")

    connect = sub.add_parser("connect", help="语义连接候选与确认")
    connect_sub = connect.add_subparsers(dest="connect_command", required=True)
    connect_propose = connect_sub.add_parser("propose")
    connect_propose.add_argument("--from-id", required=True)
    connect_propose.add_argument("--to-id", required=True)
    connect_propose.add_argument("--relation", required=True)
    connect_propose.add_argument("--rationale", required=True)
    connect_propose.add_argument("--transaction-id")
    connect_accept = connect_sub.add_parser("accept")
    connect_accept.add_argument("--proposal-id", required=True)
    connect_accept.add_argument("--transaction-id")

    sub.add_parser("lint", help="检查结构和链接")
    sub.add_parser("verify", help="检查结构、链接和 Git 清洁状态")
    rollback = sub.add_parser("rollback", help="通过 git revert 回滚事务提交")
    rollback.add_argument("--commit", required=True)
    rollback.add_argument("--yes", action="store_true")
    return parser


def _source_preview(args: argparse.Namespace) -> dict[str, Any]:
    if args.html_file:
        html_text = (
            sys.stdin.read()
            if args.html_file == "-"
            else Path(args.html_file).read_text(encoding="utf-8")
        )
        value = preview_from_html(
            args.url, html_text
        )
    elif args.markdown_file:
        markdown_text = (
            sys.stdin.read()
            if args.markdown_file == "-"
            else Path(args.markdown_file).read_text(encoding="utf-8")
        )
        value = preview_from_markdown(
            args.url,
            markdown_text,
            title=args.title,
            author=args.author,
            published_at=args.published_at,
        )
    else:
        value = preview_from_url(args.url)
    if args.output:
        output = Path(args.output).resolve()
        root = None
        if args.root:
            root = Path(args.root).resolve()
        else:
            try:
                root = Repository.discover().root
            except ValidationError:
                pass
        if root:
            if output == root or output.is_relative_to(root):
                raise ValidationError("预读阶段禁止把 preview 写入 Good idea 仓库")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        value = {**value, "preview_file": str(output)}
    return value


def dispatch(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.command == "init":
        return initialize_vault(Path(args.path)), 0
    if args.command == "source" and args.source_command == "preview":
        return _source_preview(args), 0

    repo = Repository.discover(args.root)
    service = GoodIdeaService(repo)
    if args.command == "capture":
        result = service.capture(
            args.kind,
            text=args.text,
            title=args.title,
            context=args.context,
            source_id=args.source_id,
            transaction_id=args.transaction_id,
        )
    elif args.command == "source" and args.source_command == "commit":
        result = service.source_commit(
            _read_json(args.preview_file),
            motivation=args.motivation,
            transaction_id=args.transaction_id,
        )
    elif args.command == "source" and args.source_command == "refresh":
        preview = _read_json(args.preview_file) if args.preview_file else None
        result = service.source_refresh(
            args.source_id,
            preview=preview,
            confirm_proposal=args.confirm_proposal,
            transaction_id=args.transaction_id,
        )
    elif args.command == "review":
        result = service.review(
            expire=args.expire, transaction_id=args.transaction_id
        )
    elif args.command == "maintain" and args.maintain_command == "filenames":
        result = service.maintain_filenames(transaction_id=args.transaction_id)
    elif args.command == "maintain" and args.maintain_command == "sources":
        result = service.maintain_sources(transaction_id=args.transaction_id)
    elif args.command == "permanent":
        if args.permanent_command == "propose":
            result = service.permanent_propose(
                args.type,
                draft=_read_text(args.draft_file),
                title=args.title,
                source_ids=_split_ids(args.source_ids),
                from_ids=_split_ids(args.from_ids),
                transaction_id=args.transaction_id,
            )
        elif args.permanent_command == "accept":
            result = service.permanent_accept(
                args.proposal_id,
                confirmed_by_user=args.confirm_user_authored,
                transaction_id=args.transaction_id,
            )
        elif args.permanent_command == "withdraw":
            result = service.permanent_withdraw(
                args.proposal_id,
                reason=args.reason,
                transaction_id=args.transaction_id,
            )
        elif args.permanent_command == "revise":
            result = service.permanent_revise(
                args.card_id,
                note=args.note,
                confirmed_by_user=args.confirm_user_authored,
                status=args.status,
                transaction_id=args.transaction_id,
            )
        else:
            result = service.action_feedback(
                args.card_id,
                result_text=args.result,
                adjustment=args.adjustment,
                confirmed_by_user=args.confirm_user_authored,
                transaction_id=args.transaction_id,
            )
    elif args.command == "connect":
        if args.connect_command == "propose":
            result = service.connect_propose(
                args.from_id,
                args.to_id,
                relation=args.relation,
                rationale=args.rationale,
                transaction_id=args.transaction_id,
            )
        else:
            result = service.connect_accept(
                args.proposal_id, transaction_id=args.transaction_id
            )
    elif args.command == "lint":
        result = service.lint()
    elif args.command == "verify":
        result = service.lint(verify_git=True)
    elif args.command == "rollback":
        result = service.rollback(args.commit, confirmed=args.yes)
    else:
        raise ValidationError("未知命令")
    return result, 0 if result.get("ok", True) else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result, code = dispatch(args)
        _json(result)
        return code
    except GoodIdeaError as exc:
        _json(
            {"ok": False, "error": {"code": exc.code, "message": str(exc)}},
            stream=sys.stderr,
        )
        return 2
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        _json(
            {
                "ok": False,
                "error": {"code": "input_error", "message": str(exc)},
            },
            stream=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
