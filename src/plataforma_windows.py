"""O que no Linux vem de /proc, sinais, prctl e xdotool, feito no Windows (ctypes).

Só é importado quando os.name == "nt". Sem dependências além da biblioteca padrão.
"""

import ctypes
import os
from ctypes import wintypes

import janelas_seguras

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")
shell32 = ctypes.WinDLL("shell32")

PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
STILL_ACTIVE = 259
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
kernel32.CreateJobObjectW.restype = wintypes.HANDLE
kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel32.QueryInformationJobObject.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
]
kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.LocalFree.argtypes = [ctypes.c_void_p]
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
ntdll.NtQueryInformationProcess.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG),
]
ntdll.NtQueryInformationProcess.restype = ctypes.c_long

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsHungAppWindow.argtypes = [wintypes.HWND]
user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                       wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
user32.WaitForInputIdle.argtypes = [wintypes.HANDLE, wintypes.DWORD]
user32.WaitForInputIdle.restype = wintypes.DWORD
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetSystemMetrics.argtypes = [ctypes.c_int]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]


class _Aberto:
    """Handle de processo que fecha sozinho."""

    def __init__(self, pid, acesso=PROCESS_QUERY_LIMITED_INFORMATION):
        self.h = kernel32.OpenProcess(acesso, False, int(pid)) if int(pid) > 0 else None

    def __enter__(self):
        return self.h

    def __exit__(self, *_):
        if self.h:
            kernel32.CloseHandle(self.h)


def processo_vivo(h):
    codigo = wintypes.DWORD()
    return bool(kernel32.GetExitCodeProcess(h, ctypes.byref(codigo))) and codigo.value == STILL_ACTIVE


def process_stat(pid):
    """("R", hora de criação) enquanto o processo existe; None depois.

    A hora de criação (FILETIME, 100 ns) faz o papel do "starttime" do /proc:
    junto com o PID, identifica o processo mesmo se o número for reaproveitado.
    """
    try:
        with _Aberto(pid) as h:
            if not h or not processo_vivo(h):
                return None
            criado, saiu, kern, user = (wintypes.FILETIME() for _ in range(4))
            if not kernel32.GetProcessTimes(h, ctypes.byref(criado), ctypes.byref(saiu),
                                            ctypes.byref(kern), ctypes.byref(user)):
                return None
            return "R", (criado.dwHighDateTime << 32) | criado.dwLowDateTime
    except (OSError, ValueError, TypeError):
        return None


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]


