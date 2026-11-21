"""The Outlook browser sign-in listener, driven over a real localhost socket."""

from __future__ import annotations

import http.client
import socket
import threading
import unittest
import urllib.parse
from unittest.mock import patch

import support  # noqa: F401  (puts lib/ on sys.path)

import outlook_auth


class BrowserLoginListenerTests(unittest.TestCase):
    def _login(self, visit, timeout: float = 10):
        """Run browser_login; visit(port, state) plays the browser and others."""
        posted: list[dict] = []
        failures: list[BaseException] = []
        visitors: list[threading.Thread] = []

        def fake_open(url: str) -> bool:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            redirect = urllib.parse.urlsplit(query["redirect_uri"][0])
            self.assertEqual(redirect.hostname, "localhost")

            def run() -> None:
                try:
                    visit(redirect.port, query["state"][0])
                except BaseException as exc:  # surfaced after the login returns
                    failures.append(exc)

            visitor = threading.Thread(target=run, daemon=True)
            visitors.append(visitor)
            visitor.start()
            return True

        def fake_post(url: str, data: dict) -> dict:
            posted.append(data)
            return {"refresh_token": "r", "access_token": "a"}

        with patch.object(outlook_auth.webbrowser, "open", side_effect=fake_open), patch.object(
            outlook_auth, "_post", side_effect=fake_post
        ), patch.object(outlook_auth, "LOGIN_TIMEOUT", timeout), patch.object(
            outlook_auth.sys, "stderr"
        ):
            try:
                return outlook_auth.browser_login("client", "consumers"), posted
            finally:
                # The visitor's own checks and statuses count only once it is done.
                for visitor in visitors:
                    visitor.join(timeout=10)
                    self.assertFalse(visitor.is_alive(), "the visitor did not finish")
                for exc in failures:
                    raise exc

    @staticmethod
    def _get(port: int, path: str) -> int:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.read()
            return resp.status
        finally:
            conn.close()

    def test_only_the_matching_state_ends_the_wait(self) -> None:
        statuses: list[int] = []

        def visit(port: int, state: str) -> None:
            # Another local program: none of these may end or decide sign-in.
            for path in (
                "/?code=planted&state=wrong",
                "/?code=planted",
                "/?error=access_denied&error_description=Forged",
                "/?error=access_denied&state=",
                f"/elsewhere?code=planted&state={state}",
                f"/?state={state}",
                "/favicon.ico",
            ):
                statuses.append(self._get(port, path))
            statuses.append(self._get(port, f"/?code=real&state={state}"))

        token, posted = self._login(visit)
        self.assertEqual(statuses, [400] * 7 + [200])
        self.assertEqual(token["refresh_token"], "r")
        self.assertEqual([p["code"] for p in posted], ["real"])

    def test_a_silent_connection_does_not_hold_the_listener(self) -> None:
        held: list[socket.socket] = []

        def visit(port: int, state: str) -> None:
            # Connects and never sends a request line.
            held.append(socket.create_connection(("127.0.0.1", port), timeout=5))
            self.assertEqual(self._get(port, f"/?code=real&state={state}"), 200)

        try:
            token, posted = self._login(visit)
        finally:
            for sock in held:
                sock.close()
        self.assertEqual([p["code"] for p in posted], ["real"])

    def test_forged_requests_alone_time_out_without_their_error(self) -> None:
        def visit(port: int, state: str) -> None:
            self.assertEqual(self._get(port, "/?error=x&error_description=Forged+message"), 400)

        with self.assertRaises(RuntimeError) as caught:
            self._login(visit, timeout=1)
        self.assertEqual(str(caught.exception), "Outlook sign-in timed out or was cancelled")

    def test_a_cancel_from_microsoft_with_the_state_ends_sign_in(self) -> None:
        def visit(port: int, state: str) -> None:
            path = f"/?error=access_denied&error_description=The+user+cancelled&state={state}"
            self.assertEqual(self._get(port, path), 400)

        with self.assertRaises(RuntimeError) as caught:
            self._login(visit)
        self.assertEqual(str(caught.exception), "The user cancelled")

    def test_the_listener_owns_its_port_from_the_start(self) -> None:
        # No port is picked, released and bound again for another program to take.
        self.assertFalse(hasattr(outlook_auth, "_free_port"))
        server = outlook_auth._CallbackServer("s")
        try:
            host, port = server.server_address[:2]
            self.assertEqual(host, "127.0.0.1")
            self.assertGreater(port, 0)
        finally:
            server.server_close()
        self.assertEqual(outlook_auth._CallbackHandler.timeout, outlook_auth.CONNECTION_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
