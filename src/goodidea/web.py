from __future__ import annotations

import base64
import hashlib
import html as html_module
import json
import mimetypes
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .errors import ValidationError


TRACKING_PARAMS = {
    "from",
    "from_copylink",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "spm",
    "share_token",
}
WECHAT_IDENTITY_PARAMS = {"__biz", "mid", "idx", "sn"}
LOCAL_SOURCE_EXTENSIONS = {".md", ".markdown", ".txt"}
_FRONTMATTER_FIELDS = {
    "title",
    "author",
    "published",
    "published_at",
    "date",
    "source",
    "canonical_url",
}
_MARKDOWN_IMAGE_RE = re.compile(
    r"!\[([^\]]*)\]\(\s*(?:<([^>]+)>|([^\s)]+))"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
_BINARY_MAGIC_PREFIXES = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"PK\x03\x04",
    b"%PDF-",
    b"\x1f\x8b",
    b"\x7fELF",
)


def canonicalize_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    host = (parsed.hostname or "").lower()
    if not parsed.scheme or not host:
        return url.strip()
    port = parsed.port
    netloc = host
    if port and not (
        (parsed.scheme == "http" and port == 80)
        or (parsed.scheme == "https" and port == 443)
    ):
        netloc += f":{port}"
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if host == "mp.weixin.qq.com":
        query_pairs = [pair for pair in query_pairs if pair[0] in WECHAT_IDENTITY_PARAMS]
    else:
        query_pairs = [
            pair
            for pair in query_pairs
            if pair[0].lower() not in TRACKING_PARAMS
            and not pair[0].lower().startswith("utm_")
        ]
    query = urllib.parse.urlencode(sorted(query_pairs))
    path = parsed.path or "/"
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), netloc, path, query, "")
    )


def _frontmatter_scalar(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.startswith('"') and value.endswith('"'):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
        return str(decoded) if decoded is not None else ""
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def _strip_frontmatter(markdown: str) -> tuple[str, dict[str, str]]:
    """Remove a leading YAML block and read only the small metadata allowlist."""

    normalized = markdown.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return normalized, {}
    closing_index = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() in {"---", "..."}
        ),
        None,
    )
    if closing_index is None:
        return normalized, {}
    metadata: dict[str, str] = {}
    for line in lines[1:closing_index]:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", line.rstrip("\n"))
        if not match:
            continue
        key = match.group(1).lower()
        if key in _FRONTMATTER_FIELDS and key not in metadata:
            metadata[key] = _frontmatter_scalar(match.group(2))
    return "".join(lines[closing_index + 1 :]), metadata


_TITLE_QUOTE_TRANS = str.maketrans({ch: "" for ch in "\"'“”‘’「」『』＂"})


def _title_key(text: str) -> str:
    """标题比较键：折叠空白并忽略成对引号类排版标点。

    仅用于“开头一级标题是否与最终来源标题重复”的机械判断。引号是排版
    标点、不改变标题语义：最终标题与原文 H1 只差引号时仍视为重复并移除，
    避免在正式来源标题下重复显示同一标题。
    """
    return " ".join(text.translate(_TITLE_QUOTE_TRANS).split())


def _heading_title(markdown: str) -> str:
    match = re.match(r"^\s*#\s+(.+?)(?:\s+#+)?\s*(?:\n|$)", markdown)
    return " ".join(match.group(1).split()) if match else ""


def _strip_matching_leading_h1(markdown: str, title: str) -> str:
    if not title:
        return markdown
    match = re.match(r"^(\s*)#\s+(.+?)(?:\s+#+)?\s*(?:\n|$)", markdown)
    if not match:
        return markdown
    heading = _title_key(match.group(2))
    if heading != _title_key(title):
        return markdown
    return markdown[match.end() :]


def _normalize_markdown_document(
    markdown: str,
    *,
    title: str = "",
    infer_title_from_h1: bool = False,
) -> tuple[str, dict[str, str], str]:
    content, metadata = _strip_frontmatter(markdown)
    effective_title = title.strip() or metadata.get("title", "").strip()
    if infer_title_from_h1 and not effective_title:
        effective_title = _heading_title(content)
    content = _strip_matching_leading_h1(content, effective_title)
    content = content.strip()
    return content, metadata, effective_title


