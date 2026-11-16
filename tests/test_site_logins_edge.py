"""Login automático no Edge/Chrome (DevTools Protocol) e o perfil por criança."""

import base64
import json
import os
import socket
import socketserver
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import site_logins  # noqa: E402
from application_launcher import (  # noqa: E402
    ensure_chromium_preferences,
    CHROMIUM_BLOCKED_HOSTS,
    chromium_host_resolver_rules,
    external_browser_command,
    external_chromium_profile,
)


class EdgeCommandTest(unittest.TestCase):
    def test_each_child_has_its_own_profile_and_default_keeps_the_old_one(self):
        with tempfile.TemporaryDirectory() as root:
            base = os.path.join(root, "external-chromium-profile")
            self.assertEqual(external_chromium_profile(root, "default"), base)
            self.assertEqual(external_chromium_profile(root, ""), base)
            self.assertEqual(external_chromium_profile(root, "child-1"), base + "-child-1")
            # o id vira nome de pasta: nada de "..", barras ou espaços
            self.assertEqual(external_chromium_profile(root, "../a b/c"), base + "-abc")
            self.assertEqual(external_chromium_profile(root, "/"), base)

    def test_edge_command_per_child_without_remote_control(self):
        with tempfile.TemporaryDirectory() as root:
            command = external_browser_command(
                "msedge.exe",
                "https://kiddogames.fun/", root, profile_id="child-1",
            )
            profile = os.path.join(root, "external-chromium-profile-child-1")
            self.assertIn(f"--user-data-dir={profile}", command)
            self.assertEqual(command[-2:], ["--kiosk", "--app=https://kiddogames.fun/"])
            self.assertFalse(any(arg.startswith("--remote-debugging") for arg in command))

    def test_devtools_only_when_asked_and_only_local(self):
        with tempfile.TemporaryDirectory() as root:
            command = external_browser_command(
                "msedge.exe", "https://www.teachyourmonster.org/account/play", root,
                profile_id="default", devtools_port=site_logins.DEVTOOLS_PORT,
            )
            self.assertIn(f"--remote-debugging-port={site_logins.DEVTOOLS_PORT}", command)
            self.assertIn("--remote-debugging-address=127.0.0.1", command)
            self.assertEqual(command[-1], "--app=https://www.teachyourmonster.org/account/play")
            # a porta do Marionette não liga nada no Edge
            plain = external_browser_command("msedge.exe", "https://x.org/", root, marionette_port=28290)
            self.assertFalse(any("remote-debugging" in arg or "marionette" in arg for arg in plain))

    def test_edge_blocks_ad_hosts_without_touching_localhost(self):
        with tempfile.TemporaryDirectory() as root:
            for kwargs in ({}, {"devtools_port": 28291}):
                command = external_browser_command("msedge.exe", "https://x.org/", root, **kwargs)
                rules = [a for a in command if a.startswith("--host-resolver-rules=")]
                self.assertEqual(rules, [f"--host-resolver-rules={chromium_host_resolver_rules()}"])
            firefox = external_browser_command("firefox", "https://x.org/", root)
            self.assertFalse(any("host-resolver" in arg for arg in firefox))
        value = chromium_host_resolver_rules()
        parts = value.split(", ")
        for host in ("googlesyndication.com", "doubleclick.net", "adservice.google.com", "bestschoolgames.com"):
            self.assertIn(host, CHROMIUM_BLOCKED_HOSTS)
            self.assertIn(f"MAP {host} 0.0.0.0", parts)
            self.assertIn(f"MAP *.{host} 0.0.0.0", parts)
        self.assertEqual(parts[-1], "EXCLUDE localhost")
        self.assertEqual(len(parts), 2 * len(CHROMIUM_BLOCKED_HOSTS) + 1)
        # o Escola Games e os sites dos tiles não podem cair na lista
        for host in CHROMIUM_BLOCKED_HOSTS:
            self.assertEqual(host, host.strip().lower())
            self.assertNotIn(" ", host)
            for allowed in ("escolagames.com.br", "khanacademy.org", "teachyourmonster.org", "127.0.0.1"):
                self.assertFalse(allowed == host or allowed.endswith("." + host), (allowed, host))

    def test_edge_command_turns_translation_off(self):
        with tempfile.TemporaryDirectory() as root:
            for profile_id in ("default", "child-1"):
                command = external_browser_command("msedge.exe", "https://x.org/", root, profile_id=profile_id)
                self.assertEqual([a for a in command if a.startswith("--disable-features")],
                                 ["--disable-features=Translate"])
                prefs = Path(external_chromium_profile(root, profile_id)) / "Default" / "Preferences"
                self.assertEqual(json.loads(prefs.read_text()), {"translate": {"enabled": False}})
            # o Firefox não ganha nada disso
            firefox = external_browser_command("firefox", "https://x.org/", root)
            self.assertFalse(any("disable-features" in arg for arg in firefox))

    def test_firefox_ignores_devtools_port(self):
        with tempfile.TemporaryDirectory() as root:
            command = external_browser_command("firefox", "https://x.org/", root, devtools_port=28291)
            self.assertEqual(command[-2:], ["--kiosk", "https://x.org/"])
            self.assertNotIn("--marionette", command)


class EdgePreferencesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.profile = Path(self.tmp.name) / "external-chromium-profile-child-1"
        self.prefs = self.profile / "Default" / "Preferences"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data):
        self.prefs.parent.mkdir(parents=True, exist_ok=True)
        self.prefs.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")

    def test_new_profile_gets_only_the_minimum(self):
        self.assertTrue(ensure_chromium_preferences(self.profile))
        self.assertEqual(json.loads(self.prefs.read_text()), {"translate": {"enabled": False}})
        self.assertEqual(os.listdir(self.prefs.parent), ["Preferences"])  # sem arquivo temporário

    def test_merge_keeps_every_other_key(self):
        original = {
            "profile": {"name": "Pessoa 1", "exit_type": "Crashed"},
            "translate": {"enabled": True, "other": "fica"},
            "translate_blocked_languages": ["pt"],
            "intl": {"accept_languages": "pt-BR,pt"},
            "emoji": "🎈",
        }
        self.write(original)
        self.assertTrue(ensure_chromium_preferences(self.profile))
        data = json.loads(self.prefs.read_text(encoding="utf-8"))
        expected = json.loads(json.dumps(original))
        expected["translate"]["enabled"] = False
        self.assertEqual(data, expected)

    def test_already_off_is_not_rewritten(self):
        self.write({"translate": {"enabled": False}, "x": 1})
        before = self.prefs.stat().st_mtime_ns
        self.assertFalse(ensure_chromium_preferences(self.profile))
        self.assertEqual(self.prefs.stat().st_mtime_ns, before)

    def test_translate_not_a_dict_is_replaced(self):
        self.write({"translate": "estranho", "x": 1})
        self.assertTrue(ensure_chromium_preferences(self.profile))
        self.assertEqual(json.loads(self.prefs.read_text()), {"translate": {"enabled": False}, "x": 1})

    def test_broken_file_is_left_alone(self):
        for broken in ('{"translate": {"enabled": tr', "[1, 2]"):
            self.write(broken)
            self.assertFalse(ensure_chromium_preferences(self.profile))
            self.assertEqual(self.prefs.read_text(), broken)

    def test_write_error_does_not_break_the_launch(self):
        self.write({"x": 1})
        with mock.patch("application_launcher.os.replace", side_effect=PermissionError("em uso")):
            self.assertFalse(ensure_chromium_preferences(self.profile))
            command = external_browser_command("msedge.exe", "https://x.org/", self.tmp.name, profile_id="child-1")
        self.assertIn("--disable-features=Translate", command)
        self.assertEqual(json.loads(self.prefs.read_text()), {"x": 1})
        self.assertEqual(os.listdir(self.prefs.parent), ["Preferences"])


