"""Jogos de navegador do Linux (Rabisco e moldura do itch.io) no Windows já instalado.

Um computador novo recebe estes tiles pelo config-padrao.py, que converte
navegador-jogos. Um que já estava configurado não relê o config do Linux: a
atualização troca o src/, e este módulo acrescenta o jogo que ainda não foi
oferecido.

"rabiscoSeen" guarda os ids já oferecidos. Se os pais apagarem o tile, ele não
volta. Se ocultaram ou renomearam, o tile que já existe não é reescrito.
RABISCO_JA_ENTREGUES é a foto dos jogos que já vinham no pacote quando este
registro nasceu: na primeira abertura eles contam como oferecidos, para um
jogo apagado antes desta função não reaparecer. Jogo novo entra em
src/rabisco/tiles.json (e no config do Linux) e NÃO nesta tupla.

No Linux o comando continua navegador-jogos. Aqui vira o quiosque do Edge
(special:external-browser). Jogo do itch.io (html-classic.itch.zone) usa a
moldura local benikids-jogo:; aberto direto, o itch.io bloqueia por
anti-hotlink. Jogo que no Linux só está no perfil de um gênero só entra nesse
gênero. Perfil sem gênero não ganha jogo de gênero: não adivinhamos.
"""

import copy
import json
import os
import re

AQUI = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.path.join(AQUI, "rabisco", "tiles.json")
CONFIG_LINUX = os.path.join(AQUI, "..", "beni", "config", "config.json")
MIGRACOES = os.path.join(AQUI, "..", "beni", "config", "migracoes.json")

# Não acrescente um jogo novo aqui. Senão o Windows já instalado não o recebe.
# Vazio de propósito: estes jogos nunca tinham chegado a um PC já configurado.
RABISCO_JA_ENTREGUES = ()

_CAMPOS = ("id", "label", "emoji", "cmd", "visible", "category")
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_GENEROS = ("menino", "menina")


def _e_navegador(tile):
    cmd = tile.get("cmd") if isinstance(tile, dict) else None
    return (
        isinstance(cmd, list)
        and len(cmd) == 2
        and cmd[0] == "navegador-jogos"
        and isinstance(cmd[1], str)
    )


def _comando_windows(cmd):
    """navegador-jogos no formato do Windows, ou None.

    URL pelada do itch.io não serve: sem a moldura o jogo não abre, e sem
    w/h não dá para montar o token benikids-jogo:.
    """
    import jogos_genero

    novo = jogos_genero.traduzir_navegador_jogos(cmd)
    if not novo:
        return None
    texto = novo[0] if novo else ""
    if "itch.zone" in texto and "benikids-jogo:#" not in texto:
        return None
    return novo


def _item(tile, cmd):
    item = {}
    for campo in _CAMPOS:
        if campo == "cmd":
            item["cmd"] = cmd
        elif campo in tile:
            item[campo] = tile[campo]
    return item


def _generos_de(perfil):
    """None = vale para todo perfil. Conjunto = só esses gêneros."""
    if not isinstance(perfil, dict):
        return None
    genero = perfil.get("gender")
    if genero not in _GENEROS:
        return None
    return {genero}


def _acumular(info, ordem, tile, generos):
    if not _e_navegador(tile):
        return
    ident = tile.get("id")
    if not isinstance(ident, str) or not _ID.fullmatch(ident):
        return
    if ident not in info:
        cmd = _comando_windows(tile.get("cmd"))
        if not cmd:
            return
        info[ident] = {"tile": _item(tile, cmd), "generos": set(), "livre": False}
        ordem.append(ident)
    alvo = info[ident]
    if generos is None:
        alvo["livre"] = True
    else:
        alvo["generos"].update(generos)


def _generos_da_operacao(config, quais):
    if quais in (None, "todos"):
        return None
    if not isinstance(quais, list):
        return None
    mapa = {}
    for perfil in (config or {}).get("profiles") or []:
        if isinstance(perfil, dict):
            mapa[perfil.get("id")] = perfil.get("gender")
    generos = set()
    for ident in quais:
        genero = mapa.get(ident)
        if genero not in _GENEROS:
            return None
        generos.add(genero)
    return generos or None


