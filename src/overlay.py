#!/usr/bin/env python3
"""App overlay: always-on-top close button + timer for external browser and local apps."""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from urllib.parse import quote
from urllib.request import Request, urlopen

import janelas_seguras
import marca_tk as marca
import quiosque_edge
import telemetria
import timer_fim
from process_state import (
    owned_process,
    owned_process_alive,
    remove_process_record,
    terminate_owned_process,
    write_process_record,
)

HOME = os.path.expanduser("~")
APP_ID = "cozy-kids-launcher"
APP_NAME = "Cozy Kids Launcher"
CACHE_DIR = os.path.join(HOME, ".cache", APP_ID)
BROWSER_PIDFILE = os.path.join(CACHE_DIR, "browser.pid")
TILE_PROCESS_PIDFILE = os.path.join(CACHE_DIR, "tile-process.pid")
OVERLAY_PIDFILE = os.path.join(CACHE_DIR, "overlay.pid")
TILE_PROCESS_MARKER = os.path.join(
    HOME,
    ".local",
    "share",
    APP_ID,
    "process_supervisor.py",
)
OVERLAY_MARKER = os.path.abspath(__file__)
WINDOWS = os.name == "nt"
if WINDOWS:
    import plataforma_windows as win

THEME = {
    "bg": "#ffffff",
    "text": "#333333",
    "close_bg": "#ffebee",
    "close_fg": "#c00",
    "timer_text": "#333333",
}


class X11WindowRaiser:
    """Raise one owned X11/XWayland window without a command dependency."""

    def __init__(self, loader=ctypes.CDLL):
        self.library = None
        self.display = None
        if not os.environ.get("DISPLAY"):
            return
        try:
            library = loader("libX11.so.6")
            library.XOpenDisplay.argtypes = [ctypes.c_char_p]
            library.XOpenDisplay.restype = ctypes.c_void_p
            library.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            library.XFlush.argtypes = [ctypes.c_void_p]
            library.XCloseDisplay.argtypes = [ctypes.c_void_p]
            display = library.XOpenDisplay(None)
        except (AttributeError, OSError):
            return
        if display:
            self.library = library
            self.display = display

    def raise_window(self, window_id):
        if not self.library or not self.display:
            return False
        self.library.XRaiseWindow(self.display, ctypes.c_ulong(int(window_id)))
        self.library.XFlush(self.display)
        return True

    def _top_level(self, window_id):
        """Sobe a árvore até a janela filha da raiz (a "wrapper" do Tk)."""
        lib = self.library
        lib.XQueryTree.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint),
        ]
        lib.XFree.argtypes = [ctypes.c_void_p]
        current = int(window_id)
        for _ in range(8):
            root = ctypes.c_ulong()
            parent = ctypes.c_ulong()
            children = ctypes.c_void_p()
            count = ctypes.c_uint()
            if not lib.XQueryTree(self.display, ctypes.c_ulong(current), ctypes.byref(root),
                                  ctypes.byref(parent), ctypes.byref(children), ctypes.byref(count)):
                break
            if children:
                lib.XFree(children)
            if not parent.value or parent.value == root.value:
                break
            current = parent.value
        return current

    def move_window(self, window_id, x, y):
        if not self.library or not self.display:
            return False
        try:
            target = self._top_level(window_id)
        except (AttributeError, OSError):
            target = int(window_id)
        try:
            self.library.XMoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int]
            self.library.XMoveWindow(self.display, ctypes.c_ulong(target), int(x), int(y))
        except AttributeError:
            return False
        self.library.XFlush(self.display)
        return True

    def close(self):
        if self.library and self.display:
            self.library.XCloseDisplay(self.display)
            self.display = None


def configure_overlay_window(window, nome="pílula"):
    """Apply compositor hints that keep the control above fullscreen apps."""
    if WINDOWS:
        try:
            # o Tk guarda o -toolwindow e o põe de novo quando recria a janela
            window.attributes("-toolwindow", True)
        except tk.TclError:
            pass
    try:
        # Tk runs through XWayland in the supported Wayland sessions. KWin can
        # place a plain topmost XWayland window behind an app after that app
        # enters fullscreen. The EWMH dock type keeps this small control on the
        # panel layer without reserving screen space.
        window.attributes("-type", "dock")
    except tk.TclError:
        pass
    try:
        window.attributes("-topmost", True)
    except tk.TclError:
        pass
    if WINDOWS:
        sem_ativar(window, nome)  # pílula, ‹ Voltar e contagem nunca pegam o foco
    else:
        window.lift()


_SEM_ATIVAR = {}  # nome da janela → hwnd já conferido (o log sai uma vez por hwnd)


def hwnd_de_verdade(window):
    """A janela de nível superior do Tk (a de título "App Overlay"): a raiz (GA_ROOT) da
    janela interna do widget."""
    return win.raiz_da_janela(window.winfo_id())


def retangulo_na_tela(widget):
    """(esquerda, topo, direita, baixo) do widget na tela, ou None."""
    try:
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        return (x, y, x + widget.winfo_width(), y + widget.winfo_height())
    except (tk.TclError, AttributeError):
        return None


def sem_ativar(window, nome="pílula"):
    """Janela do overlay que não recebe foco nem entra no Alt+Tab (só Windows).

    Roteiro 29: o estilo não ficava. O Tk recria a janela de fora (outro HWND) sempre que
    o exstyle que ele controla muda: o -alpha liga e desliga o WS_EX_LAYERED (0,6 parado,
    1,0 com o mouse em cima), e o estilo posto na janela antiga sumia com ela. Por isso:
    o hover não chega a 1,0 no Windows, o -toolwindow vai pelo próprio Tk, e o
    WS_EX_NOACTIVATE é conferido de novo a cada volta do stay_on_top e depois de cada
    mudança de transparência, sempre na janela de agora."""
    if not WINDOWS:
        return
    try:
        window.update_idletasks()
        h = hwnd_de_verdade(window)
        ex = win.nao_ativavel(h)
    except (tk.TclError, ValueError, OSError, AttributeError, TypeError):
        return
    if _SEM_ATIVAR.get(nome) != h:
        _SEM_ATIVAR[nome] = h
        ok = bool(ex & 0x08000000) and bool(ex & 0x80)
        log_windows(f"overlay: {nome} sem ativar (hwnd {h:#x}, exstyle {ex:#x})"
                    + ("" if ok else " — o estilo NÃO ficou"))


def x11_toplevel_id(window):
    """Return the outer X11 frame that the compositor actually stacks."""
    try:
        frame = window.tk.call("wm", "frame", window._w)
        return int(str(frame), 0)
    except (AttributeError, tk.TclError, TypeError, ValueError):
        return int(window.winfo_id())


def api(path, data=None):
    port = os.environ.get("COZY_KIDS_PORT", "38431")
    url = f"http://127.0.0.1:{port}{path}"
    try:
        if data is not None:
            payload = json.dumps(data).encode("utf-8")
            req = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        else:
            req = Request(url)
        with urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


def focus_launcher():
    if WINDOWS:
        record = owned_process(BROWSER_PIDFILE, "browser")
        if record:
            log_windows("overlay: vou trazer o menu para a frente")
            # ao fechar a pílula: no máximo 1 s, numa thread (o menu nunca prende a pílula)
            janelas_seguras.rodar_com_limite(win.ativar_processo, 1.0, record["pid"], True)
        return
    try:
        result = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                titulo = " ".join(line.split()[3:])
                if "Cozy Kids Launcher" in line or APP_NAME in line or titulo == "Beni":
                    wid = line.split()[0]
                    # "above" só para passar na frente agora; se ficar ligado,
                    # o próximo app abre escondido atrás do launcher.
                    subprocess.run(["wmctrl", "-i", "-r", wid, "-b", "add,above"], check=False)
                    subprocess.run(["wmctrl", "-i", "-a", wid], check=False)
                    subprocess.run(["wmctrl", "-i", "-r", wid, "-b", "remove,above"], check=False)
                    return
    except Exception:
        pass
    try:
        record = owned_process(BROWSER_PIDFILE, "browser")
        if not record:
            return
        subprocess.run(
            ["xdotool", "search", "--pid", str(record["pid"]), "windowactivate"],
            capture_output=True, timeout=3, check=False,
        )
    except Exception:
        pass


