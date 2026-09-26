#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".goodidea" / "capture-sessions.json"
TARGET = ROOT / "数据/记录/闪念/原始思考记录"
TEMPLATE = ROOT / "数据/模板/original-thought.md"


def load_state() -> dict:
    if not STATE.exists():
        return {}
    try:
        value = json.loads(STATE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATE)


def record_path(stem: str) -> Path:
    candidate = TARGET / f"{stem}.md"
    number = 2
    while candidate.exists():
        candidate = TARGET / f"{stem}-{number}.md"
        number += 1
    return candidate


def start(args: argparse.Namespace) -> int:
    state = load_state()
    if args.session in state:
        print(state[args.session]["path"])
        return 0
    if args.resume:
        path = (ROOT / args.resume).resolve()
        if not path.is_file() or ROOT not in path.parents:
            print("续接记录不存在或不在仓库内", file=sys.stderr)
            return 2
    else:
        if not TEMPLATE.is_file():
            print("原始思考记录模板不存在", file=sys.stderr)
            return 2
        TARGET.mkdir(parents=True, exist_ok=True)
        path = record_path(f"{date.today().isoformat()}-{args.title.strip()}")
        if not args.title.strip() or "/" in args.title or "\\" in args.title:
            print("标题不能为空，且不能包含路径分隔符", file=sys.stderr)
            return 2
        shutil.copyfile(TEMPLATE, path)
    state[args.session] = {"path": str(path.relative_to(ROOT)), "status": "active"}
    save_state(state)
    print(path.relative_to(ROOT))
    return 0


def message_block(event: dict) -> str:
    return f"### {event['time']}｜{event['speaker']}\n\n{event['text']}\n"


def append(args: argparse.Namespace) -> int:
    state = load_state()
    session = state.get(args.session)
    if not session:
        return 0
    path = ROOT / session["path"]
    try:
        events = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        print(f"事件 JSON 无效：{error}", file=sys.stderr)
        return 2
    if not isinstance(events, list):
        print("事件必须是 JSON 数组", file=sys.stderr)
        return 2
    content = path.read_text(encoding="utf-8")
    added = []
    for event in events:
        if not all(isinstance(event.get(k), str) and event[k] for k in ("speaker", "time", "text")):
            print("事件缺少 speaker、time 或 text", file=sys.stderr)
            return 2
        block = message_block(event)
        if block in content:
            continue
        added.append(block)
    if added:
        marker = "\n## 去向"
        if marker in content:
            content = content.replace(marker, "\n" + "\n".join(added) + marker, 1)
        else:
            if not content.endswith("\n"):
                content += "\n"
            content += "\n".join(added)
        path.write_text(content, encoding="utf-8")
    return 0


def stop(args: argparse.Namespace) -> int:
    state = load_state()
    if args.session not in state:
        return 0
    state[args.session]["status"] = "closing"
    save_state(state)
    return 0


def status(args: argparse.Namespace) -> int:
    session = load_state().get(args.session)
    if not session:
        print("未登记")
        return 0
    path = ROOT / session["path"]
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    count = sum(
        1 for line in text.splitlines()
        if line.startswith("### ") and "YYYY-MM-DD" not in line
    )
    print(json.dumps({"path": session["path"], "status": session["status"], "messages": count, "exists": path.exists()}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("start"); p.add_argument("--session", required=True); p.add_argument("--title", required=True); p.add_argument("--resume")
    p.set_defaults(fn=start)
    p = sub.add_parser("append"); p.add_argument("--session", required=True); p.set_defaults(fn=append)
    p = sub.add_parser("stop"); p.add_argument("--session", required=True); p.set_defaults(fn=stop)
    p = sub.add_parser("status"); p.add_argument("--session", required=True); p.set_defaults(fn=status)
    return args_fn(parser.parse_args())


def args_fn(args: argparse.Namespace) -> int:
    try:
        return args.fn(args)
    except (OSError, KeyError) as error:
        print(f"执行失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
