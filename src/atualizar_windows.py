"""Atualização automática do Benikids no Windows.

Como no Linux (beni/sistema/beni-atualizar), só Releases do GitHub contam (tag vX.Y.Z,
não rascunho nem pré-release). O pacote do Windows vai anexado à Release pelo CI
(Benikids-Windows.zip + .sha256).

- verificar(): em segundo plano (thread do iniciador), no máximo a cada 6 h:
  procura uma Release mais nova, baixa o zip, confere o SHA-256 e extrai em
  %LOCALAPPDATA%\\Benikids\\atualizacao\\pronta. O botão "Ver atualizações"
  chama com forcar=True e ignora as 6 h (mas não o mínimo de 1 minuto).
- pendente(): na próxima vez que o Benikids abre, ANTES de subir o servidor e o menu,
  o iniciador vê a versão pronta e chama aplicar_e_sair(): o instalador da versão nova
  roda com o Python do próprio pacote novo (o Python instalado está em uso pelo
  iniciador), espera o iniciador sair, guarda uma cópia, instala por cima e abre o
  Benikids de novo. Se algo falhar, volta a cópia.
"""

import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile

REPO = "jaison/benikids"
ASSET = "Benikids-Windows.zip"
SEMVER = re.compile(r"^v?([0-9]+)\.([0-9]+)\.([0-9]+)$")
UA = {"User-Agent": "benikids-atualizador-windows", "Accept": "application/vnd.github+json"}
# 6 h: cerca de 4 consultas por dia em cada computador. A API do GitHub, sem
# token, aceita 60 por hora por endereço de internet. O Linux já consulta de
# hora em hora; 6 h no Windows continua folgado mesmo com vários notebooks
# saindo pelo mesmo endereço. O botão dos pais tem um teto à parte (1 minuto).
INTERVALO = 6 * 3600
MINIMO_ENTRE_VERIFICACOES = 60
REPETIR_SEM_REDE = 30 * 60  # sem internet: tenta de novo em meia hora, não em 6 h
AGORA_SEGUNDOS = 2 * 60  # "verificado agora" se a procura acabou de acontecer
# O botão, dentro de 1 minuto, não procura de novo. Aí a frase não pode
# dizer "agora": é o resultado de antes.
SEM_CONSOLE = 0x08000000
_trava = threading.Lock()


class FalhaDeRede(RuntimeError):
    """Não deu para falar com o GitHub (sem internet, tempo esgotado, limite)."""


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


def _segundos_desde(estado, chave, agora):
    valor = estado.get(chave)
    if valor is None:
        return None
    try:
        delta = agora - float(valor)
    except (TypeError, ValueError):
        return None
    return delta


def _procura_incompleta(estado):
    """True se a última tentativa começou e não chegou a gravar verificado_em.

    Nesse meio (rede caiu, disco cheio, leitura cortada) a versão instalada
    não pode ser anunciada como a mais nova: a procura nem terminou.
    """
    try:
        tentado = float(estado.get("tentado_em"))
    except (TypeError, ValueError):
        return False
    verificado = estado.get("verificado_em")
    if verificado is None:
        return True
    try:
        return tentado > float(verificado)
    except (TypeError, ValueError):
        return True


def _ler_url(abrir, url, timeout, limite):
    try:
        with abrir(url, timeout=timeout) as resposta:
            return resposta.read(limite)
    except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as erro:
        raise FalhaDeRede("sem resposta") from erro


def verificar(app_root, base=None, abrir=_abrir, agora=None, repo=REPO, forcar=False):
    """Procura e baixa uma versão nova. Devolve a versão que ficou pronta, ou None.

    Sem forcar, espera INTERVALO desde a última procura que chegou ao GitHub
    (ou REPETIR_SEM_REDE, se a última nem chegou). Com forcar, ignora essas
    esperas: é o botão "Ver atualizações". Nos dois casos, no máximo uma
    procura por minuto.
    """
    with _trava:
        return _verificar(app_root, base, abrir, agora, repo, forcar)


