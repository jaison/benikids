"""Catálogo de apps do Windows (src/catalogo/windows.json).

Cada item é um app livre curado para crianças, instalado pelo winget e ligado por
padrão (os pais desligam na área dos pais). O tile guarda só "catalogo:<id>"; o
caminho do .exe é procurado na hora de abrir, porque muda com a versão e com o
tipo de instalação (por usuário ou para todos).
"""

import glob
import json
import os

ARQUIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalogo", "windows.json")
PREFIXO = "catalogo:"


def carregar(arquivo=ARQUIVO):
    try:
        with open(arquivo, encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        return []
    return [item for item in dados.get("apps", []) if isinstance(item, dict) and item.get("id")]


def raizes():
    vistas = []
    for nome, padrao in (
        ("ProgramFiles", r"C:\Program Files"),
        ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ("LOCALAPPDATA", ""),
    ):
        raiz = os.environ.get(nome, padrao)
        if raiz and raiz not in vistas:
            vistas.append(raiz)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        vistas.append(os.path.join(local, "Programs"))
    return vistas


def localizar(item, bases=None, registro=None):
    """Caminho do .exe do app, ou None.

    Primeiro pelos padrões glob do catálogo (relativos às pastas de programas); se
    nenhum casar, pelo "Programas instalados" do Windows (chaves Uninstall), que
    sabe a pasta mesmo quando o instalador muda o nome dela entre versões.
    """
    for padrao in item.get("exe", []):
        for base in bases if bases is not None else raizes():
            achados = sorted(glob.glob(os.path.join(base, padrao), recursive=True), reverse=True)
            for caminho in achados:
                if os.path.isfile(caminho):
                    return caminho
    if item.get("registro"):
        entradas = registro if registro is not None else programas_instalados()
        return pelo_registro(item, entradas)
    return None


def nomes_do_exe(item):
    return {os.path.basename(p).lower() for p in item.get("exe", []) if "*" not in os.path.basename(p)}


def pelo_registro(item, entradas):
    """entradas: [(DisplayName, InstallLocation, DisplayIcon)]. Acha o exe do app nelas."""
    nome = item["registro"].lower()
    exes = nomes_do_exe(item)
    for exibido, pasta, icone in entradas:
        if nome not in (exibido or "").lower():
            continue
        icone = (icone or "").split(",")[0].strip().strip('"')
        if icone.lower().endswith(".exe") and os.path.basename(icone).lower() in exes and os.path.isfile(icone):
            return icone
        if pasta and os.path.isdir(pasta):
            for raiz, _pastas, arquivos in os.walk(pasta):
                if raiz[len(pasta):].count(os.sep) > 3:
                    continue
                for arquivo in arquivos:
                    if arquivo.lower() in exes:
                        return os.path.join(raiz, arquivo)
    return None


def programas_instalados():
    """[(DisplayName, InstallLocation, DisplayIcon)] de HKLM/HKCU ...\\Uninstall (só Windows)."""
    try:
        import winreg
    except ImportError:
        return []
    caminhos = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    entradas = []
    for raiz, caminho in caminhos:
        try:
            chave = winreg.OpenKey(raiz, caminho)
        except OSError:
            continue
        with chave:
            i = 0
            while True:
                try:
                    nome = winreg.EnumKey(chave, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(chave, nome) as sub:
                        def valor(campo):
                            try:
                                return str(winreg.QueryValueEx(sub, campo)[0])
                            except OSError:
                                return ""
                        entradas.append((valor("DisplayName"), valor("InstallLocation"), valor("DisplayIcon")))
                except OSError:
                    continue
    return entradas


def por_id(item_id, catalogo=None):
    for item in catalogo if catalogo is not None else carregar():
        if item["id"] == item_id:
            return item
    return None


def comando(cmd, catalogo=None, bases=None):
    """["catalogo:gcompris"] → [caminho do exe, *args]; None se não está instalado."""
    if not cmd or not isinstance(cmd[0], str) or not cmd[0].startswith(PREFIXO):
        return cmd
    item = por_id(cmd[0][len(PREFIXO):], catalogo)
    if not item:
        return None
    exe = localizar(item, bases)
    if not exe:
        return None
    argv = [exe, *(preencher(arg, item) for arg in item.get("args", []))]
    gravar_config_inicial(item)
    if item.get("preparar") == "xmoto":
        preparar_xmoto()
    return argv


# Mesmo ajuste do beni/bin/xmoto no Linux: português, sem o aviso de "versão em
# desenvolvimento", sem internet e sem o contador de quadros (F7 → F13).
XMOTO_CONFIG = (
    ("NotifyAtInit", "false"), ("Language", "pt_BR"), ("WebConfAtInit", "false"),
    ("WebHighscores", "false"), ("CheckHighscoresAtStartup", "false"),
    ("CheckNewLevelsAtStartup", "false"), ("ShowInGameWorldRecord", "false"),
    ("EnableJoysticks", "true"), ("KeySwitchFPS", "K:1073741928:0"),
)


def bancos_xmoto():
    """Onde o X-Moto guarda o xm.db no Windows (varia com a versão do jogo)."""
    candidatos = []
    for variavel, sub in (("APPDATA", "xmoto"), ("LOCALAPPDATA", "xmoto"),
                          ("USERPROFILE", os.path.join(".local", "share", "xmoto")),
                          ("USERPROFILE", ".xmoto")):
        raiz = os.environ.get(variavel)
        if raiz:
            candidatos.append(os.path.join(raiz, sub, "xm.db"))
    return candidatos


def preparar_xmoto(bancos=None, perfil="Benikids"):
    """Deixa o perfil "Benikids" pronto no xm.db que já existe. O banco só nasce na
    primeira vez que o jogo abre; daí em diante a criança cai direto no menu."""
    import sqlite3
    import time

    preparados = []
    for caminho in bancos if bancos is not None else bancos_xmoto():
        if not os.path.isfile(caminho):
            continue
        try:
            db = sqlite3.connect(caminho, timeout=2)
            try:
                site = db.execute("SELECT value FROM xm_parameters WHERE param='siteKey'").fetchone()
                if site and not db.execute("SELECT 1 FROM stats_profiles WHERE id_profile=?", (perfil,)).fetchone():
                    db.execute("INSERT INTO stats_profiles VALUES (?, ?, 0, ?)",
                               (site[0], perfil, time.strftime("%Y-%m-%d %H:%M:%S")))
                for nome in ("", perfil):
                    for chave, valor in XMOTO_CONFIG:
                        db.execute("INSERT OR REPLACE INTO profiles_configs VALUES (?, ?, ?)", (nome, chave, valor))
                db.commit()
                preparados.append(caminho)
            finally:
                db.close()
        except sqlite3.Error:
            continue
    return preparados


def gravar_config_inicial(item):
    """Config pronta na pasta de dados do app, se ainda não existe (ex.: SuperTux sem a
    pergunta "conectar à Internet?": o ✕ fecha o jogo à força e ele nunca grava a resposta)."""
    inicial = item.get("config_inicial")
    if not isinstance(inicial, dict) or not inicial.get("arquivo"):
        return
    caminho = os.path.join(pasta_de_dados_ascii(item), inicial["arquivo"])
    if os.path.exists(caminho):
        return
    try:
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(inicial.get("texto", ""))
    except OSError:
        pass


def pasta_de_dados_ascii(item, usuario=None, raiz=None):
    """Pasta de dados do app num caminho só com letras ASCII.

    O SuperTux 0.7 não abre quando o caminho do usuário tem acento (ex.:
    C:\\Users\\Lívia): ele não consegue criar a pasta em %APPDATA%. Aqui fica em
    %ProgramData%\\Benikids\\dados\\<usuário sem acento>\\<app>, que qualquer usuário cria.
    """
    import unicodedata

    usuario = usuario or os.environ.get("USERNAME") or "crianca"
    limpo = unicodedata.normalize("NFKD", usuario).encode("ascii", "ignore").decode()
    limpo = "".join(c if c.isalnum() or c in "-_." else "_" for c in limpo).strip("._") or "crianca"
    raiz = raiz or os.environ.get("ProgramData", r"C:\ProgramData")
    pasta = os.path.join(raiz, "Benikids", "dados", limpo, item["id"])
    try:
        os.makedirs(pasta, exist_ok=True)
    except OSError:
        pass
    return pasta


def tamanho_da_tela():
    """"LARGURAxALTURA" da tela principal (em pixels reais), ou None fora do Windows."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
        largura, altura = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except (AttributeError, OSError, ImportError):
        return None
    return f"{largura}x{altura}" if largura > 0 and altura > 0 else None


def preencher(arg, item):
    if "{dados_ascii}" in arg:
        arg = arg.replace("{dados_ascii}", pasta_de_dados_ascii(item))
    if "{tela}" in arg:
        arg = arg.replace("{tela}", tamanho_da_tela() or "1280x720")
    return arg


def tiles(catalogo=None):
    """Tiles do catálogo para a configuração inicial (todos visíveis)."""
    resultado = []
    for item in catalogo if catalogo is not None else carregar():
        if item.get("tile") is False:  # ex.: VLC, usado pelo "Filmes e música"
            continue
        tile = {
            "id": item["id"],
            "label": item["label"],
            "emoji": item.get("emoji", "🎮"),
            "cmd": [PREFIXO + item["id"]],
            "visible": True,
            "category": item.get("category", "jogos"),
        }
        if item.get("gamepad"):
            tile["gamepad"] = True
        resultado.append(tile)
    return resultado


def sincronizar_tiles(stored, catalogo=None):
    """Põe nos perfis os apps do catálogo que este computador ainda não viu.

    "catalogSeen" guarda os ids já oferecidos: um app novo no catálogo entra uma vez em
    cada perfil (ligado, como todo o catálogo); um app que os pais removeram não volta.
    Devolve (config, mudou).
    """
    import copy

    catalogo = catalogo if catalogo is not None else carregar()
    novos = tiles(catalogo)
    vistos = set(stored.get("catalogSeen") or [])
    ids_catalogo = [t["id"] for t in novos]
    if vistos >= set(ids_catalogo):
        return stored, False
    resultado = copy.deepcopy(stored)
    for perfil in resultado.get("profiles", []):
        existentes = {t.get("id") for t in perfil.get("tiles", []) if isinstance(t, dict)}
        for tile in novos:
            if tile["id"] not in vistos and tile["id"] not in existentes:
                perfil.setdefault("tiles", []).append(copy.deepcopy(tile))
    resultado["catalogSeen"] = sorted(vistos | set(ids_catalogo))
    return resultado, True
