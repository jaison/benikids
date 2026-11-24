#!/usr/bin/env python3
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, quote, unquote, urlparse

import catalogo_windows
import controles
import inicio_automatico
import itch_sync
import telemetria
import site_logins
from app_detection import (
    BROWSER_CANDIDATES,
    browser_family,
    browser_statuses,
    find_browser as detect_browser,
    parse_desktop_file,
    scan_apps as discover_apps,
)
from application_launcher import (
    ApplicationLauncher,
    PortaoDeAbertura,
    direct_app_command,
    external_browser_command as build_external_browser_command,
    resolve_tile_action,
)
from activity_store import (
    ACTIVITY_VERSION,
    EmbeddedActivitySessions,
    activity_payload,
    remove_profile_activity,
)
from config_store import (
    CURRENT_CONFIG_VERSION,
    atomic_write_config,
    migrate_config,
    read_config,
)
from config_validation import (
    MAX_TILES,
    public_config,
    validate_config,
    validate_stored_config,
)
from profile_config import (
    active_config,
    active_profile,
    add_profile,
    merge_active_config,
    profile_summaries,
    remove_profile,
    select_profile,
)
from backup_store import (
    create_pre_restore_backup,
    discover_config_backups,
    read_config_backup,
)
from browser_policy import allowed_frame_origins, embedded_browser_csp
from lifecycle_state import (
    clear_lifecycle_request,
    read_lifecycle_state,
    write_lifecycle_request,
)
from media_library import (
    INDIVIDUAL_MEDIA_PLAYER_CANDIDATES,
    MAX_MEDIA_COVER_BYTES,
    SUPPORTED_MEDIA_PATTERNS,
    catalog_item,
    find_media_player as detect_media_player,
    has_media as path_has_media,
    media_locations as discover_media_locations,
    media_player_command,
    public_media_catalog,
    scan_media_catalog,
)
from media_state import (
    media_state_payload,
    record_media_play,
    remove_profile_media_state,
    set_media_favorite,
)
from media_resume import (
    prepare_profile_resume_directory,
    remove_profile_resume_directory,
)
from parent_auth import (
    ADMIN_COOKIE_NAME,
    ADMIN_SESSION_TTL_SECONDS,
    PIN_FAILURE_LIMIT,
    PIN_FAILURE_WINDOW_SECONDS,
    PIN_KDF_ITERATIONS,
    admin_session_cookie,
    aguardar_espera,
    cancelar_espera,
    clear_admin_sessions,
    criar_espera,
    liberar_espera,
    trocar_token_pais,
    clear_pin_failures,
    create_admin_session,
    expired_admin_session_cookie,
    hash_pin,
    is_legacy_pin_hash,
    is_supported_pin_hash,
    pin_attempt_blocked,
    record_pin_failure,
    valid_admin_session,
    verify_pin,
)
from process_state import (
    owned_process,
    owned_process_alive,
    remove_process_record,
    terminate_owned_process,
    write_process_record,
)
from runtime_diagnostics import (
    build_diagnostics,
    close_runtime_logging,
    configure_runtime_logging,
    log_runtime_event,
)
from schedule_rules import (
    availability_summary as schedule_availability_summary,
    tile_availability as schedule_tile_availability,
)
from usage_limits import UsageTracker, load_usage, tile_category as usage_tile_category
from speech_feedback import SpeechFeedback
from timer_state import (
    clear_timer as remove_timer_state,
    load_timer as read_timer_state,
    save_timer as write_timer_state,
    timer_status as calculate_timer_status,
)
from update_manager import (
    MissingUpdaterError,
    fetch_remote_json as fetch_update_json,
    fetch_remote_text as fetch_update_text,
    parse_semver,
    read_version,
    resolve_update_status,
    version_is_newer,
    write_update_trigger,
)

HOME = os.path.expanduser("~")
APP_ROOT = os.path.join(HOME, ".local", "share", "cozy-kids-launcher")
VERSION_FILE = os.path.join(APP_ROOT, "version")
UPDATE_SCRIPT = os.path.join(APP_ROOT, "update.sh")
UPDATE_CHANNEL_FILE = os.path.join(APP_ROOT, "update-channel")
LATEST_RELEASE_API = os.environ.get(
    "COZY_KIDS_RELEASE_API_URL",
    "https://api.github.com/repos/jaison/benikids/releases/latest",
)
LEGACY_RAW_URL = os.environ.get(
    "COZY_KIDS_RAW_URL",
    "https://raw.githubusercontent.com/jaison/benikids/main",
).rstrip("/")
LEGACY_VERSION_URL = f"{LEGACY_RAW_URL}/VERSION"
CFG = os.path.join(HOME, ".config", "cozy-kids-launcher", "config.json")
# e-mail/senha dos sites por perfil (site_logins.py); nunca vai para a página
SITE_LOGINS_FILE = os.path.join(HOME, ".config", "cozy-kids-launcher", "site-logins.json")
# mapeamento dos controles USB (controles.py), feito na área dos pais
CONTROLES_FILE = os.path.join(HOME, ".config", "cozy-kids-launcher", "controles.json")
BACKUP_ROOT = os.path.join(HOME, ".local", "share", "cozy-kids-launcher-backups")
LOG_FILE = os.path.join(HOME, ".local", "state", "cozy-kids-launcher", "runtime.jsonl")
ACTIVITY_FILE = os.path.join(HOME, ".local", "state", "cozy-kids-launcher", "activity.json")
MEDIA_STATE_FILE = os.path.join(HOME, ".local", "state", "cozy-kids-launcher", "media.json")
TELEMETRIA_FILE = os.path.join(HOME, ".config", "cozy-kids-launcher", "telemetria.json")
MEDIA_RESUME_ROOT = os.path.join(
    HOME,
    ".local",
    "state",
    "cozy-kids-launcher",
    "media-resume",
)
MEDIA_SESSION_SCRIPT = os.path.join(APP_ROOT, "media_session.py")
PORT = int(os.environ.get("COZY_KIDS_PORT", "38431"))
PIDFILE = os.path.join(HOME, ".cache", "cozy-kids-launcher", "server.pid")
BROWSER_PIDFILE = os.path.join(HOME, ".cache", "cozy-kids-launcher", "browser.pid")
TILE_PROCESS_PIDFILE = os.path.join(HOME, ".cache", "cozy-kids-launcher", "tile-process.pid")
OVERLAY_PIDFILE = os.path.join(HOME, ".cache", "cozy-kids-launcher", "overlay.pid")
PROCESS_SUPERVISOR = os.path.join(APP_ROOT, "process_supervisor.py")
OVERLAY_SCRIPT = os.path.join(APP_ROOT, "overlay.py")
EXIT_FLAGFILE = os.path.join(HOME, ".cache", "cozy-kids-launcher", "exit-requested")
LIFECYCLE_STATE_FILE = os.path.join(HOME, ".cache", "cozy-kids-launcher", "lifecycle.json")
LIFECYCLE_REQUEST_FILE = os.path.join(
    HOME,
    ".cache",
    "cozy-kids-launcher",
    "lifecycle-request.json",
)
RECOMMENDATIONS_FILE = os.path.join(APP_ROOT, "recommendations.json")
VIDEOS = os.path.join(HOME, "Videos")
MUSIC = os.path.join(HOME, "Music")
ALT_MUSIC = os.path.join(HOME, "Musik")
EXTS = SUPPORTED_MEDIA_PATTERNS
LEGACY_WEB_ACTION_MIGRATIONS = {
    "special:external-browser:https://www.netflix.com/browse/kids":
        "special:external-browser:https://www.netflix.com/browse/genre/27346",
    "special:browser:https://www.tivi.de":
        "special:external-browser:https://www.zdf.de/kinder",
    "special:browser:https://www.kika.de":
        "special:external-browser:https://www.kika.de",
}
TIMER_FILE = os.path.join(HOME, ".cache", "cozy-kids-launcher", "timer.json")
USAGE_FILE = os.path.join(HOME, ".local", "state", "cozy-kids-launcher", "usage-today.json")
MAX_JSON_BODY_BYTES = 512 * 1024
AUTOSTART_DESKTOP = inicio_automatico.DESKTOP_LINUX
_tile_launch_lock = threading.Lock()
_activity_sessions_lock = threading.Lock()
_activity_sessions = None
_speech_feedback_lock = threading.Lock()
_speech_feedback = None


def has_media(path):
    return path_has_media(path, patterns=EXTS)


# Cache da configuração: cada requisição do menu (uso a cada 5 s, horários,
# timer, overlay...) chamava load_cfg(), que relê, migra, valida e copia o
# config.json inteiro (~12 ms num Celeron). Só refaz quando o arquivo (ou o
# recommendations.json) muda; devolve sempre uma cópia nova (json.loads).
_cfg_cache = {"key": None, "stored": None, "active": None}
_cfg_cache_lock = threading.Lock()


def _cfg_cache_key():
    try:
        info = os.stat(CFG)
    except OSError:
        return None
    try:
        rec = os.stat(RECOMMENDATIONS_FILE)
        rec_key = (rec.st_mtime_ns, rec.st_size)
    except OSError:
        rec_key = None
    return (CFG, info.st_mtime_ns, info.st_ctime_ns, info.st_size, info.st_ino, rec_key)


def load_stored_cfg():
    key = _cfg_cache_key()
    if key is not None:
        with _cfg_cache_lock:
            if _cfg_cache["key"] == key and _cfg_cache["stored"] is not None:
                return json.loads(_cfg_cache["stored"])
    data = _load_stored_cfg_from_disk()
    try:
        texto = json.dumps(data)
    except (TypeError, ValueError):
        return data
    with _cfg_cache_lock:
        _cfg_cache.update(key=_cfg_cache_key(), stored=texto, active=None)
    return data


def _load_stored_cfg_from_disk():
    data = read_config(CFG)
    data, migrated = migrate_config(data)
    recs = load_recommendations(check_installed=False)
    rec_by_first_cmd = {}
    for rec in recs:
        if rec.get("cmd"):
            rec_by_first_cmd[rec["cmd"][0]] = rec["cmd"]
        for alt in rec.get("alt_cmds", []):
            rec_by_first_cmd[alt] = rec["cmd"]
    for profile in data.get("profiles", []):
        for tile in profile.get("tiles", []):
            cmd = tile.get("cmd", [])
            if len(cmd) == 1 and cmd[0] in LEGACY_WEB_ACTION_MIGRATIONS:
                tile["cmd"] = [LEGACY_WEB_ACTION_MIGRATIONS[cmd[0]]]
                cmd = tile["cmd"]
                migrated = True
            if (
                cmd
                and cmd[0] in rec_by_first_cmd
                and cmd != rec_by_first_cmd[cmd[0]]
            ):
                tile["cmd"] = rec_by_first_cmd[cmd[0]]
                migrated = True
    if "autoScanDone" not in data:
        data["autoScanDone"] = True
        migrated = True
    data = validate_stored_config(
        data,
        existing_pin_hash=data.get("pinHash", ""),
        allow_pin_hash=True,
    )
    if migrated:
        atomic_write_config(CFG, data)
        log_runtime_event(
            "config.migrated",
            configVersion=data.get("configVersion", CURRENT_CONFIG_VERSION),
        )
    return data