def _verificar(app_root, base, abrir, agora, repo, forcar):
    base = base or pasta()
    agora = agora if agora is not None else time.time()
    estado = _estado(base)
    tentativa = _segundos_desde(estado, "tentado_em", agora)
    if tentativa is not None and 0 <= tentativa < MINIMO_ENTRE_VERIFICACOES:
        return None
    if not forcar:
        # Rede ou procura cortada no meio: tenta de novo em meia hora.
        # verificado_em antigo não pode segurar as 6 h.
        if estado.get("sem_rede") or _procura_incompleta(estado):
            if tentativa is not None and 0 <= tentativa < REPETIR_SEM_REDE:
                return None
        else:
            verificada = _segundos_desde(estado, "verificado_em", agora)
            if verificada is not None and 0 <= verificada < INTERVALO:
                return None
    # Não apaga sem_rede aqui. Se a procura quebrar no meio, o estado antigo
    # (ou o except abaixo) continua dizendo que esta tentativa não terminou.
    _gravar_estado(base, tentado_em=agora)
    try:
        return _procurar(app_root, base, abrir, agora, repo)
    except FalhaDeRede:
        _gravar_estado(base, sem_rede=True, erro_download=None)
        raise
    except Exception:
        if not _estado(base).get("erro_download"):
            _gravar_estado(base, sem_rede=False, erro_download=True)
        raise


