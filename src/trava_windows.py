"""Fecha as saídas do Windows enquanto o Benikids está aberto: tecla Windows e barra de tarefas.

Roda dentro do iniciador (beni_windows.py), o único processo do Benikids que fica vivo
do começo ao fim (com o menu nativo, com o menu web de reserva, com um app aberto e
na área dos pais) e que reabre os outros quando caem.

- Tecla Windows: um gancho de teclado de baixo nível (WH_KEYBOARD_LL) engole LWin/RWin
  (e com elas todas as combinações: Win+X, Win+D, Win+E, Win+R, Win+Tab...) e o
  Ctrl+Esc, que também abre o Iniciar. Não usa política (NoWinKeys), que pede
  administrador e logoff. O Windows desfaz o gancho sozinho quando a thread ou o
  processo acabam: numa queda, a tecla volta na hora.
- Barra de tarefas: Shell_TrayWnd e Shell_SecondaryTrayWnd escondidas (SW_HIDE), e a
  área de trabalho da tela principal passa a ser a tela inteira (senão um app
  maximizado deixa a faixa da barra vazia). A cada meio segundo confere de novo (o
  Explorer reiniciado cria outra barra visível). Na saída devolve as duas coisas.

Queda do iniciador (pior caso): a tecla Windows volta sozinha, mas a barra fica
escondida até o Benikids abrir e fechar de novo, o Explorer reiniciar ou a pessoa sair e
entrar no Windows. O tamanho original da área de trabalho fica guardado em
barra-escondida.json, para a próxima abertura devolver o certo (e não a tela inteira
que ela mesma deixou). Como o adulto recupera: docs/benikids-tecnico.md.
"""

import json
import os
import threading

VK_ESCAPE = 0x1B
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12

CLASSES_DA_BARRA = ("Shell_TrayWnd", "Shell_SecondaryTrayWnd")
INTERVALO_MS = 500
# O Windows tira em silêncio um gancho que demora a responder (LowLevelHooksTimeout).
# Pôr um novo de tempos em tempos garante que ele volta mesmo que isso aconteça.
REGANCHAR_A_CADA = 60  # voltas de INTERVALO_MS = 30 s


def engolir_tecla(vk, ctrl=False, shift=False, alt=False):
    """True se a tecla não pode chegar ao Windows (abriria o Iniciar ou um atalho dele).

    Ctrl+Shift+Esc (Gerenciador de Tarefas) passa: é por ele que um adulto recupera o
    computador se algo der errado, e Ctrl+Alt+Del leva a ele de qualquer forma."""
    if vk in (VK_LWIN, VK_RWIN):
        return True
    return vk == VK_ESCAPE and ctrl and not shift and not alt


def _area_valida(area):
    return (isinstance(area, (list, tuple)) and len(area) == 4
            and all(isinstance(v, int) for v in area) and area[2] > area[0] and area[3] > area[1])


class Barra:
    """Esconde e devolve a barra de tarefas. `api` faz as chamadas ao Windows (nos testes,
    um falso): barras() → [janela], visivel(j), esconder(j), mostrar(j),
    area_de_trabalho() → [l, t, r, b], definir_area([l, t, r, b]), tela() → [l, t, r, b]."""

    def __init__(self, api, arquivo, log=lambda _texto: None):
        self.api = api
        self.arquivo = arquivo
        self.log = log
        self.ativa = False
        self.original = None
        self.escondidas = set()

    def _ler_salvo(self):
        try:
            with open(self.arquivo, encoding="utf-8") as f:
                area = json.load(f).get("area")
        except (OSError, ValueError, AttributeError):
            return None
        return list(area) if _area_valida(area) else None

    def _salvar(self):
        try:
            os.makedirs(os.path.dirname(self.arquivo), exist_ok=True)
            with open(self.arquivo, "w", encoding="utf-8") as f:
                json.dump({"area": self.original}, f)
        except OSError:
            pass

    def esconder(self):
        salvo = self._ler_salvo()
        if salvo:
            # o Benikids anterior caiu com a barra escondida: a área de agora é a tela
            # inteira que ele deixou; a de verdade é a que ficou guardada
            self.log("barra: o Benikids anterior não devolveu a barra; usando a área guardada")
            self.original = salvo
        else:
            atual = self.api.area_de_trabalho()
            self.original = list(atual) if _area_valida(atual) else None
            if self.original:
                self._salvar()
        self.ativa = True
        self.vigiar()

    def vigiar(self):
        """Esconde de novo o que reapareceu (Explorer reiniciado, outra tela ligada)."""
        if not self.ativa:
            return
        for janela in self.api.barras():
            if self.api.visivel(janela):
                self.api.esconder(janela)
                if janela not in self.escondidas:
                    self.escondidas.add(janela)
                    self.log("barra: escondida")
        tela = self.api.tela()
        if _area_valida(tela) and list(self.api.area_de_trabalho() or []) != list(tela):
            self.api.definir_area(list(tela))

    def restaurar(self):
        if not self.ativa:
            return
        self.ativa = False
        if self.original:
            self.api.definir_area(self.original)
        for janela in self.api.barras():
            self.api.mostrar(janela)
        self.escondidas.clear()
        try:
            os.unlink(self.arquivo)
        except OSError:
            pass
        self.log("barra: devolvida")


# ---------------------------------------------------------------- Windows (ctypes)

