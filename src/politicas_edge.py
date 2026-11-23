"""Políticas do Edge no Windows: bloqueador de anúncios e bloqueio de páginas.

O que o Firefox dos sites tem no Linux (beni/firefox/policies.json), no Edge:
- uBlock Origin Lite (MV3) instalado à força pela loja do Edge: num Windows fora
  de domínio a instalação forçada só aceita a loja do Edge, e o uBlock Origin
  (MV2) está sendo desligado no Edge;
- a configuração do uBOL pela política de extensão ("3rdparty"): filtragem
  "complete", a lista de avisos de cookies e sem a página de boas-vindas;
- URLBlocklist com as mesmas páginas bloqueadas do Linux;
- TranslateEnabled=0 (sem o "Traduzir esta página");
- PasswordManagerEnabled=0 (sem salvar nem preencher senhas).

Fica em HKLM\\SOFTWARE\\Policies\\Microsoft\\Edge: vale para o Edge inteiro do
computador (o mantenedor confirmou que só o Benikids usa o Edge) e precisa de
administrador. Por isso o instalar_apps.py põe estas linhas no lote que já pede
o UAC uma vez. As listas do Edge são valores numerados (1, 2, 3...) e o Edge
para de ler no primeiro número que falta: aplicar e desfazer mexem só nos
nossos valores, mantêm os dos outros e renumeram sem buracos.

Desfazer (não há desinstalador no Windows): `python politicas_edge.py desfazer`
pede o UAC e tira só o que o Benikids pôs.
"""

import os
import subprocess
import sys
import tempfile

RAIZ = r"HKLM:\SOFTWARE\Policies\Microsoft\Edge"
RAIZ_WINREG = r"SOFTWARE\Policies\Microsoft\Edge"
SEP = "\\"

UBOL_ID = "cimighlppcgcoapaliogpjjdehbnofhn"  # uBlock Origin Lite na loja do Edge
LOJA_EDGE = "https://edge.microsoft.com/extensionwebstorebase/v1/crx"
UBOL_FORCELIST = f"{UBOL_ID};{LOJA_EDGE}"

# Formato do URLBlocklist: "dominio/caminho" pega o domínio, os subdomínios
# (www.) e tudo o que começa com o caminho. Mesmas páginas do WebsiteFilter do
# Firefox no Linux; o teste confere que as duas listas não se separam.
URLS_BLOQUEADAS = (
    # Escola Games: o menu "Jogos" e "Jogos em inglês" (os educativos ficam)
    "escolagames.com.br/jogos-divertidos",
    "escolagames.com.br/diversao/",
    "bestschoolgames.com",
    # Colorir: só a parte de colorir
    "colorir-online.com/apps",
    "colorir-online.com/quem-somos",
)

# Escola Games: o jogo só abre sem anúncio quando o script do Google FALHA. Se
# o uBOL o trocar por um falso (como o uBlock fazia no Linux) e o jogo travar
# em "Loading…", ligue isto: o uBOL deixa o site em paz e o bloqueio fica com o
# --host-resolver-rules do comando do Edge (application_launcher.py).
# Ligado: no Windows real (Edge 157) o uBOL travava os jogos e a home ficava só com
# o esqueleto; sem filtro, os jogos rodam e os anúncios continuam barrados.
ESCOLA_GAMES_SEM_FILTRO = True

# Valores simples na raiz das políticas do Edge: {nome: (tipo, valor)}.
# TranslateEnabled=0: sem a barra/ícone "Traduzir esta página" e sem o
# oferecimento automático. O perfil de cada criança também leva
# translate.enabled=false (application_launcher.py), que não pede administrador.
# PasswordManagerEnabled=0: o Edge não salva nem preenche senhas (o login dos
# sites é o automático, por criança). Não apaga as senhas já salvas.
# PromptForDownloadLocation=0: o Edge não pergunta a pasta (como o Firefox do Linux,
# browser.download.useDownloadDir). A pasta em si é por criança, no HKCU: o lote
# com UAC roda como o administrador, e a pasta Imagens de quem joga é outra.
VALORES_RAIZ = {
    "TranslateEnabled": ("DWord", 0),
    "PasswordManagerEnabled": ("DWord", 0),
    "PromptForDownloadLocation": ("DWord", 0),
}
RAIZ_USUARIO = r"SOFTWARE\Policies\Microsoft\Edge"
SEM_FILTRO = ("escolagames.com.br",)


