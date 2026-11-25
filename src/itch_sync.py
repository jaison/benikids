#!/usr/bin/env python3
"""Sincroniza as coleções públicas do itch.io com os perfis das crianças.

Roda no Windows e no Linux (thread do servidor, e no Linux também pelo
cozy-itch-sync). Cada perfil recebe os jogos de navegador (HTML5) da coleção:

1. se ~/.config/cozy-kids-launcher/itch-colecoes.json tiver o id do perfil,
   essa URL manda (é o que o notebook já configurado usa);
2. senão, gender "menina" usa a coleção bea e "menino" a coleção beni;
3. perfil sem gender não recebe coleção.

Jogo novo entra ligado, na categoria "jogos", no fim da lista — a ordem
que os pais arrastaram fica. O que os pais mudaram (visível, categoria, nome)
fica. Jogo que saiu da coleção some. Jogo que os pais apagaram não volta
(o id fica em tilesSeen). Sem internet, ou se a página não vier no formato
esperado, os tiles da coleção não mudam.

A gravação relê o config.json na hora, já com a trava do servidor, e só
reaplica os tiles da coleção e os jogos por gênero. PIN, tempo e o resto
do que os pais salvaram durante o download permanecem.
"""
import html
import json
import os
import pathlib
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from config_store import atomic_write_config, config_lock

# Coleções públicas do projeto. Sem nome de criança, e-mail ou lugar.
COLECAO_BEA = "https://itch.io/c/8339492/bea"
COLECAO_BENI = "https://itch.io/c/8339489/beni"
COLECOES_PADRAO = {"menina": COLECAO_BEA, "menino": COLECAO_BENI}

# Genérico, sem dados da criança nem do computador.
UA = "Mozilla/5.0 (compatible; BenikidsItchSync/1.0)"
PAUSA = 2.5  # segundos entre pedidos, para não levar "429 Too Many Requests"
INICIO_SEGUNDOS = 120  # a thread do servidor espera o menu subir
INTERVALO_SEGUNDOS = 30 * 60
TRAVA_VELHA = 30 * 60  # trava esquecada por um processo que caiu
ESPERA_TRAVA_SEGUNDOS = 1

HOME = os.path.expanduser("~")


class Caminhos:
    def __init__(self, config, colecoes, cache, capas, log, trava, moldura, porta):
        self.config = config
        self.colecoes = colecoes
        self.cache = cache
        self.capas = capas
        self.log = log
        self.trava = trava
        self.moldura = moldura
        self.porta = porta


def caminhos_padrao():
    return Caminhos(
        config=os.path.join(HOME, ".config/cozy-kids-launcher/config.json"),
        colecoes=os.path.join(HOME, ".config/cozy-kids-launcher/itch-colecoes.json"),
        cache=os.path.join(HOME, ".cache/cozy-kids-launcher/itch-cache.json"),
        capas=os.path.join(HOME, ".local/share/cozy-kids-launcher/themes/covers"),
        log=os.path.join(HOME, ".local/state/cozy-kids-launcher/itch-sync.log"),
        trava=os.path.join(HOME, ".cache/cozy-kids-launcher/itch-sync.lock"),
        moldura=os.path.join(HOME, ".var/app/org.chromium.Chromium/cozy-jogo.html"),
        porta=int(os.environ.get("COZY_KIDS_PORT", "38431")),
    )


def log(caminho, msg):
    try:
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        linha = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
        print(linha)
        with open(caminho, "a", encoding="utf-8") as arquivo:
            arquivo.write(linha + "\n")
    except OSError:
        pass


def dormir(segundos):
    time.sleep(segundos)


def baixar_rede(url, binario=False, tentativas=4):
    espera = 10
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as resposta:
                dados = resposta.read()
            dormir(PAUSA)
            return dados if binario else dados.decode("utf-8", "replace")
        except urllib.error.HTTPError as erro:
            if erro.code == 429 and i < tentativas - 1:
                dormir(espera)
                espera *= 2
                continue
            raise
    raise RuntimeError("falhou: " + url)


