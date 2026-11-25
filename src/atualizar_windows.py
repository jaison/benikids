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
MANIFESTO = "manifesto-arquivos.txt"
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
                    os.path.join("app", "server.py"), os.path.join("app", "version"),
                    os.path.join("app", MANIFESTO)):
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


OCIOSO_PARA_ATUALIZAR = 20 * 60  # segundos sem ninguém mexer no computador


def hora_de_atualizar(pronta, app_aberto, ocioso):
    """Instalar já uma versão baixada, sem esperar o Benikids ser reaberto (ele pode
    ficar dias aberto): só com o menu parado, nenhum app aberto e ninguém mexendo."""
    return bool(pronta) and not app_aberto and ocioso >= OCIOSO_PARA_ATUALIZAR


# Dentro da pasta do app, mas não são arquivos da versão: capas baixadas pelo itch,
# o Python embutido, a config se um dia cair aqui, e logs. Na dúvida, não apaga.
_PROTEGIDOS_PREFIXO = ("themes/covers", "python")
_PROTEGIDOS_NOME = ("config.json", "config.json.bak", "config.json.novo")
_LER_AGORA = object()


def _normalizar_relativo(relativo):
    """Caminho relativo seguro (sem absoluto, sem '..'), com barras '/', ou None."""
    if not isinstance(relativo, str):
        return None
    rel = relativo.replace("\\", "/").strip()
    if not rel or rel.startswith(("/", "#")) or (len(rel) >= 2 and rel[1] == ":"):
        return None
    partes = rel.split("/")
    if any(parte in ("", ".", "..") for parte in partes):
        return None
    return "/".join(partes)


def protegido(relativo):
    """Dado do usuário, ou algo que não é arquivo do app. Não apagar."""
    rel = _normalizar_relativo(relativo)
    if rel is None:
        return True
    if rel == MANIFESTO or rel.endswith(".log"):
        return True
    baixo = rel.casefold()
    if baixo in _PROTEGIDOS_NOME or baixo.split("/")[-1] in _PROTEGIDOS_NOME:
        return True
    for prefixo in _PROTEGIDOS_PREFIXO:
        if baixo == prefixo or baixo.startswith(prefixo + "/"):
            return True
    return False


def alvo_dentro(destino, relativo):
    """Caminho absoluto do arquivo, só se continuar dentro de destino."""
    rel = _normalizar_relativo(relativo)
    if rel is None:
        return None
    destino = os.path.abspath(destino)
    alvo = os.path.abspath(os.path.join(destino, *rel.split("/")))
    if not alvo.startswith(destino + os.sep):
        return None
    return alvo


def ler_manifesto(pasta):
    """Conjunto de caminhos do manifesto, ou None se a pasta não tem a lista.

    Linha inválida é ignorada. Arquivo vazio devolve conjunto vazio (a versão
    disse que não tinha arquivos), diferente de None (instalação antiga, sem lista).
    """
    try:
        with open(os.path.join(pasta, MANIFESTO), encoding="utf-8") as f:
            texto = f.read(2 * 1024 * 1024)
    except (OSError, UnicodeError):
        return None
    caminhos = set()
    for linha in texto.splitlines():
        rel = _normalizar_relativo(linha)
        if rel is not None and not protegido(rel):
            caminhos.add(rel)
    return caminhos


def gravar_manifesto(pasta):
    """Grava a lista dos arquivos do app (a que o pacote do Windows leva)."""
    pasta = os.path.abspath(pasta)
    arquivos = []
    for raiz, pastas, nomes in os.walk(pasta):
        pastas[:] = [nome for nome in pastas if nome != "__pycache__"]
        for nome in nomes:
            if nome == MANIFESTO:
                continue
            caminho = os.path.join(raiz, nome)
            if os.path.islink(caminho) or not os.path.isfile(caminho):
                continue
            rel = _normalizar_relativo(os.path.relpath(caminho, pasta).replace(os.sep, "/"))
            if rel is None or protegido(rel):
                continue
            arquivos.append(rel)
    arquivos.sort()
    destino = os.path.join(pasta, MANIFESTO)
    temp = destino + ".novo"
    with open(temp, "w", encoding="utf-8", newline="\n") as f:
        if arquivos:
            f.write("\n".join(arquivos) + "\n")
    os.replace(temp, destino)
    return arquivos


def _apagar_pycache(destino, log):
    """Apaga pastas __pycache__ dentro do app. Não entra em capas nem no Python."""
    destino = os.path.abspath(destino)
    apagadas = 0
    for raiz, pastas, _nomes in os.walk(destino):
        rel_raiz = os.path.relpath(raiz, destino).replace(os.sep, "/")
        if rel_raiz == ".":
            rel_raiz = ""
        ficar = []
        for nome in pastas:
            rel = f"{rel_raiz}/{nome}" if rel_raiz else nome
            if protegido(rel):
                continue
            if nome == "__pycache__":
                alvo = os.path.join(raiz, nome)
                try:
                    shutil.rmtree(alvo)
                    apagadas += 1
                except OSError as erro:
                    log(f"limpeza: não consegui apagar {rel} ({erro})")
                continue
            ficar.append(nome)
        pastas[:] = ficar
    if apagadas == 1:
        log("limpeza: apaguei 1 pasta __pycache__ velha")
    elif apagadas:
        log(f"limpeza: apaguei {apagadas} pastas __pycache__ velhas")
    else:
        log("limpeza: nenhum __pycache__ velho")
    return apagadas


