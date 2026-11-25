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
import sys
import threading
import time
import urllib.request
from contextlib import contextmanager

BASE = os.environ.get("BENIKIDS_TELEMETRIA_URL", "https://telemetria.benikids.app").rstrip("/")
ENDERECO = BASE + "/v1/ping"
ENDERECO_USO = BASE + "/v1/uso"
ENDERECO_PROBLEMA = BASE + "/v1/problema"
ENDERECO_APAGAR = BASE + "/v1/apagar"
FILA_PROBLEMAS = os.path.join(os.path.expanduser("~"), ".config", "cozy-kids-launcher", "problemas-pendentes.jsonl")
INTERVALO = 24 * 3600
SEM_CONSOLE = 0x08000000 if os.name == "nt" else 0
# O Benikids só é instalado em Windows e Linux. Fora deles (o Mac de quem desenvolve,
# rodando o servidor para testar) nada é enviado: antes isso entrava no banco como
# "linux" e inflava a contagem de instalações.
SISTEMA_SUPORTADO = sys.platform == "win32" or sys.platform.startswith("linux")


def ligada(cfg):
    return cfg.get("telemetryEnabled", True) is not False


def uso_ligado(cfg):
    """Relatório de uso por criança: só com a caixinha marcada pelos pais (padrão desligado)."""
    return cfg.get("usageTelemetryEnabled", False) is True


# ------------------------------------------------------------------ relatório de uso


FAIXAS = ((0, 3, "0-3"), (4, 5, "4-5"), (6, 7, "6-7"), (8, 10, "8-10"), (11, 13, "11-13"))


def faixa_etaria(nascimento, dia):
    """"AAAA-MM" + "AAAA-MM-DD" → faixa ("6-7"); a data em si nunca sai do computador."""
    try:
        ano, mes = (int(x) for x in nascimento.split("-"))
        dia_ano, dia_mes = (int(x) for x in dia.split("-")[:2])
    except (AttributeError, ValueError):
        return None
    idade = dia_ano - ano - (1 if dia_mes < mes else 0)
    if idade < 0:
        return None
    for minimo, maximo, nome in FAIXAS:
        if minimo <= idade <= maximo:
            return nome
    return "14+"


def relatorio_de_uso(cfg, historico, depois_de=""):
    """Dias fechados do histórico (perfil → dia → {totalSeconds, categories, tiles}) em
    formato anônimo: número aleatório da criança, faixa de idade, menino/menina, minutos."""
    dias = []
    for perfil in cfg.get("profiles", []):
        id_crianca = perfil.get("telemetryId")
        if not id_crianca:
            continue
        tiles = {t.get("id"): t for t in perfil.get("tiles", []) if isinstance(t, dict)}
        for dia, entrada in sorted((historico.get(perfil.get("id")) or {}).items()):
            if dia <= depois_de:
                continue
            apps = []
            for tile_id, segundos in sorted((entrada.get("tiles") or {}).items()):
                minutos = round(segundos / 60)
                if minutos < 1:
                    continue
                tile = tiles.get(tile_id, {})
                apps.append({"app": tile_id, "nome": str(tile.get("label", ""))[:60],
                             "categoria": tile.get("category") or "", "minutos": minutos})
            dias.append({
                "crianca": id_crianca,
                "faixa": faixa_etaria(perfil.get("birthMonth"), dia),
                "genero": perfil.get("gender"),
                "dia": dia,
                "minutos": round(float(entrada.get("totalSeconds", 0)) / 60),
                "categorias": {k: round(v / 60) for k, v in (entrada.get("categories") or {}).items()},
                "apps": apps,
            })
    return dias


# ------------------------------------------------------------------ relatórios de problema


def limpar(texto, limite=4000):
    """Tira do texto o que identifica a família: pasta e nome do usuário, e-mails."""
    texto = str(texto)
    casa = os.path.expanduser("~")
    usuario = os.environ.get("USERNAME") or os.environ.get("USER") or os.path.basename(casa)
    for alvo, troca in ((casa, "%USERPROFILE%"), (casa.replace("\\", "/"), "%USERPROFILE%")):
        if alvo and len(alvo) > 3:
            texto = re.sub(re.escape(alvo), troca, texto, flags=re.I)
    if usuario and len(usuario) > 1:
        texto = re.sub(re.escape(usuario), "<usuario>", texto, flags=re.I)
    texto = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<email>", texto)
    return texto[-limite:]


MARCAS_DO_DIA = os.path.join(os.path.dirname(FILA_PROBLEMAS), "problemas-do-dia.json")


def _marcas_de_hoje(marcas, hoje):
    try:
        with open(marcas, encoding="utf-8") as f:
            dados_ = json.load(f)
        if not isinstance(dados_, dict):
            return {}
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in dados_.items() if v == hoje}  # o de ontem não serve mais


