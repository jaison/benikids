"""Fecha as saídas do Windows enquanto o Benikids está aberto: tecla Windows e barra de tarefas.

Roda dentro do iniciador (beni_windows.py), o único processo do Benikids que fica vivo
do começo ao fim (com o menu nativo, com o menu web de reserva, com um app aberto e
na área dos pais) e que reabre os outros quando caem.

- Tecla Windows: um gancho de teclado de baixo nível (WH_KEYBOARD_LL) engole LWin/RWin
  (e com elas todas as combinações: Win+X, Win+D, Win+E, Win+R, Win+Tab...) e o
  Ctrl+Esc, que também abre o Iniciar. Não usa política (NoWinKeys), que pede
  administrador e logoff. O Windows desfaz o gancho sozinho quando a thread ou o
  processo acabam: numa queda, a tecla volta na hora. A thread do gancho não faz mais
  nada: uma chamada que espera outro processo (o Explorer) atrasaria cada tecla do
  computador e faria o Windows tirar o gancho.
- Barra de tarefas (outra thread): a barra fica em "ocultar automaticamente" e, além
  disso, escondida (SW_HIDE). Com o "ocultar automaticamente", o próprio Explorer
  anuncia a tela inteira como área de trabalho, e os apps maximizados vão até
  embaixo. Gravar a área (SPI_SETWORKAREA) não servia: o Explorer a reescrevia
  (roteiro 24). Uma janela invisível recebe o "TaskbarCreated" do Explorer
  reiniciado e esconde a barra nova na hora; a conferência a cada 250 ms fica de
  reserva. Se o foco cair na área de trabalho ou na barra, volta para a última janela
  que estava na frente (menu ou app).

Queda do iniciador (pior caso): a tecla Windows volta sozinha, mas a barra fica
escondida até o Benikids abrir e fechar de novo, o Explorer reiniciar ou a pessoa sair e
entrar no Windows, e o "ocultar automaticamente" (preferência que o Windows grava)
continua ligado. O estado original fica em barra-escondida.json, e a próxima abertura
do Benikids devolve esse estado ao sair. Como o adulto recupera: docs/benikids-tecnico.md.
"""

import json
import os
import threading
import time

VK_ESCAPE = 0x1B
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12

ABS_AUTOHIDE = 0x1
ABS_ALWAYSONTOP = 0x2

CLASSES_DA_BARRA = ("Shell_TrayWnd", "Shell_SecondaryTrayWnd")
# janelas que não são do Benikids nem de um app: se o foco cair nelas, a criança
# fica na área de trabalho (Enter abre um ícone) ou na barra
CLASSES_FORA = frozenset(CLASSES_DA_BARRA + ("Progman", "WorkerW"))
INTERVALO_MS = 250
RAPIDO_MS = 50
RAPIDO_SEGUNDOS = 5.0
# O Windows tira em silêncio um gancho que demora a responder (LowLevelHooksTimeout).
# Pôr um novo de tempos em tempos garante que ele volta mesmo que isso aconteça.
REGANCHAR_MS = 30000


def engolir_tecla(vk, ctrl=False, shift=False, alt=False):
    """True se a tecla não pode chegar ao Windows (abriria o Iniciar ou um atalho dele).

    Ctrl+Shift+Esc (Gerenciador de Tarefas) passa: é por ele que um adulto recupera o
    computador se algo der errado, e Ctrl+Alt+Del leva a ele de qualquer forma."""
    if vk in (VK_LWIN, VK_RWIN):
        return True
    return vk == VK_ESCAPE and ctrl and not shift and not alt


def estado_com_ocultar(estado):
    """O estado da barra com "ocultar automaticamente", mantendo o resto."""
    return (estado or 0) | ABS_AUTOHIDE