def _procurar(app_root, base, abrir, agora, repo):
    atual = versao_instalada(app_root)
    bruto = _ler_url(abrir, f"https://api.github.com/repos/{repo}/releases/latest", 30, 2 * 1024 * 1024)
    try:
        release = json.loads(bruto.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as erro:
        raise FalhaDeRede("resposta inválida") from erro
    if not isinstance(release, dict) or (release.get("message") and not release.get("tag_name")):
        raise FalhaDeRede("resposta sem release")
    achada = release_nova(release, atual)
    if not achada:
        _gravar_estado(base, verificado_em=agora, sem_rede=False, erro_download=None)
        return None
    versao, url, url_sha = achada
    pronta = _pronta(base)
    if pronta and semver(pronta[0]) == semver(versao):
        _gravar_estado(base, verificado_em=agora, sem_rede=False, erro_download=None)
        return None  # já baixada
    esperado = _ler_url(abrir, url_sha, 30, 200).decode("ascii", "replace").split()[0].lower()
    trabalho = os.path.join(base, "baixando")
    shutil.rmtree(trabalho, ignore_errors=True)
    os.makedirs(trabalho)
    zip_local = os.path.join(trabalho, ASSET)
    soma = hashlib.sha256()
    try:
        with abrir(url, timeout=600) as resposta, open(zip_local, "wb") as saida:
            while True:
                bloco = resposta.read(1024 * 1024)
                if not bloco:
                    break
                soma.update(bloco)
                saida.write(bloco)
    except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as erro:
        shutil.rmtree(trabalho, ignore_errors=True)
        raise FalhaDeRede("sem resposta") from erro
    except OSError:
        shutil.rmtree(trabalho, ignore_errors=True)
        _gravar_estado(base, sem_rede=False, erro_download=True)
        raise
    if soma.hexdigest() != esperado:
        shutil.rmtree(trabalho, ignore_errors=True)
        _gravar_estado(base, verificado_em=agora, sem_rede=False, erro_download=True)
        raise RuntimeError("SHA-256 do pacote não confere")
    try:
        raiz = extrair_com_cuidado(zip_local, os.path.join(trabalho, "pacote"))
        conferir_pacote(raiz, versao)
    except (RuntimeError, OSError):
        shutil.rmtree(trabalho, ignore_errors=True)
        _gravar_estado(base, verificado_em=agora, sem_rede=False, erro_download=True)
        raise
    os.unlink(zip_local)
    destino = os.path.join(base, "pronta")
    shutil.rmtree(destino, ignore_errors=True)
    os.replace(trabalho, destino)
    _gravar_estado(base, pronta=versao, pacote=os.path.relpath(raiz, trabalho),
                   verificado_em=agora, sem_rede=False, erro_download=None)
    return versao


def _frase_relogio(epoch, agora):
    """'Às HH:MM' (no mesmo dia) ou 'Em DD/MM/AAAA às HH:MM'. Nunca 'agora'."""
    try:
        momento = time.localtime(float(epoch))
        hoje = time.localtime(agora)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    if momento[:3] == hoje[:3]:
        return time.strftime("Às %H:%M", momento)
    return time.strftime("Em %d/%m/%Y às %H:%M", momento)


def _frase_quando(epoch, agora, resultado_antigo=False):
    """'agora', 'há poucos segundos', 'às HH:MM' ou 'em DD/MM/AAAA às HH:MM'."""
    delta = agora - float(epoch)
    if 0 <= delta < AGORA_SEGUNDOS:
        if resultado_antigo:
            return "há poucos segundos"
        return "agora"
    hora = time.strftime("%H:%M", time.localtime(epoch))
    if time.localtime(epoch)[:3] == time.localtime(agora)[:3]:
        return f"às {hora}"
    return time.strftime("em %d/%m/%Y às %H:%M", time.localtime(epoch))


def procura_nao_rodou(base, tentado_antes):
    """True se o botão pediu e o mínimo de 1 minuto segurou a procura.

    tentado_antes é o valor lido antes da chamada. Se o arquivo não mudou,
    esta tentativa não falou com o GitHub.
    """
    if tentado_antes is None:
        return False
    return _estado(base).get("tentado_em") == tentado_antes


def _texto_sem_rede(estado, agora):
    """A falha fica com a hora da tentativa, para não parecer que é agora."""
    frase = "Não deu para verificar (sem internet?)."
    quando = _frase_relogio(estado.get("tentado_em"), agora)
    if not quando:
        return frase
    return f"{quando} não deu para verificar (sem internet?)."


def mensagem_para_os_pais(app_root, base=None, agora=None, resultado_antigo=False):
    """(texto, tipo) honesto para a área dos pais. tipo: success, error ou empty.

    Não diz que está em dia se a última procura deu erro ou já passou do intervalo.
    resultado_antigo: o botão não procurou de novo (mínimo de 1 minuto). A frase
    conta o resultado de antes, sem dizer que esta tentativa verificou agora.
    """
    base = base or pasta()
    agora = agora if agora is not None else time.time()
    estado = _estado(base)
    pronta = _pronta(base)
    atual = versao_instalada(app_root) or "?"
    nova = semver(pronta[0]) if pronta else None
    instalada = semver(atual)
    baixada = pronta[0] if pronta and nova and (not instalada or nova > instalada) else None
    falhou = estado.get("falhou")
    aviso = f" A versão {falhou} não conseguiu instalar." if isinstance(falhou, str) and falhou else ""
    if baixada and isinstance(falhou, str) and falhou == baixada:
        # pendente() recusa esta versão: prometer a instalação engana o pai
        return f"A versão {falhou} não conseguiu instalar.", "error"
    if baixada:
        texto = (f"Versão {baixada} baixada; vai ser instalada quando o computador "
                 "ficar parado no menu.")
        return texto + aviso, "error" if aviso else "success"
    if estado.get("sem_rede") or (_procura_incompleta(estado) and not estado.get("erro_download")):
        return _texto_sem_rede(estado, agora), "error"
    if estado.get("erro_download") or _procura_incompleta(estado):
        return "Não deu para baixar a atualização.", "error"
    ultima = _segundos_desde(estado, "verificado_em", agora)
    if ultima is None:
        return "Ainda não procurei se há uma versão nova. Toque em Ver atualizações." + aviso, "empty"
    quando = _frase_quando(agora - ultima, agora, resultado_antigo=resultado_antigo)
    if ultima < 0 or ultima >= INTERVALO:
        texto = f"A última verificação foi {quando}. Toque em Ver atualizações para procurar de novo."
        return texto + aviso, "empty"
    texto = f"Você tem a versão mais nova ({atual}). Verificado {quando}."
    return texto + aviso, "error" if aviso else "success"


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


def aplicar_e_sair(raiz_pacote, log=print):
    """Chama o instalador da versão nova (com o Python dela) e devolve True: o iniciador
    deve sair logo, para o instalador poder trocar os arquivos e abrir o Benikids de novo."""
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


def estado_para_os_pais(app_root, base=None, agora=None, resultado_antigo=False):
    """O que mostrar na área dos pais: versão já baixada esperando instalar, a última
    procura, se alguma versão falhou ao instalar, e o texto honesto da tela."""
    base = base or pasta()
    agora = agora if agora is not None else time.time()
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
    texto, tipo = mensagem_para_os_pais(app_root, base, agora, resultado_antigo=resultado_antigo)
    return {
        "baixada": baixada,
        "ultimaVerificacao": ultima,
        "erro": f"A versão {falhou} não conseguiu instalar." if isinstance(falhou, str) and falhou else None,
        "semRede": bool(estado.get("sem_rede")),
        "texto": texto,
        "tipo": tipo,
    }


def marcar_falha(versao, base=None):
    _gravar_estado(base or pasta(), falhou=versao)


def limpar(base=None):
    """Apaga a versão baixada (chamado pelo iniciador, depois que ela já foi instalada)."""
    base = base or pasta()
    shutil.rmtree(os.path.join(base, "pronta"), ignore_errors=True)
    _gravar_estado(base, pronta=None, pacote=None, falhou=None)
