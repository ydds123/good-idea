#!/usr/bin/env python3
"""Hermes 回合后适配器（Good Idea 默认实现）。

把 Hermes 的回合事件转成与平台无关的捕捉事件，交给通用执行契约
（`工具/capture.py`、`工具/commit.py`）。只有本文件认识 Hermes 的字段和钩子机制；
它不判断产品含义：未登记的 session 由 `capture.py` 静默忽略，是否进入捕捉、
何时 stop 由模型按规则决定。删掉本文件并移除钩子配置即禁用自动转录与自动提交，
记录仍可直接读写、由 Agent 手工补写。

- 取本回合用户可见消息与 Agent 最终可见回复；只在两者至少一项非空时动作
- 失败写 `.goodidea/tools.log` 并返回非零；始终向 stdout 输出 `{}`，不阻塞回合显示
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_FILE = ROOT / ".goodidea" / "tools.log"
CALL_TIMEOUT = 10
SPEAKER_USER = "松海"
SPEAKER_AGENT = "Agent"


def log(message: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} hermes_post_turn: {message}\n")
    except OSError:
        pass


def contract(tool: str, *args: str, stdin_text=None):
    """按执行契约调用工具/ 下的通用脚本。"""
    return subprocess.run(
        [sys.executable, str(ROOT / "工具" / tool), *args],
        cwd=ROOT,
        input=stdin_text,
        text=True,
        capture_output=True,
        timeout=CALL_TIMEOUT,
    )


def session_status(session: str) -> dict:
    result = contract("capture.py", "status", "--session", session)
    if result.returncode != 0:
        raise RuntimeError(f"status exit {result.returncode}: {result.stderr.strip()[:200]}")
    return json.loads(result.stdout or "{}")


def commit_message(record_path: str) -> str:
    parts = Path(record_path).stem.split("-", 3)
    return f"capture: {parts[3] if len(parts) > 3 else Path(record_path).stem}"


def handle_turn(payload: dict) -> int:
    extra = payload.get("extra")
    extra = extra if isinstance(extra, dict) else {}
    session = str(payload.get("session_id") or "")
    user_text = str(extra.get("user_message") or "").strip()
    reply_text = str(extra.get("assistant_response") or "").strip()
    turn_id = str(extra.get("turn_id") or "")
    if not session or not (user_text or reply_text):
        return 0
    info = session_status(session)
    if not info.get("active"):
        return 0  # 不在捕捉中：静默旁路
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    events = [
        {"speaker": speaker, "time": stamp, "text": text, "turn_id": turn_id}
        for speaker, text in ((SPEAKER_USER, user_text), (SPEAKER_AGENT, reply_text))
        if text
    ]
    appended = contract("capture.py", "append", "--session", session, stdin_text=json.dumps(events, ensure_ascii=False))
    if appended.returncode != 0:
        log(f"append failed session={session} exit={appended.returncode}: {appended.stderr.strip()[:200]}")
        return 1
    if info.get("status") != "closing":
        return 0
    # stop 所在回合：这一次 append 已注销 session，最后一条消息确认落盘后才提交
    if session_status(session).get("active"):
        log(f"session {session} still registered after closing append")
        return 1
    record = str(info.get("path") or "")
    committed = contract("commit.py", record, "--message", commit_message(record))
    if committed.returncode != 0:
        log(f"commit failed session={session} path={record} exit={committed.returncode}: {committed.stderr.strip()[:200]}")
        return 1
    return 0


def main() -> int:
    code = 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("payload is not a JSON object")
        if payload.get("hook_event_name") == "post_llm_call":
            code = handle_turn(payload)
    except Exception as exc:  # 失败只写日志、返回非零，不影响回合
        log(f"adapter error: {type(exc).__name__}: {exc}")
        code = 1
    sys.stdout.write("{}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
