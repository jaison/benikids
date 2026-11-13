"""Instala (pelo winget) os apps do catálogo do Windows que ainda faltam.

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import catalogo_windows  # noqa: E402

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


def baixar(item, pasta):
    """winget download (não precisa de administrador). Devolve o arquivo do instalador."""
    destino = os.path.join(pasta, item["id"])
    os.makedirs(destino, exist_ok=True)
    argv = [
        winget(), "download", "--id", item["winget"], "--exact", "--download-directory", destino,
        "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity",
        "--scope", "machine",
    ]
    try:
        subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=SEM_CONSOLE, timeout=1800)
    except (OSError, subprocess.TimeoutExpired):
        return None
    arquivos = [os.path.join(destino, n) for n in os.listdir(destino)
                if n.lower().endswith((".msi", ".exe"))]
    return max(arquivos, key=os.path.getmtime) if arquivos else None


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


def instalar_como_admin(pares, pasta):
    """Roda todos os instaladores "para todos" de uma vez, com um só pedido do UAC
    (a conta da criança não é administradora: o Windows pede a senha de um adulto)."""
    linhas = ["$ErrorActionPreference = 'Continue'"]
    for item, arquivo in pares:
        tipo = tipo_do_instalador(item)
        if tipo in ("msi", "wix") or arquivo.lower().endswith(".msi"):
            linhas.append(f"Start-Process msiexec.exe -Wait -ArgumentList @('/i', '\"' + {_ps(arquivo)} + '\"', '/qn', '/norestart')")
        else:
            args = ", ".join(_ps(a) for a in SILENCIOSO.get(tipo) or ["/S"])
            linhas.append(f"Start-Process -FilePath {_ps(arquivo)} -Wait -ArgumentList @({args})")
    script = os.path.join(pasta, "instalar-para-todos.ps1")
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write("\r\n".join(linhas) + "\r\n")
    pedido = (
        "Start-Process powershell.exe -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "
        f"@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', '\"' + {_ps(script)} + '\"')"
    )
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", pedido], capture_output=True,
                           creationflags=SEM_CONSOLE, timeout=3600)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def trabalhar(itens, avisos):
    """Primeiro tudo o que instala sem senha, sem nunca parar a fila esperando o UAC;
    no fim, um só pedido de senha para todos os que precisam de administrador."""
    para_todos = []
    ja_pediram = pedem_senha()
    for item in itens:
        if catalogo_windows.localizar(item):
            avisos.put((item["id"], "ja", "já estava instalado"))
            continue
        if not item.get("winget"):
            avisos.put((item["id"], "erro", "sem instalador automático"))
            continue
        if precisa_de_senha(item, ja_pediram):
            avisos.put((item["id"], "espera", "no fim, com a senha"))
            para_todos.append(item)
            continue
        avisos.put((item["id"], "instalando", "instalando..."))

        def pediu_senha(item=item):
            lembrar_que_pede_senha(item["id"])
            avisos.put((item["id"], "instalando", "o Windows pediu a senha de um adulto"))

        ok, texto = instalar(item, pediu_senha)
        if ok:
            avisos.put((item["id"], "ok", texto))
        else:
            # sem administrador não deu: tenta de novo no lote com senha, no fim
            lembrar_que_pede_senha(item["id"])
            avisos.put((item["id"], "espera", "no fim, com a senha"))
            para_todos.append(item)
    if para_todos:
        pasta = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Benikids", "instaladores")
        pares = []
        for item in para_todos:
            avisos.put((item["id"], "instalando", "baixando..."))
            arquivo = baixar(item, pasta)
            if arquivo:
                pares.append((item, arquivo))
                avisos.put((item["id"], "instalando", "esperando a senha do adulto..."))
            else:
                avisos.put((item["id"], "erro", "não deu para baixar"))
        if pares:
            avisos.put((None, "admin", ""))
            instalar_como_admin(pares, pasta)
            for item, _arquivo in pares:
                ok = bool(catalogo_windows.localizar(item))
                avisos.put((item["id"], "ok" if ok else "erro", "instalado" if ok else "não instalou"))
    avisos.put((None, "fim", ""))


def janela(itens):
    import tkinter as tk

    raiz = tk.Tk()
    raiz.title("Benikids: instalando jogos e programas")
    raiz.configure(bg="#f3f0ff")
    raiz.geometry("620x560")
    tk.Label(raiz, text="Instalando os jogos e programas", font=("Segoe UI", 18, "bold"),
             bg="#f3f0ff", fg="#2d2a3e").pack(pady=(18, 2))
    tk.Label(raiz, text="Pode levar alguns minutos. Dá para usar o computador enquanto isso.",
             font=("Segoe UI", 11), bg="#f3f0ff", fg="#6b6880").pack(pady=(0, 10))
    quadro = tk.Frame(raiz, bg="#ffffff", padx=14, pady=10)
    quadro.pack(fill=tk.BOTH, expand=True, padx=18)
    linhas = {}
    for item in itens:
        linha = tk.Frame(quadro, bg="#ffffff")
        linha.pack(fill=tk.X, pady=2)
        estado = tk.Label(linha, text=ICONES["espera"], font=("Segoe UI Emoji", 13), bg="#ffffff", width=3)
        estado.pack(side=tk.LEFT)
        tk.Label(linha, text=f"{item.get('emoji', '')} {item['label']}", font=("Segoe UI", 12),
                 bg="#ffffff", anchor="w").pack(side=tk.LEFT)
        detalhe = tk.Label(linha, text="", font=("Segoe UI", 10), bg="#ffffff", fg="#6b6880", anchor="e")
        detalhe.pack(side=tk.RIGHT)
        linhas[item["id"]] = (estado, detalhe)
    rodape = tk.Label(raiz, text="", font=("Segoe UI", 12, "bold"), bg="#f3f0ff", fg="#2d2a3e")
    rodape.pack(pady=8)
    botao = tk.Button(raiz, text="Fechar", font=("Segoe UI", 12), state=tk.DISABLED, command=raiz.destroy)
    botao.pack(pady=(0, 16))

    avisos = queue.Queue()
    threading.Thread(target=trabalhar, args=(itens, avisos), daemon=True).start()
    erros = []

    def olhar():
        try:
            while True:
                item_id, estado, texto = avisos.get_nowait()
                if item_id is None and estado == "admin":
                    rodape.config(text="Alguns precisam de um adulto: o Windows vai pedir a senha de administrador.")
                    continue
                if item_id is None:
                    rodape.config(text="Pronto!" if not erros else
                                  f"Pronto. {len(erros)} não instalaram; tente de novo pela área dos pais.")
                    botao.config(state=tk.NORMAL)
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