def pasta_imagens():
    """A pasta Imagens do usuário. No Windows o caminho real costuma ser Pictures
    (o nome Imagens é o que o Explorer mostra)."""
    if os.name != "nt":
        return os.path.join(os.path.expanduser("~"), "Imagens")
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        ole32 = ctypes.WinDLL("ole32")
        shell32 = ctypes.WinDLL("shell32")
        ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(GUID)]
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
        shell32.SHGetKnownFolderPath.restype = ctypes.HRESULT
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        guid = GUID()
        # FOLDERID_Pictures
        if ole32.CLSIDFromString("{33E28130-4E1E-4676-835A-98395C3BC3BB}", ctypes.byref(guid)) == 0:
            ptr = ctypes.c_void_p()
            if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(ptr)) == 0 and ptr:
                caminho = ctypes.wstring_at(ptr)
                ole32.CoTaskMemFree(ptr)
                if caminho:
                    return caminho
    except (OSError, AttributeError, ValueError):
        pass
    return os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), "Pictures")


def pasta_desenhos(imagens):
    """Imagens\\Desenhos, onde o Kleki (e os outros sites) salvam o desenho."""
    return os.path.join(imagens, "Desenhos")


def preferencias_downloads(pasta):
    """Preferências do perfil do Edge, o equivalente ao user.js do Firefox.

    O painel de downloads não tem política no Edge (o Firefox usa
    browser.download.alwaysOpenPanel). download_bubble.partial_view_enabled
    é a preferência do perfil que deixa esse menu fechado.
    """
    return {
        "download": {"prompt_for_download": False, "default_directory": pasta},
        "download_bubble": {"partial_view_enabled": False},
    }


def gravar_politica_de_desenhos(pasta, winreg=None):
    """HKCU do usuário atual: baixa em `pasta` sem perguntar. Não precisa de UAC.

    Devolve True se gravou. Fora do Windows, False (a preferência do perfil cobre).
    """
    if winreg is None:
        if os.name != "nt":
            return False
        import winreg  # noqa: PLC0415
    try:
        os.makedirs(pasta, exist_ok=True)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RAIZ_USUARIO) as chave:
            winreg.SetValueEx(chave, "DownloadDirectory", 0, winreg.REG_SZ, pasta)
            winreg.SetValueEx(chave, "PromptForDownloadLocation", 0, winreg.REG_DWORD, 0)
    except OSError:
        return False
    return True


def url_do_firefox(padrao):
    """Padrão do WebsiteFilter do Firefox → formato do URLBlocklist do Edge."""
    url = padrao.split("://", 1)[-1]
    if url.startswith("www."):
        url = url[4:]
    url = url.rstrip("*")
    return url[:-1] if url.endswith("/") and url.count("/") == 1 else url


# Avisos de cookies ("Aceitar cookies"): a lista "EasyList/uBO – Cookie Notices"
# do uBOL (desligada de fábrica) esconde o aviso ou recusa o opcional; não aceita
# cookies por nós. No uBOL cada item precisa do "+" (sem ele é ignorado) e soma
# às listas padrão, que continuam ligadas.
UBOL_RULESETS = ("+annoyances-cookies",)

# "complete": as regras gerais de aparência (esconder o aviso em qualquer site)
# só valem nesse modo; no "optimal" ficam só as regras de cada site, e os sites
# infantis brasileiros quase nunca têm regra própria. Se pesar no notebook
# antigo ou quebrar um jogo, volte para "optimal" (os avisos de sites grandes
# continuam sumindo).
UBOL_MODO = "complete"


def politica_ubol(sem_filtro=ESCOLA_GAMES_SEM_FILTRO):
    """Valores da política do uBOL (managed storage): {nome: (tipo, valor)}."""
    valores = {
        "defaultFiltering": ("String", UBOL_MODO),
        "disableFirstRunPage": ("DWord", 1),
        "rulesets": ("Lista", list(UBOL_RULESETS)),
    }
    if sem_filtro:
        valores["noFiltering"] = ("Lista", list(SEM_FILTRO))
    return valores


def _ps(texto):
    return "'" + str(texto).replace("'", "''") + "'"


def _lista_ps(itens):
    return "@(" + ", ".join(_ps(i) for i in itens) + ")"


