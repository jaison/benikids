"""Sites (tiles special:) do Linux que chegam ao Windows já instalado, uma vez.

Um computador novo recebe estes tiles pelo config-padrao.py. Um que já estava
instalado não relê o config do Linux: a atualização troca o src/, e este módulo
acrescenta o site que ainda não foi oferecido.

"sitesSeen" guarda os ids já oferecidos. Se os pais apagarem o tile, ele não
volta. SITES_JA_ENTREGUES é a foto dos sites que já vinham no pacote quando
este registro nasceu: na primeira abertura eles contam como oferecidos, para
um site apagado antes desta função não reaparecer. Site novo entra em
src/sites/tiles.json (e no config do Linux) e NÃO nesta tupla.
"""

import copy
import json
import os

AQUI = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.path.join(AQUI, "sites", "tiles.json")
CONFIG_LINUX = os.path.join(AQUI, "..", "beni", "config", "config.json")
MIGRACOES = os.path.join(AQUI, "..", "beni", "config", "migracoes.json")

# Não acrescente um site novo aqui. Senão o Windows já instalado não o recebe.
SITES_JA_ENTREGUES = (
    "paint",
    "autodraw",
    "colorir",
    "teachyourmonster",
    "kiddogames",
    "blockly",
    "musiclab",
    "browser",
    "codeorg",
    "khan",
    "phet",
    "music",
    "youtube-kids",
    "netflix-kids",
    "disney-plus",
    "prime-kids",
    "pbs-kids",
    "zdf-tivi",
    "kika",
)

_CAMPOS = ("id", "label", "emoji", "cmd", "visible", "category")


def e_site(tile):
    cmd = tile.get("cmd") if isinstance(tile, dict) else None
    return (isinstance(cmd, list) and len(cmd) == 1 and isinstance(cmd[0], str)
            and cmd[0].startswith("special:"))


def normalizar(tile):
    """Só os campos do tile, numa ordem estável (o teste compara com o arquivo)."""
    item = {}
    for campo in _CAMPOS:
        if campo in tile:
            item[campo] = tile[campo]
    if tile.get("gamepad") is True:
        item["gamepad"] = True
    return item


def extrair(config, migracoes):
    """Tiles special: do config do Linux e das migrações, sem repetir o id."""
    saida = []
    vistos = set()

    def por(tile):
        if not e_site(tile) or tile.get("id") in vistos:
            return
        vistos.add(tile["id"])
        saida.append(normalizar(tile))

    for perfil in (config or {}).get("profiles") or []:
        for tile in perfil.get("tiles") or []:
            por(tile)
    for migracao in (migracoes or {}).get("migracoes") or []:
        for op in migracao.get("operacoes") or []:
            if op.get("op") == "adicionar_tile":
                por(op.get("tile") or {})
    return saida


def extrair_dos_arquivos(config=CONFIG_LINUX, migracoes=MIGRACOES):
    with open(config, encoding="utf-8") as f:
        cfg = json.load(f)
    with open(migracoes, encoding="utf-8") as f:
        mig = json.load(f)
    return extrair(cfg, mig)


def carregar(arquivo=ARQUIVO):
    try:
        with open(arquivo, encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        return []
    return [normalizar(t) for t in dados.get("tiles", []) if e_site(t)]


def sincronizar(stored, sites=None, ja_entregues=SITES_JA_ENTREGUES):
    """Acrescenta sites ainda não oferecidos. Devolve (config, mudou).

    Sem "sitesSeen" (instalação de antes): o que já está no menu e os ids de
    ja_entregues contam como oferecidos.
    """
    sites = carregar() if sites is None else [normalizar(t) for t in sites if e_site(t)]
    por_id = {}
    ids = []
    for tile in sites:
        if tile["id"] not in por_id:
            por_id[tile["id"]] = tile
            ids.append(tile["id"])
    presentes = set()
    for perfil in stored.get("profiles") or []:
        for tile in perfil.get("tiles") or []:
            if isinstance(tile, dict) and isinstance(tile.get("id"), str):
                presentes.add(tile["id"])
    if isinstance(stored.get("sitesSeen"), list):
        vistos = set(stored["sitesSeen"])
        primeira = False
    else:
        vistos = set(ja_entregues) | (presentes & set(ids))
        primeira = True
    novo = sorted(vistos | set(ids))
    acrescentou = False
    resultado = copy.deepcopy(stored)
    for perfil in resultado.get("profiles") or []:
        existentes = {t.get("id") for t in perfil.get("tiles") or [] if isinstance(t, dict)}
        for sid in ids:
            if sid not in vistos and sid not in existentes:
                perfil.setdefault("tiles", []).append(copy.deepcopy(por_id[sid]))
                acrescentou = True
    if not primeira and not acrescentou and list(stored.get("sitesSeen") or []) == novo:
        return stored, False
    resultado["sitesSeen"] = novo
    return resultado, True