class WebSocketFrameTest(unittest.TestCase):
    def test_accept_key_matches_rfc_example(self):
        self.assertEqual(site_logins.ws_accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_client_frame_is_masked_text(self):
        frame = site_logins.encode_frame("Hello", mask_key=b"\x37\xfa\x21\x3d")
        # exemplo da RFC 6455, seção 5.7
        self.assertEqual(frame, bytes.fromhex("818537fa213d7f9f4d5158"))

    def test_lengths_round_trip(self):
        for size in (0, 125, 126, 65535, 65536, 70000):
            payload = bytes(i % 251 for i in range(size))
            frame = site_logins.encode_frame(payload, site_logins.OP_BINARY)
            fin, opcode, data, used = site_logins.decode_frame(frame + b"resto")
            self.assertTrue(fin)
            self.assertEqual(opcode, site_logins.OP_BINARY)
            self.assertEqual(data, payload)
            self.assertEqual(used, len(frame))
            header = 2 if size < 126 else 4 if size < 65536 else 10
            self.assertEqual(len(frame), header + 4 + size)

    def test_incomplete_frames_wait_for_more(self):
        frame = site_logins.encode_frame("x" * 300)
        for cut in (0, 1, 3, 7, len(frame) - 1):
            self.assertIsNone(site_logins.decode_frame(frame[:cut]))

    def test_server_frames_are_unmasked(self):
        fin, opcode, data, used = site_logins.decode_frame(b"\x81\x02oi")
        self.assertEqual((fin, opcode, data, used), (True, site_logins.OP_TEXT, b"oi", 4))
        fin, opcode, data, _ = site_logins.decode_frame(b"\x01\x02oi")
        self.assertFalse(fin)

    def test_extensions_are_refused(self):
        with self.assertRaises(ConnectionError):
            site_logins.decode_frame(b"\xc1\x02oi")  # RSV1 (compressão) não foi negociado

    def test_page_target_ignores_workers_and_remote_hosts(self):
        targets = [
            {"type": "service_worker", "url": "https://x.org/sw.js",
             "webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/page/W"},
            {"type": "page", "url": "https://x.org/",
             "webSocketDebuggerUrl": "ws://192.168.0.5:1/devtools/page/R"},
            {"type": "page", "url": "edge://newtab/",
             "webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/page/N"},
            {"type": "page", "url": "https://x.org/",
             "webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/page/OK"},
        ]
        self.assertEqual(site_logins.pick_page_target(targets), "/devtools/page/OK")
        self.assertIsNone(site_logins.pick_page_target({"nada": 1}))


def _server_frame(text, opcode=site_logins.OP_TEXT, fin=True):
    data = text.encode() if isinstance(text, str) else text
    assert len(data) < 126
    return bytes([(0x80 if fin else 0) | opcode, len(data)]) + data


class FakeDevTools(socketserver.ThreadingTCPServer):
    """Um "Edge" de mentira: /json/list e o WebSocket de uma página com login."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, login_url, after_login_url, start_url, fragment_replies=False):
        self.href = start_url
        self.login_url = login_url
        self.after_login_url = after_login_url
        self.fragment_replies = fragment_replies
        self.fill_args = None
        self.messages = []
        self.navigations = []
        super().__init__(("127.0.0.1", 0), FakeDevToolsHandler)

    @property
    def port(self):
        return self.server_address[1]


class FakeDevToolsHandler(socketserver.BaseRequestHandler):
    def handle(self):
        server = self.server
        sock = self.request
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(4096)
            if not chunk:
                return
            head += chunk
        lines = head.split(b"\r\n\r\n", 1)[0].decode().split("\r\n")
        path = lines[0].split()[1]
        headers = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:])}
        if path == "/json/list":
            body = json.dumps([
                {"type": "page", "url": server.href,
                 "webSocketDebuggerUrl": f"ws://127.0.0.1:{server.port}/devtools/page/ABC"},
            ]).encode()
            sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                         + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            return
        assert path == "/devtools/page/ABC", path
        assert "origin" not in headers  # o Edge recusa Origin desconhecida
        accept = site_logins.ws_accept_key(headers["sec-websocket-key"])
        sock.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode())
        sock.sendall(_server_frame(b"", site_logins.OP_PING))
        buf = b""
        while True:
            frame = site_logins.decode_frame(buf)
            if frame is None:
                chunk = sock.recv(65536)
                if not chunk:
                    return
                buf += chunk
                continue
            fin, opcode, payload, used = frame
            buf = buf[used:]
            assert payload == b"" or buf is not None
            if opcode in (site_logins.OP_PONG,):
                continue
            if opcode == site_logins.OP_CLOSE:
                return
            msg = json.loads(payload)
            server.messages.append(msg)
            reply = json.dumps({"id": msg["id"], "result": self.result(msg)})
            # um evento antes da resposta: o cliente tem de ignorar
            sock.sendall(_server_frame(json.dumps({"method": "Page.loadEventFired", "params": {}})))
            if server.fragment_replies and len(reply) > 10:
                sock.sendall(_server_frame(reply[:5], fin=False)
                             + _server_frame(reply[5:], site_logins.OP_CONT))
            else:
                data = reply.encode()
                if len(data) < 126:
                    sock.sendall(_server_frame(data))
                else:
                    sock.sendall(bytes([0x81, 126]) + len(data).to_bytes(2, "big") + data)

    def result(self, msg):
        server = self.server
        if msg["method"] == "Page.navigate":
            server.navigations.append(msg["params"]["url"])
            server.href = msg["params"]["url"]
            return {"frameId": "F"}
        assert msg["method"] == "Runtime.evaluate", msg
        assert msg["params"]["returnByValue"] is True
        expression = msg["params"]["expression"]
        if "window.__beniOld = true" in expression:
            return {"result": {"type": "undefined"}}
        if "!window.__beniOld" in expression:
            return {"result": {"type": "boolean", "value": True}}
        if "querySelector(userSel)" in expression:
            args = json.loads(expression[expression.rindex(".apply(null, ") + 13:-1])
            server.fill_args = args
            server.href = server.after_login_url
            return {"result": {"type": "string", "value": "sent"}}
        if "return location.href" in expression:
            return {"result": {"type": "string", "value": server.href}}
        raise AssertionError(expression)


class DevToolsLoginTest(unittest.TestCase):
    def run_login(self, site, target, after, fragment=False):
        info = site_logins.SITES[site]
        server = FakeDevTools(info["login_url"], after, target, fragment_replies=fragment)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        events = []
        try:
            result = site_logins.auto_login(
                site, "crianca@example.com", "s3nh@\"'", target, port=server.port,
                log=lambda event, **details: events.append((event, details)),
                timeout=10, driver="devtools",
            )
        finally:
            server.shutdown()
            server.server_close()
        return result, server, events

    def test_fills_the_login_page_and_returns_to_the_tile(self):
        target = "https://www.teachyourmonster.org/account/play"
        result, server, events = self.run_login(
            "teachyourmonster", target, "https://www.teachyourmonster.org/account/dashboard", fragment=True,
        )
        self.assertEqual(result, "ok")
        info = site_logins.SITES["teachyourmonster"]
        self.assertEqual(server.fill_args[:5], [
            "crianca@example.com", "s3nh@\"'", info["user_selector"],
            info["password_selector"], info["submit_selector"],
        ])
        self.assertEqual(server.fill_args[6], ["#tab_home"])
        self.assertEqual(server.navigations, [info["login_url"], target])
        self.assertEqual(events, [("site_login.finished", {"driver": "devtools", "result": "success"})])
        # a senha não vai para o log
        self.assertNotIn("s3nh", json.dumps(events))

    def test_already_logged_in_does_not_type(self):
        target = "https://pt.khanacademy.org/math"
        info = site_logins.SITES["khan"]

        class Logged(FakeDevToolsHandler):
            def result(self, msg):
                if msg["method"] == "Page.navigate" and msg["params"]["url"].startswith(info["login_url"]):
                    self.server.navigations.append(msg["params"]["url"])
                    self.server.href = target  # o site redireciona: sessão aberta
                    return {"frameId": "F"}
                return super().result(msg)

        server = FakeDevTools(info["login_url"], target, target)
        server.RequestHandlerClass = Logged
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            result = site_logins.auto_login("khan", "a@example.com", "x", target, port=server.port,
                                            timeout=10, driver="devtools")
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(result, "already")
        self.assertIsNone(server.fill_args)
        self.assertEqual(server.navigations, [info["login_url"] + "?continue=/math"])

    def test_no_browser_listening_gives_error_quickly(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        original = site_logins.DevTools.__init__.__defaults__
        site_logins.DevTools.__init__.__defaults__ = (0.5, 2)
        try:
            result = site_logins.auto_login("khan", "a", "b", "https://pt.khanacademy.org/", port=port,
                                            driver="devtools")
        finally:
            site_logins.DevTools.__init__.__defaults__ = original
        self.assertEqual(result, "error")


if __name__ == "__main__":
    unittest.main()