def jogos_da_colecao(url, baixar):
    """Lista (url_do_jogo, titulo, capa) de todas as páginas da coleção."""
    jogos, vistos, pagina = [], set(), 1
    while pagina <= 20:
        pg = baixar(url + ("" if pagina == 1 else f"?page={pagina}"))
        if pagina == 1 and "game_cell" not in pg:
            # página de erro ou bloqueio: não apagar os jogos que já estão no menu
            raise RuntimeError("formato inesperado")
        novos = 0
        for cel in re.split(r'<div[^>]+class="game_cell[ "]', pg)[1:]:
            encontrado = re.search(
                r'class="title game_link"[^>]*href="([^"]+)"[^>]*>([^<]+)<', cel
            ) or re.search(
                r'href="([^"]+)"[^>]*class="title game_link"[^>]*>([^<]+)<', cel
            )
            if not encontrado:
                continue
            link, titulo = encontrado.group(1), html.unescape(encontrado.group(2)).strip()
            if link in vistos:
                continue
            capa = re.search(r'data-lazy_src="([^"]+)"', cel) or re.search(
                r'<img[^>]+src="(https://img\.itch\.zone/[^"]+)"', cel
            )
            jogos.append((link, titulo, capa.group(1) if capa else ""))
            vistos.add(link)
            novos += 1
        if novos == 0 or (
            'class="next_page' not in pg and "?page=%d" % (pagina + 1) not in pg
        ):
            break
        pagina += 1
    return jogos


def info_do_jogo(link, cache, baixar):
    if link in cache and "unity" in cache[link]:
        return cache[link]
    pg = baixar(link)
    emb = re.search(r'https://html(?:-classic)?\.itch\.zone/html/\d+/[^"&\s]*?index\.html', pg)
    if not emb:
        emb = re.search(
            r'(?:https:)?//html(?:-classic)?\.itch\.zone/html/\d+/[^"&\s]*',
            html.unescape(pg),
        )
    capa = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', pg)
    if emb and emb.group(0).startswith("//"):
        embed = emb.group(0).replace("//html", "https://html", 1)
    else:
        embed = emb.group(0) if emb else ""
    info = {"embed": embed, "capa": capa.group(1) if capa else ""}
    tam = re.search(
        r'init_HtmlEmbed\([^,]+,\s*\{[^}]*"height":(\d+)[^}]*"width":(\d+)', pg
    ) or re.search(
        r'init_HtmlEmbed\([^,]+,\s*\{[^}]*"width":(\d+)[^}]*"height":(\d+)', pg
    )
    if tam:
        a, b = int(tam.group(1)), int(tam.group(2))
        if (
            '"height":' + tam.group(1) in tam.group(0)
            and tam.group(0).index('"height"') < tam.group(0).index('"width"')
        ):
            info["h"], info["w"] = a, b
        else:
            info["h"], info["w"] = b, a
    else:
        info["w"] = info["h"] = 0
    # Jogos Unity: guarda o tamanho do canvas para esconder a faixa de baixo.
    info["unity"] = []
    if info["embed"]:
        try:
            idx = baixar(info["embed"])
            u = re.search(
                r'id="unity-canvas"[^>]*?width=["\']?(\d+)["\']?[^>]*?height=["\']?(\d+)',
                idx,
            )
            if u and 'id="unity-footer"' in idx:
                info["unity"] = [int(u.group(1)), int(u.group(2))]
        except Exception:
            pass
    cache[link] = info
    return info


def slug(link):
    encontrado = re.match(r"https?://([a-z0-9-]+)\.itch\.io/([a-z0-9_-]+)", link)
    texto = (encontrado.group(2) if encontrado else re.sub(r"[^a-z0-9]+", "-", link.lower()))[:60]
    return re.sub(r"[^A-Za-z0-9_-]", "-", texto)


