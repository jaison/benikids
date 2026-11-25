"""Limite de navegação da janela do site, um tile de cada vez.

No Edge/Chrome a extensão sites-limpos, carregada com --load-extension, ganha
regras declarativeNetRequest para a navegação de topo (main_frame). Iframe,
script e CDN não passam por aqui: o anúncio continua no --host-resolver-rules.

No Firefox do Linux a mesma lista vira a mesma extensão, instalada só no perfil
do Benikids (não no policies.json: aquilo vale para o Firefox da família). O
Firefox comum não aceita extensão local sem assinatura; o Benikids instala a
cópia como extensão temporária pelo Marionette, enquanto o site está aberto.

A lista sai da URL do tile. A cópia da extensão fica no perfil/cache do
Benikids, sem política de máquina e sem UAC.
"""

import html
import json
import os
import re
import shutil
import sys
import time
import zlib
from urllib.parse import urlsplit, urlunsplit

# Pasta da extensão dentro do perfil do Firefox dos sites (o snap só lê o perfil).
PASTA_LIMITE_NO_PERFIL = "benikids-sites-limpos"
ID_EXTENSAO_FIREFOX = "sites-limpos@benikids"

AQUI = os.path.dirname(os.path.abspath(__file__))
EXTENSAO = os.path.join(AQUI, "edge", "sites-limpos")

# com.br e companhia: o registrável tem três rótulos, não dois.
SUFIXOS_COMPOSTOS = (
    "com.br", "net.br", "org.br", "co.uk", "com.au", "co.jp", "com.mx", "com.ar", "com.tr",
)

# O host de partida é o site. Não solta o registrável inteiro quando ele é uma
# plataforma com outros produtos (o Music Lab não abre outro experimento).
ESTREITOS = {
    "musiclab.chromeexperiments.com": ("musiclab.chromeexperiments.com",),
}

# Domínio a mais, quando o tile precisa mesmo navegar para lá.
EXTRAS = {
    "youtubekids.com": ("accounts.google.com",),
}

# Caminhos que o Linux já bloqueia, e a doação do Code.org (mesmo domínio).
# Prioridade maior que o "permitir o domínio": a extensão barra mesmo sem a
# política do Edge, que pede administrador.
BLOQUEIOS = {
    "code.org": (
        r"(?i)^https?://donate\.code\.org(?::\d+)?(?:[/?#]|$)",
        r"(?i)^https?://(?:[a-z0-9-]+\.)*code\.org(?::\d+)?(?:/[^?#]*)?/donate(?:[/?#]|$)",
    ),
    "escolagames.com.br": (
        r"(?i)^https?://(?:[a-z0-9-]+\.)*escolagames\.com\.br(?::\d+)?/jogos-divertidos(?:[/?#]|$)",
        r"(?i)^https?://(?:[a-z0-9-]+\.)*escolagames\.com\.br(?::\d+)?/diversao(?:[/?#]|$)",
    ),
    "colorir-online.com": (
        r"(?i)^https?://(?:[a-z0-9-]+\.)*colorir-online\.com(?::\d+)?/apps(?:[/?#]|$)",
        r"(?i)^https?://(?:[a-z0-9-]+\.)*colorir-online\.com(?::\d+)?/quem-somos(?:[/?#]|$)",
    ),
}

# PhET: só a simulação. O resto (filtro, login, doação, STUDIO, site) não.
PHET_SIM = r"(?i)^https?://(?:www\.)?phet\.colorado\.edu/sims/html/"
PHET_PAGINA = "/sites/phet.html"


def registravel(host):
    """Domínio do site, sem o www e sem o subdomínio do serviço."""
    host = (host or "").lower().rstrip(".")
    if not host or _eh_ip(host) or host == "localhost":
        return host
    rotulos = host.split(".")
    if len(rotulos) >= 3 and ".".join(rotulos[-2:]) in SUFIXOS_COMPOSTOS:
        return ".".join(rotulos[-3:])
    if len(rotulos) >= 2:
        return ".".join(rotulos[-2:])
    return host


def _eh_ip(host):
    if host.count(".") == 3 and all(p.isdigit() and 0 <= int(p) <= 255 for p in host.split(".")):
        return True
    return ":" in host


def regex_host(dominio):
    """Casa o domínio e os subdomínios, em http e https, com qualquer caminho."""
    d = re.escape(dominio.lower())
    return rf"(?i)^https?://(?:[a-z0-9-]+\.)*{d}(?::\d+)?(?:[/?#]|$)"


