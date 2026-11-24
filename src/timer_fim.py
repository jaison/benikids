"""Quando o timer da sessão acaba com um app aberto, fecha o app e não deixa
a criança voltar para ele por Alt+Tab ou clique.

O fechamento é o mesmo do ✕ e do fim da contagem da categoria:
`terminate_owned_process` manda SIGTERM ao supervisor (no Windows isso já é
TerminateProcess; o Job Object leva a árvore) e, se o processo continuar,
SIGKILL. No Linux o supervisor ainda pede SIGTERM aos filhos e só então SIGKILL.

No Linux a tela "Acabou o tempo!" é uma janela comum (o navegador do menu, ou a
vigia por cima dela). Enquanto o app ainda tem janela, ela fica abaixo, fora do
Alt+Tab, e a tela de bloqueio fica acima.
"""

import os
import shutil
import subprocess

from process_state import owned_process, owned_process_alive, terminate_owned_process


HOME = os.path.expanduser("~")
APP_ID = "cozy-kids-launcher"
CACHE_DIR = os.path.join(HOME, ".cache", APP_ID)
TILE_PROCESS_PIDFILE = os.path.join(CACHE_DIR, "tile-process.pid")
BROWSER_PIDFILE = os.path.join(CACHE_DIR, "browser.pid")
TILE_PROCESS_MARKER = os.path.join(HOME, ".local", "share", APP_ID, "process_supervisor.py")


def timer_acabou(status):
    """Timer da sessão ligado e já no zero. Para o relógio, não é hora de fechar."""
    return bool(isinstance(status, dict) and status.get("active") and status.get("expired"))


def app_aberto():
    return owned_process_alive(TILE_PROCESS_PIDFILE, "tile-process", TILE_PROCESS_MARKER)


def tratar_expiracao(status, timeout=2.0):
    """Fecha o app aberto se o timer da sessão acabou. Devolve True se encerrou."""
    if not timer_acabou(status) or not app_aberto():
        return False
    return terminate_owned_process(
        TILE_PROCESS_PIDFILE,
        "tile-process",
        TILE_PROCESS_MARKER,
        timeout=timeout,
    )


def id_de(valor):
    """0x1a, '0x1a' ou '26' → int. Lixo vira None."""
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int):
        return valor if valor > 0 else None
    texto = str(valor).strip().rstrip(",")
    if not texto:
        return None
    try:
        numero = int(texto, 0)
    except (TypeError, ValueError):
        return None
    return numero if numero > 0 else None


def pilha_do_texto(texto):
    """`_NET_CLIENT_LIST_STACKING` de baixo para cima. Ids como int."""
    if not texto or "#" not in texto:
        return []
    resto = texto.split("#", 1)[1]
    pilha = []
    for parte in resto.replace(",", " ").split():
        numero = id_de(parte)
        if numero and numero not in pilha:
            pilha.append(numero)
    return pilha


def janela_do_menu(linhas):
    """Id da janela do menu: o navegador ("Cozy Kids Launcher") ou o nativo ("Beni")."""
    for linha in linhas or []:
        partes = str(linha).split()
        if len(partes) < 4:
            continue
        titulo = " ".join(partes[3:])
        if "Cozy Kids Launcher" in titulo or titulo == "Beni":
            numero = id_de(partes[0])
            if numero:
                return numero
    return None


def _unicos(valores):
    saida = []
    for valor in valores:
        numero = id_de(valor)
        if numero and numero not in saida:
            saida.append(numero)
    return saida


def passos_da_ordem(pilha, bloqueio, apps):
    """O que fazer para a tela de bloqueio ficar na frente do app.

    `pilha` vai de baixo para cima. Sem janela de app, não mexe (soltar o
    "above" é o focus_launcher, senão o próximo app abre atrás do menu).
    A tela só é ativada de novo se algum app estiver na frente dela: repetir
    o ativar a cada volta roubaria o foco do PIN.
    Janela da vigia que não entra na pilha do WM (override-redirect) não é
    ativada por aqui; o Tk já a mantém no topo.
    """
    pilha = _unicos(pilha)
    bloqueio = id_de(bloqueio)
    apps = [a for a in _unicos(apps) if a != bloqueio]
    if not apps:
        return []
    passos = []
    for app in apps:
        passos.append(("skip_taskbar", app))
        passos.append(("below", app))
    if bloqueio and bloqueio in pilha:
        lugar = pilha.index(bloqueio)
        app_na_frente = any(a not in pilha or pilha.index(a) > lugar for a in apps)
        if app_na_frente:
            passos.append(("above", bloqueio))
            passos.append(("ativar", bloqueio))
    return passos


