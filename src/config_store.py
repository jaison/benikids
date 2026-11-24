"""Versioned configuration storage for Cozy Kids Launcher."""

import contextlib
import json
import os
import tempfile
import threading

try:
    import fcntl
except ImportError:  # pragma: no cover - no Windows a trava é a da thread (o sync roda no servidor).
    fcntl = None

from profile_config import migrate_legacy_profile


CURRENT_CONFIG_VERSION = 2


def migrate_config(data):
    """Return a current config copy and whether a schema migration was applied."""
    if not isinstance(data, dict):
        raise ValueError("Config must be a JSON object")

    result = dict(data)
    version = result.get("configVersion", 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise ValueError("configVersion must be a non-negative integer")
    if version > CURRENT_CONFIG_VERSION:
        raise ValueError(
            f"Config version {version} is newer than supported version "
            f"{CURRENT_CONFIG_VERSION}"
        )

    migrated = False
    while version < CURRENT_CONFIG_VERSION:
        if version == 0:
            version = 1
            result["configVersion"] = version
            migrated = True
            continue
        if version == 1:
            result = migrate_legacy_profile(result)
            version = 2
            result["configVersion"] = version
            migrated = True
            continue
        raise ValueError(f"No migration path exists from config version {version}")

    return result, migrated


def read_config(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


_locks_guard = threading.Lock()
_thread_locks = {}


def _thread_lock(path):
    key = os.path.abspath(path)
    with _locks_guard:
        lock = _thread_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _thread_locks[key] = lock
        return lock


@contextlib.contextmanager
def config_lock(path):
    """Trava o config.json entre threads e, no Linux, entre processos.

    O servidor (save_stored_cfg) e a sincronização do itch (outro processo no
    Linux, via cozy-itch-sync) gravam o mesmo arquivo. Sem esta trava, quem
    termina por último cobre o que o outro acabou de salvar.
    """
    lock = _thread_lock(path)
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    lock_path = os.path.join(directory, os.path.basename(os.path.abspath(path)) + ".lock")
    with lock:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, "a+b") as handle:
            try:
                os.chmod(lock_path, 0o600)
            except OSError:
                pass
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write_config(path, data):
    """Write JSON beside its target and atomically replace the old file."""
    config_dir = os.path.dirname(path)
    os.makedirs(config_dir, exist_ok=True)
    descriptor, temp_path = tempfile.mkstemp(
        prefix="config-",
        suffix=".json",
        dir=config_dir,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
