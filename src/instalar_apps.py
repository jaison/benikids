"""Instala (pelo winget ou, para apps de um .exe só, do site do autor) os apps do catálogo do Windows que ainda faltam.

Mostra uma janela simples com o andamento de cada app. Chamado pelo instalador do
Benikids e pela área dos pais. Uso: pythonw instalar_apps.py [id ...]
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import catalogo_windows  # noqa: E402
import marca_tk as marca  # noqa: E402

SEM_CONSOLE = 0x08000000
ICONES = {"espera": "⏳", "instalando": "⬇️", "ok": "✅", "ja": "✅", "erro": "⚠️"}


def winget():
    local = os.environ.get("LOCALAPPDATA", "")
    caminho = os.path.join(local, "Microsoft", "WindowsApps", "winget.exe")
    return caminho if os.path.isfile(caminho) else "winget"


def _memoria():
    """Apps que já pediram a senha de um administrador numa instalação "por usuário"."""
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Benikids", "pedem-senha.json")


def pedem_senha(caminho=None):
    try:
        with open(caminho or _memoria(), encoding="utf-8") as f:
            ids = json.load(f)
        return {i for i in ids if isinstance(i, str)}
    except (OSError, ValueError, TypeError):
        return set()


def lembrar_que_pede_senha(item_id, caminho=None):
    caminho = caminho or _memoria()
    ids = pedem_senha(caminho) | {item_id}
    try:
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(sorted(ids), f)
    except OSError:
        pass


def precisa_de_senha(item, ja_pediram=frozenset()):
    return item.get("escopo") == "machine" or item["id"] in ja_pediram


def pedido_de_senha_aberto():
    """Há uma janela do UAC (consent.exe) aberta agora?"""
    try:
        saida = subprocess.run(["tasklist", "/FI", "IMAGENAME eq consent.exe", "/NH"],
                               capture_output=True, text=True, creationflags=SEM_CONSOLE, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "consent.exe" in (saida or "").lower()


def instalar(item, ao_pedir_senha=None):
    """Roda o winget para um app "por usuário". Devolve (ok, texto).

    Os instaladores rodam com __COMPAT_LAYER=RunAsInvoker: um instalador que só pede
    administrador "por via das dúvidas" instala sem perguntar, e um que precisa mesmo
    falha em vez de travar a fila no UAC (aí ele vai para o lote com senha, no fim).
    Se mesmo assim o Windows abrir o UAC (ex.: o winget elevando um MSI), avisa por
    ao_pedir_senha, para a janela explicar e para da próxima vez ir direto ao lote.
    """
    argv = [
        winget(), "install", "--id", item["winget"], "--exact", "--silent",
        "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity",
    ]
    if item.get("escopo"):
        argv += ["--scope", item["escopo"]]
    env = dict(os.environ, __COMPAT_LAYER="RunAsInvoker")
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", env=env, creationflags=SEM_CONSOLE)
    except FileNotFoundError:
        return False, "winget não encontrado"
    pediu = threading.Event()

    def vigiar():
        while proc.poll() is None:
            if not pediu.is_set() and pedido_de_senha_aberto():
                pediu.set()
                if ao_pedir_senha:
                    ao_pedir_senha()
            time.sleep(2)

    threading.Thread(target=vigiar, daemon=True).start()
    try:
        saida, _ = proc.communicate(timeout=1800)
    except subprocess.TimeoutExpired:
        proc.kill()
        return False, "demorou demais"
    r = subprocess.CompletedProcess(argv, proc.returncode, saida, "")
    if catalogo_windows.localizar(item):
        return True, "instalado"
    fim = (r.stdout or r.stderr or "").strip().splitlines()
    return False, (fim[-1] if fim else f"código {r.returncode}")[:120]


SILENCIOSO = {
    # tipo do instalador → como rodar sem perguntas, para todos os usuários
    "msi": None,  # msiexec /i arquivo /qn
    "wix": None,
    "nullsoft": ["/S"],
    "inno": ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/ALLUSERS"],
    "burn": ["/quiet", "/norestart"],
}


def pacote(item):
    """O que identifica o instalador: dois apps com o mesmo baixam e instalam uma vez só."""
    return item.get("winget") or item.get("pagina") or item["id"]


def mais_novo_da_pagina(html, padrao):
    """Na listagem de uma pasta (ex.: cdn.kde.org/ci-builds), o instalador de número de
    build maior. padrao: regex com um grupo para o número."""
    import re

    melhores = sorted(((int(m.group(1)), m.group(0)) for m in re.finditer(padrao, html)), reverse=True)
    return melhores[0][1] if melhores else None


def baixar_da_pagina(item, destino, abrir=None):
    """Para apps cujo pacote no winget aponta para uma build que já sumiu (KDE): acha a
    build mais nova na própria pasta do KDE e baixa. Devolve o arquivo ou None."""
    import urllib.parse
    import urllib.request

    pagina = item.get("pagina", "")
    if not pagina.startswith("https://") or not item.get("padrao"):
        return None
    abrir = abrir or (lambda u: urllib.request.urlopen(u, timeout=600))
    try:
        with abrir(pagina) as resposta:
            html = resposta.read(4 * 1024 * 1024).decode("utf-8", "replace")
        nome = mais_novo_da_pagina(html, item["padrao"])
        if not nome or "/" in nome or "\\" in nome:
            return None
        with abrir(urllib.parse.urljoin(pagina, nome)) as resposta:
            dados = resposta.read(1024 * 1024 * 1024)
    except (OSError, ValueError):
        return None
    if not dados.startswith(b"MZ"):
        return None
    arquivo = os.path.join(destino, nome)
    try:
        with open(arquivo, "wb") as f:
            f.write(dados)
    except OSError:
        return None
    return arquivo


def baixar(item, pasta):
    """winget download (não precisa de administrador). Devolve o arquivo do instalador."""
    destino = os.path.join(pasta, item["id"])
    os.makedirs(destino, exist_ok=True)
    if not item.get("winget"):
        return baixar_da_pagina(item, destino)
    base = [
        winget(), "download", "--id", item["winget"], "--exact", "--download-directory", destino,
        "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity",
    ]
    tipo = ["--installer-type", item["instalador"]] if item.get("instalador") else []
    # primeiro o instalador "por máquina" do tipo que o script de administrador vai rodar;
    # manifestos sem "Scope" (ex.: Enigma) não passam no filtro --scope machine e o winget
    # responde 0x8a150010 (nenhum instalador aplicável), então tenta de novo sem ele
    for extra in (["--scope", "machine"] + tipo, tipo):
        try:
            subprocess.run(base + extra, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=SEM_CONSOLE, timeout=1800)
        except (OSError, subprocess.TimeoutExpired):
            return None
        arquivos = [os.path.join(destino, n) for n in os.listdir(destino)
                    if n.lower().endswith((".msi", ".exe"))]
        if arquivos:
            return max(arquivos, key=os.path.getmtime)
    # o winget aponta para uma build do KDE que já saiu do ar: a pasta do KDE tem a nova
    return baixar_da_pagina(item, destino) if item.get("pagina") else None


PASTA_DIRETOS = "Benikids Apps"  # em %LOCALAPPDATA%\\Programs: não precisa de administrador


def baixar_direto(item, raiz=None, abrir=None):
    """Apps de um .exe só, baixados do site do autor quando o winget não serve (ex.: os
    Quebra-cabeças de Simon Tatham, cujo pacote no winget ficou com o hash velho).
    Devolve (ok, texto)."""
    import urllib.request

    info = item.get("baixar") or {}
    url, arquivo = info.get("url", ""), info.get("arquivo", "")
    if not url.startswith("https://") or not arquivo or os.sep in arquivo or "/" in arquivo:
        return False, "sem endereço para baixar"
    raiz = raiz or os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")
    pasta = os.path.join(raiz, PASTA_DIRETOS)
    destino = os.path.join(pasta, arquivo)
    abrir = abrir or (lambda u: urllib.request.urlopen(u, timeout=120))
    try:
        os.makedirs(pasta, exist_ok=True)
        with abrir(url) as resposta:
            dados = resposta.read(64 * 1024 * 1024)
    except (OSError, ValueError) as erro:
        return False, f"não deu para baixar ({erro.__class__.__name__})"
    if len(dados) < 20 * 1024 or not dados.startswith(b"MZ"):
        return False, "o arquivo baixado não é um programa"
    temporario = destino + ".baixando"
    try:
        with open(temporario, "wb") as f:
            f.write(dados)
        os.replace(temporario, destino)
    except OSError:
        return False, "não deu para gravar o programa"
    return True, "instalado"


def tipo_do_instalador(item):
    """O tipo (msi, inno, nullsoft...) do catálogo ou, se faltar, o que o winget informa."""
    if item.get("instalador"):
        return item["instalador"]
    try:
        saida = subprocess.run(
            [winget(), "show", "--id", item["winget"], "--exact", "--scope", "machine",
             "--accept-source-agreements", "--disable-interactivity"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=SEM_CONSOLE, timeout=120).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""
    return ler_tipo(saida)


def ler_tipo(saida_do_show):
    for linha in saida_do_show.splitlines():
        chave, _, valor = linha.strip().partition(":")
        if chave.strip().lower() in ("installer type", "tipo de instalador"):
            return valor.strip().lower()
    return ""


def _ps(texto):
    return "'" + texto.replace("'", "''") + "'"


def dependencias(arquivo):
    """Instaladores que o winget download pôs em <pasta do app>\\Dependencies (ex.: VC++)."""
    pasta = os.path.join(os.path.dirname(arquivo), "Dependencies")
    achados = []
    for raiz, _pastas, nomes in os.walk(pasta):
        achados += [os.path.join(raiz, n) for n in sorted(nomes) if n.lower().endswith((".msi", ".exe"))]
    return achados


def _linha_instalar(rotulo, arquivo, tipo, logs, resultados):
    """Uma linha do PowerShell que instala sem perguntas e anota "rótulo|código"."""
    # -ArgumentList recebe UMA string: com um array, o PowerShell 5.1 põe aspas de novo
    # nos itens com espaço, e um caminho já entre aspas chega estragado ao msiexec
    # (1622 = não abriu o log; 1619 = não abriu o pacote)
    if tipo in ("msi", "wix") or arquivo.lower().endswith(".msi"):
        log = os.path.join(logs, f"{rotulo}.log")
        args = f'/i "{arquivo}" /qn /norestart ALLUSERS=1 /l*v "{log}"'
        comando = f"Start-Process msiexec.exe -Wait -PassThru -ArgumentList {_ps(args)}"
    else:
        args = " ".join(SILENCIOSO.get(tipo) or ["/S"])
        comando = f"Start-Process -FilePath {_ps(arquivo)} -Wait -PassThru -ArgumentList {_ps(args)}"
    return (f"try {{ $p = {comando}; $c = $p.ExitCode }} catch {{ $c = 'erro: ' + $_.Exception.Message }}; "
            f"Add-Content -Encoding UTF8 -Path {_ps(resultados)} -Value ({_ps(rotulo + '|')} + $c)")


def _linha_firewall(item):
    """Regra de entrada "bloquear" para o exe do app: sem ela, o Windows mostra à criança
    o alerta do firewall ("Permitir acesso"), que pede senha de administrador."""
    bases = ["$env:ProgramFiles", "${env:ProgramFiles(x86)}"]
    padroes = ", ".join(f"(Join-Path {b} {_ps(p)})" for p in item.get("exe", []) if "**" not in p for b in bases)
    nome = _ps(f"Benikids - {item.get('label', item['id'])}")
    return (f"foreach ($exe in @(Get-ChildItem -Path @({padroes}) -ErrorAction SilentlyContinue)) {{ "
            f"Remove-NetFirewallRule -DisplayName {nome} -ErrorAction SilentlyContinue; "
            f"New-NetFirewallRule -DisplayName {nome} -Direction Inbound -Action Block -Profile Any "
            f"-Program $exe.FullName | Out-Null; break }}")


def script_admin(pares, pasta):
    """O PowerShell do lote: dependências primeiro, depois cada app, anotando os códigos."""
    logs = os.path.join(pasta, "logs")
    resultados = os.path.join(pasta, "resultados.txt")
    linhas = ["$ErrorActionPreference = 'Continue'",
              f"New-Item -ItemType Directory -Force -Path {_ps(logs)} | Out-Null"]
    for item, arquivo in pares:
        for n, dep in enumerate(dependencias(arquivo)):
            linhas.append(_linha_instalar(f"{item['id']}-dependencia{n + 1}", dep, "", logs, resultados))
        linhas.append(_linha_instalar(item["id"], arquivo, tipo_do_instalador(item), logs, resultados))
        if item.get("firewall") == "bloquear":
            linhas.append(_linha_firewall(item))
    linhas.append(f"Add-Content -Encoding UTF8 -Path {_ps(resultados)} -Value 'fim|0'")
    return "\r\n".join(linhas) + "\r\n", resultados


def ler_resultados(caminho):
    """{rótulo: código} do arquivo que o lote vai escrevendo."""
    saida = {}
    try:
        with open(caminho, encoding="utf-8-sig") as f:
            for linha in f:
                rotulo, _, codigo = linha.strip().partition("|")
                if rotulo:
                    saida[rotulo] = codigo
    except OSError:
        pass
    return saida


CODIGOS_OK = {"0", "1641", "3010"}  # 1641/3010: instalou e pede para reiniciar


def instalar_como_admin(pares, pasta, ao_terminar_app=None):
    """Roda todos os instaladores "para todos" de uma vez, com um só pedido do UAC
    (a conta da criança não é administradora: o Windows pede a senha de um adulto).
    Enquanto o lote roda, avisa ao_terminar_app(id, código) a cada app que termina."""
    texto, resultados = script_admin(pares, pasta)
    try:
        os.remove(resultados)
    except OSError:
        pass
    script = os.path.join(pasta, "instalar-para-todos.ps1")
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write(texto)
    pedido = (
        "Start-Process powershell.exe -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "
        + _ps(f'-NoProfile -ExecutionPolicy Bypass -File "{script}"')
    )
    try:
        proc = subprocess.Popen(["powershell.exe", "-NoProfile", "-Command", pedido],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=SEM_CONSOLE)
    except OSError:
        return {}
    avisados = set()
    ids = {item["id"] for item, _ in pares}
    while True:
        terminou = proc.poll() is not None
        for rotulo, codigo in ler_resultados(resultados).items():
            if rotulo in ids and rotulo not in avisados:
                avisados.add(rotulo)
                if ao_terminar_app:
                    ao_terminar_app(rotulo, codigo)
        if terminou:
            break
        time.sleep(2)
    return ler_resultados(resultados)


def relatar_falha(item, codigo, pasta):
    """Relatório de problema (vai só com a telemetria ligada): o código e o fim do log."""
    log = os.path.join(pasta, "logs", f"{item['id']}.log")
    fim = ""
    try:
        with open(log, encoding="utf-16", errors="replace") as f:  # o msiexec grava em UTF-16
            fim = f.read()[-3000:]
    except (OSError, UnicodeError):
        try:
            with open(log, encoding="utf-8", errors="replace") as f:
                fim = f.read()[-3000:]
        except OSError:
            pass
    try:
        import telemetria

        telemetria.relatar_problema(
            "instalar_app",
            f"app={item['id']} winget={item.get('winget')} tipo={item.get('instalador', '')} código={codigo}\n{fim}",
            assinatura=f"instalar_app:{item['id']}:{codigo}",
        )
    except Exception:  # noqa: BLE001
        pass


def pasta_dos_instaladores():
    return os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Benikids", "instaladores")


DOWNLOADS_SIMULTANEOS = 2


def trabalhar(itens, avisos, pasta=None):
    """Instala tudo sem nunca parar a fila esperando o UAC:

    - os instaladores do lote com senha começam a baixar logo no início, em segundo
      plano (DOWNLOADS_SIMULTANEOS por vez), enquanto os apps sem senha instalam;
    - um app "por usuário" que falha sem administrador entra nesses downloads;
    - no fim, um só pedido de senha instala o lote todo, já baixado.
    """
    pasta = pasta or pasta_dos_instaladores()
    ja_pediram = pedem_senha()
    baixando = {}  # id → (item, futuro com o caminho do instalador), na ordem em que entraram
    junto = {}  # id do app que instala → outros apps do mesmo pacote
    trava = threading.Lock()
    baixador = ThreadPoolExecutor(max_workers=DOWNLOADS_SIMULTANEOS)

    def agendar(item):
        avisos.put((item["id"], "espera", "baixando para instalar no fim, com a senha..."))
        with trava:
            # mesmo pacote para dois apps (ex.: Neverball e Neverputt): baixa e instala uma vez
            for outro, futuro_existente in baixando.values():
                if pacote(outro) == pacote(item):
                    junto.setdefault(outro["id"], []).append(item)
                    return

        def baixado(futuro, item=item):
            try:
                arquivo = futuro.result()
            except Exception:  # noqa: BLE001 — um download com problema não derruba os outros
                arquivo = None
            if arquivo:
                avisos.put((item["id"], "espera", "baixado; instala no fim, com a senha"))
            else:
                avisos.put((item["id"], "erro", "não deu para baixar"))

        futuro = baixador.submit(baixar, item, pasta)
        futuro.add_done_callback(baixado)
        with trava:
            baixando[item["id"]] = (item, futuro)

    sem_senha = []
    for item in itens:
        if catalogo_windows.localizar(item):
            avisos.put((item["id"], "ja", "já estava instalado"))
        elif item.get("baixar"):
            avisos.put((item["id"], "instalando", "baixando..."))
            ok, texto = baixar_direto(item)
            if ok and not catalogo_windows.localizar(item):
                ok, texto = False, "baixou, mas não achei o programa"
            avisos.put((item["id"], "ok" if ok else "erro", texto))
        elif not item.get("winget") and not item.get("pagina"):
            avisos.put((item["id"], "erro", "sem instalador automático"))
        elif precisa_de_senha(item, ja_pediram):
            agendar(item)
        else:
            sem_senha.append(item)

    for item in sem_senha:
        if catalogo_windows.localizar(item):  # veio junto com outro app do mesmo pacote
            avisos.put((item["id"], "ok", "instalado"))
            continue
        avisos.put((item["id"], "instalando", "instalando..."))

        def pediu_senha(item=item):
            lembrar_que_pede_senha(item["id"])
            avisos.put((item["id"], "instalando", "o Windows pediu a senha de um adulto"))

        ok, texto = instalar(item, pediu_senha)
        if ok:
            avisos.put((item["id"], "ok", texto))
        else:
            # sem administrador não deu: vai para o lote com senha, no fim
            lembrar_que_pede_senha(item["id"])
            agendar(item)

    baixador.shutdown(wait=True)
    pares = []
    for item, futuro in baixando.values():
        try:
            arquivo = futuro.result()
        except Exception:  # noqa: BLE001
            arquivo = None
        if arquivo:
            pares.append((item, arquivo))
    if pares:
        for item, _arquivo in pares:
            avisos.put((item["id"], "instalando", "instala depois da senha"))
        avisos.put((None, "admin", ""))
        por_id = {item["id"]: item for item, _ in pares}

        def terminou(item_id, codigo):
            for outro in junto.get(item_id, []):
                achou = bool(catalogo_windows.localizar(outro))
                avisos.put((outro["id"], "ok" if achou else "erro",
                            "instalado" if achou else "instalou, mas não achei o programa"))
            ok = bool(catalogo_windows.localizar(por_id[item_id]))
            if ok:
                avisos.put((item_id, "ok", "instalado"))
                return
            if codigo in CODIGOS_OK:
                # o instalador disse que deu certo, mas o programa não está onde o catálogo procura
                avisos.put((item_id, "erro", "instalou, mas não achei o programa"))
                relatar_falha(por_id[item_id], f"{codigo} (instalou; exe não encontrado)", pasta)
            else:
                avisos.put((item_id, "erro", f"não instalou (código {codigo})"))
                relatar_falha(por_id[item_id], codigo, pasta)

        codigos = instalar_como_admin(pares, pasta, terminou)
        if "fim" not in codigos and not any(i in codigos for i in por_id):
            avisos.put((None, "sem_senha", ""))  # o adulto não digitou a senha (ou cancelou)
        for item, _arquivo in pares:
            if item["id"] not in codigos:
                ok = bool(catalogo_windows.localizar(item))
                avisos.put((item["id"], "ok" if ok else "erro", "instalado" if ok else "não instalou"))
    avisos.put((None, "fim", ""))


def janela(itens):
    import tkinter as tk

    raiz = tk.Tk()
    raiz.title("Benikids: instalando jogos e programas")
    # cores da marca (site/style.css): fundo céu suave, títulos marinho, botão azul
    raiz.configure(bg=marca.CEU_SUAVE)
    marca.por_icone(raiz)
    marca.fonte_titulo(raiz)
    corpo = marca.FONTE_CORPO
    raiz.geometry("640x680")
    # a área dos pais está em tela cheia (navegador em modo quiosque): sem isto a janela
    # abre atrás dela e o adulto não vê o andamento
    raiz.attributes("-topmost", True)
    raiz.after(200, lambda: (raiz.lift(), raiz.focus_force()))
    tk.Label(raiz, text="Instalando os jogos e programas", font=marca.titulo(20),
             bg=marca.CEU_SUAVE, fg=marca.MARINHO).pack(pady=(18, 2))
    tk.Label(raiz, text="Pode levar alguns minutos. Dá para usar o computador enquanto isso.",
             font=(corpo, 11), bg=marca.CEU_SUAVE, fg=marca.APAGADO).pack(pady=(0, 10))
    # botão e aviso presos embaixo, antes da lista: com muitos apps a lista é maior que a
    # janela, e o "Concluir" não pode sumir (no pacote 8 foi preciso fechar pelo X)
    botao = tk.Button(raiz, text="Aguarde...", font=(corpo, 12, "bold"), state=tk.DISABLED,
                      command=raiz.destroy, padx=24, pady=6, relief=tk.FLAT, bd=0,
                      bg=marca.BORDA, disabledforeground=marca.APAGADO)
    botao.pack(side=tk.BOTTOM, pady=(0, 16))
    rodape = tk.Label(raiz, text="", font=(corpo, 12, "bold"), bg=marca.CEU_SUAVE, fg=marca.MARINHO)
    rodape.pack(side=tk.BOTTOM, pady=8)
    # a lista rola (barra e roda do mouse)
    caixa = tk.Frame(raiz, bg=marca.SUPERFICIE, highlightthickness=1, highlightbackground=marca.BORDA)
    caixa.pack(fill=tk.BOTH, expand=True, padx=18)
    tela = tk.Canvas(caixa, bg="#ffffff", highlightthickness=0)
    barra = tk.Scrollbar(caixa, orient=tk.VERTICAL, command=tela.yview)
    tela.configure(yscrollcommand=barra.set)
    barra.pack(side=tk.RIGHT, fill=tk.Y)
    tela.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    quadro = tk.Frame(tela, bg="#ffffff", padx=14, pady=10)
    janela_lista = tela.create_window((0, 0), window=quadro, anchor="nw")
    quadro.bind("<Configure>", lambda _e: tela.configure(scrollregion=tela.bbox("all")))
    tela.bind("<Configure>", lambda e: tela.itemconfigure(janela_lista, width=e.width))
    raiz.bind_all("<MouseWheel>", lambda e: tela.yview_scroll(int(-e.delta / 120), "units"))
    linhas = {}
    for item in itens:
        linha = tk.Frame(quadro, bg="#ffffff")
        linha.pack(fill=tk.X, pady=2)
        estado = tk.Label(linha, text=ICONES["espera"], font=("Segoe UI Emoji", 13), bg="#ffffff", width=3)
        estado.pack(side=tk.LEFT)
        # o emoji numa coluna própria, de largura fixa: alguns (🏎️) são mais largos
        tk.Label(linha, text=item.get("emoji", ""), font=("Segoe UI Emoji", 13), bg="#ffffff",
                 width=3).pack(side=tk.LEFT)
        tk.Label(linha, text=item["label"], font=(corpo, 12), bg="#ffffff", fg=marca.TEXTO,
                 anchor="w").pack(side=tk.LEFT)
        detalhe = tk.Label(linha, text="", font=(corpo, 10), bg="#ffffff", fg=marca.APAGADO, anchor="e")
        detalhe.pack(side=tk.RIGHT)
        linhas[item["id"]] = (estado, detalhe)

    avisos = queue.Queue()
    threading.Thread(target=trabalhar, args=(itens, avisos), daemon=True).start()
    erros = []

    def olhar():
        try:
            while True:
                item_id, estado, texto = avisos.get_nowait()
                if item_id is None and estado == "admin":
                    rodape.config(text="Agora o Windows pede a senha de um administrador do computador,\n"
                                       "uma vez só, para instalar os que faltam.")
                    raiz.lift()
                    continue
                if item_id is None and estado == "sem_senha":
                    rodape.config(text="A senha não foi digitada: os apps marcados ficam para depois.")
                    continue
                if item_id is None:
                    rodape.config(text="Pronto! Tudo instalado." if not erros else
                                  f"Pronto. {len(erros)} não instalaram: dá para tentar de novo na área dos pais.")
                    botao.config(text="Concluir", state=tk.NORMAL, bg=marca.AZUL, fg="#ffffff",
                                 activebackground=marca.AZUL_ESCURO, activeforeground="#ffffff",
                                 cursor="hand2")
                    raiz.protocol("WM_DELETE_WINDOW", raiz.destroy)
                    raiz.lift()
                    botao.focus_set()
                    return
                if estado == "erro":
                    erros.append(item_id)
                icone, detalhe = linhas[item_id]
                icone.config(text=ICONES[estado])
                detalhe.config(text=texto)
        except queue.Empty:
            pass
        raiz.after(300, olhar)

    raiz.after(300, olhar)
    raiz.mainloop()
    return 0 if not erros else 1


def main(ids):
    itens = catalogo_windows.carregar()
    if ids:
        itens = [i for i in itens if i["id"] in ids]
    if not itens:
        return 0
    return janela(itens)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