def process_command(pid):
    """Linha de comando de outro processo (ProcessCommandLineInformation, Windows 8.1+)."""
    try:
        with _Aberto(pid) as h:
            if not h:
                return []
            tamanho = wintypes.ULONG(0)
            ntdll.NtQueryInformationProcess(h, 60, None, 0, ctypes.byref(tamanho))
            if not tamanho.value:
                return []
            buf = ctypes.create_string_buffer(tamanho.value)
            if ntdll.NtQueryInformationProcess(h, 60, buf, tamanho, ctypes.byref(tamanho)) != 0:
                return []
            us = _UNICODE_STRING.from_buffer(buf)
            if not us.Buffer or not us.Length:
                return []
            linha = ctypes.wstring_at(us.Buffer, us.Length // 2)
        return dividir_linha(linha)
    except (OSError, ValueError, TypeError):
        return []


def dividir_linha(linha):
    n = ctypes.c_int(0)
    argv = shell32.CommandLineToArgvW(linha, ctypes.byref(n))
    if not argv:
        return []
    try:
        return [argv[i] for i in range(n.value)]
    finally:
        kernel32.LocalFree(argv)


def terminar(pid, codigo=1):
    with _Aberto(pid, PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION) as h:
        if not h:
            return False
        return bool(kernel32.TerminateProcess(h, codigo))


def processos():
    """{pid: pid do pai} de todos os processos (Toolhelp32)."""
    tabela = {}
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return tabela
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            tabela[e.th32ProcessID] = e.th32ParentProcessID
            ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    finally:
        kernel32.CloseHandle(snap)
    return tabela


def arvore(pid_raiz):
    """O processo e todos os descendentes (o Windows não reparenta órfãos; basta o ppid)."""
    filhos = {}
    for pid, pai in processos().items():
        if pid != pai:
            filhos.setdefault(pai, []).append(pid)
    resultado, pendentes = [], [int(pid_raiz)]
    while pendentes:
        pid = pendentes.pop()
        if pid in resultado:
            continue
        resultado.append(pid)
        pendentes.extend(filhos.get(pid, []))
    return resultado


# ---------------------------------------------------------------- Job Object
JobObjectBasicAccountingInformation = 1
JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BASIC_LIMIT(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _EXTENDED_LIMIT(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BASIC_LIMIT),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _BASIC_ACCOUNTING(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class Trabalho:
    """Job Object: todo processo que o app abrir entra junto, e fechar o handle
    (inclusive quando este processo morre) encerra a árvore inteira."""

    def __init__(self, permitir_saida=False):
        self.h = kernel32.CreateJobObjectW(None, None)
        if not self.h:
            raise OSError(ctypes.get_last_error(), "CreateJobObject")
        info = _EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if permitir_saida:
            # quem pedir (CREATE_BREAKAWAY_FROM_JOB) sai do job e sobrevive a ele
            info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_BREAKAWAY_OK
        if not kernel32.SetInformationJobObject(
            self.h, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject")

    def incluir(self, pid):
        with _Aberto(pid, PROCESS_SET_QUOTA | PROCESS_TERMINATE) as h:
            return bool(h) and bool(kernel32.AssignProcessToJobObject(self.h, h))

    def ativos(self):
        info = _BASIC_ACCOUNTING()
        if not kernel32.QueryInformationJobObject(
            self.h, JobObjectBasicAccountingInformation, ctypes.byref(info), ctypes.sizeof(info), None
        ):
            return 0
        return int(info.ActiveProcesses)

    def encerrar(self, codigo=1):
        kernel32.TerminateJobObject(self.h, codigo)

    def fechar(self):
        if self.h:
            kernel32.CloseHandle(self.h)
            self.h = None


_job_da_sessao = []


def prender_a_sessao():
    """Põe este processo (o iniciador) num job que encerra tudo quando ele acaba.

    Os filhos (servidor, vigia, menu, e por eles os apps, o overlay e o Edge da área
    dos pais) entram junto, por herança. O handle fica só aqui e não é herdado:
    quando o iniciador morre, mesmo à força, o Windows fecha o handle e encerra o
    resto. Os jobs próprios do supervisor de apps e do menu ficam aninhados neste
    (Windows 8+). Quem precisa sobreviver ao Benikids sai com queda_windows.popen_fora_do_job."""
    job = Trabalho(permitir_saida=True)
    if not kernel32.AssignProcessToJobObject(job.h, kernel32.GetCurrentProcess()):
        erro = ctypes.get_last_error()
        job.fechar()
        raise OSError(erro, "AssignProcessToJobObject")
    _job_da_sessao.append(job)
    return job


def caminho_do_exe(pid):
    """Caminho completo do programa do processo, ou None (de outro usuário, protegido)."""
    try:
        with _Aberto(pid) as h:
            if not h:
                return None
            buf = ctypes.create_unicode_buffer(1024)
            tamanho = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(tamanho)):
                return None
            return buf.value
    except (OSError, ValueError, TypeError):
        return None


def sessao_do_processo(pid):
    sessao = wintypes.DWORD()
    if not kernel32.ProcessIdToSessionId(int(pid), ctypes.byref(sessao)):
        return None
    return sessao.value


# ---------------------------------------------------------------- janelas
GW_OWNER = 4
SW_RESTORE = 9
SW_SHOW = 5
SW_MAXIMIZE = 3
GWL_STYLE = -16
WS_MAXIMIZEBOX = 0x00010000
VK_MENU = 0x12
VK_LEFT = 0x25
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001


def janelas_de(pids):
    """Janelas visíveis de nível superior (sem dono) dos PIDs, na ordem do Z."""
    alvo = {int(p) for p in pids}
    achadas = []

    def cada(h, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in alvo and user32.IsWindowVisible(h) and not user32.GetWindow(h, GW_OWNER):
            achadas.append(h)
        return True

    user32.EnumWindows(WNDENUMPROC(cada), 0)
    return achadas


user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL


def descrever_janelas(pids):
    """Janelas visíveis de nível superior dos PIDs, com ou sem dono, na ordem do Z
    (a da frente primeiro). Cada item: hwnd, classe, titulo, dono, area, visivel.

    O diálogo de arquivo tem dono, então janelas_de não o vê. A classe vem do
    GetClassName. O título é o da legenda: em janela de outro processo o
    GetWindowText lê a legenda, não manda WM_GETTEXT. Nada de SendMessage."""
    alvo = {int(p) for p in pids}
    achadas = []
    classe_buf = ctypes.create_unicode_buffer(256)
    titulo_buf = ctypes.create_unicode_buffer(512)

    def cada(h, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value not in alvo or not user32.IsWindowVisible(h):
            return True
        user32.GetClassNameW(h, classe_buf, len(classe_buf))
        user32.GetWindowTextW(h, titulo_buf, len(titulo_buf))
        r = wintypes.RECT()
        area = 0
        if user32.GetWindowRect(h, ctypes.byref(r)):
            area = max(0, r.right - r.left) * max(0, r.bottom - r.top)
        achadas.append({
            "hwnd": h,
            "classe": classe_buf.value,
            "titulo": titulo_buf.value,
            "dono": bool(user32.GetWindow(h, GW_OWNER)),
            "area": area,
            "visivel": True,
        })
        return True

    user32.EnumWindows(WNDENUMPROC(cada), 0)
    return achadas


def fechar_extra(hwnd, classe):
    """Fecha uma janela que não é a do quiosque, sem esperar ela processar.

    PostMessage volta na hora. O #32770 (Abrir, Salvar, Imprimir) leva IDCANCEL
    antes do WM_CLOSE, para o diálogo cancelar em vez de gravar o arquivo."""
    import quiosque_edge

    ok = True
    for mensagem, wparam in quiosque_edge.mensagens_para_fechar(classe):
        ok = bool(user32.PostMessageW(hwnd, mensagem, wparam, 0)) and ok
    return ok


def travada(h):
    """O Windows considera a janela "Não respondendo" (5 s sem processar mensagens)."""
    return bool(h) and bool(user32.IsHungAppWindow(h))


SMTO_ABORTIFHUNG = 0x0002


def responde(h, ms=300):
    """A thread da janela processa um WM_NULL em até `ms` (e na hora volta se o Windows já
    a vê travada). Quem chama espera no máximo `ms`."""
    if not h:
        return False
    resultado = ctypes.c_size_t()
    return bool(user32.SendMessageTimeoutW(h, 0, 0, 0, SMTO_ABORTIFHUNG, int(ms), ctypes.byref(resultado)))


PROCESS_QUERY_INFORMATION = 0x0400
WAIT_TIMEOUT = 258


def pid_da_janela(h):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return pid.value or None


def ocioso(h):
    """O processo da janela já terminou de iniciar e espera entrada (WaitForInputIdle com
    espera 0: não bloqueia). Na dúvida (sem acesso, processo sem janela), True."""
    pid = pid_da_janela(h)
    if not pid:
        return True
    with _Aberto(pid, PROCESS_QUERY_INFORMATION | SYNCHRONIZE) as hp:
        if not hp:
            return True
        return user32.WaitForInputIdle(hp, 0) != WAIT_TIMEOUT


VK_LBUTTON, VK_RBUTTON, SM_SWAPBUTTON = 0x01, 0x02, 23


def estado_do_mouse():
    """(apertado, (x, y), pid da janela sob o cursor), lidos direto do sistema, sem
    depender de mensagem nenhuma chegar à janela. O botão "esquerdo" é o principal
    (com os botões trocados, é o direito físico: o GetAsyncKeyState olha o físico)."""
    vk = VK_RBUTTON if user32.GetSystemMetrics(SM_SWAPBUTTON) else VK_LBUTTON
    apertado = bool(user32.GetAsyncKeyState(vk) & 0x8000)
    pt = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        return apertado, None, None
    h = user32.WindowFromPoint(pt)
    return apertado, (pt.x, pt.y), (pid_da_janela(raiz_da_janela(h)) if h else None)


class _Janelas:
    """As chamadas de verdade para o janelas_seguras (todas sem esperar o outro app)."""

    travada = staticmethod(travada)
    responde = staticmethod(responde)
    ocioso = staticmethod(ocioso)

    @staticmethod
    def frente():
        return user32.GetForegroundWindow()

    @staticmethod
    def iconica(h):
        return bool(user32.IsIconic(h))

    @staticmethod
    def visivel(h):
        return bool(user32.IsWindowVisible(h))

    @staticmethod
    def mostrar(h, sw):
        user32.ShowWindowAsync(h, sw)

    @staticmethod
    def primeiro_plano(h):
        return bool(user32.SetForegroundWindow(h))

    @staticmethod
    def segurar_alt(apertar):
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_EXTENDEDKEY | (0 if apertar else KEYEVENTF_KEYUP), 0)


JANELAS = _Janelas()
ULTIMO_JEITO = [""]  # como foi o último trazer_para_frente (para o log)


def trazer_para_frente(h):
    """Primeiro plano SEM AttachThreadInput (roteiro 31: as filas ligadas travaram a
    pílula, o Tux Paint e o menu juntos). Janela travada não é tocada. Ver janelas_seguras."""
    jeito = janelas_seguras.trazer(JANELAS, h)
    ULTIMO_JEITO[0] = jeito
    return jeito in ("ja", "direto", "alt")


def raiz_da_janela(h):
    """A janela de nível superior que contém h (o Tk devolve a janela de dentro)."""
    return user32.GetAncestor(h, 2) or h  # GA_ROOT


def ativar_processo(pid, com_filhos=False):
    pids = arvore(pid) if com_filhos else [pid]
    janelas = janelas_de(pids)
    return trazer_para_frente(janelas[0]) if janelas else False


def janela_maximizavel(pid):
    """A janela principal do app (e dos filhos) que pode ser maximizada, ou None se ainda
    não apareceu.

    Só conta janela com botão de maximizar: uma caixa de aviso que abre antes (o Quatro
    em Linha avisa que falta o motor de IA) não é a janela principal, e forçar
    SW_MAXIMIZE numa janela de tamanho fixo deixa a tela preta (Quebra-cabeças)."""
    for h in janelas_de(arvore(pid)):
        if user32.GetWindowLongW(h, GWL_STYLE) & WS_MAXIMIZEBOX:
            return h
    return None


def maximizar(h):
    """Maximiza (assíncrono). Devolve True se já está ou se o pedido foi feito."""
    if travada(h):
        return False
    if not user32.IsZoomed(h):
        user32.ShowWindowAsync(h, SW_MAXIMIZE)
    return True


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)]


GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t


def nao_ativavel(h):
    """A janela nunca recebe o foco nem aparece no Alt+Tab, mas continua clicável
    (WS_EX_NOACTIVATE + WS_EX_TOOLWINDOW), e fica por cima de tudo sem ser ativada
    (SetWindowPos HWND_TOPMOST com SWP_NOACTIVATE; o lift/-topmost do Tk podem ativar).
    Devolve o exstyle lido de volta (0 se não deu)."""
    if not h:
        return 0
    ex = user32.GetWindowLongPtrW(h, GWL_EXSTYLE)
    novo = (ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    flags = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
    if novo != ex:
        user32.SetWindowLongPtrW(h, GWL_EXSTYLE, novo)
        flags |= 0x0020  # FRAMECHANGED
    user32.SetWindowPos(h, wintypes.HWND(-1), 0, 0, 0, 0, flags)  # HWND_TOPMOST
    return user32.GetWindowLongPtrW(h, GWL_EXSTYLE) & 0xFFFFFFFF


def esta_maximizada(h):
    return bool(user32.IsZoomed(h))


def retangulo(h):
    r = wintypes.RECT()
    if not user32.GetWindowRect(h, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


def areas_do_monitor(h):
    """(área de trabalho, monitor inteiro) do monitor onde a janela está."""
    m = user32.MonitorFromWindow(h, 2)  # MONITOR_DEFAULTTONEAREST
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if not m or not user32.GetMonitorInfoW(m, ctypes.byref(info)):
        return None, None
    t, mon = info.rcWork, info.rcMonitor
    return (t.left, t.top, t.right, t.bottom), (mon.left, mon.top, mon.right, mon.bottom)


WS_MAXIMIZE = 0x01000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
SWP_TELA = 0x0004 | 0x0010 | 0x0020 | 0x0200 | 0x4000  # NOZORDER|NOACTIVATE|FRAMECHANGED|NOOWNERZORDER|ASYNC


def sem_moldura(h):
    return not user32.GetWindowLongPtrW(h, GWL_STYLE) & (WS_CAPTION | WS_THICKFRAME)


def tela_cheia_sem_moldura(h, monitor):
    """Tira o estado de maximizada e a moldura (título, bordas, botões) e põe a janela no
    tamanho do monitor: o "tela cheia sem borda" dos jogos. Devolve o estilo de antes,
    ou None se o app não respondeu (não mexe; tenta na volta seguinte).

    O SetWindowLongPtr do estilo espera o app (WM_STYLECHANGING): só depois de ele
    responder, e o overlay chama isto na thread de trabalho, nunca na do Tk."""
    if not janelas_seguras.pode_mexer(JANELAS, h):
        return None
    estilo = user32.GetWindowLongPtrW(h, GWL_STYLE)
    novo = estilo & ~(WS_MAXIMIZE | WS_CAPTION | WS_THICKFRAME)
    if novo != estilo:
        user32.SetWindowLongPtrW(h, GWL_STYLE, novo)
    x, y, direita, baixo = monitor
    user32.SetWindowPos(h, None, x, y, direita - x, baixo - y, SWP_TELA)
    return estilo


def devolver_moldura(h, estilo, retangulo_antes=None):
    """Desfaz o tela_cheia_sem_moldura: o estilo de antes (sem o WS_MAXIMIZE, que o
    ShowWindowAsync põe de volta do jeito certo) e a janela maximizada. Uma janela que
    não era maximizada (o Tux Paint, do tamanho da tela com a moldura para fora) volta
    ao retângulo de antes: SW_MAXIMIZE numa janela de tamanho fixo deixa a tela preta."""
    if not janelas_seguras.pode_mexer(JANELAS, h):
        return False
    if estilo:
        user32.SetWindowLongPtrW(h, GWL_STYLE, estilo & ~WS_MAXIMIZE)
        user32.SetWindowPos(h, None, 0, 0, 0, 0, 0x0001 | 0x0002 | SWP_TELA)
    if estilo and not estilo & WS_MAXIMIZE and retangulo_antes:
        x, y, direita, baixo = retangulo_antes
        user32.SetWindowPos(h, None, x, y, direita - x, baixo - y, SWP_TELA)
    else:
        user32.ShowWindowAsync(h, SW_MAXIMIZE)
    return True


def mover_por_cima(h, x, y):
    """Põe a janela em x,y, por cima de tudo, sem mudar o tamanho nem roubar o foco.
    O Tk às vezes deixa uma janela sem moldura em 0,0 (o aviso de 10 s no Windows)."""
    if not h:
        return False
    # HWND_TOPMOST = -1; SWP_NOSIZE | SWP_NOACTIVATE = 0x0001 | 0x0010
    return bool(user32.SetWindowPos(h, wintypes.HWND(-1), int(x), int(y), 0, 0, 0x0011))


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def segundos_sem_uso():
    """Há quanto tempo ninguém mexe no teclado, mouse ou toque (GetLastInputInfo)."""
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    agora = kernel32.GetTickCount() & 0xFFFFFFFF
    return ((agora - info.dwTime) & 0xFFFFFFFF) / 1000.0


def pid_da_janela_ativa():
    h = user32.GetForegroundWindow()
    if not h:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return pid.value or None


def alt_esquerda(pid_raiz, hwnd=None):
    """Alt+← na janela do app (o "‹ Voltar" do overlay nos sites).

    hwnd, quando vem, é a do quiosque: a da frente pode ser uma janela extra
    que o vigia está fechando, e o Alt+← não pode ir para ela."""
    if not hwnd:
        janelas = janelas_de(arvore(pid_raiz))
        hwnd = janelas[0] if janelas else None
    if not hwnd or not trazer_para_frente(hwnd):
        return False
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_LEFT, 0, 0, 0)
    user32.keybd_event(VK_LEFT, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    return True


# ---------------------------------------------------------------- instância única
ERROR_ALREADY_EXISTS = 183
_mutexes = []


def instancia_unica(nome):
    """True se esta é a única instância (o mutex vive até o processo sair)."""
    h = kernel32.CreateMutexW(None, False, nome)
    erro = ctypes.get_last_error()
    if not h:
        return True
    _mutexes.append(h)
    return erro != ERROR_ALREADY_EXISTS


def sem_console():
    """creationflags para programas de console (taskkill, shutdown) sem abrir janela."""
    return 0x08000000  # CREATE_NO_WINDOW


def caminho_programa(*partes):
    """Primeiro arquivo que existe em Program Files / Program Files (x86) / LocalAppData."""
    raizes = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    for raiz in raizes:
        if not raiz:
            continue
        caminho = os.path.join(raiz, *partes)
        if os.path.isfile(caminho):
            return caminho
    return None