def load_cfg():
    key = _cfg_cache_key()
    if key is not None:
        with _cfg_cache_lock:
            if _cfg_cache["key"] == key and _cfg_cache["active"] is not None:
                return json.loads(_cfg_cache["active"])
    data = active_config(load_stored_cfg())
    try:
        texto = json.dumps(data)
    except (TypeError, ValueError):
        return data
    with _cfg_cache_lock:
        if key is not None and _cfg_cache["key"] == key:
            _cfg_cache["active"] = texto
    return data


# Mesma lista de theme-runtime.js (COZY_WORLD_THEME_IDS).
WORLD_THEME_IDS = frozenset((
    "wald", "weltraum", "ocean", "dinosaurier", "baustelle", "prinzessin", "bauernhof",
    "katzen", "hunde", "heroi", "blocos", "ninja", "gelo", "casinha", "castelo", "benikids",
))
INDEX_BODY_TAG = '<body class="theme-rosa">'


def theme_period_at(hour):
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "day"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def index_body_tag(cfg, hour=None):
    """A tag <body> já com o tema escolhido, igual a applyThemeRuntime().

    Sem isso a página abre no tema padrão (rosa) e só troca depois de carregar a
    configuração, o que aparece por alguns segundos quando o computador liga.
    """
    theme = cfg.get("theme") if isinstance(cfg, dict) else None
    if not isinstance(theme, str) or not re.fullmatch(r"[a-z0-9-]{1,40}", theme):
        theme = "rosa"
    classes = ["theme-" + theme]
    period = None
    if theme in WORLD_THEME_IDS:
        classes.append("theme-world")
        if cfg.get("themeMotionEnabled") is True:
            classes.append("theme-world-motion")
        if cfg.get("themeTimeOfDayEnabled") is True:
            period = theme_period_at(time.localtime().tm_hour if hour is None else hour)
            classes.append("theme-time-" + period)
    tag = '<body class="' + " ".join(classes) + '"'
    if period:
        tag += ' data-theme-period="' + period + '"'
    return tag + ">"


def themed_index_html(cfg, hour=None):
    with open(os.path.join(APP_ROOT, "index.html"), encoding="utf-8") as source:
        html = source.read()
    return html.replace(INDEX_BODY_TAG, index_body_tag(cfg, hour), 1).encode("utf-8")


def save_stored_cfg(data):
    validated = validate_stored_config(
        data,
        existing_pin_hash=data.get("pinHash", ""),
        allow_pin_hash=True,
    )
    for perfil in validated.get("profiles", []):
        # número aleatório da criança no relatório de uso (perfis criados depois do cadastro)
        if not perfil.get("telemetryId"):
            perfil["telemetryId"] = os.urandom(16).hex()
    atomic_write_config(CFG, validated)
    return validated


def save_cfg(data):
    try:
        stored = load_stored_cfg()
    except FileNotFoundError:
        stored = validate_stored_config(
            data,
            existing_pin_hash=data.get("pinHash", ""),
            allow_pin_hash=True,
        )
        atomic_write_config(CFG, stored)
        return active_config(stored)

    validated = validate_config(
        data,
        existing_pin_hash=stored.get("pinHash", ""),
        allow_pin_hash=True,
    )
    stored = merge_active_config(stored, validated)
    stored = save_stored_cfg(stored)
    return active_config(stored)


def write_browser_override(data):
    browser_file = os.path.join(os.path.dirname(CFG), "browser")
    browser = data.get("browser", "")
    try:
        if browser:
            with open(browser_file, "w", encoding="utf-8") as handle:
                handle.write(browser)
        else:
            os.unlink(browser_file)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def available_config_backups():
    backups = []
    for metadata in discover_config_backups(BACKUP_ROOT):
        try:
            raw = read_config_backup(BACKUP_ROOT, metadata["id"])
            validated = validate_stored_config(raw, existing_pin_hash="")
        except (FileNotFoundError, OSError, ValueError):
            continue
        backups.append({
            **metadata,
            "configVersion": validated.get(
                "configVersion",
                CURRENT_CONFIG_VERSION,
            ),
        })
    return backups


def restore_config_backup(backup_id):
    current = load_stored_cfg()
    raw = read_config_backup(BACKUP_ROOT, backup_id)
    restored = validate_stored_config(
        raw,
        existing_pin_hash=current.get("pinHash", ""),
    )
    safety_backup = create_pre_restore_backup(BACKUP_ROOT, current)
    restored = save_stored_cfg(restored)
    runtime = active_config(restored)
    write_browser_override(runtime)
    log_runtime_event(
        "config.restored",
        configVersion=restored.get(
            "configVersion",
            CURRENT_CONFIG_VERSION,
        ),
    )
    return runtime, safety_backup


def scan_apps():
    return discover_apps(HOME)


def media_location():
    locations = media_locations()
    return locations[0] if locations else None


def media_locations():
    """Return every configured media directory that contains supported files."""
    return discover_media_locations(
        (VIDEOS, MUSIC, ALT_MUSIC),
        has_media_fn=has_media,
    )


def media_catalog():
    """Return a bounded catalog without changing the legacy playlist launch path."""
    return scan_media_catalog((VIDEOS, MUSIC, ALT_MUSIC))


