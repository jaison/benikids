"""Iniciador do Beni no Windows: faz o papel do beni/bin/cozy-kids-launcher (bash).

Sobe o servidor (server.py), o vigia do timer (timer_watchdog.py) e o menu nativo
(beni-menu.exe), registra o menu como o processo "browser" e fica olhando:
- "Sair" na área dos pais (exit-kids) cria o arquivo exit-requested: tudo fecha;
- o servidor caiu: sobe de novo (até 3 vezes em 60 s);
- o menu caiu: reabre; sem GPU (código 75), cedo demais ou na 3ª queda, troca
  pelo menu web num navegador em modo quiosque.

Roda com o pythonw.exe que vem no pacote (sem janela de console).
"""

import os
import socket
import subprocess
import sys
import time

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_ROOT)

import plataforma_windows as win  # noqa: E402
import telemetria  # noqa: E402
from app_detection import browser_family, find_browser  # noqa: E402
from process_state import (  # noqa: E402
    owned_process,
    remove_process_record,
    terminate_owned_process,
    write_process_record,
)

HOME = os.path.expanduser("~")
CACHE = os.path.join(HOME, ".cache", "cozy-kids-launcher")
CONFIG = os.path.join(HOME, ".config", "cozy-kids-launcher")
PORTA = int(os.environ.get("COZY_KIDS_PORT", "38431"))
EXIT_FLAG = os.path.join(CACHE, "exit-requested")
BROWSER_PIDFILE = os.path.join(CACHE, "browser.pid")
TILE_PIDFILE = os.path.join(CACHE, "tile-process.pid")
OVERLAY_PIDFILE = os.path.join(CACHE, "overlay.pid")
LOG = os.path.join(CACHE, "beni-windows.log")
MENU_LOG = os.path.join(CACHE, "menu-nativo.log")
SEM_GPU = 75
SEM_CONSOLE = 0x08000000


def log(texto):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")
    except OSError:
        pass


def pythonw():
    exe = sys.executable
    candidato = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return candidato if os.path.isfile(candidato) else exe


def porta_aberta(timeout=0.3):
    try:
        with socket.create_connection(("127.0.0.1", PORTA), timeout=timeout):
            return True
    except OSError:
        return False


def iniciar(argv, log_em=None):
    saida = subprocess.DEVNULL
    if log_em:
        try:
            # como no Linux: acumula e corta quando passa de 200 KB
            if os.path.getsize(log_em) > 200_000:
                with open(log_em, "rb") as f:
                    f.seek(-50_000, os.SEEK_END)
                    fim = f.read()
                with open(log_em, "wb") as f:
                    f.write(fim)
        except OSError:
            pass
        try:
            saida = open(log_em, "a", encoding="utf-8")
        except OSError:
            saida = subprocess.DEVNULL
    try:
        return subprocess.Popen(
            argv,
            cwd=APP_ROOT,
            env=dict(os.environ, COZY_KIDS_PORT=str(PORTA)),
            stdin=subprocess.DEVNULL,
            stdout=saida,
            stderr=saida,
            creationflags=SEM_CONSOLE,
        )
    finally:
        if saida is not subprocess.DEVNULL:
            saida.close()


def subir_servidor(tentativa=0):
    env_extra = {"COZY_KIDS_RECOVERY_ATTEMPT": str(tentativa)} if tentativa else {}
    os.environ.update(env_extra)
    p = iniciar([pythonw(), os.path.join(APP_ROOT, "server.py")])
    for _ in range(100):
        if porta_aberta():
            return p
        if p.poll() is not None:
            break
        time.sleep(0.1)
    log(f"servidor não abriu a porta (saída {p.poll()})")
    return p


