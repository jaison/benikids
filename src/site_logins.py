"""Login automático em sites (Khan Academy, Teach Your Monster), por perfil.

O e-mail e a senha ficam em ~/.config/cozy-kids-launcher/site-logins.json
(permissão 600), fora do config.json, e a senha nunca volta para a página:
a área dos pais só vê o e-mail e se há senha salva.

Ao abrir o site, o navegador sobe com o controle remoto ligado só para esse
tile: o Firefox com o Marionette, o Edge/Chrome com o DevTools Protocol (CDP),
os dois só em 127.0.0.1. Uma thread preenche a página de login do site e clica
em "Entrar". Se a sessão ainda estiver aberta (cookie), nada é digitado. A
senha vai só pelo socket local, nunca para a linha de comando nem para o log.
"""

import base64
import hashlib
import http.client
import json
import os
import socket
import struct
import tempfile
import threading
import time
from urllib.parse import quote, urlparse

MARIONETTE_PORT = 28290
DEVTOOLS_PORT = 28291

SITES = {
    "khan": {
        "label": "Khan Academy",
        "hosts": ("khanacademy.org",),
        "login_url": "https://pt.khanacademy.org/login",
        "user_selector": "[data-testid=identifier-field]",
        "password_selector": "[data-testid=password-field]",
        "submit_selector": "[data-testid=log-in-submit-button]",
        # aviso de cookies (TrustArc): "Somente os necessários"
        "dismiss_selectors": ("#truste-consent-required",),
        "continue_param": "continue",
    },
    "teachyourmonster": {
        "label": "Teach Your Monster",
        "hosts": ("teachyourmonster.org",),
        "login_url": "https://www.teachyourmonster.org/account/users/sign_in",
        # conta de família: aba "Home" (as outras são Student e Teacher)
        "pre_click_selectors": ("#tab_home",),
        "user_selector": "form.user.home input[name='oog_user[email]']",
        "password_selector": "form.user.home input[name='oog_user[password]']",
        "submit_selector": "form.user.home button[type=submit]",
        "dismiss_selectors": (),
    },
}

MAX_FIELD = 200


# ------------------------------------------------------------ armazenamento

def _empty():
    return {"version": 1, "profiles": {}}


def load_logins(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        return _empty()
    return data


def save_logins(path, data):
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".site-logins.", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_login(path, profile_id, site):
    entry = load_logins(path)["profiles"].get(profile_id, {}).get(site)
    if not isinstance(entry, dict) or not entry.get("username") or not entry.get("password"):
        return None
    return entry


def public_logins(path, profile_id):
    """O que a área dos pais pode ver: e-mail e se há senha (nunca a senha)."""
    stored = load_logins(path)["profiles"].get(profile_id, {})
    result = []
    for site, info in SITES.items():
        entry = stored.get(site) if isinstance(stored.get(site), dict) else {}
        result.append({
            "id": site,
            "label": info["label"],
            "username": entry.get("username", ""),
            "hasPassword": bool(entry.get("password")),
        })
    return result


def update_login(path, profile_id, site, username=None, password=None, remove=False):
    """Grava/apaga o login. password=None mantém a senha já salva."""
    if site not in SITES:
        raise ValueError("unknown site")
    if not isinstance(profile_id, str) or not profile_id or len(profile_id) > 64:
        raise ValueError("invalid profile")
    data = load_logins(path)
    profiles = data["profiles"]
    if remove:
        profiles.get(profile_id, {}).pop(site, None)
        if not profiles.get(profile_id):
            profiles.pop(profile_id, None)
        save_logins(path, data)
        return
    for value in (username, password):
        if value is not None and (not isinstance(value, str) or len(value) > MAX_FIELD):
            raise ValueError("invalid field")
    username = (username or "").strip()
    if not username:
        raise ValueError("username required")
    entry = profiles.setdefault(profile_id, {}).setdefault(site, {})
    entry["username"] = username
    if password:
        entry["password"] = password
    if not entry.get("password"):
        raise ValueError("password required")
    save_logins(path, data)


def site_for_url(url):
    host = (urlparse(url).hostname or "").lower()
    for site, info in SITES.items():
        if any(host == h or host.endswith("." + h) for h in info["hosts"]):
            return site
    return None


# ------------------------------------------------------------- Marionette

class Marionette:
    """Cliente mínimo do protocolo Marionette do Firefox (só stdlib)."""

    def __init__(self, port, host="127.0.0.1", connect_timeout=40, io_timeout=60):
        deadline = time.time() + connect_timeout
        while True:
            try:
                self.sock = socket.create_connection((host, port), timeout=io_timeout)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.4)
        self.buf = b""
        self.msg_id = 0
        self._read()  # mensagem de boas-vindas

    def _read(self):
        while b":" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("marionette closed")
            self.buf += chunk
        size, rest = self.buf.split(b":", 1)
        size = int(size)
        while len(rest) < size:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("marionette closed")
            rest += chunk
        self.buf = rest[size:]
        return json.loads(rest[:size])

    def cmd(self, name, params=None):
        self.msg_id += 1
        data = json.dumps([0, self.msg_id, name, params or {}]).encode()
        self.sock.sendall(str(len(data)).encode() + b":" + data)
        while True:
            msg = self._read()
            if msg[0] == 1 and msg[1] == self.msg_id:
                if msg[2]:
                    raise RuntimeError(msg[2].get("error", "marionette error"))
                return msg[3]

    def script(self, source, *args):
        return self.cmd("WebDriver:ExecuteScript", {"script": source, "args": list(args)}).get("value")

    def begin(self):
        self.cmd("WebDriver:NewSession", {"capabilities": {"pageLoadStrategy": "eager"}})

    def navigate(self, url):
        self.cmd("WebDriver:Navigate", {"url": url})

    def end(self):
        try:
            self.cmd("WebDriver:DeleteSession")
        except Exception:  # noqa: BLE001
            pass

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# ------------------------------------------------- WebSocket mínimo (RFC 6455)
# Só o que o DevTools do Edge/Chrome precisa: handshake, frames de texto com
# máscara (cliente → servidor), sem extensões nem compressão.

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