def regex_url_inicial(url):
    """Casa a URL de partida, com ou sem âncora no fim."""
    partes = urlsplit(url.strip())
    sem_ancora = urlunsplit((partes.scheme, partes.netloc, partes.path, partes.query, ""))
    return "(?i)^" + re.escape(sem_ancora) + r"(?:#.*)?$"


def _e_phet(partes):
    host = (partes.hostname or "").lower()
    caminho = partes.path or ""
    return caminho.rstrip("/").endswith(PHET_PAGINA) or registravel(host) == "phet.colorado.edu"


def limites_da_url(url):
    """Domínios e caminhos da navegação de topo deste tile.

    permitir/bloquear são regex (RE2, as do declarativeNetRequest).
    resumo é a linha de log, sem caminho de arquivo.
    """
    partes = urlsplit(url)
    if _e_phet(partes):
        return {
            "inicio": url,
            "permitir": [PHET_SIM, regex_url_inicial(url)],
            "bloquear": [],
            "resumo": "phet.html local e phet.colorado.edu/sims/html/",
        }
    host = (partes.hostname or "").lower()
    reg = registravel(host)
    if host in ESTREITOS:
        bases = ESTREITOS[host]
    elif reg:
        bases = (reg,)
    else:
        bases = ()
    extras = EXTRAS.get(reg, ())
    hosts = tuple(dict.fromkeys(list(bases) + list(extras)))
    return {
        "inicio": url,
        "permitir": [regex_host(h) for h in hosts] + [regex_url_inicial(url)],
        "bloquear": list(BLOQUEIOS.get(reg, ())),
        "resumo": ", ".join(hosts) if hosts else "nenhum domínio",
    }


def permite(url, limites):
    """O que a regra de main_frame deixa abrir. Bloqueio ganha do domínio."""
    for rx in limites["bloquear"]:
        if re.search(rx, url):
            return False
    return any(re.search(rx, url) for rx in limites["permitir"])


def _acao_voltar():
    """Página da extensão, não a URL do tile.

    Um redirect direto de https para o http://127.0.0.1 do PhET o Edge recusa.
    ficou.html (página da extensão) devolve a criança ao tile. A regra não casa
    chrome-extension://, senão ela redirecionaria a si mesma.
    """
    return {"type": "redirect", "redirect": {"extensionPath": "/ficou.html"}}


def regras_dnr(limites):
    """Regras static do declarativeNetRequest, só main_frame.

    A de prioridade 1 manda qualquer outra navegação http(s) para ficou.html,
    que volta ao tile. As de permitir têm prioridade maior. As de bloquear
    (doação, jogos-divertidos) ganham das duas. Iframe e recurso não entram.
    """
    regras = [{
        "id": 1,
        "priority": 1,
        "action": _acao_voltar(),
        "condition": {"regexFilter": r"^https?://", "resourceTypes": ["main_frame"]},
    }]
    n = 2
    for rx in limites["permitir"]:
        regras.append({
            "id": n,
            "priority": 10,
            "action": {"type": "allow"},
            "condition": {"regexFilter": rx, "resourceTypes": ["main_frame"]},
        })
        n += 1
    for rx in limites["bloquear"]:
        regras.append({
            "id": n,
            "priority": 20,
            "action": _acao_voltar(),
            "condition": {"regexFilter": rx, "resourceTypes": ["main_frame"]},
        })
        n += 1
    return regras


def html_ficou(inicio):
    """Página mínima: o link não abre, e a janela volta ao tile.

    O script fica em ficou.js. Página de extensão (MV3) não roda script no HTML.
    """
    href = html.escape(inicio, quote=True)
    return (
        "<!doctype html><meta charset=\"utf-8\"><title>Esse link não abre</title>"
        "<style>body{font-family:sans-serif;background:#0f172a;color:#f8fafc;"
        "display:flex;min-height:100vh;align-items:center;justify-content:center;"
        "text-align:center;font-size:1.4rem}a{color:#fde047}</style>"
        "<p>Esse link não abre aqui.<br><a id=\"voltar\" href=\"%s\">Voltar</a></p>"
        "<script src=\"ficou.js\"></script>\n"
    ) % href


def js_ficou(inicio):
    return "location.replace(%s);\n" % json.dumps(inicio)


