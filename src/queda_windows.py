"""O que sobra de um Benikids que caiu no Windows, e como reconhecer.

Desde o roteiro 24 o iniciador põe a si mesmo (e, por herança, todos os filhos) num
Job Object que encerra tudo quando ele morre. Antes disso, matar o iniciador deixava
o beni-menu em tela cheia por cima de tudo, sem servidor, e cada reabertura criava
mais um menu e mais um vigia. Esta parte é a segunda ponta: na abertura, se a
sessão anterior não terminou direito (sessao.json ainda existe), encerra os
processos que sobraram dela.

Reconhece pelo caminho, não pelo nome:
- o exe é <instalação>\\beni-menu.exe;
- um argumento é <instalação>\\server.py, timer_watchdog.py, overlay.py ou
  process_supervisor.py (os scripts Python do Benikids);
- o perfil do navegador (--user-data-dir=, --profile) está em
  <cache>\\menu-...: o Edge da área dos pais e o menu web de reserva.
E só os da mesma sessão do Windows (o mesmo usuário logado), nunca este processo.
"""

import json
import os
import subprocess

SCRIPTS = ("server.py", "timer_watchdog.py", "overlay.py", "process_supervisor.py")


def _norm(caminho):
    return os.path.normcase(os.path.normpath(caminho)) if caminho else ""


def e_resto(exe, argv, app_root, cache):
    """True se o processo (exe + argumentos) é do Benikids instalado em app_root."""
    if _norm(exe) == _norm(os.path.join(app_root, "beni-menu.exe")):
        return True
    scripts = {_norm(os.path.join(app_root, s)) for s in SCRIPTS}
    perfis = _norm(os.path.join(cache, "menu-"))
    for arg in argv or []:
        if not isinstance(arg, str):
            continue
        if _norm(arg) in scripts:
            return True
        valor = arg.split("=", 1)[1] if arg.startswith("--user-data-dir=") else arg
        if valor and _norm(valor).startswith(perfis):
            return True
    return False


def restos(processos, app_root, cache, meu_pid, minha_sessao):
    """PIDs a encerrar. processos: [{"pid", "exe", "argv", "sessao"}]. O menu vem
    primeiro (fechá-lo fecha o Edge dele junto, pelo job do próprio menu)."""
    achados = [p for p in processos
               if p.get("pid") != meu_pid and p.get("sessao") == minha_sessao
               and e_resto(p.get("exe"), p.get("argv"), app_root, cache)]
    menu = _norm(os.path.join(app_root, "beni-menu.exe"))
    achados.sort(key=lambda p: _norm(p.get("exe")) != menu)
    return [p["pid"] for p in achados]


def encerrar_restos(win, app_root, cache, meu_pid):
    """Lista os processos da mesma sessão do Windows e encerra os que são restos de um
    Benikids (e_resto). win: plataforma_windows (nos testes, um falso). Devolve os PIDs."""
    minha = win.sessao_do_processo(meu_pid)
    lista = []
    for pid in win.processos():
        if pid in (0, 4, meu_pid) or win.sessao_do_processo(pid) != minha:
            continue
        exe = win.caminho_do_exe(pid)
        if not exe:
            continue
        lista.append({"pid": pid, "exe": exe, "argv": win.process_command(pid), "sessao": minha})
    pids = restos(lista, app_root, cache, meu_pid, minha)
    for pid in pids:
        win.terminar(pid)
    return pids


MUTEX = "Local\\BeniLauncher"


def iniciador_vivo(nome=MUTEX):
    """True se um iniciador (beni_windows.py) está rodando nesta sessão: é ele que segura o
    mutex. Sem ele, um beni-menu aberto é resto de uma queda (versões antes do job)."""
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenMutexW.restype = ctypes.c_void_p
        h = kernel32.OpenMutexW(0x00100000, False, nome)  # SYNCHRONIZE
    except (AttributeError, OSError):
        return False
    if not h:
        return False
    kernel32.CloseHandle(ctypes.c_void_p(h))
    return True


def o_que_fazer_com_menu_aberto(menu_rodando, iniciador):
    """Instalador/atualização encontrou o Benikids: "seguir" (nada aberto), "esperar" (o
    iniciador está vivo: a pessoa fecha pelo Sair) ou "limpar" (só restos, sem iniciador:
    ninguém consegue fechar pelo Sair, então o instalador encerra)."""
    if not menu_rodando:
        return "seguir"
    return "esperar" if iniciador else "limpar"


def caiu_antes(marcador, outros=()):
    """A sessão anterior não terminou direito? (o marcador da sessão, ou a barra que
    ela escondeu, ficaram para trás)."""
    return any(os.path.exists(c) for c in (marcador, *outros))


def marcar_sessao(marcador, pid):
    try:
        os.makedirs(os.path.dirname(marcador), exist_ok=True)
        with open(marcador, "w", encoding="utf-8") as f:
            json.dump({"pid": pid}, f)
    except OSError:
        pass


def fim_da_sessao(marcador):
    try:
        os.unlink(marcador)
    except OSError:
        pass


CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def popen_fora_do_job(argv, **kw):
    """subprocess.Popen (só no Windows) que sobrevive ao fim do Benikids: o instalador
    da atualização e a instalação de apps pedida pelos pais. Sem permissão para sair do
    job (um job de fora, sem BREAKAWAY_OK), abre do jeito de sempre."""
    base = kw.pop("creationflags", 0)
    try:
        return subprocess.Popen(argv, creationflags=base | CREATE_BREAKAWAY_FROM_JOB, **kw)
    except OSError:
        return subprocess.Popen(argv, creationflags=base, **kw)