def limpar_arquivos_velhos(destino, pasta_nova, anterior=_LER_AGORA, log=None):
    """Apaga do app instalado o que saiu desta versão, e os __pycache__ velhos.

    anterior é a lista lida ANTES de copiar o pacote por cima (senão a lista nova
    esconde a antiga). Passe None se a versão anterior não tinha lista: aí apaga
    só os __pycache__. Sem o argumento, a lista é lida agora. Sem lista no pacote
    novo, também apaga só os __pycache__. Nunca apaga fora de destino, nem capas,
    config, logs ou o Python embutido. Arquivo em uso fica para a próxima vez;
    a instalação segue.
    """
    log = log or (lambda _texto: None)
    destino = os.path.abspath(destino)
    if anterior is _LER_AGORA:
        anterior = ler_manifesto(destino)
    novo = ler_manifesto(pasta_nova) if pasta_nova else None
    apagados = []
    if novo is None:
        log("limpeza: o pacote novo não trouxe a lista de arquivos; apaguei só os __pycache__")
    elif anterior is None:
        log("limpeza: sem lista da versão anterior; apaguei só os __pycache__")
    else:
        novas = {caminho.casefold() for caminho in novo}
        for rel in sorted(anterior):
            if rel.casefold() in novas or protegido(rel):
                continue
            alvo = alvo_dentro(destino, rel)
            if alvo is None or os.path.islink(alvo) or not os.path.isfile(alvo):
                if alvo is not None and os.path.lexists(alvo):
                    log(f"limpeza: deixei {rel}")
                continue
            try:
                os.remove(alvo)
            except OSError as erro:
                log(f"limpeza: não consegui apagar {rel} ({erro})")
                continue
            apagados.append(rel)
        if apagados:
            mostra = ", ".join(apagados[:8])
            if len(apagados) > 8:
                mostra += f" e mais {len(apagados) - 8}"
            palavra = "arquivo que saiu" if len(apagados) == 1 else "arquivos que saíram"
            log(f"limpeza: apaguei {len(apagados)} {palavra} desta versão: {mostra}")
        else:
            log("limpeza: nenhum arquivo velho para apagar")
    _apagar_pycache(destino, log)
    return apagados


def aplicar_e_sair(raiz_pacote, log=print):
    """Chama o instalador da versão nova (com o Python dela) e devolve True: o iniciador
    deve sair logo, para o instalador poder trocar os arquivos, apagar os que saíram
    da versão e abrir o Benikids de novo."""
    pythonw = os.path.join(raiz_pacote, "python", "pythonw.exe")
    argv = [pythonw, os.path.join(raiz_pacote, "instalar_windows.py"), "--atualizacao", str(os.getpid())]
    try:
        # fora do job da sessão: o iniciador sai logo e o instalador precisa continuar
        from queda_windows import popen_fora_do_job

        popen_fora_do_job(argv, cwd=raiz_pacote, close_fds=True, creationflags=SEM_CONSOLE)
    except OSError as erro:
        log(f"atualização: não deu para abrir o instalador ({erro})")
        return False
    log(f"atualização: instalador de {raiz_pacote} aberto")
    return True


def estado_para_os_pais(app_root, base=None):
    """O que mostrar na área dos pais: versão já baixada esperando instalar, a última
    procura e se alguma versão falhou ao instalar."""
    base = base or pasta()
    estado = _estado(base)
    pronta = _pronta(base)
    nova, atual = (semver(pronta[0]) if pronta else None), semver(versao_instalada(app_root))
    baixada = pronta[0] if pronta and nova and (not atual or nova > atual) else None
    ultima = estado.get("verificado_em")
    try:
        ultima = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(float(ultima))) if ultima is not None else None
    except (TypeError, ValueError, OverflowError, OSError):
        ultima = None
    falhou = estado.get("falhou")
    return {
        "baixada": baixada,
        "ultimaVerificacao": ultima,
        "erro": f"A versão {falhou} não conseguiu instalar." if isinstance(falhou, str) and falhou else None,
    }


def marcar_falha(versao, base=None):
    _gravar_estado(base or pasta(), falhou=versao)


def limpar(base=None):
    """Apaga a versão baixada (chamado pelo iniciador, depois que ela já foi instalada)."""
    base = base or pasta()
    shutil.rmtree(os.path.join(base, "pronta"), ignore_errors=True)
    _gravar_estado(base, pronta=None, pacote=None, falhou=None)
