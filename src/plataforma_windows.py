"""O que no Linux vem de /proc, sinais, prctl e xdotool, feito no Windows (ctypes).

Só é importado quando os.name == "nt". Sem dependências além da biblioteca padrão.
"""

import ctypes
import os
from ctypes import wintypes

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
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]


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

    def __init__(self):
        self.h = kernel32.CreateJobObjectW(None, None)
        if not self.h:
            raise OSError(ctypes.get_last_error(), "CreateJobObject")
        info = _EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
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


def trazer_para_frente(h):
    """SetForegroundWindow "emprestando" a entrada da janela da frente: sem isso o
    Windows só pisca o botão na barra de tarefas quando um processo de fundo pede."""
    if not h:
        return False
    frente = user32.GetForegroundWindow()
    if frente == h:
        return True
    t_frente = user32.GetWindowThreadProcessId(frente, None) if frente else 0
    eu = kernel32.GetCurrentThreadId()
    ligou = bool(t_frente) and t_frente != eu and user32.AttachThreadInput(eu, t_frente, True)
    try:
        if user32.IsIconic(h):
            user32.ShowWindow(h, SW_RESTORE)
        else:
            user32.ShowWindow(h, SW_SHOW)
        user32.BringWindowToTop(h)
        ok = bool(user32.SetForegroundWindow(h))
    finally:
        if ligou:
            user32.AttachThreadInput(eu, t_frente, False)
    return ok


def ativar_processo(pid, com_filhos=False):
    pids = arvore(pid) if com_filhos else [pid]
    janelas = janelas_de(pids)
    return trazer_para_frente(janelas[0]) if janelas else False


def maximizar_processo(pid):
    """Maximiza a janela principal do app (e dos filhos). Devolve True quando ela existe
    e ficou maximizada; False se ainda não apareceu.

    Só conta janela com botão de maximizar: uma caixa de aviso que abre antes (o Quatro
    em Linha avisa que falta o motor de IA) não é a janela principal, e forçar
    SW_MAXIMIZE numa janela de tamanho fixo deixa a tela preta (Quebra-cabeças)."""
    for h in janelas_de(arvore(pid)):
        if not user32.GetWindowLongW(h, GWL_STYLE) & WS_MAXIMIZEBOX:
            continue
        if not user32.IsZoomed(h):
            user32.ShowWindow(h, SW_MAXIMIZE)
        return True
    return False


def pid_da_janela_ativa():
    h = user32.GetForegroundWindow()
    if not h:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return pid.value or None


def alt_esquerda(pid_raiz):
    """Alt+← na janela do app (o "‹ Voltar" do overlay nos sites)."""
    janelas = janelas_de(arvore(pid_raiz))
    if not janelas or not trazer_para_frente(janelas[0]):
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
