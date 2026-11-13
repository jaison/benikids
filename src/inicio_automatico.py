"""Abrir o Benikids ao entrar no computador (config "startOnLogin", padrão ligado).

- Windows: valor "Benikids" em HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
  (por usuário, sem administrador).
- Linux: o instalador cria ~/.config/autostart/cozy-kids-launcher-autostart.desktop;
  aqui só se liga/desliga esse arquivo (Hidden / X-GNOME-Autostart-enabled).
"""

import os
import sys

NOME_WINDOWS = "Benikids"
CHAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
DESKTOP_LINUX = os.path.join(
    os.path.expanduser("~"), ".config", "autostart", "cozy-kids-launcher-autostart.desktop"
)


def ligado_na_config(cfg):
    return cfg.get("startOnLogin", True) is not False


def comando_windows(app_root):
    pythonw = os.path.join(app_root, "python", "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return f'"{pythonw}" "{os.path.join(app_root, "beni_windows.py")}" --autostart'


def _aplicar_windows(ligado, app_root):
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN, 0,
                        winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as chave:
        if ligado:
            winreg.SetValueEx(chave, NOME_WINDOWS, 0, winreg.REG_SZ, comando_windows(app_root))
        else:
            try:
                winreg.DeleteValue(chave, NOME_WINDOWS)
            except FileNotFoundError:
                pass
    return ligado


def _aplicar_linux(ligado, caminho=DESKTOP_LINUX):
    try:
        with open(caminho, encoding="utf-8") as f:
            linhas = f.read().splitlines()
    except OSError:
        return None  # sem o arquivo do instalador não há o que ligar
    fora = ("Hidden=", "X-GNOME-Autostart-enabled=")
    linhas = [linha for linha in linhas if not linha.startswith(fora)]
    linhas += [f"Hidden={'false' if ligado else 'true'}",
               f"X-GNOME-Autostart-enabled={'true' if ligado else 'false'}"]
    temp = caminho + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    os.replace(temp, caminho)
    return ligado


def aplicar(cfg, app_root, caminho_linux=DESKTOP_LINUX):
    """Deixa o sistema como a config pede. Devolve o estado aplicado (None se não deu)."""
    ligado = ligado_na_config(cfg)
    try:
        if os.name == "nt":
            return _aplicar_windows(ligado, app_root)
        return _aplicar_linux(ligado, caminho_linux)
    except OSError:
        return None
