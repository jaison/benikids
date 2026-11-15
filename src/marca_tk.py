"""Cores, fonte e ícone da marca Benikids para as janelas Tk (instalador de apps no
Windows e a pílula ✕/tempo do overlay, nos dois sistemas).

As cores são as de site/style.css (bloco :root). A fonte de título é a Fredoka
SemiBold de themes/fonts, carregada só para este processo (não instala nada no
sistema); sem ela, cai na fonte do sistema.
"""
import ctypes
import os

AQUI = os.path.dirname(os.path.abspath(__file__))

AZUL = "#2a78b2"
AZUL_ESCURO = "#1d5f93"
MARINHO = "#1e3e64"
AMARELO = "#fbb813"
LARANJA = "#f2622e"
LARANJA_ESCURO = "#b8441a"
CEU = "#acdef9"
CEU_SUAVE = "#e8f6fe"
BG = "#f7fbff"
SUPERFICIE = "#ffffff"
TEXTO = "#16304f"
APAGADO = "#46607e"
BORDA = "#cfe6f5"

FONTE_CORPO = "Segoe UI" if os.name == "nt" else "Ubuntu"
# Nome da família: no Windows (GDI) é "Fredoka SemiBold"; no Linux o fontconfig lista
# "Fredoka,Fredoka SemiBold" e o Tk usa só o primeiro, "Fredoka".
FREDOKA = "Fredoka SemiBold"
_NOMES_FREDOKA = ("Fredoka SemiBold", "Fredoka")
_ARQUIVO_FREDOKA = "Fredoka-SemiBold.ttf"
_carregada = None


def _arquivo(*nomes):
    """Procura ao lado do app (pacote: app/themes/fonts) e no repositório (src/../themes)."""
    for base in (AQUI, os.path.dirname(AQUI)):
        caminho = os.path.join(base, *nomes)
        if os.path.isfile(caminho):
            return caminho
    return None


def _registrar_fonte(caminho):
    try:
        if os.name == "nt":
            FR_PRIVATE = 0x10
            return ctypes.windll.gdi32.AddFontResourceExW(caminho, FR_PRIVATE, None) > 0
        fc = ctypes.CDLL("libfontconfig.so.1")
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        return bool(fc.FcConfigAppFontAddFile(None, caminho.encode()))
    except (OSError, AttributeError):
        return False


def fonte_titulo(raiz):
    """Família para títulos: Fredoka se deu para carregar, senão a fonte do sistema.
    Chame depois de criar o tk.Tk()."""
    global _carregada
    if _carregada is None:
        _carregada = False
        caminho = _arquivo("themes", "fonts", _ARQUIVO_FREDOKA)
        if caminho and _registrar_fonte(caminho):
            try:
                from tkinter import font as tkfont

                familias = set(tkfont.families(raiz))
                _carregada = next((n for n in _NOMES_FREDOKA if n in familias), False)
            except Exception:  # noqa: BLE001
                _carregada = False
    return _carregada or FONTE_CORPO


def titulo(tamanho):
    """Fonte de título já com o peso: Fredoka (que já é SemiBold) ou a do sistema em
    negrito. Use depois de fonte_titulo(raiz)."""
    return (_carregada, tamanho) if _carregada else (FONTE_CORPO, tamanho, "bold")


def por_icone(raiz):
    """Ícone da janela no Windows (barra de tarefas/Alt+Tab): o beni.ico do atalho.
    No Linux as janelas Tk do Benikids não aparecem na barra (overrideredirect)."""
    if os.name != "nt":
        return
    ico = _arquivo("beni.ico")
    if ico:
        try:
            raiz.iconbitmap(default=ico)
        except Exception:  # noqa: BLE001
            pass