# Funções do PowerShell usadas pelos dois scripts. "Get-Item ... .Property" lista
# os nomes dos valores; New-Item -Force numa chave que já existe a recriaria
# vazia, por isso só cria quando falta.
#
# Cuidado com o pipeline: Benikids-Ler devolve os valores um por um (sem o
# "return ,$lista", que mandaria a lista inteira como UM objeto e faria o
# Where-Object comparar o array todo — foi o que juntou o URLBlocklist num valor
# só e apagou valores de terceiros no teste do Windows). Quem chama sempre
# embrulha em @(...) para ter um array mesmo com zero ou um valor, e valores
# vazios são descartados.
_FUNCOES = r"""
function Benikids-Chave($k) { if (-not (Test-Path $k)) { New-Item -Path $k -Force | Out-Null } }
function Benikids-Numerados($k) {
  $chave = Get-Item -Path $k
  return @(@($chave.Property) | Where-Object { "$_" -match '^\d+$' } | Sort-Object { [int]$_ })
}
function Benikids-Ler($k) {
  if (-not (Test-Path $k)) { return }
  $chave = Get-Item -Path $k
  foreach ($n in (Benikids-Numerados $k)) {
    $v = [string]$chave.GetValue($n)
    if ($v -ne '') { $v }
  }
}
function Benikids-Gravar($k, $itens) {
  Benikids-Chave $k
  foreach ($n in (Benikids-Numerados $k)) { Remove-ItemProperty -Path $k -Name $n }
  $i = 1
  foreach ($v in @($itens)) {
    if ([string]$v -eq '') { continue }
    New-ItemProperty -Path $k -Name "$i" -Value ([string]$v) -PropertyType String -Force | Out-Null
    $i++
  }
}
function Benikids-Nossos($v, $nossos, $prefixo) {
  $v = [string]$v
  return ($nossos -contains $v) -or ($prefixo -and $v.StartsWith($prefixo))
}
function Benikids-Por($k, $nossos, $prefixo) {
  $lidos = @(Benikids-Ler $k)
  $outros = @($lidos | Where-Object { $_ -and -not (Benikids-Nossos $_ $nossos $prefixo) })
  Benikids-Gravar $k ($outros + @($nossos))
}
function Benikids-Tirar($k, $nossos, $prefixo) {
  if (-not (Test-Path $k)) { return }
  $lidos = @(Benikids-Ler $k)
  $outros = @($lidos | Where-Object { $_ -and -not (Benikids-Nossos $_ $nossos $prefixo) })
  Benikids-Gravar $k $outros
  $chave = Get-Item -Path $k
  if ($outros.Count -eq 0 -and $chave.SubKeyCount -eq 0 -and $chave.ValueCount -eq 0) { Remove-Item -Path $k }
}
"""


def _chave_extensao():
    return RAIZ + "\\3rdparty\\extensions\\" + UBOL_ID


def _chave_ubol():
    return _chave_extensao() + "\\policy"


def script_aplicar(sem_filtro=ESCOLA_GAMES_SEM_FILTRO):
    """Linhas do PowerShell (como administrador) que põem as políticas. Idempotente."""
    linhas = [_FUNCOES.strip()]
    linhas.append(
        f"Benikids-Por {_ps(RAIZ + SEP + 'ExtensionInstallForcelist')} "
        f"{_lista_ps([UBOL_FORCELIST])} {_ps(UBOL_ID + ';')}"
    )
    linhas.append(f"Benikids-Por {_ps(RAIZ + SEP + 'URLBlocklist')} {_lista_ps(URLS_BLOQUEADAS)} ''")
    linhas.append(f"Benikids-Chave {_ps(RAIZ)}")
    for nome, (tipo, valor) in VALORES_RAIZ.items():
        linhas.append(
            f"New-ItemProperty -Path {_ps(RAIZ)} -Name {_ps(nome)} -Value {valor} -PropertyType {tipo} -Force | Out-Null"
        )
    chave = _chave_ubol()
    linhas.append(f"Benikids-Chave {_ps(chave)}")
    for nome, (tipo, valor) in politica_ubol(sem_filtro).items():
        if tipo == "Lista":
            linhas.append(f"Benikids-Gravar {_ps(chave + SEP + nome)} {_lista_ps(valor)}")
        else:
            linhas.append(
                f"New-ItemProperty -Path {_ps(chave)} -Name {_ps(nome)} -Value {_ps(valor) if tipo == 'String' else valor} "
                f"-PropertyType {tipo} -Force | Out-Null"
            )
    if "noFiltering" not in politica_ubol(sem_filtro):
        linhas.append(f"Remove-Item -Path {_ps(chave + SEP + 'noFiltering')} -Recurse -ErrorAction SilentlyContinue")
    return linhas


