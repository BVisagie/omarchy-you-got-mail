from __future__ import annotations

import base64
import unittest

import mime_text as mime


def b64(text: str, charset: str = "utf-8") -> str:
    return base64.urlsafe_b64encode(text.encode(charset)).decode("ascii")


def part(mime_type: str, data: str, charset: str = "utf-8", disposition: str = "") -> dict:
    headers = [{"name": "Content-Type", "value": f"{mime_type}; charset={charset}"}]
    if disposition:
        headers.append({"name": "Content-Disposition", "value": disposition})
    return {"mimeType": mime_type, "headers": headers, "body": {"data": data}}


def message(parts: list[dict], headers: list[dict] | None = None) -> dict:
    return {
        "id": "abc",
        "threadId": "thread-1",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": headers or [],
            "parts": parts,
        },
    }


class Base64UrlTests(unittest.TestCase):
    def test_decodes_padded_urlsafe_alphabet(self) -> None:
        encoded = base64.urlsafe_b64encode(b"\xfb\xff").decode("ascii")
        self.assertIn("-", encoded)
        self.assertEqual(mime.decode_base64url(encoded), b"\xfb\xff")

    def test_decodes_unpadded(self) -> None:
        self.assertEqual(mime.decode_base64url(b64("hello").rstrip("=")), b"hello")

    def test_ignores_whitespace(self) -> None:
        raw = b64("hello")
        self.assertEqual(mime.decode_base64url(raw[:4] + "\n" + raw[4:]), b"hello")

    def test_garbage_is_empty_not_an_error(self) -> None:
        self.assertEqual(mime.decode_base64url("!!!!"), b"")


class HtmlToTextTests(unittest.TestCase):
    def test_removes_script_style_and_head(self) -> None:
        text = mime.html_to_text(
            "<head><style>p{color:red}</style><title>hidden</title></head>"
            "<body><p>Keep</p><script>alert(1)</script></body>"
        )
        self.assertEqual(text, "Keep")
        self.assertNotIn("hidden", text)
        self.assertNotIn("alert", text)

    def test_block_tags_and_break_become_newlines(self) -> None:
        self.assertEqual(mime.html_to_text("<p>one</p><p>two</p>"), "one\n\ntwo")
        self.assertEqual(mime.html_to_text("one<br>two"), "one\ntwo")

    def test_entities_are_decoded(self) -> None:
        self.assertEqual(
            mime.html_to_text("Tom &amp; Jerry &lt;3 &#39;hi&#39;&nbsp;there"),
            "Tom & Jerry <3 'hi' there",
        )

    def test_images_leave_no_content(self) -> None:
        self.assertEqual(mime.html_to_text('<img src="https://x/y.png" alt="pixel">'), "")

    def test_whitespace_is_collapsed(self) -> None:
        self.assertEqual(mime.html_to_text("<p>a   b</p>\n\n\n\n<p>c</p>"), "a b\n\nc")


class HeaderTests(unittest.TestCase):
    def test_rfc2047_subject(self) -> None:
        self.assertEqual(mime.decode_header_value("=?UTF-8?B?SGVsbG8=?="), "Hello")

    def test_rfc2047_non_utf8_charset(self) -> None:
        raw = "=?ISO-8859-1?Q?Ol=E1?="
        self.assertEqual(mime.decode_header_value(raw), "Olá")

    def test_plain_header_collapses_whitespace(self) -> None:
        self.assertEqual(mime.decode_header_value("Ada\n  Lovelace"), "Ada Lovelace")


class MessageToTextTests(unittest.TestCase):
    def test_prefers_plain_over_html(self) -> None:
        result = mime.message_to_text(
            message(
                [
                    part("text/html", b64("<p>html body</p>")),
                    part("text/plain", b64("plain body")),
                ]
            )
        )
        self.assertEqual(result["text"], "plain body")

    def test_falls_back_to_html(self) -> None:
        result = mime.message_to_text(
            message([part("text/html", b64("<p>Hi<br>there</p>"))])
        )
        self.assertEqual(result["text"], "Hi\nthere")

    def test_attachment_plain_is_skipped_for_html_body(self) -> None:
        result = mime.message_to_text(
            message(
                [
                    part("text/plain", b64("attached text"), disposition="attachment; filename=a.txt"),
                    part("text/html", b64("<p>body</p>")),
                ]
            )
        )
        self.assertEqual(result["text"], "body")

    def test_non_utf8_charset(self) -> None:
        result = mime.message_to_text(
            message([part("text/plain", b64("Olá", "iso-8859-1"), charset="iso-8859-1")])
        )
        self.assertEqual(result["text"], "Olá")

    def test_headers_are_decoded(self) -> None:
        result = mime.message_to_text(
            message(
                [part("text/plain", b64("body"))],
                headers=[
                    {"name": "Subject", "value": "=?UTF-8?B?SGVsbG8=?="},
                    {"name": "From", "value": "Ada <ada@example.test>"},
                    {"name": "To", "value": "you@example.test"},
                    {"name": "Date", "value": "Tue, 1 Jan 2030 00:00:00 +0000"},
                ],
            )
        )
        self.assertEqual(result["subject"], "Hello")
        self.assertEqual(result["from"], "Ada <ada@example.test>")
        self.assertEqual(result["to"], "you@example.test")
        self.assertEqual(result["date"], "Tue, 1 Jan 2030 00:00:00 +0000")
        self.assertEqual(result["threadId"], "thread-1")

    def test_truncates_large_bodies(self) -> None:
        big = "x" * (mime.MAX_TEXT_CHARS + 10)
        result = mime.message_to_text(message([part("text/plain", b64(big))]))
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["text"]), mime.MAX_TEXT_CHARS)

    def test_no_readable_part_is_ok_and_empty(self) -> None:
        result = mime.message_to_text(message([part("application/pdf", b64("nope"))]))
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "")
        self.assertFalse(result["truncated"])

    def test_missing_payload_is_ok_and_empty(self) -> None:
        result = mime.message_to_text({"id": "abc"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "")


if __name__ == "__main__":
    unittest.main()
