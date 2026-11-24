"""Tile action normalization and owned application launching."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time

from app_detection import browser_family
from browser_policy import is_safe_web_url
from process_state import owned_process_alive, terminate_owned_process


def resolve_tile_action(tile):
    """Normalize legacy tile commands into one launch action model."""
    command = tile.get("cmd", []) if isinstance(tile, dict) else []
    if not isinstance(command, list):
        return {"type": "none"}
    clean = [part for part in command if isinstance(part, str) and part]
    if clean == ["special:filme-musik"]:
        return {"type": "media"}
    if len(clean) == 1:
        for prefix, mode in (
            ("special:browser:", "embedded"),
            ("special:external-browser:", "external"),
        ):
            if clean[0].startswith(prefix):
                url = clean[0][len(prefix):]
                if mode == "external":
                    # Moldura do itch.io: o token (ou o http://127.0.0.1/jogo.html
                    # antigo) vira file:// da instalação. Outro file:// continua
                    # barrado pelo is_safe_web_url, logo abaixo.
                    import itch_sync

                    arquivo = itch_sync.url_da_moldura(url)
                    if arquivo:
                        return {"type": "web", "mode": mode, "url": arquivo}
                if not is_safe_web_url(url):
                    raise ValueError("Invalid browser URL")
                return {"type": "web", "mode": mode, "url": url}
    # Older installer versions created browser tiles as `xdg-open URL`.
    if (
        len(clean) == 2
        and clean[0] == "xdg-open"
        and is_safe_web_url(clean[1])
    ):
        return {"type": "web", "mode": "external", "url": clean[1]}
    if len(clean) == 1:
        try:
            clean = shlex.split(clean[0])
        except ValueError:
            clean = []
    return {"type": "app", "argv": clean} if clean else {"type": "none"}


EXTERNAL_PROFILE_SEED = ("extensions", "chrome", "user.js")


# Bloqueio no Edge/Chrome dos sites, sem administrador e sem tocar no navegador
# dos pais: --host-resolver-rules só vale para esta abertura do navegador. Cada
# domínio (e os subdomínios) passa a resolver para 0.0.0.0, então a conexão
# falha. Bloqueia o anúncio, não esconde o espaço vazio que ele deixa (isso só um
# bloqueador como o uBlock faz) e não bloqueia caminhos dentro de um site.
CHROMIUM_BLOCKED_HOSTS = (
    # Google Ads / AdSense. No Escola Games o jogo só abre sem anúncio quando o
    # adsbygoogle.js FALHA ao carregar (onerror): é o mesmo efeito da regra do
    # uBlock no Linux (beni/firefox/policies.json).
    "googlesyndication.com",
    "doubleclick.net",
    "googleadservices.com",
    "googletagservices.com",
    "adservice.google.com",
    "adservice.google.com.br",
    # redes de anúncio comuns em sites de jogos infantis
    "amazon-adsystem.com",
    "adnxs.com",
    "criteo.com",
    "criteo.net",
    "pubmatic.com",
    "rubiconproject.com",
    "openx.net",
    "taboola.com",
    "outbrain.com",
    # redirecionador de anúncio em vídeo que levava ao doubleclick no Escola Games
    # (tracking.adovid.com/redirectv2?url=…pubads.g.doubleclick.net…)
    "adovid.com",
    # site inteiro bloqueado (no Linux: WebsiteFilter do policies.json)
    "bestschoolgames.com",
)


def chromium_host_resolver_rules(hosts=CHROMIUM_BLOCKED_HOSTS):
    """Valor do --host-resolver-rules: cada domínio e seus subdomínios em 0.0.0.0.

    "MAP *.x" não pega o próprio "x", por isso as duas regras. O localhost fica de
    fora para nada atrapalhar o DevTools e o servidor do Benikids em 127.0.0.1.
    """
    rules = []
    for host in hosts:
        rules += [f"MAP {host} 0.0.0.0", f"MAP *.{host} 0.0.0.0"]
    return ", ".join(rules + ["EXCLUDE localhost"])


def _safe_profile_id(profile_id):
    """Id do perfil só com letras, números, "-" e "_" (vira nome de pasta)."""
    return "".join(ch for ch in (profile_id or "") if ch.isalnum() or ch in "-_")[:64]


def external_firefox_profile(cache_root, profile_id=""):
    """Perfil do Firefox dos sites de cada criança (cookies e logins separados).

    O perfil padrão ("default") continua no diretório antigo; os outros nascem
    com as extensões, o CSS e as preferências do padrão, mas sem cookies/senhas.
    """
    base = os.path.join(os.fspath(cache_root), "external-firefox-profile")
    safe = _safe_profile_id(profile_id)
    if not safe or safe == "default":
        return base
    path = f"{base}-{safe}"
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
        for name in EXTERNAL_PROFILE_SEED:
            source = os.path.join(base, name)
            target = os.path.join(path, name)
            try:
                if os.path.isdir(source):
                    shutil.copytree(source, target)
                elif os.path.isfile(source):
                    shutil.copy2(source, target)
            except OSError:
                pass
    return path


def external_chromium_profile(cache_root, profile_id=""):
    """Pasta de dados do Edge/Chrome dos sites de cada criança.

    Como no Firefox: o perfil "default" fica na pasta antiga (quem já usava não
    perde os cookies) e cada outra criança tem a sua, para os logins e cookies
    de irmãos não se misturarem.
    """
    base = os.path.join(os.fspath(cache_root), "external-chromium-profile")
    safe = _safe_profile_id(profile_id)
    if not safe or safe == "default":
        return base
    return f"{base}-{safe}"


# Preferências do perfil do Edge/Chrome dos sites que o Benikids garante a cada
# abertura (sem administrador; as políticas TranslateEnabled e
# PasswordManagerEnabled do politicas_edge.py fazem o mesmo para o computador):
# - translate.enabled=false: sem a barra/ícone "Traduzir esta página" e sem o
#   oferecimento automático;
# - gerenciador de senhas desligado: o Edge não oferece salvar a senha nem
#   preenche sozinho um login salvo à mão (quem entra é o login automático, com
#   o login de cada criança). Logins já salvos não são apagados.
CHROMIUM_PREFERENCES = {
    "translate": {"enabled": False},
    "credentials_enable_service": False,
    "profile": {"password_manager_enabled": False},
}


def _merge_prefs(current, wanted):
    """Põe os valores de wanted em current sem tirar nenhuma outra chave."""
    changed = False
    for key, value in wanted.items():
        if isinstance(value, dict):
            if not isinstance(current.get(key), dict):
                current[key] = {}
                changed = True
            changed = _merge_prefs(current[key], value) or changed
        elif current.get(key) != value or type(current.get(key)) is not type(value):
            current[key] = value
            changed = True
    return changed


def ensure_chromium_preferences(profile, wanted=CHROMIUM_PREFERENCES):
    """Garante as preferências em <perfil>/Default/Preferences antes de abrir o navegador.

    O resto do arquivo fica como está. Sem o arquivo (perfil novo), cria só o
    mínimo; o navegador completa o resto. Se o arquivo não for um JSON válido
    (o navegador escrevendo naquela hora), não mexe: na próxima abertura dá. Se
    o Windows não deixar trocar o arquivo (navegador aberto), segue sem ele.
    Devolve True se gravou.
    """
    path = os.path.join(os.fspath(profile), "Default", "Preferences")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    if not _merge_prefs(data, wanted):
        return False
    tmp = f"{path}.benikids-tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False
    return True


def external_browser_command(
    browser, url, cache_root, profile_id="", marionette_port=None, devtools_port=None,
):
    """Build the isolated kiosk command used for an external web tile.

    marionette_port (Firefox) e devtools_port (Edge/Chrome) só vêm quando o tile
    tem login automático salvo: o controle remoto do navegador fica desligado
    nos outros sites.
    """
    cache_root = os.fspath(cache_root)
    if browser_family(browser) == "chromium":
        profile = external_chromium_profile(cache_root, profile_id)
        ensure_chromium_preferences(profile)
        command = [
            browser,
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--disable-session-crashed-bubble",
            "--lang=pt-BR",
            f"--host-resolver-rules={chromium_host_resolver_rules()}",
            # Só um --disable-features vale: as funções desligadas vão na mesma
            # lista. Translate reforça a preferência; DnsOverHttps é o mesmo do
            # navegador-jogos no Linux (o quiosque usa o DNS da rede).
            "--disable-features=Translate,DnsOverHttps",
        ]
        if devtools_port:
            # login automático (site_logins.py, DevTools Protocol): só neste tile,
            # só em 127.0.0.1
            command += [
                f"--remote-debugging-port={int(devtools_port)}",
                "--remote-debugging-address=127.0.0.1",
            ]
        if os.name == "nt" and url.startswith("file:"):
            # sem o fragmento: o log fica com o caminho codificado, não com o jogo
            _log_windows("jogo: Edge em quiosque na moldura local " + url.split("#", 1)[0])
        return command + ["--kiosk", f"--app={url}"]
    profile = external_firefox_profile(cache_root, profile_id)
    os.makedirs(profile, exist_ok=True)
    if marionette_port:
        # login automático (site_logins.py): o Marionette só liga neste tile
        _set_user_pref(profile, "marionette.port", int(marionette_port))
        return [browser, "--no-remote", "--profile", profile, "--marionette", "--kiosk", url]
    return [browser, "--no-remote", "--profile", profile, "--kiosk", url]


def _set_user_pref(profile, name, value):
    path = os.path.join(profile, "user.js")
    line = f'user_pref("{name}", {json.dumps(value)});'
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        lines = []
    lines = [item for item in lines if f'"{name}"' not in item] + [line]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def direct_app_command(command):
    """Remove the legacy KDE fullscreen wrapper before supervision."""
    if (
        len(command) >= 3
        and command[0] in ("kstart5", "kstart")
        and command[1] == "--fullscreen"
    ):
        return command[2:]
    return command


def _log_windows(texto):
    try:
        caminho = os.path.join(os.path.expanduser("~"), ".cache", "cozy-kids-launcher", "beni-windows.log")
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")
    except OSError:
        pass


class PortaoDeAbertura:
    """Um app por vez, com folga (roteiro 31, a avalanche).

    O menu travou junto com a pílula, e os toques da criança ficaram represados. Quando
    ele destravou, mandou todos de uma vez: o servidor abriu o Kiddo Games ~32 vezes, uma
    a cada ~2,5 s, cada uma matando a anterior. Agora um pedido de abertura é recusado
    enquanto outro está abrindo e nos FOLGA segundos depois de um app ter sido aberto
    (qualquer tile). Um pedido que não abriu nada (bloqueado, não instalado) não dá folga."""

    FOLGA = 3.0

    def __init__(self, folga=FOLGA, relogio=time.monotonic):
        self.folga = folga
        self.relogio = relogio
        self._lock = threading.Lock()
        self.ocupado = False
        self.abriu = False
        self.fim = None

    def entrar(self):
        with self._lock:
            if self.ocupado:
                return False
            if self.fim is not None and self.relogio() - self.fim < self.folga:
                return False
            self.ocupado = True
            self.abriu = False
            return True

    def abriu_app(self):
        with self._lock:
            self.abriu = True

    def sair(self):
        with self._lock:
            if self.abriu:
                self.fim = self.relogio()
            self.ocupado = False
            self.abriu = False


class ApplicationLauncher:
    """Start and stop only process trees owned by one launcher tile."""

    # argumentos da última pílula aberta (o servidor cria um ApplicationLauncher por
    # pedido; o vigia da pílula precisa deles para reabri-la igual)
    ultimo_overlay = None

    def __init__(
        self,
        tile_process_pidfile,
        overlay_pidfile,
        process_supervisor,
        overlay_script,
        activity_file="",
        lock=None,
        python_executable=None,
    ):
        self.tile_process_pidfile = os.fspath(tile_process_pidfile)
        self.overlay_pidfile = os.fspath(overlay_pidfile)
        self.process_supervisor = os.fspath(process_supervisor)
        self.overlay_script = os.fspath(overlay_script)
        self.activity_file = os.fspath(activity_file) if activity_file else ""
        self.lock = lock or threading.Lock()
        self.python_executable = python_executable or sys.executable

    def stop_existing_overlay(self):
        return terminate_owned_process(
            self.overlay_pidfile,
            "overlay",
            self.overlay_script,
        )

    def stop_active_tile(self):
        parou = terminate_owned_process(
            self.tile_process_pidfile,
            "tile-process",
            self.process_supervisor,
        )
        if parou and os.name == "nt":
            # ✕ da pílula, outro app aberto, limite de tempo, Sair: o Job Object do
            # supervisor leva a árvore inteira do app junto (mesmo travado)
            ultimo = ApplicationLauncher.ultimo_overlay or {}
            _log_windows(f"app: {ultimo.get('tile_id') or '?'} encerrado pelo servidor (com a árvore do app)")
        return parou

    @staticmethod
    def _wait_for_owned_process(path, role, marker, process, timeout=1.5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if owned_process_alive(path, role, marker):
                return True
            if process.poll() is not None:
                break
            time.sleep(0.05)
        return owned_process_alive(path, role, marker)

    @staticmethod
    def _terminate_started_process(process):
        try:
            process.terminate()
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def start_overlay(self, mode, url="", tile_id=""):
        if not os.path.isfile(self.overlay_script):
            return False
        command = [
            self.python_executable,
            self.overlay_script,
            "--mode",
            mode,
            "--label",
            "Home",
        ]
        if url:
            command.extend(["--url", url])
        if tile_id:
            command.extend(["--tile-id", tile_id])
        ApplicationLauncher.ultimo_overlay = {"mode": mode, "url": url, "tile_id": tile_id}
        process = subprocess.Popen(
            command,
            env=dict(os.environ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if self._wait_for_owned_process(
            self.overlay_pidfile,
            "overlay",
            self.overlay_script,
            process,
            timeout=5,
        ):
            return True
        self._terminate_started_process(process)
        return False

    def reset_active_tile(self):
        with self.lock:
            self.stop_existing_overlay()
            self.stop_active_tile()

    def launch_owned_tile(
        self,
        command,
        mode,
        url="",
        tile_id="",
        profile_id="",
        track_activity=False,
        path_extra="",
        env_extra=None,
    ):
        if not command or not os.path.isfile(self.process_supervisor):
            raise OSError("Tile process supervisor is unavailable")
        with self.lock:
            self.stop_existing_overlay()
            self.stop_active_tile()
            wrapped = [
                self.python_executable,
                self.process_supervisor,
                "--record",
                self.tile_process_pidfile,
                "--marker",
                self.process_supervisor,
            ]
            if track_activity and self.activity_file and profile_id and tile_id:
                wrapped.extend([
                    "--activity-file",
                    self.activity_file,
                    "--activity-profile",
                    profile_id,
                    "--activity-tile",
                    tile_id,
                ])
            wrapped.extend(["--", *command])
            env = dict(os.environ)
            if path_extra:
                # Só para este app e seus filhos (ex.: o Quatro em Linha acha o motor de IA
                # pelo PATH); o PATH do servidor não muda.
                env["PATH"] = path_extra + os.pathsep + env.get("PATH", "")
            # "env" do catálogo (ex.: SDL_RENDER_DRIVER=opengl no Tux Paint): só este app
            env.update(env_extra or {})
            process = subprocess.Popen(
                wrapped,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=(os.name == "posix"),
            )
            if not self._wait_for_owned_process(
                self.tile_process_pidfile,
                "tile-process",
                self.process_supervisor,
                process,
            ):
                self._terminate_started_process(process)
                raise OSError("Tile process ownership could not be established")
            if not self.start_overlay(mode, url=url, tile_id=tile_id):
                self.stop_active_tile()
                raise OSError("Tile overlay could not be started")
            return process
