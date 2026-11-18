#!/usr/bin/env python3
"""Own and supervise the complete process tree launched for one tile."""

import argparse
import ctypes
import os
import signal
import subprocess
import sys
import time

from activity_store import record_activity
from process_state import remove_process_record, write_process_record


PR_SET_CHILD_SUBREAPER = 36
TERMINATION_GRACE_SECONDS = 1.0
POLL_SECONDS = 0.05
_termination_signal = None


def _process_info(pid):
    """Return (state, parent pid, session id) from Linux /proc."""
    try:
        with open(f"/proc/{int(pid)}/stat", "r", encoding="utf-8") as handle:
            stat_line = handle.read()
        closing_parenthesis = stat_line.rfind(")")
        if closing_parenthesis < 0:
            return None
        fields = stat_line[closing_parenthesis + 2:].split()
        return fields[0], int(fields[1]), int(fields[3])
    except (IndexError, OSError, TypeError, ValueError):
        return None


def _process_snapshot():
    snapshot = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return snapshot
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        info = _process_info(pid)
        if info:
            snapshot[pid] = info
    return snapshot


def owned_processes(supervisor_pid=None):
    """Return live descendants, including children that retain our session."""
    supervisor_pid = supervisor_pid or os.getpid()
    snapshot = _process_snapshot()
    owned = {supervisor_pid}
    changed = True
    while changed:
        changed = False
        for pid, (state, parent_pid, session_id) in snapshot.items():
            if pid in owned or state == "Z":
                continue
            if parent_pid in owned or session_id == supervisor_pid:
                owned.add(pid)
                changed = True
    owned.discard(supervisor_pid)
    return sorted(owned)


def _enable_child_subreaper():
    """Adopt double-forked descendants so they remain part of our tree."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
    except (AttributeError, OSError):
        return False


def _handle_termination(signum, _frame):
    global _termination_signal
    _termination_signal = signum


def _signal_owned_processes(signum):
    for pid in reversed(owned_processes()):
        try:
            os.kill(pid, signum)
        except (ProcessLookupError, PermissionError):
            pass


def _reap_children():
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except (ChildProcessError, OSError):
            return
        if pid <= 0:
            return


def terminate_owned_tree(grace_seconds=TERMINATION_GRACE_SECONDS):
    """Stop only descendants of this supervisor, escalating after a grace period."""
    deadline = time.monotonic() + max(0.0, grace_seconds)
    while owned_processes() and time.monotonic() < deadline:
        _signal_owned_processes(signal.SIGTERM)
        _reap_children()
        time.sleep(POLL_SECONDS)
    for _attempt in range(20):
        if not owned_processes():
            break
        _signal_owned_processes(signal.SIGKILL)
        _reap_children()
        time.sleep(POLL_SECONDS)
    _reap_children()


def pasta_do_programa(command):
    """Pasta do .exe, como no "Iniciar em" de um atalho do Windows: muitos jogos
    (Extreme TuxRacer, Pingus...) procuram os próprios dados a partir dela."""
    if not command:
        return None
    programa = str(command[0])
    if not os.path.isabs(programa) or not os.path.isfile(programa):
        return None
    return os.path.dirname(programa)


def _log_windows(texto):
    """Uma linha no beni-windows.log. Só a saída normal: quando o servidor encerra o
    supervisor (TerminateProcess), quem loga é o servidor ("app: encerrado")."""
    try:
        caminho = os.path.join(os.path.expanduser("~"), ".cache", "cozy-kids-launcher", "beni-windows.log")
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")
    except OSError:
        pass


def codigo_legivel(codigo):
    """0xC0000005 em vez de 3221225477 (NTSTATUS de erro); o resto em decimal."""
    if not isinstance(codigo, int):
        return "?"
    codigo &= 0xFFFFFFFF
    return f"0x{codigo:08X}" if codigo >= 0xC0000000 else str(codigo)


def codigo_de_saida(codigo):
    """O código do app como código de saída deste processo. O Windows guarda 32 bits sem
    sinal; o Python precisa do número com sinal para sair com 0xC0000005 de verdade."""
    if not isinstance(codigo, int):
        return 0
    codigo &= 0xFFFFFFFF
    return codigo - 0x100000000 if codigo >= 0x80000000 else codigo


def supervise_windows(
    command,
    record_path,
    marker,
    activity_file="",
    activity_profile="",
    activity_tile="",
):
    """No Windows a árvore do app fica num Job Object. Quando o servidor encerra
    este supervisor (TerminateProcess), o handle do job fecha e o Windows encerra
    todos os processos do app junto (KILL_ON_JOB_CLOSE)."""
    import plataforma_windows as win

    trabalho = win.Trabalho()
    # o próprio supervisor entra no job: os filhos já nascem dentro dele
    trabalho.incluir(os.getpid())
    child = None
    started_at = None
    try:
        child = subprocess.Popen(command, env=dict(os.environ), close_fds=True,
                                 cwd=pasta_do_programa(command))
        started_at = int(time.time())
        write_process_record(record_path, os.getpid(), "tile-process", marker=marker)
        while True:
            # só o supervisor sobrou no job: o app (e o que ele abriu) acabou
            if child.poll() is not None and trabalho.ativos() <= 1:
                _log_windows(f"app: {activity_tile or os.path.basename(str(command[0]))} fechou "
                             f"(código {codigo_legivel(child.returncode)}); o supervisor sai junto")
                # o servidor lê o código do app no do supervisor (roteiro 33: o crash
                # 0xC0000005 do Tux Paint chegou à telemetria sem o código)
                return codigo_de_saida(child.returncode)
            time.sleep(0.2)
    finally:
        remove_process_record(record_path, expected_pid=os.getpid())
        if started_at is not None and activity_file and activity_profile and activity_tile:
            try:
                record_activity(activity_file, activity_profile, activity_tile, started_at)
            except (OSError, ValueError):
                pass


def supervise(
    command,
    record_path,
    marker,
    activity_file="",
    activity_profile="",
    activity_tile="",
):
    global _termination_signal
    _termination_signal = None
    _enable_child_subreaper()
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _handle_termination)

    child = None
    started_at = None
    try:
        child = subprocess.Popen(command, env=dict(os.environ))
        started_at = int(time.time())
        write_process_record(
            record_path,
            os.getpid(),
            "tile-process",
            marker=marker,
        )
        while True:
            child.poll()
            _reap_children()
            if _termination_signal is not None:
                terminate_owned_tree()
                return 0
            if not owned_processes():
                return 0
            time.sleep(POLL_SECONDS)
    finally:
        if owned_processes():
            terminate_owned_tree()
        if child is not None:
            try:
                child.wait(timeout=0.1)
            except (subprocess.TimeoutExpired, ChildProcessError):
                pass
        remove_process_record(record_path, expected_pid=os.getpid())
        if started_at is not None and activity_file and activity_profile and activity_tile:
            try:
                record_activity(
                    activity_file,
                    activity_profile,
                    activity_tile,
                    started_at,
                )
            except (OSError, ValueError):
                pass


def _parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", required=True)
    parser.add_argument("--marker", required=True)
    parser.add_argument("--activity-file", default="")
    parser.add_argument("--activity-profile", default="")
    parser.add_argument("--activity-tile", default="")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        return 2
    try:
        return (supervise_windows if os.name == "nt" else supervise)(
            command,
            args.record,
            args.marker,
            activity_file=args.activity_file,
            activity_profile=args.activity_profile,
            activity_tile=args.activity_tile,
        )
    except (OSError, ValueError):
        remove_process_record(args.record, expected_pid=os.getpid())
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