# Faixas de cor do tempo restante, nas cores da marca: céu (tranquilo) -> amarelo
# (metade) -> laranja (acabando). pill_fg é o texto na pílula marinho; os três têm
# contraste >= 4,8:1 sobre ela e tons bem diferentes entre si.
USAGE_COLORS = {
    "ok": {"bg": "#e8f5e9", "fg": "#1b5e20", "bar": marca.AZUL, "pill_fg": marca.CEU},
    "warn": {"bg": "#fff8e1", "fg": "#7a5200", "bar": marca.AMARELO, "pill_fg": marca.AMARELO},
    "low": {"bg": "#ffebee", "fg": "#b71c1c", "bar": marca.LARANJA, "pill_fg": "#ff8f70"},
}
COUNTDOWN_SECONDS = 10


def usage_band(remaining, limit):
    if remaining is None:
        return "ok"
    if remaining <= 60:
        return "low"
    if limit:
        fraction = remaining / float(limit)
        if fraction <= 0.2:
            return "low"
        if fraction <= 0.5:
            return "warn"
    return "ok"


def format_remaining(seconds):
    seconds = max(0, int(seconds))
    if seconds >= 60:
        return f"{(seconds + 59) // 60} min"
    return f"{seconds} s"


# A barra de tarefas fica escondida (trava_windows), mas o Windows continua reservando
# a faixa dela: um app maximizado para 40 px acima do fim da tela. Esticar a janela
# maximizada não segurava (roteiro 28: o app a devolvia à área em menos de 100 ms).
# Agora a janela maximizada vira "tela cheia sem moldura": sai o estado de maximizada e
# a moldura (título, bordas, botões), e ela ocupa o monitor inteiro. Não mexe em
# preferência do Windows (o "ocultar automaticamente" foi abandonado no roteiro 27).
BORDA_MAX = 16  # o Windows 10 põe a janela maximizada 8 px além da área (a moldura)
TELA_CHEIA_LIMITE = 5  # vezes que o app pode desfazer antes de o overlay desistir