def ja_relatado_hoje(assinatura, marcas=None, hoje=None, marcar=True):
    """True se esta assinatura já foi guardada hoje; senão, marca (se marcar) e devolve
    False. Os vigias (pílula travada, app travado, exceções) mandam no máximo 1 por dia."""
    marcas = marcas or MARCAS_DO_DIA
    hoje = hoje or time.strftime("%Y-%m-%d")
    dados_ = _marcas_de_hoje(marcas, hoje)
    if dados_.get(assinatura) == hoje:
        return True
    if not marcar:
        return False
    dados_[assinatura] = hoje
    try:
        os.makedirs(os.path.dirname(marcas), exist_ok=True)
        temp = marcas + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(dados_, f)
        os.replace(temp, marcas)
    except OSError:
        pass
    return False


def relatar_problema(etapa, detalhe, assinatura=None, fila=None, por_dia=False, marcas=None):
    """Guarda um problema para o servidor enviar (se a telemetria estiver ligada).
    Pode ser chamado de qualquer processo: instalador, iniciador, servidor.
    por_dia: no máximo 1 por assinatura por dia (o resto é descartado aqui). A marca do
    dia só é gravada DEPOIS de o problema entrar na fila (roteiro 33: marcar antes e
    falhar ao gravar perdia o problema do dia inteiro)."""
    chave = str(assinatura or etapa)[:120]
    if por_dia and ja_relatado_hoje(chave, marcas, marcar=False):
        return False
    item = {
        "etapa": str(etapa)[:60],
        "assinatura": str(assinatura or etapa)[:120],
        "detalhe": limpar(detalhe),
        "quando": time.strftime("%Y-%m-%d"),
    }
    fila = fila or FILA_PROBLEMAS
    try:
        os.makedirs(os.path.dirname(fila), exist_ok=True)
        with open(fila, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except OSError:
        return False
    if por_dia:
        ja_relatado_hoje(chave, marcas)
    return True


LOG_WINDOWS = os.path.join(os.path.expanduser("~"), ".cache", "cozy-kids-launcher", "beni-windows.log")


def log_windows(texto, arquivo=None):
    """Uma linha (ou mais) no beni-windows.log. Nunca lança exceção."""
    try:
        agora = time.time()
        with open(arquivo or LOG_WINDOWS, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(agora))
                    + f".{int(agora * 1000) % 1000:03d} " + str(texto) + "\n")
    except Exception:  # noqa: BLE001
        pass


def relatar_excecao(processo, tipo, valor, tb, fila=None, marcas=None, log=None):
    """Exceção não tratada num processo Python do Windows: "excecao:<processo>:<Tipo>",
    com o fim do traceback já limpo (sem pasta nem nome do usuário). 1 por dia na
    telemetria; no beni-windows.log, SEMPRE, com o traceback (roteiro 33: um
    PermissionError do overlay foi para a telemetria sem deixar linha no log)."""
    import traceback

    try:
        texto = "".join(traceback.format_exception(tipo, valor, tb))
    except Exception:  # noqa: BLE001
        texto = f"{getattr(tipo, '__name__', tipo)}: {valor}"
    nome = getattr(tipo, "__name__", "Erro")
    (log or log_windows)(f"{processo}: exceção não tratada {nome}: {valor}\n{texto.rstrip()}")
    return relatar_problema(f"excecao.{processo}", limpar(texto, 1500), f"excecao:{processo}:{nome}",
                            fila=fila, por_dia=True, marcas=marcas)


def instalar_excepthook(processo, sistema_nt=None):
    """sys.excepthook e threading.excepthook mandam a exceção para a telemetria (só no
    Windows, onde o pythonw não tem console) e depois seguem o caminho de sempre."""
    if not (os.name == "nt" if sistema_nt is None else sistema_nt):
        return False
    import sys

    anterior_sys = sys.excepthook
    anterior_thread = threading.excepthook

    def gancho_sys(tipo, valor, tb):
        if not issubclass(tipo, (KeyboardInterrupt, SystemExit)):
            try:
                relatar_excecao(processo, tipo, valor, tb)
            except Exception:  # noqa: BLE001
                pass
        anterior_sys(tipo, valor, tb)

    def gancho_thread(args):
        if args.exc_type is not None and not issubclass(args.exc_type, SystemExit):
            try:
                relatar_excecao(processo, args.exc_type, args.exc_value, args.exc_traceback)
            except Exception:  # noqa: BLE001
                pass
        anterior_thread(args)

    sys.excepthook = gancho_sys
    threading.excepthook = gancho_thread
    return True


