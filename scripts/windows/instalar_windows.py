"""Instalador do Beni no Windows (roda com o Python que vem no pacote).

Instala para o usuário atual, sem pedir administrador:
- o launcher em %USERPROFILE%\\.local\\share\\cozy-kids-launcher (as mesmas pastas do
  Linux, que o servidor já usa);
- a configuração inicial, só se ainda não existir;
- atalhos "Beni" na área de trabalho e no menu Iniciar.

Para instalar no usuário da criança, rode estando logado nele.
"""

import ctypes
import os
import shutil
import subprocess
import sys

PACOTE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
APP_ROOT = os.path.join(HOME, ".local", "share", "cozy-kids-launcher")
CONFIG = os.path.join(HOME, ".config", "cozy-kids-launcher", "config.json")
NOME = "Beni"


def aviso(texto, titulo="Beni", estilo=0x40):
    try:
        return ctypes.windll.user32.MessageBoxW(None, texto, titulo, estilo)
    except (AttributeError, OSError):
        print(texto)
        return 0


def processo_rodando():
    try:
        saida = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq beni-menu.exe", "/NH"],
            capture_output=True, text=True, creationflags=0x08000000, timeout=10,
        ).stdout
        return "beni-menu.exe" in saida.lower()
    except (OSError, subprocess.SubprocessError):
        return False


def copiar_arvore(origem, destino):
    """Copia por cima, sem apagar o que só existe no destino (capas baixadas etc.)."""
    for raiz, _pastas, arquivos in os.walk(origem):
        alvo = os.path.join(destino, os.path.relpath(raiz, origem))
        os.makedirs(alvo, exist_ok=True)
        for nome in arquivos:
            shutil.copy2(os.path.join(raiz, nome), os.path.join(alvo, nome))


def atalho(caminho, alvo, argumentos, pasta, icone):
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:BENI_LNK);"
        "$s.TargetPath=$env:BENI_ALVO;$s.Arguments=$env:BENI_ARGS;"
        "$s.WorkingDirectory=$env:BENI_PASTA;$s.IconLocation=$env:BENI_ICONE;"
        "$s.Description='Beni - o cantinho das crianças';$s.Save()"
    )
    env = dict(os.environ, BENI_LNK=caminho, BENI_ALVO=alvo, BENI_ARGS=argumentos,
               BENI_PASTA=pasta, BENI_ICONE=icone)
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                   env=env, check=True, creationflags=0x08000000, timeout=60)


def pasta_especial(csidl):
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return buf.value


def main():
    if processo_rodando():
        aviso("O Beni está aberto. Feche (Pais → Sair) e rode o instalador de novo.", estilo=0x30)
        return 1
    os.makedirs(APP_ROOT, exist_ok=True)
    copiar_arvore(os.path.join(PACOTE, "app"), APP_ROOT)
    copiar_arvore(os.path.join(PACOTE, "python"), os.path.join(APP_ROOT, "python"))
    criou_config = False
    if not os.path.isfile(CONFIG):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        shutil.copy2(os.path.join(PACOTE, "config-padrao.json"), CONFIG)
        criou_config = True

    pythonw = os.path.join(APP_ROOT, "python", "pythonw.exe")
    iniciador = os.path.join(APP_ROOT, "beni_windows.py")
    icone = os.path.join(APP_ROOT, "beni.ico")
    if not os.path.isfile(icone):
        icone = os.path.join(APP_ROOT, "beni-menu.exe")
    destinos = [
        os.path.join(pasta_especial(0x10), f"{NOME}.lnk"),  # área de trabalho
        os.path.join(pasta_especial(0x02), f"{NOME}.lnk"),  # menu Iniciar > Programas
    ]
    for lnk in destinos:
        try:
            atalho(lnk, pythonw, f'"{iniciador}"', APP_ROOT, icone)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"atalho {lnk}: {e}")

    texto = "O Beni foi instalado.\n\nUse o ícone \"Beni\" na área de trabalho."
    if criou_config:
        texto += ("\n\nNa primeira vez, entre em Pais e crie um PIN: sem PIN, qualquer um "
                  "consegue sair do Beni.")
    texto += "\n\nAbrir agora?"
    if aviso(texto, estilo=0x44) == 6:  # Sim
        subprocess.Popen([pythonw, iniciador], cwd=APP_ROOT, close_fds=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