def versao_da_extensao(regras):
    """Muda quando as regras mudam, para o Edge recompilar o ruleset (0–65535)."""
    n = zlib.crc32(json.dumps(regras, ensure_ascii=False, sort_keys=True).encode()) & 0xFFFFFFFF
    return f"1.{(n >> 16) & 0xFFFF}.{n & 0xFFFF}"


def completar_manifesto(base, regras):
    """Manifest da cópia: o CSS de origem mais o limite deste tile."""
    manifesto = dict(base)
    manifesto["version"] = versao_da_extensao(regras)
    manifesto["description"] = (
        "Esconde o que não é para a criança e limita a navegação de topo ao site aberto."
    )
    manifesto["permissions"] = ["declarativeNetRequest"]
    manifesto["host_permissions"] = ["<all_urls>"]
    manifesto["declarative_net_request"] = {
        "rule_resources": [{"id": "limites", "enabled": True, "path": "regras.json"}]
    }
    scripts = list(manifesto.get("content_scripts") or [])
    scripts.append({
        "matches": ["http://*/*", "https://*/*"],
        "js": ["guarda.js"],
        "run_at": "document_start",
        "world": "MAIN",
        "all_frames": True,
        "match_about_blank": True,
    })
    manifesto["content_scripts"] = scripts
    manifesto["web_accessible_resources"] = [{
        "resources": ["ficou.html", "ficou.js"],
        "matches": ["<all_urls>"],
    }]
    return manifesto


def _gravar_json(caminho, dados):
    with open(caminho, "w", encoding="utf-8") as handle:
        json.dump(dados, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _gravar_guarda(destino, limites, modelo):
    with open(modelo, encoding="utf-8") as handle:
        texto = handle.read()
    texto = texto.replace(
        "var BENI_REGEXES = [];",
        "var BENI_REGEXES = %s;" % json.dumps(limites["permitir"], ensure_ascii=False),
        1,
    )
    texto = texto.replace(
        "var BENI_BLOQUEIOS = [];",
        "var BENI_BLOQUEIOS = %s;" % json.dumps(limites["bloquear"], ensure_ascii=False),
        1,
    )
    if limites["permitir"] and "var BENI_REGEXES = [];" in texto:
        raise ValueError("modelo da guarda sem o marcador das regras")
    with open(destino, "w", encoding="utf-8") as handle:
        handle.write(texto)


def log_linux(texto):
    """Uma linha em ~/.cache/cozy-kids-launcher/beni-linux.log (sem caminho de casa)."""
    if not sys.platform.startswith("linux"):
        return
    try:
        pasta = os.path.join(os.path.expanduser("~"), ".cache", "cozy-kids-launcher")
        os.makedirs(pasta, exist_ok=True)
        with open(os.path.join(pasta, "beni-linux.log"), "a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")
    except OSError:
        pass


def preparar_extensao(destino, url, origem=EXTENSAO, firefox=False):
    """Copia a extensão para o cache e grava as regras deste tile. Devolve o caminho."""
    os.makedirs(destino, exist_ok=True)
    for nome in os.listdir(origem):
        src = os.path.join(origem, nome)
        if not os.path.isfile(src) or nome in ("regras.json", "guarda.js"):
            continue
        shutil.copy2(src, os.path.join(destino, nome))
    limites = limites_da_url(url)
    regras = regras_dnr(limites)
    _gravar_json(os.path.join(destino, "regras.json"), regras)
    with open(os.path.join(destino, "ficou.html"), "w", encoding="utf-8") as handle:
        handle.write(html_ficou(limites["inicio"]))
    with open(os.path.join(destino, "ficou.js"), "w", encoding="utf-8") as handle:
        handle.write(js_ficou(limites["inicio"]))
    _gravar_guarda(os.path.join(destino, "guarda.js"), limites, os.path.join(origem, "guarda.js"))
    with open(os.path.join(destino, "manifest.json"), encoding="utf-8") as handle:
        base = json.load(handle)
    manifesto = completar_manifesto(base, regras)
    if firefox:
        # id estável: a extensão temporária é reinstalada a cada abertura
        manifesto["browser_specific_settings"] = {
            "gecko": {"id": ID_EXTENSAO_FIREFOX, "strict_min_version": "128.0"},
        }
    _gravar_json(os.path.join(destino, "manifest.json"), manifesto)
    return destino
