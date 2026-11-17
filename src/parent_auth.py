"""PIN authentication, throttling, and parent-session state."""

import hashlib
import hmac
import re
import secrets
import threading
import time
from http.cookies import SimpleCookie


ADMIN_SESSION_TTL_SECONDS = 30 * 60
PIN_FAILURE_WINDOW_SECONDS = 60
PIN_FAILURE_LIMIT = 5
PIN_KDF_ITERATIONS = 200_000
ADMIN_COOKIE_NAME = "cozy_admin"

_admin_sessions = {}
_admin_sessions_lock = threading.Lock()
_pin_failures = []
_pin_failures_lock = threading.Lock()


def is_legacy_pin_hash(pin_hash):
    return isinstance(pin_hash, str) and bool(
        re.fullmatch(r"[0-9a-f]{16}", pin_hash)
    )


def is_supported_pin_hash(pin_hash):
    if not isinstance(pin_hash, str):
        return False
    if is_legacy_pin_hash(pin_hash):
        return True
    parts = pin_hash.split("$")
    return (
        len(parts) == 4
        and parts[0] == "pbkdf2_sha256"
        and parts[1].isdigit()
        and 50_000 <= int(parts[1]) <= 1_000_000
        and bool(re.fullmatch(r"[0-9a-f]{32}", parts[2]))
        and bool(re.fullmatch(r"[0-9a-f]{64}", parts[3]))
    )


def hash_pin(pin, salt=None):
    if not isinstance(pin, str) or not re.fullmatch(r"\d{4,6}", pin):
        raise ValueError("PIN must contain 4 to 6 digits")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode("utf-8"),
        bytes.fromhex(salt),
        PIN_KDF_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PIN_KDF_ITERATIONS}${salt}${digest}"


def verify_pin(pin_hash, pin):
    if not pin_hash or not pin:
        return False
    if is_legacy_pin_hash(pin_hash):
        computed = hashlib.sha256(pin.encode("utf-8")).hexdigest()[:16]
        return hmac.compare_digest(computed, pin_hash)
    if not is_supported_pin_hash(pin_hash):
        return False
    _, iterations, salt, expected = pin_hash.split("$")
    computed = hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode("utf-8"),
        bytes.fromhex(salt),
        int(iterations),
    ).hex()
    return hmac.compare_digest(computed, expected)


def create_admin_session(now=None):
    now = time.time() if now is None else now
    token = secrets.token_urlsafe(32)
    with _admin_sessions_lock:
        expired = [key for key, expiry in _admin_sessions.items() if expiry <= now]
        for key in expired:
            _admin_sessions.pop(key, None)
        _admin_sessions[token] = now + ADMIN_SESSION_TTL_SECONDS
    return token


def clear_admin_sessions():
    with _admin_sessions_lock:
        _admin_sessions.clear()


def valid_admin_session(cookie_header, now=None):
    if not cookie_header:
        return False
    try:
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        morsel = cookie.get(ADMIN_COOKIE_NAME)
        token = morsel.value if morsel else ""
    except Exception:
        return False
    if not token:
        return False
    now = time.time() if now is None else now
    with _admin_sessions_lock:
        expiry = _admin_sessions.get(token, 0)
        if expiry <= now:
            _admin_sessions.pop(token, None)
            return False
        _admin_sessions[token] = now + ADMIN_SESSION_TTL_SECONDS
    return True


def admin_session_cookie(token):
    return (
        f"{ADMIN_COOKIE_NAME}={token}; Path=/; HttpOnly; "
        f"SameSite=Strict; Max-Age={ADMIN_SESSION_TTL_SECONDS}"
    )


def expired_admin_session_cookie():
    return (
        f"{ADMIN_COOKIE_NAME}=; Path=/; HttpOnly; "
        "SameSite=Strict; Max-Age=0"
    )


def pin_attempt_blocked(now=None):
    now = time.time() if now is None else now
    cutoff = now - PIN_FAILURE_WINDOW_SECONDS
    with _pin_failures_lock:
        _pin_failures[:] = [stamp for stamp in _pin_failures if stamp > cutoff]
        return len(_pin_failures) >= PIN_FAILURE_LIMIT


def record_pin_failure(now=None):
    now = time.time() if now is None else now
    with _pin_failures_lock:
        _pin_failures.append(now)


def clear_pin_failures():
    with _pin_failures_lock:
        _pin_failures.clear()