def aplicar_passos(passos, rodar):
    for acao, wid in passos:
        ident = format(int(wid), "#x")
        if acao == "skip_taskbar":
            rodar(["wmctrl", "-i", "-r", ident, "-b", "add,skip_taskbar,skip_pager"])
        elif acao == "below":
            rodar(["wmctrl", "-i", "-r", ident, "-b", "add,below"])
        elif acao == "above":
            rodar(["wmctrl", "-i", "-r", ident, "-b", "add,above"])
        elif acao == "ativar":
            rodar(["wmctrl", "-i", "-a", ident])
        elif acao == "restaurar":
            rodar(["wmctrl", "-i", "-r", ident, "-b", "remove,below"])
            rodar(["wmctrl", "-i", "-r", ident, "-b", "remove,skip_taskbar,skip_pager"])
    return passos


def _rodar(comando, timeout=1):
    return subprocess.run(
        comando,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _x11_disponivel():
    return os.name != "nt" and bool(os.environ.get("DISPLAY")) and bool(shutil.which("wmctrl"))


def arvore(raiz):
    """PIDs do processo e dos descendentes. No Windows, a árvore da plataforma."""
    try:
        raiz = int(raiz)
    except (TypeError, ValueError):
        return []
    if os.name == "nt":
        try:
            import plataforma_windows as win

            return list(win.arvore(raiz))
        except Exception:  # noqa: BLE001
            return [raiz]
    filhos = {}
    try:
        nomes = os.listdir("/proc")
    except OSError:
        return [raiz]
    for nome in nomes:
        if not nome.isdigit():
            continue
        try:
            with open(f"/proc/{nome}/stat", encoding="utf-8", errors="replace") as handle:
                stat = handle.read()
            ppid = int(stat[stat.rindex(")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        filhos.setdefault(ppid, []).append(int(nome))
    saida, fila = [], [raiz]
    while fila and len(saida) < 64:
        pid = fila.pop()
        if pid in saida:
            continue
        saida.append(pid)
        fila.extend(filhos.get(pid, []))
    return saida


def _pids_do_app():
    registro = owned_process(TILE_PROCESS_PIDFILE, "tile-process", TILE_PROCESS_MARKER)
    if not registro:
        return []
    return arvore(registro["pid"])


def _janelas_do_pid(pid, rodar):
    try:
        resultado = rodar(["xdotool", "search", "--onlyvisible", "--pid", str(pid)])
    except (OSError, subprocess.SubprocessError):
        return []
    saida = getattr(resultado, "stdout", "") or ""
    return saida.split()


def _linhas_wmctrl(rodar):
    try:
        resultado = rodar(["wmctrl", "-l"])
    except (OSError, subprocess.SubprocessError):
        return []
    saida = getattr(resultado, "stdout", "") or ""
    if getattr(resultado, "returncode", 0) not in (0, None):
        return []
    return saida.splitlines()


def _pilha_real(rodar):
    if not shutil.which("xprop"):
        return []
    try:
        resultado = rodar(["xprop", "-root", "_NET_CLIENT_LIST_STACKING"])
    except (OSError, subprocess.SubprocessError):
        return []
    return pilha_do_texto(getattr(resultado, "stdout", "") or "")


def janelas_do_app(rodar=None):
    rodar = rodar or _rodar
    janelas = []
    for pid in _pids_do_app():
        janelas.extend(_janelas_do_pid(pid, rodar))
    return _unicos(janelas)


def por_o_bloqueio_na_frente(bloqueio=None, rodar=None, pilha=None, apps=None, menu=None):
    """Sobe a tela de bloqueio e tira o app do Alt+Tab. Sem X11, não faz nada."""
    if rodar is None and not _x11_disponivel():
        return []
    rodar = rodar or _rodar
    if menu is None and pilha is None:
        menu = janela_do_menu(_linhas_wmctrl(rodar))
    if apps is None:
        apps = janelas_do_app(rodar)
    if pilha is None:
        pilha = _pilha_real(rodar)
    bloqueio = id_de(bloqueio) or menu
    passos = passos_da_ordem(pilha, bloqueio, apps)
    return aplicar_passos(passos, rodar)


def restaurar_app(rodar=None, apps=None):
    """Devolve as janelas do app ao Alt+Tab. O tempo foi estendido e o app
    ainda está vivo (o fechamento não tinha conseguido)."""
    if rodar is None and not _x11_disponivel():
        return []
    rodar = rodar or _rodar
    if apps is None:
        apps = janelas_do_app(rodar)
    return aplicar_passos([("restaurar", app) for app in apps], rodar)