def partes_do_link(link):
    """Devolve (autor, jogo) a partir de https://autor.itch.io/jogo."""
    encontrado = re.match(r"https?://([a-z0-9-]+)\.itch\.io/([a-z0-9_-]+)", str(link), re.I)
    if not encontrado:
        texto = re.sub(r"[^a-z0-9]+", "-", str(link).lower()).strip("-")[:40]
        return "", texto
    autor = re.sub(r"[^A-Za-z0-9_-]", "-", encontrado.group(1))[:30]
    jogo = re.sub(r"[^A-Za-z0-9_-]", "-", encontrado.group(2))[:40]
    return autor, jogo


def _id_livre(candidato, usados, ocupados):
    candidato = re.sub(r"[^A-Za-z0-9_-]", "-", candidato or "")[:80].strip("-")
    if candidato and candidato not in usados and candidato not in ocupados:
        return candidato
    base = (candidato or "itch-jogo")[:70].strip("-")
    for n in range(2, 50):
        alt = f"{base}-{n}"[:80]
        if alt not in usados and alt not in ocupados:
            return alt
    return None


def ids_da_colecao(brutos, tiles_atuais):
    """Um id por jogo. O id curto (itch-dog-wash) fica, se já existir ou se estiver livre.

    Dois jogos com o mesmo nome ganham o autor no id (itch-autor-jogo) só a
    partir do segundo. Nunca devolve o mesmo id duas vezes, nem um id que já
    pertence a um tile que não é desta coleção.
    """
    tiles_atuais = tiles_atuais if isinstance(tiles_atuais, list) else []
    ocupados = set()
    itch_ids = set()
    embed_para_id = {}
    for tile in tiles_atuais:
        if not isinstance(tile, dict) or not isinstance(tile.get("id"), str):
            continue
        tid = tile["id"]
        if tid.startswith("itch-"):
            itch_ids.add(tid)
            embed = embed_do_tile(tile)
            if embed and embed not in embed_para_id:
                embed_para_id[embed] = tid
        else:
            ocupados.add(tid)

    escolhidos = [None] * len(brutos)
    usados = set()
    for i, bruto in enumerate(brutos):
        embed = (bruto.get("info") or {}).get("embed") or ""
        eid = embed_para_id.get(embed)
        if eid and eid not in usados:
            escolhidos[i] = eid
            usados.add(eid)

    grupos = {}
    for i, bruto in enumerate(brutos):
        if escolhidos[i] is not None:
            continue
        autor, jogo = partes_do_link(bruto.get("link"))
        grupos.setdefault(jogo or "jogo", []).append((i, autor))

    for jogo, itens in grupos.items():
        curto = ("itch-" + jogo)[:80]
        livres = list(itens)
        curto_livre = curto not in usados and curto not in ocupados
        # Id curto (itch-dog-wash) fica com o primeiro jogo deste nome, seja
        # porque o PC já tem esse id, seja porque ninguém o usa ainda.
        if curto_livre and livres:
            indice, _autor = livres.pop(0)
            escolhidos[indice] = curto
            usados.add(curto)
        for indice, autor in livres:
            candidato = ("itch-" + autor + "-" + jogo)[:80] if autor else ""
            if not candidato or candidato == curto:
                candidato = ("itch-outro-" + jogo)[:80]
            livre = _id_livre(candidato, usados, ocupados | (itch_ids - usados))
            escolhidos[indice] = livre
            if livre:
                usados.add(livre)
    return escolhidos


def arquivo_da_capa(nome, ext):
    """O emoji do tile cabe em 32 caracteres: "img:covers/" + arquivo."""
    base = nome[:20]
    while base and len("img:covers/" + base + ext) > 32:
        base = base[:-1]
    return (base or "capa") + ext


def salvar_capa(url, nome, capas, baixar):
    if not url:
        return ""
    os.makedirs(capas, exist_ok=True)
    ext = os.path.splitext(url.split("?")[0])[1].lower()
    ext = ext if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp") else ".png"
    arq = arquivo_da_capa(nome, ext)
    caminho = os.path.join(capas, arq)
    if not os.path.exists(caminho):
        with open(caminho, "wb") as arquivo:
            arquivo.write(baixar(url, binario=True))
    return "img:covers/" + arq