def _is_binary_text(text: str) -> bool:
    if "\x00" in text:
        return True
    if not text:
        return False
    control_count = sum(
        1 for char in text if ord(char) < 32 and char not in "\t\n\r"
    )
    return control_count / len(text) > 0.02


def _is_binary_bytes(data: bytes) -> bool:
    return b"\x00" in data[:8192] or any(
        data.startswith(prefix) for prefix in _BINARY_MAGIC_PREFIXES
    )


def _local_image_records(
    markdown: str,
    *,
    source_directory: Path,
    remote_referer: str = "",
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    source_root = source_directory.resolve()
    for match in _MARKDOWN_IMAGE_RE.finditer(markdown):
        alt = match.group(1).strip() or "图片"
        image_url = (match.group(2) or match.group(3) or "").strip()
        if not image_url or image_url in seen:
            continue
        seen.add(image_url)
        parsed = urllib.parse.urlsplit(image_url)
        if parsed.scheme in {"http", "https"}:
            records.append(
                {"alt": alt, "url": image_url, "referer": remote_referer}
            )
            continue
        if parsed.scheme or image_url.startswith(("/", "~")):
            raise ValidationError(
                f"本地图片必须使用来源目录内的相对路径：{image_url}"
            )
        relative_path = Path(urllib.parse.unquote(parsed.path))
        resolved = (source_root / relative_path).resolve()
        if not resolved.is_relative_to(source_root):
            raise ValidationError(
                f"本地图片越出来源文件所在目录树：{image_url}"
            )
        if not resolved.exists():
            raise ValidationError(f"本地图片不存在：{image_url}")
        if not resolved.is_file():
            raise ValidationError(f"本地图片不是普通文件：{image_url}")
        try:
            data = resolved.read_bytes()
        except OSError as exc:
            detail = exc.strerror or exc.__class__.__name__
            raise ValidationError(
                f"无法读取本地图片 {image_url}：{detail}"
            ) from exc
        if not data:
            raise ValidationError(f"本地图片内容为空：{image_url}")
        content_type = (
            mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        )
        records.append(
            {
                "alt": alt,
                "url": image_url,
                "content_type": content_type,
                "data_base64": base64.b64encode(data).decode("ascii"),
            }
        )
    return records


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() == "meta":
            key = (
                values.get("property")
                or values.get("name")
                or values.get("itemprop")
            ).lower()
            content = values.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self._title_parts).split())


