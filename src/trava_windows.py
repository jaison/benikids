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

A preferência do usuário é a gravada no registro (StuckRects3); o "ocultar
automaticamente" do Benikids fica só na memória do Explorer, e o Sair confere que o
registro continuou como estava (roteiro 26).

Queda do iniciador (pior caso): a tecla Windows volta sozinha, mas a barra fica
escondida até o Benikids abrir e fechar de novo, o Explorer reiniciar ou a pessoa sair e
entrar no Windows. O estado original fica em barra-escondida.json, e a próxima abertura
do Benikids devolve esse estado ao sair. Como o adulto recupera: docs/benikids-tecnico.md.
"""

import json
import os
import threading
import time
import traceback

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
WM_TIMER = 0x0113


def timer_da_thread(msg):
    """WM_TIMER do SetTimer(NULL, ...): sem janela. O campo do wintypes.MSG é hWnd (com W
    maiúsculo): ler o campo "hwnd" dava AttributeError no primeiro timer e matava a thread da
    barra em silêncio (pacote 22: Explorer reiniciado deixava a barra à mostra)."""
    return msg.message == WM_TIMER and not msg.hWnd


class LogDeErro:
    """Loga cada erro diferente uma vez (a conferência roda 4 vezes por segundo)."""

    def __init__(self, log):
        self.log = log
        self.vistos = set()

    def __call__(self, onde, erro):
        chave = (onde, type(erro).__name__, str(erro))
        if chave in self.vistos:
            return
        self.vistos.add(chave)
        self.log(f"{onde}: erro {type(erro).__name__}: {erro}")


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


# ------------------------------------------------- preferência gravada (StuckRects3)
# O Explorer grava a barra em HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\
# StuckRects3, valor "Settings" (binário; 48 bytes no Windows 10 e 11). Os 4 primeiros
# bytes são o tamanho da estrutura (0x30); o byte 8 guarda as opções, e o bit 0x01 é o
# "ocultar automaticamente" (0x02 = barra fixa, 0x03 = ocultar).
STUCKRECTS = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StuckRects3"
BYTE_DAS_OPCOES = 8
# Um Explorer que acabou de abrir ainda está montando a cópia das opções que ele grava
# no registro. Ligar o "ocultar automaticamente" nessa hora faz o Explorer gravá-lo como
# preferência (roteiro 26: Explorer reiniciado com o Benikids aberto → depois do Sair o
# registro ficou 0x03). Antes de religar, espera o Explorer ter esta idade.
ESPERA_EXPLORER = 12.0
CONFERIR_REGISTRO_S = 3.0


def stuckrects_valido(dados):
    return (isinstance(dados, (bytes, bytearray)) and len(dados) > BYTE_DAS_OPCOES + 3
            and int.from_bytes(dados[0:4], "little") == len(dados))


def autohide_no_registro(dados):
    """True/False pelo bit 0x01 do byte 8; None se o formato não for o conhecido."""
    if not stuckrects_valido(dados):
        return None
    return bool(dados[BYTE_DAS_OPCOES] & ABS_AUTOHIDE)


def com_autohide_no_registro(dados, ligado):
    """Os mesmos bytes, só com o bit 0x01 do byte 8 trocado."""
    novo = bytearray(dados)
    if ligado:
        novo[BYTE_DAS_OPCOES] |= ABS_AUTOHIDE
    else:
        novo[BYTE_DAS_OPCOES] &= 0xFF ^ ABS_AUTOHIDE
    return bytes(novo)


class Barra:
    """Esconde e devolve a barra de tarefas. `api` faz as chamadas ao Windows (nos testes,
    um falso): barras() → [janela], visivel(j), esconder(j), mostrar(j),
    estado() → bits ABS_* (ou None), definir_estado(bits), registro() → bytes do
    StuckRects3 (ou None), gravar_registro(bytes), idade_do_explorer() → segundos (ou
    None), reiniciar_explorer()."""

    def __init__(self, api, arquivo, log=lambda _texto: None, dormir=None):
        self.api = api
        self.arquivo = arquivo
        self.log = log
        self.dormir = dormir or (lambda s: time.sleep(s))
        self.ativa = False
        self.original = None
        self.escondidas = set()
        self.religar = False  # falta ligar o "ocultar automaticamente" (Explorer novo)
        self.avisou_espera = False

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

    def _preferencia(self, atual):
        """O estado de agora, com o "ocultar automaticamente" que está GRAVADO no registro:
        é a preferência do usuário. O de agora pode ser sobra de um Benikids (ou de um
        Explorer que ainda não releu)."""
        if not isinstance(atual, int):
            return None
        gravado = autohide_no_registro(self.api.registro())
        if gravado is None:
            return atual
        pref = (atual & ~ABS_AUTOHIDE) | (ABS_AUTOHIDE if gravado else 0)
        if pref != atual:
            self.log(f"barra: o Windows está com \"ocultar automaticamente\" {'ligado' if atual & ABS_AUTOHIDE else 'desligado'}, "
                     f"mas a preferência gravada é {'ligado' if gravado else 'desligado'}; vale a gravada")
        return pref

    def esconder(self):
        salvo = self._ler_salvo()
        if salvo is not None:
            # o Benikids anterior caiu: o "ocultar automaticamente" de agora é o que ele
            # ligou; o de verdade é o que ficou guardado
            self.log("barra: o Benikids anterior não devolveu a barra; usando o estado guardado")
            self.original = salvo
        else:
            self.original = self._preferencia(self.api.estado())
            if self.original is not None:
                self._salvar()
        self.ativa = True
        self.religar = True
        self.manter()

    def _explorer_pronto(self):
        idade = self.api.idade_do_explorer()
        if idade is None or idade >= ESPERA_EXPLORER:
            self.avisou_espera = False
            return True
        if not self.avisou_espera:
            self.avisou_espera = True
            self.log(f"barra: o Explorer abriu há {idade:.0f} s; o \"ocultar automaticamente\" espera "
                     f"ele terminar de abrir ({ESPERA_EXPLORER:.0f} s)")
        return False

    def ocultar_automaticamente(self):
        """Liga o "ocultar automaticamente" se estiver desligado. Devolve True se ficou
        ligado; False se o Explorer ainda não respondeu (tenta de novo depois)."""
        if not self.ativa:
            return True
        atual = self.api.estado()
        if not isinstance(atual, int):
            return False
        if self.original is None:
            # o Explorer ainda não existia quando o Benikids abriu: guarda agora
            self.original = self._preferencia(atual)
            self._salvar()
        if atual & ABS_AUTOHIDE:
            return True
        self.api.definir_estado(estado_com_ocultar(atual))
        depois = self.api.estado()
        ok = isinstance(depois, int) and bool(depois & ABS_AUTOHIDE)
        if ok:
            self.log("barra: \"ocultar automaticamente\" ligado")
        return ok

    def manter(self):
        """A conferência periódica: esconde o que voltou e, se falta, liga o "ocultar
        automaticamente" (só com o Explorer já aberto de vez). Devolve True se o Explorer
        acabou de voltar (barra nova escondida agora)."""
        voltou = self.vigiar()
        if self.religar and self._explorer_pronto() and self.ocultar_automaticamente():
            self.religar = False
        return voltou

    def explorer_voltou(self):
        """O "TaskbarCreated": esconde a barra nova; o autohide volta quando der."""
        self.religar = True
        self.manter()

    def vigiar(self):
        """Esconde de novo o que reapareceu (Explorer reiniciado, outra tela ligada).
        Devolve True se escondeu uma barra nova de um Explorer reiniciado."""
        if not self.ativa:
            return False
        nova = False
        havia = bool(self.escondidas)
        for janela in self.api.barras():
            if self.api.visivel(janela):
                self.api.esconder(janela)
                if janela not in self.escondidas:
                    if havia:
                        # já havia escondido outra: é a barra de um Explorer novo
                        nova = True
                        self.religar = True
                        self.log("barra: Explorer voltou; escondida de novo")
                    else:
                        self.log("barra: escondida")
                    self.escondidas.add(janela)
        return nova

    def restaurar(self):
        if not self.ativa:
            return
        self.ativa = False
        if self.original is not None:
            self.api.definir_estado(self.original)
        for janela in self.api.barras():
            self.api.mostrar(janela)
        self.escondidas.clear()
        if self.original is not None:
            self.conferir_registro(bool(self.original & ABS_AUTOHIDE))
        try:
            os.unlink(self.arquivo)
        except OSError:
            pass
        self.log("barra: devolvida")

    def conferir_registro(self, querido):
        """Depois de devolver: o registro precisa ficar com a preferência do usuário. Se o
        Explorer gravou o "ocultar automaticamente" do Benikids, acerta o bit e reinicia o
        Explorer: a cópia que ele grava está errada, e ele a gravaria de novo (ao desligar o
        PC, por exemplo). O Explorer novo lê o registro já certo."""
        errado = False
        for _ in range(int(CONFERIR_REGISTRO_S / 0.25) + 1):
            dados = self.api.registro()
            gravado = autohide_no_registro(dados)
            if gravado is None:
                return
            if gravado != querido:
                self.api.gravar_registro(com_autohide_no_registro(dados, querido))
                if not errado:
                    self.log("barra: o Explorer gravou o \"ocultar automaticamente\" do Benikids; "
                             "preferência devolvida no registro")
                errado = True
            self.dormir(0.25)
        if errado:
            self.log("barra: reiniciando o Explorer para ele ler a preferência certa")
            self.api.reiniciar_explorer()


class Foco:
    """Se o foco cair na área de trabalho ou na barra (ex.: o Explorer reiniciado o pega),
    devolve para a última janela que estava na frente. Espera duas voltas seguidas
    para não brigar com uma troca de janela que ainda está acontecendo."""

    def __init__(self):
        self.ultima = None
        self.fora = 0

    def passo(self, janela, classe, existe, vazio_conta=False):
        """janela/classe da frente agora; existe(j) diz se a janela ainda está aberta.
        vazio_conta: logo depois de o Explorer voltar, "nenhuma janela na frente" também
        é foco perdido (fora disso é só uma troca de janela no meio).
        Devolve a janela que deve voltar para a frente, ou None."""
        if janela and classe not in CLASSES_FORA:
            self.ultima = janela
            self.fora = 0
            return None
        if not janela and not vazio_conta:
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
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel32.GetSystemTimeAsFileTime.argtypes = [ctypes.POINTER(wintypes.FILETIME)]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
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

        def registro(self):
            import winreg

            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STUCKRECTS) as chave:
                    valor, tipo = winreg.QueryValueEx(chave, "Settings")
            except OSError:
                return None
            return bytes(valor) if tipo == winreg.REG_BINARY else None

        def gravar_registro(self, valor):
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STUCKRECTS, 0, winreg.KEY_SET_VALUE) as chave:
                winreg.SetValueEx(chave, "Settings", 0, winreg.REG_BINARY, bytes(valor))

        def _pid_do_explorer(self):
            h = user32.FindWindowW("Shell_TrayWnd", None)
            if not h:
                return None
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            return pid.value or None

        def idade_do_explorer(self):
            pid = self._pid_do_explorer()
            if not pid:
                return None
            h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return None
            try:
                criado, x1, x2, x3 = (wintypes.FILETIME() for _ in range(4))
                if not kernel32.GetProcessTimes(h, ctypes.byref(criado), ctypes.byref(x1),
                                                ctypes.byref(x2), ctypes.byref(x3)):
                    return None
            finally:
                kernel32.CloseHandle(h)
            agora = wintypes.FILETIME()
            kernel32.GetSystemTimeAsFileTime(ctypes.byref(agora))

            def n(ft):
                return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

            return max(0.0, (n(agora) - n(criado)) / 1e7)

        def reiniciar_explorer(self):
            pid = self._pid_do_explorer()
            if pid:
                h = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
                if h:
                    kernel32.TerminateProcess(h, 1)
                    kernel32.CloseHandle(h)
            # o Windows reabre o shell sozinho (AutoRestartShell); se não reabrir, abre
            for _ in range(20):
                time.sleep(0.25)
                if user32.FindWindowW("Shell_TrayWnd", None):
                    return
            from queda_windows import popen_fora_do_job

            popen_fora_do_job(["explorer.exe"], close_fds=True)

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
            t = threading.Thread(target=self._rodar, args=(nome, alvo, pronta), name=f"trava-{nome}", daemon=True)
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

    def _rodar(self, nome, alvo, pronta):
        """Roda a thread logando o que a derrubar: no pythonw não há stderr, e uma exceção
        numa thread sumia sem deixar rastro (foi assim que a da barra morreu no pacote 22)."""
        try:
            alvo(pronta)
        except BaseException as erro:  # noqa: BLE001
            self.log(f"trava ({nome}): a thread caiu: {type(erro).__name__}: {erro}\n"
                     + "".join(traceback.format_exc()[-1500:]))
        finally:
            pronta.set()
            if self.threads.get(nome):
                # caiu sozinha (não foi o desligar): ninguém mais vigia
                self.log(f"trava ({nome}): parou")

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
                if not timer_da_thread(msg):
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
        user32.ChangeWindowMessageFilterEx.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.DWORD, ctypes.c_void_p]

        erro_de = LogDeErro(self.log)
        taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        foco = Foco()
        rapido = {"ate": 0.0, "timer": 0, "janela": None}
        TIMER_RAPIDO = 2

        def classe_de(h):
            buf = ctypes.create_unicode_buffer(64)
            return buf.value if h and user32.GetClassNameW(h, buf, 64) else ""

        def existe(h):
            return bool(user32.IsWindow(h)) and bool(user32.IsWindowVisible(h))

        def acelerar(hwnd):
            # Explorer de volta: confere bem de perto por alguns segundos (ele mostra a
            # barra mais de uma vez ao subir e pode levar o foco para a área de trabalho)
            rapido["ate"] = time.monotonic() + RAPIDO_SEGUNDOS
            if hwnd and not rapido["timer"]:
                rapido["timer"] = user32.SetTimer(hwnd, TIMER_RAPIDO, RAPIDO_MS, None)

        def conferir():
            try:
                if self.barra.manter():
                    acelerar(rapido["janela"])
            except Exception as erro:  # noqa: BLE001
                erro_de("barra", erro)
            try:
                frente = user32.GetForegroundWindow()
                classe_frente = classe_de(frente)
                volta = foco.passo(frente, classe_frente, existe,
                                   vazio_conta=time.monotonic() < rapido["ate"])
                if volta:
                    ok = win.trazer_para_frente(volta)
                    self.log(f"foco: estava na {classe_frente or 'área de trabalho (nenhuma janela)'}; "
                             f"{'devolvido ao menu/app' if ok else 'não deu para devolver'} ({classe_de(volta)})")
            except Exception as erro:  # noqa: BLE001
                erro_de("foco", erro)

        def proc(hwnd, msg, wparam, lparam):
            if msg == taskbar_created and taskbar_created:
                self.log("barra: o Explorer reiniciou (TaskbarCreated)")
                try:
                    self.barra.explorer_voltou()
                except Exception as erro:  # noqa: BLE001
                    erro_de("barra (TaskbarCreated)", erro)
                acelerar(hwnd)
                return 0
            if msg == WM_TIMER and wparam == TIMER_RAPIDO:
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
        else:
            rapido["janela"] = janela
            # deixa o aviso do Explorer (integridade média) passar mesmo se o Benikids
            # estiver rodando como administrador (filtro de mensagens do UIPI)
            user32.ChangeWindowMessageFilterEx(janela, taskbar_created, 1, None)  # MSGFLT_ALLOW
        if not user32.SetTimer(None, 0, INTERVALO_MS, None):
            self.log(f"barra: sem a conferência periódica (erro {ctypes.get_last_error()})")
        self.log("barra: vigiando (TaskbarCreated e a cada 250 ms)")
        pronta.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if timer_da_thread(msg):
                    conferir()
                    continue
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if janela:
                user32.DestroyWindow(janela)