def navegador():
    try:
        import json

        with open(os.path.join(CONFIG, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    return find_browser(cfg)


def relatar_menu(codigo):
    """O menu nativo não ficou de pé: guarda o fim do log dele para o relatório de problema."""
    try:
        with open(MENU_LOG, encoding="utf-8", errors="replace") as f:
            fim = f.read()[-3000:]
    except OSError:
        fim = ""
    telemetria.relatar_problema("menu_nativo", f"código {codigo}\n{fim}",
                                assinatura=f"menu_nativo:{'sem_gpu' if codigo == SEM_GPU else codigo}")


def abrir_menu(usar_web):
    nav = navegador()
    exe = os.path.join(APP_ROOT, "beni-menu.exe")
    if not usar_web and os.path.isfile(exe):
        familia = browser_family(nav) if nav else "chromium"
        argv = [
            exe,
            "--porta", str(PORTA),
            "--app-root", APP_ROOT,
            "--web-cmd", nav or "msedge",
            "--web-familia", familia,
            "--web-perfil", os.path.join(CACHE, f"menu-{familia}-profile"),
        ]
        return iniciar(argv, log_em=MENU_LOG), "nativo"
    if not nav:
        log("sem navegador para o menu web")
        return None, "nenhum"
    url = f"http://127.0.0.1:{PORTA}/index.html"
    if browser_family(nav) == "chromium":
        argv = [nav, f"--user-data-dir={os.path.join(CACHE, 'menu-chromium-profile')}",
                "--no-first-run", "--disable-session-crashed-bubble", "--kiosk", url]
    else:
        perfil = os.path.join(CACHE, "menu-firefox-profile")
        os.makedirs(perfil, exist_ok=True)
        argv = [nav, "--no-remote", "--profile", perfil, "--kiosk", url]
    return iniciar(argv), "web"


def parar(p):
    if p is not None and p.poll() is None:
        try:
            p.terminate()
            p.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass


def encerrar_tudo(servidor, vigia, menu):
    for pidfile, papel in ((OVERLAY_PIDFILE, "overlay"), (TILE_PIDFILE, "tile-process")):
        try:
            terminate_owned_process(pidfile, papel)
        except OSError:
            pass
    parar(menu)
    parar(vigia)
    parar(servidor)
    remove_process_record(BROWSER_PIDFILE)


def atualizacao_pendente():
    """Versão nova já baixada e conferida: chama o instalador dela antes de subir qualquer
    coisa (o Python e os arquivos daqui ficam livres quando este processo sai)."""
    try:
        import atualizar_windows

        pronta = atualizar_windows.pendente(APP_ROOT)
        if not pronta:
            return False
        log(f"atualização: instalando a versão {pronta[0]}")
        return atualizar_windows.aplicar_e_sair(pronta[1], log)
    except Exception as erro:  # noqa: BLE001 — a atualização nunca impede o Benikids de abrir
        log(f"atualização: {erro}")
        return False


def atualizar_se_parado():
    """True se começou a instalar uma versão pronta (o iniciador deve sair)."""
    try:
        import atualizar_windows

        pronta = atualizar_windows.pendente(APP_ROOT)
        if not atualizar_windows.hora_de_atualizar(pronta, owned_process(TILE_PIDFILE, "tile-process"),
                                 win.segundos_sem_uso()):
            return False
        log(f"atualização: computador parado; instalando a versão {pronta[0]} agora")
        return atualizar_windows.aplicar_e_sair(pronta[1], log)
    except Exception as erro:  # noqa: BLE001 — nunca derruba o menu
        log(f"atualização: {erro}")
        return False


def procurar_atualizacao_depois(espera=120):
    """Em segundo plano, alguns minutos depois de abrir: procura e baixa uma versão nova
    (no máximo uma vez por dia). Ela é instalada na próxima vez que o Benikids abrir."""
    import threading

    def trabalhar():
        time.sleep(espera)
        try:
            import atualizar_windows

            versao = atualizar_windows.verificar(APP_ROOT)
            if versao:
                log(f"atualização: versão {versao} baixada; instala na próxima abertura")
        except Exception as erro:  # noqa: BLE001
            log(f"atualização: não deu para procurar ({erro})")

    threading.Thread(target=trabalhar, daemon=True).start()


def main():
    os.makedirs(CACHE, exist_ok=True)
    if "--autostart" in sys.argv[1:]:
        # ao entrar no Windows: deixa a área de trabalho e a rede subirem antes
        time.sleep(6)
    if not win.instancia_unica("Local\\BeniLauncher"):
        # já está aberto: só traz o menu para a frente
        from process_state import owned_process

        registro = owned_process(BROWSER_PIDFILE, "browser")
        if registro:
            win.ativar_processo(registro["pid"], com_filhos=True)
        return 0
    try:
        os.unlink(EXIT_FLAG)
    except OSError:
        pass
    log(f"início (python {sys.version.split()[0]}, {APP_ROOT})")
    if atualizacao_pendente():
        return 0  # o instalador da versão nova abre o Benikids de novo quando terminar
    procurar_atualizacao_depois()

    servidor = None if porta_aberta() else subir_servidor()
    vigia = iniciar([pythonw(), os.path.join(APP_ROOT, "timer_watchdog.py"), "--port", str(PORTA)])
    usar_web = os.path.isfile(os.path.join(CONFIG, "menu")) and \
        open(os.path.join(CONFIG, "menu"), encoding="utf-8").read().strip() == "web"
    quedas_menu = 0
    quedas_servidor = []
    menu = None
    try:
        while True:
            menu, tipo = abrir_menu(usar_web)
            if menu is None:
                return 1
            aberto_em = time.monotonic()
            try:
                write_process_record(BROWSER_PIDFILE, menu.pid, "browser")
            except (OSError, ValueError) as e:
                log(f"não registrei o menu: {e}")
            log(f"menu {tipo} aberto (pid {menu.pid})")
            proxima_olhada = time.monotonic() + 300
            while True:
                time.sleep(1)
                if time.monotonic() >= proxima_olhada:
                    proxima_olhada = time.monotonic() + 300
                    if atualizar_se_parado():
                        return 0  # o instalador abre o Benikids de novo quando terminar
                if os.path.exists(EXIT_FLAG):
                    log("saída pedida (exit-kids)")
                    try:
                        os.unlink(EXIT_FLAG)
                    except OSError:
                        pass
                    return 0
                if servidor is not None and servidor.poll() is not None and not porta_aberta():
                    agora = time.monotonic()
                    quedas_servidor = [t for t in quedas_servidor if agora - t < 60] + [agora]
                    if len(quedas_servidor) > 3:
                        log("servidor caiu demais; encerrando")
                        return 1
                    log(f"servidor caiu (saída {servidor.returncode}); subindo de novo")
                    time.sleep(len(quedas_servidor))
                    servidor = subir_servidor(len(quedas_servidor))
                if vigia.poll() is not None:
                    vigia = iniciar([pythonw(), os.path.join(APP_ROOT, "timer_watchdog.py"),
                                     "--port", str(PORTA)])
                if menu.poll() is not None:
                    break
            codigo = menu.returncode
            vida = time.monotonic() - aberto_em
            remove_process_record(BROWSER_PIDFILE, expected_pid=menu.pid)
            if os.path.exists(EXIT_FLAG):
                log("saída pedida (exit-kids)")
                try:
                    os.unlink(EXIT_FLAG)
                except OSError:
                    pass
                return 0
            if tipo == "nativo":
                if codigo == SEM_GPU or (codigo != 0 and vida < 20):
                    log(f"menu nativo saiu cedo (código {codigo}); usando o menu web")
                    relatar_menu(codigo)
                    usar_web = True
                    continue
                if codigo != 0:
                    quedas_menu += 1
                    log(f"menu nativo caiu (código {codigo}, {quedas_menu}ª vez)")
                    if quedas_menu >= 3:
                        relatar_menu(codigo)
                        usar_web = True
                    continue
            # o menu foi fechado normalmente
            log(f"menu {tipo} fechado (código {codigo})")
            return 0
    finally:
        encerrar_tudo(servidor, vigia, menu)
        log("fim")


if __name__ == "__main__":
    sys.exit(main())
