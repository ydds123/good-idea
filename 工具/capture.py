#!/usr/bin/env python3
"""A platform-neutral capture recorder. It never decides product meaning."""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".goodidea"
STATE_FILE = STATE_DIR / "capture-sessions.json"
LOG_FILE = STATE_DIR / "tools.log"
RECORD_DIR = ROOT / "数据/记录/闪念/原始思考记录"
def log(message):
    STATE_DIR.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now().isoformat(timespec='seconds')} {message}\n")
def state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log(f"state read failed: {exc}")
        return {}
def save(data):
    STATE_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
def unique_path(title):
    base = RECORD_DIR / f"{dt.date.today().isoformat()}-{title}.md"
    path, n = base, 2
    while path.exists():
        path = RECORD_DIR / f"{dt.date.today().isoformat()}-{title}-{n}.md"
        n += 1
    return path


def valid_title(title):
    return bool(title.strip()) and Path(title).name == title and title not in {".", ".."}
def start(args):
    records = state()
    if args.session in records:
        log(f"start rejected: session already exists {args.session}")
        print("session already exists", file=sys.stderr)
        return 2
    if not valid_title(args.title):
        log(f"invalid title: {args.title!r}")
        print("标题不能包含路径分隔符", file=sys.stderr)
        return 2
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    if args.resume:
        path = Path(args.resume)
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            log(f"resume missing: {path}")
            return 3
    else:
        path = unique_path(args.title)
        template = ROOT / "数据/模板/original-thought.md"
        text = template.read_text(encoding="utf-8")
        text = text.replace("../../规则/", "../../../规则/")
        text = re.sub(r"；本模板只展示 Markdown 文件形状。", "。", text)
        text = re.sub(r"\n### YYYY-MM-DD HH:MM｜松海\n\n消息原文。\n", "\n", text)
        text = re.sub(r"\n### YYYY-MM-DD HH:MM｜Agent\n\n消息原文。\n", "\n", text)
        text = re.sub(r"\n## 去向\n[\s\S]*$", "\n", text)
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
    records[args.session] = {"path": str(path.relative_to(ROOT)), "status": "open", "turns": 0, "last_error": ""}
    save(records)
    print(path.relative_to(ROOT))
    return 0
def messages(text):
    pattern = re.compile(r"^### (\d{4}-\d\d-\d\d \d\d:\d\d)｜(松海|Agent)\n", re.M)
    found = list(pattern.finditer(text))
    result = []
    for i, match in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        body = text[match.end():end].strip("\n")
        result.append((match.group(1), match.group(2), body))
    return result
def append(args):
    records = state()
    item = records.get(args.session)
    if not item:
        return 0
    path = ROOT / item["path"]
    try:
        incoming = json.load(sys.stdin)
        if not isinstance(incoming, list):
            raise ValueError("stdin must be a JSON array")
        original = path.read_text(encoding="utf-8")
        existing = set(messages(original))
        additions = []
        for event in incoming:
            key = (str(event["time"]), str(event["speaker"]), str(event["text"]).strip("\n"))
            if key not in existing:
                additions.append(key)
                existing.add(key)
        if additions:
            block = "\n".join(f"### {t}｜{s}\n\n{text}\n" for t, s, text in additions)
            marker = re.search(r"^## 去向\s*$", original, re.M)
            original = original[:marker.start()] + block + "\n" + original[marker.start():] if marker else original.rstrip() + "\n\n" + block
            path.write_text(original.rstrip() + "\n", encoding="utf-8")
            item["turns"] = item.get("turns", 0) + len(additions)
        if item.get("status") == "closing":
            del records[args.session]
        save(records)
        return 0
    except Exception as exc:
        item["last_error"] = str(exc)
        save(records)
        log(f"append failed for {args.session}: {exc}")
        print(str(exc), file=sys.stderr)
        return 3
def stop(args):
    records = state()
    if args.session not in records:
        return 0
    records[args.session]["status"] = "closing"
    save(records)
    return 0
def status(args):
    item = state().get(args.session)
    if not item:
        print(json.dumps({"session": args.session, "active": False}, ensure_ascii=False))
        return 0
    path = ROOT / item["path"]
    dirty = False
    if path.exists():
        result = subprocess.run(["git", "status", "--short", "--", str(path)], cwd=ROOT, text=True, capture_output=True)
        dirty = bool(result.stdout.strip())
    print(json.dumps({"session": args.session, **item, "active": True, "uncommitted": dirty}, ensure_ascii=False))
    return 0
def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "append", "stop", "status"):
        p = sub.add_parser(name)
        p.add_argument("--session", required=True)
        if name == "start":
            p.add_argument("--title", required=False, default="未命名捕捉")
            p.add_argument("--resume")
    args = parser.parse_args()
    return globals()[args.command](args)
if __name__ == "__main__":
    raise SystemExit(main())