def fragmento(info):
    from urllib.parse import quote

    embed = quote(info.get("embed") or "", safe="")
    if info.get("unity"):
        uw, uh = info["unity"]
        # a página do Unity centraliza canvas + faixa (38 px); mostra só o canvas
        return "w=%d&h=%d&fh=%d&u=%s" % (uw, uh, uh + 38, embed)
    try:
        folga = int(info.get("pad") or 0)
    except (TypeError, ValueError):
        folga = 0
    if folga > 0:
        # GameMaker: o canvas é fixo e inline. A folga joga a barra para fora
        # da área visível. Não usar em jogo que ocupa a janela inteira (Godot).
        return "w=%d&h=%d&pad=%d&u=%s" % (info.get("w", 0), info.get("h", 0), folga, embed)
    return "w=%d&h=%d&u=%s" % (info.get("w", 0), info.get("h", 0), embed)


# No Windows o tile não guarda caminho nem porta. Na hora de abrir, o servidor
# troca este token pela moldura local em file:// (origem opaca). http://127.0.0.1
# faz o htmlgame.js do itch.io cair em itch.io/embed-hotlink.
TOKEN_MOLDURA = "benikids-jogo:"
_FRAG_MOLDURA = re.compile(r"^[A-Za-z0-9%&=._~+-]+$")
_CMD_VELHO = re.compile(
    r"^https?://(?:127\.0\.0\.1|localhost)(?::\d+)?/jogo\.html#([A-Za-z0-9%&=._~+-]+)$"
)


