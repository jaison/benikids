"""Telemetria anônima do Benikids: em que computadores ele está instalado.

Um envio por dia, em segundo plano, se os pais não desligarem ("telemetryEnabled"
na configuração; Pais → Sistema). O que vai é exatamente o que dados() devolve:
um número aleatório desta instalação, a versão, o sistema, a CPU, a memória, a
placa de vídeo, o tipo de menu, a resolução da tela e o idioma. Nada sobre as
crianças nem sobre o uso. O destino é um Cloudflare Worker (telemetria/) que
não grava o IP. Sem internet, tenta de novo no dia seguinte.
"""

import json
import locale
import os
import platform
import re
import secrets
import subprocess
import threading
import time
import urllib.request

ENDERECO = os.environ.get("BENIKIDS_TELEMETRIA_URL", "https://benikids-telemetria.PREENCHER.workers.dev/v1/ping")
INTERVALO = 24 * 3600
SEM_CONSOLE = 0x08000000 if os.name == "nt" else 0


def ligada(cfg):
    return cfg.get("telemetryEnabled", True) is not False


# ------------------------------------------------------------------ estado local


def ler_estado(caminho):
    try:
        with open(caminho, encoding="utf-8") as f:
            estado = json.load(f)
        if isinstance(estado, dict) and re.fullmatch(r"[0-9a-f]{32}", str(estado.get("id", ""))):
            return estado
    except (OSError, ValueError):
        pass
    return {"id": secrets.token_hex(16), "ultimo_envio": 0}


def gravar_estado(caminho, estado):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    temp = caminho + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(estado, f)
    os.replace(temp, caminho)


# ------------------------------------------------------------------ o computador


def _rodar(argv, timeout=20):
    try:
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, creationflags=SEM_CONSOLE).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _registro(caminho, nome):
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, caminho) as chave:
            return str(winreg.QueryValueEx(chave, nome)[0])
    except (OSError, ImportError):
        return ""


def sistema():
    if os.name == "nt":
        chave = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        build = _registro(chave, "CurrentBuildNumber") or platform.version().split(".")[-1]
        versao = _registro(chave, "DisplayVersion") or _registro(chave, "ReleaseId")
        nome = "Windows 11" if build.isdigit() and int(build) >= 22000 else f"Windows {platform.release()}"
        return " ".join(p for p in (nome, versao, f"(build {build})" if build else "") if p)
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for linha in f:
                if linha.startswith("PRETTY_NAME="):
                    return linha.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.platform(terse=True)


def cpu():
    if os.name == "nt":
        return _registro(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString").strip()
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for linha in f:
                if linha.startswith("model name"):
                    return linha.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor()


def ram_gb():
    if os.name == "nt":
        import ctypes

        class Memoria(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        m = Memoria()
        m.dwLength = ctypes.sizeof(Memoria)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return round(m.ullTotalPhys / 1024 ** 3)
        return None
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for linha in f:
                if linha.startswith("MemTotal:"):
                    return round(int(linha.split()[1]) / 1024 ** 2)
    except (OSError, ValueError, IndexError):
        pass
    return None


def gpu():
    if os.name == "nt":
        saida = _rodar(["powershell.exe", "-NoProfile", "-Command",
                        "(Get-CimInstance Win32_VideoController).Name -join ' / '"], timeout=40)
        return saida.strip()
    nomes = []
    for linha in _rodar(["lspci"]).splitlines():
        if re.search(r"VGA compatible controller|3D controller|Display controller", linha):
            nomes.append(linha.split(": ", 1)[-1].strip())
    return " / ".join(nomes)


def tela():
    if os.name == "nt":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            try:
                user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass
            return f"{user32.GetSystemMetrics(0)}x{user32.GetSystemMetrics(1)}"
        except (AttributeError, OSError):
            return ""
    achado = re.search(r"current (\d+) x (\d+)", _rodar(["xrandr", "--current"]))
    return f"{achado.group(1)}x{achado.group(2)}" if achado else ""


def idioma():
    try:
        nome = locale.getlocale()[0] or ""
    except ValueError:
        nome = ""
    if os.name == "nt" and not nome:
        try:
            import ctypes

            nome = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
        except (AttributeError, OSError):
            nome = ""
    return nome.replace("_", "-").split(".")[0]


def dados(id_instalacao, versao, menu):
    """Tudo o que é enviado (a área dos pais mostra isto em "o que é enviado")."""
    def seguro(f):
        try:
            return f() or None
        except Exception:  # noqa: BLE001 — um dado que falha não impede o resto
            return None

    return {
        "id": id_instalacao,
        "versao": versao or None,
        "plataforma": "windows" if os.name == "nt" else "linux",
        "sistema": seguro(sistema),
        "cpu": seguro(cpu),
        "ram_gb": seguro(ram_gb),
        "gpu": seguro(gpu),
        "menu": menu,
        "tela": seguro(tela),
        "idioma": seguro(idioma),
    }


# ------------------------------------------------------------------ envio


def enviar(corpo, endereco=ENDERECO, timeout=15):
    pedido = urllib.request.Request(
        endereco, data=json.dumps(corpo).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "Benikids"},
    )
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
            return 200 <= resposta.status < 300
    except (OSError, ValueError):
        return False


class Telemetria:
    """Envia uma vez por dia, numa thread de fundo, enquanto a config deixar."""

    def __init__(self, caminho_estado, ler_config, versao, menu, enviar=enviar, agora=time.time):
        self.caminho = caminho_estado
        self.ler_config = ler_config
        self.versao = versao
        self.menu = menu
        self._enviar = enviar
        self._agora = agora
        self._parar = threading.Event()

    def id(self):
        estado = ler_estado(self.caminho)
        if not os.path.exists(self.caminho):
            gravar_estado(self.caminho, estado)
        return estado["id"]

    def previa(self):
        return dados(self.id(), self.versao(), self.menu())

    def talvez_enviar(self):
        """Envia se a config deixa e já passou um dia. Devolve True se enviou."""
        try:
            if not ligada(self.ler_config()):
                return False
        except Exception:  # noqa: BLE001
            return False
        estado = ler_estado(self.caminho)
        if self._agora() - float(estado.get("ultimo_envio") or 0) < INTERVALO:
            return False
        if not self._enviar(dados(estado["id"], self.versao(), self.menu())):
            return False
        estado["ultimo_envio"] = self._agora()
        try:
            gravar_estado(self.caminho, estado)
        except OSError:
            pass
        return True

    def iniciar(self, primeira_espera=120, entre_tentativas=3600):
        def laco():
            if self._parar.wait(primeira_espera):
                return
            while True:
                self.talvez_enviar()
                if self._parar.wait(entre_tentativas):
                    return

        threading.Thread(target=laco, name="telemetria", daemon=True).start()

    def parar(self):
        self._parar.set()
