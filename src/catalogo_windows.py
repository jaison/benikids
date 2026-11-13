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


def localizar(item, bases=None):
    """Caminho do .exe do app (padrões glob relativos às pastas de programas), ou None."""
    for padrao in item.get("exe", []):
        for base in bases if bases is not None else raizes():
            achados = sorted(glob.glob(os.path.join(base, padrao), recursive=True), reverse=True)
            for caminho in achados:
                if os.path.isfile(caminho):
                    return caminho
    return None


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
    return [exe, *(preencher(arg, item) for arg in item.get("args", []))]


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