def configured_media_tile(cfg, tile_id):
    """Resolve one visible media tile without trusting a client-supplied command."""
    if not isinstance(tile_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", tile_id):
        return None
    tile = next(
        (
            candidate
            for candidate in cfg.get("tiles", [])
            if candidate.get("id") == tile_id and candidate.get("visible", True)
        ),
        None,
    )
    if not tile:
        return None
    try:
        action = resolve_tile_action(tile)
    except ValueError:
        return None
    return tile if action["type"] == "media" else None


def configured_feedback_tile(cfg, tile_id):
    """Resolve one visible tile without accepting a client-provided label."""
    if (
        not isinstance(tile_id, str)
        or len(tile_id) > 80
        or not re.fullmatch(r"[A-Za-z0-9_-]+", tile_id)
    ):
        return None
    return next(
        (
            tile
            for tile in cfg.get("tiles", [])
            if tile.get("id") == tile_id and tile.get("visible", True)
        ),
        None,
    )


def find_media_player(candidates=None):
    if candidates is None:
        return detect_media_player(which=shutil.which)
    return detect_media_player(candidates=candidates, which=shutil.which)


def get_version():
    return read_version(VERSION_FILE)


def diagnostics_payload():
    """Return technical state without returning any family configuration values."""
    config_readable = False
    config_version = None
    try:
        data = read_config(CFG)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    else:
        if isinstance(data, dict):
            config_readable = True
            config_version = data.get("configVersion", 0)
    try:
        lifecycle = read_lifecycle_state(LIFECYCLE_STATE_FILE)
    except (OSError, ValueError, json.JSONDecodeError):
        lifecycle = None
    return build_diagnostics(
        LOG_FILE,
        app_version=get_version(),
        config_readable=config_readable,
        config_version=config_version,
        lifecycle=lifecycle,
    )


def activity_catalog(data):
    """Return current display labels without copying them into activity storage."""
    return [
        {
            "id": profile["id"],
            "name": profile.get("name", ""),
            "avatar": profile.get("avatar", ""),
            "tiles": [
                {
                    "id": tile["id"],
                    "label": tile.get("label", ""),
                    "emoji": tile.get("emoji", ""),
                }
                for tile in profile.get("tiles", [])
            ],
        }
        for profile in data.get("profiles", [])
    ]


def browser_wrapper_policy(data, query):
    """Bind one browser wrapper request to its configured embedded tile."""
    params = parse_qs(query, keep_blank_values=True, max_num_fields=8)
    tile_values = params.get("tile", [])
    url_values = params.get("url", [])
    if len(tile_values) != 1 or len(url_values) != 1:
        raise ValueError("Browser wrapper request is incomplete")
    tile_id = tile_values[0]
    requested_url = url_values[0]
    tile = next(
        (
            candidate
            for candidate in data.get("tiles", [])
            if candidate.get("id") == tile_id and candidate.get("visible", True)
        ),
        None,
    )
    if not tile:
        raise ValueError("Browser wrapper tile is unavailable")
    action = resolve_tile_action(tile)
    if (
        action.get("type") != "web"
        or action.get("mode") != "embedded"
        or action.get("url") != requested_url
    ):
        raise ValueError("Browser wrapper target does not match its tile")
    return embedded_browser_csp(allowed_frame_origins(tile, requested_url))


def _fetch_remote_json(url, timeout=5):
    return fetch_update_json(url, timeout=timeout)


def _fetch_remote_text(url, timeout=5):
    return fetch_update_text(url, timeout=timeout)


# Estado do atualizador automático deste projeto (beni/sistema/beni-atualizar).
AUTO_UPDATE_STATE = "/var/lib/beni-launcher/estado.json"
AUTO_UPDATE_TIMER = "/etc/systemd/system/beni-atualizar-verificar.timer"


def auto_update_status(state_file=AUTO_UPDATE_STATE, timer_file=AUTO_UPDATE_TIMER):
    """O que o atualizador automático já fez: versão baixada, última verificação, erro."""
    try:
        with open(state_file, encoding="utf-8") as handle:
            state = json.load(handle)
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    installed = get_version()
    staged = state.get("baixada") if isinstance(state.get("baixada"), str) else None
    latest = state.get("disponivel") if isinstance(state.get("disponivel"), str) else installed
    def text(key, limit=300):
        value = state.get(key)
        return value[:limit] if isinstance(value, str) else None
    return {
        "installedVersion": installed,
        "latestVersion": staged or latest,
        "source": "release",
        "updateAvailable": False,   # instala sozinho: sem botão "Atualizar agora"
        "autoUpdate": os.path.isfile(timer_file),
        "staged": staged,
        "forced": bool(state.get("forcada")) and bool(staged),
        "lastCheck": text("ultimaVerificacao", 40),
        "installedAt": text("instaladaEm", 40),
        "lastError": text("erro"),
        "notes": text("notas", 1000),
    }


def windows_update_status():
    """No Windows o atualizador é o atualizar_windows.py (estado em %LOCALAPPDATA%)."""
    import atualizar_windows

    estado = atualizar_windows.estado_para_os_pais(APP_ROOT)
    installed = get_version()
    return {
        "installedVersion": installed,
        "latestVersion": estado["baixada"] or installed,
        "source": "release",
        "updateAvailable": False,   # instala sozinho: sem botão "Atualizar agora"
        "autoUpdate": True,
        "staged": estado["baixada"],
        "forced": False,
        "lastCheck": estado["ultimaVerificacao"],
        "installedAt": None,
        "lastError": estado["erro"],
        "notes": None,
        "installHint": "Vai ser instalada quando o Benikids abrir de novo, ou quando o computador "
                       "ficar 20 minutos parado no menu.",
    }


def get_update_status(timeout=5):
    if os.name == "nt":
        return windows_update_status()
    return auto_update_status()


def legacy_update_status(timeout=5):
    return resolve_update_status(
        get_version(),
        LATEST_RELEASE_API,
        LEGACY_VERSION_URL,
        UPDATE_CHANNEL_FILE,
        timeout=timeout,
        fetch_json=_fetch_remote_json,
        fetch_text=_fetch_remote_text,
    )


_recommendations_cache = {"key": None, "recs": []}
_recommendations_lock = threading.Lock()


def _read_recommendations():
    """recommendations.json, relido só quando o arquivo muda."""
    try:
        info = os.stat(RECOMMENDATIONS_FILE)
    except OSError:
        return []
    key = (info.st_mtime_ns, info.st_size)
    with _recommendations_lock:
        if _recommendations_cache["key"] == key:
            return _recommendations_cache["recs"]
    try:
        with open(RECOMMENDATIONS_FILE, "r", encoding="utf-8") as fh:
            recs = json.load(fh)
    except Exception:
        return []
    if not isinstance(recs, list):
        recs = []
    with _recommendations_lock:
        _recommendations_cache.update(key=key, recs=recs)
    return recs


def load_recommendations(check_installed=True):
    """Recomendações com "installed". Com check_installed=False não procura os
    programas no PATH (dezenas de stat por chamada): load_stored_cfg roda a cada
    requisição do menu e só precisa dos comandos."""
    recs = _read_recommendations()
    if not check_installed:
        return recs
    if os.name == "nt":
        # Os comandos das recomendações são de Linux: no Windows o shutil.which
        # nunca acha nenhum, mas varre PATH x PATHEXT e levava ~1 s por abertura
        # da área dos pais num notebook de 2012, disputando CPU com o Edge.
        return [{**rec, "installed": rec.get("category") == "browser"} for rec in recs]
    result = []
    for rec in recs:
        all_cmds = []
        cmd = rec.get("cmd", [])
        # KDE wrapper detection: kstart/kstart5 are wrappers, not the app itself
        is_wrapper = cmd and cmd[0] in ("kstart", "kstart5")
        if is_wrapper:
            # Only check alt_cmds or the actual app name (skip wrapper and --fullscreen)
            for alt in rec.get("alt_cmds", []):
                all_cmds.append(alt)
            for part in cmd[2:]:
                if part and not part.startswith("-"):
                    all_cmds.append(part)
        else:
            if cmd:
                all_cmds.append(cmd[0])
            for alt in rec.get("alt_cmds", []):
                all_cmds.append(alt)
        installed = any(shutil.which(c) for c in all_cmds if c)
        if not installed and rec.get("category") == "browser":
            installed = True
        result.append({**rec, "installed": installed})
    return result


def find_browser(config=None):
    return detect_browser(
        config,
        candidates=BROWSER_CANDIDATES,
        which=None if os.name == "nt" else shutil.which,
    )


def comandos_desligar():
    if os.name == "nt":
        return [["shutdown", "/s", "/t", "0"]]
    return [cmd for cmd in (["systemctl", "poweroff"], ["loginctl", "poweroff"]) if shutil.which(cmd[0])]


def abridor_do_sistema():
    """Programa que abre arquivo/URL com o app padrão (xdg-open; explorer no Windows)."""
    if os.name == "nt":
        return "explorer.exe"
    return "xdg-open" if shutil.which("xdg-open") else None


def external_browser_command(browser, url, profile_id="", marionette_port=None, devtools_port=None):
    cache_root = os.path.join(HOME, ".cache", "cozy-kids-launcher")
    return build_external_browser_command(
        browser, url, cache_root, profile_id=profile_id,
        marionette_port=marionette_port, devtools_port=devtools_port,
    )


def site_login_driver(browser):
    """Como o login automático controla este navegador: Firefox pelo Marionette,
    Edge/Chrome pelo DevTools Protocol. None se não há navegador (o site abriria
    no programa padrão do sistema, sem controle)."""
    if not browser:
        return None
    return "devtools" if browser_family(browser) == "chromium" else "marionette"


def site_login_for_launch(browser, url, profile_id):
    """Login salvo para o site deste tile, ou None."""
    site = site_logins.site_for_url(url)
    if not site or not site_login_driver(browser):
        return None
    login = site_logins.get_login(SITE_LOGINS_FILE, profile_id, site)
    return (site, login) if login else None


def application_launcher():
    return ApplicationLauncher(
        TILE_PROCESS_PIDFILE,
        OVERLAY_PIDFILE,
        PROCESS_SUPERVISOR,
        OVERLAY_SCRIPT,
        activity_file=ACTIVITY_FILE,
        lock=_tile_launch_lock,
    )


def speech_feedback():
    global _speech_feedback
    with _speech_feedback_lock:
        if _speech_feedback is None:
            _speech_feedback = SpeechFeedback()
        return _speech_feedback


def embedded_activity_sessions():
    global _activity_sessions
    with _activity_sessions_lock:
        if _activity_sessions is None or _activity_sessions.path != os.fspath(ACTIVITY_FILE):
            _activity_sessions = EmbeddedActivitySessions(ACTIVITY_FILE)
        return _activity_sessions


def stop_existing_overlay():
    return application_launcher().stop_existing_overlay()


def stop_active_tile():
    return application_launcher().stop_active_tile()


def start_overlay(mode, url="", tile_id=""):
    return application_launcher().start_overlay(mode, url=url, tile_id=tile_id)


def reset_active_tile():
    embedded_activity_sessions().finish_all()
    application_launcher().reset_active_tile()
    usage_tracker().clear_active()


# --- Limites diários por categoria -------------------------------------
_usage_lock = threading.Lock()
_usage_tracker = None
_profiles_cache = {"mtime": None, "profiles": {}}


def stored_profiles_cached():
    """Perfis armazenados, relidos só quando o config.json muda (CPU fraca)."""
    try:
        mtime = os.stat(CFG).st_mtime_ns
    except OSError:
        return _profiles_cache["profiles"]
    if mtime != _profiles_cache["mtime"]:
        try:
            stored = load_stored_cfg()
            _profiles_cache["profiles"] = {
                p.get("id"): p for p in stored.get("profiles", []) if isinstance(p, dict)
            }
            _profiles_cache["mtime"] = mtime
        except (OSError, ValueError):
            pass
    return _profiles_cache["profiles"]


def _tile_alive():
    return owned_process_alive(TILE_PROCESS_PIDFILE, "tile-process", PROCESS_SUPERVISOR)


def _stop_tile_for_limit():
    log_runtime_event("usage.limit.enforced")
    embedded_activity_sessions().finish_all()
    application_launcher().reset_active_tile()


def iniciar_vigia_da_pilula():
    import plataforma_windows
    import vigia_da_pilula

    def registros():
        return (owned_process(TILE_PROCESS_PIDFILE, "tile-process", PROCESS_SUPERVISOR),
                owned_process(OVERLAY_PIDFILE, "overlay", OVERLAY_SCRIPT))

    def relatar(etapa, detalhe, assinatura):
        telemetria.relatar_problema(etapa, detalhe, assinatura, por_dia=True)

    def ao_fechar(tile):
        # roteiro 33: o app travado foi fechado pelo vigia; o menu avisa a criança
        avisar_app_travado(tile)
        usage_tracker().clear_active()
        menu = owned_process(BROWSER_PIDFILE, "browser")
        if menu:
            import janelas_seguras

            janelas_seguras.rodar_com_limite(plataforma_windows.ativar_processo, 1.0, menu["pid"], True)

    vigia = vigia_da_pilula.VigiaWindows(plataforma_windows, application_launcher, registros,
                                         uso=usage_tracker(), relatar=relatar, ao_fechar=ao_fechar)
    threading.Thread(target=vigia.rodar, args=(threading.Event(),), name="vigia-da-pilula",
                     daemon=True).start()


def usage_tracker():
    global _usage_tracker
    with _usage_lock:
        if _usage_tracker is None:
            _usage_tracker = UsageTracker(
                USAGE_FILE,
                stored_profiles_cached,
                _tile_alive,
                _stop_tile_for_limit,
            )
        return _usage_tracker


_controles = None
_controles_lock = threading.Lock()

# Menu nativo (beni-menu): as páginas web que ele abre (área dos pais, sites
# embutidos, biblioteca de mídia) avisam aqui quando voltariam para o menu.
_cliente_voltar = 0
_cliente_lock = threading.Lock()


def cliente_voltar_registrar():
    global _cliente_voltar
    with _cliente_lock:
        _cliente_voltar += 1
        return _cliente_voltar


def cliente_voltar_contador():
    with _cliente_lock:
        return _cliente_voltar


def menu_na_frente():
    """O controle só vira teclado do menu quando a janela do menu está na frente
    e nenhum app/site está aberto (jogos de navegador leem o controle sozinhos)."""
    browser = owned_process(BROWSER_PIDFILE, "browser")
    if not browser:
        return False
    if controles.janela_ativa_pid() != browser.get("pid"):
        return False
    try:
        return not usage_status(load_cfg()).get("active")
    except Exception:  # noqa: BLE001
        return False


def pid_da_janela_ativa():
    if os.name == "nt":
        try:
            import plataforma_windows
            return plataforma_windows.pid_da_janela_ativa()
        except Exception:  # noqa: BLE001
            return None
    return controles.janela_ativa_pid()


def pais_dos_processos():
    """{pid: pid do pai}."""
    if os.name == "nt":
        try:
            import plataforma_windows
            return plataforma_windows.processos()
        except Exception:  # noqa: BLE001
            return {}
    tabela = {}
    try:
        nomes = os.listdir("/proc")
    except OSError:
        return tabela
    for nome in nomes:
        if not nome.isdigit():
            continue
        try:
            with open(f"/proc/{nome}/stat", encoding="utf-8", errors="replace") as f:
                campos = f.read().rsplit(")", 1)[1].split()
            tabela[int(nome)] = int(campos[1])
        except (OSError, IndexError, ValueError):
            continue
    return tabela


def processo_descende_de(pid, ancestral, pais=None):
    """pid é o próprio ancestral ou um descendente dele (ex.: o navegador que o
    menu nativo abre para a área dos pais)."""
    if not pid or not ancestral:
        return False
    if pid == ancestral:
        return True
    pais = pais_dos_processos() if pais is None else pais
    vistos = set()
    while pid and pid not in vistos and len(vistos) < 64:
        vistos.add(pid)
        pid = pais.get(pid)
        if pid == ancestral:
            return True
    return False


# Menu registrado há pouco (abrindo): ainda sem janela na frente, conta como menu.
MENU_PARTIDA_SEGUNDOS = 15


def menu_cobre_a_tela(agora=None):
    """O menu está na frente e nenhum app/site está aberto: aí as telas do timer
    ("Acabou o tempo!", "Faltam N minutos") são as do próprio menu, e o
    timer_watchdog não mostra as dele (eram duas ao mesmo tempo, com o teclado
    indo para a de baixo). Com um app ou jogo na frente, quem cobre é o watchdog.
    - A área dos pais no navegador aberto pelo menu nativo conta como menu (o
      navegador é processo filho dele e não é um app; o adulto está lá).
    - Menu abrindo (registrado há menos de MENU_PARTIDA_SEGUNDOS) conta como
      menu: ao reabrir com o tempo esgotado, a rosa aparecia antes do menu."""
    browser = owned_process(BROWSER_PIDFILE, "browser")
    if not browser:
        return False
    if owned_process_alive(TILE_PROCESS_PIDFILE, "tile-process"):
        return False
    try:
        if usage_status(load_cfg()).get("active"):
            return False
    except Exception:  # noqa: BLE001
        return False
    agora = time.time() if agora is None else agora
    try:
        if agora - os.path.getmtime(BROWSER_PIDFILE) < MENU_PARTIDA_SEGUNDOS:
            return True
    except OSError:
        pass
    return processo_descende_de(pid_da_janela_ativa(), browser.get("pid"))


def fechar_app_pelo_controle():
    """Start + Select seguros: fecha o app aberto como o ✕ do overlay e mostra o menu."""
    if not owned_process_alive(TILE_PROCESS_PIDFILE, "tile-process"):
        return
    reset_active_tile()
    log_runtime_event("controles.app_closed")
    browser = owned_process(BROWSER_PIDFILE, "browser")
    if browser and shutil.which("xdotool"):
        subprocess.run(["xdotool", "search", "--pid", str(browser["pid"]), "windowactivate"],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5, check=False)


def controles_service():
    global _controles
    with _controles_lock:
        if _controles is None:
            _controles = controles.Controles(CONTROLES_FILE, HOME, pode_navegar=menu_na_frente,
                                             ao_sair=fechar_app_pelo_controle)
        return _controles


# Roteiro 33: o vigia fechou um app travado; o menu (nativo e web) mostra "O jogo travou
# e foi fechado." uma vez. Vai junto do /api/usage/status, que os dois já consultam a
# cada 5 s: {"seq": n, "tileId": ...} por 2 min; o menu guarda o último seq mostrado.
APP_TRAVADO_AVISO_S = 120
_app_travado_aviso = {"seq": 0, "tileId": "", "em": 0.0}
_app_travado_lock = threading.Lock()


def avisar_app_travado(tile_id, agora=None):
    with _app_travado_lock:
        _app_travado_aviso["seq"] += 1
        _app_travado_aviso["tileId"] = str(tile_id or "")
        _app_travado_aviso["em"] = time.monotonic() if agora is None else agora


def aviso_app_travado(agora=None):
    agora = time.monotonic() if agora is None else agora
    with _app_travado_lock:
        if not _app_travado_aviso["seq"] or agora - _app_travado_aviso["em"] > APP_TRAVADO_AVISO_S:
            return None
        return {"seq": _app_travado_aviso["seq"], "tileId": _app_travado_aviso["tileId"]}


def usage_status(cfg):
    profile_id = cfg.get("activeProfileId", "")
    profile = stored_profiles_cached().get(profile_id) or cfg
    payload = usage_tracker().status(profile_id, profile)
    aviso = aviso_app_travado()
    if aviso and isinstance(payload, dict):
        payload = dict(payload, appTravadoFechado=aviso)
    return payload


def tile_availability(cfg, tile_id, when=None):
    result = schedule_tile_availability(cfg, tile_id, when=when)
    if not result["allowed"]:
        return result
    reason = usage_status(cfg).get("blockedReasons", {}).get(tile_id)
    if reason:
        return {"allowed": False, "reason": reason}
    return result


def availability_summary(cfg, when=None):
    summary = schedule_availability_summary(cfg, when=when)
    usage = usage_status(cfg)
    blocked = list(summary.get("blockedTileIds", []))
    for tile_id in usage.get("blockedTileIds", []):
        if tile_id not in blocked:
            blocked.append(tile_id)
    summary["blockedTileIds"] = blocked
    summary["limitBlocked"] = usage.get("blockedReasons", {})
    return summary


APP_FECHOU_SOZINHO_SEGUNDOS = 2.0


def app_fechou_sozinho(supervisor, espera=None):
    """No Windows, o app que morre logo ao abrir (ex.: SuperTux com acento no nome do
    usuário) leva o supervisor junto: espera um pouco para o menu poder avisar, em vez
    de ficar parado sem resposta. No Linux nada muda."""
    if os.name != "nt" or supervisor is None or not hasattr(supervisor, "wait"):
        return False
    try:
        supervisor.wait(timeout=APP_FECHOU_SOZINHO_SEGUNDOS if espera is None else espera)
    except subprocess.TimeoutExpired:
        return False
    return True


def como_o_app_saiu(codigo):
    """(etapa da telemetria, código para o detalhe). No Windows o supervisor sai com o
    código do app; de 0xC0000000 para cima é um NTSTATUS de erro (0xC0000005: acesso
    inválido à memória), ou seja, o app CAIU: "app.caiu". Senão, "app.fechou_sozinho"."""
    if not isinstance(codigo, int):
        return "app.fechou_sozinho", "?"
    codigo &= 0xFFFFFFFF
    if codigo >= 0xC0000000:
        return "app.caiu", f"{codigo:#010X}".replace("0X", "0x")
    return "app.fechou_sozinho", str(codigo)


PORTAO_DE_ABERTURA = PortaoDeAbertura()


def launch_owned_tile(
    command,
    mode,
    url="",
    tile_id="",
    profile_id="",
    track_activity=False,
    path_extra="",
    env_extra=None,
):
    process = application_launcher().launch_owned_tile(
        command,
        mode,
        url=url,
        tile_id=tile_id,
        profile_id=profile_id,
        track_activity=track_activity,
        path_extra=path_extra,
        env_extra=env_extra,
    )
    PORTAO_DE_ABERTURA.abriu_app()
    profile = stored_profiles_cached().get(profile_id) or {}
    usage_tracker().set_active(
        profile_id,
        tile_id,
        usage_tile_category(profile, tile_id),
    )
    return process


def load_timer():
    return read_timer_state(TIMER_FILE)


def save_timer(data):
    write_timer_state(TIMER_FILE, data)


def clear_timer():
    remove_timer_state(TIMER_FILE)


def timer_status(cfg):
    return calculate_timer_status(load_timer(), cfg, now=time.time())


# Primeira configuração (configurar.html): crianças (nome + menino/menina) e o
# PIN dos pais. Só vale enquanto setupCompleted é false e ainda não há PIN.
# Tema inicial: o da marca (Benikids) para todos; os pais trocam em Pais > Aparência.
SETUP_ICONES = {
    "menino": {"avatar": "👦", "theme": "benikids"},
    "menina": {"avatar": "👧", "theme": "benikids"},
}
SETUP_MAX_CRIANCAS = 8


def first_setup_config(stored, children, pin, start_on_login=True, telemetry=True, usage_telemetry=False):
    """Perfis novos a partir do perfil-modelo (tiles, limites, horários) + PIN."""
    if stored.get("setupCompleted") is not False or stored.get("pinHash"):
        raise PermissionError("Setup already completed")
    if not isinstance(children, list) or not 1 <= len(children) <= SETUP_MAX_CRIANCAS:
        raise ValueError(f"Informe de 1 a {SETUP_MAX_CRIANCAS} crianças")
    modelo = active_profile(stored)
    perfis = []
    for indice, crianca in enumerate(children):
        if not isinstance(crianca, dict):
            raise ValueError("Criança inválida")
        nome = " ".join(str(crianca.get("name", "")).split())[:40]
        icone = SETUP_ICONES.get(crianca.get("icon"))
        if not nome:
            raise ValueError("Digite o nome de cada criança")
        if icone is None:
            raise ValueError("Escolha menino ou menina")
        nascimento = crianca.get("birthMonth")
        if nascimento is not None and (
            not isinstance(nascimento, str) or not re.fullmatch(r"(19|20)\d\d-(0[1-9]|1[0-2])", nascimento)
        ):
            raise ValueError("Mês/ano de nascimento inválido")
        perfil = json.loads(json.dumps(modelo))
        perfil["id"] = modelo["id"] if indice == 0 else f"child-{os.urandom(6).hex()}"
        perfil.update(
            name=nome,
            avatar=icone["avatar"],
            title=f"Oi, {nome}!",
            theme=icone["theme"],
            currentPage=0,
            favorites=[],
            gender=crianca.get("icon"),
            telemetryId=os.urandom(16).hex(),
        )
        # Menina recebe os jogos de vestir/maquiagem. Menino não fica com os
        # que vieram copiados do perfil-modelo. Sem gender a configuração nem chega aqui.
        import jogos_genero
        jogos_genero.retirar_de_outros_generos(perfil)
        jogos_genero.aplicar_perfil(
            perfil,
            "windows" if os.name == "nt" else "linux",
            porta=PORT,
        )
        if nascimento:
            perfil["birthMonth"] = nascimento
        else:
            perfil.pop("birthMonth", None)
        perfis.append(perfil)
    resultado = json.loads(json.dumps(stored))
    resultado["profiles"] = perfis
    resultado["activeProfileId"] = perfis[0]["id"]
    resultado["pinHash"] = hash_pin(pin if isinstance(pin, str) else "")
    resultado["setupCompleted"] = True
    resultado["startOnLogin"] = start_on_login is not False
    resultado["telemetryEnabled"] = telemetry is not False
    resultado["usageTelemetryEnabled"] = usage_telemetry is True
    return resultado


# o menu nativo fala com o servidor sem User-Agent; os navegadores sempre mandam um
_ULTIMO_PEDIDO_NATIVO = [0.0]


def anotar_cliente(user_agent):
    if not user_agent:
        _ULTIMO_PEDIDO_NATIVO[0] = time.time()


def tipo_de_menu():
    return "nativo" if time.time() - _ULTIMO_PEDIDO_NATIVO[0] < 24 * 3600 else "web"


_TELEMETRIA = []


def telemetria_service():
    if not _TELEMETRIA:
        _TELEMETRIA.append(telemetria.Telemetria(
            TELEMETRIA_FILE, load_stored_cfg, get_version, tipo_de_menu,
            ler_historico=lambda: load_usage(USAGE_FILE).get("history", {}),
        ))
    return _TELEMETRIA[0]


# Quanto um pedido da página escondida espera pelo PIN antes de voltar vazio.
PAIS_ESPERA_POR_PEDIDO = 20.0


class Handler(http.server.SimpleHTTPRequestHandler):
    server_version = "CozyKidsLauncher"
    sys_version = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=APP_ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        browser_csp = getattr(self, "browser_content_security_policy", "")
        if browser_csp:
            self.send_header("Content-Security-Policy", browser_csp)
        super().end_headers()

    def json_response(self, payload, status=200, headers=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def media_cover_response(self, item):
        path = item.get("coverPath", "") if item else ""
        content_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        content_type = content_types.get(os.path.splitext(path)[1].casefold())
        if not content_type:
            self.send_error(404)
            return
        try:
            with open(path, "rb") as cover_file:
                payload = cover_file.read(MAX_MEDIA_COVER_BYTES + 1)
        except OSError:
            self.send_error(404)
            return
        if len(payload) > MAX_MEDIA_COVER_BYTES:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def read_json_body(self, required=True):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.json_response({"status": "error", "message": "Invalid Content-Length"}, 400)
            return None
        if length < 0 or length > MAX_JSON_BODY_BYTES:
            self.json_response({"status": "error", "message": "Request body is too large"}, 413)
            return None
        if length == 0:
            if required:
                self.json_response({"status": "error", "message": "JSON body required"}, 400)
                return None
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.json_response({"status": "error", "message": "Invalid JSON"}, 400)
            return None
        if not isinstance(data, dict):
            self.json_response({"status": "error", "message": "JSON body must be an object"}, 400)
            return None
        return data

    def request_has_local_origin(self):
        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            parsed = urlparse(origin)
            expected_port = self.server.server_address[1]
            actual_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            return (
                parsed.scheme == "http"
                and parsed.hostname in ("127.0.0.1", "localhost", "::1")
                and actual_port == expected_port
            )
        except ValueError:
            return False

    def has_admin_access(self, cfg=None):
        cfg = load_cfg() if cfg is None else cfg
        if not cfg.get("pinHash", ""):
            return True
        return valid_admin_session(self.headers.get("Cookie", ""))

    def require_admin(self, cfg=None):
        if self.has_admin_access(cfg):
            return True
        self.json_response({"status": "error", "message": "Parent authentication required"}, 403)
        return False

    def pedido_do_proprio_computador(self):
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def area_dos_pais_nativa(self, passo):
        """Área dos pais pelo menu nativo (PIN no menu, navegador já aberto e
        escondido). Ver o fluxo em parent_auth.criar_espera. Nada daqui vai para
        o log: nem o id da espera, nem o token, nem o PIN."""
        if not self.pedido_do_proprio_computador():
            self.json_response({"status": "error", "message": "Local requests only"}, 403)
            return
        data = self.read_json_body(required=passo != "preparar")
        if data is None:
            return
        if passo == "preparar":
            if not load_cfg().get("pinHash", ""):
                self.json_response({"espera": None, "pinConfigured": False})
                return
            self.json_response({"espera": criar_espera(), "pinConfigured": True})
            return
        if passo == "liberar":
            if pin_attempt_blocked():
                log_runtime_event("auth.throttled", level="warning")
                self.json_response({"valid": False, "message": "Too many attempts"}, 429)
                return
            cfg = load_cfg()
            pin_hash = cfg.get("pinHash", "")
            pin = data.get("pin", "")
            if pin_hash and (not isinstance(pin, str) or not verify_pin(pin_hash, pin)):
                record_pin_failure()
                log_runtime_event("auth.failed", level="warning")
                self.json_response({"valid": False}, 403)
                return
            clear_pin_failures()
            if pin_hash and is_legacy_pin_hash(pin_hash):
                cfg["pinHash"] = hash_pin(pin)
                save_cfg(cfg)
            entregue = liberar_espera(data.get("espera"))
            log_runtime_event("auth.succeeded")
            self.json_response({"valid": True, "entregue": entregue})
            return
        if passo == "espera":
            # a página escondida fica aqui até o PIN (long polling: um pedido por vez)
            estado, token = aguardar_espera(data.get("espera"), PAIS_ESPERA_POR_PEDIDO)
            if estado == "ocupada":
                # outro pedido já espera nesta espera: só a página do menu devia estar aqui
                log_runtime_event("pais.espera_ocupada", level="warning")
                self.json_response({"estado": estado}, 409)
                return
            resposta = {"estado": estado}
            if token:
                resposta["token"] = token
            self.json_response(resposta, 404 if estado == "desconhecida" else 200)
            return
        if passo == "entrar":
            if not trocar_token_pais(data.get("token")):
                log_runtime_event("auth.failed", level="warning")
                self.json_response({"status": "error"}, 403)
                return
            sessao = create_admin_session()
            self.json_response({"status": "ok"}, headers={"Set-Cookie": self.admin_cookie(sessao)})
            return
        if passo == "cancelar":
            self.json_response({"status": "ok" if cancelar_espera(data.get("espera")) else "ignored"})
            return
        self.json_response({"status": "error", "message": "Unknown action"}, 404)

    @staticmethod
    def admin_cookie(token):
        return admin_session_cookie(token)

    def do_GET(self):
        request_url = urlparse(self.path)
        if request_url.path.startswith("/api/"):
            anotar_cliente(self.headers.get("User-Agent", ""))
        if request_url.path == "/api/telemetria/previa":
            if not self.require_admin():
                return
            servico = telemetria_service()
            return self.json_response({"computador": servico.previa(), "uso_das_criancas": servico.previa_uso()})
        if request_url.path in ("/", "/index.html"):
            try:
                cfg = load_cfg()
            except Exception:
                cfg = {}
            try:
                body = themed_index_html(cfg)
            except OSError:
                return super().do_GET()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if request_url.path == "/browser.html":
            try:
                self.browser_content_security_policy = browser_wrapper_policy(
                    load_cfg(),
                    request_url.query,
                )
            except ValueError:
                self.send_error(404)
                return
            return super().do_GET()
        if request_url.path == "/api/media":
            entries, truncated = media_catalog()
            cfg = load_cfg()
            try:
                state = media_state_payload(
                    MEDIA_STATE_FILE,
                    cfg.get("activeProfileId", ""),
                    available_ids=[entry["id"] for entry in entries],
                )
            except (OSError, ValueError):
                state = {"favoriteIds": [], "recentIds": []}
            return self.json_response({
                "items": public_media_catalog(entries),
                "truncated": truncated,
                **state,
            })
        if request_url.path == "/api/media/cover":
            query = parse_qs(request_url.query, keep_blank_values=True)
            media_ids = query.get("id", [])
            if len(media_ids) != 1 or len(query) != 1:
                self.send_error(404)
                return
            entries, _ = media_catalog()
            return self.media_cover_response(catalog_item(entries, media_ids[0]))
        if self.path == "/api/config":
            return self.json_response(public_config(load_cfg()))
        if self.path == "/api/profiles":
            data = load_stored_cfg()
            if not self.require_admin(active_config(data)):
                return
            return self.json_response({
                "activeProfileId": data["activeProfileId"],
                "profiles": profile_summaries(data),
            })
        if self.path == "/api/apps":
            return self.json_response(scan_apps())
        if self.path == "/api/recommendations":
            return self.json_response(load_recommendations())
        if self.path == "/api/version":
            return self.json_response({"version": get_version()})
        if self.path == "/api/update/status":
            try:
                status = get_update_status()
            except RuntimeError as exc:
                log_runtime_event(
                    "update.failed",
                    level="warning",
                    exceptionType=type(exc).__name__,
                )
                return self.json_response({"status": "error", "message": str(exc)}, 503)
            log_runtime_event(
                "update.checked",
                source=status["source"],
                updateAvailable=status["updateAvailable"],
                version=status["latestVersion"],
            )
            return self.json_response(status)
        if self.path == "/api/features":
            shutdown_ok = bool(comandos_desligar())
            return self.json_response({
                "shutdownAvailable": shutdown_ok,
                "speechFeedbackAvailable": speech_feedback().available(),
                "catalogInstallAvailable": os.name == "nt",
            })
        if self.path == "/api/browsers":
            return self.json_response(
                browser_statuses(BROWSER_CANDIDATES, which=None if os.name == "nt" else shutil.which)
            )
        if self.path == "/api/cliente/estado":
            # Menu nativo (beni-menu): quantas vezes uma página aberta por ele pediu
            # para voltar ao menu (ele fecha o navegador quando o número muda).
            return self.json_response({"voltar": cliente_voltar_contador()})
        if self.path == "/api/timer/tela":
            # timer_watchdog: quem mostra o "Acabou o tempo!" (o menu ou ele)
            return self.json_response({"menuNaFrente": menu_cobre_a_tela()})
        if self.path == "/api/timer/status":
            return self.json_response(timer_status(load_cfg()))
        if self.path == "/api/availability/status":
            return self.json_response(availability_summary(load_cfg()))
        if request_url.path == "/api/usage/status":
            cfg = load_cfg()
            # O overlay informa o tile aberto; isso permite retomar a contagem
            # se o servidor reiniciar com um app ainda aberto.
            tile_id = parse_qs(request_url.query).get("tile", [""])[0]
            if tile_id and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", tile_id):
                usage_tracker().adopt(
                    cfg.get("activeProfileId", ""),
                    tile_id,
                    usage_tile_category(
                        stored_profiles_cached().get(cfg.get("activeProfileId", "")) or cfg,
                        tile_id,
                    ),
                    _tile_alive,
                )
            return self.json_response(usage_status(cfg))
        if self.path == "/api/activity":
            stored = load_stored_cfg()
            data = active_config(stored)
            if not self.require_admin(data):
                return
            payload = activity_payload(ACTIVITY_FILE)
            payload["enabled"] = bool(data.get("activityTrackingEnabled", False))
            payload["profiles"] = activity_catalog(stored)
            return self.json_response(payload)
        if self.path == "/api/activity/export":
            data = load_cfg()
            if not self.require_admin(data):
                return
            activity = activity_payload(ACTIVITY_FILE)
            payload = json.dumps({
                "activityVersion": ACTIVITY_VERSION,
                "exportedAt": int(time.time()),
                "records": list(reversed(activity["records"])),
            }, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header(
                "Content-Disposition",
                'attachment; filename="cozy-kids-activity.json"',
            )
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/api/backups":
            data = load_cfg()
            if not self.require_admin(data):
                return
            return self.json_response({"backups": available_config_backups()})
        if request_url.path in ("/api/controles", "/api/controles/captura"):
            if not self.require_admin():
                return
            servico = controles_service()
            if request_url.path == "/api/controles":
                return self.json_response(servico.estado())
            try:
                depois = int(parse_qs(request_url.query).get("depois", ["0"])[0])
            except ValueError:
                depois = 0
            return self.json_response({"captura": servico.ultima_captura(depois)})
        if request_url.path == "/api/site-logins":
            data = load_stored_cfg()
            if not self.require_admin(active_config(data)):
                return
            profile_id = data.get("activeProfileId", "")
            return self.json_response({
                "profileId": profile_id,
                # sem navegador compatível o login salvo não teria efeito: a tela avisa
                "available": site_login_driver(find_browser(active_config(data))) is not None,
                "sites": site_logins.public_logins(SITE_LOGINS_FILE, profile_id),
            })
        if self.path == "/api/export-config":
            data = load_stored_cfg()
            if not self.require_admin(active_config(data)):
                return
            payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="cozy-kids-config.json"')
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/api/diagnostics":
            data = load_cfg()
            if not self.require_admin(data):
                return
            payload = json.dumps(
                diagnostics_payload(),
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header(
                "Content-Disposition",
                'attachment; filename="cozy-kids-diagnostics.json"',
            )
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            log_runtime_event("diagnostics.exported")
            return
        return super().do_GET()

    def do_POST(self):
        if not self.request_has_local_origin():
            log_runtime_event("request.rejected", level="warning", statusCode=403)
            self.json_response({"status": "error", "message": "Cross-site request rejected"}, 403)
            return
        action = self.path.strip("/")
        if action == "api/cliente/voltar":
            self.json_response({"voltar": cliente_voltar_registrar()})
            return
        if action == "api/cliente/evento":
            # A página aberta pelo menu nativo achou a tela vazia e se recuperou
            # (diagnóstico para os testes; só valores da lista de etapas).
            body = self.read_json_body()
            if body is None:
                return
            etapa = body.get("etapa") if isinstance(body, dict) else None
            detalhes = {"etapa": etapa}
            erro = body.get("erro") if isinstance(body, dict) else None
            if isinstance(erro, str) and erro.strip():
                detalhes["erro"] = erro[:600]
            ok = isinstance(etapa, str) and log_runtime_event("cliente.recuperado", level="warning", **detalhes)
            self.json_response({"status": "ok" if ok else "ignored"})
            return
        if action == "api/feedback/speak":
            body = self.read_json_body()
            if body is None:
                return
            if set(body) != {"tileId"}:
                self.json_response(
                    {"status": "error", "message": "Only a tile identifier is accepted"},
                    400,
                )
                return
            cfg = load_cfg()
            if cfg.get("speechFeedbackEnabled") is not True:
                self.json_response({"status": "disabled"})
                return
            tile = configured_feedback_tile(cfg, body.get("tileId"))
            if tile is None:
                self.send_response(404)
                self.end_headers()
                return
            try:
                status = speech_feedback().speak(
                    tile.get("label", ""),
                    cfg.get("language", "en"),
                )
            except ValueError:
                self.json_response(
                    {"status": "error", "message": "Tile label cannot be spoken"},
                    400,
                )
                return
            self.json_response({"status": status})
            return
        if action == "api/media/favorite":
            body = self.read_json_body()
            if body is None:
                return
            cfg = load_cfg()
            tile_id = body.get("tileId")
            if not configured_media_tile(cfg, tile_id):
                self.send_response(404)
                self.end_headers()
                return
            availability = tile_availability(cfg, tile_id)
            if not availability["allowed"]:
                self.json_response({
                    "status": "blocked",
                    "reason": availability["reason"],
                }, 403)
                return
            entries, _ = media_catalog()
            item = catalog_item(entries, body.get("mediaId"))
            if not item:
                self.send_response(404)
                self.end_headers()
                return
            try:
                favorite = set_media_favorite(
                    MEDIA_STATE_FILE,
                    cfg.get("activeProfileId", ""),
                    item["id"],
                    body.get("favorite"),
                )
            except ValueError as exc:
                self.json_response({"status": "error", "message": str(exc)}, 400)
                return
            except OSError:
                self.json_response(
                    {"status": "error", "message": "Media favorite could not be saved"},
                    503,
                )
                return
            self.json_response({"status": "ok", "favorite": favorite})
            return
        if action == "api/media/play":
            body = self.read_json_body()
            if body is None:
                return
            cfg = load_cfg()
            tile_id = body.get("tileId")
            if not configured_media_tile(cfg, tile_id):
                self.send_response(404)
                self.end_headers()
                return
            availability = tile_availability(cfg, tile_id)
            if not availability["allowed"]:
                self.json_response({
                    "status": "blocked",
                    "reason": availability["reason"],
                }, 403)
                return
            entries, _ = media_catalog()
            item = catalog_item(entries, body.get("mediaId"))
            if not item:
                self.send_response(404)
                self.end_headers()
                return
            player = find_media_player(INDIVIDUAL_MEDIA_PLAYER_CANDIDATES)
            if player:
                resume_directory = None
                profile_id = cfg.get("activeProfileId", "")
                if player in ("mpv", "vlc"):
                    try:
                        resume_directory = prepare_profile_resume_directory(
                            MEDIA_RESUME_ROOT,
                            profile_id,
                        )
                    except (OSError, ValueError):
                        log_runtime_event(
                            "media.resume.unavailable",
                            level="warning",
                            actionType="media",
                        )
                command = media_player_command(
                    player,
                    [item["path"]],
                    resume_directory=resume_directory,
                )
                if (
                    player == "vlc"
                    and resume_directory
                    and os.path.isfile(MEDIA_SESSION_SCRIPT)
                ):
                    command = [
                        sys.executable,
                        MEDIA_SESSION_SCRIPT,
                        "--resume-root",
                        MEDIA_RESUME_ROOT,
                        "--profile-id",
                        profile_id,
                        "--media-id",
                        item["id"],
                        "--media-path",
                        item["path"],
                        "--",
                        *command,
                    ]
            elif abridor_do_sistema():
                command = [abridor_do_sistema(), item["path"]]
            else:
                log_runtime_event(
                    "launch.failed",
                    level="warning",
                    actionType="media",
                    result="missing",
                )
                self.json_response(
                    {"status": "error", "message": "No supported media player found"},
                    503,
                )
                return
            log_runtime_event("launch.started", actionType="media")
            try:
                launch_owned_tile(
                    command,
                    "local",
                    tile_id=tile_id,
                    profile_id=cfg.get("activeProfileId", ""),
                    track_activity=cfg.get("activityTrackingEnabled", False),
                )
            except OSError:
                log_runtime_event(
                    "launch.failed",
                    level="warning",
                    actionType="media",
                    result="failure",
                )
                self.json_response(
                    {"status": "error", "message": "Media process could not be started"},
                    503,
                )
                return
            try:
                record_media_play(
                    MEDIA_STATE_FILE,
                    cfg.get("activeProfileId", ""),
                    item["id"],
                )
            except (OSError, ValueError):
                pass
            self.send_response(204)
            self.end_headers()
            return
        if action == "api/activity/finish":
            body = self.read_json_body()
            if body is None:
                return
            embedded_activity_sessions().finish(body.get("token"))
            self.send_response(204)
            self.end_headers()
            return
        if action == "api/activity/clear":
            cfg = load_cfg()
            if not self.require_admin(cfg):
                return
            body = self.read_json_body(required=False)
            if body is None:
                return
            try:
                embedded_activity_sessions().discard_all()
            except OSError:
                self.json_response(
                    {"status": "error", "message": "Activity data could not be removed"},
                    500,
                )
                return
            self.json_response({"status": "ok"})
            return
        if action == "api/profiles/create":
            stored = load_stored_cfg()
            if not self.require_admin(active_config(stored)):
                return
            body = self.read_json_body()
            if body is None:
                return
            try:
                stored, profile_id = add_profile(
                    stored,
                    body.get("name"),
                    body.get("avatar", ""),
                )
                stored = save_stored_cfg(stored)
            except (OSError, ValueError) as exc:
                self.json_response({"status": "error", "message": str(exc)}, 400)
                return
            log_runtime_event("profile.created")
            self.json_response({
                "status": "ok",
                "profileId": profile_id,
                "activeProfileId": stored["activeProfileId"],
                "profiles": profile_summaries(stored),
            })
            return
        if action == "api/profiles/select":
            stored = load_stored_cfg()
            if not self.require_admin(active_config(stored)):
                return
            body = self.read_json_body()
            if body is None:
                return
            try:
                stored = select_profile(stored, body.get("profileId"))
                stored = save_stored_cfg(stored)
                clear_timer()
            except (OSError, ValueError) as exc:
                self.json_response({"status": "error", "message": str(exc)}, 400)
                return
            log_runtime_event("profile.selected")
            self.json_response({
                "status": "ok",
                "config": public_config(active_config(stored)),
            })
            return
        if action == "api/profiles/delete":
            stored = load_stored_cfg()
            if not self.require_admin(active_config(stored)):
                return
            body = self.read_json_body()
            if body is None:
                return
            try:
                stored = remove_profile(stored, body.get("profileId"))
                remove_profile_activity(ACTIVITY_FILE, body.get("profileId"))
                remove_profile_media_state(MEDIA_STATE_FILE, body.get("profileId"))
                remove_profile_resume_directory(
                    MEDIA_RESUME_ROOT,
                    body.get("profileId"),
                )
                stored = save_stored_cfg(stored)
            except (OSError, ValueError) as exc:
                self.json_response({"status": "error", "message": str(exc)}, 400)
                return
            log_runtime_event("profile.removed")
            self.json_response({
                "status": "ok",
                "activeProfileId": stored["activeProfileId"],
                "profiles": profile_summaries(stored),
            })
            return
        if action == "api/save-config":
            cfg = load_cfg()
            if not self.require_admin(cfg):
                return
            data = self.read_json_body()
            if data is None:
                return
            try:
                data = validate_config(data, existing_pin_hash=cfg.get("pinHash", ""))
                data = save_cfg(data)
            except (OSError, ValueError) as exc:
                self.json_response({"status": "error", "message": str(exc)}, 400)
                return
            write_browser_override(data)
            inicio_automatico.aplicar(data, APP_ROOT, AUTOSTART_DESKTOP)
            log_runtime_event(
                "config.saved",
                configVersion=data.get("configVersion", CURRENT_CONFIG_VERSION),
            )
            self.json_response({"status": "ok", "config": public_config(data)})
            return
        if action == "api/catalogo/instalar":
            # Windows: instala os apps do catálogo que faltam (janela com o andamento)
            if not self.require_admin():
                return
            if os.name != "nt":
                self.json_response({"status": "error", "message": "Windows only"}, 404)
                return
            try:
                # fora do job da sessão: a instalação continua se os pais saírem do Benikids
                from queda_windows import popen_fora_do_job

                popen_fora_do_job(
                    [sys.executable, os.path.join(APP_ROOT, "instalar_apps.py")],
                    cwd=APP_ROOT, close_fds=True,
                )
            except OSError as exc:
                self.json_response({"status": "error", "message": str(exc)}, 503)
                return
            self.json_response({"status": "ok"})
            return
        if action == "api/telemetria/apagar":
            if not self.require_admin():
                return
            ok = telemetria_service().apagar_dados_enviados(load_stored_cfg())
            log_runtime_event("telemetria.apagar", result="ok" if ok else "failed")
            self.json_response({"status": "ok" if ok else "error"}, 200 if ok else 503)
            return
        if action == "api/setup":
            body = self.read_json_body()
            if body is None:
                return
            try:
                stored = first_setup_config(
                    load_stored_cfg(), body.get("children"), body.get("pin", ""),
                    body.get("startOnLogin", True),
                    body.get("telemetry", True),
                    body.get("usageTelemetry", False),
                )
                stored = save_stored_cfg(stored)
                clear_timer()
                inicio_automatico.aplicar(stored, APP_ROOT, AUTOSTART_DESKTOP)
            except PermissionError:
                self.json_response({"status": "error", "message": "Setup already completed"}, 403)
                return
            except (OSError, ValueError) as exc:
                self.json_response({"status": "error", "message": str(exc)}, 400)
                return
            clear_admin_sessions()
            log_runtime_event("setup.completed", profiles=len(stored["profiles"]))
            self.json_response({"status": "ok", "profiles": profile_summaries(stored)})
            return
        if action == "api/verify-pin":
            if pin_attempt_blocked():
                log_runtime_event("auth.throttled", level="warning")
                self.json_response({"valid": False, "message": "Too many attempts"}, 429)
                return
            data = self.read_json_body()
            if data is None:
                return
            cfg = load_cfg()
            pin_hash = cfg.get("pinHash", "")
            if not pin_hash:
                log_runtime_event("auth.succeeded")
                self.json_response({"valid": True, "pinConfigured": False})
                return
            pin = data.get("pin", "")
            if not isinstance(pin, str) or not verify_pin(pin_hash, pin):
                record_pin_failure()
                log_runtime_event("auth.failed", level="warning")
                self.json_response({"valid": False}, 403)
                return
            clear_pin_failures()
            if is_legacy_pin_hash(pin_hash):
                cfg["pinHash"] = hash_pin(pin)
                save_cfg(cfg)
            token = create_admin_session()
            log_runtime_event("auth.succeeded")
            self.json_response(
                {"valid": True, "pinConfigured": True},
                headers={"Set-Cookie": self.admin_cookie(token)},
            )
            return
        if action.startswith("api/pais/"):
            self.area_dos_pais_nativa(action[len("api/pais/"):])
            return
        if action == "api/pin/set":
            cfg = load_cfg()
            if not self.require_admin(cfg):
                return
            data = self.read_json_body()
            if data is None:
                return
            try:
                cfg["pinHash"] = hash_pin(data.get("pin", ""))
                save_cfg(cfg)
            except (OSError, ValueError) as exc:
                self.json_response({"status": "error", "message": str(exc)}, 400)
                return
            clear_admin_sessions()
            token = create_admin_session()
            log_runtime_event("pin.changed")
            self.json_response(
                {"status": "ok", "pinConfigured": True},
                headers={"Set-Cookie": self.admin_cookie(token)},
            )
            return
        if action == "api/pin/remove":
            cfg = load_cfg()
            if not self.require_admin(cfg):
                return
            cfg["pinHash"] = ""
            save_cfg(cfg)
            clear_admin_sessions()
            log_runtime_event("pin.removed")
            self.json_response(
                {"status": "ok", "pinConfigured": False},
                headers={"Set-Cookie": expired_admin_session_cookie()},
            )
            return
        if action == "api/import-config":
            stored = load_stored_cfg()
            cfg = active_config(stored)
            if not self.require_admin(cfg):
                return
            data = self.read_json_body()
            if data is None:
                return
            try:
                imported = validate_stored_config(
                    data,
                    existing_pin_hash=cfg.get("pinHash", ""),
                    allow_pin_hash="pinHash" in data,
                )
                imported = save_stored_cfg(imported)
                write_browser_override(active_config(imported))
            except (OSError, ValueError) as exc:
                self.json_response({"status": "error", "message": str(exc)}, 400)
                return
            if imported.get("pinHash", "") != cfg.get("pinHash", ""):
                clear_admin_sessions()
            log_runtime_event(
                "config.imported",
                configVersion=imported.get("configVersion", CURRENT_CONFIG_VERSION),
            )
            self.json_response({"status": "ok"})
            return
        if action == "api/backups/restore":
            cfg = load_cfg()
            if not self.require_admin(cfg):
                return
            data = self.read_json_body()
            if data is None:
                return
            backup_id = data.get("backupId")
            if not isinstance(backup_id, str):
                self.json_response(
                    {"status": "error", "message": "Invalid backup identifier"},
                    400,
                )
                return
            try:
                restored, safety_backup = restore_config_backup(backup_id)
            except FileNotFoundError as exc:
                self.json_response(
                    {"status": "error", "message": str(exc)},
                    404,
                )
                return
            except ValueError as exc:
                self.json_response(
                    {"status": "error", "message": str(exc)},
                    400,
                )
                return
            except OSError:
                self.json_response(
                    {"status": "error", "message": "Backup could not be restored"},
                    500,
                )
                return
            self.json_response({
                "status": "ok",
                "config": public_config(restored),
                "safetyBackupId": safety_backup["id"],
            })
            return
        if action.startswith("api/controles/"):
            if not self.require_admin():
                return
            body = self.read_json_body()
            if body is None:
                return
            servico = controles_service()
            try:
                if action == "api/controles/captura":
                    if body.get("acao") == "iniciar":
                        servico.iniciar_captura()
                    else:
                        servico.parar_captura()
                elif action == "api/controles/salvar":
                    servico.salvar(body.get("chave"), body.get("nome"), body.get("mapa"))
                    log_runtime_event("controles.saved")
                elif action == "api/controles/esquecer":
                    servico.esquecer(body.get("chave"))
                elif action == "api/controles/navegacao":
                    servico.definir_navegacao(body.get("ligada") is True)
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
            except ValueError as exc:
                self.json_response({"status": "error", "message": str(exc)}, 400)
                return
            except OSError as exc:
                self.json_response({"status": "error", "message": type(exc).__name__}, 500)
                return
            self.json_response({"status": "ok", **servico.estado()})
            return
        if action == "api/site-logins":
            data = load_stored_cfg()
            if not self.require_admin(active_config(data)):
                return
            body = self.read_json_body()
            if body is None:
                return
            profile_id = data.get("activeProfileId", "")
            try:
                if set(body).difference(("site", "username", "password", "remove")):
                    raise ValueError("unsupported fields")
                site_logins.update_login(
                    SITE_LOGINS_FILE,
                    profile_id,
                    body.get("site"),
                    username=body.get("username"),
                    password=body.get("password") or None,
                    remove=body.get("remove") is True,
                )
            except ValueError as exc:
                self.json_response({"status": "error", "message": str(exc)}, 400)
                return
            log_runtime_event("site_login.saved")
            self.json_response({
                "status": "ok",
                "sites": site_logins.public_logins(SITE_LOGINS_FILE, profile_id),
            })
            return
        if action == "shutdown":
            if not self.require_admin():
                return
            shutdown_ok = False
            try:
                write_lifecycle_request(LIFECYCLE_REQUEST_FILE, "shutdown")
            except (OSError, ValueError):
                pass
            for cmd in comandos_desligar():
                try:
                    if os.name == "nt":  # sem janela de console
                        subprocess.Popen(cmd, env=dict(os.environ), creationflags=0x08000000)
                    else:
                        subprocess.Popen(cmd, env=dict(os.environ))
                    shutdown_ok = True
                    break
                except Exception:
                    pass
            if not shutdown_ok:
                try:
                    clear_lifecycle_request(LIFECYCLE_REQUEST_FILE)
                except OSError:
                    pass
            self.json_response({"status": "ok" if shutdown_ok else "error"})
            return
        if action == "exit-kids":
            if not self.require_admin():
                return
            reset_active_tile()
            # Sair com PIN encerra o timer da sessão: senão o Benikids reabria já com
            # "Acabou o tempo!" (roteiro 25). Uma queda ou reinício não passam por aqui,
            # e aí o timer continua valendo.
            try:
                clear_timer()
            except OSError:
                pass
            # Signal launcher.sh to exit its while-true loop
            try:
                write_lifecycle_request(LIFECYCLE_REQUEST_FILE, "parent-exit")
            except (OSError, ValueError):
                pass
            try:
                with open(EXIT_FLAGFILE, "w", encoding="utf-8") as f:
                    f.write("1")
            except OSError:
                pass
            terminate_owned_process(BROWSER_PIDFILE, "browser")
            self.send_response(204)
            self.end_headers()
            # Shutdown the HTTP server so launcher.sh exits cleanly
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if action == "api/usage/reset":
            cfg = load_cfg()
            if not self.require_admin(cfg):
                return
            body = self.read_json_body(required=False)
            if body is None:
                return
            profile_id = body.get("profileId") if isinstance(body, dict) else None
            if profile_id is not None and not (
                isinstance(profile_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", profile_id)
            ):
                self.json_response({"status": "error", "message": "Invalid profile"}, 400)
                return
            usage_tracker().reset(profile_id)
            log_runtime_event("usage.reset")
            self.json_response({"status": "ok"})
            return
        if action == "api/timer/start":
            cfg = load_cfg()
            if not self.require_admin(cfg):
                return
            body = self.read_json_body(required=False)
            if body is None:
                return
            minutes = body.get("minutes", cfg.get("timerMinutes", 0))
            if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 180:
                self.json_response({"valid": False, "message": "Invalid duration"}, 400)
                return
            end_time = int(time.time()) + minutes * 60
            save_timer({"end_time": end_time, "totalMinutes": minutes})
            log_runtime_event("timer.started")
            self.json_response({"valid": True, "endTime": end_time, "minutes": minutes})
            return
        if action == "api/timer/stop":
            cfg = load_cfg()
            if not self.require_admin(cfg):
                return
            body = self.read_json_body(required=False)
            if body is None:
                return
            clear_timer()
            log_runtime_event("timer.stopped")
            self.json_response({"valid": True})
            return
        if action == "api/timer/extend":
            cfg = load_cfg()
            body = self.read_json_body(required=False)
            if body is None:
                return
            pin_hash = cfg.get("pinHash", "")
            if pin_hash:
                if pin_attempt_blocked():
                    self.json_response({"valid": False, "message": "Too many attempts"}, 429)
                    return
                pin = body.get("pin", "")
                if not isinstance(pin, str) or not verify_pin(pin_hash, pin):
                    record_pin_failure()
                    self.json_response({"valid": False, "message": "Invalid PIN"}, 403)
                    return
                clear_pin_failures()
            minutes = body.get("minutes", 15)
            if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 180:
                self.json_response({"valid": False, "message": "Invalid duration"}, 400)
                return
            end_time = int(time.time()) + minutes * 60
            save_timer({"end_time": end_time, "totalMinutes": minutes})
            log_runtime_event("timer.extended")
            self.json_response({"valid": True, "endTime": end_time, "minutes": minutes})
            return
        if action == "api/update":
            if not self.require_admin():
                return
            try:
                write_update_trigger(APP_ROOT, UPDATE_SCRIPT)
                log_runtime_event("update.triggered")
                self.json_response({"status": "triggered"})
            except MissingUpdaterError as exc:
                self.json_response(
                    {"status": "error", "message": str(exc)},
                    503,
                )
            except Exception as e:
                self.json_response({"status": "error", "message": str(e)}, 500)
            return
        if action == "api/install-package":
            if not self.require_admin():
                return
            data = self.read_json_body()
            if data is None:
                return
            package = data.get("package", "")
            recs = load_recommendations()
            valid_packages = {r["package"] for r in recs if r.get("package")}
            if not package or package not in valid_packages:
                self.json_response({"status": "error", "message": "Invalid package"}, 400)
                return
            command = f"sudo apt install -y {package}"
            self.json_response({"status": "manual", "command": command})
            return
        if action.startswith("launch/"):
            tile_id = unquote(action.split("/", 1)[1])
            if not tile_id or not re.match(r"^[A-Za-z0-9_-]+$", tile_id):
                self.send_response(400)
                self.end_headers()
                return
            if not PORTAO_DE_ABERTURA.entrar():
                # roteiro 31: toques represados viravam dezenas de aberturas seguidas
                log_runtime_event("launch.ignored", level="warning", reason="busy")
                self.json_response({"status": "busy", "message": "Another app is opening"}, 429)
                return
            try:
                cfg = load_cfg()
                tile = next((t for t in cfg.get("tiles", []) if t.get("id") == tile_id and t.get("visible", True)), None)
                if not tile:
                    self.send_response(404)
                    self.end_headers()
                    return
                availability = tile_availability(cfg, tile_id)
                if not availability["allowed"]:
                    self.json_response({
                        "status": "blocked",
                        "reason": availability["reason"],
                    }, 403)
                    return
                try:
                    launch = resolve_tile_action(tile)
                except ValueError as exc:
                    self.json_response({"status": "error", "message": str(exc)}, 400)
                    return
                log_runtime_event("launch.started", actionType=launch["type"])

                if launch["type"] == "media":
                    locations = media_locations()
                    if not locations:
                        reset_active_tile()
                        log_runtime_event(
                            "launch.failed",
                            level="warning",
                            actionType="media",
                            result="missing",
                        )
                        self.send_response(302)
                        self.send_header("Location", "/no-media.html")
                        self.end_headers()
                        return
                    player = find_media_player()
                    command = (
                        media_player_command(player, locations)
                        if player
                        else [abridor_do_sistema() or "xdg-open", locations[0]]
                    )
                    try:
                        launch_owned_tile(
                            command,
                            "local",
                            tile_id=tile_id,
                            profile_id=cfg.get("activeProfileId", ""),
                            track_activity=cfg.get("activityTrackingEnabled", False),
                        )
                    except OSError:
                        log_runtime_event(
                            "launch.failed",
                            level="warning",
                            actionType="media",
                            result="failure",
                        )
                        self.json_response(
                            {"status": "error", "message": "Media process could not be started"},
                            503,
                        )
                        return
                    self.send_response(204)
                    self.end_headers()
                    return

                if launch["type"] == "web":
                    url = launch["url"]
                    if launch["mode"] == "embedded":
                        reset_active_tile()
                        activity_token = ""
                        if cfg.get("activityTrackingEnabled", False):
                            activity_token = embedded_activity_sessions().start(
                                cfg.get("activeProfileId", ""),
                                tile_id,
                            )
                        self.send_response(302)
                        self.send_header(
                            "Location",
                            f"/browser.html?url={quote(url, safe='')}&tile={quote(tile_id, safe='')}"
                            f"&activity={quote(activity_token, safe='')}",
                        )
                        self.end_headers()
                        return
                    browser = find_browser(cfg)
                    command = None
                    profile_id = cfg.get("activeProfileId", "")
                    auto_login = site_login_for_launch(browser, url, profile_id)
                    login_driver = site_login_driver(browser) if auto_login else None
                    if browser:
                        command = external_browser_command(
                            browser, url, profile_id=profile_id,
                            marionette_port=site_logins.MARIONETTE_PORT if login_driver == "marionette" else None,
                            devtools_port=site_logins.DEVTOOLS_PORT if login_driver == "devtools" else None,
                        )
                    elif abridor_do_sistema():
                        command = [abridor_do_sistema(), url]
                    else:
                        reset_active_tile()
                        log_runtime_event(
                            "launch.failed",
                            level="warning",
                            actionType="web",
                            result="missing",
                        )
                        self.json_response({"status": "error", "message": "No supported browser found"}, 503)
                        return
                    try:
                        launch_owned_tile(
                            command,
                            "external",
                            url=url,
                            tile_id=tile_id,
                            profile_id=cfg.get("activeProfileId", ""),
                            track_activity=cfg.get("activityTrackingEnabled", False),
                        )
                    except OSError:
                        log_runtime_event(
                            "launch.failed",
                            level="warning",
                            actionType="web",
                            result="failure",
                        )
                        self.json_response(
                            {"status": "error", "message": "Browser process could not be started"},
                            503,
                        )
                        return
                    if login_driver and command and (
                        "--marionette" in command
                        or any(arg.startswith("--remote-debugging-port=") for arg in command)
                    ):
                        site, login = auto_login
                        site_logins.start_auto_login(
                            site, login["username"], login["password"], url,
                            log=log_runtime_event, driver=login_driver,
                        )
                    self.send_response(204)
                    self.end_headers()
                    return

                clean = launch.get("argv", [])
                if launch["type"] == "none" or not clean:
                    reset_active_tile()
                    self.send_response(204)
                    self.end_headers()
                    return
                path_extra = ""
                env_extra = {}
                if clean[0].startswith(catalogo_windows.PREFIXO):
                    resolved = catalogo_windows.comando(clean)
                    if not resolved:
                        reset_active_tile()
                        log_runtime_event("launch.failed", level="warning", actionType="app", result="missing")
                        self.json_response({"status": "missing", "message": "App not installed"}, 404)
                        return
                    path_extra = catalogo_windows.pasta_no_path(clean, resolved)
                    env_extra = catalogo_windows.ambiente(clean)
                    clean = resolved
                clean = direct_app_command(clean)
                try:
                    # The supervisor still launches argv directly and never invokes a shell.
                    supervisor = launch_owned_tile(
                        clean,
                        "local",
                        tile_id=tile_id,
                        profile_id=cfg.get("activeProfileId", ""),
                        track_activity=cfg.get("activityTrackingEnabled", False),
                        path_extra=path_extra,
                        env_extra=env_extra,
                    )
                except OSError:
                    log_runtime_event(
                        "launch.failed",
                        level="warning",
                        actionType="app",
                        result="failure",
                    )
                    self.json_response(
                        {"status": "error", "message": "Application process could not be started"},
                        503,
                    )
                    return
                if app_fechou_sozinho(supervisor):
                    reset_active_tile()
                    log_runtime_event("launch.failed", level="warning", actionType="app", result="crashed")
                    etapa, codigo = como_o_app_saiu(getattr(supervisor, "returncode", None))
                    telemetria.relatar_problema(
                        etapa, f"tile={tile_id} codigo={codigo} cmd={clean}", assinatura=f"{etapa}:{tile_id}",
                        por_dia=True,
                    )
                    self.json_response({"status": "crashed", "message": "Application closed right away"}, 503)
                    return

                self.send_response(204)
                self.end_headers()
                return
            finally:
                PORTAO_DE_ABERTURA.sair()
        self.send_response(404)
        self.end_headers()


class Servidor(http.server.ThreadingHTTPServer):
    # Cada pedido abre uma conexão nova (HTTP/1.0), e a página pede uns 30 arquivos
    # de uma vez ao abrir. Com a fila padrão (5), o Windows recusa as conexões que
    # sobram quando o servidor demora a aceitar, e o arquivo não carrega (a tela
    # sai sem a marca ou para). A fila maior absorve esses picos.
    request_queue_size = 128


def create_server(host="127.0.0.1", port=PORT):
    return Servidor((host, port), Handler)


def main():
    try:
        configure_runtime_logging(LOG_FILE)
    except OSError:
        pass
    telemetria.instalar_excepthook("servidor")
    server_marker = os.path.abspath(__file__)
    if owned_process_alive(PIDFILE, "server", server_marker):
        log_runtime_event("server.duplicate", level="warning")
        close_runtime_logging()
        return
    try:
        with create_server() as httpd:
            write_process_record(
                PIDFILE,
                os.getpid(),
                "server",
                marker=server_marker,
            )
            log_runtime_event("server.started", version=get_version())
            usage_tracker().start()
            if os.name == "nt":
                try:  # apps novos do catálogo chegam também a quem já tinha instalado
                    atual, mudou = catalogo_windows.sincronizar_tiles(load_stored_cfg())
                    if mudou:
                        save_stored_cfg(atual)
                        log_runtime_event("catalogo.sincronizado")
                except Exception:  # noqa: BLE001
                    pass
                try:  # jogos de navegador do Rabisco: uma vez; oculto ou renomeado fica
                    import rabisco_windows
                    atual, mudou = rabisco_windows.sincronizar(load_stored_cfg())
                    if mudou:
                        save_stored_cfg(atual)
                        log_runtime_event("rabisco.sincronizado")
                except Exception:  # noqa: BLE001
                    pass
            try:
                telemetria_service().iniciar()
            except Exception:  # noqa: BLE001 — telemetria nunca derruba o servidor
                pass
            try:
                # coleções do itch.io: 2 min depois de subir e a cada 30 min
                # (no Linux o cozy-itch-sync também chama a mesma lógica)
                itch_sync.iniciar()
            except Exception:  # noqa: BLE001
                pass
            if os.name == "nt":
                try:  # roteiro 31: pílula travada é reaberta; app travado não conta tempo
                    iniciar_vigia_da_pilula()
                except Exception:  # noqa: BLE001
                    pass
            try:
                if os.name != "nt":  # controles USB: só Linux (evdev) por enquanto
                    controles_service().aplicar()
                    controles_service().garantir_thread()
            except Exception as exc:  # noqa: BLE001
                log_runtime_event("controles.failed", level="warning",
                                  exceptionType=type(exc).__name__)
            try:
                recovery_attempt = int(
                    os.environ.get("COZY_KIDS_RECOVERY_ATTEMPT", "0")
                )
            except ValueError:
                recovery_attempt = 0
            if 1 <= recovery_attempt <= 100:
                log_runtime_event(
                    "launcher.recovered",
                    attempt=recovery_attempt,
                )
            httpd.serve_forever()
    except Exception as exc:
        log_runtime_event(
            "server.crashed",
            level="critical",
            exceptionType=type(exc).__name__,
        )
        raise
    finally:
        embedded_activity_sessions().finish_all()
        if _usage_tracker is not None:
            _usage_tracker.shutdown()
        if _controles is not None:
            _controles.encerrar()
        if _speech_feedback is not None:
            _speech_feedback.close()
        remove_process_record(PIDFILE, expected_pid=os.getpid())
        log_runtime_event("server.stopped")
        close_runtime_logging()


if __name__ == "__main__":
    main()