def caminho_da_moldura():
    """jogo.html que veio na instalação, ao lado deste módulo.

    No Windows o pacote fica em ~/.local/share/cozy-kids-launcher, pasta do
    próprio usuário (dá para ler; a página não escreve). Uma cópia à parte
    ficaria para trás quando o Benikids atualiza a moldura.
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "jogo.html")


def _embed_do_fragmento(frag):
    if not isinstance(frag, str) or not frag:
        return ""
    try:
        valores = urllib.parse.parse_qs(frag, keep_blank_values=False).get("u") or []
    except ValueError:
        return ""
    if len(valores) != 1 or not isinstance(valores[0], str):
        return ""
    return valores[0]


def embed_permitido(url):
    """Só https em html.itch.zone, html-classic.itch.zone e demais *.itch.zone.

    Os jogos das coleções e os bea-* de hoje abrem em html-classic.itch.zone.
    html.itch.zone é o host novo do itch. img.itch.zone e qualquer outro
    subdomínio também passam; itch.zone sozinho (sem subdomínio) não.
    """
    if not isinstance(url, str) or not url or len(url) > 2000:
        return False
    try:
        partes = urllib.parse.urlsplit(url)
        porta = partes.port
    except ValueError:
        return False
    if partes.scheme != "https" or partes.username is not None or partes.password is not None:
        return False
    if porta not in (None, 443):
        return False
    host = (partes.hostname or "").lower().rstrip(".")
    if not host or host == "itch.zone" or not host.endswith(".itch.zone"):
        return False
    if ".." in host or not re.fullmatch(r"[a-z0-9.-]+", host):
        return False
    return True


def _fragmento_valido(frag):
    if not isinstance(frag, str) or not _FRAG_MOLDURA.fullmatch(frag):
        return False
    if "w=" not in frag or "h=" not in frag:
        return False
    # javascript: e file: não passam; http também não (só https no itch.zone)
    return embed_permitido(_embed_do_fragmento(frag))


def embed_do_tile(tile):
    cmd = tile.get("cmd") if isinstance(tile, dict) else None
    if not isinstance(cmd, list):
        return ""
    for parte in cmd:
        if not isinstance(parte, str) or "#" not in parte:
            continue
        embed = _embed_do_fragmento(parte.split("#", 1)[1])
        if embed:
            return embed
    return ""


def fragmento_da_moldura(url):
    """Fragmento (#w=&h=&u=) de um comando de moldura, novo ou antigo. Ou None."""
    if not isinstance(url, str):
        return None
    if url.startswith(TOKEN_MOLDURA + "#"):
        frag = url[len(TOKEN_MOLDURA) + 1:]
    else:
        velho = _CMD_VELHO.fullmatch(url)
        frag = velho.group(1) if velho else None
    return frag if _fragmento_valido(frag) else None


def comando_da_moldura(frag):
    return ["special:external-browser:" + TOKEN_MOLDURA + "#" + frag]


def uri_arquivo(caminho):
    """file:/// com acentos e espaços codificados, no Windows e no Linux."""
    path = pathlib.Path(caminho)
    if not path.is_absolute():
        path = pathlib.Path(os.path.abspath(str(path)))
    return path.as_uri()


def url_da_moldura(url, moldura=None):
    """file:///…/jogo.html#fragmento, com acentos e espaços codificados. Ou None."""
    frag = fragmento_da_moldura(url)
    if not frag:
        return None
    return uri_arquivo(moldura or caminho_da_moldura()) + "#" + frag


def converter_comando_gravado(cmd):
    """http://127.0.0.1/jogo.html#… gravado no config vira o token estável.

    Devolve None quando o comando não é a moldura antiga (o Linux, os sites
    e o PhET em 127.0.0.1/sites/ ficam como estão).
    """
    prefixo = "special:external-browser:"
    if not (isinstance(cmd, list) and len(cmd) == 1 and isinstance(cmd[0], str)):
        return None
    if not cmd[0].startswith(prefixo):
        return None
    url = cmd[0][len(prefixo):]
    if _CMD_VELHO.fullmatch(url) is None:
        return None
    frag = fragmento_da_moldura(url)
    if not frag:
        return None
    return comando_da_moldura(frag)


def converter_comandos_velhos(cfg):
    """Converte a moldura antiga em todos os perfis. Devolve quantos tiles mudaram."""
    if not isinstance(cfg, dict):
        return 0
    n = 0
    for perfil in cfg.get("profiles", []):
        if not isinstance(perfil, dict):
            continue
        for tile in perfil.get("tiles") or []:
            if not isinstance(tile, dict):
                continue
            novo = converter_comando_gravado(tile.get("cmd"))
            if novo and novo != tile.get("cmd"):
                tile["cmd"] = novo
                n += 1
    return n


def comando_do_jogo(info, plataforma, caminhos):
    frag = fragmento(info)
    if plataforma == "windows":
        # O mesmo caminho dos sites: o servidor abre o Edge em --kiosk --app,
        # com a pílula, o ‹ Voltar e o limite da categoria do tile. A URL
        # file:// só nasce na abertura (url_da_moldura).
        return comando_da_moldura(frag)
    return ["navegador-jogos", uri_arquivo(caminhos.moldura) + "#" + frag]


def atualizar_uri_da_moldura(cmd, moldura):
    """Codifica o file:// já gravado no Linux. O fragmento (#w=&h=&u=) fica."""
    if not isinstance(cmd, list) or len(cmd) != 2 or cmd[0] != "navegador-jogos":
        return cmd
    url = cmd[1]
    if not isinstance(url, str) or "#" not in url:
        return cmd
    if "jogo.html#" not in url and "cozy-jogo.html#" not in url:
        return cmd
    frag = url.split("#", 1)[1]
    if not _fragmento_valido(frag):
        return cmd
    novo = ["navegador-jogos", uri_arquivo(moldura) + "#" + frag]
    return novo if novo != cmd else cmd


def url_da_colecao(perfil, mapa):
    """Devolve (url, origem) ou (None, None). origem: "json", "menina" ou "menino"."""
    if not isinstance(perfil, dict):
        return None, None
    pid = perfil.get("id")
    if isinstance(mapa, dict) and isinstance(pid, str) and pid in mapa:
        url = mapa[pid]
        if isinstance(url, str) and url.strip():
            return url.strip(), "json"
    gender = perfil.get("gender")
    if gender in COLECOES_PADRAO:
        return COLECOES_PADRAO[gender], gender
    return None, None


def _atualizar_tile(velho, novo):
    tile = dict(novo)
    tile["visible"] = velho.get("visible", True) if isinstance(velho, dict) else True
    tile["category"] = velho.get("category", "jogos") if isinstance(velho, dict) else "jogos"
    if isinstance(velho, dict) and velho.get("label"):
        tile["label"] = velho["label"]
    if isinstance(velho, dict):
        return {**velho, **tile}
    return tile


def mesclar_tiles(tiles_atuais, tiles_colecao, vistos=None):
    """Mantém a ordem. Atualiza o itch-* que continua. Tira o que saiu.

    Id em `vistos` que não está mais na lista foi apagado pelos pais: não
    volta. Jogo novo (não visto e não presente) entra no fim.
    """
    atuais = tiles_atuais if isinstance(tiles_atuais, list) else []
    vistos = set(vistos or [])
    colecao = {}
    for tile in tiles_colecao:
        if isinstance(tile, dict) and tile.get("id") and tile["id"] not in colecao:
            colecao[tile["id"]] = tile
    resultado = []
    presentes = set()
    for tile in atuais:
        if not isinstance(tile, dict):
            resultado.append(tile)
            continue
        tid = str(tile.get("id", ""))
        if tid.startswith("itch-"):
            if tid not in colecao:
                continue
            resultado.append(_atualizar_tile(tile, colecao[tid]))
            presentes.add(tid)
        else:
            resultado.append(tile)
            if tid:
                presentes.add(tid)
    for tid, tile in colecao.items():
        if tid in presentes or tid in vistos:
            continue
        resultado.append(dict(tile))
        presentes.add(tid)
    return resultado


def tem_id_duplicado(cfg):
    if not isinstance(cfg, dict):
        return False
    for perfil in cfg.get("profiles") or []:
        if not isinstance(perfil, dict):
            continue
        ids = []
        for tile in perfil.get("tiles") or []:
            if isinstance(tile, dict):
                ids.append(tile.get("id"))
        if len(ids) != len(set(ids)):
            return True
    return False


def gravar_json(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(caminho))
    with os.fdopen(fd, "w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, indent=2, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, caminho)


def ler_mapa(caminho):
    try:
        with open(caminho, encoding="utf-8") as arquivo:
            mapa = json.load(arquivo)
    except OSError:
        return {}
    except ValueError:
        return {}
    return mapa if isinstance(mapa, dict) else {}


def _adquirir_trava(caminho):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, str(os.getpid()).encode())
            return fd
        except FileExistsError:
            try:
                velha = time.time() - os.path.getmtime(caminho) > TRAVA_VELHA
            except OSError:
                velha = True
            if not velha:
                return None
            try:
                os.unlink(caminho)
            except OSError:
                return None
    return None


def _soltar_trava(caminho, fd):
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(caminho)
    except OSError:
        pass


def _plataforma():
    return "windows" if os.name == "nt" else "linux"


def _sincronizar(caminhos, baixar, plataforma):
    try:
        with open(caminhos.config, encoding="utf-8") as arquivo:
            cfg = json.load(arquivo)
    except OSError:
        log(caminhos.log, "sem config.json; nada a fazer")
        return 0
    except ValueError:
        log(caminhos.log, "config.json inválido; nada a fazer")
        return 0
    if not isinstance(cfg, dict):
        log(caminhos.log, "config.json inválido; nada a fazer")
        return 0

    mapa = ler_mapa(caminhos.colecoes)
    try:
        with open(caminhos.cache, encoding="utf-8") as arquivo:
            cache = json.load(arquivo)
    except (OSError, ValueError):
        cache = {}
    if not isinstance(cache, dict):
        cache = {}

    por_perfil = {}
    algum = False
    for perfil in cfg.get("profiles", []):
        if not isinstance(perfil, dict):
            continue
        pid = str(perfil.get("id", ""))
        url, origem = url_da_colecao(perfil, mapa)
        if not url:
            log(caminhos.log, f"{pid}: sem gênero, nenhuma coleção")
            continue
        try:
            jogos = jogos_da_colecao(url, baixar)
        except Exception as erro:
            log(caminhos.log, f"{pid}: não consegui ler a coleção ({erro}); mantendo como está")
            continue
        repetidos = {}
        for link, _titulo, _capa in jogos:
            _autor, jogo = partes_do_link(link)
            chave = jogo or "jogo"
            repetidos[chave] = repetidos.get(chave, 0) + 1
        brutos = []
        for link, titulo, capa_lista in jogos:
            try:
                info = info_do_jogo(link, cache, baixar)
            except Exception as erro:
                log(caminhos.log, f"  {titulo}: erro ao ler o jogo ({erro})")
                continue
            if not info["embed"]:
                log(caminhos.log, f"  {titulo}: sem versão de navegador, ignorado")
                continue
            autor, jogo = partes_do_link(link)
            # Capa com o nome curto de sempre. Só entra o autor quando dois
            # jogos da coleção têm o mesmo nome (senão o arquivo da capa colide).
            if repetidos.get(jogo or "jogo", 0) > 1 and autor:
                nome_capa = (autor + "-" + (jogo or "jogo"))[:40]
            else:
                nome_capa = slug(link)
            try:
                icone = salvar_capa(capa_lista or info["capa"], nome_capa, caminhos.capas, baixar) or "🎮"
            except Exception as erro:
                log(caminhos.log, f"  capa falhou ({erro})")
                icone = "🎮"
            brutos.append({
                "link": link,
                "titulo": titulo[:60],
                "icone": icone,
                "info": info,
            })
        por_perfil[perfil.get("id")] = brutos
        algum = True
        if origem == "json":
            como = "itch-colecoes.json"
        else:
            como = f"gênero {origem}"
        log(caminhos.log, f"{pid}: {len(brutos)} jogo(s) de navegador na coleção ({como})")

    if algum:
        gravar_json(caminhos.cache, cache)

    # A rede pode ter levado minutos. Relê o config com a trava do servidor e
    # reaplica só a coleção e os jogos por gênero em cima do que está no disco.
    _aplicar_e_gravar(caminhos, por_perfil, plataforma)
    return 0


def montar_tiles(brutos, tiles_atuais, plataforma, caminhos):
    """Tiles da coleção, com id estável. Devolve (tiles, títulos sem id único)."""
    ids = ids_da_colecao(brutos, tiles_atuais)
    tiles = []
    pulados = []
    for bruto, tid in zip(brutos, ids):
        if not tid:
            pulados.append(bruto.get("titulo") or bruto.get("link") or "jogo")
            continue
        tiles.append({
            "id": tid,
            "label": bruto.get("titulo") or tid,
            "emoji": bruto.get("icone") or "🎮",
            "cmd": comando_do_jogo(bruto.get("info") or {}, plataforma, caminhos),
            "visible": True,
            "category": "jogos",
        })
    return tiles, pulados


def _aplicar(cfg, por_perfil, plataforma, caminhos):
    """Mexe só em tiles da coleção, jogos por gênero e tilesSeen. Devolve (mudou, acrescentou, convertidos)."""
    import copy

    import jogos_genero

    convertidos = converter_comandos_velhos(cfg)
    mudou = convertidos > 0
    acrescentou = 0
    for perfil in cfg.get("profiles") or []:
        if not isinstance(perfil, dict):
            continue
        if perfil.get("id") in por_perfil:
            tiles = perfil.get("tiles") if isinstance(perfil.get("tiles"), list) else []
            novos, pulados = montar_tiles(por_perfil[perfil["id"]], tiles, plataforma, caminhos)
            for titulo in pulados:
                log(caminhos.log, f"  {titulo}: não coube um id único, ignorado")
            lista = mesclar_tiles(tiles, novos, jogos_genero.ids_vistos(perfil))
            if lista != tiles:
                perfil["tiles"] = lista
                mudou = True
            if jogos_genero.gravar_vistos(perfil, [t["id"] for t in novos]):
                mudou = True
        vistos_antes = copy.deepcopy(perfil.get("tilesSeen"))
        tiles_antes = copy.deepcopy(perfil.get("tiles"))
        novos_genero = jogos_genero.aplicar_perfil(
            perfil, plataforma, moldura=caminhos.moldura, porta=caminhos.porta,
        )
        if novos_genero:
            acrescentou += novos_genero
            log(caminhos.log, f"{perfil.get('id')}: {novos_genero} jogo(s) por gênero acrescentado(s)")
        if perfil.get("tiles") != tiles_antes or perfil.get("tilesSeen") != vistos_antes:
            mudou = True
        if plataforma != "windows":
            for tile in perfil.get("tiles") or []:
                if not isinstance(tile, dict):
                    continue
                novo_cmd = atualizar_uri_da_moldura(tile.get("cmd"), caminhos.moldura)
                if novo_cmd != tile.get("cmd"):
                    tile["cmd"] = novo_cmd
                    mudou = True
    return mudou, acrescentou, convertidos


def _aplicar_e_gravar(caminhos, por_perfil, plataforma):
    with config_lock(caminhos.config):
        try:
            with open(caminhos.config, encoding="utf-8") as arquivo:
                cfg = json.load(arquivo)
        except (OSError, ValueError):
            log(caminhos.log, "config.json não pôde ser relido; nada gravado")
            return
        if not isinstance(cfg, dict):
            log(caminhos.log, "config.json não pôde ser relido; nada gravado")
            return
        mudou, acrescentou, convertidos = _aplicar(cfg, por_perfil, plataforma, caminhos)
        if convertidos:
            log(caminhos.log, f"{convertidos} comando(s) antigo(s) de jogo convertido(s) para a moldura local")
        if not mudou and not acrescentou:
            if por_perfil:
                log(caminhos.log, "nada mudou")
            return
        if tem_id_duplicado(cfg):
            log(caminhos.log, "config.json ficaria com id de tile repetido; nada gravado")
            return
        atomic_write_config(caminhos.config, cfg)
        log(caminhos.log, "config.json atualizado")


def _pegar_trava(caminhos, esperar, prazo):
    """A trava é um arquivo. Se outra sync já baixou os perfis, quem chega
    agora (o perfil recém-criado) espera e tenta de novo, senão lê o config
    velho e o menino fica sem a coleção até o ciclo de 30 min.
    """
    fd = _adquirir_trava(caminhos.trava)
    if fd is not None or not esperar:
        if fd is None:
            log(caminhos.log, "outra sincronização em andamento")
        return fd
    log(caminhos.log, "outra sincronização em andamento; esperando para tentar de novo")
    limite = time.monotonic() + (TRAVA_VELHA if prazo is None else prazo)
    while time.monotonic() < limite:
        dormir(ESPERA_TRAVA_SEGUNDOS)
        fd = _adquirir_trava(caminhos.trava)
        if fd is not None:
            return fd
    log(caminhos.log, "outra sincronização em andamento")
    return None


def sincronizar(caminhos=None, baixar=None, plataforma=None, usar_trava=True, esperar_trava=False, prazo_trava=None):
    caminhos = caminhos or caminhos_padrao()
    baixar = baixar or baixar_rede
    plataforma = plataforma or _plataforma()
    fd = None
    try:
        if usar_trava:
            fd = _pegar_trava(caminhos, esperar_trava, prazo_trava)
            if fd is None:
                return 0
        return _sincronizar(caminhos, baixar, plataforma)
    except Exception as erro:
        log(caminhos.log, f"sincronização falhou ({type(erro).__name__}: {erro})")
        return 1
    finally:
        if fd is not None:
            _soltar_trava(caminhos.trava, fd)


def loop(sincronizar_fn, esperar, parar=None):
    """Espera 2 min, sincroniza, e repete a cada 30 min."""
    parar = parar or (lambda: False)
    esperar(INICIO_SEGUNDOS)
    while not parar():
        try:
            sincronizar_fn()
        except Exception as erro:
            log(caminhos_padrao().log, f"sincronização falhou ({type(erro).__name__})")
        if parar():
            break
        esperar(INTERVALO_SEGUNDOS)


def iniciar():
    threading.Thread(
        target=loop, args=(sincronizar, dormir), name="itch-sync", daemon=True,
    ).start()


def main():
    return sincronizar()


if __name__ == "__main__":
    raise SystemExit(main())
