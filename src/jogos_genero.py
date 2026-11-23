"""Jogos que entram no perfil conforme o gênero.

A lista fica em jogos_por_genero.json (um lugar só, Windows e Linux).
Perfil sem gender não ganha nada: não adivinhamos. Tile que já existe
não é reescrito — se os pais ocultaram, continua oculto.

No Linux o comando é o mesmo dos jogos da coleção do itch.io
(navegador-jogos + cozy-jogo.html). No Windows, special:external-browser
+ /jogo.html, também igual à coleção.
"""

import json
import os

PORTA = 38431
ARQUIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jogos_por_genero.json")
MOLDURA_LINUX = os.path.join(
    os.path.expanduser("~"), ".var", "app", "org.chromium.Chromium", "cozy-jogo.html",
)


def carregar(arquivo=ARQUIVO):
    try:
        with open(arquivo, encoding="utf-8") as handle:
            dados = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(dados, dict):
        return {}
    return {
        gender: [jogo for jogo in lista if isinstance(jogo, dict) and jogo.get("id")]
        for gender, lista in dados.items()
        if isinstance(gender, str) and isinstance(lista, list)
    }


def ids(gender, arquivo=ARQUIVO):
    return [jogo["id"] for jogo in carregar(arquivo).get(gender, [])]


def traduzir_navegador_jogos(cmd, porta=PORTA):
    """Comando do Linux (navegador-jogos + url) no formato do Windows.

    Moldura de tamanho fixo (cozy-jogo.html#w=&h=) vira /jogo.html.
    Um site http(s) abre direto, no mesmo quiosque dos outros sites.
    Devolve None quando o comando não é um jogo de navegador.
    """
    if (
        not isinstance(cmd, list)
        or len(cmd) != 2
        or cmd[0] != "navegador-jogos"
        or not isinstance(cmd[1], str)
    ):
        return None
    url = cmd[1]
    marca = "cozy-jogo.html#"
    if marca in url:
        frag = url.split("#", 1)[1]
        if "w=" not in frag or "h=" not in frag:
            return None
        return ["special:external-browser:http://127.0.0.1:%d/jogo.html#%s" % (int(porta), frag)]
    if url.startswith("https://") or url.startswith("http://"):
        return ["special:external-browser:" + url]
    return None


def tile_de(jogo, plataforma, moldura=None, porta=PORTA):
    import itch_sync

    info = {
        "embed": jogo["url"],
        "w": int(jogo.get("w") or 0),
        "h": int(jogo.get("h") or 0),
    }
    caminhos = itch_sync.Caminhos(
        config="", colecoes="", cache="", capas="", log="", trava="",
        moldura=moldura or MOLDURA_LINUX,
        porta=int(porta),
    )
    return {
        "id": jogo["id"],
        "label": jogo.get("label") or jogo["id"],
        "emoji": jogo.get("emoji") or "🎮",
        "cmd": itch_sync.comando_do_jogo(info, plataforma, caminhos),
        "visible": True,
        "category": jogo.get("category") or "jogos",
    }


def retirar_de_outros_generos(perfil, arquivo=ARQUIVO):
    """Tira do perfil os jogos que são de outro gênero. Usado só na configuração inicial,
    em que o perfil foi copiado do modelo e ainda não é uma escolha dos pais."""
    if not isinstance(perfil, dict) or not isinstance(perfil.get("tiles"), list):
        return 0
    dados = carregar(arquivo)
    gender = perfil.get("gender")
    banidos = {
        jogo["id"]
        for outro, lista in dados.items()
        if outro != gender
        for jogo in lista
    }
    if not banidos:
        return 0
    antes = len(perfil["tiles"])
    perfil["tiles"] = [
        t for t in perfil["tiles"]
        if not (isinstance(t, dict) and t.get("id") in banidos)
    ]
    return antes - len(perfil["tiles"])


def aplicar_perfil(perfil, plataforma="linux", moldura=None, porta=PORTA, arquivo=ARQUIVO):
    """Acrescenta os jogos do gênero que o perfil ainda não tem. Devolve quantos."""
    if not isinstance(perfil, dict):
        return 0
    lista = carregar(arquivo).get(perfil.get("gender"), [])
    if not lista:
        return 0
    tiles = perfil.setdefault("tiles", [])
    if not isinstance(tiles, list):
        return 0
    presentes = {t.get("id") for t in tiles if isinstance(t, dict)}
    acrescentados = 0
    for jogo in lista:
        if jogo["id"] in presentes:
            continue
        tiles.append(tile_de(jogo, plataforma, moldura=moldura, porta=porta))
        presentes.add(jogo["id"])
        acrescentados += 1
    return acrescentados


def aplicar(cfg, plataforma="linux", moldura=None, porta=PORTA, arquivo=ARQUIVO):
    if not isinstance(cfg, dict):
        return 0
    return sum(
        aplicar_perfil(perfil, plataforma, moldura=moldura, porta=porta, arquivo=arquivo)
        for perfil in cfg.get("profiles", [])
        if isinstance(perfil, dict)
    )
