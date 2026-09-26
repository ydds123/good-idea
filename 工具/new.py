#!/usr/bin/env python3
"""Create an empty Good Idea record from a repository template."""
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPES = {
    "interesting": ("interesting.md", "数据/记录/有意思"),
    "action": ("action.md", "数据/记录/行动"),
    "flash": ("flash.md", "数据/记录/闪念"),
    "permanent": ("permanent-card.md", "数据/记录/永久卡片"),
    "source": ("source.md", "数据/记录/外部来源"),
}


def clean_template(text, title, kind):
    text = text.replace("../../规则/", "../../../规则/")
    text = re.sub(r"^> .*本模板只展示 Markdown 文件形状。\n?", "", text, flags=re.M)
    text = re.sub(r"^# (有意思标题|行动标题|闪念卡片标题|永久卡片标题|外部来源标题)$", f"# {title}", text, flags=re.M)
    text = re.sub(r"\n## 去向\n[\s\S]*$", "\n", text)
    if kind == "original":
        text = re.sub(r"\n### YYYY-MM-DD HH:MM｜松海\n\n消息原文。\n", "\n", text)
        text = re.sub(r"\n### YYYY-MM-DD HH:MM｜Agent\n\n消息原文。\n", "\n", text)
    return text.rstrip() + "\n"


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in TYPES or not sys.argv[2].strip():
        print("用法：python3 工具/new.py <interesting|action|flash|permanent|source> <标题>", file=sys.stderr)
        return 2
    kind, title = sys.argv[1], sys.argv[2].strip()
    template, directory = TYPES[kind]
    target_dir = ROOT / directory
    target_dir.mkdir(parents=True, exist_ok=True)
    date = dt.date.today().isoformat()
    base = target_dir / f"{date}-{title}.md"
    target = base
    suffix = 2
    while target.exists():
        target = target_dir / f"{date}-{title}-{suffix}.md"
        suffix += 1
    source = ROOT / "数据" / "模板" / template
    target.write_text(clean_template(source.read_text(encoding="utf-8"), title, kind), encoding="utf-8")
    print(target.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
