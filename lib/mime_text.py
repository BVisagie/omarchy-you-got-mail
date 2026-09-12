#!/usr/bin/env python3
"""Turn a Gmail API message payload into plain text for the panel.

The panel only ever draws plain text (see Panel.qml), so decoding lives
here and never in QML: walk the MIME tree, prefer the first text/plain
leaf, fall back to text/html stripped to text, decode RFC 2047 headers,
and cap the result.

Nothing here fetches remote content, executes markup, or writes to disk.
Read on demand only.

As a script it reads one Gmail ``users.messages.get`` JSON object on
stdin and prints one JSON object with ``subject``, ``from``, ``to``,
``date``, ``text``, ``truncated``, and ``threadId``.
"""

from __future__ import annotations

import base64
import binascii
import email.errors
import email.header
import html as html_module
import json
import re
import sys

MAX_TEXT_CHARS = 256 * 1024

_BLOCK = re.compile(
    r"(?is)<\s*(?:br\s*/?|/?p|/?div|/?tr|/?li|/?h[1-6]|/?table|/?thead"
    r"|/?tbody|/?blockquote|/?pre|/?section|/?article|/?header|/?footer"
    r"|/?ul|/?ol|/?dl|/?dd|/?dt|/?hr)\b[^>]*>"
)
_TAG = re.compile(r"(?s)<[^>]*>")
_COMMENT = re.compile(r"(?s)<!--.*?-->")
_CONTAINER = re.compile(r"(?is)<(script|style|head|title|noscript|template)\b.*?</\1\s*>")
_CHARSET = re.compile(r"""charset\s*=\s*["']?([A-Za-z0-9._:+-]+)""", re.I)
_WS = re.compile(r"[ \t\f\v]+")
_LINE_WS = re.compile(r" *\n *")
_MANY_NL = re.compile(r"\n{3,}")
_HEADER_WS = re.compile(r"\s+")


def collapse(value: str) -> str:
    """Squash a header to one line, the way the list rows are squashed."""
    return _HEADER_WS.sub(" ", value or "").strip()


def decode_base64url(data: object) -> bytes:
    """Decode Gmail's leaf ``body.data`` (URL-safe alphabet, padded)."""
    if data is None:
        return b""
    if isinstance(data, str):
        data = data.encode("ascii", "ignore")
    if not isinstance(data, (bytes, bytearray)):
        return b""
    data = bytes(data).translate(bytes.maketrans(b"-_", b"+/"))
    data = re.sub(rb"\s+", b"", data)
    if not data:
        return b""
    pad = (-len(data)) % 4
    try:
        return base64.b64decode(data + b"=" * pad, validate=False)
    except (binascii.Error, ValueError):
        return b""


def decode_bytes(raw: bytes, charset: str) -> str:
    try:
        return raw.decode(charset or "utf-8", errors="replace")
    except (LookupError, UnicodeError):
        return raw.decode("utf-8", errors="replace")


def decode_header_value(raw: str) -> str:
    """Decode RFC 2047 encoded words, then collapse to one line."""
    if not raw:
        return ""
    try:
        chunks = email.header.decode_header(raw)
    except (email.errors.HeaderParseError, ValueError):
        return collapse(raw)
    out: list[str] = []
    for chunk, charset in chunks:
        if isinstance(chunk, bytes):
            out.append(decode_bytes(chunk, charset or "utf-8"))
        else:
            out.append(chunk)
    return collapse("".join(out))


def charset_from_content_type(value: str) -> str:
    match = _CHARSET.search(value or "")
    return match.group(1) if match else "utf-8"


def html_to_text(raw: str) -> str:
    """Strip HTML to text without fetching or rendering anything."""
    text = _COMMENT.sub("", raw or "")
    text = _CONTAINER.sub("", text)
    text = _BLOCK.sub("\n", text)
    text = _TAG.sub("", text)
    text = html_module.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = _WS.sub(" ", text)
    text = _LINE_WS.sub("\n", text)
    text = _MANY_NL.sub("\n\n", text)
    return text.strip()


def _header_map(headers: object) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(headers, list):
        return out
    for item in headers:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        if name:
            out[name] = str(item.get("value") or "")
    return out


def _find_part(payload: object) -> tuple[str, str, str] | None:
    """Return (mime, base64url-data, charset) for the best leaf."""
    plain: tuple[str, str, str] | None = None
    html: tuple[str, str, str] | None = None

    def walk(part: object) -> None:
        nonlocal plain, html
        if not isinstance(part, dict):
            return
        headers = _header_map(part.get("headers"))
        mime = str(part.get("mimeType") or "").strip().lower()
        disposition = headers.get("content-disposition", "").strip().lower()
        body = part.get("body") if isinstance(part.get("body"), dict) else {}
        data = body.get("data") if isinstance(body, dict) else None
        children = part.get("parts")
        if isinstance(children, list) and children:
            for child in children:
                walk(child)
            return
        if not data or disposition.startswith("attachment"):
            return
        charset = charset_from_content_type(headers.get("content-type", ""))
        if mime == "text/plain" and plain is None:
            plain = (mime, str(data), charset)
        elif mime == "text/html" and html is None:
            html = (mime, str(data), charset)

    walk(payload)
    return plain or html


def message_to_text(message: dict) -> dict:
    """Normalise a Gmail ``format=full`` message into panel-ready text."""
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    headers = _header_map(payload.get("headers"))
    result: dict = {
        "ok": True,
        "subject": decode_header_value(headers.get("subject", "")),
        "from": decode_header_value(headers.get("from", "")),
        "to": decode_header_value(headers.get("to", "")),
        "date": collapse(headers.get("date", "")),
        "text": "",
        "truncated": False,
        "threadId": str(message.get("threadId") or message.get("id") or ""),
    }
    part = _find_part(payload)
    if part is None:
        return result
    mime, data, charset = part
    raw = decode_base64url(data)
    if not raw:
        return result
    decoded = decode_bytes(raw, charset)
    if mime == "text/html":
        text = html_to_text(decoded)
    else:
        text = decoded.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        result["truncated"] = True
    result["text"] = text
    return result


def _read_message() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    for candidate in (raw, raw.splitlines()[-1] if raw.splitlines() else raw):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def main() -> int:
    try:
        result = message_to_text(_read_message())
    except Exception:  # noqa: BLE001 - never leak parser soup to the panel
        result = {"ok": False, "error": "could not read this message"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