class Barra:
    """Esconde e devolve a barra de tarefas. `api` faz as chamadas ao Windows (nos testes,
    um falso): barras() → [janela], visivel(j), esconder(j), mostrar(j),
    estado() → bits ABS_* (ou None), definir_estado(bits)."""

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
                estado = json.load(f).get("estado")
        except (OSError, ValueError, AttributeError):
            return None
        return estado if isinstance(estado, int) and not isinstance(estado, bool) and 0 <= estado < 16 else None

    def _salvar(self):
        try:
            os.makedirs(os.path.dirname(self.arquivo), exist_ok=True)
            with open(self.arquivo, "w", encoding="utf-8") as f:
                json.dump({"estado": self.original}, f)
        except OSError:
            pass

    def esconder(self):
        salvo = self._ler_salvo()
        if salvo is not None:
            # o Benikids anterior caiu: o "ocultar automaticamente" de agora é o que ele
            # ligou; o de verdade é o que ficou guardado
            self.log("barra: o Benikids anterior não devolveu a barra; usando o estado guardado")
            self.original = salvo
        else:
            atual = self.api.estado()
            self.original = atual if isinstance(atual, int) else None
            if self.original is not None:
                self._salvar()
        self.ativa = True
        self.ocultar_automaticamente()
        self.vigiar()

    def ocultar_automaticamente(self):
        """Liga o "ocultar automaticamente" se estiver desligado (também depois de o
        Explorer reiniciar, que relê a preferência)."""
        if not self.ativa:
            return
        atual = self.api.estado()
        if not isinstance(atual, int):
            return
        if self.original is None:
            # o Explorer ainda não existia quando o Benikids abriu: guarda agora
            self.original = atual
            self._salvar()
        if not atual & ABS_AUTOHIDE:
            self.api.definir_estado(estado_com_ocultar(atual))

    def vigiar(self):
        """Esconde de novo o que reapareceu (Explorer reiniciado, outra tela ligada).
        Devolve True se escondeu alguma barra agora."""
        if not self.ativa:
            return False
        escondeu = False
        for janela in self.api.barras():
            if self.api.visivel(janela):
                self.api.esconder(janela)
                escondeu = True
                if janela not in self.escondidas:
                    self.escondidas.add(janela)
                    self.log("barra: escondida")
        return escondeu

    def restaurar(self):
        if not self.ativa:
            return
        self.ativa = False
        if self.original is not None:
            self.api.definir_estado(self.original)
        for janela in self.api.barras():
            self.api.mostrar(janela)
        self.escondidas.clear()
        try:
            os.unlink(self.arquivo)
        except OSError:
            pass
        self.log("barra: devolvida")


class Foco:
    """Se o foco cair na área de trabalho ou na barra (ex.: o Explorer reiniciado o pega),
    devolve para a última janela que estava na frente. Espera duas voltas seguidas
    para não brigar com uma troca de janela que ainda está acontecendo."""

    def __init__(self):
        self.ultima = None
        self.fora = 0

    def passo(self, janela, classe, existe):
        """janela/classe da frente agora; existe(j) diz se a janela ainda está aberta.
        Devolve a janela que deve voltar para a frente, ou None."""
        if janela and classe not in CLASSES_FORA:
            self.ultima = janela
            self.fora = 0
            return None
        if not janela or classe not in CLASSES_FORA:
            return None
        self.fora += 1
        if self.fora < 2 or not self.ultima or not existe(self.ultima):
            return None
        self.fora = 0
        return self.ultima


# ---------------------------------------------------------------- Windows (ctypes)

def _api_windows():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowExW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]

    class APPBARDATA(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uCallbackMessage", wintypes.UINT),
                    ("uEdge", wintypes.UINT), ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]

    shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(APPBARDATA)]
    shell32.SHAppBarMessage.restype = ctypes.c_size_t
    ABM_GETSTATE, ABM_SETSTATE = 0x4, 0xA
    SW_HIDE, SW_SHOWNA = 0, 8

    def dados():
        d = APPBARDATA()
        d.cbSize = ctypes.sizeof(d)
        d.hWnd = user32.FindWindowW("Shell_TrayWnd", None)
        return d

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

        def estado(self):
            d = dados()
            if not d.hWnd:
                return None
            return int(shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(d))) & 0xF

        def definir_estado(self, estado):
            d = dados()
            if not d.hWnd:
                return
            d.lParam = int(estado)
            shell32.SHAppBarMessage(ABM_SETSTATE, ctypes.byref(d))

    return Api()