def script_desfazer():
    """Linhas do PowerShell (como administrador) que tiram só o que o Benikids pôs."""
    return [
        _FUNCOES.strip(),
        f"Benikids-Tirar {_ps(RAIZ + SEP + 'ExtensionInstallForcelist')} "
        f"{_lista_ps([UBOL_FORCELIST])} {_ps(UBOL_ID + ';')}",
        f"Benikids-Tirar {_ps(RAIZ + SEP + 'URLBlocklist')} {_lista_ps(URLS_BLOQUEADAS)} ''",
        # a política do uBOL é toda nossa
        f"Remove-Item -Path {_ps(_chave_extensao())} -Recurse -ErrorAction SilentlyContinue",
    ] + [
        f"Remove-ItemProperty -Path {_ps(RAIZ)} -Name {_ps(nome)} -ErrorAction SilentlyContinue"
        for nome in VALORES_RAIZ
    ]


# ---------------------------------------------------------- leitura (sem admin)

def _ler_lista(winreg, caminho):
    try:
        chave = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, caminho)
    except OSError:
        return []
    itens = {}
    with chave:
        i = 0
        while True:
            try:
                nome, valor, _tipo = winreg.EnumValue(chave, i)
            except OSError:
                break
            if nome.isdigit():
                itens[int(nome)] = str(valor)
            i += 1
    # o Edge para no primeiro número que falta
    saida, n = [], 1
    while n in itens:
        saida.append(itens[n])
        n += 1
    return saida


def _ler_valor(winreg, caminho, nome):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, caminho) as chave:
            return winreg.QueryValueEx(chave, nome)[0]
    except OSError:
        return None


def faltam(sem_filtro=ESCOLA_GAMES_SEM_FILTRO, winreg=None):
    """True se alguma política do Benikids não está no registro (aí o lote com UAC as põe).

    Ler o HKLM não precisa de administrador. Fora do Windows: False.
    """
    if winreg is None:
        if os.name != "nt":
            return False
        import winreg  # noqa: PLC0415 — só existe no Windows
    if UBOL_FORCELIST not in _ler_lista(winreg, RAIZ_WINREG + r"\ExtensionInstallForcelist"):
        return True
    if not set(URLS_BLOQUEADAS) <= set(_ler_lista(winreg, RAIZ_WINREG + r"\URLBlocklist")):
        return True
    for nome, (_tipo, valor) in VALORES_RAIZ.items():
        if _ler_valor(winreg, RAIZ_WINREG, nome) != valor:
            return True
    chave = rf"{RAIZ_WINREG}\3rdparty\extensions\{UBOL_ID}\policy"
    for nome, (tipo, valor) in politica_ubol(sem_filtro).items():
        if tipo == "Lista":
            if _ler_lista(winreg, chave + SEP + nome) != list(valor):
                return True
        elif _ler_valor(winreg, chave, nome) != valor:
            return True
    if not sem_filtro and _ler_lista(winreg, chave + r"\noFiltering"):
        return True
    return False


# ------------------------------------------------------------------- linha de comando

def rodar_como_admin(linhas):
    """Roda as linhas num PowerShell com UAC e espera. Devolve True se terminou."""
    pasta = tempfile.mkdtemp(prefix="benikids-edge-")
    script = os.path.join(pasta, "politicas-edge.ps1")
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write("$ErrorActionPreference = 'Stop'\r\n" + "\r\n".join(linhas) + "\r\n")
    pedido = (
        "$p = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList "
        + _ps(f'-NoProfile -ExecutionPolicy Bypass -File "{script}"')
        + "; exit $p.ExitCode"
    )
    resultado = subprocess.run(["powershell.exe", "-NoProfile", "-Command", pedido], check=False)
    return resultado.returncode == 0


def main(args):
    if os.name != "nt" or not args or args[0] not in ("aplicar", "desfazer"):
        print("uso (Windows): politicas_edge.py aplicar [--escolagames-sem-filtro] | desfazer")
        return 2
    if args[0] == "desfazer":
        linhas = script_desfazer()
    else:
        linhas = script_aplicar("--escolagames-sem-filtro" in args or ESCOLA_GAMES_SEM_FILTRO)
    ok = rodar_como_admin(linhas)
    print("pronto" if ok else "não terminou (senha cancelada ou erro)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
