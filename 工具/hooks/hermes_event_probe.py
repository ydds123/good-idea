#!/usr/bin/env python3
"""Hermes 回合事件探针（Good Idea 阶段 0）。

只做一件事：把 Hermes 回合钩子收到的载荷字段、时序和自身耗时记到独立日志，
供核实事件契约用。不做任何产品动作：

- 不调用 工具/capture.py，不写 数据/记录/
- 不记录系统提示、思考过程、工具调用正文
- 只留字段名、类型、文本长度和必要时极短片段（脱敏）
- 始终向 stdout 输出 `{}`（观察者事件的无操作应答），不阻塞回合
- 自身失败时写日志并返回非零，不抛出到调用方

日志：<仓库根>/.goodidea/probe.log（运行时派生状态，已 gitignore）
测试用环境变量：HERMES_PROBE_SLEEP_MS=<毫秒>（用于判定钩子是同步还是异步）
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

T0 = time.monotonic()
REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = REPO_ROOT / ".goodidea" / "probe.log"
SAMPLE_CHARS = 40


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _describe(value) -> dict:
    """字段画像：类型 + 长度 + 极短片段；不落全文。"""
    if value is None:
        return {"type": "null"}
    if isinstance(value, str):
        return {
            "type": "str",
            "len": len(value),
            "head": value[:SAMPLE_CHARS],
            "tail": value[-12:] if len(value) > SAMPLE_CHARS else "",
        }
    if isinstance(value, list):
        return {"type": "list", "len": len(value)}
    if isinstance(value, dict):
        return {"type": "dict", "keys": sorted(value)[:12]}
    return {"type": type(value).__name__, "value": str(value)[:SAMPLE_CHARS]}


def _write(record: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    raw = sys.stdin.read()
    record = {
        "ts": _now_iso(),
        "pid": os.getpid(),
        "event": None,
        "session_id": None,
        "cwd": None,
        "profile": None,
        "fields": {},
        "missing_key_fields": [],
        "stdin_bytes": len(raw),
        "ok": True,
    }
    try:
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            raise ValueError(f"payload is {type(payload).__name__}, expected object")
        record["event"] = payload.get("hook_event_name")
        record["session_id"] = payload.get("session_id")
        record["cwd"] = payload.get("cwd")
        record["profile"] = payload.get("profile")
        extra: dict = {}
        candidate = payload.get("extra")
        if isinstance(candidate, dict):
            extra = candidate
        observed = {k: v for k, v in payload.items() if k != "extra"}
        observed.update(extra)
        record["fields"] = {k: _describe(v) for k, v in sorted(observed.items())}
        for key in ("session_id", "turn_id", "user_message", "assistant_response"):
            if observed.get(key) in (None, ""):
                record["missing_key_fields"].append(key)
    except Exception as exc:  # 失败只写日志、返回非零，不阻塞回合
        record["ok"] = False
        record["error"] = f"{type(exc).__name__}: {exc}"

    sleep_ms = int(os.environ.get("HERMES_PROBE_SLEEP_MS", "0") or 0)
    record["sleep_ms"] = sleep_ms
    if sleep_ms:
        time.sleep(sleep_ms / 1000)
    record["elapsed_ms"] = round((time.monotonic() - T0) * 1000, 1)
    _write(record)

    sys.stdout.write("{}\n")
    return 0 if record["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