class _MarkdownParser(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "form"}
    SKIP_TOKENS = {
        "nav",
        "navigation",
        "header",
        "footer",
        "sidebar",
        "comment",
        "comments",
        "advert",
        "advertisement",
        "recommend",
        "share",
        "toolbar",
    }
    BLOCK_TAGS = {
        "p",
        "div",
        "section",
        "article",
        "main",
        "li",
        "ul",
        "ol",
        "blockquote",
        "pre",
        "table",
        "tr",
    }

    def __init__(self, base_url: str, target: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.target = target
        self.depth = 0
        self.target_depth: int | None = None
        self.skip_depth: int | None = None
        self.parts: list[str] = []
        self.images: list[dict[str, str]] = []
        self.links: list[tuple[str, int]] = []

    @property
    def active(self) -> bool:
        return self.target_depth is not None and self.skip_depth is None

    def _matches_target(self, tag: str, values: dict[str, str]) -> bool:
        if self.target == "wechat":
            return values.get("id") == "js_content"
        if self.target == "article":
            return tag == "article"
        if self.target == "main":
            return tag == "main"
        return tag == "body"

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()
        self.depth += 1
        values = {key.lower(): (value or "") for key, value in attrs}
        if self.target_depth is None and self._matches_target(tag, values):
            self.target_depth = self.depth
        if not self.active:
            return
        tokens = " ".join(
            [values.get("id", ""), values.get("class", "")]
        ).lower()
        if tag in self.SKIP_TAGS or any(token in tokens for token in self.SKIP_TOKENS):
            self.skip_depth = self.depth
            return
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n\n")
        if tag == "br":
            self.parts.append("\n")
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.parts.append("- ")
        elif tag == "blockquote":
            self.parts.append("> ")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "code":
            self.parts.append(chr(96))
        elif tag == "a":
            href = urllib.parse.urljoin(self.base_url, values.get("href", ""))
            self.links.append((href, len(self.parts)))
            self.parts.append("[")
        elif tag == "img":
            src = (
                values.get("data-src")
                or values.get("data-original")
                or values.get("src")
                or ""
            )
            src = urllib.parse.urljoin(self.base_url, src)
            alt = values.get("alt", "").strip() or "图片"
            if src.startswith(("http://", "https://")):
                self.parts.append(f"\n\n![{alt}]({src})\n\n")
                self.images.append({"url": src, "alt": alt})

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip_depth == self.depth:
            self.skip_depth = None
        elif self.active:
            if tag in {"strong", "b"}:
                self.parts.append("**")
            elif tag in {"em", "i"}:
                self.parts.append("*")
            elif tag == "code":
                self.parts.append(chr(96))
            elif tag == "a" and self.links:
                href, _ = self.links.pop()
                self.parts.append(f"]({href})" if href else "]")
            elif tag in self.BLOCK_TAGS or tag.startswith("h"):
                self.parts.append("\n\n")
        if self.target_depth == self.depth:
            self.target_depth = None
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data: str) -> None:
        if not self.active:
            return
        text = html_module.unescape(data)
        text = re.sub(r"[ \t\f\v]+", " ", text)
        if text.strip():
            self.parts.append(text)

    def markdown(self) -> str:
        value = "".join(self.parts)
        value = re.sub(r" *\n *", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        value = re.sub(r" {2,}", " ", value)
        return value.strip()


def preview_from_html(url: str, html: str) -> dict[str, Any]:
    meta_parser = _MetadataParser()
    meta_parser.feed(html)
    lower = html.lower()
    if re.search(r'id\s*=\s*["\']js_content["\']', lower):
        target = "wechat"
    elif re.search(r"<article(?:\s|>)", lower):
        target = "article"
    elif re.search(r"<main(?:\s|>)", lower):
        target = "main"
    else:
        target = "body"
    parser = _MarkdownParser(url, target)
    parser.feed(html)
    markdown = parser.markdown()
    title = (
        meta_parser.meta.get("og:title")
        or meta_parser.meta.get("twitter:title")
        or meta_parser.title
        or canonicalize_url(url)
    )
    author = (
        meta_parser.meta.get("author")
        or meta_parser.meta.get("article:author")
        or meta_parser.meta.get("og:article:author")
        or ""
    )
    published_at = (
        meta_parser.meta.get("article:published_time")
        or meta_parser.meta.get("date")
        or meta_parser.meta.get("datepublished")
        or ""
    )
    status = "complete"
    error = ""
    lowered_markdown = markdown.lower()
    suspicious = (
        "环境异常" in markdown
        or "访问过于频繁" in markdown
        or "请登录后" in markdown
        or "登录后查看" in markdown
        or "captcha" in lowered_markdown
        or "verify" in lowered_markdown
        or "sign in to continue" in lowered_markdown
        or "log in to continue" in lowered_markdown
    )
    if not markdown:
        status, error = "failed", "未提取到正文"
    elif len(markdown) < 200 or suspicious:
        status, error = "partial", "正文可能不完整或页面要求验证"
    return {
        "url": url,
        "canonical_url": canonicalize_url(url),
        "title": " ".join(title.split()),
        "author": " ".join(author.split()),
        "published_at": published_at.strip(),
        "markdown": markdown,
        "images": [
            {**image, "referer": url}
            for image in parser.images
        ],
        "status": status,
        "error": error,
        "extractor": f"stdlib-html:{target}",
    }


def preview_from_markdown(
    url: str,
    markdown: str,
    *,
    title: str = "",
    author: str = "",
    published_at: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    content, metadata, extracted_title = _normalize_markdown_document(
        markdown,
        title=title,
    )
    images = [
        {"alt": alt or "图片", "url": image_url, "referer": url}
        for alt, image_url in re.findall(
            r"!\[([^\]]*)\]\((https?://[^)]+)\)", content
        )
    ]
    effective_title = extracted_title or canonicalize_url(url)
    effective_author = author.strip() or metadata.get("author", "").strip()
    effective_published_at = (
        published_at.strip()
        or metadata.get("published_at", "").strip()
        or metadata.get("published", "").strip()
        or metadata.get("date", "").strip()
    )
    return {
        "url": url,
        "canonical_url": canonicalize_url(url),
        "title": effective_title,
        "author": effective_author,
        "published_at": effective_published_at,
        "markdown": content,
        "images": images,
        "status": "complete" if content else "failed",
        "error": "" if content else "未提供正文",
        "extractor": "agent-markdown",
        "tags": list(tags or []),
    }


def preview_from_local_file(
    path: str | Path,
    *,
    title: str = "",
    author: str = "",
    published_at: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    source_path = Path(path).expanduser()
    filename = source_path.name
    if not source_path.exists():
        raise ValidationError(f"本地来源文件不存在：{filename or path}")
    if not source_path.is_file():
        raise ValidationError(f"本地来源必须是普通文件：{filename or path}")
    suffix = source_path.suffix.lower()
    if suffix not in LOCAL_SOURCE_EXTENSIONS:
        supported = ", ".join(sorted(LOCAL_SOURCE_EXTENSIONS))
        raise ValidationError(f"不支持的本地来源扩展名 {suffix or '(无)'}；仅支持 {supported}")
    try:
        raw = source_path.read_bytes()
    except OSError as exc:
        detail = exc.strerror or exc.__class__.__name__
        raise ValidationError(f"无法读取本地来源 {filename}：{detail}") from exc
    if _is_binary_bytes(raw):
        raise ValidationError(f"本地来源疑似二进制文件：{filename}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"本地来源不是有效的 UTF-8 文本：{filename}") from exc
    if _is_binary_text(text):
        raise ValidationError(f"本地来源疑似二进制文件：{filename}")

    content, metadata, extracted_title = _normalize_markdown_document(
        text,
        title=title,
        infer_title_from_h1=True,
    )
    effective_title = extracted_title or source_path.stem
    effective_author = author.strip() or metadata.get("author", "").strip()
    effective_published_at = (
        published_at.strip()
        or metadata.get("published_at", "").strip()
        or metadata.get("published", "").strip()
        or metadata.get("date", "").strip()
    )
    declared_referer = (
        metadata.get("canonical_url", "").strip()
        or metadata.get("source", "").strip()
    )
    images = _local_image_records(
        content,
        source_directory=source_path.parent,
        remote_referer=(
            declared_referer
            if declared_referer.startswith(("http://", "https://"))
            else ""
        ),
    )
    return {
        "origin_filename": filename,
        "origin_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "title": " ".join(effective_title.split()),
        "author": effective_author,
        "published_at": effective_published_at,
        "markdown": content,
        "images": images,
        "status": "complete" if content else "failed",
        "error": "" if content else "未提供正文",
        "extractor": (
            "local-markdown"
            if suffix in {".md", ".markdown"}
            else "local-text"
        ),
        "tags": list(tags or []),
    }


def preview_from_url(url: str, timeout: float = 20.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36 GoodIdea/0.1"
            ),
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            raw = response.read(12 * 1024 * 1024)
            charset = response.headers.get_content_charset() or "utf-8"
            final_url = response.geturl()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            return {
                "url": url,
                "canonical_url": canonicalize_url(final_url),
                "title": canonicalize_url(final_url),
                "author": "",
                "published_at": "",
                "markdown": "",
                "images": [],
                "status": "failed",
                "error": f"v0.1 仅支持 HTML 网页，收到 {content_type}",
                "extractor": "stdlib-url",
            }
        return preview_from_html(final_url, raw.decode(charset, errors="replace"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {
            "url": url,
            "canonical_url": canonicalize_url(url),
            "title": canonicalize_url(url),
            "author": "",
            "published_at": "",
            "markdown": "",
            "images": [],
            "status": "failed",
            "error": str(exc),
            "extractor": "stdlib-url",
        }
