#!/usr/bin/env python3
"""Create a dated Markdown record from a repository template."""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DESTINATIONS = {
    "interesting": ROOT / "数据/记录/有意思",
    "action": ROOT / "数据/记录/行动",
    "flash": ROOT / "数据/记录/闪念",
    "permanent": ROOT / "数据/记录/永久卡片",
    "source": ROOT / "数据/记录/外部来源",
}
TEMPLATES = {**{kind: kind for kind in DESTINATIONS}, "permanent": "permanent-card"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("type", choices=sorted(DESTINATIONS))
    parser.add_argument("title")
    return parser.parse_args()


def safe_title(title: str) -> str:
    cleaned = " ".join(title.split())
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise ValueError("标题不能为空，且不能包含路径分隔符")
    return cleaned


def next_path(directory: Path, stem: str) -> Path:
    candidate = directory / f"{stem}.md"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{index}.md"
        index += 1
    return candidate


def clean_template(text: str, kind: str) -> str:
    lines = [line for line in text.splitlines() if not line.startswith("> ")]
    text = "\n".join(lines).strip() + "\n"
    text = text.replace("../../规则/", "../../../规则/")
    if kind == "original-thought":
        start = text.index("## 对话")
        text = text[:start] + "## 对话\n"
        return text
    removals = {
        "interesting": ["保存的内容。", "只有松海实际表达过时才填写；没有则删除本节，不由 Agent 补写。", "只有已经发生真实处理结果时才填写，并附对应文档链接；没有则删除本节。"],
        "action": ["写清松海已经决定推进或完成的一件事。", "实际存在且执行需要的信息；没有则删除本节。"],
        "flash": ["松海认领的闪念正文。可以模糊、不完整，也可以只是一个问题、异常或连接。", "记录当时为什么会注意到它，以及未来从哪里可以继续思考。需要时链接到 `原始思考记录/` 中的完整现场。", "只有存在实际材料、原始思考记录或其他形成依据时才填写；没有则删除本节。", "实际去向及对应文档链接；当前没有去向时删除本节。"],
        "permanent": ["能够脱离原对话独立理解的阶段性判断。", "让这项判断成立所必需的理由。", "只有确实影响适用范围时才填写；没有则删除本节。", "用自然语言说明这项卡片为什么形成，并在原因中附上对应文档链接。不单独列出关联文件、独立 ID 或机械依赖。", "只有修订过程确实有助于理解判断如何变化时才填写；没有则删除本节。"],
        "source": ["实际内容……"],
    }
    for value in removals.get(kind, []):
        text = text.replace(value, "")
    text = re.sub(r"\n## 去向\n\s*$", "\n", text)
    text = re.sub(r"\n## (执行信息|材料与论证锚点|边界或不确定性|形成依据|演化记录)\n\s*(?=## |\Z)", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def main() -> int:
    args = parse_args()
    title = safe_title(args.title)
    template = ROOT / "数据/模板" / f"{TEMPLATES[args.type]}.md"
    directory = DESTINATIONS[args.type]
    if not template.is_file():
        raise SystemExit(f"模板不存在：{template}")
    directory.mkdir(parents=True, exist_ok=True)
    target = next_path(directory, f"{date.today().isoformat()}-{title}")
    target.write_text(clean_template(template.read_text(encoding="utf-8"), args.type), encoding="utf-8")
    print(target.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        raise SystemExit(f"错误：{error}")
