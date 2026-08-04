from __future__ import annotations

import html as html_module
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any


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
) -> dict[str, Any]:
    images = [
        {"alt": alt or "图片", "url": image_url, "referer": url}
        for alt, image_url in re.findall(
            r"!\[([^\]]*)\]\((https?://[^)]+)\)", markdown
        )
    ]
    content = markdown.strip()
    return {
        "url": url,
        "canonical_url": canonicalize_url(url),
        "title": title.strip() or canonicalize_url(url),
        "author": author.strip(),
        "published_at": published_at.strip(),
        "markdown": content,
        "images": images,
        "status": "complete" if content else "failed",
        "error": "" if content else "未提供正文",
        "extractor": "agent-markdown",
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