def log_windows(texto):
    """Uma linha no beni-windows.log (o do iniciador), para o teste no PC ver o overlay.
    Com milissegundos (roteiro 32: a última linha antes de um travamento diz o que foi
    feito, e quando)."""
    agora = time.time()
    try:
        with open(os.path.join(CACHE_DIR, "beni-windows.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(agora))
                    + f".{int(agora * 1000) % 1000:03d} " + texto + "\n")
    except OSError:
        pass


def hx(h):
    """hwnd para o log."""
    return f"{h:#x}" if isinstance(h, int) else str(h)


def maximizada_na_area(janela, trabalho, monitor):
    """Retângulos (esquerda, topo, direita, baixo). True se a janela é uma maximizada
    comum: ocupa a área de trabalho, com até 16 px de moldura além dela em cada lado, e
    a área é menor que o monitor (há uma faixa reservada para a barra)."""
    if tuple(trabalho) == tuple(monitor):
        return False
    if janela[0] <= monitor[0] and janela[1] <= monitor[1] and janela[2] >= monitor[2] and janela[3] >= monitor[3]:
        return False  # já cobre o monitor (tela cheia de verdade, o menu)
    sobra = (trabalho[0] - janela[0], trabalho[1] - janela[1], janela[2] - trabalho[2], janela[3] - trabalho[3])
    return all(0 <= lado <= BORDA_MAX for lado in sobra)


class TelaCheia:
    """Decide, a cada volta, o que fazer com cada janela do app: "tela_cheia" (tirar a
    moldura e cobrir o monitor), "desistir" (o app desfaz toda hora: devolve a moldura
    e a maximiza de novo, para ele continuar usável) ou None.

    Só janela MAXIMIZADA. Roteiro 32: a regra do roteiro 31 para janela comum do tamanho
    do monitor (o Tux Paint com --windowsize, título para fora da tela) saiu: o SDL
    desfazia 4 vezes, e mexer no estilo durante o carregamento é a 1ª suspeita do Tux
    Paint que trava no splash. Ele fica como no pacote 27."""

    def __init__(self, limite=TELA_CHEIA_LIMITE):
        self.limite = limite
        self.feitas = {}  # janela → quantas vezes o app desfez
        self.desistidas = set()

    def passo(self, janela, maximizada, retangulo, trabalho, monitor, sem_moldura):
        if janela in self.desistidas:
            return None
        if janela not in self.feitas:
            if maximizada and maximizada_na_area(retangulo, trabalho, monitor):
                self.feitas[janela] = 0
                return "tela_cheia"
            return None
        if sem_moldura and tuple(retangulo) == tuple(monitor):
            return None  # continua como deixamos
        self.feitas[janela] += 1
        if self.feitas[janela] >= self.limite:
            self.desistidas.add(janela)
            return "desistir"
        return "tela_cheia"

    def nao_deu(self, janela):
        """O app não respondeu e nada foi feito: esta volta não conta."""
        if self.feitas.get(janela) == 0:
            del self.feitas[janela]
        elif janela in self.feitas:
            self.feitas[janela] -= 1


TIMER_COR_AVISO = "#fde047"
TIMER_COR_FIM = "#fca5a5"


def emoji_visivel(emoji):
    """Emoji para escrever na tela. Capa de jogo ("img:covers/...") não é texto."""
    texto = str(emoji or "")
    corte = texto.find("img:")
    if corte >= 0:
        texto = texto[:corte]
    return texto.strip()


def rotulo_da_pilula(uso, timer, cor_padrao):
    """O que a pílula mostra: o tempo que acaba PRIMEIRO, entre o limite da categoria e o
    timer da sessão (roteiro 26: mostrava "28 min" de Aprender com o timer em 3 min).
    uso: None ou {"restante", "limite", "emoji"}; timer: None ou {"restante", "expirado",
    "aviso"}. Devolve (texto, cor) ou ("", None)."""
    if timer and timer.get("expirado"):
        return "⏰ Acabou!", TIMER_COR_FIM
    # Aprender parado: o tempo não está correndo até a criança mexer.
    if uso and uso.get("pausado"):
        return "⏸ mexa para contar", cor_padrao
    t = timer.get("restante") if timer else None
    u = uso.get("restante") if uso else None
    if t is not None and (u is None or t < u):
        return f"⏱️ {format_remaining(t)}", (TIMER_COR_AVISO if timer.get("aviso") else cor_padrao)
    if u is not None:
        band = USAGE_COLORS[usage_band(u, uso.get("limite"))]
        return f"{emoji_visivel(uso.get('emoji')) or '⏳'} {format_remaining(u)}", band["pill_fg"]
    return "", None


def tile_is_blocked(status, tile_id):
    if not tile_id or not isinstance(status, dict):
        return False
    blocked = status.get("blockedTileIds", [])
    if not isinstance(blocked, list):
        blocked = []
    return status.get("profileAllowed") is False or tile_id in blocked


# Visual da barrinha (❌ + tempo): pílula marinho da marca, meio transparente.
PILL_BG = marca.MARINHO
PILL_TEXT = marca.BG
PILL_ALPHA_IDLE = 0.6
# No Windows, 1,0 tira o WS_EX_LAYERED e faz o Tk recriar a janela (e perder o
# WS_EX_NOACTIVATE); 0,99 é igual à vista.
PILL_ALPHA_HOVER = 0.99 if WINDOWS else 1.0
PILL_FONT = marca.FONTE_CORPO   # símbolos dos botões (✕ ✥ ‹); os textos usam marca.titulo()
BUTTON_SIZE = 46
CORNER_MARGIN = 14
CORNERS = ("tl", "tr", "br", "bl")  # ordem do toque em ✥ (sentido horário)
CORNER_FILE = os.path.join(CACHE_DIR, "overlay-corner.json")


def canto_padrao(tile_id):
    """Canto inicial do app no catálogo do Windows (ex.: Tux Paint no direito, para não
    cobrir as ferramentas). App maximizado vai para o superior direito: no esquerdo a
    pílula cobre a barra de menus (Come-Come, Scratch); no direito cobre só os botões
    da janela, e a pílula já fecha o app. Senão, o superior esquerdo."""
    try:
        import catalogo_windows

        item = catalogo_windows.por_id(tile_id or "")
        if item and item.get("overlay") in CORNERS:
            return item["overlay"]
        if item and item.get("maximizar") is True:
            return "tr"
    except Exception:  # noqa: BLE001
        pass
    return "tl"


def maximizar_no_inicio(tile_id):
    """"maximizar": true no catálogo do Windows."""
    try:
        import catalogo_windows

        item = catalogo_windows.por_id(tile_id or "")
        return bool(item and item.get("maximizar") is True)
    except Exception:  # noqa: BLE001
        return False


def sem_moldura_no_inicio(tile_id):
    """A tela cheia sem moldura vale para todo app, menos os com "sem_moldura": false no
    catálogo do Windows. Roteiro 33: o Pingus (SDL) a desfazia 4 vezes e o overlay
    desistia; o desfaz-refaz de 5 s é feio. Esses ficam só maximizados."""
    try:
        import catalogo_windows

        item = catalogo_windows.por_id(tile_id or "")
        return not (item and item.get("sem_moldura") is False)
    except Exception:  # noqa: BLE001
        return True


class PrimeiraJanela:
    """Traz o app para a frente quando a janela dele aparece (Windows).

    Um app que demora a abrir (o SuperTuxKart leva uns 3 s, e mais na 1ª vez, quando
    compila os shaders) às vezes nasce atrás do menu: o Windows não deixa um processo
    tomar a frente se o usuário mexeu em outra janela nesse meio-tempo. Roteiro 24:
    só a pílula aparecia. Cada passo recebe se a janela já existe e se o app (ou esta
    pílula) está na frente; devolve "esperar", "trazer" ou "fim". Para de insistir
    quando o app ficou na frente por 3 passos, depois de 5 tentativas ou no limite."""

    def __init__(self, limite=180, tentativas=5, confirmacoes=3):
        self.limite = limite
        self.tentativas = tentativas
        self.confirmacoes = confirmacoes
        self.voltas = 0
        self.trazidas = 0
        self.na_frente = 0

    def passo(self, tem_janela, app_na_frente):
        self.voltas += 1
        if self.voltas > self.limite:
            return "fim"
        if not tem_janela:
            return "esperar"
        if app_na_frente:
            self.na_frente += 1
            return "fim" if self.na_frente >= self.confirmacoes else "esperar"
        self.na_frente = 0
        if self.trazidas >= self.tentativas:
            return "fim"
        self.trazidas += 1
        return "trazer"


def load_corner(tile_id):
    try:
        with open(CORNER_FILE, encoding="utf-8") as handle:
            corner = json.load(handle).get(tile_id or "_") or canto_padrao(tile_id)
    except (OSError, ValueError, AttributeError):
        corner = canto_padrao(tile_id)
    return corner if corner in CORNERS else "tl"


def back_corner_key(tile_id):
    """Chave do canto do ‹ Voltar no mesmo arquivo dos cantos da pílula."""
    return (tile_id or "_") + "#voltar"


def load_back_corner(tile_id):
    """Canto do ‹ Voltar deste site; o padrão é o inferior esquerdo."""
    try:
        with open(CORNER_FILE, encoding="utf-8") as handle:
            corner = json.load(handle).get(back_corner_key(tile_id)) or "bl"
    except (OSError, ValueError, AttributeError):
        corner = "bl"
    return corner if corner in CORNERS else "bl"


def stacked_offset(corner, other_height, gap=10):
    """Deslocamento vertical da pílula quando divide o canto com o ‹ Voltar: em cima
    ela fica logo abaixo dele; embaixo, logo acima."""
    step = other_height + gap
    return step if corner in ("tl", "tr") else -step


def save_corner(tile_id, corner):
    try:
        with open(CORNER_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[tile_id or "_"] = corner
    try:
        with open(CORNER_FILE, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
    except OSError:
        pass


def corner_position(corner, width, height, screen_w, screen_h, margin=CORNER_MARGIN):
    x = margin if corner in ("tl", "bl") else screen_w - width - margin
    y = margin if corner in ("tl", "tr") else screen_h - height - margin
    return max(0, x), max(0, y)


def nearest_corner(center_x, center_y, screen_w, screen_h):
    left = center_x < screen_w / 2
    top = center_y < screen_h / 2
    return {(True, True): "tl", (False, True): "tr", (False, False): "br", (True, False): "bl"}[(left, top)]


def process_tree(root_pid):
    """PIDs do processo e de todos os descendentes (lido de /proc)."""
    if WINDOWS:
        return win.arvore(root_pid)
    children = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="utf-8") as handle:
                stat = handle.read()
            ppid = int(stat[stat.rindex(")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(ppid, []).append(int(entry))
    result, pending = [], [int(root_pid)]
    while pending:
        pid = pending.pop()
        result.append(pid)
        pending.extend(children.get(pid, []))
    return result


def rounded_rectangles(width, height, radius):
    """Retângulos (x, y, w, h) que formam um retângulo de cantos redondos."""
    radius = max(0, min(radius, width // 2, height // 2))
    rects = []
    for row in range(radius):
        dy = radius - row - 0.5
        inset = int(round(radius - (radius * radius - dy * dy) ** 0.5))
        rects.append((inset, row, width - 2 * inset, 1))
        rects.append((inset, height - row - 1, width - 2 * inset, 1))
    rects.append((0, radius, width, height - 2 * radius))
    return rects


class _XRectangle(ctypes.Structure):
    _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short),
                ("width", ctypes.c_ushort), ("height", ctypes.c_ushort)]


def shape_window_rounded(window, width, height, radius):
    """Recorta a janela com cantos redondos (extensão X Shape). Falha em silêncio."""
    try:
        if not os.environ.get("DISPLAY"):
            return False
        xlib = ctypes.CDLL("libX11.so.6")
        xext = ctypes.CDLL("libXext.so.6")
        xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        xlib.XOpenDisplay.restype = ctypes.c_void_p
        xlib.XFlush.argtypes = [ctypes.c_void_p]
        xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        xext.XShapeCombineRectangles.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(_XRectangle), ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ]
        rects = rounded_rectangles(int(width), int(height), int(radius))
        array = (_XRectangle * len(rects))(*[_XRectangle(*r) for r in rects])
        display = xlib.XOpenDisplay(None)
        if not display:
            return False
        try:
            # ShapeBounding=0, ShapeSet=0, Unsorted=0
            raiser = X11WindowRaiser()
            try:
                target = raiser._top_level(x11_toplevel_id(window)) if raiser.display else x11_toplevel_id(window)
            finally:
                raiser.close()
            xext.XShapeCombineRectangles(display, ctypes.c_ulong(target),
                                         0, 0, 0, array, len(rects), 0, 0)
            xlib.XFlush(display)
        finally:
            xlib.XCloseDisplay(display)
        return True
    except (OSError, AttributeError, tk.TclError, ValueError):
        return False


class RoundButton(tk.Canvas):
    """Botão redondo desenhado num Canvas (o tk.Button não arredonda)."""

    def __init__(self, parent, glyph, fill, fg, hover, command=None, size=BUTTON_SIZE, font_size=20, nome=""):
        super().__init__(parent, width=size, height=size, bg=PILL_BG,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.fill, self.hover = fill, hover
        self.oval = self.create_oval(2, 2, size - 2, size - 2, fill=fill, outline="")
        self.create_text(size / 2, size / 2 - 1, text=glyph, fill=fg,
                         font=(PILL_FONT, font_size, "bold"))
        self.command = command
        self.nome = nome or glyph
        if WINDOWS:
            # roteiro 32: o ✕ não fechava o app travado e o log não dizia nada
            self.bind("<ButtonPress-1>", self._log_aperto, add="+")
        self.bind("<Enter>", lambda _e: self.itemconfig(self.oval, fill=self.hover), add="+")
        self.bind("<Leave>", lambda _e: self.itemconfig(self.oval, fill=self.fill), add="+")
        if command is not None:
            self.bind("<ButtonRelease-1>", self._release, add="+")

    def _log_aperto(self, event):
        log_windows(f"overlay: botão {self.nome} apertado ({event.x},{event.y})")

    def _release(self, event):
        # Só conta o clique se o dedo/mouse ainda estiver em cima do botão.
        dentro = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        if WINDOWS:
            log_windows(f"overlay: botão {self.nome} solto ({event.x},{event.y}) "
                        + ("dentro" if dentro else "fora; não conta"))
        if dentro:
            self.command()


class AppOverlay:
    fechando = False  # o app já está sendo fechado (pelo ✕, pelo tempo ou pelo vigia do ✕)
    retangulo_do_x = None  # (esquerda, topo, direita, baixo) do ✕ na tela, para o vigia do ✕
    maximizada = False
    ultimo_tique = 0.0  # monotonic da última volta do stay_on_top (o Tk está rodando?)
    _trava_fechar = threading.Lock()

    def __init__(self, mode, url, label, tile_id=""):
        self.mode = mode
        self.url = url
        self.label = label
        self.tile_id = tile_id
        self.corner = load_corner(tile_id)
        self.shape_size = None
        self.drag_start = None
        self.dragging = False
        self.idle_job = None

        self.root = tk.Tk()
        marca.fonte_titulo(self.root)  # carrega a Fredoka (tempo, Voltar, aviso)
        self.root.title("App Overlay")
        self.root.overrideredirect(True)
        self.root.configure(bg=PILL_BG)
        self.root.geometry("120x60+14+14")
        self.root.resizable(False, False)
        configure_overlay_window(self.root)
        if not WINDOWS:
            # no Windows a pílula nunca pega o foco (sem_ativar): o teclado fica com o app
            self.root.focus_force()
        self.x11_raiser = X11WindowRaiser()
        self.set_alpha(PILL_ALPHA_IDLE)

        self.frame = tk.Frame(self.root, bg=PILL_BG, bd=0, padx=6, pady=6)
        self.frame.pack(fill=tk.BOTH, expand=True)

        # ‹ Voltar: só em sites (é o Alt+← do navegador). Começa no canto inferior
        # esquerdo e, como a pílula, pode ser arrastado para outro canto.
        self.back_window = None
        self.back_corner = load_back_corner(tile_id)
        self.back_drag = None
        if mode == "external":
            self.back_window = self.build_back_window()
        self.close_btn = RoundButton(self.frame, "✕", marca.LARANJA, "#ffffff", marca.LARANJA_ESCURO,
                                     command=lambda: self.on_close("✕"))
        self.close_btn.pack(side=tk.LEFT, padx=3)

        self.timer_lbl = tk.Label(self.frame, text="", font=marca.titulo(15),
                                  bg=PILL_BG, fg=PILL_TEXT, padx=6)

        self.move_btn = RoundButton(self.frame, "✥", marca.AZUL, marca.CEU_SUAVE, marca.AZUL_ESCURO,
                                    size=34, font_size=16)
        self.move_btn.pack(side=tk.RIGHT, padx=(3, 1))

        # Arrastar pela barra (tempo ou ✥); tocar no ✥ muda de canto.
        for widget in (self.frame, self.timer_lbl, self.move_btn):
            widget.bind("<ButtonPress-1>", self.on_drag_start, add="+")
            widget.bind("<B1-Motion>", self.on_drag_motion, add="+")
            widget.bind("<ButtonRelease-1>", self.on_drag_end, add="+")
        self.root.bind("<Enter>", self.on_enter, add="+")
        self.root.bind("<Leave>", self.on_leave, add="+")

        # Limites diários por categoria
        self.usage_active = None
        self.usage_label = None
        self.uso_pilula = None  # {"restante", "limite", "emoji"} do limite da categoria
        self.timer_pilula = None  # {"fim" (monotonic), "expirado", "aviso"} do timer
        self.countdown_window = None
        self.countdown_deadline = None
        self.countdown_number = None
        self.countdown_geometry = ""
        self.countdown_position = None
        self.closing = False
        self.erros_logados = set()
        # roteiro 31: o que mexe em janela de outro app roda aqui, nunca na thread do Tk
        self.trabalho = janelas_seguras.Trabalhador("overlay-janelas", ao_erro=self.erro_no_trabalho)
        # roteiro 32: só mexe numa janela de outro app depois que ela está de pé
        self.de_pe = janelas_seguras.DePe()
        if WINDOWS:
            self.root.report_callback_exception = self.erro_do_tk
            threading.Thread(target=self.vigiar_o_x, name="vigia-do-x", daemon=True).start()

        self.place()
        self.root.after(0, self.poll_process)
        self.root.after(0, self.poll_timer)
        if WINDOWS and maximizar_no_inicio(tile_id):
            self.root.after(500, lambda: self.maximize_app(120))
        # special:external-browser no Windows: a 2ª janela do Edge (pop-up, diálogo
        # de arquivo, Ctrl+N) não vira o app. O vigia fecha na thread de trabalho.
        self.quiosque = None
        self.quiosque_logados = set()
        if WINDOWS:
            self.root.after(300, lambda: self.trazer_app_quando_abrir(PrimeiraJanela()))
            if sem_moldura_no_inicio(tile_id):
                self.root.after(1000, lambda: self.esticar_app(TelaCheia()))
            if mode == "external":
                self.quiosque = quiosque_edge.Estado()
                self.root.after(250, self.vigiar_quiosque)
        self.root.after(200, self.poll_usage)
        self.root.after(0, self.stay_on_top)

    def stay_on_top(self):
        """Periodically force this window to the front so it stays visible over kiosk apps."""
        if WINDOWS:
            # no Windows o lift/-topmost do Tk podem ativar a pílula: por cima com
            # SWP_NOACTIVATE, conferindo o estilo na janela de agora
            sem_ativar(self.root, "pílula")
            self.retangulo_do_x = retangulo_na_tela(self.close_btn)
            self.ultimo_tique = time.monotonic()
            if self.back_window is not None:
                sem_ativar(self.back_window, "‹ Voltar")
            if self.countdown_window is not None:
                try:
                    self.countdown_window.geometry(self.countdown_geometry)
                    if self.countdown_position and (self.countdown_window.winfo_rootx(),
                                                    self.countdown_window.winfo_rooty()) != self.countdown_position:
                        win.mover_por_cima(hwnd_de_verdade(self.countdown_window), *self.countdown_position)
                except (tk.TclError, OSError):
                    pass
                sem_ativar(self.countdown_window, "contagem")
            self.root.after(500, self.stay_on_top)
            return
        try:
            self.root.lift()
            self.root.attributes("-topmost", True)
            # Mutter can restack a fullscreen XWayland app above Tk even though
            # Tk still reports the topmost attribute. Raise only this overlay's
            # own XID directly; no global window lookup or extra tool is needed.
            self.x11_raiser.raise_window(x11_toplevel_id(self.root))
            if self.back_window is not None:
                self.back_window.lift()
                self.back_window.attributes("-topmost", True)
            if self.countdown_window is not None:
                # Alguns apps em tela cheia fazem o WM jogar a janela para 0,0.
                # (o Tux Paint, p.ex.) — por isso movemos direto pelo X11.
                self.countdown_window.geometry(self.countdown_geometry)
                if self.countdown_position:
                    window_id = x11_toplevel_id(self.countdown_window)
                    if (self.countdown_window.winfo_rootx(), self.countdown_window.winfo_rooty()) != self.countdown_position:
                        if WINDOWS:
                            win.mover_por_cima(int(self.countdown_window.wm_frame(), 16), *self.countdown_position)
                        else:
                            self.x11_raiser.move_window(window_id, *self.countdown_position)
                self.countdown_window.lift()
                self.countdown_window.attributes("-topmost", True)
                self.x11_raiser.raise_window(x11_toplevel_id(self.countdown_window))
        except tk.TclError:
            pass
        self.root.after(500, self.stay_on_top)

    # ----- aparência e posição -----
    def set_alpha(self, value):
        try:
            self.root.attributes("-alpha", value)
        except tk.TclError:
            pass
        sem_ativar(self.root, "pílula")

    def on_enter(self, _event=None):
        if self.idle_job:
            self.root.after_cancel(self.idle_job)
            self.idle_job = None
        self.set_alpha(PILL_ALPHA_HOVER)

    def on_leave(self, _event=None):
        if self.idle_job:
            self.root.after_cancel(self.idle_job)
        self.idle_job = self.root.after(1200, lambda: self.set_alpha(PILL_ALPHA_IDLE))

    def build_back_window(self):
        window = tk.Toplevel(self.root)
        window.overrideredirect(True)
        window.configure(bg=PILL_BG)
        configure_overlay_window(window, "‹ Voltar")
        try:
            window.attributes("-alpha", PILL_ALPHA_IDLE)
        except tk.TclError:
            pass
        sem_ativar(window, "‹ Voltar")  # o -alpha recria a janela no Windows
        box = tk.Frame(window, bg=PILL_BG, padx=6, pady=6, cursor="hand2")
        box.pack(fill=tk.BOTH, expand=True)
        arrow = RoundButton(box, "‹", marca.CEU, marca.MARINHO, marca.CEU_SUAVE, font_size=26)
        arrow.pack(side=tk.LEFT)
        text = tk.Label(box, text="Voltar", font=marca.titulo(15), bg=PILL_BG,
                        fg=PILL_TEXT, padx=8, cursor="hand2")
        text.pack(side=tk.LEFT)

        def press(event):
            self.back_drag = (event.x_root, event.y_root, window.winfo_rootx(), window.winfo_rooty(), False)

        def motion(event):
            if not self.back_drag:
                return
            sx, sy, wx, wy, moving = self.back_drag
            dx, dy = event.x_root - sx, event.y_root - sy
            if not moving and abs(dx) + abs(dy) < 10:
                return
            self.back_drag = (sx, sy, wx, wy, True)
            window.geometry(f"+{wx + dx}+{wy + dy}")

        def release(event):
            drag, self.back_drag = self.back_drag, None
            if drag and drag[4]:
                # arrastou: vai para o canto mais perto e guarda para este site
                self.back_corner = nearest_corner(window.winfo_rootx() + self.back_width / 2,
                                                  window.winfo_rooty() + self.back_height / 2,
                                                  window.winfo_screenwidth(),
                                                  window.winfo_screenheight())
                save_corner(back_corner_key(self.tile_id), self.back_corner)
                self.place_back()
                self.place()
                self.devolver_foco_ao_app()
                return
            widget = event.widget
            if 0 <= event.x <= widget.winfo_width() and 0 <= event.y <= widget.winfo_height():
                self.on_back()

        def alpha(value):
            try:
                window.attributes("-alpha", value)
            except tk.TclError:
                pass
            sem_ativar(window, "‹ Voltar")

        for widget in (box, arrow, text):
            widget.bind("<ButtonPress-1>", press, add="+")
            widget.bind("<B1-Motion>", motion, add="+")
            widget.bind("<ButtonRelease-1>", release, add="+")
        window.bind("<Enter>", lambda _e: alpha(PILL_ALPHA_HOVER), add="+")
        window.bind("<Leave>", lambda _e: window.after(1200, lambda: alpha(PILL_ALPHA_IDLE)), add="+")
        window.update_idletasks()
        width, height = box.winfo_reqwidth(), box.winfo_reqheight()
        self.back_width, self.back_height = width, height
        x, y = corner_position(self.back_corner, width, height,
                               window.winfo_screenwidth(), window.winfo_screenheight())
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.update_idletasks()
        shape_window_rounded(window, width, height, height // 2)
        return window

    def place_back(self):
        if self.back_window is None:
            return
        x, y = corner_position(self.back_corner, self.back_width, self.back_height,
                               self.back_window.winfo_screenwidth(), self.back_window.winfo_screenheight())
        self.back_window.geometry(f"{self.back_width}x{self.back_height}+{x}+{y}")

    def size(self):
        try:
            self.root.update_idletasks()
            return self.frame.winfo_reqwidth(), self.frame.winfo_reqheight()
        except tk.TclError:
            return 120, 60

    def place(self):
        width, height = self.size()
        x, y = corner_position(self.corner, width, height,
                               self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        if self.back_window is not None and self.corner == self.back_corner:
            y += stacked_offset(self.corner, self.back_height)  # junto do ‹ Voltar, sem cobrir
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        if self.shape_size != (width, height):
            self.root.update_idletasks()
            if shape_window_rounded(self.root, width, height, height // 2):
                self.shape_size = (width, height)

    def set_timer_text(self, text, fg=PILL_TEXT):
        if text:
            self.timer_lbl.config(text=text, fg=fg)
            if not self.timer_lbl.winfo_ismapped():
                self.timer_lbl.pack(side=tk.LEFT, padx=(4, 2))
        else:
            self.timer_lbl.config(text="")
            self.timer_lbl.pack_forget()
        self.place()

    def on_drag_start(self, event):
        self.drag_start = (event.x_root, event.y_root,
                           self.root.winfo_rootx(), self.root.winfo_rooty())
        self.dragging = False

    def on_drag_motion(self, event):
        if not self.drag_start:
            return
        sx, sy, wx, wy = self.drag_start
        dx, dy = event.x_root - sx, event.y_root - sy
        if not self.dragging and abs(dx) + abs(dy) < 10:
            return
        self.dragging = True
        self.root.geometry(f"+{wx + dx}+{wy + dy}")

    def on_drag_end(self, event):
        if not self.drag_start:
            return
        if self.dragging:
            width, height = self.size()
            self.corner = nearest_corner(self.root.winfo_rootx() + width / 2,
                                         self.root.winfo_rooty() + height / 2,
                                         self.root.winfo_screenwidth(),
                                         self.root.winfo_screenheight())
        elif event.widget is self.move_btn:
            self.corner = CORNERS[(CORNERS.index(self.corner) + 1) % len(CORNERS)]
        else:
            self.drag_start = None
            return
        self.drag_start = None
        self.dragging = False
        save_corner(self.tile_id, self.corner)
        self.place()
        self.devolver_foco_ao_app()

    def devolver_foco_ao_app(self):
        """No Windows, arrastar a pílula ou o ‹ Voltar dá o foco à janela do Tk, e a
        barra de tarefas aparece por cima do app em tela cheia (o Edge em quiosque)
        até a criança clicar nele. Devolve o foco ao app logo depois de soltar."""
        if not WINDOWS:
            return
        record = owned_process(TILE_PROCESS_PIDFILE, "tile-process")
        if not record:
            return
        self.pedir_janela("devolver o foco", self.trazer_app, record["pid"])

    def on_back(self):
        """Volta uma página no navegador do tile (Alt+←)."""
        record = owned_process(TILE_PROCESS_PIDFILE, "tile-process")
        if not record:
            return
        if WINDOWS:
            self.pedir_janela("voltar", self.voltar_no_app, record["pid"])
            return
        windows = []
        try:
            for pid in process_tree(record["pid"]):
                found = subprocess.run(["xdotool", "search", "--onlyvisible", "--pid", str(pid)],
                                       capture_output=True, text=True, timeout=2)
                windows.extend(found.stdout.split())
        except (OSError, subprocess.SubprocessError):
            return
        if not windows:
            return
        try:
            subprocess.run(["xdotool", "windowactivate", "--sync", windows[0],
                            "key", "--clearmodifiers", "alt+Left"],
                           capture_output=True, timeout=3, check=False)
        except (OSError, subprocess.SubprocessError):
            pass

    def voltar_no_app(self, pid):
        log_windows(f"overlay: vou mandar Alt+← ao app (pid {pid})")
        hwnd = None
        if getattr(self, "quiosque", None) is not None:
            hwnds = self._hwnds_do_app(pid)
            if not hwnds:
                log_windows("overlay: sem a janela do quiosque para o Alt+←")
                return
            hwnd = hwnds[0]
        win.alt_esquerda(pid, hwnd)

    def vigiar_quiosque(self):
        """Enquanto o site/jogo está aberto: fecha janela nova do Edge na thread de trabalho."""
        if self.closing or self.quiosque is None:
            return
        self.pedir_janela("quiosque", self.passo_do_quiosque)
        self.root.after(250, self.vigiar_quiosque)

    def passo_do_quiosque(self):
        """Na thread de trabalho. PostMessage não espera o Edge."""
        record = owned_process(TILE_PROCESS_PIDFILE, "tile-process")
        if not record or self.quiosque is None:
            return
        try:
            descritas = win.descrever_janelas(win.arvore(record["pid"]))
            for janela in self.quiosque.observar(descritas):
                hwnd = janela["hwnd"]
                win.fechar_extra(hwnd, janela.get("classe"))
                if hwnd in self.quiosque_logados:
                    continue
                self.quiosque_logados.add(hwnd)
                log_windows(
                    "quiosque: fechei janela extra do Edge ("
                    f"{janela.get('classe')}, {quiosque_edge.titulo_curto(janela.get('titulo'))})"
                )
        except Exception as erro:  # noqa: BLE001 — a volta seguinte tenta de novo
            self.log_uma_vez(f"overlay: erro no quiosque: {type(erro).__name__}: {erro}")

    # ----- limites por categoria -----
    def poll_usage(self):
        if self.closing:
            return
        path = "/api/usage/status"
        if self.tile_id:
            path += "?tile=" + quote(self.tile_id, safe="")
        data = api(path)
        active = data.get("active") if isinstance(data, dict) and data.get("enabled") else None
        if isinstance(active, dict) and active.get("tileId") == self.tile_id \
                and active.get("remainingSeconds") is not None:
            self.usage_active = active
            remaining = int(active.get("remainingSeconds") or 0)
            self.update_usage_label(active, remaining)
            if active.get("paused"):
                # o tempo de Aprender parou: a contagem grande volta quando contar de novo
                if self.countdown_window is not None:
                    self.hide_countdown()
            elif remaining <= COUNTDOWN_SECONDS:
                deadline = time.monotonic() + remaining
                if self.countdown_deadline is None or abs(deadline - self.countdown_deadline) > 1.5:
                    self.countdown_deadline = deadline
                if self.countdown_window is None:
                    self.show_countdown(active)
            elif self.countdown_window is not None:
                # Os pais aumentaram o limite: some a contagem.
                self.hide_countdown()
        else:
            self.usage_active = None
            self.uso_pilula = None
            self.atualizar_pilula()
            if self.countdown_window is not None:
                self.hide_countdown()
        self.root.after(1000, self.poll_usage)

    def update_usage_label(self, active, remaining):
        self.uso_pilula = {"restante": remaining, "limite": active.get("limitSeconds"),
                           "emoji": active.get("categoryEmoji"),
                           "pausado": bool(active.get("paused"))}
        self.atualizar_pilula()

    def atualizar_pilula(self):
        if self.fechando:
            return
        # O relógio local chegou a zero antes da próxima pergunta ao servidor
        # (o poll é de 5 s): confirma e, se expirou, fecha como o ✕.
        if self.timer_pilula and not self.timer_pilula.get("expirado") \
                and self.timer_pilula.get("fim", 0) <= time.monotonic():
            self.confirmar_timer()
            if self.fechando:
                return
        if self.timer_pilula and self.timer_pilula.get("expirado"):
            # Mesmo fechar do ✕ e do fim da contagem da categoria. Motivo próprio
            # para não mexer na janela da contagem da categoria, que já cobre a tela.
            self.on_close("acabou o timer")
            return
        timer = None
        if self.timer_pilula:
            timer = dict(self.timer_pilula)
            timer["restante"] = max(0, int(round(timer.pop("fim") - time.monotonic())))
        texto, cor = rotulo_da_pilula(self.uso_pilula, timer, PILL_TEXT)
        if texto != self.usage_label:
            self.usage_label = texto
            self.set_timer_text(texto, cor or PILL_TEXT)

    def show_countdown(self, active):
        window = tk.Toplevel(self.root)
        self.countdown_window = window
        window.overrideredirect(True)
        configure_overlay_window(window, "contagem")
        sw = window.winfo_screenwidth()
        sh = window.winfo_screenheight()
        ww, wh = min(820, sw - 40), min(440, sh - 40)
        self.countdown_geometry = f"{ww}x{wh}+{(sw - ww) // 2}+{(sh - wh) // 2}"
        window.geometry(self.countdown_geometry)
        self.countdown_position = ((sw - ww) // 2, (sh - wh) // 2)
        border = marca.LARANJA
        card = marca.BG
        window.configure(bg=border)
        box = tk.Frame(window, bg=card)
        box.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        label = (active.get("categoryLabel") or "").strip()
        if active.get("limitedBy") == "category" and label:
            title = f"⏳ Seu tempo de {label.lower()} está acabando!"
        else:
            title = "⏳ Seu tempo de hoje está acabando!"
        tk.Label(box, text=title, font=marca.titulo(26), bg=card,
                 fg=marca.MARINHO, wraplength=ww - 60).pack(pady=(26, 0))
        self.countdown_number = tk.Label(box, text="", font=marca.titulo(120),
                                         bg=card, fg=border)
        self.countdown_number.pack(expand=True)
        alternatives = [
            alt for alt in active.get("alternatives", [])
            if (alt.get("availableSeconds") or 0) > 0
        ]
        if alternatives:
            parts = [
                f"{alt.get('label', '')} {emoji_visivel(alt.get('emoji', ''))} ({format_remaining(alt.get('availableSeconds'))})".replace("  ", " ")
                for alt in alternatives
            ]
            hint = "Você ainda pode brincar de " + " ou ".join(parts)
            hint_color = marca.AZUL_ESCURO
        else:
            hint = "Por hoje acabou. Amanhã tem mais! 😊"
            hint_color = marca.MARINHO
        tk.Label(box, text=hint, font=(marca.FONTE_CORPO, 20, "bold"), bg=card,
                 fg=hint_color, wraplength=ww - 60).pack(pady=(0, 28))
        self.tick_countdown()

    def tick_countdown(self):
        if self.countdown_window is None or self.countdown_deadline is None:
            return
        left = self.countdown_deadline - time.monotonic()
        shown = max(0, int(left + 0.999))
        try:
            self.countdown_number.config(text=str(shown) if shown > 0 else "0")
        except tk.TclError:
            return
        if left <= 0:
            self.closing = True
            # Mesmo caminho do ❌: fecha o app e volta para o launcher.
            self.root.after(400, lambda: self.on_close("acabou o tempo"))
            return
        self.root.after(200, self.tick_countdown)

    def hide_countdown(self):
        try:
            if self.countdown_window is not None:
                self.countdown_window.destroy()
        except tk.TclError:
            pass
        self.countdown_window = None
        self.countdown_deadline = None
        self.countdown_number = None

    def confirmar_timer(self):
        """O fim local pode estar adiantado (os pais deram mais tempo). Atualiza
        a pílula; quem fecha é o atualizar_pilula, se o servidor disser que acabou."""
        data = api("/api/timer/status")
        if not isinstance(data, dict) or "active" not in data:
            return
        if data.get("active"):
            self.timer_pilula = {
                "fim": time.monotonic() + int(data.get("remainingSeconds") or 0),
                "expirado": bool(data.get("expired")),
                "aviso": bool(data.get("warning")),
            }
        else:
            self.timer_pilula = None

    def on_close(self, motivo="✕"):
        if WINDOWS:
            log_windows("overlay: ✕ tocado" if motivo == "✕" else f"overlay: fechando ({motivo})")
        if motivo == "acabou o timer" and not WINDOWS and not self.fechando:
            # Antes de matar: a janela do menu (no Linux, a do navegador) fica
            # na frente e a do app sai do Alt+Tab. O fechar espera o processo.
            try:
                timer_fim.por_o_bloqueio_na_frente()
            except Exception:  # noqa: BLE001 — fechar o app não pode falhar por causa do WM
                pass
        self.fechar_app(motivo)
        focus_launcher()
        self.root.destroy()
        sys.exit(0)

    def fechar_app(self, motivo):
        """Encerra o supervisor do app (TerminateProcess no Windows). O Job Object dele tem
        KILL_ON_JOB_CLOSE: o Windows leva a árvore inteira, mesmo com o app travado.
        Uma vez só, venha do ✕ (Tk), do vigia do ✕ ou do fim do tempo."""
        with self._trava_fechar:
            if self.fechando:
                return False
            self.fechando = True
        try:
            ok = terminate_owned_process(TILE_PROCESS_PIDFILE, "tile-process", TILE_PROCESS_MARKER)
        except Exception as erro:  # noqa: BLE001 — fechar a pílula continua
            ok = False
            if WINDOWS:
                log_windows(f"overlay: erro ao encerrar o app ({motivo}): {type(erro).__name__}: {erro}")
        if WINDOWS:
            log_windows("overlay: supervisor do app encerrado; o Job Object leva a árvore" if ok
                        else "overlay: nenhum app aberto para encerrar")
        return ok

    def vigiar_o_x(self):
        """Thread (Windows). Roteiro 32: com o Tux Paint travado, 6 cliques no ✕ não
        chegaram ao Tk (nem uma linha no log), com a pílula viva e respondendo. Este
        vigia olha o botão do mouse direto do sistema a cada 30 ms; se um clique no ✕
        não virou on_close em 0,8 s, fecha o app daqui e sai, sem depender do Tk."""
        clique = janelas_seguras.CliqueNoBotao()
        eu = os.getpid()
        pids, proxima_arvore = set(), 0.0
        while not self.fechando:
            time.sleep(0.03)
            try:
                agora = time.monotonic()
                if agora >= proxima_arvore:
                    record = owned_process(TILE_PROCESS_PIDFILE, "tile-process")
                    pids = set(win.arvore(record["pid"])) if record else set()
                    proxima_arvore = agora + 0.5
                # SuperTux, Pingus e outros prendem o cursor (ClipCursor) e o ✕
                # fica fora do alcance. Alargar é do sistema, não uma mensagem ao jogo,
                # e o recorte novo não passa do monitor do jogo.
                if pids and win.soltar_cursor_se_preso(pids, self.retangulo_do_x):
                    self.log_uma_vez("overlay: alarguei o recorte do cursor até o ✕")
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            try:
                apertado, pos, pid = win.estado_do_mouse()
            except (OSError, ValueError, TypeError):
                continue
            if not clique.passo(apertado, pos, self.retangulo_do_x, pid == eu):
                continue
            log_windows("overlay: vigia do ✕: clique no ✕")
            fim = time.monotonic() + 0.8
            while time.monotonic() < fim and not self.fechando:
                time.sleep(0.05)
            if self.fechando:
                return
            # o Tk parado há segundos = a thread dele presa; há < 1 s = o clique é que não chegou
            parado = time.monotonic() - self.ultimo_tique if self.ultimo_tique else -1
            log_windows(f"overlay: o clique no ✕ não chegou ao Tk (o Tk rodou há {parado:.1f} s); "
                        "o vigia do ✕ fecha o app")
            telemetria.relatar_problema("overlay.x_sem_tk", f"tile={self.tile_id}",
                                        f"overlay.x_sem_tk:{self.tile_id}", por_dia=True)
            self.fechar_app("vigia do ✕")
            focus_launcher()
            remove_process_record(OVERLAY_PIDFILE, expected_pid=eu)
            os._exit(0)

    def maximize_app(self, tentativas):
        """Apps que abrem numa janela pequena (KDE, Pencil2D, Scratch): maximiza uma vez,
        quando a janela principal está de pé (tenta por 1 min: o Quatro em Linha só
        mostra a janela depois que alguém fecha o aviso dele). Na thread de trabalho."""
        if self.closing or self.maximizada:
            return
        record = owned_process(TILE_PROCESS_PIDFILE, "tile-process")
        if record:
            self.pedir_janela("maximizar", self.passo_maximizar, record["pid"])
        if tentativas > 1:
            self.root.after(500, lambda: self.maximize_app(tentativas - 1))

    def _hwnds_do_app(self, pid):
        """Janelas em que o overlay pode mexer. No Edge em quiosque, só a primeira:
        a segunda (pop-up, diálogo) não é adotada."""
        if getattr(self, "quiosque", None) is not None:
            return self.quiosque.para_cuidar(win.descrever_janelas(win.arvore(pid)))
        return win.janelas_de(win.arvore(pid))

    def passo_maximizar(self, pid):
        if getattr(self, "quiosque", None) is not None:
            hwnds = self._hwnds_do_app(pid)
            h = hwnds[0] if hwnds else None
        else:
            h = win.janela_maximizavel(pid)
        if not h or not self.de_pe.pronta(win.JANELAS, h):
            return
        log_windows(f"overlay: vou maximizar o app (hwnd {hx(h)})")
        self.maximizada = win.maximizar(h)

    # ----- janelas de outro app (roteiro 31) -----
    def pedir_janela(self, chave, funcao, *args):
        """Manda para a thread de trabalho. Se ela está presa numa janela de outro app, o
        pedido é recusado (a pílula segue) e o log diz uma vez."""
        if self.trabalho.pedir(chave, funcao, *args):
            return True
        preso = self.trabalho.preso()
        if preso and preso[1] >= 5:
            self.log_uma_vez(f"overlay: {preso[0]} preso há mais de 5 s numa janela de outro app; a pílula segue")
        return False

    def log_uma_vez(self, texto):
        if texto not in self.erros_logados:
            self.erros_logados.add(texto)
            log_windows(texto)

    def erro_no_trabalho(self, chave, erro):
        self.log_uma_vez(f"overlay: erro em {chave}: {type(erro).__name__}: {erro}")

    def erro_do_tk(self, tipo, valor, tb):
        """Erro numa função agendada do Tk: log e telemetria (o Tk só imprimiria no stderr,
        que no pythonw não vai a lugar nenhum)."""
        self.log_uma_vez(f"overlay: erro no Tk: {tipo.__name__}: {valor}")
        telemetria.relatar_excecao("overlay", tipo, valor, tb, log=self.log_uma_vez)

    def trazer_app(self, pid):
        """Na thread de trabalho: traz o app para a frente, se a janela já está de pé, e
        loga antes (com ms) e depois. No quiosque, a janela é a do --app, não a que
        acabou de abrir na frente."""
        janelas = self._hwnds_do_app(pid)
        if not janelas:
            return
        h = janelas[0]
        if not self.de_pe.pronta(win.JANELAS, h):
            self.log_uma_vez(f"overlay: o app (hwnd {hx(h)}) ainda não está de pé; espero para trazê-lo")
            return
        log_windows(f"overlay: vou trazer o app (hwnd {hx(h)})")
        win.trazer_para_frente(h)
        log_windows(f"overlay: trazer o app (hwnd {hx(h)}): {win.ULTIMO_JEITO[0]}")

    def esticar_app(self, decisao, originais=None):
        """A cada 1 s, enquanto o app está aberto: a janela maximizada do app (que pararia
        acima da faixa da barra escondida) vira tela cheia sem moldura. Janelas pequenas
        (Klavaro, Quinze) não estão maximizadas e ficam como estão; jogos em tela cheia
        de verdade já cobrem o monitor. A volta roda na thread de trabalho (o
        SetWindowLongPtr espera o app); se ela está ocupada, esta volta é pulada."""
        if self.closing:
            return
        originais = {} if originais is None else originais
        self.pedir_janela("tela cheia", self.passo_da_tela_cheia, decisao, originais)
        self.root.after(1000, lambda: self.esticar_app(decisao, originais))

    def passo_da_tela_cheia(self, decisao, originais):
        record = owned_process(TILE_PROCESS_PIDFILE, "tile-process")
        try:
            hwnds = self._hwnds_do_app(record["pid"]) if record else []
            for h in hwnds:
                if win.travada(h):
                    continue  # app "Não respondendo": não mexe nem conta
                if not self.de_pe.pronta(win.JANELAS, h):
                    continue  # acabou de aparecer (roteiro 32): nem olha ainda
                ret = win.retangulo(h)
                trabalho, monitor = win.areas_do_monitor(h)
                if not ret or not monitor:
                    continue
                acao = decisao.passo(h, win.esta_maximizada(h), ret, trabalho, monitor, win.sem_moldura(h))
                if acao == "tela_cheia":
                    log_windows(f"overlay: vou tirar a moldura (hwnd {hx(h)})")
                    estilo = win.tela_cheia_sem_moldura(h, monitor)
                    if estilo is None:
                        log_windows(f"overlay: não tirei a moldura (hwnd {hx(h)}): o app não respondeu")
                        decisao.nao_deu(h)
                        continue
                    originais.setdefault(h, (estilo, ret))
                    if decisao.feitas[h] == 0:
                        log_windows(f"overlay: app em tela cheia sem moldura {ret} → {monitor}")
                    else:
                        log_windows(f"overlay: o app desfez a tela cheia ({decisao.feitas[h]}ª vez); refeita")
                elif acao == "desistir":
                    estilo, antes = originais.get(h, (None, None))
                    log_windows(f"overlay: vou devolver a moldura (hwnd {hx(h)})")
                    win.devolver_moldura(h, estilo, antes)
                    log_windows("overlay: o app desfaz a tela cheia sem moldura; devolvida a janela como era")
        except Exception as erro:  # noqa: BLE001 — um erro não pode parar a volta seguinte
            self.log_uma_vez(f"overlay: erro na tela cheia: {type(erro).__name__}: {erro}")

    def trazer_app_quando_abrir(self, estado):
        acao = "esperar"
        record = owned_process(TILE_PROCESS_PIDFILE, "tile-process")
        try:
            pids = win.arvore(record["pid"]) if record else []
            # no quiosque, a janela que conta é a do --app, não a que abriu na frente
            if getattr(self, "quiosque", None) is not None and self.quiosque.principal:
                janelas = [self.quiosque.principal]
            else:
                janelas = win.janelas_de(pids) if pids else []
            if any(win.travada(h) for h in janelas):
                # roteiro 31: nunca mexer num app "Não respondendo"; a volta não conta
                self.log_uma_vez("overlay: o app não responde; espero para trazê-lo para a frente")
            else:
                frente = win.pid_da_janela_ativa()
                # roteiro 32: janela que acabou de aparecer ainda não conta; a thread de
                # trabalho confere se ela está de pé (2 s respondendo)
                de_pe = bool(janelas) and self.de_pe.firme(janelas[0])
                if janelas and not de_pe:
                    self.pedir_janela("ver se está de pé", self.de_pe.pronta, win.JANELAS, janelas[0])
                # a própria pílula na frente NÃO conta como o app na frente (roteiro 28: o
                # foco ficava nela e o jogo ficava sem teclado)
                acao = estado.passo(de_pe, frente in pids)
                if acao == "trazer":
                    self.pedir_janela("trazer o app", self.trazer_app, record["pid"])
        except (OSError, TypeError, KeyError):
            acao = estado.passo(False, False)  # conta a volta: o limite vale mesmo com erro
        if acao != "fim":
            self.root.after(500, lambda: self.trazer_app_quando_abrir(estado))

    def poll_process(self):
        if not owned_process_alive(
            TILE_PROCESS_PIDFILE,
            "tile-process",
            TILE_PROCESS_MARKER,
        ):
            self.on_close("o app fechou")
            return
        self.root.after(1000, self.poll_process)

    def poll_timer(self):
        if self.fechando:
            return
        availability = api("/api/availability/status")
        if tile_is_blocked(availability, self.tile_id):
            self.on_close("horário bloqueado")
            return
        data = api("/api/timer/status")
        if isinstance(data, dict) and data.get("active"):
            self.timer_pilula = {"fim": time.monotonic() + int(data.get("remainingSeconds") or 0),
                                 "expirado": bool(data.get("expired")), "aviso": bool(data.get("warning"))}
        else:
            self.timer_pilula = None
        self.atualizar_pilula()  # o poll_usage (a cada 1 s) também atualiza, com a conta local
        if not self.fechando:
            self.root.after(5000, self.poll_timer)

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.x11_raiser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="external", choices=["external", "local"])
    parser.add_argument("--url", default="")
    parser.add_argument("--label", default="Home")
    parser.add_argument("--tile-id", default="")
    args = parser.parse_args()

    telemetria.instalar_excepthook("overlay")
    overlay = AppOverlay(args.mode, args.url, args.label, tile_id=args.tile_id)
    write_process_record(
        OVERLAY_PIDFILE,
        os.getpid(),
        "overlay",
        marker=OVERLAY_MARKER,
    )
    try:
        overlay.run()
    finally:
        remove_process_record(OVERLAY_PIDFILE, expected_pid=os.getpid())


if __name__ == "__main__":
    main()