def tirar_da_fila(fila=None, maximo=20):
    """Tira os problemas da fila para enviar. Primeiro troca o nome do arquivo (atômico):
    o que outro processo acrescentar depois vai para uma fila nova e não se perde entre
    o ler e o apagar. Uma troca que sobrou de antes (queda no meio) é lida primeiro."""
    fila = fila or FILA_PROBLEMAS
    enviando = fila + ".enviando"
    try:
        if not os.path.exists(enviando):
            os.replace(fila, enviando)
        with open(enviando, encoding="utf-8") as f:
            linhas = f.readlines()
        os.remove(enviando)
    except OSError:
        return []
    itens = []
    for linha in linhas[-maximo:]:
        try:
            itens.append(json.loads(linha))
        except ValueError:
            pass
    return itens


# ------------------------------------------------------------------ estado local

# Id deste processo, por arquivo. Se a leitura falhar no meio do envio, o próximo
# POST usa este id em vez de sortear outro. Não vale para outro processo: o disco é
# quem manda quando a leitura funciona.
_memoria = {}
_memoria_trava = threading.Lock()
_ID_LOCAL = re.compile(r"^[0-9a-f]{32}$")


def _id_valido(valor):
    return isinstance(valor, str) and _ID_LOCAL.fullmatch(valor) is not None


def _lembrar(caminho, estado):
    with _memoria_trava:
        _memoria[os.path.abspath(caminho)] = dict(estado)


def _lembrado(caminho):
    with _memoria_trava:
        estado = _memoria.get(os.path.abspath(caminho))
        return dict(estado) if estado else None


def _travar(fd):
    """Trava exclusiva. No Windows o msvcrt trava 1 byte; nos outros, flock."""
    if os.name == "nt":
        import msvcrt

        if os.lseek(fd, 0, os.SEEK_END) == 0:
            os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
        prazo = time.time() + 5
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.time() >= prazo:
                    raise
                time.sleep(0.05)
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX)