# ---------------------------------------------------------------------------
# Área dos pais pelo menu nativo: o menu abre o navegador escondido enquanto o
# adulto digita o PIN na tela do menu. Fluxo:
#   1. o menu cria uma "espera" (criar_espera) e abre o navegador com o id dela;
#   2. a página escondida fica esperando (aguardar_espera) num estado neutro;
#   3. PIN certo no menu → liberar_espera: nasce um token de uso único que vale
#      PAIS_TOKEN_TTL_SECONDS; a espera o entrega UMA vez à página e some;
#   4. a página troca o token pelo cookie de admin normal (trocar_token_pais).
# Nem o id da espera nem o token aparecem em log. Espera não liberada some em
# PAIS_ESPERA_TTL_SECONDS; o token, usado ou vencido, não serve mais.

PAIS_TOKEN_TTL_SECONDS = 30
PAIS_ESPERA_TTL_SECONDS = 10 * 60
PAIS_ESPERAS_MAX = 8

_esperas = {}  # id -> {"criada": t, "token": str|None, "evento": Event}
_tokens_pais = {}  # token -> validade
_pais_lock = threading.Lock()


def _limpar_pais(now):
    for chave in [k for k, e in _esperas.items() if e["criada"] + PAIS_ESPERA_TTL_SECONDS <= now]:
        _esperas.pop(chave).get("evento").set()
    for chave in [k for k, validade in _tokens_pais.items() if validade <= now]:
        _tokens_pais.pop(chave, None)


def criar_espera(now=None):
    now = time.time() if now is None else now
    espera = secrets.token_urlsafe(24)
    with _pais_lock:
        _limpar_pais(now)
        while len(_esperas) >= PAIS_ESPERAS_MAX:
            mais_velha = min(_esperas, key=lambda k: _esperas[k]["criada"])
            _esperas.pop(mais_velha)["evento"].set()
        _esperas[espera] = {"criada": now, "token": None, "evento": threading.Event()}
    return espera


def liberar_espera(espera, now=None):
    """Depois do PIN certo: cria o token da espera. False se ela não existe mais."""
    now = time.time() if now is None else now
    if not isinstance(espera, str) or not espera:
        return False
    with _pais_lock:
        _limpar_pais(now)
        item = _esperas.get(espera)
        if item is None:
            return False
        if item["token"] is None:
            token = secrets.token_urlsafe(32)
            item["token"] = token
            _tokens_pais[token] = now + PAIS_TOKEN_TTL_SECONDS
        item["evento"].set()
    return True


def cancelar_espera(espera):
    with _pais_lock:
        item = _esperas.pop(espera, None) if isinstance(espera, str) else None
        if item:
            if item["token"]:
                _tokens_pais.pop(item["token"], None)
            item["evento"].set()
    return item is not None


def aguardar_espera(espera, timeout=20.0):
    """A página escondida espera o PIN. Devolve ("pronto", token) uma única vez,
    ("aguardando", None) se o tempo acabou, ("ocupada", None) se outro pedido já
    espera nesta mesma espera, ou ("desconhecida", None).

    Um pedido por vez: o id da espera fica na linha de comando do navegador, que
    outro programa do mesmo usuário consegue ler. Sem esta regra, um programa
    esperando junto com a página poderia levar o token quando o PIN chegasse."""
    if not isinstance(espera, str) or not espera:
        return "desconhecida", None
    with _pais_lock:
        _limpar_pais(time.time())
        item = _esperas.get(espera)
        if item is None:
            return "desconhecida", None
        if item.get("ocupada"):
            return "ocupada", None
        item["ocupada"] = True
    try:
        item["evento"].wait(max(0.0, timeout))
    finally:
        with _pais_lock:
            item["ocupada"] = False
    with _pais_lock:
        if _esperas.get(espera) is not item:
            return "desconhecida", None
        if item["token"] is None:
            return "aguardando", None
        _esperas.pop(espera, None)  # entregue: a espera não serve de novo
        return "pronto", item["token"]


def trocar_token_pais(token, now=None):
    """Uso único: True só na primeira troca, dentro da validade."""
    now = time.time() if now is None else now
    if not isinstance(token, str) or not token:
        return False
    with _pais_lock:
        validade = _tokens_pais.pop(token, 0)
    return validade > now


def limpar_pais():
    with _pais_lock:
        for item in _esperas.values():
            item["evento"].set()
        _esperas.clear()
        _tokens_pais.clear()
