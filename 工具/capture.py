#!/usr/bin/env python3
"""Manage optional original-thought capture records."""
from __future__ import annotations
import argparse, json, re, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE, LOG = ROOT / ".goodidea/capture-sessions.json", ROOT / ".goodidea/tools.log"
TARGET, TEMPLATE = ROOT / "数据/记录/闪念/原始思考记录", ROOT / "数据/模板/original-thought.md"

def log(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(message.rstrip() + "\n")

def state() -> dict:
    try:
        value = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

def save(value: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(STATE)

def next_path(stem: str) -> Path:
    path, number = TARGET / f"{stem}.md", 2
    while path.exists():
        path, number = TARGET / f"{stem}-{number}.md", number + 1
    return path

def empty_record() -> str:
    text = re.sub(r"^> .*\n", "", TEMPLATE.read_text(encoding="utf-8"), flags=re.M)
    text = text.replace("../../规则/", "../../../../规则/")
    return text[:text.index("## 对话")] + "## 对话\n"

def start(args: argparse.Namespace) -> int:
    records = state()
    if args.session in records:
        print(records[args.session]["path"]); return 0
    if args.resume:
        path = (ROOT / args.resume).resolve()
        if not path.is_file() or ROOT not in path.parents:
            print("续接记录不存在或不在仓库内", file=sys.stderr); return 2
    else:
        title = " ".join(args.title.split())
        if not title or "/" in title or "\\" in title:
            print("标题不能为空，且不能包含路径分隔符", file=sys.stderr); return 2
        TARGET.mkdir(parents=True, exist_ok=True)
        path = next_path(f"{date.today().isoformat()}-{title}")
        path.write_text(empty_record(), encoding="utf-8")
    records[args.session] = {"path": str(path.relative_to(ROOT)), "status": "active"}
    save(records); print(path.relative_to(ROOT)); return 0

def messages(text: str) -> tuple[set[tuple[str, str, str]], int | None]:
    marker = text.rfind("\n## 去向")
    body = text if marker < 0 else text[:marker]
    pattern = r"^### (?P<time>[^｜\n]+)｜(?P<speaker>[^\n]+)\n\n(?P<text>.*?)(?=^### |\Z)"
    found = {(m["time"], m["speaker"], m["text"]) for m in re.finditer(pattern, body, re.M | re.S)}
    return found, marker if marker >= 0 else None

def append(args: argparse.Namespace) -> int:
    record = state().get(args.session)
    if not record:
        log(f"append ignored: unknown session {args.session}"); return 0
    path, content = ROOT / record["path"], (ROOT / record["path"]).read_text(encoding="utf-8")
    try: events = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        log(f"append failed: invalid JSON: {error}"); print(f"事件 JSON 无效：{error}", file=sys.stderr); return 2
    if not isinstance(events, list):
        log("append failed: events is not an array"); print("事件必须是 JSON 数组", file=sys.stderr); return 2
    existing, marker, added = *messages(content), []
    for event in events:
        if not isinstance(event, dict) or not all(isinstance(event.get(k), str) and event[k] for k in ("speaker", "time", "text")):
            log("append failed: event missing speaker/time/text"); print("事件缺少 speaker、time 或 text", file=sys.stderr); return 2
        key = event["time"], event["speaker"], event["text"]
        if key in existing: continue
        existing.add(key); added.append(f"### {event['time']}｜{event['speaker']}\n\n{event['text']}\n")
    if added:
        insertion = "\n" + "\n".join(added)
        content = content[:marker] + insertion + content[marker:] if marker is not None else content.rstrip() + insertion + "\n"
        path.write_text(content, encoding="utf-8")
    return 0

def stop(args: argparse.Namespace) -> int:
    records = state()
    if args.session in records:
        records[args.session]["status"] = "closing"; save(records)
    else: log(f"stop ignored: unknown session {args.session}")
    return 0

def status(args: argparse.Namespace) -> int:
    record = state().get(args.session)
    if not record: print("未登记"); return 0
    path = ROOT / record["path"]; text = path.read_text(encoding="utf-8") if path.exists() else ""
    count = len(re.findall(r"^### (?!YYYY-MM-DD)", text, re.M))
    print(json.dumps({"path": record["path"], "status": record["status"], "messages": count, "exists": path.exists()}, ensure_ascii=False)); return 0

def main() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    for name, function in (("start", start), ("append", append), ("stop", stop), ("status", status)):
        current = sub.add_parser(name); current.add_argument("--session", required=True)
        if name == "start": current.add_argument("--title", required=True); current.add_argument("--resume")
        current.set_defaults(fn=function)
    args = parser.parse_args()
    try: return args.fn(args)
    except (OSError, KeyError) as error:
        log(f"capture failed: {error}"); print(f"执行失败：{error}", file=sys.stderr); return 1

if __name__ == "__main__": raise SystemExit(main())