class Trava:
    """Tecla Windows e barra de tarefas presas enquanto o Benikids roda (só no Windows).

    Duas threads, cada uma com a sua fila de mensagens: a do gancho de teclado (que o
    Windows chama dentro do GetMessage dela e que não pode esperar ninguém) e a da
    barra (janela invisível para o "TaskbarCreated", conferência periódica, foco)."""

    def __init__(self, arquivo_barra, log=lambda _texto: None):
        self.arquivo_barra = arquivo_barra
        self.log = log
        self.threads = {}
        self.barra = None

    def ligar(self):
        if os.name != "nt" or self.threads:
            return
        for nome, alvo in (("tecla", self._rodar_tecla), ("barra", self._rodar_barra)):
            pronta = threading.Event()
            t = threading.Thread(target=alvo, args=(pronta,), name=f"trava-{nome}", daemon=True)
            self.threads[nome] = [t, 0]
            t.start()
            pronta.wait(3)

    def desligar(self):
        """Desfaz o gancho e devolve a barra. Pode ser chamada mais de uma vez."""
        threads, self.threads = self.threads, {}
        for t, thread_id in threads.values():
            if thread_id:
                try:
                    import ctypes

                    ctypes.windll.user32.PostThreadMessageW(thread_id, 0x0012, 0, 0)  # WM_QUIT
                except (AttributeError, OSError):
                    pass
        for t, _ in threads.values():
            t.join(3)
        if self.barra is not None:
            try:
                self.barra.restaurar()
            except Exception as erro:  # noqa: BLE001 — sair do Benikids nunca pode travar aqui
                self.log(f"barra: não deu para devolver ({erro})")

    @staticmethod
    def _base():
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
        user32.SetTimer.restype = ctypes.c_size_t
        user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        return ctypes, wintypes, user32, kernel32

    def _rodar_tecla(self, pronta):
        try:
            ctypes, wintypes, user32, kernel32 = self._base()
        except Exception as erro:  # noqa: BLE001
            self.log(f"tecla Windows: indisponível ({erro})")
            pronta.set()
            return
        self.threads["tecla"][1] = kernel32.GetCurrentThreadId()

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
        user32.SetTimer(None, 0, REGANCHAR_MS, None)
        pronta.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message != 0x0113:  # WM_TIMER
                    continue
                novo = enganchar()
                if novo:
                    if gancho_atual:
                        user32.UnhookWindowsHookEx(gancho_atual)
                    gancho_atual = novo
        finally:
            if gancho_atual:
                user32.UnhookWindowsHookEx(gancho_atual)
            self.log("tecla Windows: liberada")

    def _rodar_barra(self, pronta):
        try:
            ctypes, wintypes, user32, kernel32 = self._base()
            api = _api_windows()
            import plataforma_windows as win
        except Exception as erro:  # noqa: BLE001
            self.log(f"barra: indisponível ({erro})")
            pronta.set()
            return
        self.threads["barra"][1] = kernel32.GetCurrentThreadId()
        self.barra = Barra(api, self.arquivo_barra, self.log)
        try:
            self.barra.esconder()
        except Exception as erro:  # noqa: BLE001
            self.log(f"barra: não deu para esconder ({erro})")

        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
        user32.RegisterWindowMessageW.restype = wintypes.UINT
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                           wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]

        taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        foco = Foco()
        rapido = {"ate": 0.0, "timer": 0}
        TIMER_RAPIDO = 2

        def classe_de(h):
            buf = ctypes.create_unicode_buffer(64)
            return buf.value if h and user32.GetClassNameW(h, buf, 64) else ""

        def existe(h):
            return bool(user32.IsWindow(h)) and bool(user32.IsWindowVisible(h))

        def conferir():
            try:
                self.barra.vigiar()
                frente = user32.GetForegroundWindow()
                volta = foco.passo(frente, classe_de(frente), existe)
                if volta:
                    self.log(f"foco: estava na {classe_de(frente) or 'área de trabalho'}; devolvido")
                    win.trazer_para_frente(volta)
            except Exception:  # noqa: BLE001
                pass

        def proc(hwnd, msg, wparam, lparam):
            if msg == taskbar_created and taskbar_created:
                # Explorer reiniciado: barra nova; esconde já e confere bem de perto
                # por alguns segundos (ele mostra a barra mais de uma vez ao subir)
                self.log("barra: o Explorer reiniciou")
                try:
                    self.barra.vigiar()
                    self.barra.ocultar_automaticamente()
                except Exception:  # noqa: BLE001
                    pass
                rapido["ate"] = time.monotonic() + RAPIDO_SEGUNDOS
                if not rapido["timer"]:
                    rapido["timer"] = user32.SetTimer(hwnd, TIMER_RAPIDO, RAPIDO_MS, None)
                return 0
            if msg == 0x0113 and wparam == TIMER_RAPIDO:  # WM_TIMER
                conferir()
                if time.monotonic() > rapido["ate"]:
                    user32.KillTimer(hwnd, TIMER_RAPIDO)
                    rapido["timer"] = 0
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._proc_c = WNDPROC(proc)
        modulo = kernel32.GetModuleHandleW(None)
        classe = WNDCLASSW()
        classe.lpfnWndProc = self._proc_c
        classe.hInstance = modulo
        classe.lpszClassName = "BenikidsTravaBarra"
        user32.RegisterClassW(ctypes.byref(classe))
        # janela de nível superior que nunca aparece: as mensagens "para todos" (como o
        # TaskbarCreated) não chegam às janelas só de mensagem (HWND_MESSAGE)
        janela = user32.CreateWindowExW(0x00000080, "BenikidsTravaBarra", "Benikids", 0,  # WS_EX_TOOLWINDOW
                                        0, 0, 0, 0, None, None, modulo, None)
        if not janela:
            self.log(f"barra: sem a janela do TaskbarCreated (erro {ctypes.get_last_error()})")
        user32.SetTimer(None, 0, INTERVALO_MS, None)
        pronta.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0113 and not msg.hwnd:  # WM_TIMER da thread
                    conferir()
                    continue
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if janela:
                user32.DestroyWindow(janela)
