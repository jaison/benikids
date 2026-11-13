"""Desktop application and browser discovery for Cozy Kids Launcher."""

import os
import re
import shutil


BROWSER_CANDIDATES = (
    "firefox",
    "firefox-esr",
    "librewolf",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "brave",
    "brave-browser",
    "opera",
    "opera-stable",
    "vivaldi",
    "vivaldi-stable",
    "microsoft-edge",
    "microsoft-edge-stable",
    "edge",
    "cachy-browser",
)

# Windows: os navegadores não ficam no PATH; procura nas pastas de instalação.
WINDOWS_BROWSERS = {
    "msedge": ("Microsoft", "Edge", "Application", "msedge.exe"),
    "chrome": ("Google", "Chrome", "Application", "chrome.exe"),
    "firefox": ("Mozilla Firefox", "firefox.exe"),
    "brave": ("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
}
if os.name == "nt":
    BROWSER_CANDIDATES = tuple(WINDOWS_BROWSERS)


def windows_which(name):
    """Caminho completo de um navegador conhecido (ou de um .exe já com caminho)."""
    if not name:
        return None
    if os.path.isabs(name):
        return name if os.path.isfile(name) else None
    base = os.path.splitext(os.path.basename(name))[0].lower()
    parts = WINDOWS_BROWSERS.get(base)
    if parts:
        for root in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ):
            if root and os.path.isfile(os.path.join(root, *parts)):
                return os.path.join(root, *parts)
    return shutil.which(name)


CHROMIUM_BROWSER_NAMES = {
    "msedge",
    "chrome",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "brave",
    "brave-browser",
    "opera",
    "opera-stable",
    "vivaldi",
    "vivaldi-stable",
    "microsoft-edge",
    "microsoft-edge-stable",
    "edge",
    "cachy-browser",
}


def parse_desktop_file(path, environ=None):
    """Return the display name and launch command from a visible desktop entry."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            contents = handle.read()
    except Exception:
        return None

    if "NoDisplay=true" in contents:
        return None

    environment = os.environ if environ is None else environ
    if "TryExec=" in contents:
        for line in contents.splitlines():
            if line.startswith("TryExec="):
                try_command = line[8:].strip().split()[0]
                search_path = environment.get("PATH", "/usr/bin").split(":")
                if not any(
                    os.path.exists(os.path.join(directory, try_command))
                    for directory in search_path
                ):
                    if not os.path.isabs(try_command) or not os.path.exists(
                        try_command
                    ):
                        return None
                break

    app_name = None
    exec_command = None
    for line in contents.splitlines():
        if line.startswith("Name=") and app_name is None:
            app_name = line[5:].strip()
        elif line.startswith("Exec=") and exec_command is None:
            exec_command = line[5:].strip()
    if not app_name or not exec_command:
        return None

    clean_exec = re.sub(
        r"%[UuFfCcIiMmKkVvDdNnTtRr]",
        "",
        exec_command,
    ).strip()
    if not clean_exec:
        return None
    return {"name": app_name, "exec": clean_exec}


def scan_apps(home, application_dirs=None, limit=300):
    """Discover visible desktop applications in stable directory/name order."""
    directories = application_dirs
    if directories is None:
        directories = (
            os.path.join(home, ".local/share/applications"),
            "/usr/share/applications",
            "/var/lib/snapd/desktop/applications",
        )
    apps = []
    seen = set()
    for directory in directories:
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".desktop"):
                continue
            app = parse_desktop_file(os.path.join(directory, name))
            if not app or app["exec"] in seen:
                continue
            seen.add(app["exec"])
            apps.append(app)
    return apps[:limit]


def browser_family(browser):
    """Return the launch-profile family used by a browser executable."""
    name = os.path.basename(browser)
    if name.lower().endswith(".exe"):
        name = os.path.splitext(name)[0].lower()
    if name in CHROMIUM_BROWSER_NAMES:
        return "chromium"
    return "firefox"


def find_browser(config=None, candidates=BROWSER_CANDIDATES, which=None):
    """Find the configured browser first, then the supported fallbacks."""
    config = config or {}
    preferred = config.get("browser", "")
    ordered_candidates = ([preferred] if preferred else []) + list(candidates)
    if which is None:
        executable = windows_which if os.name == "nt" else shutil.which
    else:
        executable = which
    seen = set()
    for candidate in ordered_candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        found = executable(candidate)
        if found:
            # no Windows o comando precisa do caminho completo
            return found if os.name == "nt" and isinstance(found, str) else candidate
    return None


def browser_statuses(candidates=BROWSER_CANDIDATES, which=None):
    """Return the stable public browser-detection payload."""
    if which is None:
        executable = windows_which if os.name == "nt" else shutil.which
    else:
        executable = which
    return [
        {"name": browser, "installed": bool(executable(browser))}
        for browser in candidates
    ]
