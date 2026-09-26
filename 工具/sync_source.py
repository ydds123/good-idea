#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""得到大脑（Get笔记）材料 → Goodidea 外部来源：一次调用完成取料、落盘、资产入库、去重、可选提交。

用法:
  sync_source.py list   [--limit 20] [--since YYYY-MM-DD] [--root DIR] [--json]
  sync_source.py sync   <note_id|链接> [更多...] [--tag 名称]... [--update] [--commit] [--dry-run] [--json]
  sync_source.py merge  <note_id> [更多...] [--tag 名称]... [--update] [--commit] [--dry-run] [--json]
  sync_source.py weekly [--since YYYY-MM-DD] [--scan-only] [--no-merge] [--tag 名称]... [--update] [--commit] [--dry-run] [--json]
                        [--keyword 炒饭会] [--weekday 2] [--min-hour 17] [--min-minutes 20] [--exclude-type 工作会议]
  sync_source.py tags-health [--root DIR] [--json]  # 标签体检：使用次数 / 树外标签 / 闲置节点 / 清单结构自检

weekly 默认把「同一晚的多段录音」合并成一份记录（--no-merge 可关）。
weekly 的识别阈值（关键词、星期、起始小时、最短时长、排除内容类型）取 规则/标签清单.json 的「炒饭会」节点 识别参数，命令行参数可临时覆盖。

规则边界（脚本不定义规则，只执行）:
  格式与语义：规则/内容对象.md#外部来源
  取料/去重/写入顺序：规则/协作协议.md#统一来源登记协议
