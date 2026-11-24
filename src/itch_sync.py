#!/usr/bin/env python3
"""Sincroniza as coleções públicas do itch.io com os perfis das crianças.

Roda no Windows e no Linux (thread do servidor, e no Linux também pelo
cozy-itch-sync). Cada perfil recebe os jogos de navegador (HTML5) da coleção:

1. se ~/.config/cozy-kids-launcher/itch-colecoes.json tiver o id do perfil,
   essa URL manda (é o que o notebook já configurado usa);
2. senão, gender "menina" usa a coleção bea e "menino" a coleção beni;
3. perfil sem gender não recebe coleção.

Jogo novo entra ligado, na categoria "jogos". O que os pais mudaram
(visível, categoria, nome) fica. Jogo que saiu da coleção some. Sem internet,
ou se a página não vier no formato esperado, o config.json não muda.
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
import urllib.request

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


def _fragmento_valido(frag):
    if not isinstance(frag, str) or not _FRAG_MOLDURA.fullmatch(frag):
        return False
    if "w=" not in frag or "h=" not in frag:
        return False
    # o iframe só recebe http(s); javascript: e file: não passam
    return "u=https%3A%2F%2F" in frag or "u=http%3A%2F%2F" in frag


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


def url_da_moldura(url, moldura=None):
    """file:///…/jogo.html#fragmento, com acentos e espaços codificados. Ou None."""
    frag = fragmento_da_moldura(url)
    if not frag:
        return None
    caminho = pathlib.Path(moldura or caminho_da_moldura())
    if not caminho.is_absolute():
        caminho = pathlib.Path(os.path.abspath(caminho))
    return caminho.as_uri() + "#" + frag


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
    return ["navegador-jogos", "file://%s#%s" % (caminhos.moldura, frag)]


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


def mesclar_tiles(tiles_atuais, tiles_colecao):
    """Preserva visível, categoria e nome. Tira o itch-* que saiu da coleção."""
    atuais = tiles_atuais if isinstance(tiles_atuais, list) else []
    antigos = {
        t["id"]: t
        for t in atuais
        if isinstance(t, dict) and str(t.get("id", "")).startswith("itch-")
    }
    novos = []
    for tile in tiles_colecao:
        velho = dict(antigos.get(tile["id"], {}))
        tile = dict(tile)
        tile["visible"] = velho.get("visible", True)
        tile["category"] = velho.get("category", "jogos")
        if velho.get("label"):
            tile["label"] = velho["label"]
        novos.append({**velho, **tile})
    resto = [
        t
        for t in atuais
        if not (isinstance(t, dict) and str(t.get("id", "")).startswith("itch-"))
    ]
    return novos + resto


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
        tiles = []
        for link, titulo, capa_lista in jogos:
            try:
                info = info_do_jogo(link, cache, baixar)
            except Exception as erro:
                log(caminhos.log, f"  {titulo}: erro ao ler o jogo ({erro})")
                continue
            if not info["embed"]:
                log(caminhos.log, f"  {titulo}: sem versão de navegador, ignorado")
                continue
            nome = slug(link)
            try:
                icone = salvar_capa(capa_lista or info["capa"], nome, caminhos.capas, baixar) or "🎮"
            except Exception as erro:
                log(caminhos.log, f"  capa falhou ({erro})")
                icone = "🎮"
            tiles.append({
                "id": "itch-" + nome,
                "label": titulo[:60],
                "emoji": icone,
                "cmd": comando_do_jogo(info, plataforma, caminhos),
                "visible": True,
                "category": "jogos",
            })
        por_perfil[perfil.get("id")] = tiles
        algum = True
        if origem == "json":
            como = "itch-colecoes.json"
        else:
            como = f"gênero {origem}"
        log(caminhos.log, f"{pid}: {len(tiles)} jogo(s) de navegador na coleção ({como})")

    if algum:
        gravar_json(caminhos.cache, cache)

    # Jogos por gênero (vestir/maquiagem) não dependem da página da coleção:
    # entram mesmo sem internet. Tile que já existe não muda — por isso a
    # moldura antiga (http://127.0.0.1/jogo.html) é convertida aqui, mesmo
    # quando a coleção não pôde ser lida.
    import jogos_genero

    convertidos = converter_comandos_velhos(cfg)
    if convertidos:
        log(caminhos.log, f"{convertidos} comando(s) antigo(s) de jogo convertido(s) para a moldura local")
    mudou = convertidos > 0
    acrescentou = 0
    for perfil in cfg.get("profiles", []):
        if not isinstance(perfil, dict):
            continue
        if perfil.get("id") in por_perfil:
            lista = mesclar_tiles(perfil.get("tiles", []), por_perfil[perfil["id"]])
            if lista != perfil.get("tiles"):
                perfil["tiles"] = lista
                mudou = True
        novos = jogos_genero.aplicar_perfil(
            perfil, plataforma, moldura=caminhos.moldura, porta=caminhos.porta,
        )
        if novos:
            acrescentou += novos
            log(caminhos.log, f"{perfil.get('id')}: {novos} jogo(s) por gênero acrescentado(s)")
    if mudou or acrescentou:
        gravar_json(caminhos.config, cfg)
        log(caminhos.log, "config.json atualizado")
    elif por_perfil:
        log(caminhos.log, "nada mudou")
    return 0


def sincronizar(caminhos=None, baixar=None, plataforma=None, usar_trava=True):
    caminhos = caminhos or caminhos_padrao()
    baixar = baixar or baixar_rede
    plataforma = plataforma or _plataforma()
    fd = None
    try:
        if usar_trava:
            fd = _adquirir_trava(caminhos.trava)
            if fd is None:
                log(caminhos.log, "outra sincronização em andamento")
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
