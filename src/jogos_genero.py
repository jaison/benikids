"""Jogos que entram no perfil conforme o gênero.

A lista fica em jogos_por_genero.json (um lugar só, Windows e Linux).
Perfil sem gender não ganha nada: não adivinhamos. Tile que já existe
não é reescrito — se os pais ocultaram, continua oculto. Tile que os pais
apagaram também não volta: o id fica em tilesSeen, no mesmo espírito do
catalogSeen dos apps do Windows.

No Linux o comando é o mesmo dos jogos da coleção do itch.io
(navegador-jogos + cozy-jogo.html). No Windows, o token benikids-jogo:,
resolvido na abertura para a moldura local em file://.
"""

import json
import os
import re

_ID_VISTO = re.compile(r"[A-Za-z0-9_-]{1,80}")

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

    Moldura de tamanho fixo (cozy-jogo.html#w=&h=) vira o token benikids-jogo:,
    resolvido na abertura para file://. Um site http(s) abre direto, no mesmo
    quiosque dos outros sites. Devolve None quando o comando não é um jogo
    de navegador. `porta` fica na assinatura por quem já chamava assim; a
    moldura não usa mais o servidor em 127.0.0.1.
    """
    int(porta)  # quem passava a porta do servidor continua recebendo erro se ela for inválida
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
        import itch_sync

        if not itch_sync._fragmento_valido(frag):
            return None
        return itch_sync.comando_da_moldura(frag)
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
    if jogo.get("pad"):
        info["pad"] = int(jogo["pad"])
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


def _comando_de_moldura(cmd):
    if not isinstance(cmd, list):
        return False
    texto = " ".join(parte for parte in cmd if isinstance(parte, str))
    return (
        "benikids-jogo:#" in texto
        or "jogo.html#" in texto
        or "cozy-jogo.html#" in texto
    )


def ids_vistos(perfil):
    """Ids que este perfil já recebeu da sincronização (coleção ou gênero)."""
    if not isinstance(perfil, dict):
        return set()
    vistos = perfil.get("tilesSeen")
    if not isinstance(vistos, list):
        return set()
    return {v for v in vistos if isinstance(v, str) and _ID_VISTO.fullmatch(v)}


def gravar_vistos(perfil, ids):
    """Acrescenta ids a tilesSeen. Devolve True se a lista mudou.

    Não tira ids antigos: um jogo que saiu e voltou continua "já oferecido"
    se os pais o tinham apagado. Lista sempre ordenada, para a segunda
    sincronização não regravar o arquivo à toa.
    """
    if not isinstance(perfil, dict):
        return False
    atuais = perfil.get("tilesSeen")
    base = ids_vistos(perfil)
    extra = {i for i in ids if isinstance(i, str) and _ID_VISTO.fullmatch(i)}
    if not extra and not isinstance(atuais, list):
        return False
    novo = sorted(base | extra)
    if isinstance(atuais, list) and atuais == novo:
        return False
    perfil["tilesSeen"] = novo
    return True


def retirar_de_outros_generos(perfil, arquivo=ARQUIVO):
    """Tira do perfil os jogos que são de outro gênero.

    Serve para um perfil que acabou de nascer do modelo (configuração inicial
    ou perfil novo) e ainda não guarda escolha dos pais.
    """
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
    """Acrescenta os jogos do gênero que o perfil ainda não tem. Devolve quantos.

    Id que já esteve no perfil e foi apagado (tilesSeen) não volta. Os jogos
    novos entram no fim: a ordem que os pais arrastaram não muda.
    """
    if not isinstance(perfil, dict):
        return 0
    lista = carregar(arquivo).get(perfil.get("gender"), [])
    if not lista:
        return 0
    tiles = perfil.setdefault("tiles", [])
    if not isinstance(tiles, list):
        return 0
    presentes = {t.get("id") for t in tiles if isinstance(t, dict)}
    vistos = ids_vistos(perfil)
    acrescentados = 0
    for jogo in lista:
        if jogo["id"] in presentes or jogo["id"] in vistos:
            continue
        tiles.append(tile_de(jogo, plataforma, moldura=moldura, porta=porta))
        presentes.add(jogo["id"])
        acrescentados += 1
    # Jogo que já está no perfil não muda de nome nem de lugar. Só a folga da
    # moldura (pad=) entra no comando, se ele ainda for o da moldura: sem isso
    # o GameMaker que já foi instalado continua com a barra de rolagem.
    por_id = {jogo["id"]: jogo for jogo in lista}
    for tile in tiles:
        if not isinstance(tile, dict):
            continue
        jogo = por_id.get(tile.get("id"))
        if not jogo or not jogo.get("pad"):
            continue
        if not _comando_de_moldura(tile.get("cmd")):
            continue
        novo = tile_de(jogo, plataforma, moldura=moldura, porta=porta)["cmd"]
        if tile.get("cmd") != novo:
            tile["cmd"] = novo
    gravar_vistos(perfil, [jogo["id"] for jogo in lista])
    return acrescentados


def aplicar_genero_inicial(perfil, plataforma="linux", moldura=None, porta=PORTA, arquivo=ARQUIVO):
    """Monta os jogos do gênero num perfil novo, igual na configuração inicial.

    Tira o que é de outro gênero (veio copiado do modelo) e acrescenta os
    deste. Devolve quantos jogos entrou.
    """
    retirar_de_outros_generos(perfil, arquivo=arquivo)
    return aplicar_perfil(
        perfil, plataforma, moldura=moldura, porta=porta, arquivo=arquivo,
    )


def trocar_genero(perfil, plataforma="linux", moldura=None, porta=PORTA, arquivo=ARQUIVO):
    """O gênero de um perfil que já existe mudou.

    Os jogos exclusivos do gênero anterior saem, se estavam visíveis, e os
    deste gênero entram. Jogo que os pais apagaram (id em tilesSeen, sem o
    tile) não volta. Jogo que os pais ocultaram (visible false) continua
    oculto, no mesmo lugar. Jogo que saiu só porque o gênero mudou pode
    voltar se o gênero voltar. Devolve quantos jogos entrou.
    """
    if not isinstance(perfil, dict) or perfil.get("gender") not in ("menino", "menina"):
        return 0
    dados = carregar(arquivo)
    gender = perfil.get("gender")
    outros = {
        jogo["id"]
        for outro, lista in dados.items()
        if outro != gender
        for jogo in lista
    }
    tiles = perfil.get("tiles")
    if not isinstance(tiles, list):
        perfil["tiles"] = []
        tiles = perfil["tiles"]
    ficam = []
    sairam = []
    for tile in tiles:
        tid = tile.get("id") if isinstance(tile, dict) else None
        oculto = isinstance(tile, dict) and tile.get("visible") is False
        if tid in outros and not oculto:
            sairam.append(tid)
            continue
        ficam.append(tile)
    perfil["tiles"] = ficam
    if sairam and isinstance(perfil.get("tilesSeen"), list):
        sair = set(sairam)
        perfil["tilesSeen"] = [i for i in perfil["tilesSeen"] if i not in sair]
    return aplicar_perfil(
        perfil, plataforma, moldura=moldura, porta=porta, arquivo=arquivo,
    )


def aplicar(cfg, plataforma="linux", moldura=None, porta=PORTA, arquivo=ARQUIVO):
    if not isinstance(cfg, dict):
        return 0
    return sum(
        aplicar_perfil(perfil, plataforma, moldura=moldura, porta=porta, arquivo=arquivo)
        for perfil in cfg.get("profiles", [])
        if isinstance(perfil, dict)
    )
