"""Atualização automática do Benikids no Windows.

Como no Linux (beni/sistema/beni-atualizar), só Releases do GitHub contam (tag vX.Y.Z,
não rascunho nem pré-release). O pacote do Windows vai anexado à Release pelo CI
(Benikids-Windows.zip + .sha256).

- verificar(): no máximo uma vez por dia, em segundo plano (thread do iniciador):
  procura uma Release mais nova, baixa o zip, confere o SHA-256 e extrai em
  %LOCALAPPDATA%\\Benikids\\atualizacao\\pronta.
- pendente(): na próxima vez que o Benikids abre, ANTES de subir o servidor e o menu,
  o iniciador vê a versão pronta e chama aplicar_e_sair(): o instalador da versão nova
  roda com o Python do próprio pacote novo (o Python instalado está em uso pelo
  iniciador), espera o iniciador sair, guarda uma cópia, instala por cima e abre o
  Benikids de novo. Se algo falhar, volta a cópia.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
import zipfile

REPO = "jaison/benikids"
ASSET = "Benikids-Windows.zip"
SEMVER = re.compile(r"^v?([0-9]+)\.([0-9]+)\.([0-9]+)$")
UA = {"User-Agent": "benikids-atualizador-windows", "Accept": "application/vnd.github+json"}
INTERVALO = 20 * 3600  # procura de novo depois de 20 h
SEM_CONSOLE = 0x08000000


def pasta(raiz=None):
    raiz = raiz or os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(raiz, "Benikids", "atualizacao")


def semver(valor):
    m = SEMVER.match((valor or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def versao_instalada(app_root):
    try:
        with open(os.path.join(app_root, "version"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _estado(base):
    try:
        with open(os.path.join(base, "estado.json"), encoding="utf-8") as f:
            dados = json.load(f)
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_estado(base, **mudancas):
    dados = _estado(base)
    dados.update(mudancas)
    os.makedirs(base, exist_ok=True)
    temp = os.path.join(base, "estado.json.novo")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False)
    os.replace(temp, os.path.join(base, "estado.json"))


def _abrir(url, timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)


def release_nova(release, atual):
    """(versão, url do zip, url do .sha256) se a Release é mais nova e tem o pacote."""
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        return None
    versao = str(release.get("tag_name", "")).lstrip("v")
    nova, velha = semver(versao), semver(atual)
    if not nova or (velha and nova <= velha):
        return None
    assets = {a.get("name"): a.get("browser_download_url") for a in release.get("assets") or []
              if isinstance(a, dict)}
    url, url_sha = assets.get(ASSET), assets.get(ASSET + ".sha256")
    if not (url and url_sha and url.startswith("https://") and url_sha.startswith("https://")):
        return None
    return versao, url, url_sha


def extrair_com_cuidado(arquivo, destino):
    """Extrai o zip sem deixar caminho absoluto nem '..' sair do destino. Devolve a pasta
    do pacote (a que tem instalar_windows.py)."""
    destino = os.path.abspath(destino)
    with zipfile.ZipFile(arquivo) as z:
        for nome in z.namelist():
            alvo = os.path.abspath(os.path.join(destino, nome))
            if not alvo.startswith(destino + os.sep) and alvo != destino:
                raise RuntimeError(f"caminho perigoso no pacote: {nome}")
        z.extractall(destino)
    for raiz, _pastas, arquivos in os.walk(destino):
        if "instalar_windows.py" in arquivos and raiz[len(destino):].count(os.sep) <= 2:
            return raiz
    raise RuntimeError("pacote sem instalar_windows.py")


def conferir_pacote(raiz, versao):
    for preciso in ("instalar_windows.py", os.path.join("python", "pythonw.exe"),
                    os.path.join("app", "server.py"), os.path.join("app", "version")):
        if not os.path.exists(os.path.join(raiz, preciso)):
            raise RuntimeError(f"pacote incompleto: falta {preciso}")
    with open(os.path.join(raiz, "app", "version"), encoding="utf-8") as f:
        dentro = f.read().strip()
    if semver(dentro) != semver(versao):
        raise RuntimeError(f"versão do pacote ({dentro}) não bate com a tag ({versao})")


def verificar(app_root, base=None, abrir=_abrir, agora=None, repo=REPO):
    """Procura e baixa uma versão nova. Devolve a versão que ficou pronta, ou None."""
    base = base or pasta()
    agora = agora if agora is not None else time.time()
    estado = _estado(base)
    ultima = estado.get("verificado_em")
    if ultima is not None and 0 <= agora - float(ultima) < INTERVALO:
        return None
    _gravar_estado(base, verificado_em=agora)
    atual = versao_instalada(app_root)
    with abrir(f"https://api.github.com/repos/{repo}/releases/latest") as resposta:
        release = json.loads(resposta.read(2 * 1024 * 1024).decode("utf-8"))
    achada = release_nova(release, atual)
    if not achada:
        return None
    versao, url, url_sha = achada
    pronta = _pronta(base)
    if pronta and semver(pronta[0]) == semver(versao):
        return None  # já baixada
    with abrir(url_sha) as resposta:
        esperado = resposta.read(200).decode("ascii", "replace").split()[0].lower()
    trabalho = os.path.join(base, "baixando")
    shutil.rmtree(trabalho, ignore_errors=True)
    os.makedirs(trabalho)
    zip_local = os.path.join(trabalho, ASSET)
    soma = hashlib.sha256()
    with abrir(url, timeout=600) as resposta, open(zip_local, "wb") as saida:
        while True:
            bloco = resposta.read(1024 * 1024)
            if not bloco:
                break
            soma.update(bloco)
            saida.write(bloco)
    if soma.hexdigest() != esperado:
        shutil.rmtree(trabalho, ignore_errors=True)
        raise RuntimeError("SHA-256 do pacote não confere")
    raiz = extrair_com_cuidado(zip_local, os.path.join(trabalho, "pacote"))
    conferir_pacote(raiz, versao)
    os.unlink(zip_local)
    destino = os.path.join(base, "pronta")
    shutil.rmtree(destino, ignore_errors=True)
    os.replace(trabalho, destino)
    _gravar_estado(base, pronta=versao, pacote=os.path.relpath(raiz, trabalho))
    return versao


def _pronta(base):
    estado = _estado(base)
    versao, relativo = estado.get("pronta"), estado.get("pacote")
    if not versao or not relativo:
        return None
    raiz = os.path.normpath(os.path.join(base, "pronta", relativo))
    if not raiz.startswith(os.path.join(base, "pronta")) or not os.path.isfile(os.path.join(raiz, "instalar_windows.py")):
        return None
    return versao, raiz


def pendente(app_root, base=None):
    """(versão, pasta do pacote) se há uma versão mais nova baixada e conferida."""
    base = base or pasta()
    pronta = _pronta(base)
    if not pronta:
        return None
    nova, atual = semver(pronta[0]), semver(versao_instalada(app_root))
    if not nova or (atual and nova <= atual):
        limpar(base)  # já instalada (o instalador não apaga a pasta de onde roda)
        return None
    if _estado(base).get("falhou") == pronta[0]:
        return None  # esta versão já falhou ao instalar: não tenta a cada login
    return pronta


def aplicar_e_sair(raiz_pacote, log=print):
    """Chama o instalador da versão nova (com o Python dela) e devolve True: o iniciador
    deve sair logo, para o instalador poder trocar os arquivos e abrir o Benikids de novo."""
    pythonw = os.path.join(raiz_pacote, "python", "pythonw.exe")
    argv = [pythonw, os.path.join(raiz_pacote, "instalar_windows.py"), "--atualizacao", str(os.getpid())]
    try:
        subprocess.Popen(argv, cwd=raiz_pacote, close_fds=True, creationflags=SEM_CONSOLE)
    except OSError as erro:
        log(f"atualização: não deu para abrir o instalador ({erro})")
        return False
    log(f"atualização: instalador de {raiz_pacote} aberto")
    return True


def marcar_falha(versao, base=None):
    _gravar_estado(base or pasta(), falhou=versao)


def limpar(base=None):
    """Apaga a versão baixada (chamado pelo iniciador, depois que ela já foi instalada)."""
    base = base or pasta()
    shutil.rmtree(os.path.join(base, "pronta"), ignore_errors=True)
    _gravar_estado(base, pronta=None, pacote=None, falhou=None)