def _api_windows():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowExW.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    SPI_SETWORKAREA, SPI_GETWORKAREA, SPIF_SENDCHANGE = 0x002F, 0x0030, 0x0002
    SW_HIDE, SW_SHOWNA = 0, 8

    class Api:
        def barras(self):
            achadas = []
            for classe in CLASSES_DA_BARRA:
                h = None
                while True:
                    h = user32.FindWindowExW(None, h, classe, None)
                    if not h:
                        break
                    achadas.append(h)
            return achadas

        def visivel(self, h):
            return bool(user32.IsWindowVisible(h))

        # assíncrono: um Explorer travado não trava o iniciador
        def esconder(self, h):
            user32.ShowWindowAsync(h, SW_HIDE)

        def mostrar(self, h):
            user32.ShowWindowAsync(h, SW_SHOWNA)

        def area_de_trabalho(self):
            r = wintypes.RECT()
            if not user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0):
                return None
            return [r.left, r.top, r.right, r.bottom]

        def definir_area(self, area):
            r = wintypes.RECT(*area)
            # sem SPIF_UPDATEINIFILE: não fica gravado; o Explorer recalcula ao voltar
            user32.SystemParametersInfoW(SPI_SETWORKAREA, 0, ctypes.byref(r), SPIF_SENDCHANGE)

        def tela(self):
            monitor = user32.MonitorFromPoint(wintypes.POINT(0, 0), 1)  # MONITOR_DEFAULTTOPRIMARY
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return None
            m = info.rcMonitor
            return [m.left, m.top, m.right, m.bottom]

    return Api(), user32, kernel32


class Trava:
    """Tecla Windows e barra de tarefas presas enquanto o Benikids roda (só no Windows).

    Uma thread só, com a fila de mensagens que o gancho de teclado exige: o gancho é
    chamado dentro do GetMessage dela, e o WM_TIMER dela vigia a barra."""

    def __init__(self, arquivo_barra, log=lambda _texto: None):
        self.arquivo_barra = arquivo_barra
        self.log = log
        self.thread = None
        self.thread_id = 0
        self.barra = None
        self.pronta = threading.Event()

    def ligar(self):
        if os.name != "nt" or self.thread is not None:
            return
        self.thread = threading.Thread(target=self._rodar, name="trava-windows", daemon=True)
        self.thread.start()
        self.pronta.wait(3)

    def desligar(self):
        """Desfaz o gancho e devolve a barra. Pode ser chamada mais de uma vez."""
        thread, self.thread = self.thread, None
        if thread is not None and self.thread_id:
            try:
                import ctypes

                ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)  # WM_QUIT
            except (AttributeError, OSError):
                pass
            thread.join(3)
        if self.barra is not None:
            try:
                self.barra.restaurar()
            except Exception as erro:  # noqa: BLE001 — sair do Benikids nunca pode travar aqui
                self.log(f"barra: não deu para devolver ({erro})")

    def _rodar(self):
        import ctypes
        from ctypes import wintypes

        try:
            api, user32, kernel32 = _api_windows()
        except Exception as erro:  # noqa: BLE001
            self.log(f"trava: indisponível ({erro})")
            self.pronta.set()
            return
        self.thread_id = kernel32.GetCurrentThreadId()

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        LRESULT = ctypes.c_ssize_t
        HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HANDLE
        user32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = LRESULT
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
        user32.SetTimer.restype = ctypes.c_size_t
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        def apertada(vk):
            return bool(user32.GetAsyncKeyState(vk) & 0x8000)

        def gancho(codigo, wparam, lparam):
            if codigo == 0:  # HC_ACTION
                tecla = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                vk = tecla.vkCode
                if vk in (VK_LWIN, VK_RWIN, VK_ESCAPE) and engolir_tecla(
                        vk, apertada(VK_CONTROL), apertada(VK_SHIFT), apertada(VK_MENU)):
                    return 1
            return user32.CallNextHookEx(None, codigo, wparam, lparam)

        self._gancho_c = HOOKPROC(gancho)  # a referência precisa viver enquanto o gancho existir
        modulo = kernel32.GetModuleHandleW(None)

        def enganchar():
            h = user32.SetWindowsHookExW(13, self._gancho_c, modulo, 0)  # WH_KEYBOARD_LL
            if not h:
                self.log(f"tecla Windows: gancho recusado (erro {ctypes.get_last_error()})")
            return h

        gancho_atual = enganchar()
        if gancho_atual:
            self.log("tecla Windows: bloqueada")
        self.barra = Barra(api, self.arquivo_barra, self.log)
        try:
            self.barra.esconder()
        except Exception as erro:  # noqa: BLE001
            self.log(f"barra: não deu para esconder ({erro})")
        user32.SetTimer(None, 0, INTERVALO_MS, None)
        self.pronta.set()

        msg = wintypes.MSG()
        voltas = 0
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message != 0x0113:  # WM_TIMER
                    continue
                voltas += 1
                try:
                    self.barra.vigiar()
                except Exception:  # noqa: BLE001
                    pass
                if voltas % REGANCHAR_A_CADA == 0:
                    novo = enganchar()
                    if novo:
                        if gancho_atual:
                            user32.UnhookWindowsHookEx(gancho_atual)
                        gancho_atual = novo
        finally:
            if gancho_atual:
                user32.UnhookWindowsHookEx(gancho_atual)
            self.log("tecla Windows: liberada")