"""

import argparse
import hashlib
import html as htmllib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]   # 仓库根：随脚本所在位置解析
GETNOTE = os.environ.get("GETNOTE_BIN", "getnote")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

SERIES_AUTHORS = [("炒饭会", "永道缔生")]
KNOWN_SECTIONS = [
    "智能总结", "章节概要", "金句精选", "关键洞察", "待办事项",
    "写作提纲", "核心结论", "行动建议", "术语解释", "逐字稿", "节目简介", "页面正文",
]
TS_PATTERNS = [
    re.compile(r'^\[\d{1,2}:\d{2}(?::\d{2})?\s*-\s*[\d:]{4,8}\]'),
    re.compile(r'^[🟢🟣🟠🟡⚪️🔵]\s*说话人\s*\d*\s*\['),
    re.compile(r'^\*{0,2}说话人\s*\d+'),
]
IMG_RE = re.compile(r'!\[[^\]]*\]\((https?://[^)\s]+)\)')
APP_LINK_RE = re.compile(r'\[([^\]]+)\]\(https://getnotes\.seek:[^)\s]*\)')
SRC_RE = re.compile(r'^source:\s*"?(?P<v>[^"\n]+?)"?\s*$', re.M)
TAGS_RE = re.compile(r'^tags:\s*\[(?P<v>[^\]]*)\]', re.M)
NAME_MAP = {'/': '／', ':': '：', '*': '＊', '?': '？', '"': '”', '<': '＜', '>': '＞', '|': '｜', '\\': '＼'}

# weekly 识别阈值不写在本脚本里：唯一来源是 规则/标签清单.json 的「炒饭会」节点 识别参数
PARAM_FIELDS = [("keyword", "关键词"), ("weekday", "星期"), ("min_hour", "起始小时"),
                ("min_minutes", "最短时长分钟"), ("exclude_type", "排除内容类型")]


def recognition_params(root):
    """读 规则/标签清单.json → (识别参数, 问题说明)。脚本不内置阈值。"""
    path = root / "规则" / "标签清单.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, f"读不到 {path}：{exc}"
    for axis in data.get("相关线") or []:
        for tag in axis.get("标签") or []:
            if tag.get("名称") == "炒饭会":
                params = tag.get("识别参数")
                if isinstance(params, dict):
                    return params, ""
                return {}, "「炒饭会」节点缺少 识别参数"
    return {}, "标签清单里没有「炒饭会」节点"


# ---------- 基础工具 ----------

def warn(report, msg):
    report.setdefault("warnings", []).append(msg)


def sh(cmd, timeout=300):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"命令失败 {p.returncode}: {' '.join(map(str, cmd))} :: {(p.stderr or '').strip()[:300]}")
    return p.stdout


def cli_json(args):
    return json.loads(sh([GETNOTE] + list(args) + ["-o", "json"]), strict=False)


def load_note(nid):
    d = cli_json(["note", str(nid)])
    data = d.get("data")
    n = data.get("note") if isinstance(data, dict) and isinstance(data.get("note"), dict) else data
    if not isinstance(n, dict) or not n.get("id"):
        raise RuntimeError(f"取不到笔记 {nid}")
    return n


def fetch_text(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


# ---------- 材料解析 ----------

def note_facts(note):
    """可比较的客观事实：时长、内容类型、参与人数、录音结束时间。"""
    c = note.get("content") or ""
    wp = note.get("web_page") if isinstance(note.get("web_page"), dict) else {}
    out = {"minutes": None, "content_type": "", "people": "", "ended_at": "", "started_at": ""}
    m = re.search(r'时长\*{0,2}[：:]\s*约?\s*([^\n]+)', c) or \
        re.search(r'内容总时长[：:]\s*([^\n]+)', wp.get("content") or "")
    if m:
        mm = re.search(r'(?:(\d+)\s*小时)?\s*(\d+)\s*分', m.group(1))
        if mm:
            out["minutes"] = int(mm.group(1) or 0) * 60 + int(mm.group(2))
    t = re.search(r'\*\*内容类型\*\*[：:]\s*([^\n]+)', c)
    if t:
        out["content_type"] = t.group(1).strip()
    p = re.search(r'\*\*参与人数\*\*[：:]\s*([^\n]+)', c)
    if p:
        out["people"] = p.group(1).strip()
    r = re.search(r'\*\*录音时间\*\*[：:]\s*[\d\-: ]+?\s*~\s*([\d\-: ]+)', c)
    if r:
        out["ended_at"] = r.group(1).strip()
    r0 = re.search(r'\*\*录音时间\*\*[：:]\s*([\d\-: ]{10,20}?)\s*~', c)
    if r0:
        out["started_at"] = r0.group(1).strip()
    return out


def note_source(note):
    atts = [a for a in (note.get("attachments") or []) if isinstance(a, dict)]
    link_atts = [a for a in atts if a.get("type") == "link" and a.get("url")]
    wp = note.get("web_page") if isinstance(note.get("web_page"), dict) else {}
    page_url = (link_atts[0]["url"] if link_atts else "") or (wp.get("url") or "")
    return {"atts": atts, "link_atts": link_atts, "wp": wp, "page_url": page_url,
            "source": page_url or f"https://biji.com/note/{note['id']}"}


def page_meta(page_url, report):
    out = {}
    try:
        doc = fetch_text(page_url)
    except Exception as e:
        warn(report, f"页面元数据获取失败（字段将省略）：{type(e).__name__} {page_url[:80]}")
        return out
    m = re.search(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', doc, re.S)
    if m:
        try:
            data = json.loads(m.group(1).strip())
            item = data[0] if isinstance(data, list) and data else data
            if isinstance(item, dict):
                if item.get("name"):
                    out["title"] = str(item["name"]).strip()
                if item.get("datePublished"):
                    out["published_at"] = str(item["datePublished"])[:10]
                au = item.get("author")
                if isinstance(au, dict) and au.get("name"):
                    out["author"] = str(au["name"]).strip()
                elif isinstance(au, list) and au and isinstance(au[0], dict) and au[0].get("name"):
                    out["author"] = str(au[0]["name"]).strip()
        except Exception:
            pass
    t = re.search(r'<title[^>]*>(.*?)</title>', doc, re.S)
    if t:
        pt = htmllib.unescape(re.sub(r'\s+', ' ', t.group(1))).strip()
        out["page_title"] = pt
        m2 = re.match(r'^.*?\s-\s(?P<show>[^|]{1,40}?)\s*\|\s*小宇宙', pt)
        if m2:
            out["show"] = m2.group("show").strip()
    return out


def is_ts_line(line):
    s = line.strip()
    return any(p.match(s) for p in TS_PATTERNS)


def split_original(text):
    """把「转写 + 页面正文」拆成两段：最后一个时间戳行之后是页面正文。"""
    lines = (text or "").split("\n")
    last = None
    for i, l in enumerate(lines):
        if is_ts_line(l):
            last = i
    if last is None:
        return (text or "").strip(), ""
    return "\n".join(lines[:last + 1]).strip(), "\n".join(lines[last + 1:]).strip()


def strip_app_links(text):
    """去掉材料自带的应用跳转链接（getnotes.seek），保留时间戳文本。"""
    return APP_LINK_RE.sub(r'**\1**', text or "")


def normalize_summary(md):
    out = []
    for line in (md or "").split("\n"):
        s = line.rstrip()
        m = re.match(r'^#{1,4}\s+(.+)$', s)
        if m and re.sub(r'[^\u4e00-\u9fff]', '', m.group(1)) in KNOWN_SECTIONS:
            s = "## " + re.sub(r'[^\u4e00-\u9fff]', '', m.group(1))
        out.append(s)
    return "\n".join(out).strip()


def guess_ext(url, data):
    m = re.search(r'\.(jpe?g|png|gif|webp|bmp)(?:[?#]|$)', url, re.I)
    if m:
        return "." + m.group(1).lower().replace("jpeg", "jpg")
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".bin"


def localize_images(text, root, report, dry_run):
    def repl(m):
        url = m.group(1)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
        except Exception as e:
            warn(report, f"图片下载失败，保留远程链接：{url[:90]} ({type(e).__name__})")
            return m.group(0)
        name = hashlib.sha256(data).hexdigest() + guess_ext(url, data)
        path = root / "数据" / "assets" / name
        is_new = not path.exists()
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            if is_new:
                path.write_bytes(data)
        report.setdefault("images", []).append(
            {"asset": f"数据/assets/{name}", "bytes": len(data), "new": is_new, "src": url[:110]})
        return f"![]({'../../assets/' + name})"

    return IMG_RE.sub(repl, text)


def derive_author(note, meta, page_body, explicit, tags=()):
    if explicit:
        return explicit
    series = " ".join([note.get("title") or ""] + [str(t) for t in (tags or [])])
    for pat, author in SERIES_AUTHORS:
        if pat in series:
            return author
    host = re.search(r'【本期主播】[\s\S]{0,40}?\n\s*([^\s：:（）()【】]{1,20})\s*[：:]', page_body or "")
    guest = re.search(r'【本期嘉宾】[\s\S]{0,40}?\n\s*([^\s：:（）()【】]{1,20})\s*[：:]', page_body or "")
    show = meta.get("show")
    h, g = (host.group(1) if host else ""), (guest.group(1) if guest else "")
    if show and h and g:
        return f"《{show}》｜{h} × {g}"
    if show and h:
        return f"《{show}》｜{h}"
    if show and g:
        return f"《{show}》｜{g}"
    if show:
        return f"《{show}》"
    return meta.get("author") or ""


def yaml_str(v):
    return '"' + str(v).replace('\\', '\\\\').replace('"', '\\"') + '"'


def safe_title(title):
    t = "".join(NAME_MAP.get(ch, ch) for ch in (title or "").strip())
    t = re.sub(r'[\n\r\t]+', ' ', t).strip()
    return (t[:90] or "未命名").rstrip('.')


# ---------- 去重 ----------

_TREE_CACHE = {}
_MANIFEST_PROBLEMS = {}
_RETIRED_CACHE = {}


def norm_url(u):
    u = (u or "").strip()
    u = re.sub(r'^https?://', '', u)
    u = re.sub(r'[?#].*$', '', u)
    u = re.sub(r'^www\.', '', u)
    return u.rstrip('/').lower()


def load_registry(root):
    reg = {}
    d = root / "数据" / "记录" / "外部来源"
    if not d.is_dir():
        return reg
    for f in sorted(d.glob("*.md")):
        try:
            head = f.read_text(encoding="utf-8")[:1500]
        except Exception:
            continue
        m = SRC_RE.search(head)
        if m:
            reg[norm_url(m.group("v"))] = f.name
        for m2 in re.findall(r'biji\.com/note/(\d{6,})', head):
            reg["note:" + m2] = f.name
        h1 = re.search(r'^#\s+(.+)$', head, re.M)
        if h1:
            reg["title:" + norm_title(h1.group(1))] = f.name
    return reg


def norm_title(t):
    return re.sub(r'\s+', '', (t or "").strip())


def _manifest(root):
    """读 规则/标签清单.json → (全部标签名, 退场表, 结构问题)。"""
    key = str(root)
    if key not in _TREE_CACHE:
        names, retired, problems = [], {}, []
        try:
            data = json.loads((root / "规则" / "标签清单.json").read_text(encoding="utf-8"))
            seen = set()
            for line in data.get("相关线", []):
                for tag in line.get("标签", []):
                    name = (tag.get("名称") or "").strip()
                    if not name:
                        problems.append(f"{line.get('线名') or '某条线'}有一个标签缺「名称」")
                        continue
                    if name in seen:
                        problems.append(f"标签名重复：{name}")
                    seen.add(name)
                    names.append(name)
                    st = tag.get("状态") or "在用"
                    if st in ("停用", "已并入"):
                        retired[name] = f"{st}｜{tag.get('备注') or tag.get('判据') or ''}"
            for name in names:
                if "/" in name and name.split("/", 1)[0] not in seen:
                    problems.append(f"子标签 {name} 的父级不在清单里（子标签要从一级长起）")
        except Exception as e:
            problems.append(f"读不到 规则/标签清单.json（{type(e).__name__}）")
        _TREE_CACHE[key], _RETIRED_CACHE[key], _MANIFEST_PROBLEMS[key] = names, retired, problems
    return _TREE_CACHE[key], _RETIRED_CACHE[key], _MANIFEST_PROBLEMS.get(key, [])


def tree_nodes(root):
    """规则/标签清单.json 里的标签名（取值唯一来源）。"""
    return _manifest(root)[0]


def retired_nodes(root):
    """清单里状态为「停用」或「已并入」的标签 → {标签: 说明}。"""
    return _manifest(root)[1]


def manifest_problems(root):
    """清单自身的结构问题（缺名称／重名／子标签缺父级／文件读不到）。"""
    return _manifest(root)[2]


def registered_as(reg, source, nid):
    return reg.get(norm_url(source)) or reg.get("note:" + str(nid))


def read_tags(path):
    try:
        head = path.read_text(encoding="utf-8")[:1000]
    except Exception:
        return []
    m = TAGS_RE.search(head)
    if not m:
        return []
    return [s.strip().strip('"\'') for s in m.group("v").split(",") if s.strip()]


# ---------- 组装 ----------

def build_document(note, opts, report, info=None, tags=(), existing_tags=()):
    info = info or note_source(note)
    link_atts, wp, page_url, source = info["link_atts"], info["wp"], info["page_url"], info["source"]
    self_link = "biji.com" in page_url
    meta = page_meta(page_url, report) if (page_url and not self_link) else {}

    title = (link_atts[0].get("title") if link_atts else "") or meta.get("title") or note.get("title") or f"笔记 {note['id']}"
    facts = note_facts(note)

    published = meta.get("published_at") or ""
    if not published:
        m = re.search(r'\*\*录音时间\*\*[：:]\s*(\d{4}-\d{2}-\d{2})', note.get("content") or "")
        if m:
            published = m.group(1)

    summary = normalize_summary(note.get("content") or "")
    original = wp.get("content") or ""
    if original:
        transcript, page_body = split_original(original)
        page_section = "节目简介" if "xiaoyuzhou" in page_url else "页面正文"
    else:
        audio = note.get("audio") if isinstance(note.get("audio"), dict) else {}
        transcript, page_body, page_section = (audio.get("original") or "").strip(), "", "页面正文"

    if opts.no_transcript:
        transcript = ""

    tag_list = []
    for t in list(existing_tags) + list(tags):
        if t and t not in tag_list:
            tag_list.append(t)

    author = derive_author(note, meta, page_body, opts.author, tags=tag_list)

    parts = [f"# {title}", summary]
    if transcript:
        parts += ["---", "## 完整逐字稿", transcript]
    if page_body:
        parts += [f"## {page_section}", page_body]
    body = strip_app_links("\n\n".join(p for p in parts if p and p.strip()))
    if not opts.no_images:
        body = localize_images(body, opts.root, report, opts.dry_run)

    fm = []
    if author:
        fm.append(f"author: {yaml_str(author)}")
    if published:
        fm.append(f"published_at: {yaml_str(published)}")
    fm.append(f"source: {yaml_str(source)}")
    if tag_list:
        fm.append("tags: [" + ", ".join(yaml_str(t) for t in tag_list) + "]")
    doc = "---\n" + "\n".join(fm) + "\n---\n\n" + body + "\n"

    report.update({
        "note_id": str(note.get("id")), "note_type": note.get("note_type"), "title": title,
        "source": source, "author": author or None, "published_at": published or None,
        "tags": tag_list, "minutes": facts["minutes"], "content_type": facts["content_type"] or None,
        "summary_chars": len(summary), "transcript_chars": len(transcript),
        "page_body_chars": len(page_body), "doc_chars": len(doc),
    })
    return {"title": title, "source": source, "doc": doc, "published_at": published,
            "author": author, "tags": tag_list}


def demote_headings(text, extra=1):
    """把段内自带的标题整体降级，保证合并记录里层级不打架。"""
    out = []
    for ln in (text or "").splitlines():
        m = re.match(r'^(#{1,5})\s+(.*)$', ln)
        out.append("#" * min(len(m.group(1)) + extra, 6) + " " + m.group(2) if m else ln)
    return "\n".join(out)


def note_title(note, info=None):
    info = info or note_source(note)
    la = info["link_atts"]
    return (la[0].get("title") if la else "") or note.get("title") or f"笔记 {note.get('id')}"


def build_merged_document(infos, opts, report, tags=(), existing_tags=()):
    """一晚多段录音合并成一份记录；主段（时长最长的一段）定标题与 source。"""
    main_note = max(infos, key=lambda t: (t[2].get("minutes") or 0))[0]
    title = safe_title(note_title(main_note))
    night = str(infos[0][2].get("started_at") or infos[0][0].get("created_at") or "")[:10]
    source = note_source(main_note)["source"]

    tag_list = []
    for t in list(existing_tags) + list(tags):
        if t and t not in tag_list:
            tag_list.append(t)
    author = derive_author(main_note, {}, "", opts.author, tags=tag_list)

    rows, sums, trs, total = [], [], [], 0
    for i, (n, info, f) in enumerate(infos, 1):
        t = note_title(n, info).replace("|", "｜")
        mins = f.get("minutes") or 0
        total += mins
        dur = f"{mins} 分钟" if mins else "时长未标注"
        when = str(f.get("started_at") or n.get("created_at") or "")[:16]
        rows.append(f"| {i} | {when} | {dur} | {t} | {info['source']} |")
        summary = normalize_summary(n.get("content") or "")
        if summary:
            sums += [f"### 段 {i}｜{t}（{dur}）", demote_headings(summary)]
        audio = n.get("audio") if isinstance(n.get("audio"), dict) else {}
        tr = (audio.get("original") or "").strip()
        if tr and not opts.no_transcript:
            trs += [f"### 段 {i}｜{t}（{dur}）", demote_headings(tr)]

    lead = (f"> 本条由 {night} 晚 {len(infos)} 段录音合并成一份，合计约 {total} 分钟；"
            f"各段来源见下表，主段是时长最长的一段。")
    table = "\n".join(["| 段 | 开始时间 | 时长 | 标题 | 来源 |", "|---|---|---|---|---|"] + rows)
    parts = [f"# {title}", lead, "## 当晚分段", table]
    if sums:
        parts += ["## 智能笔记", *sums]
    if trs:
        parts += ["---", "## 完整逐字稿", *trs]
    body = strip_app_links("\n\n".join(str(p) for p in parts if str(p).strip()))
    if not opts.no_images:
        body = localize_images(body, opts.root, report, opts.dry_run)

    fm = []
    if author:
        fm.append(f"author: {yaml_str(author)}")
    if night:
        fm.append(f"published_at: {yaml_str(night)}")
    fm.append(f"source: {yaml_str(source)}")
    if tag_list:
        fm.append("tags: [" + ", ".join(yaml_str(t) for t in tag_list) + "]")
    doc = "---\n" + "\n".join(fm) + "\n---\n\n" + body + "\n"

    report.update({
        "note_id": str(main_note.get("id")), "note_type": main_note.get("note_type"), "title": title,
        "note_ids": [str(n.get("id")) for n, _, _ in infos], "night": night, "segments": len(infos),
        "source": source, "author": author or None, "published_at": night or None, "tags": tag_list,
        "minutes": total or None, "content_type": None,
        "summary_chars": sum(len(x) for x in sums), "transcript_chars": sum(len(x) for x in trs),
        "doc_chars": len(doc),
    })
    return {"title": title, "source": source, "doc": doc, "published_at": night,
            "author": author, "tags": tag_list}


def write_record(rec, opts, item, out, existing=False):
    if opts.dry_run:
        tmp = Path(tempfile.mkdtemp(prefix="sync_source_")) / out.name
        tmp.write_text(rec["doc"], encoding="utf-8")
        item.update(status="dry_run", dry_run_path=str(tmp))
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".md.tmp")
    tmp.write_text(rec["doc"], encoding="utf-8")
    tmp.replace(out)
    item.update(status="updated" if existing else "created", file=str(out.relative_to(opts.root)))
    if opts.commit:
        assets = sorted({str(opts.root / i["asset"]) for i in item.get("images", [])})
        item["commit"] = commit(opts.root, [out] + assets, rec["title"])


def target_path(root, day, title):
    d = root / "数据" / "记录" / "外部来源"
    base = f"{day}-{safe_title(title)}"
    p = d / f"{base}.md"
    i = 2
    while p.exists():
        p = d / f"{base}-{i}.md"
        i += 1
    return p


# ---------- git ----------

def commit(root, paths, title):
    rel = [str(Path(p).relative_to(root)) if Path(p).is_absolute() else str(p) for p in paths]
    sh(["git", "-C", str(root), "add", "--"] + rel)
    q = subprocess.run(["git", "-C", str(root), "diff", "--cached", "--quiet", "--"] + rel)
    if q.returncode == 0:
        return {"committed": False, "reason": "无变化"}
    sh(["git", "-C", str(root), "commit", "-q", "-m", f"feat: 登记外部来源（{title}）"])
    return {"committed": True,
            "hash": sh(["git", "-C", str(root), "log", "-1", "--format=%h %s"]).strip()}


# ---------- 单篇同步 ----------

def sync_one(target, opts, reg, item=None):
    item = item if item is not None else {"target": str(target)}
    t0 = time.time()
    try:
        m = re.search(r'(\d{6,})', str(target))
        if not m:
            raise RuntimeError("目标里找不到笔记 id")
        nid = m.group(1)
        item["note_id"] = nid
        note = load_note(nid)
        info = note_source(note)
        used = registered_as(reg, info["source"], nid)
        if not used:
            guess = (info["link_atts"][0].get("title") if info["link_atts"] else "") or note.get("title") or ""
            dup = reg.get("title:" + norm_title(guess))
            if dup:
                item.update(status="exists_title", file=f"数据/记录/外部来源/{dup}",
                            hint="标题与既有记录相同，疑似同一材料，未重复登记；确认后可手工合并")
                item["elapsed_s"] = round(time.time() - t0, 1)
                return item
        if used and not opts.update:
            item.update(status="exists", file=f"数据/记录/外部来源/{used}",
                        hint="已登记，跳过；要补全内容加 --update")
            item["elapsed_s"] = round(time.time() - t0, 1)
            return item
        existing_tags = read_tags(opts.root / "数据" / "记录" / "外部来源" / used) if (used and opts.update) else []
        rec = build_document(note, opts, item, info=info, tags=opts.tags, existing_tags=existing_tags)
        out = (opts.root / "数据" / "记录" / "外部来源" / used) if (opts.update and used) \
            else target_path(opts.root, opts.date, rec["title"])
        write_record(rec, opts, item, out, existing=bool(used))
    except Exception as e:
        item.update(status="error", error=f"{type(e).__name__}: {e}")
    item["elapsed_s"] = round(time.time() - t0, 1)
    return item


def check_tags(opts, report):
    if not opts.tags:
        return
    nodes = tree_nodes(opts.root)
    unknown = [t for t in opts.tags if t not in nodes]
    if unknown:
        warn(report, f"标签不在 规则/标签清单.json 中：{unknown}；按规则应先新增节点再引用（见 规则/标签树.md「新增与维护」）")
    gone = [t for t in opts.tags if t in retired_nodes(opts.root)]
    if gone:
        warn(report, f"标签已停用或已并入：{gone}——新登记不要再用（见 规则/标签清单.json 与 规则/标签树.md「停用、合并与退场」）")


def cmd_tags(opts):
    """标签体检（flomo 式）：看每个标签用了多少次、有没有树外标签、节点有没有闲置。"""
    t0 = time.time()
    d = opts.root / "数据" / "记录" / "外部来源"
    nodes = tree_nodes(opts.root)
    counts, per = {}, []
    for f in sorted(d.glob("*.md")):
        ts = read_tags(f)
        per.append({"file": f.name, "tags": ts})
        for t in ts:
            counts[t] = counts.get(t, 0) + 1
    unknown = sorted(t for t in counts if t not in nodes)
    report = {"mode": opts.mode, "records": len(per), "nodes": nodes, "counts": counts,
              "retired": retired_nodes(opts.root), "problems": manifest_problems(opts.root),
              "untracked": unknown, "unused_nodes": [n for n in nodes if n not in counts],
              "items": per, "warnings": ([f"树外标签：{unknown}；按 规则/标签清单.json 应先新增节点"] if unknown else []),
              "elapsed_s": round(time.time() - t0, 1)}
    return report


def merge_one(note_ids, opts, reg, item=None):
    """把一晚的多段录音合并成一份记录（主段＝时长最长的一段）。"""
    item = item if item is not None else {"target": ",".join(str(i) for i in note_ids)}
    t0 = time.time()
    try:
        infos = []
        for i in note_ids:
            n = load_note(str(i))
            infos.append((n, note_source(n), note_facts(n)))
        infos.sort(key=lambda t: str(t[2].get("started_at") or t[0].get("created_at") or ""))
        main_note = max(infos, key=lambda t: (t[2].get("minutes") or 0))[0]
        used = ""
        for n, info, f in infos:
            used = registered_as(reg, info["source"], n.get("id")) or ""
            if used:
                break
        item.update(note_ids=[str(n.get("id")) for n, _, _ in infos], segments=len(infos),
                    night=str(infos[0][2].get("started_at") or infos[0][0].get("created_at") or "")[:10])
        if not used:
            dup = reg.get("title:" + norm_title(note_title(main_note)))
            if dup:
                item.update(status="exists_title", file=f"数据/记录/外部来源/{dup}",
                            hint="主段标题与既有记录相同，疑似同一材料，未重复登记；确认后可手工合并")
                item["elapsed_s"] = round(time.time() - t0, 1)
                return item
        if used and not opts.update:
            item.update(status="exists", file=f"数据/记录/外部来源/{used}",
                        hint="当晚已登记，跳过；要补全加 --update")
            item["elapsed_s"] = round(time.time() - t0, 1)
            return item
        existing_tags = read_tags(opts.root / "数据" / "记录" / "外部来源" / used) if (used and opts.update) else []
        rec = build_merged_document(infos, opts, item, tags=opts.tags, existing_tags=existing_tags)
        out = (opts.root / "数据" / "记录" / "外部来源" / used) if (opts.update and used) \
            else target_path(opts.root, opts.date, rec["title"])
        write_record(rec, opts, item, out, existing=bool(used))
    except Exception as e:
        item.update(status="error", error=f"{type(e).__name__}: {e}")
    item["elapsed_s"] = round(time.time() - t0, 1)
    return item


def night_groups(rows, opts):
    """按「周三这一晚」分组录音（含 <min_minutes 的短片段）；只保留至少有一段够长的当晚。"""
    g = {}
    for r in rows:
        if r.get("is_link"):
            continue
        try:
            d = datetime.fromisoformat(str(r.get("started_at") or r.get("created_at")).replace(" ", "T"))
        except Exception:
            continue
        if d.weekday() != opts.weekday or d.hour < opts.min_hour:
            continue
        if opts.exclude_type and opts.exclude_type in (r.get("content_type") or ""):
            continue
        g.setdefault(str(r.get("started_at") or r.get("created_at"))[:10], []).append(r)
    return {k: sorted(v, key=lambda x: str(x.get("started_at") or "")) for k, v in g.items()
            if any((x.get("minutes") is None or x["minutes"] >= opts.min_minutes) for x in v)}


def cmd_merge(targets, opts):
    t0 = time.time()
    report = {"mode": "merge", "items": []}
    check_tags(opts, report)
    reg = load_registry(opts.root)
    ids = []
    for t in targets:
        m = re.search(r'(\d{6,})', str(t))
        if m:
            ids.append(m.group(1))
        else:
            report["items"].append({"target": str(t), "status": "error", "error": "目标里找不到笔记 id"})
    if not ids:
        report["items"].append({"target": "", "status": "error", "error": "没有可用的笔记 id"})
    else:
        report["items"].append(merge_one(ids, opts, reg, {"target": ",".join(ids)}))
    report["elapsed_s"] = round(time.time() - t0, 1)
    return report


def cmd_sync(args, opts):
    t0 = time.time()
    report = {"mode": "sync", "items": []}
    check_tags(opts, report)
    reg = load_registry(opts.root)
    for target in args:
        report["items"].append(sync_one(target, opts, reg))
    report["elapsed_s"] = round(time.time() - t0, 1)
    return report


# ---------- 扫描与每周例行 ----------

def scan_notes(opts, since):
    reg = load_registry(opts.root)
    notes, cursor = [], None
    while len(notes) < opts.scan_max:
        args = ["notes", "--limit", "20"]
        if cursor:
            args += ["--since-id", str(cursor)]
        d = cli_json(args)
        data = d.get("data") if isinstance(d.get("data"), dict) else {}
        batch = data.get("notes") or []
        if not batch:
            break
        notes += batch
        cursor = batch[-1].get("id")
        if len(batch) < 20:
            break
    rows = []
    for n in notes:
        nid = str(n.get("id"))
        created = str(n.get("created_at") or "")
        if since and created[:10] < since:
            break
        atts = [a for a in (n.get("attachments") or []) if isinstance(a, dict) and a.get("type") == "link"]
        title = atts[0].get("title") if atts else n.get("title")
        src = atts[0]["url"] if atts else f"https://biji.com/note/{nid}"
        resolved = bool(atts)
        facts = note_facts(n)
        if not atts and (n.get("note_type") or "") == "link":
            try:
                det = load_note(nid)
                datt = [a for a in (det.get("attachments") or []) if isinstance(a, dict) and a.get("type") == "link"]
                if datt:
                    src = datt[0]["url"]
                    title = datt[0].get("title") or title
                    resolved = True
                dfacts = note_facts(det)
                if dfacts["minutes"]:
                    facts.update(dfacts)
            except Exception:
                pass
        hay = f"{title or ''}\n{n.get('content') or ''}"
        _nt = (n.get("note_type") or "")
        _created = created or ""
        rows.append({
            "note_id": nid, "created_at": created, "note_type": n.get("note_type"),
            "title": title, "source": src, "source_resolved": resolved,
            "minutes": facts["minutes"], "content_type": facts["content_type"] or None,
            "ended_at": facts["ended_at"] or None,
            "started_at": facts.get("started_at") or _created, "is_link": _nt == "link",
            "keyword_hits": len(re.findall(re.escape(opts.keyword), hay)) if opts.keyword else 0,
            "registered": registered_as(reg, src, nid),
        })
    return rows


def classify(row, opts):
    """判据（可调默认，权威见 规则/默认规则.md）：自己录的音 + 周三 min-hour 点后开始 + 时长下限 + 非工作会议。"""
    if not row.get("is_link"):
        try:
            d = datetime.fromisoformat(str(row.get("started_at") or row.get("created_at")).replace(" ", "T"))
        except Exception:
            d = None
        if d and d.weekday() == opts.weekday and d.hour >= opts.min_hour \
                and opts.exclude_type not in (row.get("content_type") or "") \
                and (row.get("minutes") is None or row["minutes"] >= opts.min_minutes):
            why = f"{'一二三四五六日'[d.weekday()]} {d:%H:%M} 开始的录音"
            if row.get("minutes"):
                why += f"，{row['minutes']} 分钟"
            why += (f"，正文出现「{opts.keyword}」{row['keyword_hits']} 处" if row.get("keyword_hits")
                    else f"，正文没有「{opts.keyword}」字样")
            return "auto", why
    if row.get("keyword_hits"):
        return "suspect", f"出现「{opts.keyword}」{row['keyword_hits']} 处，但不是周三 {opts.min_hour} 点后开始的自己录音"
    return "skip", ""


def cmd_weekly(opts):
    t0 = time.time()
    since = opts.since or (date.today() - timedelta(days=1)).isoformat()
    rows = scan_notes(opts, since)
    report = {"mode": "weekly", "since": since, "scanned": len(rows),
              "recordings": sum(1 for r in rows if not r.get("is_link")),
              "filters": {"keyword": opts.keyword, "weekday": opts.weekday, "min_hour": opts.min_hour,
                          "min_minutes": opts.min_minutes, "exclude_type": opts.exclude_type,
                          "tag": opts.tags},
              "auto": [], "suspect": [], "skipped": [], "items": []}
    auto_rows = []
    for r in rows:
        kind, why = classify(r, opts)
        r["match"], r["why"] = kind, why
        if kind == "auto":
            report["auto"].append(r)
            auto_rows.append(r)
        elif kind == "suspect" and not r["registered"]:
            report["suspect"].append(r)
        elif kind == "suspect":
            report["skipped"].append({"note_id": r["note_id"], "title": r["title"],
                                      "minutes": r["minutes"], "content_type": r["content_type"],
                                      "why": "疑似但已登记"})
        else:
            report["skipped"].append({"note_id": r["note_id"], "title": r["title"],
                                      "minutes": r["minutes"], "content_type": r["content_type"],
                                      "started_at": r.get("started_at"), "note_type": r["note_type"]})
    if not opts.scan_only:
        check_tags(opts, report)
        reg = load_registry(opts.root)
        if opts.merge:
            groups = night_groups(rows, opts)
            report["nights"] = {k: [x["note_id"] for x in v] for k, v in groups.items()}
            for night in sorted(groups):
                ids = [r["note_id"] for r in groups[night]]
                report["items"].append(merge_one(ids, opts, reg, {"target": night}))
        else:
            for r in auto_rows:
                report["items"].append(sync_one(r["note_id"], opts, reg))
    report["elapsed_s"] = round(time.time() - t0, 1)
    return report


# ---------- 输出 ----------

def print_report(report, opts):
    for w in report.get("warnings", []):
        print(f"! {w}")
    mode = report.get("mode")
    if mode == "list":
        for it in report["items"]:
            state = f"已登记：{it['registered']}" if it["registered"] else "未登记"
            print(f"{it['created_at'][:16]} | {str(it['note_type']):<10} | {state} | "
                  f"{it.get('minutes') or '-'} min | {it.get('content_type') or '-'} | {str(it['title'])[:50]}")
    elif mode == "sync":
        for it in report["items"]:
            print(f"[{it.get('status')}] {it.get('title') or it.get('target')} → "
                  f"{it.get('file') or it.get('dry_run_path') or ''}")
            for w in it.get("warnings", []):
                print(f"    ! {w}")
    elif mode in ("tags", "tags-health"):
        print(f"外部来源 {report['records']} 份；标签清单节点 {len(report['nodes'])} 个"
              + (f"（{', '.join(report['nodes'])}）" if report["nodes"] else "（空）"))
        if not report["counts"]:
            print("  还没有任何记录带标签")
        for t, c in sorted(report["counts"].items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {c:>3} 次  {t}" + ("" if t in report["nodes"] else "   ← 不在标签清单"))
        for pr in report.get("problems", []):
            print(f"  ! 清单问题：{pr}")
        if report.get("retired"):
            print(f"  已停用/已并入：{report['retired']}")
        if report["unused_nodes"]:
            print(f"  树内暂无材料的节点：{report['unused_nodes']}")
    elif mode == "merge":
        for it in report["items"]:
            head = it.get("title") or it.get("target") or ""
            if it.get("segments"):
                head += f"（{it['segments']} 段，{it.get('minutes') or '-'} 分钟，{it.get('night')}）"
            print(f"[{it.get('status')}] {head} → {it.get('file') or it.get('dry_run_path') or ''}")
            for w in it.get("warnings", []):
                print(f"    ! {w}")
    elif mode == "weekly":
        nights = report.get("nights")
        print(f"窗口 since {report['since']}：扫描 {report['scanned']} 条；"
              f"自动 {len(report['auto'])}、疑似 {len(report['suspect'])}、跳过 {len(report['skipped'])}"
              + (f"；合并后 {len(nights)} 晚" if nights else ""))
        for it in report["items"]:
            print(f"[{it.get('status')}] {it.get('title')} [{it.get('minutes')} min, "
                  f"{it.get('content_type')}] → {it.get('file') or it.get('dry_run_path') or ''}")
        for s in report["suspect"]:
            print(f"[疑似] {s['title']} ({s['minutes']} min, {s['content_type']}) — {s['why']}")
    print(f"耗时 {report.get('elapsed_s')}s", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="得到大脑材料 → Goodidea 外部来源")
    ap.add_argument("mode", choices=["sync", "list", "weekly", "tags-health", "merge", "tags"],
                    help="tags 是 tags-health 的同义词")
    ap.add_argument("targets", nargs="*", help="sync: note_id 或含 id 的链接（可多个）")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--since", default="")
    ap.add_argument("--scan-max", type=int, default=200, help="weekly/list 最多往前看多少条笔记")
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    ap.add_argument("--author", default="")
    ap.add_argument("--tag", action="append", default=[], dest="tags",
                    help="写入 frontmatter 标签，可重复")
    ap.add_argument("--keyword", default=None, help="weekly 识别关键词；默认取 规则/标签清单.json")
    ap.add_argument("--weekday", type=int, default=None, help="0=周一 … 2=周三；默认取 规则/标签清单.json")
    ap.add_argument("--min-hour", type=int, default=None, help="起始小时；默认取 规则/标签清单.json")
    ap.add_argument("--min-minutes", type=int, default=None, help="最短时长（分钟）；默认取 规则/标签清单.json")
    ap.add_argument("--exclude-type", default=None, help="排除的内容类型；默认取 规则/标签清单.json")
    ap.add_argument("--merge", dest="merge", action="store_true", default=True,
                    help="weekly：把同一晚的多段录音合并成一份（默认开）")
    ap.add_argument("--no-merge", dest="merge", action="store_false",
                    help="weekly：不合并，每段各登记一份")
    ap.add_argument("--scan-only", action="store_true")
    ap.add_argument("--no-transcript", action="store_true")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--json", action="store_true")
    opts = ap.parse_args()
    opts.root = Path(opts.root).expanduser()
    params, problem = recognition_params(opts.root)
    for name, label in PARAM_FIELDS:
        if getattr(opts, name) is None:
            value = params.get(label)
            if value is None and opts.mode == "weekly":
                ap.error(f"识别参数缺失：请在 规则/标签清单.json 的「炒饭会」节点补 识别参数.{label}（{problem or '未列出'}）")
            setattr(opts, name, value)
    if opts.mode == "sync" and not opts.targets:
        ap.error("sync 需要至少一个 note_id")
    if opts.mode == "sync":
        report = cmd_sync(opts.targets, opts)
    elif opts.mode == "merge":
        report = cmd_merge(opts.targets, opts)
    elif opts.mode in ("tags", "tags-health"):
        report = cmd_tags(opts)
    elif opts.mode == "list":
        rows = scan_notes(opts, opts.since)
        report = {"mode": "list", "root": str(opts.root), "count": min(len(rows), opts.limit),
                  "items": rows[:opts.limit]}
    else:
        report = cmd_weekly(opts)
    if opts.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report, opts)


if __name__ == "__main__":
    main()
