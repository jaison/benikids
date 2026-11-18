"""Ajudante de teste (só Windows, nunca vai para o pacote): uma janela Win32 de verdade
que fica "Não respondendo".

Uso: python janela_travada.py <segundos dormindo>

Cria uma janela visível, bombeia mensagens por ~1 s (com espera de entrada, para o
Windows deixar de considerá-la "iniciando"), escreve "pronto <hwnd>" e então DORME na
própria thread da janela, sem bombear. É o que um app travado faz: a thread da janela
não está esperando entrada nem lendo a fila. Um processo suspenso dentro do GetMessage,
ao contrário, continua "esperando entrada" e o IsHungAppWindow não vira True (roteiro
34: foi o que o claude-win viu no PC). Depois de dormir, escreve "acordei" e volta a
bombear até ser encerrado.
"""

import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
                                wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.MsgWaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD,
                                             wintypes.DWORD]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

WS_OVERLAPPEDWINDOW_VISIVEL = 0x00CF0000 | 0x10000000
PM_REMOVE = 1
QS_ALLINPUT = 0x04FF


@WNDPROC
def procedimento(h, msg, wp, lp):
    return user32.DefWindowProcW(h, msg, wp, lp)


def bombear(segundos):
    fim = time.monotonic() + segundos
    msg = wintypes.MSG()
    while time.monotonic() < fim:
        # espera de entrada de verdade: tira o processo do estado "iniciando"
        user32.MsgWaitForMultipleObjects(0, None, False, 20, QS_ALLINPUT)
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


def main():
    dorme = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    instancia = kernel32.GetModuleHandleW(None)
    classe = WNDCLASSW()
    classe.lpfnWndProc = procedimento
    classe.hInstance = instancia
    classe.lpszClassName = "BenikidsJanelaTravadaDeTeste"
    if not user32.RegisterClassW(ctypes.byref(classe)):
        raise OSError(ctypes.get_last_error(), "RegisterClassW")
    h = user32.CreateWindowExW(0, classe.lpszClassName, "Janela travada (teste)", WS_OVERLAPPEDWINDOW_VISIVEL,
                               100, 100, 400, 300, None, None, instancia, None)
    if not h:
        raise OSError(ctypes.get_last_error(), "CreateWindowExW")
    bombear(1.2)
    print(f"pronto {h}", flush=True)
    time.sleep(dorme)  # a thread da janela para de ler a fila: "Não respondendo"
    print("acordei", flush=True)
    bombear(600)


if __name__ == "__main__":
    main()
