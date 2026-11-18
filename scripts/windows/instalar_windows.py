"""Instalador do Benikids no Windows (roda com o Python que vem no pacote).

Instala para o usuário atual, sem pedir administrador:
- o launcher em %USERPROFILE%\\.local\\share\\cozy-kids-launcher (as mesmas pastas do
  Linux, que o servidor já usa);
- a configuração inicial, só se ainda não existir;
- atalhos "Benikids" na área de trabalho e no menu Iniciar.

Para instalar no usuário da criança, rode estando logado nele.
"""

import ctypes
import os
import shutil
import subprocess
import sys
import time

PACOTE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
APP_ROOT = os.path.join(HOME, ".local", "share", "cozy-kids-launcher")
CONFIG = os.path.join(HOME, ".config", "cozy-kids-launcher", "config.json")
CACHE = os.path.join(HOME, ".cache", "cozy-kids-launcher")
NOME = "Benikids"


def aviso(texto, titulo="Benikids", estilo=0x40):
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


def _app():
    pasta = os.path.join(PACOTE, "app")
    if pasta not in sys.path:
        sys.path.insert(0, pasta)


def menu_aberto():
    """O que fazer com o Benikids aberto: "seguir", "esperar" (o iniciador está vivo e
    fecha pelo Sair) ou "limpar" (só restos de uma queda, que ninguém fecha pelo Sair)."""
    rodando = processo_rodando()
    if not rodando:
        return "seguir"
    try:
        _app()
        import queda_windows

        return queda_windows.o_que_fazer_com_menu_aberto(rodando, queda_windows.iniciador_vivo())
    except ImportError:
        return "esperar"


def fechar_restos():
    """Encerra o menu órfão, o servidor e o vigia que sobraram de uma queda (pelo caminho
    da instalação, como a limpeza do iniciador) e espera o beni-menu.exe soltar."""
    try:
        _app()
        import plataforma_windows
        import queda_windows

        pids = queda_windows.encerrar_restos(plataforma_windows, APP_ROOT, CACHE, os.getpid())
        print(f"restos de uma queda encerrados: {len(pids)}")
    except (ImportError, OSError) as e:
        print(f"restos: {e}")
    for _ in range(10):
        if not processo_rodando():
            return True
        time.sleep(1)
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
        "$s.Description='Benikids - o cantinho das crianças';$s.Save()"
    )
    env = dict(os.environ, BENI_LNK=caminho, BENI_ALVO=alvo, BENI_ARGS=argumentos,
               BENI_PASTA=pasta, BENI_ICONE=icone)
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                   env=env, check=True, creationflags=0x08000000, timeout=60)


def pasta_especial(csidl):
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return buf.value


def copiar_pacote():
    os.makedirs(APP_ROOT, exist_ok=True)
    copiar_arvore(os.path.join(PACOTE, "app"), APP_ROOT)
    copiar_arvore(os.path.join(PACOTE, "python"), os.path.join(APP_ROOT, "python"))


def esperar_sair(pid, limite=60):
    """Espera o processo (o iniciador antigo) terminar, para os arquivos ficarem livres."""
    try:
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
        if handle:
            kernel.WaitForSingleObject(handle, int(limite * 1000))
            kernel.CloseHandle(handle)
    except (AttributeError, OSError, ValueError):
        time.sleep(5)
    for _ in range(limite):
        situacao = menu_aberto()
        if situacao == "seguir":
            return True
        if situacao == "limpar":
            # o iniciador já saiu e o menu ficou: órfão de uma queda de antes (até a
            # 1.0.6, sem o job da sessão); sem isso a atualização falharia para sempre
            return fechar_restos()
        time.sleep(1)
    return False


def atualizar(pid):
    """--atualizacao: chamado pelo iniciador (atualizar_windows.aplicar_e_sair), com o
    Python deste pacote novo. Sem perguntas: guarda uma cópia, instala por cima e abre o
    Benikids de novo; se falhar, volta a cópia."""
    _app()
    import atualizar_windows
    import telemetria

    with open(os.path.join(PACOTE, "app", "version"), encoding="utf-8") as f:
        versao = f.read().strip()
    copia = APP_ROOT + ".anterior"
    pythonw = os.path.join(APP_ROOT, "python", "pythonw.exe")
    iniciador = os.path.join(APP_ROOT, "beni_windows.py")
    try:
        if not esperar_sair(pid):
            raise RuntimeError("o Benikids não fechou")
        shutil.rmtree(copia, ignore_errors=True)
        shutil.copytree(APP_ROOT, copia)
        try:
            copiar_pacote()
        except Exception:
            copiar_arvore(copia, APP_ROOT)
            raise
    except Exception:  # noqa: BLE001
        import traceback

        atualizar_windows.marcar_falha(versao)
        telemetria.relatar_problema("atualizar_windows", traceback.format_exc(),
                                    assinatura="atualizar_windows:" + type(sys.exc_info()[1]).__name__)
    subprocess.Popen([pythonw, iniciador], cwd=APP_ROOT, close_fds=True, creationflags=0x08000000)
    return 0


def main():
    args = sys.argv[1:]
    if args[:1] == ["--atualizacao"]:
        return atualizar(args[1] if len(args) > 1 else 0)
    situacao = menu_aberto()
    if situacao == "limpar" and not fechar_restos():
        situacao = "esperar"
    if situacao == "esperar":
        aviso("O Benikids está aberto. Feche (Pais → Sair) e rode o instalador de novo.", estilo=0x30)
        return 1
    copiar_pacote()
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
    for antigo in destinos:  # atalhos "Beni.lnk" das primeiras versões
        try:
            os.remove(os.path.join(os.path.dirname(antigo), "Beni.lnk"))
        except OSError:
            pass
    for lnk in destinos:
        try:
            atalho(lnk, pythonw, f'"{iniciador}"', APP_ROOT, icone)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"atalho {lnk}: {e}")

    # abrir sozinho ao entrar no Windows (padrão ligado; os pais mudam na área dos pais)
    try:
        import json

        sys.path.insert(0, APP_ROOT)
        import inicio_automatico

        with open(CONFIG, encoding="utf-8") as f:
            inicio_automatico.aplicar(json.load(f), APP_ROOT)
    except (OSError, ValueError, ImportError) as e:
        print(f"início automático: {e}")

    # catálogo: jogos e programas livres (todos ligados; os pais desligam os que não quiserem)
    if aviso("Instalar agora os jogos e programas do Benikids?\n\n"
             "São apps livres para crianças (GCompris, Tux Paint, SuperTux, Scratch...). "
             "Leva alguns minutos; alguns pedem a senha de um administrador do computador.",
             estilo=0x24) == 6:
        subprocess.run([pythonw, os.path.join(APP_ROOT, "instalar_apps.py")], cwd=APP_ROOT)

    texto = "O Benikids foi instalado.\n\nUse o ícone \"Benikids\" na área de trabalho. Ele também abre sozinho quando alguém entra neste usuário do Windows."
    texto += "\n\nAbrir agora?"
    if aviso(texto, estilo=0x44) == 6:  # Sim
        subprocess.Popen([pythonw, iniciador], cwd=APP_ROOT, close_fds=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — sem console (pythonw), o erro precisa aparecer numa janela
        import traceback

        aviso("Não deu para instalar o Benikids.\n\n" + traceback.format_exc()[-1500:], estilo=0x10)
        try:
            sys.path.insert(0, os.path.join(PACOTE, "app"))
            import telemetria

            telemetria.relatar_problema("instalar_benikids", traceback.format_exc(),
                                        assinatura="instalar_benikids:" + type(sys.exc_info()[1]).__name__)
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
