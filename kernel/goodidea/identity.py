from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .errors import ValidationError


TRACKING_KEYS = {
    "fbclid",
    "gclid",
    "igshid",
    "share",
    "share_token",
    "spm",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_url(raw: str) -> str:
    parsed = urlsplit(raw.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValidationError("URL must be an absolute HTTP(S) address")
    if parsed.username or parsed.password:
        raise ValidationError("URL credentials are not allowed")
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    port = parsed.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_KEYS:
            continue
        query.append((key, value))
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    return urlunsplit((scheme, netloc, path, urlencode(sorted(query)), ""))


def file_identity(filename: str, content: bytes) -> tuple[str, str]:
    basename = Path(filename).name
    if not basename or basename in {".", ".."}:
        raise ValidationError("filename is required")
    return f"file:{digest(content)}", basename


def text_identity(content: str) -> str:
    normalized = "\n".join(line.rstrip() for line in content.strip().splitlines())
    if not normalized:
        raise ValidationError("external text is empty")
    return f"text:{digest(normalized.encode('utf-8'))}"


def search_units(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", text.casefold())
    units = set(re.findall(r"[a-z0-9_]{2,}", normalized))
    chinese = "".join(re.findall(r"[\u3400-\u9fff]", normalized))
    if len(chinese) == 1:
        units.add(chinese)
    else:
        units.update(chinese[index : index + 2] for index in range(len(chinese) - 1))
    return units
