"""Políticas do Edge no Windows: bloqueador de anúncios e bloqueio de páginas.

O que o Firefox dos sites tem no Linux (beni/firefox/policies.json), no Edge:
- uBlock Origin Lite (MV3) instalado à força pela loja do Edge: num Windows fora
  de domínio a instalação forçada só aceita a loja do Edge, e o uBlock Origin
  (MV2) está sendo desligado no Edge;
- a configuração do uBOL pela política de extensão ("3rdparty"): filtragem
  "optimal" e sem a página de boas-vindas;
- URLBlocklist com as mesmas páginas bloqueadas do Linux.

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
ESCOLA_GAMES_SEM_FILTRO = False
SEM_FILTRO = ("escolagames.com.br",)


def url_do_firefox(padrao):
    """Padrão do WebsiteFilter do Firefox → formato do URLBlocklist do Edge."""
    url = padrao.split("://", 1)[-1]
    if url.startswith("www."):
        url = url[4:]
    url = url.rstrip("*")
    return url[:-1] if url.endswith("/") and url.count("/") == 1 else url


def politica_ubol(sem_filtro=ESCOLA_GAMES_SEM_FILTRO):
    """Valores da política do uBOL (managed storage): {nome: (tipo, valor)}."""
    valores = {
        "defaultFiltering": ("String", "optimal"),
        "disableFirstRunPage": ("DWord", 1),
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
_FUNCOES = r"""
function Benikids-Chave($k) { if (-not (Test-Path $k)) { New-Item -Path $k -Force | Out-Null } }
function Benikids-Ler($k) {
  $itens = @()
  if (Test-Path $k) {
    $chave = Get-Item -Path $k
    $nomes = @($chave.Property | Where-Object { $_ -match '^\d+$' } | Sort-Object { [int]$_ })
    foreach ($n in $nomes) { $itens += [string]$chave.GetValue($n) }
  }
  return ,$itens
}
function Benikids-Gravar($k, $itens) {
  Benikids-Chave $k
  $chave = Get-Item -Path $k
  foreach ($n in @($chave.Property | Where-Object { $_ -match '^\d+$' })) { Remove-ItemProperty -Path $k -Name $n }
  $i = 1
  foreach ($v in $itens) { New-ItemProperty -Path $k -Name "$i" -Value $v -PropertyType String -Force | Out-Null; $i++ }
}
function Benikids-Nossos($v, $nossos, $prefixo) {
  return ($nossos -contains $v) -or ($prefixo -and $v.StartsWith($prefixo))
}
function Benikids-Por($k, $nossos, $prefixo) {
  $outros = @(Benikids-Ler $k | Where-Object { -not (Benikids-Nossos $_ $nossos $prefixo) })
  Benikids-Gravar $k ($outros + $nossos)
}
function Benikids-Tirar($k, $nossos, $prefixo) {
  if (-not (Test-Path $k)) { return }
  $outros = @(Benikids-Ler $k | Where-Object { -not (Benikids-Nossos $_ $nossos $prefixo) })
  Benikids-Gravar $k $outros
  $chave = Get-Item -Path $k
  if ($outros.Count -eq 0 -and $chave.SubKeyCount -eq 0) { Remove-Item -Path $k }
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