def extrair(config, migracoes):
    """Tiles navegador-jogos do config do Linux e das migrações, sem repetir o id.

    O comando já sai no formato do Windows. "gender" só aparece quando o jogo
    está num único gênero; nos dois (ou num perfil sem gênero) vale para todos.
    """
    info = {}
    ordem = []
    for perfil in (config or {}).get("profiles") or []:
        if not isinstance(perfil, dict):
            continue
        generos = _generos_de(perfil)
        for tile in perfil.get("tiles") or []:
            _acumular(info, ordem, tile, generos)
    for migracao in (migracoes or {}).get("migracoes") or []:
        if not isinstance(migracao, dict):
            continue
        for op in migracao.get("operacoes") or []:
            if not isinstance(op, dict) or op.get("op") != "adicionar_tile":
                continue
            _acumular(
                info, ordem, op.get("tile") or {},
                _generos_da_operacao(config, op.get("perfis", "todos")),
            )
    saida = []
    for ident in ordem:
        alvo = info[ident]
        item = dict(alvo["tile"])
        if not alvo["livre"] and len(alvo["generos"]) == 1:
            item["gender"] = next(iter(alvo["generos"]))
        saida.append(item)
    return saida


def extrair_dos_arquivos(config=CONFIG_LINUX, migracoes=MIGRACOES):
    with open(config, encoding="utf-8") as arquivo:
        cfg = json.load(arquivo)
    with open(migracoes, encoding="utf-8") as arquivo:
        mig = json.load(arquivo)
    return extrair(cfg, mig)


def _normalizar(tile):
    if not isinstance(tile, dict):
        return None
    ident = tile.get("id")
    cmd = tile.get("cmd")
    if not isinstance(ident, str) or not _ID.fullmatch(ident):
        return None
    if not (
        isinstance(cmd, list) and len(cmd) == 1 and isinstance(cmd[0], str)
        and cmd[0].startswith("special:")
    ):
        return None
    if "itch.zone" in cmd[0] and "benikids-jogo:#" not in cmd[0]:
        return None
    item = _item(tile, cmd)
    if tile.get("gender") in _GENEROS:
        item["gender"] = tile["gender"]
    return item


def carregar(arquivo=ARQUIVO):
    try:
        with open(arquivo, encoding="utf-8") as arquivo_json:
            dados = json.load(arquivo_json)
    except (OSError, ValueError):
        return []
    saida = []
    for tile in dados.get("tiles", []) if isinstance(dados, dict) else []:
        item = _normalizar(tile)
        if item:
            saida.append(item)
    return saida


def _serve(jogo, perfil):
    genero = jogo.get("gender")
    if genero and perfil.get("gender") != genero:
        return False
    return True


def sincronizar(stored, jogos=None, ja_entregues=RABISCO_JA_ENTREGUES):
    """Acrescenta jogos ainda não oferecidos. Devolve (config, mudou).

    Sem "rabiscoSeen" (instalação de antes): o que já está no menu e os ids de
    ja_entregues contam como oferecidos. Tile existente não muda: oculto
    continua oculto, nome escolhido pelos pais fica.
    """
    if not isinstance(stored, dict):
        return stored, False
    brutos = carregar() if jogos is None else jogos
    por_id = {}
    ids = []
    for tile in brutos:
        item = _normalizar(tile)
        if item and item["id"] not in por_id:
            por_id[item["id"]] = item
            ids.append(item["id"])
    presentes = set()
    for perfil in stored.get("profiles") or []:
        if not isinstance(perfil, dict):
            continue
        for tile in perfil.get("tiles") or []:
            if isinstance(tile, dict) and isinstance(tile.get("id"), str):
                presentes.add(tile["id"])
    if isinstance(stored.get("rabiscoSeen"), list):
        vistos = set(stored["rabiscoSeen"])
        primeira = False
    else:
        vistos = set(ja_entregues) | (presentes & set(ids))
        primeira = True
    novo = sorted(vistos | set(ids))
    acrescentou = False
    resultado = copy.deepcopy(stored)
    for perfil in resultado.get("profiles") or []:
        if not isinstance(perfil, dict):
            continue
        existentes = {
            t.get("id") for t in perfil.get("tiles") or [] if isinstance(t, dict)
        }
        for ident in ids:
            jogo = por_id[ident]
            if ident in vistos or ident in existentes or not _serve(jogo, perfil):
                continue
            tile = copy.deepcopy(jogo)
            tile.pop("gender", None)
            perfil.setdefault("tiles", []).append(tile)
            acrescentou = True
    if not primeira and not acrescentou and list(stored.get("rabiscoSeen") or []) == novo:
        return stored, False
    resultado["rabiscoSeen"] = novo
    return resultado, True