def _destravar(fd):
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def _trava_estado(caminho):
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    fd = os.open(caminho + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _travar(fd)
        yield
    finally:
        try:
            _destravar(fd)
        except OSError:
            pass
        os.close(fd)


def _classificar(caminho):
    """'ok' com o dict, 'ausente', 'invalido' (JSON ou id ruim) ou 'erro' de leitura."""
    try:
        with open(caminho, encoding="utf-8") as f:
            estado = json.load(f)
    except FileNotFoundError:
        return "ausente", None
    except ValueError:
        return "invalido", None
    except OSError:
        return "erro", None
    if not isinstance(estado, dict):
        return "invalido", None
    if not _id_valido(estado.get("id")):
        return "invalido", estado
    return "ok", estado


def _gravar_atomico(caminho, estado):
    """Grava noutro arquivo (nome com pid) e troca no lugar. O .tmp fixo antigo
    podia ser escrito por dois ao mesmo tempo e nascia um JSON pela metade."""
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    tmp = f"{caminho}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(4)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        dados_ = json.dumps(estado).encode("utf-8")
        os.write(fd, dados_)
        os.fsync(fd)
    except Exception:
        os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.close(fd)
    try:
        os.replace(tmp, caminho)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if os.name != "nt" and pasta:
        try:
            dirfd = os.open(pasta, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dirfd)
        except OSError:
            pass
        finally:
            os.close(dirfd)


def ler_estado(caminho):
    """O estado com um id estável, já gravado no disco.

    None se não der para usar um id sem inventar outro: arquivo ilegível e este
    processo ainda não leu um id, ou id novo que não coube no disco. Quem chama
    não envia nesse caso.
    """
    try:
        with _trava_estado(caminho):
            return _ler_ou_criar_trancado(caminho)
    except OSError:
        return _lembrado(caminho)


def _ler_ou_criar_trancado(caminho):
    situacao, estado = "erro", None
    for tentativa in range(3):
        situacao, estado = _classificar(caminho)
        if situacao != "erro":
            break
        if tentativa < 2:
            time.sleep(0.02)
    if situacao == "ok":
        _lembrar(caminho, estado)
        return dict(estado)
    lembrado = _lembrado(caminho)
    if situacao == "erro":
        # Permissão ou falha passageira: não apaga o arquivo e não sorteia outro id.
        return dict(lembrado) if lembrado else None
    if lembrado and situacao == "invalido":
        try:
            _gravar_atomico(caminho, lembrado)
        except OSError:
            pass
        return dict(lembrado)
    if lembrado and situacao == "ausente":
        try:
            _gravar_atomico(caminho, lembrado)
        except OSError:
            return None
        return dict(lembrado)
    novo = dict(estado) if isinstance(estado, dict) else {}
    novo["id"] = secrets.token_hex(16)
    if not isinstance(novo.get("ultimo_envio"), (int, float)):
        novo["ultimo_envio"] = 0
    try:
        _gravar_atomico(caminho, novo)
    except OSError:
        return None
    _lembrar(caminho, novo)
    return dict(novo)


def gravar_estado(caminho, estado):
    if not isinstance(estado, dict) or not _id_valido(estado.get("id")):
        raise OSError("estado da telemetria sem id")
    with _trava_estado(caminho):
        _gravar_atomico(caminho, estado)
        _lembrar(caminho, estado)


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

    def __init__(self, caminho_estado, ler_config, versao, menu, enviar=enviar, agora=time.time,
                 ler_historico=lambda: {}, fila=None):
        self.caminho = caminho_estado
        self.ler_config = ler_config
        self.versao = versao
        self.menu = menu
        self._enviar = enviar
        self._agora = agora
        self.ler_historico = ler_historico
        self.fila = fila
        self._parar = threading.Event()

    def id(self):
        estado = ler_estado(self.caminho)
        if not estado:
            raise OSError("não deu para ler o id da telemetria")
        return estado["id"]

    def previa(self):
        return dados(self.id(), self.versao(), self.menu())

    def previa_uso(self):
        try:
            estado = ler_estado(self.caminho) or {}
            return relatorio_de_uso(self.ler_config(), self.ler_historico(), estado.get("uso_ate", ""))
        except Exception:  # noqa: BLE001
            return []

    def enviar_problemas(self):
        """Manda os problemas da fila (só com a telemetria ligada; senão, descarta)."""
        itens = tirar_da_fila(self.fila)
        if not itens:
            return 0
        try:
            cfg = self.ler_config()
        except Exception:  # noqa: BLE001
            cfg = {}
        if not ligada(cfg):
            return 0
        estado = ler_estado(self.caminho)
        if not estado:
            for item in itens:
                relatar_problema(item.get("etapa"), item.get("detalhe"), item.get("assinatura"), self.fila)
            return 0
        base = {"id": estado["id"], "versao": self.versao() or None,
                "plataforma": "windows" if os.name == "nt" else "linux", "sistema": sistema()}
        enviados = 0
        for item in itens:
            if self._enviar(dict(base, **item), ENDERECO_PROBLEMA):
                enviados += 1
            else:
                relatar_problema(item.get("etapa"), item.get("detalhe"), item.get("assinatura"), self.fila)
        return enviados

    def enviar_uso(self):
        """Manda os dias fechados de uso ainda não enviados (só com a caixinha marcada)."""
        try:
            cfg = self.ler_config()
        except Exception:  # noqa: BLE001
            return False
        if not uso_ligado(cfg) and not os.path.exists(self.caminho):
            return False
        estado = ler_estado(self.caminho)
        if not estado:
            return False
        if not uso_ligado(cfg):
            if estado.pop("uso_desde", None):  # desligou: se ligar de novo, conta a partir dali
                gravar_estado(self.caminho, estado)
            return False
        if not estado.get("uso_desde"):
            # só vai o uso a partir do dia em que os pais ligaram, nunca o que veio antes
            estado["uso_desde"] = time.strftime("%Y-%m-%d", time.localtime(self._agora()))
            gravar_estado(self.caminho, estado)
            return False
        desde = estado["uso_desde"]
        dias = [d for d in relatorio_de_uso(cfg, self.ler_historico(), estado.get("uso_ate", ""))
                if d["dia"] >= desde]
        if not dias:
            return False
        if not self._enviar({"dias": dias}, ENDERECO_USO):
            return False
        estado["uso_ate"] = max(d["dia"] for d in dias)
        try:
            gravar_estado(self.caminho, estado)
        except OSError:
            pass
        return True

    def apagar_dados_enviados(self, cfg):
        """Pede ao servidor para apagar o uso das crianças e o registro deste computador."""
        estado = ler_estado(self.caminho)
        if not estado:
            return False
        criancas = [p["telemetryId"] for p in cfg.get("profiles", []) if p.get("telemetryId")]
        return self._enviar({"id": estado["id"], "criancas": criancas}, ENDERECO_APAGAR)

    def talvez_enviar(self):
        """Envia se a config deixa e já passou um dia. Devolve True se enviou."""
        try:
            self.enviar_problemas()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.enviar_uso()
        except Exception:  # noqa: BLE001
            pass
        try:
            if not ligada(self.ler_config()):
                return False
        except Exception:  # noqa: BLE001
            return False
        estado = ler_estado(self.caminho)
        if not estado:
            return False
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
        if not SISTEMA_SUPORTADO:
            return

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