def ws_accept_key(key):
    return base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()


def encode_frame(payload, opcode=OP_TEXT, mask_key=None):
    """Um frame final (FIN), com máscara, como o cliente tem de mandar."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    mask_key = os.urandom(4) if mask_key is None else mask_key
    header = bytes([0x80 | opcode])
    size = len(payload)
    if size < 126:
        header += bytes([0x80 | size])
    elif size < 1 << 16:
        header += bytes([0x80 | 126]) + struct.pack("!H", size)
    else:
        header += bytes([0x80 | 127]) + struct.pack("!Q", size)
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return header + mask_key + masked


def decode_frame(buf):
    """(fin, opcode, payload, bytes usados) do primeiro frame de buf, ou None se incompleto."""
    if len(buf) < 2:
        return None
    fin = bool(buf[0] & 0x80)
    if buf[0] & 0x70:
        raise ConnectionError("websocket extension not negotiated")
    opcode = buf[0] & 0x0F
    masked = bool(buf[1] & 0x80)
    size = buf[1] & 0x7F
    pos = 2
    if size == 126:
        if len(buf) < 4:
            return None
        size = struct.unpack("!H", buf[2:4])[0]
        pos = 4
    elif size == 127:
        if len(buf) < 10:
            return None
        size = struct.unpack("!Q", buf[2:10])[0]
        pos = 10
    mask_key = b""
    if masked:
        if len(buf) < pos + 4:
            return None
        mask_key = buf[pos:pos + 4]
        pos += 4
    if len(buf) < pos + size:
        return None
    payload = bytes(buf[pos:pos + size])
    if masked:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return fin, opcode, payload, pos + size


class WebSocket:
    """Cliente WebSocket só para 127.0.0.1 (o DevTools do navegador)."""

    def __init__(self, port, path, timeout=60):
        if not path.startswith("/"):
            raise ValueError("invalid websocket path")
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake closed")
            response += chunk
            if len(response) > 65536:
                raise ConnectionError("websocket handshake too long")
        head, self.buf = response.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        if len(lines[0].split()) < 2 or lines[0].split()[1] != "101":
            raise ConnectionError("websocket handshake refused")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        if headers.get("sec-websocket-accept") != ws_accept_key(key):
            raise ConnectionError("websocket handshake mismatch")

    def send_text(self, text):
        self.sock.sendall(encode_frame(text, OP_TEXT))

    def recv_text(self):
        """Próxima mensagem de texto (junta fragmentos, responde ping)."""
        parts = []
        while True:
            frame = decode_frame(self.buf)
            if frame is None:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("websocket closed")
                self.buf += chunk
                continue
            fin, opcode, payload, used = frame
            self.buf = self.buf[used:]
            if opcode == OP_PING:
                self.sock.sendall(encode_frame(payload, OP_PONG))
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                raise ConnectionError("websocket closed")
            parts.append(payload)
            if fin:
                return b"".join(parts).decode("utf-8")

    def close(self):
        try:
            self.sock.sendall(encode_frame(b"", OP_CLOSE))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


# ------------------------------------------------------ DevTools (Edge/Chrome)

def _devtools_targets(port, timeout=5):
    # http.client direto: o urllib usaria o proxy do sistema no Windows
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", "/json/list")
        response = conn.getresponse()
        if response.status != 200:
            raise ConnectionError("devtools list failed")
        return json.loads(response.read())
    finally:
        conn.close()


def pick_page_target(targets):
    """O caminho do WebSocket da página do site (não de iframes/workers)."""
    for target in targets if isinstance(targets, list) else []:
        if not isinstance(target, dict) or target.get("type") != "page":
            continue
        url = target.get("url", "")
        if url.startswith(("devtools:", "edge:", "chrome:", "chrome-extension:", "extension:")):
            continue
        ws = urlparse(target.get("webSocketDebuggerUrl", ""))
        if ws.scheme == "ws" and ws.hostname in ("127.0.0.1", "localhost") and ws.path:
            return ws.path
    return None


class DevTools:
    """Controle da página do Edge/Chrome pelo DevTools Protocol (mesma interface do Marionette)."""

    def __init__(self, port, connect_timeout=40, io_timeout=60):
        deadline = time.time() + connect_timeout
        while True:
            try:
                path = pick_page_target(_devtools_targets(port))
                if path:
                    break
            except (OSError, ValueError, ConnectionError):
                pass
            if time.time() > deadline:
                raise ConnectionError("devtools page not found")
            time.sleep(0.4)
        self.ws = WebSocket(port, path, timeout=io_timeout)
        self.msg_id = 0

    def cmd(self, method, params=None):
        self.msg_id += 1
        self.ws.send_text(json.dumps({"id": self.msg_id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv_text())
            if msg.get("id") != self.msg_id:
                continue  # eventos
            if "error" in msg:
                raise RuntimeError(str(msg["error"].get("message", "devtools error")))
            return msg.get("result", {})

    def script(self, source, *args):
        """Roda o corpo de função (como no Marionette, com `arguments`). None se a página trocou no meio."""
        expression = f"(function(){{{source}\n}}).apply(null, {json.dumps(list(args))})"
        try:
            result = self.cmd("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        except RuntimeError:
            return None  # contexto destruído (navegação em andamento)
        if result.get("exceptionDetails"):
            return None
        return result.get("result", {}).get("value")

    def begin(self):
        pass

    def navigate(self, url, timeout=30):
        # O Page.navigate volta antes de a página nova carregar; a marca no
        # documento atual some quando o novo assume (inclusive em redirect).
        self.script("window.__beniOld = true;")
        self.cmd("Page.navigate", {"url": url})
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.script("return !window.__beniOld && document.readyState !== 'loading';"):
                return
            time.sleep(0.3)

    def end(self):
        pass

    def close(self):
        self.ws.close()


_FILL_SCRIPT = """
const [user, pass, userSel, passSel, submitSel, dismiss, preClick] = arguments;
for (const sel of dismiss) { const b = document.querySelector(sel); if (b && b.offsetParent) b.click(); }
for (const sel of preClick) { const b = document.querySelector(sel); if (b) b.click(); }
const u = document.querySelector(userSel), p = document.querySelector(passSel), s = document.querySelector(submitSel);
if (!u || !p || !s) return 'wait';
const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
for (const [el, v] of [[u, user], [p, pass]]) {
  setter.call(el, v);
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
}
s.click();
return 'sent';
"""


def auto_login(site, username, password, target_url, port=MARIONETTE_PORT, log=None, timeout=60,
               driver="marionette"):
    """Faz o login no navegador recém-aberto. Devolve 'ok', 'already', 'failed' ou 'error'.

    driver: "marionette" (Firefox) ou "devtools" (Edge/Chrome).
    """
    info = SITES[site]
    log = log or (lambda *a, **k: None)
    client = None
    try:
        client = DevTools(port) if driver == "devtools" else Marionette(port)
        client.begin()
        login_path = urlparse(info["login_url"]).path
        target_path = urlparse(target_url).path or "/"
        login_url = info["login_url"]
        if info.get("continue_param"):
            login_url += "?" + info["continue_param"] + "=" + quote(target_path, safe="/")
        client.navigate(login_url)
        deadline = time.time() + timeout
        sent = False
        while time.time() < deadline:
            href = client.script("return location.href")
            if not href:
                time.sleep(0.7)  # página trocando (DevTools)
                continue
            here = urlparse(href)
            if not here.path.startswith(login_path):
                result = "ok" if sent else "already"
                break
            if not sent:
                if client.script(
                    _FILL_SCRIPT, username, password, info["user_selector"],
                    info["password_selector"], info["submit_selector"],
                    list(info.get("dismiss_selectors", ())), list(info.get("pre_click_selectors", ())),
                ) == "sent":
                    sent = True
                    sent_at = time.time()
            elif time.time() - sent_at > 15:
                result = "failed"   # continua na página de login (senha errada?)
                break
            time.sleep(0.7)
        else:
            result = "failed"
        if result in ("ok", "already"):
            # depois do login, vai para a página do tile (se o site não foi sozinho)
            if urlparse(client.script("return location.href") or "").path.rstrip("/") != target_path.rstrip("/"):
                client.navigate(target_url)
        log("site_login.finished", driver=driver,
            result={"ok": "success", "already": "already"}.get(result, "failure"))
        return result
    except Exception as exc:  # noqa: BLE001 — nunca derruba o launcher
        log("site_login.finished", level="warning", driver=driver, result="failure",
            exceptionType=type(exc).__name__)
        return "error"
    finally:
        if client is not None:
            client.end()
            client.close()


def start_auto_login(site, username, password, target_url, log=None, driver="marionette"):
    port = DEVTOOLS_PORT if driver == "devtools" else MARIONETTE_PORT
    thread = threading.Thread(
        target=auto_login,
        args=(site, username, password, target_url),
        kwargs={"log": log, "driver": driver, "port": port},
        name=f"site-login-{site}",
        daemon=True,
    )
    thread.start()
    return thread
